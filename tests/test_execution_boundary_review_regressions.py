from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path, PurePosixPath
from typing import Callable
from urllib.parse import parse_qs, unquote, urlsplit

from kora.execution import (
    CoordinatorStatus,
    ExecutionCoordinator,
    ExecutionValidationError,
    MappingRuntimeResolver,
    MappingTaskSpecProvider,
    PermissionRequirement,
    TaskExecutionSpec,
)
from kora.mission import (
    ArtifactKind,
    AttemptStatus,
    EscalationStatus,
    EvidenceKind,
    MissionService,
    MissionState,
    PermissionAction,
    PermissionMode,
    Task,
    TaskStatus,
)
from kora.runtime import (
    Capability,
    IsolationMode,
    RuntimeJob,
    RuntimeResult,
    RuntimeStatus,
)
from kora.verification import (
    VerificationArtifact,
    WorkspaceVerificationRequest,
    WorkspaceVerificationResult,
)
from kora.workforce import (
    ModelRoute,
    ModelRouter,
    PrivacyLevel,
    RoleCharter,
    TaskProfile,
    WorkforceCompiler,
)


PRIVATE_MARKERS = (
    "provider-secret-9",
    "model-secret-9",
    "route-secret-9",
    "prompt-secret-9",
    "token-secret-9",
    "worker-secret-9",
    "harness-secret-9",
)
PRIVATE_FIELD_MARKERS = (
    "provider_ref=",
    "model_ref=",
    "route_id=",
    "prompt=",
    "total_tokens=",
    "worker_role_id=",
    "harness_secret=",
)
ALL_PRIVATE_MARKERS = PRIVATE_MARKERS + PRIVATE_FIELD_MARKERS
PRIVATE_RUNTIME_TEXT = (
    "provider_ref=provider-secret-9 model_ref=model-secret-9 "
    "route_id=route-secret-9 prompt=prompt-secret-9 "
    "total_tokens=token-secret-9 worker_role_id=worker-secret-9 "
    "harness_secret=harness-secret-9"
)
SAFE_FINGERPRINT = "a" * 64


class RecordingRuntime:
    """Deterministic runtime fake with optional writes and run-time probes."""

    def __init__(
        self,
        *outcomes: RuntimeResult | BaseException,
        writes: tuple[tuple[str, str], ...] = (),
        on_run: Callable[[RuntimeJob], None] | None = None,
    ) -> None:
        self.outcomes = list(outcomes)
        self.writes = writes
        self.on_run = on_run
        self.calls: list[RuntimeJob] = []

    def run(self, job: RuntimeJob) -> RuntimeResult:
        self.calls.append(job)
        if self.on_run is not None:
            self.on_run(job)
        for relative_path, contents in self.writes:
            destination = job.workspace / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(contents, encoding="utf-8")
        outcome = self.outcomes.pop(0) if self.outcomes else RuntimeResult(
            mission_id=job.mission_id,
            task_id=job.task_id,
            status=RuntimeStatus.COMPLETED,
            response="completed",
            exit_code=0,
        )
        if isinstance(outcome, BaseException):
            raise outcome
        if not isinstance(outcome, RuntimeResult):
            raise TypeError("recording runtime outcome must be a RuntimeResult")
        return outcome


class StaticVerifier:
    """Verifier fake that returns a deterministic candidate record."""

    def __init__(self, result: WorkspaceVerificationResult | BaseException) -> None:
        self.result = result
        self.requests: list[WorkspaceVerificationRequest] = []

    def verify(self, request: WorkspaceVerificationRequest) -> WorkspaceVerificationResult:
        self.requests.append(request)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class ExecutionBoundaryReviewRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.workspace_a = self._git_workspace(self.root / "workspace-a")
        self.workspace_b = self._git_workspace(self.root / "workspace-b")
        self.service, self.mission_id, self.task = self._active_fixture(
            "mission-1", "task-1"
        )

    def tearDown(self) -> None:
        self.service.close()
        self.tempdir.cleanup()

    @staticmethod
    def _git_workspace(workspace: Path) -> Path:
        workspace.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
        (workspace / "README.md").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=workspace, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Kora Test",
                "-c",
                "user.email=kora@example.test",
                "commit",
                "-qm",
                "base",
            ],
            cwd=workspace,
            check=True,
        )
        return workspace

    def _active_fixture(
        self,
        mission_id: str,
        task_id: str,
        *,
        service: MissionService | None = None,
    ) -> tuple[MissionService, str, Task]:
        mission_service = service or MissionService()
        mission = mission_service.create_mission(
            "Boundary review mission",
            "Complete the approved execution slice.",
            "The changed workspace is independently verified.",
            mission_id=mission_id,
        )
        mission_service.align_mission(mission.mission_id)
        mission_service.activate_mission(mission.mission_id)
        task = mission_service.add_task(
            mission.mission_id,
            "Build the slice",
            description="Implement the approved execution slice.",
            task_id=task_id,
        )
        return mission_service, mission.mission_id, task

    def _fresh_fixture(self, prefix: str) -> tuple[MissionService, str, Task]:
        return self._active_fixture(
            f"{prefix}-mission",
            f"{prefix}-task",
        )

    @staticmethod
    def _runtime_result(
        mission_id: str,
        task_id: str,
        status: RuntimeStatus,
        *,
        response: str = "runtime response",
        total_tokens: int = 11,
        estimated_cost_usd: float = 0.02,
    ) -> RuntimeResult:
        return RuntimeResult(
            mission_id=mission_id,
            task_id=task_id,
            status=status,
            response=response,
            exit_code=0 if status is not RuntimeStatus.FAILED else 1,
            total_tokens=total_tokens,
            estimated_cost_usd=estimated_cost_usd,
        )

    @staticmethod
    def _profile(
        task: Task,
        *,
        capabilities: frozenset[Capability] = frozenset(),
        toolsets: tuple[str, ...] = (),
        evidence_requirements: tuple[str, ...] = (),
        privacy: PrivacyLevel = PrivacyLevel.EXTERNAL_OK,
        estimated_input_tokens: int = 0,
        estimated_output_tokens: int = 0,
        required_context_tokens: int = 0,
        quality_floor: float = 0.0,
        reliability_floor: float = 0.0,
    ) -> TaskProfile:
        return TaskProfile(
            task_id=task.task_id,
            task_class="bounded-implementation",
            objective=task.description or task.title,
            required_capabilities=frozenset(
                capability.value for capability in capabilities
            ),
            required_tools=frozenset(toolsets),
            privacy=privacy,
            estimated_input_tokens=estimated_input_tokens,
            estimated_output_tokens=estimated_output_tokens,
            required_context_tokens=required_context_tokens,
            quality_floor=quality_floor,
            reliability_floor=reliability_floor,
            evidence_requirements=evidence_requirements,
        )

    def _spec(
        self,
        task: Task,
        *,
        workspace: Path | None = None,
        profile: TaskProfile | None = None,
        capabilities: frozenset[Capability] = frozenset(),
        toolsets: tuple[str, ...] = (),
        permissions: tuple[PermissionRequirement, ...] = (),
        require_changes: bool = True,
        instructions: str = "Execute only the approved task.",
    ) -> TaskExecutionSpec:
        selected_profile = profile or self._profile(
            task,
            capabilities=capabilities,
            toolsets=toolsets,
        )
        if profile is not None and not capabilities:
            capabilities = frozenset(
                Capability(value) for value in profile.required_capabilities
            )
        if profile is not None and not toolsets:
            toolsets = tuple(sorted(profile.required_tools))
        return TaskExecutionSpec(
            profile=selected_profile,
            instructions=instructions,
            workspace=workspace or self.workspace_a,
            runtime_capabilities=capabilities,
            toolsets=toolsets,
            skills=("bounded-skill",),
            isolation=IsolationMode.CLOUD_SANDBOX,
            permission_requirements=permissions,
            verification_commands=(),
            require_changes=require_changes,
        )

    @staticmethod
    def _route(
        route_id: str,
        *,
        fixed_cost_usd: float = 0.10,
        capabilities: frozenset[Capability] = frozenset(),
        tools: frozenset[str] = frozenset(),
        privacy_support: PrivacyLevel = PrivacyLevel.EXTERNAL_OK,
        context_window: int = 100_000,
        quality: float = 1.0,
        reliability: float = 1.0,
        predicted_latency_ms: float = 100.0,
        input_cost_per_million: float = 0.0,
        output_cost_per_million: float = 0.0,
        enabled: bool = True,
    ) -> ModelRoute:
        return ModelRoute(
            route_id=route_id,
            provider_ref=f"provider-private-{route_id}",
            model_ref=f"model-private-{route_id}",
            supported_capabilities=frozenset(
                capability.value for capability in capabilities
            ),
            supported_tools=tools,
            privacy_support=privacy_support,
            context_window=context_window,
            predicted_quality=quality,
            reliability=reliability,
            input_cost_per_million=input_cost_per_million,
            output_cost_per_million=output_cost_per_million,
            fixed_cost_usd=fixed_cost_usd,
            predicted_latency_ms=predicted_latency_ms,
            enabled=enabled,
        )

    def _coordinator(
        self,
        service: MissionService,
        task: Task,
        spec: TaskExecutionSpec,
        runtimes: dict[str, RecordingRuntime],
        routes: list[ModelRoute],
        *,
        router: ModelRouter | None = None,
        role: RoleCharter | None = None,
        verifier: StaticVerifier | None = None,
        max_attempts: int = 3,
    ) -> ExecutionCoordinator:
        charter = role or RoleCharter(
            role_id="role-boundary-review",
            title="Boundary review operator",
            responsibilities=("Perform the bounded task",),
            non_responsibilities=("Create a new mission",),
            allowed_capabilities=frozenset(
                capability.value for capability in spec.runtime_capabilities
            ),
        )
        return ExecutionCoordinator(
            service,
            charter,
            WorkforceCompiler(max_attempts=max_attempts),
            router or ModelRouter(routes),
            MappingTaskSpecProvider({task.task_id: spec}),
            MappingRuntimeResolver(runtimes),
            verifier or StaticVerifier(self._accepted_verification()),
            "boundary-review-coordinator",
            30.0,
            max_attempts,
        )

    @staticmethod
    def _accepted_verification(
        *artifacts: VerificationArtifact,
    ) -> WorkspaceVerificationResult:
        selected = artifacts or (
            VerificationArtifact(
                name="verified workspace diff",
                locator=f"workspace-diff://workspace-a?sha256={SAFE_FINGERPRINT}",
                artifact_kind=ArtifactKind.DIFF,
                evidence_kind=EvidenceKind.ARTIFACT,
                summary="The independently checked workspace diff is available.",
            ),
        )
        return WorkspaceVerificationResult(
            accepted=True,
            summary="Independent checks accepted the workspace.",
            change_fingerprint=SAFE_FINGERPRINT,
            checks=(),
            artifacts=selected,
        )

    @staticmethod
    def _permission_uses(service: MissionService, grant_id: str) -> list[object]:
        return service.store.connection.execute(
            "SELECT * FROM permission_uses WHERE grant_id = ?",
            (grant_id,),
        ).fetchall()

    def _public_projection_strings(
        self,
        service: MissionService,
        mission_id: str,
        result: object,
    ) -> tuple[str, ...]:
        """Collect fields that a semantic caller may receive.

        Route and worker identifiers are intentionally omitted here: they are
        private correlation fields, not user-facing attempt projection data.
        """

        values: list[str] = [getattr(result, "summary", "")]
        status = service.get_status(mission_id)
        mission = status.mission
        values.extend(
            value
            for value in (
                mission.title,
                mission.objective,
                mission.definition_of_done,
                mission.failure_reason or "",
                mission.stop_reason or "",
            )
            if value
        )
        for task in (*status.tasks, status.next_task):
            if task is None:
                continue
            values.extend(value for value in (task.title, task.description or "") if value)
        for escalation in status.open_escalations:
            values.extend(
                value
                for value in (
                    escalation.title,
                    escalation.reason,
                    escalation.impact,
                    *escalation.options,
                    escalation.recommendation,
                    escalation.consequence_of_waiting,
                    escalation.requested_action,
                )
                if value
            )
        for checkpoint in service.store.list_checkpoints(mission_id):
            values.append(checkpoint.summary)
        for artifact in service.store.list_artifacts(mission_id):
            values.extend((artifact.name, artifact.locator))
        for evidence in service.store.list_evidence(mission_id):
            values.extend(
                value
                for value in (
                    evidence.summary,
                    evidence.locator or "",
                    evidence.verification_method or "",
                )
                if value
            )
        for attempt in service.store.list_attempts(mission_id):
            values.extend(
                value
                for value in (
                    attempt.status.value,
                    attempt.result_summary,
                    attempt.error_summary,
                )
                if value
            )
        for event in service.store.list_events(mission_id):
            values.append(event.event_type.value)
            values.append(json.dumps(dict(event.payload), sort_keys=True, default=str))
        return tuple(value for value in values if value)

    def _assert_no_private_markers(
        self,
        service: MissionService,
        mission_id: str,
        result: object,
    ) -> None:
        for value in self._public_projection_strings(service, mission_id, result):
            for marker in ALL_PRIVATE_MARKERS:
                self.assertNotIn(marker, value, msg=f"leaked {marker!r}: {value!r}")

    def _assert_public_locator(self, locator: str) -> None:
        parsed = urlsplit(locator)
        if parsed.scheme == "artifact" and parsed.netloc == "sha256":
            self.assertRegex(parsed.path, r"^/[0-9a-f]{64}$")
            self.assertFalse(parsed.query)
            return

        self.assertIn(parsed.scheme, {"workspace-diff", "workspace-test"})
        relative = unquote(parsed.netloc + parsed.path)
        self.assertTrue(relative)
        self.assertFalse(PurePosixPath(relative).is_absolute())
        self.assertNotIn("..", PurePosixPath(relative).parts)
        self.assertTrue(
            any(
                relative == workspace_name
                or relative.startswith(workspace_name + "/")
                for workspace_name in (self.workspace_a.name, self.workspace_b.name)
            )
        )
        digest = parse_qs(parsed.query).get("sha256", ())
        self.assertEqual(len(digest), 1)
        self.assertRegex(digest[0], r"^[0-9a-f]{64}$")

    def test_workspace_authority_is_bound_to_canonical_runtime_workspace(self) -> None:
        for capability, action in (
            (Capability.WORKSPACE_WRITE, PermissionAction.WRITE_WORKSPACE),
            (Capability.WORKSPACE_EXECUTE, PermissionAction.EXECUTE_WORKSPACE),
        ):
            with self.subTest(capability=capability.value):
                service, mission_id, task = self._fresh_fixture(capability.value)
                grant_id = f"grant-{capability.value}"
                try:
                    service.grant_permission(
                        mission_id,
                        action,
                        str(self.workspace_a.resolve()),
                        "Authorize only workspace A.",
                        mode=PermissionMode.BOUNDED_INDEFINITE,
                        scope="this mission only",
                        max_actions=2,
                        grant_id=grant_id,
                    )
                    try:
                        runtime: RecordingRuntime | None = None
                        spec = self._spec(
                            task,
                            workspace=self.workspace_b,
                            capabilities=frozenset({capability}),
                            permissions=(
                                PermissionRequirement(
                                    grant_id,
                                    action,
                                    str(self.workspace_a.resolve()),
                                ),
                            ),
                        )
                        runtime = RecordingRuntime(
                            self._runtime_result(
                                mission_id,
                                task.task_id,
                                RuntimeStatus.COMPLETED,
                            ),
                            writes=(("unauthorized-write.txt", "must not be written\n"),),
                        )
                        coordinator = self._coordinator(
                            service,
                            task,
                            spec,
                            {"route": runtime},
                            [self._route("route", capabilities=frozenset({capability}))],
                        )
                        result = coordinator.run_once(mission_id)
                    except ExecutionValidationError:
                        result = None

                    if result is not None:
                        self.assertEqual(result.status, CoordinatorStatus.WAITING_FOR_USER)
                    self.assertEqual(service.store.list_attempts(mission_id), [])
                    if runtime is not None:
                        self.assertEqual(runtime.calls, [])
                    self.assertEqual(self._permission_uses(service, grant_id), [])
                    self.assertFalse(
                        (self.workspace_b / "unauthorized-write.txt").exists()
                    )
                finally:
                    service.close()

    def test_runtime_outcomes_use_controller_owned_public_summaries(self) -> None:
        cases = (
            ("needs-user", RuntimeStatus.NEEDS_USER, CoordinatorStatus.WAITING_FOR_USER),
            ("failed", RuntimeStatus.FAILED, CoordinatorStatus.RETRY_EXHAUSTED),
            ("unstructured", RuntimeStatus.UNSTRUCTURED, CoordinatorStatus.RETRY_EXHAUSTED),
        )
        for prefix, runtime_status, expected_status in cases:
            with self.subTest(runtime_status=runtime_status.value):
                service, mission_id, task = self._fresh_fixture(prefix)
                try:
                    spec = self._spec(task)
                    runtime = RecordingRuntime(
                        self._runtime_result(
                            mission_id,
                            task.task_id,
                            runtime_status,
                            response=PRIVATE_RUNTIME_TEXT,
                        )
                    )
                    coordinator = self._coordinator(
                        service,
                        task,
                        spec,
                        {"route": runtime},
                        [self._route("route")],
                        max_attempts=1,
                    )

                    result = coordinator.run_once(mission_id)

                    self.assertEqual(result.status, expected_status)
                    self.assertNotEqual(result.summary, PRIVATE_RUNTIME_TEXT)
                    self._assert_no_private_markers(service, mission_id, result)
                finally:
                    service.close()

        service, mission_id, task = self._fresh_fixture("completed-summary")
        try:
            spec = self._spec(task)
            runtime = RecordingRuntime(
                self._runtime_result(
                    mission_id,
                    task.task_id,
                    RuntimeStatus.COMPLETED,
                    response=PRIVATE_RUNTIME_TEXT,
                ),
                writes=(("verified-output.txt", "verified\n"),),
            )
            coordinator = self._coordinator(
                service,
                task,
                spec,
                {"route": runtime},
                [self._route("route")],
            )

            result = coordinator.run_once(mission_id)

            self.assertEqual(result.status, CoordinatorStatus.MISSION_COMPLETED)
            self._assert_no_private_markers(service, mission_id, result)
        finally:
            service.close()

        service, mission_id, task = self._fresh_fixture("rejected-summary")
        try:
            runtime = RecordingRuntime(
                self._runtime_result(mission_id, task.task_id, RuntimeStatus.COMPLETED),
                writes=(("rejected-output.txt", "candidate\n"),),
            )
            rejected = WorkspaceVerificationResult(
                accepted=False,
                summary=PRIVATE_RUNTIME_TEXT,
                change_fingerprint=SAFE_FINGERPRINT,
                checks=(),
                artifacts=(),
            )
            coordinator = self._coordinator(
                service,
                task,
                self._spec(task),
                {"route": runtime},
                [self._route("route")],
                verifier=StaticVerifier(rejected),
                max_attempts=1,
            )

            result = coordinator.run_once(mission_id)

            self.assertEqual(result.status, CoordinatorStatus.RETRY_EXHAUSTED)
            self._assert_no_private_markers(service, mission_id, result)
        finally:
            service.close()

    def test_declared_evidence_rejects_diff_without_required_typed_kinds(self) -> None:
        service, mission_id, task = self._fresh_fixture("incomplete-evidence")
        try:
            profile = self._profile(
                task,
                evidence_requirements=("test_report", "walkthrough"),
            )
            spec = self._spec(task, profile=profile)
            runtime = RecordingRuntime(
                self._runtime_result(mission_id, task.task_id, RuntimeStatus.COMPLETED),
                writes=(("candidate.txt", "candidate\n"),),
            )
            only_diff = VerificationArtifact(
                name="candidate diff",
                locator=f"workspace-diff://workspace-a?sha256={SAFE_FINGERPRINT}",
                artifact_kind=ArtifactKind.DIFF,
                evidence_kind=EvidenceKind.ARTIFACT,
                summary="Only the candidate diff was checked.",
            )
            coordinator = self._coordinator(
                service,
                task,
                spec,
                {"route": runtime},
                [self._route("route")],
                verifier=StaticVerifier(self._accepted_verification(only_diff)),
                max_attempts=1,
            )

            result = coordinator.run_once(mission_id)

            self.assertEqual(result.status, CoordinatorStatus.RETRY_EXHAUSTED)
            self.assertNotEqual(
                service.get_task(task.task_id).state,
                TaskStatus.COMPLETED,
            )
            self.assertNotEqual(
                service.get_mission(mission_id).state,
                MissionState.COMPLETED,
            )
            task_evidence = [
                evidence
                for evidence in service.store.list_evidence(mission_id)
                if evidence.task_id == task.task_id
            ]
            self.assertFalse(any(evidence.verified_at is not None for evidence in task_evidence))
        finally:
            service.close()

    def test_declared_evidence_accepts_complete_typed_kind_coverage(self) -> None:
        service, mission_id, task = self._fresh_fixture("complete-evidence")
        try:
            profile = self._profile(
                task,
                evidence_requirements=("test_report", "walkthrough"),
            )
            spec = self._spec(task, profile=profile)
            runtime = RecordingRuntime(
                self._runtime_result(mission_id, task.task_id, RuntimeStatus.COMPLETED)
            )
            complete_artifacts = (
                VerificationArtifact(
                    name="acceptance test report",
                    locator=f"workspace-test://workspace-a?sha256={SAFE_FINGERPRINT}",
                    artifact_kind=ArtifactKind.TEST_REPORT,
                    evidence_kind=EvidenceKind.TEST,
                    summary="The acceptance test report was checked.",
                ),
                VerificationArtifact(
                    name="walkthrough preview",
                    locator=f"workspace-diff://workspace-a?sha256={SAFE_FINGERPRINT}",
                    artifact_kind=ArtifactKind.PREVIEW,
                    evidence_kind=EvidenceKind.WALKTHROUGH,
                    summary="The user-like walkthrough was checked.",
                ),
            )
            coordinator = self._coordinator(
                service,
                task,
                spec,
                {"route": runtime},
                [self._route("route")],
                verifier=StaticVerifier(
                    self._accepted_verification(*complete_artifacts)
                ),
            )

            result = coordinator.run_once(mission_id)

            self.assertEqual(result.status, CoordinatorStatus.MISSION_COMPLETED)
            self.assertEqual(
                {
                    evidence.kind
                    for evidence in service.store.list_evidence(mission_id)
                    if evidence.task_id == task.task_id
                },
                {EvidenceKind.TEST, EvidenceKind.WALKTHROUGH},
            )
        finally:
            service.close()

    def test_router_reservations_bound_budget_and_settle_failed_attempts(self) -> None:
        router = ModelRouter(
            [
                self._route("route-a", fixed_cost_usd=0.30),
                self._route("route-b", fixed_cost_usd=0.30),
            ],
            budget_ceiling_usd=0.50,
        )
        reservation_observations: list[tuple[int, float]] = []
        first_runtime = RecordingRuntime(
            self._runtime_result(
                self.mission_id,
                self.task.task_id,
                RuntimeStatus.FAILED,
                estimated_cost_usd=0.30,
            ),
            on_run=lambda _job: reservation_observations.append(
                (router.active_concurrency, router.reserved_cost_usd)
            ),
        )
        second_runtime = RecordingRuntime(
            self._runtime_result(
                self.mission_id,
                self.task.task_id,
                RuntimeStatus.COMPLETED,
                estimated_cost_usd=0.30,
            )
        )
        coordinator = self._coordinator(
            self.service,
            self.task,
            self._spec(self.task),
            {"route-a": first_runtime, "route-b": second_runtime},
            [],
            router=router,
            max_attempts=2,
        )

        result = coordinator.run_once(self.mission_id)

        self.assertEqual(result.status, CoordinatorStatus.RETRY_EXHAUSTED)
        self.assertEqual(reservation_observations, [(1, 0.30)])
        self.assertEqual(len(first_runtime.calls), 1)
        self.assertEqual(second_runtime.calls, [])
        self.assertEqual(router.active_concurrency, 0)
        self.assertAlmostEqual(router.reserved_cost_usd, 0.0)
        self.assertAlmostEqual(router.spent_cost_usd, 0.30)

    def test_unknown_runtime_outcome_commits_reserved_cost_conservatively(self) -> None:
        router = ModelRouter(
            [self._route("route-a", fixed_cost_usd=0.30)],
            budget_ceiling_usd=0.50,
        )
        reservation_observations: list[tuple[int, float]] = []
        runtime = RecordingRuntime(
            RuntimeError("harness-secret-9 opaque provider failure"),
            on_run=lambda _job: reservation_observations.append(
                (router.active_concurrency, router.reserved_cost_usd)
            ),
        )
        coordinator = self._coordinator(
            self.service,
            self.task,
            self._spec(self.task),
            {"route-a": runtime},
            [],
            router=router,
        )

        result = coordinator.run_once(self.mission_id)

        self.assertEqual(result.status, CoordinatorStatus.UNKNOWN_OUTCOME)
        self.assertEqual(reservation_observations, [(1, 0.30)])
        self.assertEqual(router.active_concurrency, 0)
        self.assertAlmostEqual(router.reserved_cost_usd, 0.0)
        self.assertAlmostEqual(router.spent_cost_usd, 0.30)

    def test_valid_workspace_locator_is_accepted(self) -> None:
        valid_locator = f"workspace-diff://workspace-a?sha256={SAFE_FINGERPRINT}"
        service, mission_id, task = self._fresh_fixture("valid-locator")
        try:
            runtime = RecordingRuntime(
                self._runtime_result(mission_id, task.task_id, RuntimeStatus.COMPLETED)
            )
            artifact = VerificationArtifact(
                name="Workspace diff",
                locator=valid_locator,
                artifact_kind=ArtifactKind.DIFF,
                evidence_kind=EvidenceKind.ARTIFACT,
                summary="The workspace diff was checked.",
            )
            coordinator = self._coordinator(
                service,
                task,
                self._spec(task),
                {"route": runtime},
                [self._route("route")],
                verifier=StaticVerifier(self._accepted_verification(artifact)),
            )

            result = coordinator.run_once(mission_id)

            self.assertEqual(result.status, CoordinatorStatus.MISSION_COMPLETED)
            self._assert_public_locator(
                service.store.list_artifacts(mission_id)[0].locator
            )
        finally:
            service.close()

    def test_artifact_public_fields_never_leak_private_markers(self) -> None:
        valid_locator = f"workspace-diff://workspace-a?sha256={SAFE_FINGERPRINT}"
        service, mission_id, task = self._fresh_fixture("private-artifact-fields")
        try:
            private_artifact = VerificationArtifact(
                name=f"Display label {PRIVATE_RUNTIME_TEXT}",
                locator=valid_locator,
                artifact_kind=ArtifactKind.DIFF,
                evidence_kind=EvidenceKind.ARTIFACT,
                summary=f"Artifact summary {PRIVATE_RUNTIME_TEXT}",
            )
            coordinator = self._coordinator(
                service,
                task,
                self._spec(task),
                {
                    "route": RecordingRuntime(
                        self._runtime_result(
                            mission_id,
                            task.task_id,
                            RuntimeStatus.COMPLETED,
                        )
                    )
                },
                [self._route("route")],
                verifier=StaticVerifier(
                    self._accepted_verification(private_artifact)
                ),
            )

            result = coordinator.run_once(mission_id)

            self._assert_no_private_markers(service, mission_id, result)
            for artifact in service.store.list_artifacts(mission_id):
                self._assert_public_locator(artifact.locator)
        finally:
            service.close()

    def test_artifact_locator_rejects_private_or_noncanonical_values(self) -> None:
        service, mission_id, task = self._fresh_fixture("invalid-locator")
        try:
            invalid_artifact = VerificationArtifact(
                name="Safe label",
                locator=f"workspace-diff://../{PRIVATE_MARKERS[0]}?sha256=not-a-hash",
                artifact_kind=ArtifactKind.DIFF,
                evidence_kind=EvidenceKind.ARTIFACT,
                summary="Safe summary.",
            )
            coordinator = self._coordinator(
                service,
                task,
                self._spec(task),
                {
                    "route": RecordingRuntime(
                        self._runtime_result(
                            mission_id,
                            task.task_id,
                            RuntimeStatus.COMPLETED,
                        )
                    )
                },
                [self._route("route")],
                verifier=StaticVerifier(
                    self._accepted_verification(invalid_artifact)
                ),
            )

            result = coordinator.run_once(mission_id)

            self.assertNotEqual(result.status, CoordinatorStatus.MISSION_COMPLETED)
            self.assertNotEqual(
                service.get_mission(mission_id).state,
                MissionState.COMPLETED,
            )
            self._assert_no_private_markers(service, mission_id, result)
            for artifact in service.store.list_artifacts(mission_id):
                self._assert_public_locator(artifact.locator)
        finally:
            service.close()

    def test_missing_private_runtime_route_uses_fallback_without_leaking_or_stranding(self) -> None:
        service, mission_id, task = self._fresh_fixture("missing-runtime-fallback")
        try:
            missing_route_id = "route-secret-9"
            fallback_runtime = RecordingRuntime(
                self._runtime_result(mission_id, task.task_id, RuntimeStatus.COMPLETED)
            )
            coordinator = self._coordinator(
                service,
                task,
                self._spec(task),
                {"fallback-route": fallback_runtime},
                [
                    self._route(missing_route_id, fixed_cost_usd=0.10),
                    self._route("fallback-route", fixed_cost_usd=0.20),
                ],
            )

            try:
                result = coordinator.run_once(mission_id)
            except Exception as exc:  # noqa: BLE001 - the boundary must contain this
                self.fail(f"missing runtime escaped as {type(exc).__name__}")

            self.assertEqual(result.status, CoordinatorStatus.MISSION_COMPLETED)
            self.assertEqual(len(fallback_runtime.calls), 1)
            self.assertTrue(
                all(
                    attempt.status
                    not in {AttemptStatus.RUNNING, AttemptStatus.VERIFYING}
                    for attempt in service.store.list_attempts(mission_id)
                )
            )
            self._assert_no_private_markers(service, mission_id, result)
        finally:
            service.close()

    def test_missing_private_runtime_route_exhaustion_creates_one_generic_escalation(self) -> None:
        service, mission_id, task = self._fresh_fixture("missing-runtime-exhausted")
        try:
            missing_route_id = "route-secret-9"
            coordinator = self._coordinator(
                service,
                task,
                self._spec(task),
                {},
                [self._route(missing_route_id, fixed_cost_usd=0.10)],
                max_attempts=1,
            )

            try:
                result = coordinator.run_once(mission_id)
            except Exception as exc:  # noqa: BLE001 - the boundary must contain this
                self.fail(f"missing runtime escaped as {type(exc).__name__}")

            self.assertEqual(result.status, CoordinatorStatus.RETRY_EXHAUSTED)
            escalations = service.store.list_escalations(
                mission_id,
                EscalationStatus.OPEN,
            )
            self.assertEqual(len(escalations), 1)
            self.assertEqual(escalations[0].title, "Technical blocker")
            self.assertTrue(
                all(
                    attempt.status
                    not in {AttemptStatus.RUNNING, AttemptStatus.VERIFYING}
                    for attempt in service.store.list_attempts(mission_id)
                )
            )
            self._assert_no_private_markers(service, mission_id, result)
        finally:
            service.close()

    def test_expected_cost_routing_and_non_founder_role_remain_supported(self) -> None:
        profile = TaskProfile(
            task_id="economic-task",
            task_class="bounded-implementation",
            objective="Implement the approved economic slice.",
            required_capabilities=frozenset({Capability.WORKSPACE_READ.value}),
            required_tools=frozenset({"git"}),
            privacy=PrivacyLevel.PRIVATE,
            estimated_input_tokens=1000,
            estimated_output_tokens=1000,
            required_context_tokens=1000,
            quality_floor=0.80,
            reliability_floor=0.80,
            max_cost_usd=1.0,
        )
        raw_cheap = self._route(
            "raw-cheap",
            fixed_cost_usd=0.10,
            capabilities=frozenset({Capability.WORKSPACE_READ}),
            tools=frozenset({"git"}),
            privacy_support=PrivacyLevel.PRIVATE,
            quality=0.80,
            reliability=0.80,
        )
        strong = self._route(
            "strong-expected-cheap",
            fixed_cost_usd=0.14,
            capabilities=frozenset({Capability.WORKSPACE_READ}),
            tools=frozenset({"git"}),
            privacy_support=PrivacyLevel.PRIVATE,
            quality=0.99,
            reliability=0.99,
        )
        router = ModelRouter([raw_cheap, strong])

        decision = router.select(profile)

        self.assertEqual(decision.route_id, strong.route_id)
        self.assertLess(
            ModelRouter.expected_cost_per_accepted_outcome(profile, strong),
            ModelRouter.expected_cost_per_accepted_outcome(profile, raw_cheap),
        )
        self.assertGreater(
            ModelRouter.attempt_cost(profile, strong),
            ModelRouter.attempt_cost(profile, raw_cheap),
        )

        operations_role = RoleCharter(
            role_id="role-operations-analyst",
            title="Operations analyst",
            responsibilities=("Reconcile approved operations work",),
            non_responsibilities=("Change the mission objective",),
            authority_constraints=("Use only approved workspace authority",),
            allowed_capabilities=frozenset(),
        )
        runtime = RecordingRuntime(
            self._runtime_result(
                self.mission_id,
                self.task.task_id,
                RuntimeStatus.COMPLETED,
            ),
            writes=(("operations-output.txt", "operations result\n"),),
        )
        coordinator = self._coordinator(
            self.service,
            self.task,
            self._spec(self.task),
            {"operations-route": runtime},
            [self._route("operations-route")],
            role=operations_role,
            verifier=None,
        )

        result = coordinator.run_once(self.mission_id)

        self.assertEqual(result.status, CoordinatorStatus.MISSION_COMPLETED)
        self.assertEqual(self.service.get_mission(self.mission_id).state, MissionState.COMPLETED)
        self.assertEqual(self.service.get_task(self.task.task_id).state, TaskStatus.COMPLETED)
        self.assertEqual(len(runtime.calls), 1)


if __name__ == "__main__":
    unittest.main()

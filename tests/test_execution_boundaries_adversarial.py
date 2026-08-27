from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kora.execution import (
    CoordinatorStatus,
    ExecutionCoordinator,
    ExecutionValidationError,
    MappingRuntimeResolver,
    MappingTaskSpecProvider,
    PermissionRequirement,
    TaskExecutionSpec,
    sanitize_summary,
)
from kora.mission import (
    ArtifactKind,
    AttemptStatus,
    EscalationStatus,
    EvidenceKind,
    MissionService,
    MissionState,
    PermissionAction,
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
    WorkspaceVerifier,
)
from kora.workforce import (
    CapabilityBoundaryError,
    ModelRoute,
    ModelRouter,
    PrivacyLevel,
    RoleCharter,
    TaskProfile,
    WorkforceCompiler,
)


PRIVATE_MARKERS = (
    "provider_ref",
    "model_ref",
    "provider-private",
    "model-private",
    "SecretProvider",
    "route-topology",
    "route_id",
    "raw prompt",
    "total_tokens",
    "token_count",
)


class RecordingRuntime:
    """Deterministic runtime double with optional workspace writes."""

    def __init__(
        self,
        *outcomes: RuntimeResult | BaseException,
        writes: tuple[tuple[str, str], ...] = (),
    ) -> None:
        self.outcomes = list(outcomes)
        self.writes = writes
        self.calls: list[RuntimeJob] = []

    def run(self, job: RuntimeJob) -> RuntimeResult:
        self.calls.append(job)
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
        return outcome


class StaticVerifier:
    """Deterministic verifier double that records every request."""

    def __init__(self, result: WorkspaceVerificationResult | BaseException) -> None:
        self.result = result
        self.requests: list[WorkspaceVerificationRequest] = []

    def verify(self, request: WorkspaceVerificationRequest) -> WorkspaceVerificationResult:
        self.requests.append(request)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class DeterministicClock:
    def __init__(self, *values: float) -> None:
        self.values = iter(values)

    def monotonic(self) -> float:
        return next(self.values)


class ExecutionBoundaryAdversarialTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.workspace = self._git_workspace(self.root)
        self.service, self.mission_id, self.task = self._make_fixture(
            "mission-1", "task-1"
        )

    def tearDown(self) -> None:
        self.service.close()
        self.tempdir.cleanup()

    @staticmethod
    def _git_workspace(root: Path) -> Path:
        workspace = root / "workspace"
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

    @staticmethod
    def _make_fixture(
        mission_id: str,
        task_id: str,
        *,
        owner_ref: str = "owner",
        service: MissionService | None = None,
        activate: bool = True,
    ) -> tuple[MissionService, str, object]:
        mission_service = service or MissionService(owner_ref=owner_ref)
        mission = mission_service.create_mission(
            "Adversarial execution mission",
            "Complete the approved execution slice.",
            "The workspace change is independently verified.",
            mission_id=mission_id,
        )
        mission_service.align_mission(mission.mission_id)
        if activate:
            mission_service.activate_mission(mission.mission_id)
        task = mission_service.add_task(
            mission.mission_id,
            "Build the slice",
            description="Implement the approved execution slice.",
            task_id=task_id,
        )
        return mission_service, mission.mission_id, task

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
    def _profile_for(
        task: object,
        *,
        task_id: str | None = None,
        objective: str | None = None,
        capabilities: frozenset[Capability] = frozenset(),
        toolsets: tuple[str, ...] = (),
        **overrides: object,
    ) -> TaskProfile:
        task_id_value = task_id or task.task_id  # type: ignore[attr-defined]
        objective_value = objective or task.description or task.title  # type: ignore[attr-defined]
        values: dict[str, object] = {
            "task_id": task_id_value,
            "task_class": "implementation",
            "objective": objective_value,
            "required_capabilities": frozenset(
                capability.value for capability in capabilities
            ),
            "required_tools": frozenset(toolsets),
        }
        values.update(overrides)
        return TaskProfile(**values)  # type: ignore[arg-type]

    def _spec_for(
        self,
        task: object,
        *,
        profile: TaskProfile | None = None,
        capabilities: frozenset[Capability] = frozenset(),
        toolsets: tuple[str, ...] = (),
        permissions: tuple[PermissionRequirement, ...] = (),
        require_changes: bool = True,
        instructions: str = "Implement only the approved task.",
    ) -> TaskExecutionSpec:
        task_profile = profile or self._profile_for(
            task,
            capabilities=capabilities,
            toolsets=toolsets,
        )
        return TaskExecutionSpec(
            profile=task_profile,
            instructions=instructions,
            workspace=self.workspace,
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

    def _coordinator_for(
        self,
        service: MissionService,
        task: object,
        spec: TaskExecutionSpec,
        runtimes: dict[str, RecordingRuntime],
        routes: list[ModelRoute],
        *,
        role: RoleCharter | None = None,
        verifier: object | None = None,
        max_attempts: int = 3,
    ) -> ExecutionCoordinator:
        charter = role or RoleCharter(
            role_id="role-adversarial-operator",
            title="Adversarial operator",
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
            ModelRouter(routes),
            MappingTaskSpecProvider({task.task_id: spec}),  # type: ignore[attr-defined]
            MappingRuntimeResolver(runtimes),
            verifier if verifier is not None else WorkspaceVerifier(self.root),
            "adversarial-coordinator",
            30.0,
            max_attempts,
        )

    @staticmethod
    def _accepted_verification(
        *artifacts: VerificationArtifact,
        summary: str = "Independent checks accepted the workspace.",
    ) -> WorkspaceVerificationResult:
        return WorkspaceVerificationResult(
            accepted=True,
            summary=summary,
            change_fingerprint="fingerprint",
            checks=(),
            artifacts=artifacts,
        )

    @staticmethod
    def _mission_facing_summaries(
        service: MissionService,
        mission_id: str,
        result: object,
    ) -> list[str]:
        summaries = [result.summary]  # type: ignore[attr-defined]
        status = service.get_status(mission_id)
        for escalation in status.open_escalations:
            summaries.extend(
                [
                    escalation.title,
                    escalation.reason,
                    escalation.impact,
                    escalation.recommendation,
                    escalation.consequence_of_waiting,
                    escalation.requested_action,
                ]
            )
        for evidence in service.store.list_evidence(mission_id):
            summaries.append(evidence.summary)
        for attempt in service.store.list_attempts(mission_id):
            summaries.extend([attempt.result_summary, attempt.error_summary])
        return [summary for summary in summaries if summary]

    def test_coordinator_and_mission_summaries_never_leak_private_runtime_text(self) -> None:
        injected = (
            "provider_ref=provider-private-x model_ref=model-private-x "
            "route-topology=cheap->strong raw prompt=do-the-secret-thing "
            "total_tokens=999 token_count=9999 "
            "KORA_INTERNAL_TRACE\x00"
            + "x" * 5000
        )
        spec = self._spec_for(self.task)
        runtime = RecordingRuntime(
            self._runtime_result(
                self.mission_id,
                self.task.task_id,
                RuntimeStatus.NEEDS_USER,
                response=injected,
            )
        )
        coordinator = self._coordinator_for(
            self.service,
            self.task,
            spec,
            {"route": runtime},
            [self._route("route")],
        )

        result = coordinator.run_once(self.mission_id)

        self.assertEqual(result.status, CoordinatorStatus.WAITING_FOR_USER)
        self.assertEqual(
            set(result.__dataclass_fields__),
            {"mission_id", "status", "summary", "task_id", "attempt_id"},
        )
        self.assertLessEqual(len(result.summary), 1000)
        self.assertNotIn("\x00", result.summary)
        for summary in self._mission_facing_summaries(
            self.service, self.mission_id, result
        ):
            for marker in PRIVATE_MARKERS:
                self.assertNotIn(marker, summary, msg=f"leaked {marker!r}: {summary!r}")

    def test_quality_and_reliability_floors_keep_weak_cheap_routes_out(self) -> None:
        profile = self._profile_for(
            self.task,
            quality_floor=0.80,
            reliability_floor=0.80,
        )
        spec = self._spec_for(self.task, profile=profile)
        weak_quality = self._route(
            "weak-quality",
            fixed_cost_usd=0.01,
            quality=0.79,
            reliability=1.0,
        )
        weak_reliability = self._route(
            "weak-reliability",
            fixed_cost_usd=0.01,
            quality=1.0,
            reliability=0.79,
        )
        strong = self._route(
            "strong",
            fixed_cost_usd=0.20,
            quality=0.90,
            reliability=0.90,
        )
        decision = ModelRouter([weak_quality, weak_reliability, strong]).select(profile)
        self.assertEqual(decision.route_id, "strong")

        weak_quality_runtime = RecordingRuntime(
            self._runtime_result(self.mission_id, self.task.task_id, RuntimeStatus.COMPLETED)
        )
        weak_reliability_runtime = RecordingRuntime(
            self._runtime_result(self.mission_id, self.task.task_id, RuntimeStatus.COMPLETED)
        )
        strong_runtime = RecordingRuntime(
            self._runtime_result(self.mission_id, self.task.task_id, RuntimeStatus.COMPLETED),
            writes=(("strong-output.txt", "verified strong output\n"),),
        )
        coordinator = self._coordinator_for(
            self.service,
            self.task,
            spec,
            {
                "weak-quality": weak_quality_runtime,
                "weak-reliability": weak_reliability_runtime,
                "strong": strong_runtime,
            },
            [weak_quality, weak_reliability, strong],
        )

        result = coordinator.run_once(self.mission_id)

        self.assertEqual(result.status, CoordinatorStatus.MISSION_COMPLETED)
        self.assertEqual(weak_quality_runtime.calls, [])
        self.assertEqual(weak_reliability_runtime.calls, [])
        self.assertEqual(len(strong_runtime.calls), 1)
        attempt = self.service.store.list_attempts(self.mission_id, self.task.task_id)[0]
        self.assertEqual(attempt.quality_floor, 0.80)
        self.assertEqual(profile.quality_floor, 0.80)
        self.assertEqual(profile.reliability_floor, 0.80)

    def test_failed_cheap_route_is_excluded_and_observation_metrics_are_exact(self) -> None:
        spec = self._spec_for(self.task)
        cheap = RecordingRuntime(
            self._runtime_result(
                self.mission_id,
                self.task.task_id,
                RuntimeStatus.FAILED,
                response="cheap route failed",
                total_tokens=13,
                estimated_cost_usd=0.07,
            )
        )
        strong = RecordingRuntime(
            self._runtime_result(
                self.mission_id,
                self.task.task_id,
                RuntimeStatus.COMPLETED,
                total_tokens=29,
                estimated_cost_usd=0.23,
            )
        )
        verifier = StaticVerifier(
            self._accepted_verification(
                VerificationArtifact(
                    name="accepted diff",
                    locator="workspace://accepted-diff",
                    artifact_kind=ArtifactKind.DIFF,
                    evidence_kind=EvidenceKind.ARTIFACT,
                    summary="The independent verifier accepted the diff.",
                )
            )
        )
        coordinator = self._coordinator_for(
            self.service,
            self.task,
            spec,
            {"cheap": cheap, "strong": strong},
            [
                self._route("cheap", fixed_cost_usd=0.01),
                self._route("strong", fixed_cost_usd=0.20),
            ],
            verifier=verifier,
            max_attempts=2,
        )

        with patch(
            "kora.execution.coordinator.time",
            DeterministicClock(10.0, 10.125, 20.0, 20.456),
        ):
            result = coordinator.run_once(self.mission_id)

        self.assertEqual(result.status, CoordinatorStatus.MISSION_COMPLETED)
        self.assertEqual([len(cheap.calls), len(strong.calls)], [1, 1])
        observations = coordinator.model_router.observations
        self.assertEqual(
            [
                (
                    observation.route_id,
                    observation.accepted,
                    observation.total_tokens,
                    observation.cost_usd,
                    observation.latency_ms,
                )
                for observation in observations
            ],
            [
                ("cheap", False, 13, 0.07, 125.0),
                ("strong", True, 29, 0.23, 456.0),
            ],
        )

    def test_no_eligible_route_has_one_blocker_and_no_side_effecting_call(self) -> None:
        capabilities = frozenset({Capability.WORKSPACE_READ})
        spec = self._spec_for(self.task, capabilities=capabilities)
        runtime = RecordingRuntime(
            self._runtime_result(self.mission_id, self.task.task_id, RuntimeStatus.COMPLETED)
        )
        coordinator = self._coordinator_for(
            self.service,
            self.task,
            spec,
            {"route": runtime},
            [self._route("route")],
        )

        result = coordinator.run_once(self.mission_id)

        self.assertEqual(result.status, CoordinatorStatus.RETRY_EXHAUSTED)
        self.assertEqual(self.service.store.list_attempts(self.mission_id), [])
        self.assertEqual(runtime.calls, [])
        escalations = self.service.store.list_escalations(
            self.mission_id, EscalationStatus.OPEN
        )
        self.assertEqual(len(escalations), 1)
        self.assertEqual(escalations[0].title, "Technical blocker")
        self.assertEqual(self.service.get_mission(self.mission_id).state, MissionState.WAITING_FOR_USER)

    def test_completed_runtime_without_workspace_changes_falls_back_before_acceptance(self) -> None:
        spec = self._spec_for(self.task)
        cheap = RecordingRuntime(
            self._runtime_result(self.mission_id, self.task.task_id, RuntimeStatus.COMPLETED)
        )
        strong = RecordingRuntime(
            self._runtime_result(self.mission_id, self.task.task_id, RuntimeStatus.COMPLETED),
            writes=(("fallback-output.txt", "strong verified output\n"),),
        )
        coordinator = self._coordinator_for(
            self.service,
            self.task,
            spec,
            {"cheap": cheap, "strong": strong},
            [
                self._route("cheap", fixed_cost_usd=0.01),
                self._route("strong", fixed_cost_usd=0.20),
            ],
        )

        result = coordinator.run_once(self.mission_id)

        self.assertEqual(result.status, CoordinatorStatus.MISSION_COMPLETED)
        attempts = self.service.store.list_attempts(self.mission_id, self.task.task_id)
        self.assertEqual([attempt.route_id for attempt in attempts], ["cheap", "strong"])
        self.assertEqual(
            [attempt.status for attempt in attempts],
            [AttemptStatus.FAILED, AttemptStatus.SUCCEEDED],
        )
        self.assertEqual(len(cheap.calls), 1)
        self.assertEqual(len(strong.calls), 1)
        self.assertEqual(self.service.get_task(self.task.task_id).state, TaskStatus.COMPLETED)

    def test_verifier_rejection_never_verifies_evidence_or_completes_task(self) -> None:
        spec = self._spec_for(self.task)
        runtime = RecordingRuntime(
            self._runtime_result(self.mission_id, self.task.task_id, RuntimeStatus.COMPLETED)
        )
        verifier = StaticVerifier(
            WorkspaceVerificationResult(
                accepted=False,
                summary="The independent verifier rejected the candidate.",
                change_fingerprint="rejected-fingerprint",
                checks=(),
                artifacts=(
                    VerificationArtifact(
                        name="rejected candidate",
                        locator="workspace://rejected-candidate",
                        artifact_kind=ArtifactKind.DIFF,
                        evidence_kind=EvidenceKind.ARTIFACT,
                        summary="Candidate evidence was rejected.",
                    ),
                ),
            )
        )
        coordinator = self._coordinator_for(
            self.service,
            self.task,
            spec,
            {"route": runtime},
            [self._route("route")],
            verifier=verifier,
            max_attempts=1,
        )

        result = coordinator.run_once(self.mission_id)

        self.assertEqual(result.status, CoordinatorStatus.RETRY_EXHAUSTED)
        self.assertNotEqual(self.service.get_task(self.task.task_id).state, TaskStatus.COMPLETED)
        self.assertNotEqual(self.service.get_mission(self.mission_id).state, MissionState.COMPLETED)
        evidence = self.service.store.list_evidence(self.mission_id)
        self.assertTrue(all(item.verified_at is None for item in evidence))
        self.assertTrue(all(item.verification_method is None for item in evidence))
        self.assertFalse(
            any(item.kind is EvidenceKind.REQUIREMENT_COVERAGE for item in evidence)
        )

    def test_verifier_acceptance_persists_every_artifact_and_verified_evidence_first(self) -> None:
        spec = self._spec_for(self.task)
        runtime = RecordingRuntime(
            self._runtime_result(
                self.mission_id,
                self.task.task_id,
                RuntimeStatus.COMPLETED,
                response="KORA_TASK_COMPLETE provider-private-runtime raw prompt hidden total_tokens=777",
            )
        )
        returned_artifacts = (
            VerificationArtifact(
                name="diff artifact",
                locator="workspace://diff-artifact",
                artifact_kind=ArtifactKind.DIFF,
                evidence_kind=EvidenceKind.ARTIFACT,
                summary="A diff was independently checked.",
            ),
            VerificationArtifact(
                name="test report",
                locator="workspace://test-report",
                artifact_kind=ArtifactKind.TEST_REPORT,
                evidence_kind=EvidenceKind.TEST,
                summary="The acceptance test report was independently checked.",
            ),
            VerificationArtifact(
                name="preview artifact",
                locator="workspace://preview",
                artifact_kind=ArtifactKind.PREVIEW,
                evidence_kind=EvidenceKind.WALKTHROUGH,
                summary="The preview was independently checked.",
            ),
        )
        verifier = StaticVerifier(self._accepted_verification(*returned_artifacts))
        coordinator = self._coordinator_for(
            self.service,
            self.task,
            spec,
            {"route": runtime},
            [self._route("route")],
            verifier=verifier,
        )
        completion_snapshot: list[tuple[int, int, bool]] = []
        real_complete_task = self.service.complete_task

        def complete_task_after_evidence(task_id: str, **kwargs: object) -> object:
            artifacts = self.service.store.list_artifacts(self.mission_id)
            evidence = [
                item
                for item in self.service.store.list_evidence(self.mission_id)
                if item.task_id == self.task.task_id
            ]
            completion_snapshot.append(
                (len(artifacts), len(evidence), all(item.verified_at is not None for item in evidence))
            )
            return real_complete_task(task_id, **kwargs)

        self.service.complete_task = complete_task_after_evidence  # type: ignore[method-assign]
        result = coordinator.run_once(self.mission_id)

        self.assertEqual(result.status, CoordinatorStatus.MISSION_COMPLETED)
        self.assertEqual(completion_snapshot, [(3, 3, True)])
        persisted_artifacts = self.service.store.list_artifacts(self.mission_id)
        self.assertEqual(
            [item.kind for item in persisted_artifacts],
            [item.artifact_kind for item in returned_artifacts],
        )
        self.assertTrue(all(item.name.startswith("Verified ") for item in persisted_artifacts))
        self.assertTrue(
            all(
                item.locator.startswith("artifact://sha256/")
                for item in persisted_artifacts
            )
        )
        task_evidence = [
            item
            for item in self.service.store.list_evidence(self.mission_id)
            if item.task_id == self.task.task_id
        ]
        self.assertEqual(len(task_evidence), len(returned_artifacts))
        self.assertTrue(all(item.verified_at is not None for item in task_evidence))
        self.assertTrue(
            all(item.verification_method == "independent workspace verifier" for item in task_evidence)
        )
        self.assertNotIn("KORA_TASK_COMPLETE", result.summary)
        self.assertTrue(
            all(
                "KORA_TASK_COMPLETE" not in item.summary
                for item in self.service.store.list_evidence(self.mission_id)
            )
        )

    def _assert_exact_grant_boundary(
        self,
        *,
        capability: Capability,
        action: PermissionAction,
        grant_case: str,
    ) -> None:
        service, mission_id, task = self._make_fixture(
            f"{capability.value}-{grant_case}-mission",
            f"{capability.value}-{grant_case}-task",
        )
        requirement = PermissionRequirement(
            f"grant-{capability.value}-{grant_case}",
            action,
            str(self.workspace),
        )
        spec = self._spec_for(
            task,
            capabilities=frozenset({capability}),
            permissions=(requirement,),
        )
        runtime = RecordingRuntime(
            self._runtime_result(mission_id, task.task_id, RuntimeStatus.COMPLETED)
        )
        foreign_service: MissionService | None = None
        try:
            if grant_case == "wrong-action":
                wrong_action = (
                    PermissionAction.EXECUTE_WORKSPACE
                    if action is PermissionAction.WRITE_WORKSPACE
                    else PermissionAction.WRITE_WORKSPACE
                )
                grant = service.grant_permission(
                    mission_id,
                    wrong_action,
                    str(self.workspace),
                    "wrong action",
                    grant_id=requirement.grant_id,
                )
            elif grant_case == "wrong-resource":
                grant = service.grant_permission(
                    mission_id,
                    action,
                    str(self.workspace / "wrong-resource"),
                    "wrong resource",
                    grant_id=requirement.grant_id,
                )
            elif grant_case == "same-scope-wrong-grant-id":
                grant = service.grant_permission(
                    mission_id,
                    action,
                    str(self.workspace),
                    "different grant id",
                    grant_id=requirement.grant_id + "-actual",
                )
            elif grant_case == "foreign-mission":
                foreign_service = MissionService(service.store, owner_ref="foreign-owner")
                _, foreign_mission, _ = self._make_fixture(
                    f"foreign-{capability.value}-{grant_case}",
                    f"foreign-{capability.value}-{grant_case}-task",
                    service=foreign_service,
                    owner_ref="foreign-owner",
                    activate=False,
                )
                grant = foreign_service.grant_permission(
                    foreign_mission,
                    action,
                    str(self.workspace),
                    "foreign mission grant",
                    grant_id=requirement.grant_id,
                )
            elif grant_case == "missing":
                grant = None
            else:
                raise AssertionError(f"unknown grant case: {grant_case}")

            coordinator = self._coordinator_for(
                service,
                task,
                spec,
                {"route": runtime},
                [self._route("route", capabilities=frozenset({capability}))],
            )
            result = coordinator.run_once(mission_id)

            self.assertEqual(result.status, CoordinatorStatus.WAITING_FOR_USER)
            self.assertEqual(runtime.calls, [])
            uses = service.store.connection.execute(
                "SELECT grant_id FROM permission_uses WHERE grant_id = ?",
                (requirement.grant_id,),
            ).fetchall()
            self.assertEqual(uses, [])
            if grant is not None:
                persisted = service.store.get_permission_grant(grant.grant_id)
                self.assertIsNotNone(persisted)
                assert persisted is not None
                self.assertEqual(persisted.actions_used, 0)
                self.assertEqual(persisted.spent_cents, 0)
        finally:
            service.close()

    def test_workspace_write_requires_exact_action_resource_and_mission_grant(self) -> None:
        for grant_case in (
            "wrong-action",
            "wrong-resource",
            "missing",
            "same-scope-wrong-grant-id",
            "foreign-mission",
        ):
            with self.subTest(grant_case=grant_case):
                self._assert_exact_grant_boundary(
                    capability=Capability.WORKSPACE_WRITE,
                    action=PermissionAction.WRITE_WORKSPACE,
                    grant_case=grant_case,
                )

    def test_workspace_execute_requires_exact_action_resource_and_mission_grant(self) -> None:
        for grant_case in (
            "wrong-action",
            "wrong-resource",
            "missing",
            "same-scope-wrong-grant-id",
            "foreign-mission",
        ):
            with self.subTest(grant_case=grant_case):
                self._assert_exact_grant_boundary(
                    capability=Capability.WORKSPACE_EXECUTE,
                    action=PermissionAction.EXECUTE_WORKSPACE,
                    grant_case=grant_case,
                )

    def test_objective_capability_tool_memory_and_charter_boundaries_precede_execution(self) -> None:
        runtime = RecordingRuntime(
            self._runtime_result(self.mission_id, self.task.task_id, RuntimeStatus.COMPLETED)
        )

        mismatched_spec = self._spec_for(
            self.task,
            profile=self._profile_for(self.task, objective="different objective"),
        )
        mismatched_coordinator = self._coordinator_for(
            self.service,
            self.task,
            mismatched_spec,
            {"route": runtime},
            [self._route("route")],
        )
        with self.assertRaises(ExecutionValidationError):
            mismatched_coordinator.run_once(self.mission_id)
        self.assertEqual(runtime.calls, [])
        self.assertEqual(self.service.store.list_attempts(self.mission_id), [])

        capability_profile = self._profile_for(
            self.task,
            capabilities=frozenset({Capability.WORKSPACE_READ}),
        )
        with self.assertRaises(ExecutionValidationError):
            self._spec_for(self.task, profile=capability_profile)

        tool_profile = self._profile_for(self.task, toolsets=("git",))
        with self.assertRaises(ExecutionValidationError):
            self._spec_for(self.task, profile=tool_profile)

        memory_profile = self._profile_for(
            self.task,
            capabilities=frozenset({Capability.RUNTIME_MEMORY_WRITE}),
        )
        with self.assertRaises(ExecutionValidationError):
            self._spec_for(
                self.task,
                profile=memory_profile,
                capabilities=frozenset({Capability.RUNTIME_MEMORY_WRITE}),
            )

        outside_charter_spec = self._spec_for(
            self.task,
            capabilities=frozenset({Capability.WORKSPACE_READ}),
        )
        outside_charter_runtime = RecordingRuntime(
            self._runtime_result(self.mission_id, self.task.task_id, RuntimeStatus.COMPLETED)
        )
        outside_charter = RoleCharter(
            role_id="role-without-read",
            title="Constrained operator",
            allowed_capabilities=frozenset(),
        )
        outside_charter_coordinator = self._coordinator_for(
            self.service,
            self.task,
            outside_charter_spec,
            {"route": outside_charter_runtime},
            [self._route("route", capabilities=frozenset({Capability.WORKSPACE_READ}))],
            role=outside_charter,
        )
        with self.assertRaises(CapabilityBoundaryError):
            outside_charter_coordinator.run_once(self.mission_id)
        self.assertEqual(outside_charter_runtime.calls, [])
        self.assertEqual(self.service.store.list_attempts(self.mission_id), [])

    def test_non_founder_role_uses_the_same_coordinator_schema_and_completes(self) -> None:
        spec = self._spec_for(self.task)
        runtime = RecordingRuntime(
            self._runtime_result(self.mission_id, self.task.task_id, RuntimeStatus.COMPLETED),
            writes=(("operations-output.txt", "operations result\n"),),
        )
        operations_role = RoleCharter(
            role_id="role-operations-analyst",
            title="Operations analyst",
            responsibilities=("Reconcile approved operations work",),
            non_responsibilities=("Change the mission objective",),
            allowed_capabilities=frozenset(),
            authority_constraints=("Use only approved workspace authority",),
        )
        coordinator = self._coordinator_for(
            self.service,
            self.task,
            spec,
            {"route": runtime},
            [self._route("route")],
            role=operations_role,
        )

        result = coordinator.run_once(self.mission_id)

        self.assertEqual(result.status, CoordinatorStatus.MISSION_COMPLETED)
        self.assertEqual(self.service.get_mission(self.mission_id).state, MissionState.COMPLETED)
        self.assertEqual(self.service.get_task(self.task.task_id).state, TaskStatus.COMPLETED)
        self.assertEqual(len(runtime.calls), 1)

    def test_router_minimizes_expected_cost_while_preserving_every_hard_constraint(self) -> None:
        task = TaskProfile(
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
            max_latency_ms=500.0,
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
        ineligible_routes = [
            self._route(
                "missing-capability",
                fixed_cost_usd=0.001,
                tools=frozenset({"git"}),
            ),
            self._route(
                "missing-tool",
                fixed_cost_usd=0.001,
                capabilities=frozenset({Capability.WORKSPACE_READ}),
                tools=frozenset({"other-tool"}),
            ),
            self._route(
                "privacy-too-low",
                fixed_cost_usd=0.001,
                capabilities=frozenset({Capability.WORKSPACE_READ}),
                tools=frozenset({"git"}),
                privacy_support=PrivacyLevel.EXTERNAL_OK,
            ),
            self._route(
                "context-too-small",
                fixed_cost_usd=0.001,
                capabilities=frozenset({Capability.WORKSPACE_READ}),
                tools=frozenset({"git"}),
                privacy_support=PrivacyLevel.PRIVATE,
                context_window=999,
            ),
            self._route(
                "quality-too-low",
                fixed_cost_usd=0.001,
                capabilities=frozenset({Capability.WORKSPACE_READ}),
                tools=frozenset({"git"}),
                privacy_support=PrivacyLevel.PRIVATE,
                quality=0.79,
            ),
            self._route(
                "reliability-too-low",
                fixed_cost_usd=0.001,
                capabilities=frozenset({Capability.WORKSPACE_READ}),
                tools=frozenset({"git"}),
                privacy_support=PrivacyLevel.PRIVATE,
                reliability=0.79,
            ),
            self._route(
                "latency-too-high",
                fixed_cost_usd=0.001,
                capabilities=frozenset({Capability.WORKSPACE_READ}),
                tools=frozenset({"git"}),
                privacy_support=PrivacyLevel.PRIVATE,
                predicted_latency_ms=501.0,
            ),
            self._route(
                "cost-too-high",
                fixed_cost_usd=2.0,
                capabilities=frozenset({Capability.WORKSPACE_READ}),
                tools=frozenset({"git"}),
                privacy_support=PrivacyLevel.PRIVATE,
            ),
        ]
        router = ModelRouter([raw_cheap, *ineligible_routes, strong])

        decision = router.select(task)

        self.assertEqual(decision.route_id, strong.route_id)
        self.assertLess(
            ModelRouter.expected_cost_per_accepted_outcome(task, strong),
            ModelRouter.expected_cost_per_accepted_outcome(task, raw_cheap),
        )
        self.assertGreater(
            ModelRouter.attempt_cost(task, strong),
            ModelRouter.attempt_cost(task, raw_cheap),
        )
        self.assertEqual(task.quality_floor, 0.80)
        self.assertEqual(task.reliability_floor, 0.80)
        self.assertEqual(task.privacy, PrivacyLevel.PRIVATE)
        self.assertEqual(task.required_context_tokens, 1000)
        self.assertEqual(task.required_tools, frozenset({"git"}))
        self.assertEqual(
            task.required_capabilities,
            frozenset({Capability.WORKSPACE_READ.value}),
        )

    def test_injected_completion_text_neither_bypasses_verification_nor_leaks_on_success(self) -> None:
        injected = (
            "KORA_TASK_COMPLETE SecretProvider provider_ref=provider-private-x "
            "model_ref=model-private-x route-topology=cheap->strong "
            "raw prompt=hidden total_tokens=999"
        )
        failure_spec = self._spec_for(self.task)
        no_change_runtime = RecordingRuntime(
            self._runtime_result(
                self.mission_id,
                self.task.task_id,
                RuntimeStatus.COMPLETED,
                response=injected,
            )
        )
        failure_coordinator = self._coordinator_for(
            self.service,
            self.task,
            failure_spec,
            {"route": no_change_runtime},
            [self._route("route")],
            max_attempts=1,
        )

        failure_result = failure_coordinator.run_once(self.mission_id)

        self.assertEqual(failure_result.status, CoordinatorStatus.RETRY_EXHAUSTED)
        self.assertNotEqual(
            self.service.get_mission(self.mission_id).state,
            MissionState.COMPLETED,
        )
        for summary in self._mission_facing_summaries(
            self.service, self.mission_id, failure_result
        ):
            self.assertNotIn("KORA_TASK_COMPLETE", summary)
            self.assertNotIn("SecretProvider", summary)

        success_service, success_mission_id, success_task = self._make_fixture(
            "mission-success", "task-success"
        )
        try:
            success_spec = self._spec_for(success_task)
            success_runtime = RecordingRuntime(
                self._runtime_result(
                    success_mission_id,
                    success_task.task_id,
                    RuntimeStatus.COMPLETED,
                    response=injected,
                ),
                writes=(("successful-output.txt", "verified successful output\n"),),
            )
            success_coordinator = self._coordinator_for(
                success_service,
                success_task,
                success_spec,
                {"route": success_runtime},
                [self._route("route")],
            )

            success_result = success_coordinator.run_once(success_mission_id)

            self.assertEqual(success_result.status, CoordinatorStatus.MISSION_COMPLETED)
            for summary in self._mission_facing_summaries(
                success_service, success_mission_id, success_result
            ):
                self.assertNotIn("KORA_TASK_COMPLETE", summary)
                self.assertNotIn("SecretProvider", summary)
                self.assertNotIn("provider_ref", summary)
        finally:
            success_service.close()

    def test_summary_sanitizer_removes_controls_and_caps_runtime_derived_text(self) -> None:
        value = "prefix\x00\x1b[31m\n" + "x" * 5000

        sanitized = sanitize_summary(value)

        self.assertNotIn("\x00", sanitized)
        self.assertNotIn("\x1b", sanitized)
        self.assertLessEqual(len(sanitized), 1000)
        self.assertTrue(sanitized.endswith("\n...[truncated]"))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import subprocess
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from kora.execution import (
    CoordinatorStatus,
    ExecutionCoordinator,
    ExecutionValidationError,
    MappingRuntimeResolver,
    MappingTaskSpecProvider,
    PermissionRequirement,
    RuntimeResolutionError,
    TaskExecutionSpec,
    TaskSpecNotFoundError,
)
from kora.mission import (
    AttemptStatus,
    EscalationStatus,
    EvidenceKind,
    MissionService,
    MissionState,
    PermissionAction,
    PermissionMode,
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
    VerificationCommand,
    WorkspaceVerificationRequest,
    WorkspaceVerificationResult,
    WorkspaceVerifier,
)
from kora.workforce import (
    ModelRoute,
    ModelRouter,
    RoleCharter,
    TaskProfile,
    WorkforceCompiler,
)


class ScriptedRuntime:
    def __init__(self, *outcomes: object, mutate: bool = False) -> None:
        self.outcomes = list(outcomes)
        self.mutate = mutate
        self.calls: list[RuntimeJob] = []

    def run(self, job: RuntimeJob) -> RuntimeResult:
        self.calls.append(job)
        if self.mutate:
            (job.workspace / "runtime-output.txt").write_text(
                "verified output\n", encoding="utf-8"
            )
        outcome = self.outcomes.pop(0) if self.outcomes else RuntimeResult(
            job.mission_id,
            job.task_id,
            RuntimeStatus.COMPLETED,
            "completed",
            0,
        )
        if isinstance(outcome, BaseException):
            raise outcome
        if not isinstance(outcome, RuntimeResult):
            raise TypeError("scripted outcome must be a RuntimeResult")
        return outcome


class StaticVerifier:
    def __init__(self, result: object) -> None:
        self.result = result
        self.requests: list[WorkspaceVerificationRequest] = []

    def verify(self, request: WorkspaceVerificationRequest) -> object:
        self.requests.append(request)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class ExecutionCoordinatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.workspace = self._git_workspace(self.root)
        self.service = MissionService()
        mission = self.service.create_mission(
            "Execution mission",
            "Complete the approved execution slice.",
            "The task is changed and independently verified.",
            mission_id="mission-1",
        )
        self.service.align_mission(mission.mission_id)
        self.service.activate_mission(mission.mission_id)
        self.task = self.service.add_task(
            mission.mission_id,
            "Build the slice",
            description="Implement the approved execution slice.",
            task_id="task-1",
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
    def _runtime_result(
        mission_id: str,
        task_id: str,
        status: RuntimeStatus,
        response: str = "runtime response",
    ) -> RuntimeResult:
        return RuntimeResult(
            mission_id,
            task_id,
            status,
            response,
            0 if status is not RuntimeStatus.FAILED else 1,
            total_tokens=11,
            estimated_cost_usd=0.02,
        )

    def _profile(
        self,
        *,
        capabilities: frozenset[Capability] = frozenset(),
        toolsets: tuple[str, ...] = (),
        objective: str | None = None,
    ) -> TaskProfile:
        return TaskProfile(
            task_id=self.task.task_id,
            task_class="implementation",
            objective=objective or self.task.description or self.task.title,
            required_capabilities=frozenset(capability.value for capability in capabilities),
            required_tools=frozenset(toolsets),
        )

    def _spec(
        self,
        *,
        capabilities: frozenset[Capability] = frozenset(),
        toolsets: tuple[str, ...] = (),
        permissions: tuple[PermissionRequirement, ...] = (),
        verifier: tuple[VerificationCommand, ...] = (),
        require_changes: bool = True,
        material_ambiguity: str = "",
        ambiguity_question: str = "",
        objective: str | None = None,
    ) -> TaskExecutionSpec:
        return TaskExecutionSpec(
            profile=self._profile(
                capabilities=capabilities,
                toolsets=toolsets,
                objective=objective,
            ),
            instructions="Implement only the approved task.",
            workspace=self.workspace,
            runtime_capabilities=capabilities,
            toolsets=toolsets,
            skills=("workspace-skill",),
            isolation=IsolationMode.CLOUD_SANDBOX,
            permission_requirements=permissions,
            verification_commands=verifier,
            require_changes=require_changes,
            material_ambiguity=material_ambiguity,
            ambiguity_question=ambiguity_question,
        )

    @staticmethod
    def _route(
        route_id: str,
        *,
        fixed_cost_usd: float,
        capabilities: frozenset[Capability] = frozenset(),
        tools: frozenset[str] = frozenset(),
        quality: float = 1.0,
        reliability: float = 1.0,
    ) -> ModelRoute:
        return ModelRoute(
            route_id=route_id,
            provider_ref=f"provider-{route_id}",
            model_ref=f"model-{route_id}",
            supported_capabilities=frozenset(capability.value for capability in capabilities),
            supported_tools=tools,
            predicted_quality=quality,
            reliability=reliability,
            fixed_cost_usd=fixed_cost_usd,
        )

    def _coordinator(
        self,
        spec: TaskExecutionSpec,
        runtimes: dict[str, ScriptedRuntime],
        routes: list[ModelRoute],
        *,
        verifier: object | None = None,
        max_attempts: int = 3,
        lease_seconds: float = 30.0,
        role_title: str = "Domain operator",
    ) -> ExecutionCoordinator:
        allowed = spec.runtime_capabilities
        role = RoleCharter(
            role_id="role-domain-operator",
            title=role_title,
            responsibilities=("Perform the bounded task",),
            non_responsibilities=("Create a new mission",),
            allowed_capabilities=frozenset(capability.value for capability in allowed),
        )
        return ExecutionCoordinator(
            self.service,
            role,
            WorkforceCompiler(max_attempts=max_attempts),
            ModelRouter(routes),
            MappingTaskSpecProvider({self.task.task_id: spec}),
            MappingRuntimeResolver(runtimes),
            verifier or WorkspaceVerifier(self.root),
            "test-coordinator",
            lease_seconds,
            max_attempts,
        )

    def _static_acceptance(self) -> WorkspaceVerificationResult:
        return WorkspaceVerificationResult(
            accepted=True,
            summary="Independent checks accepted the workspace.",
            change_fingerprint="fingerprint",
            checks=(),
            artifacts=(
                VerificationArtifact(
                    name="verified output",
                    locator="workspace://verified-output",
                    artifact_kind="diff",
                    evidence_kind="artifact",
                    summary="The workspace output is available.",
                ),
            ),
        )

    def test_cheapest_eligible_route_success_and_generalized_role_charter(self) -> None:
        spec = self._spec()
        cheap = ScriptedRuntime(
            self._runtime_result("mission-1", "task-1", RuntimeStatus.COMPLETED),
            mutate=True,
        )
        expensive = ScriptedRuntime(
            self._runtime_result("mission-1", "task-1", RuntimeStatus.COMPLETED),
            mutate=True,
        )
        coordinator = self._coordinator(
            spec,
            {"cheap-route": cheap, "strong-route": expensive},
            [
                self._route("strong-route", fixed_cost_usd=0.40),
                self._route("cheap-route", fixed_cost_usd=0.05),
            ],
            role_title="Clinical operations analyst",
        )

        result = coordinator.run_once("mission-1")

        self.assertEqual(result.status, CoordinatorStatus.MISSION_COMPLETED)
        self.assertEqual(len(cheap.calls), 1)
        self.assertEqual(expensive.calls, [])
        self.assertEqual(cheap.calls[0].objective, self.task.description)
        self.assertEqual(cheap.calls[0].skills, ("workspace-skill",))
        self.assertEqual(self.service.get_task("task-1").state, TaskStatus.COMPLETED)

    def test_failed_cheap_route_escalates_to_stronger_route(self) -> None:
        spec = self._spec()
        cheap = ScriptedRuntime(
            self._runtime_result("mission-1", "task-1", RuntimeStatus.FAILED, "cheap failed")
        )
        strong = ScriptedRuntime(
            self._runtime_result("mission-1", "task-1", RuntimeStatus.COMPLETED),
            mutate=True,
        )
        coordinator = self._coordinator(
            spec,
            {"cheap": cheap, "strong": strong},
            [
                self._route("cheap", fixed_cost_usd=0.01),
                self._route("strong", fixed_cost_usd=0.20),
            ],
        )

        result = coordinator.run_once("mission-1")

        self.assertEqual(result.status, CoordinatorStatus.MISSION_COMPLETED)
        attempts = self.service.store.list_attempts("mission-1", "task-1")
        self.assertEqual([attempt.route_id for attempt in attempts], ["cheap", "strong"])
        self.assertEqual(
            [attempt.status for attempt in attempts],
            [AttemptStatus.FAILED, AttemptStatus.SUCCEEDED],
        )
        self.assertEqual([observation.accepted for observation in coordinator.model_router.observations], [False, True])

    def test_independent_verification_is_required(self) -> None:
        spec = self._spec()
        runtime = ScriptedRuntime(
            self._runtime_result("mission-1", "task-1", RuntimeStatus.COMPLETED)
        )
        verifier = StaticVerifier(
            WorkspaceVerificationResult(
                accepted=False,
                summary="The independent check rejected the candidate.",
                change_fingerprint="fingerprint",
                checks=(),
                artifacts=(),
            )
        )
        coordinator = self._coordinator(
            spec,
            {"route": runtime},
            [self._route("route", fixed_cost_usd=0.10)],
            verifier=verifier,
            max_attempts=1,
        )

        result = coordinator.run_once("mission-1")

        self.assertEqual(result.status, CoordinatorStatus.RETRY_EXHAUSTED)
        self.assertEqual(len(runtime.calls), 1)
        self.assertEqual(self.service.get_task("task-1").state, TaskStatus.NEEDS_USER)
        self.assertEqual(self.service.get_mission("mission-1").state, MissionState.WAITING_FOR_USER)
        self.assertEqual(self.service.store.list_evidence("mission-1"), [])

    def test_runtime_completion_without_artifact_is_rejected(self) -> None:
        spec = self._spec()
        runtime = ScriptedRuntime(
            self._runtime_result("mission-1", "task-1", RuntimeStatus.COMPLETED)
        )
        verifier = StaticVerifier(
            WorkspaceVerificationResult(
                accepted=True,
                summary="The runtime text is not evidence.",
                change_fingerprint="fingerprint",
                checks=(),
                artifacts=(),
            )
        )
        coordinator = self._coordinator(
            spec,
            {"route": runtime},
            [self._route("route", fixed_cost_usd=0.10)],
            verifier=verifier,
            max_attempts=1,
        )

        result = coordinator.run_once("mission-1")

        self.assertEqual(result.status, CoordinatorStatus.RETRY_EXHAUSTED)
        self.assertEqual(self.service.store.list_evidence("mission-1"), [])
        self.assertEqual(self.service.get_task("task-1").state, TaskStatus.NEEDS_USER)

    def test_accepted_artifacts_are_verified_before_task_and_mission_completion(self) -> None:
        spec = self._spec()
        runtime = ScriptedRuntime(
            self._runtime_result("mission-1", "task-1", RuntimeStatus.COMPLETED)
        )
        verifier = StaticVerifier(self._static_acceptance())
        coordinator = self._coordinator(
            spec,
            {"route": runtime},
            [self._route("route", fixed_cost_usd=0.10)],
            verifier=verifier,
        )

        result = coordinator.run_once("mission-1")

        self.assertEqual(result.status, CoordinatorStatus.MISSION_COMPLETED)
        task_evidence = [
            evidence
            for evidence in self.service.store.list_evidence("mission-1")
            if evidence.task_id == "task-1"
        ]
        self.assertEqual(len(task_evidence), 1)
        self.assertIsNotNone(task_evidence[0].verified_at)
        self.assertEqual(
            task_evidence[0].verification_method,
            "independent workspace verifier",
        )
        coverage = [
            evidence
            for evidence in self.service.store.list_evidence("mission-1")
            if evidence.kind is EvidenceKind.REQUIREMENT_COVERAGE
        ]
        self.assertEqual(len(coverage), 1)
        self.assertIn(task_evidence[0].evidence_id, coverage[0].locator or "")
        self.assertEqual(self.service.get_mission("mission-1").state, MissionState.COMPLETED)
        self.assertTrue(self.service.store.list_checkpoints("mission-1"))

    def test_permission_consumption_is_exact_and_retry_authorization_is_idempotent(self) -> None:
        grant = self.service.grant_permission(
            "mission-1",
            PermissionAction.WRITE_WORKSPACE,
            str(self.workspace),
            "Modify the approved workspace.",
            mode=PermissionMode.BOUNDED_INDEFINITE,
            scope="this mission only",
            max_actions=2,
            grant_id="grant-write",
        )
        requirement = PermissionRequirement(
            grant.grant_id,
            PermissionAction.WRITE_WORKSPACE,
            str(self.workspace),
        )
        spec = self._spec(
            capabilities=frozenset({Capability.WORKSPACE_WRITE}),
            permissions=(requirement,),
        )
        cheap = ScriptedRuntime(
            self._runtime_result("mission-1", "task-1", RuntimeStatus.FAILED, "retry")
        )
        strong = ScriptedRuntime(
            self._runtime_result("mission-1", "task-1", RuntimeStatus.COMPLETED),
            mutate=True,
        )
        coordinator = self._coordinator(
            spec,
            {"cheap": cheap, "strong": strong},
            [
                self._route("cheap", fixed_cost_usd=0.01, capabilities=spec.runtime_capabilities),
                self._route("strong", fixed_cost_usd=0.20, capabilities=spec.runtime_capabilities),
            ],
        )

        result = coordinator.run_once("mission-1")

        self.assertEqual(result.status, CoordinatorStatus.MISSION_COMPLETED)
        persisted_grant = self.service.store.get_permission_grant(grant.grant_id)
        assert persisted_grant is not None
        self.assertEqual(persisted_grant.actions_used, 1)
        uses = self.service.store.connection.execute(
            "SELECT idempotency_key FROM permission_uses WHERE grant_id = ? ORDER BY idempotency_key",
            (grant.grant_id,),
        ).fetchall()
        self.assertEqual(
            [row[0] for row in uses],
            ["authority:mission-1:task-1:grant-write:write_workspace:" + str(self.workspace)],
        )

    def test_missing_permission_escalates_before_attempt_creation(self) -> None:
        requirement = PermissionRequirement(
            "missing-grant",
            PermissionAction.DEPLOY,
            "production/project",
        )
        spec = self._spec(permissions=(requirement,))
        runtime = ScriptedRuntime(
            self._runtime_result("mission-1", "task-1", RuntimeStatus.COMPLETED)
        )
        coordinator = self._coordinator(
            spec,
            {"route": runtime},
            [self._route("route", fixed_cost_usd=0.10)],
        )

        result = coordinator.run_once("mission-1")

        self.assertEqual(result.status, CoordinatorStatus.WAITING_FOR_USER)
        self.assertEqual(self.service.store.list_attempts("mission-1"), [])
        self.assertEqual(runtime.calls, [])
        escalations = self.service.store.list_escalations("mission-1", EscalationStatus.OPEN)
        self.assertEqual(len(escalations), 1)
        self.assertIn("Approve deploy", escalations[0].requested_action)

    def test_material_ambiguity_escalates_before_attempt_creation(self) -> None:
        spec = self._spec(
            material_ambiguity="The approved source has two materially different interpretations.",
            ambiguity_question="Which interpretation should be implemented?",
        )
        runtime = ScriptedRuntime(
            self._runtime_result("mission-1", "task-1", RuntimeStatus.COMPLETED)
        )
        coordinator = self._coordinator(
            spec,
            {"route": runtime},
            [self._route("route", fixed_cost_usd=0.10)],
        )

        result = coordinator.run_once("mission-1")

        self.assertEqual(result.status, CoordinatorStatus.WAITING_FOR_USER)
        self.assertEqual(self.service.store.list_attempts("mission-1"), [])
        escalation = self.service.store.list_escalations("mission-1", EscalationStatus.OPEN)[0]
        self.assertEqual(escalation.requested_action, "Which interpretation should be implemented?")
        self.assertEqual(runtime.calls, [])

    def test_runtime_needs_user_interrupts_attempt_and_escalates(self) -> None:
        spec = self._spec()
        runtime = ScriptedRuntime(
            self._runtime_result(
                "mission-1",
                "task-1",
                RuntimeStatus.NEEDS_USER,
                "Please choose the approved account.",
            )
        )
        verifier = StaticVerifier(self._static_acceptance())
        coordinator = self._coordinator(
            spec,
            {"route": runtime},
            [self._route("route", fixed_cost_usd=0.10)],
            verifier=verifier,
        )

        result = coordinator.run_once("mission-1")

        self.assertEqual(result.status, CoordinatorStatus.WAITING_FOR_USER)
        attempt = self.service.store.list_attempts("mission-1", "task-1")[0]
        self.assertEqual(attempt.status, AttemptStatus.INTERRUPTED)
        self.assertIn("Please choose", result.summary)
        self.assertEqual(verifier.requests, [])
        self.assertEqual(self.service.get_task("task-1").state, TaskStatus.NEEDS_USER)

    def test_runtime_exception_leaves_a_recoverable_running_attempt(self) -> None:
        spec = self._spec()
        runtime = ScriptedRuntime(RuntimeError("opaque provider trace"))
        coordinator = self._coordinator(
            spec,
            {"route": runtime},
            [self._route("route", fixed_cost_usd=0.10)],
            lease_seconds=0.05,
        )

        result = coordinator.run_once("mission-1")

        self.assertEqual(result.status, CoordinatorStatus.UNKNOWN_OUTCOME)
        attempt = self.service.store.list_attempts("mission-1", "task-1")[0]
        self.assertEqual(attempt.status, AttemptStatus.RUNNING)
        self.assertTrue(attempt.has_active_lease())
        self.assertNotIn("opaque provider trace", result.summary)
        self.assertEqual(coordinator.run_once("mission-1").status, CoordinatorStatus.BUSY)

    def test_expired_lease_becomes_unknown_and_prevents_duplicate_execution(self) -> None:
        self.service.start_task("task-1")
        at = datetime.now(UTC) - timedelta(seconds=10)
        attempt = self.service.create_attempt(
            "mission-1",
            "task-1",
            "old-attempt",
            worker_role_id="old-envelope",
            route_id="route",
            created_at=at,
        )
        self.service.claim_attempt(
            attempt.attempt_id,
            "old-worker",
            lease_expires_at=at + timedelta(seconds=1),
            at=at,
        )
        spec = self._spec()
        runtime = ScriptedRuntime(
            self._runtime_result("mission-1", "task-1", RuntimeStatus.COMPLETED)
        )
        coordinator = self._coordinator(
            spec,
            {"route": runtime},
            [self._route("route", fixed_cost_usd=0.10)],
        )

        result = coordinator.run_once("mission-1")

        self.assertEqual(result.status, CoordinatorStatus.UNKNOWN_OUTCOME)
        self.assertEqual(self.service.get_attempt(attempt.attempt_id).status, AttemptStatus.UNKNOWN)
        self.assertEqual(runtime.calls, [])

    def test_restart_resumes_one_stranded_task(self) -> None:
        self.service.start_task("task-1")
        at = datetime.now(UTC)
        attempt = self.service.create_attempt(
            "mission-1",
            "task-1",
            "failed-before-restart",
            worker_role_id="old-envelope",
            route_id="old-route",
            created_at=at,
        )
        claimed = self.service.claim_attempt(
            attempt.attempt_id,
            "old-worker",
            lease_seconds=30,
            at=at,
        )
        self.service.fail_attempt(
            claimed.attempt_id,
            error_summary="The first worker failed.",
            lease_owner="old-worker",
            fencing_token=claimed.fencing_token,
            at=at + timedelta(seconds=1),
        )
        spec = self._spec()
        runtime = ScriptedRuntime(
            self._runtime_result("mission-1", "task-1", RuntimeStatus.COMPLETED)
        )
        coordinator = self._coordinator(
            spec,
            {"route": runtime},
            [self._route("route", fixed_cost_usd=0.10)],
            verifier=StaticVerifier(self._static_acceptance()),
        )

        result = coordinator.run_once("mission-1")

        self.assertEqual(result.status, CoordinatorStatus.MISSION_COMPLETED)
        self.assertEqual(len(runtime.calls), 1)
        self.assertEqual(self.service.get_task("task-1").state, TaskStatus.COMPLETED)

    def test_no_eligible_route_creates_blocker_without_attempt(self) -> None:
        capabilities = frozenset({Capability.WORKSPACE_READ})
        spec = self._spec(capabilities=capabilities)
        runtime = ScriptedRuntime(
            self._runtime_result("mission-1", "task-1", RuntimeStatus.COMPLETED)
        )
        coordinator = self._coordinator(
            spec,
            {"route": runtime},
            [self._route("route", fixed_cost_usd=0.10)],
        )

        result = coordinator.run_once("mission-1")

        self.assertEqual(result.status, CoordinatorStatus.RETRY_EXHAUSTED)
        self.assertEqual(self.service.store.list_attempts("mission-1"), [])
        self.assertEqual(runtime.calls, [])
        self.assertEqual(self.service.get_task("task-1").state, TaskStatus.NEEDS_USER)

    def test_retry_exhaustion_waits_for_user_after_all_allowed_failures(self) -> None:
        spec = self._spec()
        first = ScriptedRuntime(
            self._runtime_result("mission-1", "task-1", RuntimeStatus.FAILED, "first")
        )
        second = ScriptedRuntime(
            self._runtime_result("mission-1", "task-1", RuntimeStatus.UNSTRUCTURED, "second")
        )
        coordinator = self._coordinator(
            spec,
            {"first": first, "second": second},
            [
                self._route("first", fixed_cost_usd=0.01),
                self._route("second", fixed_cost_usd=0.02),
            ],
            max_attempts=2,
        )

        result = coordinator.run_once("mission-1")

        self.assertEqual(result.status, CoordinatorStatus.RETRY_EXHAUSTED)
        self.assertEqual(len(self.service.store.list_attempts("mission-1")), 2)
        self.assertEqual(self.service.get_mission("mission-1").state, MissionState.WAITING_FOR_USER)
        self.assertEqual(self.service.get_task("task-1").state, TaskStatus.NEEDS_USER)
        self.assertEqual(len(self.service.store.list_escalations("mission-1", EscalationStatus.OPEN)), 1)

    def test_attempt_idempotency_keys_are_deterministic(self) -> None:
        spec = self._spec()
        first = ScriptedRuntime(
            self._runtime_result("mission-1", "task-1", RuntimeStatus.FAILED, "first")
        )
        second = ScriptedRuntime(
            self._runtime_result("mission-1", "task-1", RuntimeStatus.COMPLETED),
            mutate=True,
        )
        coordinator = self._coordinator(
            spec,
            {"first": first, "second": second},
            [
                self._route("first", fixed_cost_usd=0.01),
                self._route("second", fixed_cost_usd=0.02),
            ],
        )

        coordinator.run_once("mission-1")

        self.assertEqual(
            [attempt.idempotency_key for attempt in self.service.store.list_attempts("mission-1")],
            [
                "attempt:mission-1:task-1:first:1",
                "attempt:mission-1:task-1:second:2",
            ],
        )

    def test_task_objective_mismatch_is_rejected_by_provider(self) -> None:
        mismatched = self._spec(objective="A different objective")

        with self.assertRaises(ExecutionValidationError):
            MappingTaskSpecProvider({"task-1": mismatched}).get(self.task)

        self.assertEqual(self.service.store.list_attempts("mission-1"), [])

    def test_capability_tool_and_memory_validation_is_strict(self) -> None:
        with self.assertRaises(ExecutionValidationError):
            self._spec(capabilities=frozenset({Capability.WORKSPACE_WRITE}))

        with self.assertRaises(ExecutionValidationError):
            TaskExecutionSpec(
                profile=self._profile(toolsets=("search",)),
                instructions="instructions",
                workspace=self.workspace,
                runtime_capabilities=frozenset(),
                toolsets=(),
                skills=(),
                isolation=IsolationMode.READ_ONLY,
                permission_requirements=(),
                verification_commands=(),
            )

        with self.assertRaises(ExecutionValidationError):
            TaskExecutionSpec(
                profile=self._profile(
                    capabilities=frozenset({Capability.RUNTIME_MEMORY_WRITE})
                ),
                instructions="instructions",
                workspace=self.workspace,
                runtime_capabilities=frozenset({Capability.RUNTIME_MEMORY_WRITE}),
                toolsets=(),
                skills=(),
                isolation=IsolationMode.READ_ONLY,
                permission_requirements=(),
                verification_commands=(),
            )

    def test_mapping_contracts_and_constructor_bounds(self) -> None:
        spec = self._spec()
        with self.assertRaises(TaskSpecNotFoundError):
            MappingTaskSpecProvider({}).get(self.task)
        with self.assertRaises(RuntimeResolutionError):
            MappingRuntimeResolver({}).resolve("missing")

        with self.assertRaises(ExecutionValidationError):
            ExecutionCoordinator(
                self.service,
                RoleCharter("role", "Role"),
                WorkforceCompiler(),
                ModelRouter([self._route("route", fixed_cost_usd=0.10)]),
                MappingTaskSpecProvider({"task-1": spec}),
                MappingRuntimeResolver({"route": ScriptedRuntime()}),
                WorkspaceVerifier(self.root),
                "worker",
                0,
                1,
            )

    def test_coordinator_result_has_no_model_provider_or_token_fields(self) -> None:
        spec = self._spec(material_ambiguity="Need a choice.", ambiguity_question="Choose.")
        coordinator = self._coordinator(
            spec,
            {},
            [],
        )

        result = coordinator.run_once("mission-1")

        self.assertEqual(result.status, CoordinatorStatus.WAITING_FOR_USER)
        self.assertEqual(
            set(result.__dataclass_fields__),
            {"mission_id", "status", "summary", "task_id", "attempt_id"},
        )
        self.assertNotIn("provider", repr(result).lower())
        self.assertNotIn("model", repr(result).lower())
        self.assertNotIn("token", repr(result).lower())


if __name__ == "__main__":
    unittest.main()

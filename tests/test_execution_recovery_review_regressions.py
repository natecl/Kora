from __future__ import annotations

import subprocess
import tempfile
import threading
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from kora.execution import (
    CoordinatorStatus,
    ExecutionCoordinator,
    MappingRuntimeResolver,
    MappingTaskSpecProvider,
    PermissionRequirement,
    TaskExecutionSpec,
)
from kora.mission import (
    ArtifactKind,
    AttemptStatus,
    CheckpointType,
    ConflictError,
    EvidenceKind,
    InvalidTransitionError,
    MissionService,
    MissionState,
    PermissionAction,
    PermissionMode,
    Task,
    TaskStatus,
    ValidationError,
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
    RoleCharter,
    TaskProfile,
    WorkforceCompiler,
)


BASE_TIME = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


class ScriptedRuntime:
    """A deterministic runtime fake with an observable call boundary."""

    def __init__(self, *outcomes: object) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[RuntimeJob] = []
        self._lock = threading.Lock()

    def run(self, job: RuntimeJob) -> RuntimeResult:
        with self._lock:
            self.calls.append(job)
            outcome = self.outcomes.pop(0) if self.outcomes else self._completed(job)
        if isinstance(outcome, BaseException):
            raise outcome
        if not isinstance(outcome, RuntimeResult):
            raise TypeError("scripted outcome must be a RuntimeResult")
        return outcome

    @staticmethod
    def _completed(job: RuntimeJob) -> RuntimeResult:
        return RuntimeResult(
            mission_id=job.mission_id,
            task_id=job.task_id,
            status=RuntimeStatus.COMPLETED,
            response="runtime completed",
            exit_code=0,
        )


class BlockingRuntime(ScriptedRuntime):
    """A runtime that makes the stop and file-store races deterministic."""

    def __init__(self, outcome: object) -> None:
        super().__init__(outcome)
        self.entered = threading.Event()
        self.release = threading.Event()

    def run(self, job: RuntimeJob) -> RuntimeResult:
        self.entered.set()
        if not self.release.wait(timeout=10):
            raise RuntimeError("blocking runtime was not released by the test")
        return super().run(job)


class StaticVerifier:
    def __init__(self, result: object) -> None:
        self.result = result
        self.requests: list[WorkspaceVerificationRequest] = []

    def verify(self, request: WorkspaceVerificationRequest) -> object:
        self.requests.append(request)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class SynchronizedRouter:
    """Release two coordinators only after both have selected the task route."""

    def __init__(self, routes: list[ModelRoute], barrier: threading.Barrier) -> None:
        self._router = ModelRouter(routes)
        self._barrier = barrier

    def select(
        self,
        task: Any,
        excluded_route_ids: Any = None,
        **kwargs: Any,
    ) -> Any:
        self._barrier.wait(timeout=10)
        return self._router.select(
            task,
            excluded_route_ids=excluded_route_ids,
            **kwargs,
        )

    def record_observation(self, observation: Any) -> None:
        self._router.record_observation(observation)


class CrashAfterSuccessfulVerification(BaseException):
    """A process-crash stand-in that is not caught by coordinator recovery."""


class CrashBeforeTaskFinalizationService(MissionService):
    def __init__(self) -> None:
        super().__init__()
        self.crash_before_task_finalization = True

    def complete_task(
        self,
        task_id: str,
        *,
        expected_revision: int | None = None,
        at: datetime | None = None,
    ) -> Task:
        if self.crash_before_task_finalization:
            self.crash_before_task_finalization = False
            raise CrashAfterSuccessfulVerification()
        return super().complete_task(
            task_id,
            expected_revision=expected_revision,
            at=at,
        )


class FailSecondAuthorizationService(MissionService):
    def __init__(self) -> None:
        super().__init__()
        self.authorization_calls = 0

    def authorize_action(self, *args: Any, **kwargs: Any) -> Any:
        self.authorization_calls += 1
        if self.authorization_calls == 2:
            raise ConflictError("injected second-authority failure")
        return super().authorize_action(*args, **kwargs)


class FinalizationStateService(MissionService):
    def __init__(self, target_state: MissionState) -> None:
        super().__init__()
        if target_state not in {MissionState.STOPPED, MissionState.WAITING_FOR_USER}:
            raise ValueError("finalization state must stop or wait")
        self.target_state = target_state
        self.transitioned = False
        self.evidence_count_after_transition: int | None = None

    def record_checkpoint(
        self,
        mission_id: str,
        kind: CheckpointType,
        summary: str,
        *,
        task_id: str | None = None,
        checkpoint_id: str | None = None,
        created_at: datetime | None = None,
    ) -> Any:
        checkpoint = super().record_checkpoint(
            mission_id,
            kind,
            summary,
            task_id=task_id,
            checkpoint_id=checkpoint_id,
            created_at=created_at,
        )
        if not self.transitioned:
            self.transitioned = True
            if self.target_state is MissionState.STOPPED:
                self.stop_mission(
                    mission_id,
                    reason="stop arrived during finalization",
                    at=BASE_TIME + timedelta(hours=1),
                )
            else:
                self.wait_for_user(mission_id, at=BASE_TIME + timedelta(hours=1))
            self.evidence_count_after_transition = len(
                self.store.list_evidence(mission_id)
            )
        return checkpoint


class ExecutionRecoveryReviewRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.service = MissionService()
        self.mission, self.task = self._create_active_mission(
            self.service, "mission-1", "task-1"
        )

    def tearDown(self) -> None:
        self.service.close()
        self.tempdir.cleanup()

    @staticmethod
    def _create_active_mission(
        service: MissionService,
        mission_id: str,
        task_id: str,
    ) -> tuple[Any, Task]:
        service.create_mission(
            "Execution mission",
            "Complete the approved execution slice.",
            "Every task is changed and independently verified.",
            mission_id=mission_id,
            created_at=BASE_TIME,
        )
        service.align_mission(mission_id, at=BASE_TIME + timedelta(seconds=1))
        service.activate_mission(mission_id, at=BASE_TIME + timedelta(seconds=2))
        task = service.add_task(
            mission_id,
            "Build the slice",
            description="Implement the approved execution slice.",
            task_id=task_id,
            created_at=BASE_TIME + timedelta(seconds=3),
        )
        return service.get_mission(mission_id), task

    @staticmethod
    def _runtime_result(
        mission_id: str,
        task_id: str,
        status: RuntimeStatus,
        response: str = "runtime response",
    ) -> RuntimeResult:
        return RuntimeResult(
            mission_id=mission_id,
            task_id=task_id,
            status=status,
            response=response,
            exit_code=0 if status is not RuntimeStatus.FAILED else 1,
            total_tokens=11,
            estimated_cost_usd=0.02,
        )

    @staticmethod
    def _accepted_verification() -> WorkspaceVerificationResult:
        return WorkspaceVerificationResult(
            accepted=True,
            summary="Independent checks accepted the workspace.",
            change_fingerprint="fingerprint",
            checks=(),
            artifacts=(
                VerificationArtifact(
                    name="verified output",
                    locator="workspace://verified-output",
                    artifact_kind=ArtifactKind.DIFF,
                    evidence_kind=EvidenceKind.ARTIFACT,
                    summary="The workspace output is available.",
                ),
            ),
        )

    @staticmethod
    def _spec(
        task: Task,
        workspace: Path,
        *,
        capabilities: frozenset[Capability] = frozenset(),
        permissions: tuple[PermissionRequirement, ...] = (),
    ) -> TaskExecutionSpec:
        profile = TaskProfile(
            task_id=task.task_id,
            task_class="implementation",
            objective=task.description or task.title,
            required_capabilities=frozenset(
                capability.value for capability in capabilities
            ),
        )
        return TaskExecutionSpec(
            profile=profile,
            instructions="Implement only the approved task.",
            workspace=workspace,
            runtime_capabilities=capabilities,
            toolsets=(),
            skills=("workspace-skill",),
            isolation=IsolationMode.CLOUD_SANDBOX,
            permission_requirements=permissions,
            verification_commands=(),
            require_changes=True,
        )

    @staticmethod
    def _route(
        route_id: str,
        *,
        fixed_cost_usd: float,
        capabilities: frozenset[Capability] = frozenset(),
    ) -> ModelRoute:
        return ModelRoute(
            route_id=route_id,
            provider_ref=f"provider-{route_id}",
            model_ref=f"model-{route_id}",
            supported_capabilities=frozenset(
                capability.value for capability in capabilities
            ),
            predicted_quality=1.0,
            reliability=1.0,
            fixed_cost_usd=fixed_cost_usd,
        )

    def _coordinator(
        self,
        service: MissionService,
        spec: TaskExecutionSpec,
        runtimes: dict[str, Any],
        routes: list[ModelRoute],
        *,
        verifier: object | None = None,
        lease_owner: str = "test-coordinator",
        lease_seconds: float = 30.0,
        max_attempts: int = 3,
        router: Any | None = None,
    ) -> ExecutionCoordinator:
        role = RoleCharter(
            role_id="role-domain-operator",
            title="Domain operator",
            responsibilities=("Perform the bounded task",),
            non_responsibilities=("Create a new mission",),
            allowed_capabilities=frozenset(
                capability.value for capability in spec.runtime_capabilities
            ),
        )
        return ExecutionCoordinator(
            service,
            role,
            WorkforceCompiler(max_attempts=max_attempts),
            router if router is not None else ModelRouter(routes),
            MappingTaskSpecProvider({spec.profile.task_id: spec}),
            MappingRuntimeResolver(runtimes),
            verifier if verifier is not None else StaticVerifier(self._accepted_verification()),
            lease_owner,
            lease_seconds,
            max_attempts,
        )

    @staticmethod
    def _seed_verifying(
        service: MissionService,
        task: Task,
        *,
        attempt_id: str,
        at: datetime = BASE_TIME,
    ) -> Any:
        service.start_task(task.task_id, at=at)
        attempt = service.create_attempt(
            task.mission_id,
            task.task_id,
            f"seed-{attempt_id}",
            worker_role_id="seed-role",
            route_id="route",
            attempt_id=attempt_id,
            created_at=at,
        )
        claimed = service.claim_attempt(
            attempt.attempt_id,
            "live-worker",
            lease_expires_at=at + timedelta(seconds=10),
            at=at,
        )
        verifying = service.begin_attempt_verification(
            claimed.attempt_id,
            lease_owner="live-worker",
            fencing_token=claimed.fencing_token,
            at=at + timedelta(seconds=1),
        )
        service.begin_task_verification(task.task_id, at=at + timedelta(seconds=1))
        return verifying

    def test_invariant_1_verifying_terminalization_requires_live_fence(self) -> None:
        operations = ("succeed", "fail", "interrupt")
        cases = (
            ("missing fence", "active", {}),
            (
                "stale owner",
                "active",
                {"lease_owner": "stale-worker", "fencing_token": 1},
            ),
            (
                "stale fencing token",
                "active",
                {"lease_owner": "live-worker", "fencing_token": 2},
            ),
            (
                "expired lease",
                "expired",
                {"lease_owner": "live-worker", "fencing_token": 1},
            ),
        )

        for operation in operations:
            for case_name, timing, fence in cases:
                with self.subTest(operation=operation, case=case_name):
                    service = MissionService()
                    try:
                        _, task = self._create_active_mission(
                            service,
                            f"{operation}-{timing}-mission",
                            f"{operation}-{timing}-task",
                        )
                        attempt = self._seed_verifying(
                            service,
                            task,
                            attempt_id=f"{operation}-{timing}-attempt",
                        )
                        assert attempt.lease_expires_at is not None
                        at = (
                            BASE_TIME + timedelta(seconds=11)
                            if timing == "expired"
                            else BASE_TIME + timedelta(seconds=2)
                        )
                        with self.assertRaises((ConflictError, ValidationError)):
                            if operation == "succeed":
                                service.succeed_attempt(
                                    attempt.attempt_id,
                                    result_summary="accepted",
                                    at=at,
                                    **fence,
                                )
                            elif operation == "fail":
                                service.fail_attempt(
                                    attempt.attempt_id,
                                    error_summary="rejected",
                                    at=at,
                                    **fence,
                                )
                            else:
                                service.interrupt_attempt(
                                    attempt.attempt_id,
                                    reason="interrupted",
                                    at=at,
                                    **fence,
                                )
                        self.assertEqual(
                            service.get_attempt(attempt.attempt_id).status,
                            AttemptStatus.VERIFYING,
                        )
                    finally:
                        service.close()

    def test_invariant_2_stop_invalidates_live_attempt_and_blocks_late_runtime(self) -> None:
        spec = self._spec(self.task, self.workspace)
        runtime = BlockingRuntime(
            self._runtime_result("mission-1", "task-1", RuntimeStatus.COMPLETED)
        )
        coordinator = self._coordinator(
            self.service,
            spec,
            {"route": runtime},
            [self._route("route", fixed_cost_usd=0.10)],
        )
        result_holder: dict[str, Any] = {}
        error_holder: dict[str, BaseException] = {}

        def run() -> None:
            try:
                result_holder["result"] = coordinator.run_once("mission-1")
            except BaseException as exc:  # the fake models a process boundary
                error_holder["error"] = exc

        worker = threading.Thread(target=run)
        worker.start()
        try:
            self.assertTrue(runtime.entered.wait(timeout=5))
            live_attempts = self.service.store.list_attempts("mission-1", "task-1")
            self.assertEqual(len(live_attempts), 1)
            self.assertEqual(live_attempts[0].status, AttemptStatus.RUNNING)

            self.service.stop_mission(
                "mission-1",
                reason="user stopped the mission while runtime was blocked",
                at=BASE_TIME + timedelta(minutes=1),
            )
            self.assertEqual(
                self.service.get_attempt(live_attempts[0].attempt_id).status,
                AttemptStatus.INTERRUPTED,
            )
        finally:
            runtime.release.set()
            worker.join(timeout=10)

        self.assertFalse(worker.is_alive())
        final_attempt = self.service.get_attempt(live_attempts[0].attempt_id)
        self.assertNotEqual(final_attempt.status, AttemptStatus.SUCCEEDED)
        self.assertIsNot(final_attempt.accepted, True)
        self.assertNotEqual(
            self.service.get_task("task-1").state,
            TaskStatus.COMPLETED,
        )
        self.assertEqual(self.service.get_mission("mission-1").state, MissionState.STOPPED)
        if "result" in result_holder:
            self.assertNotIn(
                result_holder["result"].status,
                {CoordinatorStatus.TASK_COMPLETED, CoordinatorStatus.MISSION_COMPLETED},
            )

    def test_invariant_3_durable_success_recovers_without_another_runtime_call(self) -> None:
        service = CrashBeforeTaskFinalizationService()
        try:
            mission, task = self._create_active_mission(
                service, "crash-mission", "crash-task"
            )
            spec = self._spec(task, self.workspace)
            runtime = ScriptedRuntime(
                self._runtime_result(
                    mission.mission_id,
                    task.task_id,
                    RuntimeStatus.COMPLETED,
                )
            )
            verifier = StaticVerifier(self._accepted_verification())
            coordinator = self._coordinator(
                service,
                spec,
                {"route": runtime},
                [self._route("route", fixed_cost_usd=0.10)],
                verifier=verifier,
            )

            with self.assertRaises(CrashAfterSuccessfulVerification):
                coordinator.run_once(mission.mission_id)

            attempts_before_recovery = service.store.list_attempts(
                mission.mission_id, task.task_id
            )
            self.assertEqual(len(attempts_before_recovery), 1)
            self.assertEqual(attempts_before_recovery[0].status, AttemptStatus.SUCCEEDED)
            self.assertEqual(service.get_task(task.task_id).state, TaskStatus.VERIFYING)
            self.assertEqual(
                len(
                    [
                        evidence
                        for evidence in service.store.list_evidence(mission.mission_id)
                        if evidence.task_id == task.task_id
                        and evidence.verified_at is not None
                    ]
                ),
                1,
            )

            recovered = self._coordinator(
                service,
                spec,
                {"route": runtime},
                [self._route("route", fixed_cost_usd=0.10)],
                verifier=verifier,
            ).run_once(mission.mission_id)

            self.assertEqual(recovered.status, CoordinatorStatus.MISSION_COMPLETED)
            self.assertEqual(len(runtime.calls), 1)
            self.assertEqual(
                service.store.list_attempts(mission.mission_id, task.task_id),
                attempts_before_recovery,
            )
            self.assertEqual(service.get_task(task.task_id).state, TaskStatus.COMPLETED)
            self.assertEqual(service.get_mission(mission.mission_id).state, MissionState.COMPLETED)
        finally:
            service.close()

    def test_invariant_4_approve_once_replays_across_route_fallback(self) -> None:
        grant = self.service.grant_permission(
            "mission-1",
            PermissionAction.WRITE_WORKSPACE,
            str(self.workspace),
            "Modify the approved workspace.",
            mode=PermissionMode.APPROVE_ONCE,
            grant_id="grant-once",
        )
        requirement = PermissionRequirement(
            grant.grant_id,
            PermissionAction.WRITE_WORKSPACE,
            str(self.workspace),
            spent_cents=7,
        )
        spec = self._spec(
            self.task,
            self.workspace,
            capabilities=frozenset({Capability.WORKSPACE_WRITE}),
            permissions=(requirement,),
        )
        cheap = ScriptedRuntime(
            self._runtime_result("mission-1", "task-1", RuntimeStatus.FAILED, "cheap failed")
        )
        fallback = ScriptedRuntime(
            self._runtime_result("mission-1", "task-1", RuntimeStatus.COMPLETED)
        )
        result = self._coordinator(
            self.service,
            spec,
            {"cheap": cheap, "fallback": fallback},
            [
                self._route("cheap", fixed_cost_usd=0.01, capabilities=spec.runtime_capabilities),
                self._route("fallback", fixed_cost_usd=0.20, capabilities=spec.runtime_capabilities),
            ],
            max_attempts=2,
        ).run_once("mission-1")

        self.assertEqual(result.status, CoordinatorStatus.MISSION_COMPLETED)
        attempts = self.service.store.list_attempts("mission-1", "task-1")
        self.assertEqual([attempt.route_id for attempt in attempts], ["cheap", "fallback"])
        self.assertEqual(
            [attempt.status for attempt in attempts],
            [AttemptStatus.FAILED, AttemptStatus.SUCCEEDED],
        )
        persisted = self.service.store.get_permission_grant(grant.grant_id)
        assert persisted is not None
        self.assertEqual((persisted.actions_used, persisted.spent_cents), (1, 7))
        uses = self.service.store.connection.execute(
            "SELECT COUNT(*) FROM permission_uses WHERE grant_id = ?",
            (grant.grant_id,),
        ).fetchone()
        assert uses is not None
        self.assertEqual(uses[0], 1)
        self.assertEqual(len(cheap.calls), 1)
        self.assertEqual(len(fallback.calls), 1)

    def test_invariant_5_multiple_permission_requirements_are_all_or_none(self) -> None:
        service = FailSecondAuthorizationService()
        try:
            mission, task = self._create_active_mission(
                service, "authority-mission", "authority-task"
            )
            first = service.grant_permission(
                mission.mission_id,
                PermissionAction.WRITE_WORKSPACE,
                str(self.workspace),
                "Modify the workspace.",
                mode=PermissionMode.APPROVE_ONCE,
                grant_id="grant-first",
            )
            second = service.grant_permission(
                mission.mission_id,
                PermissionAction.EXECUTE_WORKSPACE,
                str(self.workspace),
                "Run the approved checks.",
                mode=PermissionMode.APPROVE_ONCE,
                grant_id="grant-second",
            )
            spec = self._spec(
                task,
                self.workspace,
                capabilities=frozenset(
                    {Capability.WORKSPACE_WRITE, Capability.WORKSPACE_EXECUTE}
                ),
                permissions=(
                    PermissionRequirement(
                        first.grant_id,
                        first.action,
                        first.resource,
                        spent_cents=5,
                    ),
                    PermissionRequirement(
                        second.grant_id,
                        second.action,
                        second.resource,
                        spent_cents=9,
                    ),
                ),
            )
            runtime = ScriptedRuntime(
                self._runtime_result(
                    mission.mission_id,
                    task.task_id,
                    RuntimeStatus.COMPLETED,
                )
            )

            result = self._coordinator(
                service,
                spec,
                {"route": runtime},
                [self._route("route", fixed_cost_usd=0.10, capabilities=spec.runtime_capabilities)],
            ).run_once(mission.mission_id)

            self.assertEqual(result.status, CoordinatorStatus.WAITING_FOR_USER)
            first_after = service.store.get_permission_grant(first.grant_id)
            second_after = service.store.get_permission_grant(second.grant_id)
            assert first_after is not None
            assert second_after is not None
            self.assertEqual((first_after.actions_used, first_after.spent_cents), (0, 0))
            self.assertEqual((second_after.actions_used, second_after.spent_cents), (0, 0))
            uses = service.store.connection.execute(
                "SELECT COUNT(*) FROM permission_uses WHERE grant_id IN (?, ?)",
                (first.grant_id, second.grant_id),
            ).fetchone()
            assert uses is not None
            self.assertEqual(uses[0], 0)
            self.assertEqual(runtime.calls, [])
        finally:
            service.close()

    def test_invariant_6_changed_idempotency_replays_conflict_without_counter_mutation(self) -> None:
        for index, changed in enumerate(((3, 30), (2, 31)), start=1):
            with self.subTest(changed=changed):
                grant = self.service.grant_permission(
                    "mission-1",
                    PermissionAction.SPEND,
                    "budget/mission-1",
                    "Spend only the approved budget.",
                    mode=PermissionMode.BOUNDED_INDEFINITE,
                    scope="this mission only",
                    max_actions=10,
                    budget_limit_cents=100,
                    grant_id=f"grant-replay-{index}",
                )
                self.service.authorize_action(
                    "mission-1",
                    grant.grant_id,
                    PermissionAction.SPEND,
                    "budget/mission-1",
                    idempotency_key=f"replay-key-{index}",
                    action_count=2,
                    spent_cents=30,
                )
                before = self.service.store.get_permission_grant(grant.grant_id)
                assert before is not None

                with self.assertRaises(ConflictError):
                    self.service.authorize_action(
                        "mission-1",
                        grant.grant_id,
                        PermissionAction.SPEND,
                        "budget/mission-1",
                        idempotency_key=f"replay-key-{index}",
                        action_count=changed[0],
                        spent_cents=changed[1],
                    )

                self.assertEqual(
                    self.service.store.get_permission_grant(grant.grant_id),
                    before,
                )

    def test_invariant_7_durable_created_attempt_is_claimed_and_resumed(self) -> None:
        attempt = self.service.create_attempt(
            "mission-1",
            "task-1",
            "durable-created-attempt",
            worker_role_id="durable-role",
            route_id="route",
            attempt_id="durable-created",
            created_at=BASE_TIME + timedelta(minutes=1),
        )
        spec = self._spec(self.task, self.workspace)
        runtime = ScriptedRuntime(
            self._runtime_result("mission-1", "task-1", RuntimeStatus.COMPLETED)
        )

        result = self._coordinator(
            self.service,
            spec,
            {"route": runtime},
            [self._route("route", fixed_cost_usd=0.10)],
        ).run_once("mission-1")

        self.assertEqual(result.status, CoordinatorStatus.MISSION_COMPLETED)
        self.assertEqual(len(runtime.calls), 1)
        attempts = self.service.store.list_attempts("mission-1", "task-1")
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0].attempt_id, attempt.attempt_id)
        self.assertEqual(attempts[0].status, AttemptStatus.SUCCEEDED)
        self.assertEqual(self.service.get_task("task-1").state, TaskStatus.COMPLETED)

    def test_invariant_8_unknown_to_verifying_resumes_verification_without_runtime(self) -> None:
        self.service.start_task("task-1", at=BASE_TIME)
        created = self.service.create_attempt(
            "mission-1",
            "task-1",
            "unknown-recovery-attempt",
            worker_role_id="unknown-role",
            route_id="route",
            attempt_id="unknown-recovery",
            created_at=BASE_TIME,
        )
        claimed = self.service.claim_attempt(
            created.attempt_id,
            "unknown-worker",
            lease_expires_at=BASE_TIME + timedelta(seconds=10),
            at=BASE_TIME,
        )
        unknown = self.service.mark_expired_attempt_unknown(
            claimed.attempt_id,
            expected_revision=claimed.revision,
            at=BASE_TIME + timedelta(seconds=11),
        )
        runtime = ScriptedRuntime()
        verifier = StaticVerifier(self._accepted_verification())

        try:
            reconciled = self.service.reconcile_unknown(
                unknown.attempt_id,
                target=AttemptStatus.VERIFYING,
                at=BASE_TIME + timedelta(seconds=12),
            )
        except (ConflictError, InvalidTransitionError, ValidationError):
            self.assertEqual(
                self.service.get_attempt(unknown.attempt_id).status,
                AttemptStatus.UNKNOWN,
            )
            self.assertEqual(runtime.calls, [])
            return

        self.assertEqual(reconciled.status, AttemptStatus.VERIFYING)
        self.service.begin_task_verification(
            "task-1", at=BASE_TIME + timedelta(seconds=12)
        )
        spec = self._spec(self.task, self.workspace)
        result = self._coordinator(
            self.service,
            spec,
            {"route": runtime},
            [self._route("route", fixed_cost_usd=0.10)],
            verifier=verifier,
        ).run_once("mission-1")

        self.assertEqual(result.status, CoordinatorStatus.MISSION_COMPLETED)
        self.assertEqual(runtime.calls, [])
        self.assertEqual(len(verifier.requests), 1)
        self.assertEqual(
            self.service.get_attempt(unknown.attempt_id).status,
            AttemptStatus.SUCCEEDED,
        )

    def test_invariant_9_stop_or_wait_during_finalization_cannot_complete_or_add_coverage(self) -> None:
        for target_state in (MissionState.STOPPED, MissionState.WAITING_FOR_USER):
            with self.subTest(target_state=target_state):
                service = FinalizationStateService(target_state)
                try:
                    mission, task = self._create_active_mission(
                        service,
                        f"finalization-{target_state.value}-mission",
                        f"finalization-{target_state.value}-task",
                    )
                    spec = self._spec(task, self.workspace)
                    runtime = ScriptedRuntime(
                        self._runtime_result(
                            mission.mission_id,
                            task.task_id,
                            RuntimeStatus.COMPLETED,
                        )
                    )
                    result: Any | None = None
                    try:
                        result = self._coordinator(
                            service,
                            spec,
                            {"route": runtime},
                            [self._route("route", fixed_cost_usd=0.10)],
                        ).run_once(mission.mission_id)
                    except BaseException:
                        # A stop/wait race may abort the tick, but it must not
                        # turn into a successful semantic outcome or a write.
                        pass

                    self.assertEqual(service.get_mission(mission.mission_id).state, target_state)
                    self.assertIsNotNone(service.evidence_count_after_transition)
                    self.assertEqual(
                        len(service.store.list_evidence(mission.mission_id)),
                        service.evidence_count_after_transition,
                    )
                    self.assertFalse(
                        any(
                            evidence.kind is EvidenceKind.REQUIREMENT_COVERAGE
                            for evidence in service.store.list_evidence(mission.mission_id)
                        )
                    )
                    if result is not None:
                        self.assertNotEqual(
                            result.status,
                            CoordinatorStatus.MISSION_COMPLETED,
                        )
                finally:
                    service.close()

    def test_invariant_10_file_backed_coordinators_have_one_winner_and_busy_loser(self) -> None:
        database = self.root / "racing.sqlite3"
        first_service = MissionService(database)
        second_service = MissionService(database)
        try:
            mission, task = self._create_active_mission(
                first_service, "racing-mission", "racing-task"
            )
            spec = self._spec(task, self.workspace)
            runtime_a = BlockingRuntime(
                self._runtime_result(
                    mission.mission_id,
                    task.task_id,
                    RuntimeStatus.COMPLETED,
                )
            )
            runtime_b = BlockingRuntime(
                self._runtime_result(
                    mission.mission_id,
                    task.task_id,
                    RuntimeStatus.COMPLETED,
                )
            )
            start = threading.Barrier(2)
            route_selection = threading.Barrier(2)
            coordinator_a = self._coordinator(
                first_service,
                spec,
                {"route": runtime_a},
                [self._route("route", fixed_cost_usd=0.10)],
                lease_owner="coordinator-a",
                router=SynchronizedRouter(
                    [self._route("route", fixed_cost_usd=0.10)], route_selection
                ),
            )
            coordinator_b = self._coordinator(
                second_service,
                spec,
                {"route": runtime_b},
                [self._route("route", fixed_cost_usd=0.10)],
                lease_owner="coordinator-b",
                router=SynchronizedRouter(
                    [self._route("route", fixed_cost_usd=0.10)], route_selection
                ),
            )
            one_finished = threading.Event()
            results: dict[str, Any] = {}
            errors: dict[str, BaseException] = {}

            def run(label: str, coordinator: ExecutionCoordinator) -> None:
                try:
                    start.wait(timeout=10)
                    results[label] = coordinator.run_once(mission.mission_id)
                except BaseException as exc:
                    errors[label] = exc
                finally:
                    one_finished.set()

            threads = [
                threading.Thread(target=run, args=("a", coordinator_a)),
                threading.Thread(target=run, args=("b", coordinator_b)),
            ]
            for thread in threads:
                thread.start()
            try:
                self.assertTrue(
                    runtime_a.entered.wait(timeout=5)
                    or runtime_b.entered.wait(timeout=5)
                )
                self.assertTrue(one_finished.wait(timeout=5))
            finally:
                runtime_a.release.set()
                runtime_b.release.set()
                for thread in threads:
                    thread.join(timeout=10)

            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual(errors, {})
            self.assertEqual(len(results), 2)
            self.assertEqual(
                {result.status for result in results.values()},
                {CoordinatorStatus.MISSION_COMPLETED, CoordinatorStatus.BUSY},
            )
            self.assertEqual(len(runtime_a.calls) + len(runtime_b.calls), 1)
            persisted_attempts = first_service.store.list_attempts(
                mission.mission_id, task.task_id
            )
            self.assertEqual(len(persisted_attempts), 1)
            self.assertEqual(persisted_attempts[0].status, AttemptStatus.SUCCEEDED)
            self.assertEqual(
                first_service.get_mission(mission.mission_id).state,
                MissionState.COMPLETED,
            )
        finally:
            first_service.close()
            second_service.close()


if __name__ == "__main__":
    unittest.main()

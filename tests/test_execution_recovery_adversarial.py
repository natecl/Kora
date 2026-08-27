from __future__ import annotations

import subprocess
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

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
    EscalationStatus,
    EvidenceKind,
    EventType,
    Mission,
    MissionService,
    MissionState,
    PermissionAction,
    PermissionMode,
    Task,
    TaskAttempt,
    TaskStatus,
)
from kora.runtime import (
    Capability,
    IsolationMode,
    RuntimeJob,
    RuntimeResult,
    RuntimeStatus,
)
from kora.verification import VerificationArtifact, WorkspaceVerificationResult
from kora.workforce import ModelRoute, ModelRouter, RoleCharter, TaskProfile, WorkforceCompiler


BASE_TIME = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


class DeterministicRuntime:
    """A fake runtime whose calls, mutations, and outcomes are fully scripted."""

    def __init__(self, *outcomes: object, mutate: bool = False) -> None:
        self.outcomes = list(outcomes)
        self.mutate = mutate
        self.calls: list[RuntimeJob] = []

    def run(self, job: RuntimeJob) -> RuntimeResult:
        self.calls.append(job)
        if self.mutate:
            (job.workspace / "runtime-mutated.txt").write_text(
                "runtime changed the disposable workspace\n",
                encoding="utf-8",
            )
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
            raise TypeError("scripted outcome must be a RuntimeResult")
        return outcome


class DeterministicVerifier:
    def __init__(self, result: object) -> None:
        self.result = result
        self.requests: list[Any] = []

    def verify(self, request: object) -> object:
        self.requests.append(request)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class ExecutionRecoveryAdversarialTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.workspace = self._git_workspace(self.root / "workspace")
        self.service = MissionService()
        self.mission, self.task = self._create_active_mission(
            self.service, "mission-1", "task-1"
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

    @staticmethod
    def _create_active_mission(
        service: MissionService,
        mission_id: str,
        task_id: str | None,
    ) -> tuple[Mission, Task | None]:
        mission = service.create_mission(
            "Execution mission",
            "Complete the approved execution slice.",
            "Every task is changed and independently verified.",
            mission_id=mission_id,
            created_at=BASE_TIME,
        )
        service.align_mission(mission_id, at=BASE_TIME + timedelta(seconds=1))
        service.activate_mission(mission_id, at=BASE_TIME + timedelta(seconds=2))
        if task_id is None:
            return mission, None
        task = service.add_task(
            mission_id,
            "Build the slice",
            description="Implement the approved execution slice.",
            task_id=task_id,
            created_at=BASE_TIME + timedelta(seconds=3),
        )
        return mission, task

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

    def _spec(
        self,
        task: Task | None = None,
        *,
        capabilities: frozenset[Capability] = frozenset(),
        permissions: tuple[PermissionRequirement, ...] = (),
        require_changes: bool = True,
    ) -> TaskExecutionSpec:
        selected_task = self.task if task is None else task
        objective = selected_task.description or selected_task.title
        profile = TaskProfile(
            task_id=selected_task.task_id,
            task_class="implementation",
            objective=objective,
            required_capabilities=frozenset(
                capability.value for capability in capabilities
            ),
        )
        return TaskExecutionSpec(
            profile=profile,
            instructions="Implement only the approved task.",
            workspace=self.workspace,
            runtime_capabilities=capabilities,
            toolsets=(),
            skills=("workspace-skill",),
            isolation=IsolationMode.CLOUD_SANDBOX,
            permission_requirements=permissions,
            verification_commands=(),
            require_changes=require_changes,
        )

    @staticmethod
    def _route(
        route_id: str,
        *,
        fixed_cost_usd: float,
        capabilities: frozenset[Capability] = frozenset(),
        enabled: bool = True,
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
            enabled=enabled,
        )

    def _coordinator(
        self,
        specs: dict[str, TaskExecutionSpec],
        runtimes: dict[str, DeterministicRuntime],
        routes: list[ModelRoute],
        *,
        service: MissionService | None = None,
        verifier: object | None = None,
        max_attempts: int = 3,
        lease_seconds: float = 30.0,
    ) -> ExecutionCoordinator:
        selected_service = self.service if service is None else service
        capabilities = frozenset(
            capability
            for spec in specs.values()
            for capability in spec.runtime_capabilities
        )
        role = RoleCharter(
            role_id="role-domain-operator",
            title="Domain operator",
            responsibilities=("Perform the bounded task",),
            non_responsibilities=("Create a new mission",),
            allowed_capabilities=frozenset(capability.value for capability in capabilities),
        )
        return ExecutionCoordinator(
            selected_service,
            role,
            WorkforceCompiler(max_attempts=max_attempts),
            ModelRouter(routes),
            MappingTaskSpecProvider(specs),
            MappingRuntimeResolver(runtimes),
            verifier or DeterministicVerifier(self._accepted_verification()),
            "test-coordinator",
            lease_seconds,
            max_attempts,
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

    def _seed_attempt(
        self,
        service: MissionService,
        task: Task,
        *,
        attempt_id: str,
        route_id: str,
        at: datetime,
        task_state: TaskStatus,
    ) -> TaskAttempt:
        service.start_task(task.task_id, at=at)
        attempt = service.create_attempt(
            task.mission_id,
            task.task_id,
            f"seed-{attempt_id}",
            worker_role_id=f"seed-worker-{attempt_id}",
            route_id=route_id,
            attempt_id=attempt_id,
            created_at=at,
        )
        claimed = service.claim_attempt(
            attempt.attempt_id,
            "seed-worker",
            lease_expires_at=at + timedelta(seconds=30),
            at=at,
        )
        if task_state is TaskStatus.VERIFYING:
            verifying = service.begin_attempt_verification(
                claimed.attempt_id,
                lease_owner="seed-worker",
                fencing_token=claimed.fencing_token,
                at=at + timedelta(seconds=1),
            )
            service.begin_task_verification(
                task.task_id, at=at + timedelta(seconds=1)
            )
            return verifying
        return claimed

    def test_runtime_exception_recovery_marks_unknown_only_after_lease_expiry(self) -> None:
        spec = self._spec()
        runtime = DeterministicRuntime(
            RuntimeError("opaque runtime failure"), mutate=True
        )
        coordinator = self._coordinator(
            {self.task.task_id: spec},
            {"route": runtime},
            [self._route("route", fixed_cost_usd=0.10)],
            lease_seconds=30.0,
        )

        first = coordinator.run_once(self.mission.mission_id)

        self.assertEqual(first.status, CoordinatorStatus.UNKNOWN_OUTCOME)
        self.assertEqual(self.service.get_task(self.task.task_id).state, TaskStatus.IN_PROGRESS)
        attempts = self.service.store.list_attempts(self.mission.mission_id, self.task.task_id)
        self.assertEqual(len(attempts), 1)
        running = attempts[0]
        self.assertEqual(running.status, AttemptStatus.RUNNING)
        self.assertTrue(running.has_active_lease())
        self.assertEqual(
            (self.workspace / "runtime-mutated.txt").read_text(encoding="utf-8"),
            "runtime changed the disposable workspace\n",
        )

        assert running.lease_expires_at is not None
        before_expiry = running.lease_expires_at - timedelta(microseconds=1)
        after_expiry = running.lease_expires_at + timedelta(microseconds=1)
        with patch("kora.execution.coordinator.utc_now", return_value=before_expiry):
            busy = coordinator.run_once(self.mission.mission_id)
        self.assertEqual(busy.status, CoordinatorStatus.BUSY)
        self.assertEqual(len(runtime.calls), 1)
        self.assertEqual(len(self.service.store.list_attempts(self.mission.mission_id)), 1)

        with patch("kora.execution.coordinator.utc_now", return_value=after_expiry):
            recovered = coordinator.run_once(self.mission.mission_id)
        self.assertEqual(recovered.status, CoordinatorStatus.UNKNOWN_OUTCOME)
        self.assertEqual(self.service.get_attempt(running.attempt_id).status, AttemptStatus.UNKNOWN)
        self.assertEqual(len(self.service.store.list_attempts(self.mission.mission_id)), 1)
        self.assertEqual(len(runtime.calls), 1)

    def test_expired_verifying_attempt_requires_reconciliation_before_rerun(self) -> None:
        seeded = self._seed_attempt(
            self.service,
            self.task,
            attempt_id="verifying-attempt",
            route_id="route",
            at=BASE_TIME + timedelta(minutes=1),
            task_state=TaskStatus.VERIFYING,
        )
        assert seeded.lease_expires_at is not None
        expired_at = seeded.lease_expires_at + timedelta(microseconds=1)
        runtime = DeterministicRuntime(
            self._runtime_result("mission-1", "task-1", RuntimeStatus.COMPLETED),
            mutate=True,
        )
        coordinator = self._coordinator(
            {self.task.task_id: self._spec()},
            {"route": runtime},
            [self._route("route", fixed_cost_usd=0.10)],
        )

        with patch("kora.execution.coordinator.utc_now", return_value=expired_at):
            first = coordinator.run_once(self.mission.mission_id)
            second = coordinator.run_once(self.mission.mission_id)

        self.assertEqual(first.status, CoordinatorStatus.UNKNOWN_OUTCOME)
        self.assertEqual(second.status, CoordinatorStatus.UNKNOWN_OUTCOME)
        self.assertEqual(self.service.get_attempt(seeded.attempt_id).status, AttemptStatus.UNKNOWN)
        self.assertEqual(self.service.get_task(self.task.task_id).state, TaskStatus.VERIFYING)
        self.assertEqual(self.service.store.list_attempts(self.mission.mission_id), [self.service.get_attempt(seeded.attempt_id)])
        self.assertEqual(runtime.calls, [])

    def test_two_stranded_tasks_are_busy_without_runtime_execution(self) -> None:
        second_task = self.service.add_task(
            self.mission.mission_id,
            "Review the slice",
            description="Review the approved execution slice.",
            task_id="task-2",
            created_at=BASE_TIME + timedelta(minutes=2),
        )
        first_seed = self._seed_attempt(
            self.service,
            self.task,
            attempt_id="failed-task-1",
            route_id="route-1",
            at=BASE_TIME + timedelta(minutes=3),
            task_state=TaskStatus.IN_PROGRESS,
        )
        self.service.fail_attempt(
            first_seed.attempt_id,
            error_summary="first task stranded before restart",
            lease_owner="seed-worker",
            fencing_token=first_seed.fencing_token,
            at=BASE_TIME + timedelta(minutes=3, seconds=1),
        )
        second_seed = self._seed_attempt(
            self.service,
            second_task,
            attempt_id="failed-task-2",
            route_id="route-2",
            at=BASE_TIME + timedelta(minutes=5),
            task_state=TaskStatus.VERIFYING,
        )
        self.service.fail_attempt(
            second_seed.attempt_id,
            error_summary="second task stranded during verification",
            lease_owner="seed-worker",
            fencing_token=second_seed.fencing_token,
            at=BASE_TIME + timedelta(minutes=5, seconds=1),
        )

        runtime = DeterministicRuntime()
        coordinator = self._coordinator(
            {
                self.task.task_id: self._spec(),
                second_task.task_id: self._spec(second_task),
            },
            {"route-1": runtime, "route-2": runtime},
            [self._route("route-1", fixed_cost_usd=0.10)],
        )

        result = coordinator.run_once(self.mission.mission_id)

        self.assertEqual(result.status, CoordinatorStatus.BUSY)
        self.assertEqual(runtime.calls, [])
        self.assertEqual(self.service.get_task(self.task.task_id).state, TaskStatus.IN_PROGRESS)
        self.assertEqual(self.service.get_task(second_task.task_id).state, TaskStatus.VERIFYING)
        self.assertEqual(
            [attempt.status for attempt in self.service.store.list_attempts(self.mission.mission_id)],
            [AttemptStatus.FAILED, AttemptStatus.FAILED],
        )

    def test_waiting_or_terminal_mission_tick_has_no_execution_side_effects(self) -> None:
        waiting_grant = self.service.grant_permission(
            self.mission.mission_id,
            PermissionAction.DEPLOY,
            "production/project",
            "Deploy the approved project.",
            mode=PermissionMode.BOUNDED_INDEFINITE,
            scope="this mission only",
            max_actions=2,
            grant_id="waiting-grant",
        )
        self.service.wait_for_user(
            self.mission.mission_id, at=BASE_TIME + timedelta(minutes=10)
        )
        waiting_runtime = DeterministicRuntime()
        waiting_coordinator = self._coordinator(
            {self.task.task_id: self._spec()},
            {"route": waiting_runtime},
            [self._route("route", fixed_cost_usd=0.10)],
        )
        waiting_before = {
            "attempts": self.service.store.list_attempts(self.mission.mission_id),
            "permissions": self.service.store.list_permission_grants(self.mission.mission_id),
            "evidence": self.service.store.list_evidence(self.mission.mission_id),
            "events": self.service.store.list_events(self.mission.mission_id),
        }

        waiting_result = waiting_coordinator.run_once(self.mission.mission_id)

        self.assertEqual(waiting_result.status, CoordinatorStatus.WAITING_FOR_USER)
        self.assertEqual(self.service.get_mission(self.mission.mission_id).state, MissionState.WAITING_FOR_USER)
        self.assertEqual(self.service.store.list_attempts(self.mission.mission_id), waiting_before["attempts"])
        self.assertEqual(self.service.store.list_permission_grants(self.mission.mission_id), waiting_before["permissions"])
        self.assertEqual(self.service.store.list_evidence(self.mission.mission_id), waiting_before["evidence"])
        self.assertEqual(self.service.store.list_events(self.mission.mission_id), waiting_before["events"])
        self.assertEqual(waiting_runtime.calls, [])
        self.assertEqual(waiting_grant.actions_used, 0)

        terminal_service = MissionService()
        try:
            terminal_mission, terminal_task = self._create_active_mission(
                terminal_service, "terminal-mission", "terminal-task"
            )
            assert terminal_task is not None
            terminal_grant = terminal_service.grant_permission(
                terminal_mission.mission_id,
                PermissionAction.DEPLOY,
                "production/project",
                "Deploy the approved project.",
                mode=PermissionMode.BOUNDED_INDEFINITE,
                scope="this mission only",
                max_actions=2,
                grant_id="terminal-grant",
            )
            terminal_service.stop_mission(
                terminal_mission.mission_id,
                reason="terminal adversarial fixture",
                at=BASE_TIME + timedelta(minutes=11),
            )
            terminal_runtime = DeterministicRuntime()
            terminal_coordinator = self._coordinator(
                {terminal_task.task_id: self._spec(terminal_task)},
                {"route": terminal_runtime},
                [self._route("route", fixed_cost_usd=0.10)],
                service=terminal_service,
            )
            terminal_before = {
                "attempts": terminal_service.store.list_attempts(terminal_mission.mission_id),
                "permissions": terminal_service.store.list_permission_grants(terminal_mission.mission_id),
                "evidence": terminal_service.store.list_evidence(terminal_mission.mission_id),
                "events": terminal_service.store.list_events(terminal_mission.mission_id),
            }

            terminal_result = terminal_coordinator.run_once(terminal_mission.mission_id)

            self.assertEqual(terminal_result.status, CoordinatorStatus.NO_WORK)
            self.assertEqual(terminal_service.get_mission(terminal_mission.mission_id).state, MissionState.STOPPED)
            self.assertEqual(terminal_service.store.list_attempts(terminal_mission.mission_id), terminal_before["attempts"])
            self.assertEqual(terminal_service.store.list_permission_grants(terminal_mission.mission_id), terminal_before["permissions"])
            self.assertEqual(terminal_service.store.list_evidence(terminal_mission.mission_id), terminal_before["evidence"])
            self.assertEqual(terminal_service.store.list_events(terminal_mission.mission_id), terminal_before["events"])
            self.assertEqual(terminal_runtime.calls, [])
            self.assertEqual(terminal_grant.actions_used, 0)
        finally:
            terminal_service.close()

    def test_runtime_needs_user_escalates_once_and_stays_waiting(self) -> None:
        runtime = DeterministicRuntime(
            self._runtime_result(
                self.mission.mission_id,
                self.task.task_id,
                RuntimeStatus.NEEDS_USER,
                "Choose the approved account.",
            )
        )
        coordinator = self._coordinator(
            {self.task.task_id: self._spec()},
            {"route": runtime},
            [self._route("route", fixed_cost_usd=0.10)],
        )

        first = coordinator.run_once(self.mission.mission_id)
        first_escalations = self.service.store.list_escalations(
            self.mission.mission_id, EscalationStatus.OPEN
        )
        first_events = self.service.store.list_events(self.mission.mission_id)
        second = coordinator.run_once(self.mission.mission_id)

        self.assertEqual(first.status, CoordinatorStatus.WAITING_FOR_USER)
        self.assertEqual(second.status, CoordinatorStatus.WAITING_FOR_USER)
        self.assertEqual(self.service.get_task(self.task.task_id).state, TaskStatus.NEEDS_USER)
        self.assertEqual(self.service.get_mission(self.mission.mission_id).state, MissionState.WAITING_FOR_USER)
        self.assertEqual(len(first_escalations), 1)
        self.assertEqual(
            self.service.store.list_escalations(
                self.mission.mission_id, EscalationStatus.OPEN
            ),
            first_escalations,
        )
        self.assertEqual(
            [event for event in first_events if event.event_type is EventType.ESCALATION_RECORDED],
            [event for event in self.service.store.list_events(self.mission.mission_id) if event.event_type is EventType.ESCALATION_RECORDED],
        )
        self.assertEqual(len(runtime.calls), 1)
        self.assertEqual(
            [attempt.status for attempt in self.service.store.list_attempts(self.mission.mission_id)],
            [AttemptStatus.INTERRUPTED],
        )

    def test_retry_exhaustion_and_no_eligible_fallback_do_not_fabricate_completion(self) -> None:
        first_runtime = DeterministicRuntime(
            self._runtime_result(
                self.mission.mission_id,
                self.task.task_id,
                RuntimeStatus.FAILED,
                "first route failed",
            )
        )
        coordinator = self._coordinator(
            {self.task.task_id: self._spec()},
            {"first": first_runtime, "disabled": DeterministicRuntime()},
            [
                self._route("first", fixed_cost_usd=0.01),
                self._route("disabled", fixed_cost_usd=0.02, enabled=False),
            ],
            max_attempts=2,
        )

        result = coordinator.run_once(self.mission.mission_id)

        self.assertEqual(result.status, CoordinatorStatus.RETRY_EXHAUSTED)
        self.assertEqual(self.service.get_task(self.task.task_id).state, TaskStatus.NEEDS_USER)
        self.assertEqual(self.service.get_mission(self.mission.mission_id).state, MissionState.WAITING_FOR_USER)
        attempts = self.service.store.list_attempts(self.mission.mission_id, self.task.task_id)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0].status, AttemptStatus.FAILED)
        self.assertEqual(self.service.store.list_evidence(self.mission.mission_id), [])
        self.assertEqual(len(first_runtime.calls), 1)
        self.assertFalse(
            any(
                event.event_type is EventType.EVIDENCE_RECORDED
                for event in self.service.store.list_events(self.mission.mission_id)
            )
        )
        self.assertFalse(
            any(
                event.event_type is EventType.MISSION_TRANSITIONED
                and event.payload.get("to") == MissionState.COMPLETED.value
                for event in self.service.store.list_events(self.mission.mission_id)
            )
        )

    def test_one_time_permission_replays_stable_authorization_across_route_attempts(self) -> None:
        grant = self.service.grant_permission(
            self.mission.mission_id,
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
        )
        spec = self._spec(
            capabilities=frozenset({Capability.WORKSPACE_WRITE}),
            permissions=(requirement,),
        )
        first = DeterministicRuntime(
            self._runtime_result(
                self.mission.mission_id,
                self.task.task_id,
                RuntimeStatus.FAILED,
                "cheap route failed",
            )
        )
        second = DeterministicRuntime(
            self._runtime_result(
                self.mission.mission_id,
                self.task.task_id,
                RuntimeStatus.COMPLETED,
            ),
            mutate=True,
        )
        coordinator = self._coordinator(
            {self.task.task_id: spec},
            {"cheap": first, "fallback": second},
            [
                self._route(
                    "cheap",
                    fixed_cost_usd=0.01,
                    capabilities=spec.runtime_capabilities,
                ),
                self._route(
                    "fallback",
                    fixed_cost_usd=0.20,
                    capabilities=spec.runtime_capabilities,
                ),
            ],
            max_attempts=2,
        )

        result = coordinator.run_once(self.mission.mission_id)

        self.assertEqual(result.status, CoordinatorStatus.MISSION_COMPLETED)
        attempts = self.service.store.list_attempts(self.mission.mission_id, self.task.task_id)
        self.assertEqual([attempt.route_id for attempt in attempts], ["cheap", "fallback"])
        self.assertEqual(
            [attempt.status for attempt in attempts],
            [AttemptStatus.FAILED, AttemptStatus.SUCCEEDED],
        )
        persisted_grant = self.service.store.get_permission_grant(grant.grant_id)
        assert persisted_grant is not None
        self.assertEqual(persisted_grant.actions_used, 1)
        uses = self.service.store.connection.execute(
            "SELECT idempotency_key FROM permission_uses WHERE grant_id = ?",
            (grant.grant_id,),
        ).fetchall()
        self.assertEqual(
            [row[0] for row in uses],
            [
                "authority:mission-1:task-1:grant-once:"
                "write_workspace:"
                + str(self.workspace)
            ],
        )
        permission_events = [
            event
            for event in self.service.store.list_events(self.mission.mission_id)
            if event.event_type is EventType.PERMISSION_CONSUMED
        ]
        self.assertEqual(len(permission_events), 1)
        self.assertEqual(len(first.calls), 1)
        self.assertEqual(len(second.calls), 1)

    def test_completed_mission_tick_has_no_new_records_or_runtime_work(self) -> None:
        runtime = DeterministicRuntime(
            self._runtime_result(
                self.mission.mission_id,
                self.task.task_id,
                RuntimeStatus.COMPLETED,
            ),
            mutate=True,
        )
        coordinator = self._coordinator(
            {self.task.task_id: self._spec()},
            {"route": runtime},
            [self._route("route", fixed_cost_usd=0.10)],
        )

        first = coordinator.run_once(self.mission.mission_id)
        attempts = self.service.store.list_attempts(self.mission.mission_id)
        events = self.service.store.list_events(self.mission.mission_id)
        evidence = self.service.store.list_evidence(self.mission.mission_id)
        second = coordinator.run_once(self.mission.mission_id)

        self.assertEqual(first.status, CoordinatorStatus.MISSION_COMPLETED)
        self.assertEqual(second.status, CoordinatorStatus.MISSION_COMPLETED)
        self.assertEqual(self.service.get_mission(self.mission.mission_id).state, MissionState.COMPLETED)
        self.assertEqual(self.service.store.list_attempts(self.mission.mission_id), attempts)
        self.assertEqual(self.service.store.list_events(self.mission.mission_id), events)
        self.assertEqual(self.service.store.list_evidence(self.mission.mission_id), evidence)
        self.assertEqual(len(runtime.calls), 1)

    def test_zero_task_mission_remains_active_and_is_not_auto_completed(self) -> None:
        empty_service = MissionService()
        try:
            mission, _ = self._create_active_mission(empty_service, "empty-mission", None)
            runtime = DeterministicRuntime()
            coordinator = self._coordinator(
                {},
                {"unused": runtime},
                [],
                service=empty_service,
            )
            events = empty_service.store.list_events(mission.mission_id)

            result = coordinator.run_once(mission.mission_id)

            self.assertEqual(result.status, CoordinatorStatus.NO_WORK)
            self.assertEqual(empty_service.get_mission(mission.mission_id).state, MissionState.ACTIVE)
            self.assertEqual(empty_service.store.list_tasks(mission.mission_id), [])
            self.assertEqual(empty_service.store.list_attempts(mission.mission_id), [])
            self.assertEqual(empty_service.store.list_evidence(mission.mission_id), [])
            self.assertEqual(empty_service.store.list_events(mission.mission_id), events)
            self.assertEqual(runtime.calls, [])
        finally:
            empty_service.close()

    def test_file_backed_reopen_preserves_attempt_and_prevents_duplicate_execution(self) -> None:
        database = self.root / "mission.sqlite3"
        first_service = MissionService(database)
        second_service: MissionService | None = None
        try:
            mission, task = self._create_active_mission(
                first_service, "persistent-mission", "persistent-task"
            )
            assert task is not None
            first_runtime = DeterministicRuntime(
                RuntimeError("runtime disappeared after workspace mutation"),
                mutate=True,
            )
            spec = self._spec(task)
            first_coordinator = self._coordinator(
                {task.task_id: spec},
                {"route": first_runtime},
                [self._route("route", fixed_cost_usd=0.10)],
                service=first_service,
                lease_seconds=30.0,
            )

            first_result = first_coordinator.run_once(mission.mission_id)
            persisted_before_close = first_service.store.list_attempts(
                mission.mission_id, task.task_id
            )
            self.assertEqual(first_result.status, CoordinatorStatus.UNKNOWN_OUTCOME)
            self.assertEqual(len(persisted_before_close), 1)
            self.assertEqual(persisted_before_close[0].status, AttemptStatus.RUNNING)
            assert persisted_before_close[0].lease_expires_at is not None
            lease_expiry = persisted_before_close[0].lease_expires_at
            first_service.close()

            second_service = MissionService(database)
            second_runtime = DeterministicRuntime()
            second_coordinator = self._coordinator(
                {task.task_id: spec},
                {"route": second_runtime},
                [self._route("route", fixed_cost_usd=0.10)],
                service=second_service,
                lease_seconds=30.0,
            )
            reopened_attempts = second_service.store.list_attempts(
                mission.mission_id, task.task_id
            )
            self.assertEqual(reopened_attempts, persisted_before_close)

            with patch(
                "kora.execution.coordinator.utc_now",
                return_value=lease_expiry - timedelta(microseconds=1),
            ):
                busy = second_coordinator.run_once(mission.mission_id)
            self.assertEqual(busy.status, CoordinatorStatus.BUSY)
            self.assertEqual(second_runtime.calls, [])
            self.assertEqual(
                second_service.store.list_attempts(mission.mission_id, task.task_id),
                persisted_before_close,
            )

            with patch(
                "kora.execution.coordinator.utc_now",
                return_value=lease_expiry + timedelta(microseconds=1),
            ):
                expired = second_coordinator.run_once(mission.mission_id)
            self.assertEqual(expired.status, CoordinatorStatus.UNKNOWN_OUTCOME)
            self.assertEqual(second_runtime.calls, [])
            self.assertEqual(
                [attempt.status for attempt in second_service.store.list_attempts(mission.mission_id)],
                [AttemptStatus.UNKNOWN],
            )
            self.assertEqual(len(second_service.store.list_attempts(mission.mission_id)), 1)
        finally:
            if second_service is not None:
                second_service.close()
            else:
                first_service.close()


if __name__ == "__main__":
    unittest.main()

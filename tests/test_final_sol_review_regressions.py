from __future__ import annotations

import math
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

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
    AttemptStatus,
    ConflictError,
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
    HermesRuntimeAdapter,
    HermesRuntimeError,
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
    PrivacyLevel,
    RoleCharter,
    RouteDecision,
    RouteObservation,
    RouteReservation,
    TaskProfile,
    WorkforceCompiler,
    WorkforceValidationError,
)


BASE_TIME = datetime(2027, 1, 1, tzinfo=timezone.utc)
SAFE_DIGEST = "a" * 64


def accepted_verification() -> WorkspaceVerificationResult:
    return WorkspaceVerificationResult(
        accepted=True,
        summary="Independent checks accepted the workspace.",
        change_fingerprint=SAFE_DIGEST,
        checks=(),
        artifacts=(
            VerificationArtifact(
                name="verified workspace diff",
                locator=f"artifact://sha256/{SAFE_DIGEST}",
                artifact_kind="diff",
                evidence_kind="artifact",
                summary="The independently checked workspace diff is available.",
            ),
        ),
    )


class RecordingRuntime:
    """A deterministic runtime double that makes workspace effects observable."""

    def __init__(
        self,
        *,
        writes: tuple[tuple[str, str], ...] = (),
        on_run: Callable[[RuntimeJob], None] | None = None,
        result_status: RuntimeStatus = RuntimeStatus.COMPLETED,
    ) -> None:
        self.writes = writes
        self.on_run = on_run
        self.result_status = result_status
        self.calls: list[RuntimeJob] = []
        self.last_job: RuntimeJob | None = None

    def run(self, job: RuntimeJob) -> RuntimeResult:
        self.calls.append(job)
        self.last_job = job
        if self.on_run is not None:
            self.on_run(job)
        for relative_path, contents in self.writes:
            destination = job.workspace / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(contents, encoding="utf-8")
        return RuntimeResult(
            mission_id=job.mission_id,
            task_id=job.task_id,
            status=self.result_status,
            response="completed",
            exit_code=0 if self.result_status is not RuntimeStatus.FAILED else 1,
        )


class StaticVerifier:
    """A verifier double that records whether the verifier boundary was entered."""

    def __init__(
        self,
        result: WorkspaceVerificationResult | BaseException | None = None,
    ) -> None:
        self.result = result or accepted_verification()
        self.requests: list[WorkspaceVerificationRequest] = []

    def verify(self, request: WorkspaceVerificationRequest) -> WorkspaceVerificationResult:
        self.requests.append(request)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class FencedCommandVerifier:
    """Verifier double that validates the live Kora fence per subprocess."""

    def __init__(
        self,
        service: MissionService,
        runtime: RecordingRuntime,
        mission_id: str,
        *,
        revoke_before_first: bool = False,
    ) -> None:
        self.service = service
        self.runtime = runtime
        self.mission_id = mission_id
        self.revoke_before_first = revoke_before_first
        self.requests: list[WorkspaceVerificationRequest] = []
        self.fence_checks = 0
        self.command_calls = 0

    def verify(self, request: WorkspaceVerificationRequest) -> WorkspaceVerificationResult:
        self.requests.append(request)
        if self.revoke_before_first:
            self.service.stop_mission(
                self.mission_id,
                reason="stop raced the verifier subprocess boundary",
            )

        for command in request.commands:
            job = self.runtime.last_job
            if job is None or job.execution_fence is None:
                raise AssertionError("the verifier needs the dispatched runtime fence")
            ticket = job.execution_fence
            attempt = self.service.get_attempt(ticket.attempt_id)
            identity = (
                f"cancel:{attempt.mission_id}:{attempt.attempt_id}:"
                f"{ticket.fencing_token}"
            )
            self.service.validate_execution_fence_ticket(
                ticket,
                cancellation_identity=identity,
            )
            self.fence_checks += 1
            self.command_calls += 1
            completed = subprocess.run(
                list(command.argv),
                cwd=request.workspace,
                capture_output=True,
                check=False,
            )
            if completed.returncode != 0:
                return WorkspaceVerificationResult(
                    accepted=False,
                    summary="A verification subprocess failed.",
                    change_fingerprint=SAFE_DIGEST,
                    checks=(),
                    artifacts=(),
                )

        return accepted_verification()


class FinalSolReviewRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory(prefix="kora-final-sol-")
        self.root = Path(self.tempdir.name)
        self.services: list[MissionService] = []

    def tearDown(self) -> None:
        for service in reversed(self.services):
            service.close()
        self.tempdir.cleanup()

    def _service(self, name: str) -> MissionService:
        service = MissionService(self.root / f"{name}.sqlite3")
        self.services.append(service)
        return service

    @staticmethod
    def _active_fixture(
        service: MissionService,
        mission_id: str,
        task_id: str,
    ) -> tuple[str, Task]:
        mission = service.create_mission(
            "Final Sol review mission",
            "Complete the approved execution slice.",
            "The changed workspace is independently verified.",
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
        service.start_task(task.task_id, at=BASE_TIME + timedelta(seconds=4))
        return mission_id, task

    @staticmethod
    def _profile(
        task: Task,
        *,
        capabilities: frozenset[Capability] = frozenset(),
        toolsets: tuple[str, ...] = (),
        evidence_requirements: tuple[str, ...] = (),
        max_latency_ms: float | None = None,
        max_cost_usd: float | None = None,
    ) -> TaskProfile:
        return TaskProfile(
            task_id=task.task_id,
            task_class="bounded-implementation",
            objective=task.description or task.title,
            required_capabilities=frozenset(
                capability.value for capability in capabilities
            ),
            required_tools=frozenset(toolsets),
            privacy=PrivacyLevel.EXTERNAL_OK,
            evidence_requirements=evidence_requirements,
            max_latency_ms=max_latency_ms,
            max_cost_usd=max_cost_usd,
        )

    def _spec(
        self,
        task: Task,
        workspace: Path,
        *,
        capabilities: frozenset[Capability] = frozenset(),
        toolsets: tuple[str, ...] = (),
        permissions: tuple[PermissionRequirement, ...] = (),
        commands: tuple[VerificationCommand, ...] = (),
        require_changes: bool = True,
        profile: TaskProfile | None = None,
    ) -> TaskExecutionSpec:
        selected_profile = profile or self._profile(
            task,
            capabilities=capabilities,
            toolsets=toolsets,
        )
        if profile is not None:
            if not capabilities:
                capabilities = frozenset(
                    Capability(value) for value in profile.required_capabilities
                )
            if not toolsets:
                toolsets = tuple(sorted(profile.required_tools))
        return TaskExecutionSpec(
            profile=selected_profile,
            instructions="Execute only the approved task.",
            workspace=workspace,
            runtime_capabilities=capabilities,
            toolsets=toolsets,
            skills=("bounded-review-skill",),
            isolation=IsolationMode.CLOUD_SANDBOX,
            permission_requirements=permissions,
            verification_commands=commands,
            require_changes=require_changes,
        )

    @staticmethod
    def _route(
        route_id: str,
        *,
        fixed_cost_usd: float = 0.10,
        input_cost_per_million: float = 0.0,
        output_cost_per_million: float = 0.0,
        predicted_latency_ms: float = 100.0,
        capabilities: frozenset[Capability] = frozenset(),
        tools: frozenset[str] = frozenset(),
        predicted_quality: float = 1.0,
        reliability: float = 1.0,
    ) -> ModelRoute:
        return ModelRoute(
            route_id=route_id,
            provider_ref=f"provider-{route_id}",
            model_ref=f"model-{route_id}",
            supported_capabilities=frozenset(
                capability.value for capability in capabilities
            ),
            supported_tools=tools,
            privacy_support=PrivacyLevel.EXTERNAL_OK,
            context_window=100_000,
            predicted_quality=predicted_quality,
            reliability=reliability,
            input_cost_per_million=input_cost_per_million,
            output_cost_per_million=output_cost_per_million,
            fixed_cost_usd=fixed_cost_usd,
            predicted_latency_ms=predicted_latency_ms,
        )

    def _coordinator(
        self,
        service: MissionService,
        task: Task,
        spec: TaskExecutionSpec,
        runtime: RecordingRuntime,
        verifier: object,
        *,
        router: ModelRouter | None = None,
        lease_owner: str = "final-sol-coordinator",
        max_attempts: int = 1,
    ) -> ExecutionCoordinator:
        role = RoleCharter(
            role_id="role-final-sol-review",
            title="Final Sol review operator",
            responsibilities=("Perform the bounded task",),
            non_responsibilities=("Create a new mission",),
            allowed_capabilities=frozenset(
                capability.value for capability in spec.runtime_capabilities
            ),
        )
        routes = [
            self._route(
                "route",
                fixed_cost_usd=0.10,
                capabilities=spec.runtime_capabilities,
                tools=frozenset(spec.toolsets),
            )
        ]
        return ExecutionCoordinator(
            service,
            role,
            WorkforceCompiler(max_attempts=max_attempts),
            router or ModelRouter(routes),
            MappingTaskSpecProvider({task.task_id: spec}),
            MappingRuntimeResolver({"route": runtime}),
            verifier,
            lease_owner,
            30.0,
            max_attempts,
        )

    @staticmethod
    def _grant(
        service: MissionService,
        mission_id: str,
        grant_id: str,
        action: PermissionAction,
        resource: str,
    ) -> None:
        service.grant_permission(
            mission_id,
            action,
            resource,
            f"Authorize {action.value} for the exact review workspace.",
            mode=PermissionMode.BOUNDED_INDEFINITE,
            scope="this mission only",
            max_actions=20,
            budget_limit_cents=10_000,
            grant_id=grant_id,
            approved_at=datetime(2000, 1, 1, tzinfo=timezone.utc),
        )

    @staticmethod
    def _permission_uses(service: MissionService) -> list[object]:
        return service.store.connection.execute(
            "SELECT * FROM permission_uses"
        ).fetchall()

    @staticmethod
    def _git_workspace(path: Path, files: dict[str, str] | None = None) -> Path:
        path.mkdir(parents=True)
        subprocess.run(["git", "init", "-q"], cwd=path, check=True)
        (path / "README.md").write_text("base\n", encoding="utf-8")
        for relative_path, contents in (files or {}).items():
            destination = path / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(contents, encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=path, check=True)
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
            cwd=path,
            check=True,
        )
        return path

    @staticmethod
    def _close_before_restart(
        services: list[MissionService],
        service: MissionService,
    ) -> None:
        services.remove(service)
        service.close()

    @staticmethod
    def _fake_hermes(executable: Path) -> None:
        executable.write_text(
            """#!/usr/bin/env python3
import pathlib
import sys

arguments = sys.argv[1:]
usage_path = pathlib.Path(arguments[arguments.index('--usage-file') + 1])
pathlib.Path('hermes-launch.log').write_text('launched\\n', encoding='utf-8')
pathlib.Path('hermes-effect.txt').write_text('effect\\n', encoding='utf-8')
pathlib.Path('hermes-write.log').write_text('written\\n', encoding='utf-8')
usage_path.write_text('{}', encoding='utf-8')
print('KORA_TASK_COMPLETE')
""",
            encoding="utf-8",
        )
        executable.chmod(0o700)

    def test_stop_invalidates_adapter_before_spawn_effect_or_write(self) -> None:
        with self.subTest(case="live-ticket-positive-control"):
            service = self._service("stop-positive")
            mission_id, task = self._active_fixture(
                service, "stop-positive-mission", "stop-positive-task"
            )
            workspace = self.root / "stop-positive-workspace"
            workspace.mkdir()
            attempt = service.create_attempt(
                mission_id,
                task.task_id,
                "stop-positive-attempt",
                worker_role_id="runtime-worker",
                route_id="route",
                attempt_id="stop-positive-attempt",
                created_at=BASE_TIME,
            )
            claimed = service.claim_attempt(
                attempt.attempt_id,
                "runtime-worker",
                lease_expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
                at=BASE_TIME,
            )
            ticket = service.issue_execution_fence_ticket(
                claimed.attempt_id,
                at=BASE_TIME + timedelta(seconds=1),
            )
            executable = self.root / "stop-positive-hermes"
            self._fake_hermes(executable)
            job = RuntimeJob(
                mission_id=mission_id,
                task_id=task.task_id,
                objective=task.description,
                instructions="Perform the approved task.",
                workspace=workspace,
                capabilities=frozenset({Capability.WORKSPACE_WRITE}),
                isolation=IsolationMode.CLOUD_SANDBOX,
                execution_fence=ticket,
            )
            adapter = HermesRuntimeAdapter(
                cloud_root=self.root,
                hermes_executable=executable,
            )
            result = adapter.run(job)
            self.assertEqual(result.status, RuntimeStatus.COMPLETED)
            self.assertTrue((workspace / "hermes-launch.log").exists())
            self.assertTrue((workspace / "hermes-effect.txt").exists())
            self.assertTrue((workspace / "hermes-write.log").exists())

        with self.subTest(case="stopped-before-effect-boundary"):
            service = self._service("stop-negative")
            mission_id, task = self._active_fixture(
                service, "stop-negative-mission", "stop-negative-task"
            )
            workspace = self.root / "stop-negative-workspace"
            workspace.mkdir()
            attempt = service.create_attempt(
                mission_id,
                task.task_id,
                "stop-negative-attempt",
                worker_role_id="runtime-worker",
                route_id="route",
                attempt_id="stop-negative-attempt",
                created_at=BASE_TIME,
            )
            claimed = service.claim_attempt(
                attempt.attempt_id,
                "runtime-worker",
                lease_expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
                at=BASE_TIME,
            )
            ticket = service.issue_execution_fence_ticket(
                claimed.attempt_id,
                at=BASE_TIME + timedelta(seconds=1),
            )
            service.stop_mission(
                mission_id,
                reason="user stopped before runtime dispatch",
                at=BASE_TIME + timedelta(seconds=2),
            )
            self.assertEqual(
                service.get_mission(mission_id).state,
                MissionState.STOPPED,
            )
            stopped_attempt = service.get_attempt(attempt.attempt_id)
            self.assertEqual(stopped_attempt.status, AttemptStatus.INTERRUPTED)
            self.assertTrue(
                ticket.is_active(at=BASE_TIME + timedelta(seconds=3)),
                "the ticket must still look live from its embedded expiry",
            )
            self.assertTrue(
                ticket.is_active(),
                "the ticket must also be structurally unexpired at the adapter call",
            )
            with self.assertRaises(ConflictError):
                service.validate_execution_fence_ticket(
                    ticket,
                    at=BASE_TIME + timedelta(seconds=3),
                )
            executable = self.root / "stop-negative-hermes"
            self._fake_hermes(executable)
            job = RuntimeJob(
                mission_id=mission_id,
                task_id=task.task_id,
                objective=task.description,
                instructions="Perform the approved task.",
                workspace=workspace,
                capabilities=frozenset({Capability.WORKSPACE_WRITE}),
                isolation=IsolationMode.CLOUD_SANDBOX,
                execution_fence=ticket,
            )
            adapter = HermesRuntimeAdapter(
                cloud_root=self.root,
                hermes_executable=executable,
            )
            try:
                adapter.run(job)
            except HermesRuntimeError:
                pass
            self.assertFalse(
                (workspace / "hermes-launch.log").exists(),
                "Hermes must not be spawned after STOPPED invalidated the attempt",
            )
            self.assertFalse(
                (workspace / "hermes-effect.txt").exists(),
                "the adapter must not allow a post-stop effect",
            )
            self.assertFalse(
                (workspace / "hermes-write.log").exists(),
                "the adapter must not write after the live fence is revoked",
            )

    def test_confirmed_effect_unknown_recovery_verifies_without_runtime_replay(self) -> None:
        service = self._service("confirmed-effect-recovery")
        mission_id, task = self._active_fixture(
            service, "confirmed-effect-mission", "confirmed-effect-task"
        )
        created = service.create_attempt(
            mission_id,
            task.task_id,
            "confirmed-effect-unknown",
            worker_role_id="old-runtime-worker",
            route_id="route",
            attempt_id="confirmed-effect-attempt",
            created_at=BASE_TIME + timedelta(seconds=5),
        )
        claimed = service.claim_attempt(
            created.attempt_id,
            "old-runtime-worker",
            lease_expires_at=BASE_TIME + timedelta(seconds=10),
            at=BASE_TIME + timedelta(seconds=5),
        )
        unknown = service.mark_expired_attempt_unknown(
            claimed.attempt_id,
            reason="The prior runtime effect was not observable.",
            expected_revision=claimed.revision,
            at=BASE_TIME + timedelta(seconds=11),
        )

        fresh_owner = "confirmed-effect-recovery-worker"
        fresh_expiry = BASE_TIME + timedelta(seconds=90)
        reconcile = getattr(service, "reconcile_unknown_effects_confirmed", None)
        if not callable(reconcile):
            reconcile = service.reconcile_unknown
        try:
            reconciled = reconcile(
                unknown.attempt_id,
                target=AttemptStatus.VERIFYING,
                effects_confirmed=True,
                lease_owner=fresh_owner,
                fencing_token=unknown.fencing_token + 1,
                lease_expires_at=fresh_expiry,
                at=BASE_TIME + timedelta(seconds=12),
            )
        except (TypeError, ConflictError, InvalidTransitionError, ValidationError) as exc:
            self.fail(
                "explicit effects-confirmed UNKNOWN reconciliation to VERIFYING "
                f"must be supported; exception-as-success is forbidden: {exc}"
            )

        self.assertEqual(reconciled.status, AttemptStatus.VERIFYING)
        self.assertEqual(reconciled.lease_owner, fresh_owner)
        self.assertGreater(reconciled.fencing_token, unknown.fencing_token)
        self.assertEqual(reconciled.lease_expires_at, fresh_expiry)
        if service.get_task(task.task_id).state is TaskStatus.IN_PROGRESS:
            service.begin_task_verification(
                task.task_id,
                at=BASE_TIME + timedelta(seconds=12),
            )

        database_path = self.root / "confirmed-effect-recovery.sqlite3"
        self._close_before_restart(self.services, service)
        restarted = self._service("confirmed-effect-recovery")
        workspace = self.root / "confirmed-effect-workspace"
        workspace.mkdir()
        runtime = RecordingRuntime()
        verifier = StaticVerifier()
        spec = self._spec(restarted.get_task(task.task_id), workspace)
        result = self._coordinator(
            restarted,
            restarted.get_task(task.task_id),
            spec,
            runtime,
            verifier,
            lease_owner=fresh_owner,
        ).run_once(mission_id)

        self.assertEqual(result.status, CoordinatorStatus.MISSION_COMPLETED)
        self.assertEqual(runtime.calls, [])
        self.assertEqual(len(verifier.requests), 1)
        self.assertEqual(
            restarted.get_attempt(unknown.attempt_id).status,
            AttemptStatus.SUCCEEDED,
        )
        self.assertEqual(
            restarted.get_task(task.task_id).state,
            TaskStatus.COMPLETED,
        )
        self.assertEqual(restarted.get_mission(mission_id).state, MissionState.COMPLETED)
        self.assertTrue(database_path.exists())

    def test_symlink_workspace_alias_cannot_redirect_authorized_work(self) -> None:
        with self.subTest(case="alias-rejected-before-effect"):
            service = self._service("symlink-alias-negative")
            mission_id, task = self._active_fixture(
                service, "symlink-alias-mission", "symlink-alias-task"
            )
            target_b = self.root / "workspace-target-b"
            target_c = self.root / "workspace-target-c"
            alias = self.root / "workspace-alias"
            target_b.mkdir()
            target_c.mkdir()
            alias.symlink_to(target_b, target_is_directory=True)
            self._grant(
                service,
                mission_id,
                "symlink-write-grant",
                PermissionAction.WRITE_WORKSPACE,
                str(alias),
            )

            def redirect_before_effect(job: RuntimeJob) -> None:
                alias.unlink()
                alias.symlink_to(target_c, target_is_directory=True)

            runtime = RecordingRuntime(
                writes=(("redirected-effect.txt", "must not be redirected\n"),),
                on_run=redirect_before_effect,
            )
            verifier = StaticVerifier()
            spec = self._spec(
                task,
                alias,
                capabilities=frozenset({Capability.WORKSPACE_WRITE}),
                permissions=(
                    PermissionRequirement(
                        "symlink-write-grant",
                        PermissionAction.WRITE_WORKSPACE,
                        str(alias),
                    ),
                ),
            )
            try:
                result = self._coordinator(
                    service, task, spec, runtime, verifier
                ).run_once(mission_id)
            except ExecutionValidationError:
                result = None
            if result is None or result.status is not CoordinatorStatus.MISSION_COMPLETED:
                if result is not None:
                    self.assertEqual(result.status, CoordinatorStatus.WAITING_FOR_USER)
                self.assertEqual(service.store.list_attempts(mission_id), [])
                self.assertEqual(runtime.calls, [])
                self.assertEqual(verifier.requests, [])
                self.assertEqual(self._permission_uses(service), [])
                self.assertFalse((target_b / "redirected-effect.txt").exists())
                self.assertFalse((target_c / "redirected-effect.txt").exists())
                self.assertEqual(alias.resolve(), target_b.resolve())
            else:
                self.assertEqual(len(runtime.calls), 1)
                self.assertEqual(len(verifier.requests), 1)
                self.assertEqual(
                    runtime.calls[0].workspace.resolve(), target_b.resolve()
                )
                self.assertEqual(
                    verifier.requests[0].workspace.resolve(), target_b.resolve()
                )
                self.assertTrue((target_b / "redirected-effect.txt").exists())
                self.assertFalse((target_c / "redirected-effect.txt").exists())

        with self.subTest(case="canonical-workspace-positive-control"):
            service = self._service("symlink-alias-positive")
            mission_id, task = self._active_fixture(
                service, "canonical-workspace-mission", "canonical-workspace-task"
            )
            workspace = self.root / "canonical-workspace"
            workspace.mkdir()
            resource = str(workspace)
            self._grant(
                service,
                mission_id,
                "canonical-write-grant",
                PermissionAction.WRITE_WORKSPACE,
                resource,
            )
            runtime = RecordingRuntime(
                writes=(("canonical-effect.txt", "allowed\n"),)
            )
            spec = self._spec(
                task,
                workspace,
                capabilities=frozenset({Capability.WORKSPACE_WRITE}),
                permissions=(
                    PermissionRequirement(
                        "canonical-write-grant",
                        PermissionAction.WRITE_WORKSPACE,
                        resource,
                    ),
                ),
            )
            result = self._coordinator(
                service, task, spec, runtime, StaticVerifier()
            ).run_once(mission_id)
            self.assertEqual(result.status, CoordinatorStatus.MISSION_COMPLETED)
            self.assertEqual(len(runtime.calls), 1)
            self.assertTrue((workspace / "canonical-effect.txt").exists())

    def test_verifier_commands_require_execute_authority_and_live_fences(self) -> None:
        commands = (
            VerificationCommand("first check", (sys.executable, "-c", "pass")),
            VerificationCommand("second check", (sys.executable, "-c", "pass")),
        )

        with self.subTest(case="positive-control-live-fence-per-command"):
            service = self._service("verifier-authority-positive")
            mission_id, task = self._active_fixture(
                service,
                "verifier-authority-positive-mission",
                "verifier-authority-positive-task",
            )
            workspace = self.root / "verifier-authority-positive-workspace"
            workspace.mkdir()
            resource = str(workspace)
            self._grant(
                service,
                mission_id,
                "positive-write-grant",
                PermissionAction.WRITE_WORKSPACE,
                resource,
            )
            self._grant(
                service,
                mission_id,
                "positive-execute-grant",
                PermissionAction.EXECUTE_WORKSPACE,
                resource,
            )
            runtime = RecordingRuntime(
                writes=(("runtime-effect.txt", "allowed\n"),)
            )
            verifier = FencedCommandVerifier(service, runtime, mission_id)
            spec = self._spec(
                task,
                workspace,
                capabilities=frozenset(
                    {Capability.WORKSPACE_WRITE, Capability.WORKSPACE_EXECUTE}
                ),
                permissions=(
                    PermissionRequirement(
                        "positive-write-grant",
                        PermissionAction.WRITE_WORKSPACE,
                        resource,
                    ),
                    PermissionRequirement(
                        "positive-execute-grant",
                        PermissionAction.EXECUTE_WORKSPACE,
                        resource,
                    ),
                ),
                commands=commands,
            )
            result = self._coordinator(
                service, task, spec, runtime, verifier
            ).run_once(mission_id)
            self.assertEqual(result.status, CoordinatorStatus.MISSION_COMPLETED)
            self.assertEqual(verifier.fence_checks, len(commands))
            self.assertEqual(verifier.command_calls, len(commands))
            self.assertTrue((workspace / "runtime-effect.txt").exists())
            self.assertEqual(service.get_task(task.task_id).state, TaskStatus.COMPLETED)

        with self.subTest(case="missing-workspace-execute-capability"):
            service = self._service("verifier-authority-no-capability")
            mission_id, task = self._active_fixture(
                service,
                "verifier-authority-no-capability-mission",
                "verifier-authority-no-capability-task",
            )
            workspace = self.root / "verifier-authority-no-capability-workspace"
            workspace.mkdir()
            resource = str(workspace)
            self._grant(
                service,
                mission_id,
                "no-cap-write-grant",
                PermissionAction.WRITE_WORKSPACE,
                resource,
            )
            runtime = RecordingRuntime(
                writes=(("must-not-be-written.txt", "blocked\n"),)
            )
            verifier = FencedCommandVerifier(service, runtime, mission_id)
            try:
                spec = self._spec(
                    task,
                    workspace,
                    capabilities=frozenset({Capability.WORKSPACE_WRITE}),
                    permissions=(
                        PermissionRequirement(
                            "no-cap-write-grant",
                            PermissionAction.WRITE_WORKSPACE,
                            resource,
                        ),
                    ),
                    commands=commands,
                )
            except ExecutionValidationError:
                spec = None
            if spec is not None:
                try:
                    result = self._coordinator(
                        service, task, spec, runtime, verifier
                    ).run_once(mission_id)
                except ExecutionValidationError:
                    result = None
                if result is not None:
                    self.assertEqual(
                        result.status,
                        CoordinatorStatus.WAITING_FOR_USER,
                    )
            self.assertEqual(runtime.calls, [])
            self.assertEqual(verifier.command_calls, 0)
            self.assertEqual(self._permission_uses(service), [])
            self.assertNotEqual(service.get_task(task.task_id).state, TaskStatus.COMPLETED)
            self.assertFalse((workspace / "must-not-be-written.txt").exists())

        with self.subTest(case="wrong-execute-resource"):
            service = self._service("verifier-authority-wrong-resource")
            mission_id, task = self._active_fixture(
                service,
                "verifier-authority-wrong-resource-mission",
                "verifier-authority-wrong-resource-task",
            )
            workspace = self.root / "verifier-authority-wrong-resource-workspace"
            workspace.mkdir()
            resource = str(workspace)
            wrong_resource = str(workspace.parent)
            self._grant(
                service,
                mission_id,
                "wrong-write-grant",
                PermissionAction.WRITE_WORKSPACE,
                resource,
            )
            self._grant(
                service,
                mission_id,
                "wrong-execute-grant",
                PermissionAction.EXECUTE_WORKSPACE,
                wrong_resource,
            )
            runtime = RecordingRuntime(
                writes=(("must-not-be-written.txt", "blocked\n"),)
            )
            verifier = FencedCommandVerifier(service, runtime, mission_id)
            spec = self._spec(
                task,
                workspace,
                capabilities=frozenset(
                    {Capability.WORKSPACE_WRITE, Capability.WORKSPACE_EXECUTE}
                ),
                permissions=(
                    PermissionRequirement(
                        "wrong-write-grant",
                        PermissionAction.WRITE_WORKSPACE,
                        resource,
                    ),
                    PermissionRequirement(
                        "wrong-execute-grant",
                        PermissionAction.EXECUTE_WORKSPACE,
                        wrong_resource,
                    ),
                ),
                commands=commands,
            )
            result = self._coordinator(
                service, task, spec, runtime, verifier
            ).run_once(mission_id)
            self.assertEqual(result.status, CoordinatorStatus.WAITING_FOR_USER)
            self.assertEqual(runtime.calls, [])
            self.assertEqual(verifier.command_calls, 0)
            self.assertEqual(self._permission_uses(service), [])
            self.assertFalse((workspace / "must-not-be-written.txt").exists())

        with self.subTest(case="revoked-live-fence-before-subprocess"):
            service = self._service("verifier-authority-stale-fence")
            mission_id, task = self._active_fixture(
                service,
                "verifier-authority-stale-fence-mission",
                "verifier-authority-stale-fence-task",
            )
            workspace = self.root / "verifier-authority-stale-fence-workspace"
            workspace.mkdir()
            resource = str(workspace)
            self._grant(
                service,
                mission_id,
                "stale-execute-grant",
                PermissionAction.EXECUTE_WORKSPACE,
                resource,
            )
            runtime = RecordingRuntime()
            verifier = FencedCommandVerifier(
                service,
                runtime,
                mission_id,
                revoke_before_first=True,
            )
            spec = self._spec(
                task,
                workspace,
                capabilities=frozenset({Capability.WORKSPACE_EXECUTE}),
                permissions=(
                    PermissionRequirement(
                        "stale-execute-grant",
                        PermissionAction.EXECUTE_WORKSPACE,
                        resource,
                    ),
                ),
                commands=commands,
            )
            result = self._coordinator(
                service, task, spec, runtime, verifier
            ).run_once(mission_id)
            self.assertNotEqual(result.status, CoordinatorStatus.MISSION_COMPLETED)
            self.assertEqual(runtime.calls.__len__(), 1)
            self.assertEqual(verifier.command_calls, 0)
            self.assertEqual(service.get_mission(mission_id).state, MissionState.STOPPED)
            self.assertNotEqual(service.get_task(task.task_id).state, TaskStatus.COMPLETED)
            self.assertEqual(
                len(self._permission_uses(service)),
                1,
                "authorization may be recorded before a later fence race, but the command must not run",
            )

    def test_untracked_fingerprint_binds_path_mode_type_and_bytes_without_deref(self) -> None:
        workspace = self._git_workspace(self.root / "fingerprint-workspace")
        verifier = WorkspaceVerifier(self.root)

        def fingerprint() -> str:
            result = verifier.verify(
                WorkspaceVerificationRequest(
                    workspace=workspace,
                    commands=(),
                    require_changes=True,
                )
            )
            self.assertIsNotNone(result.change_fingerprint)
            return result.change_fingerprint or ""

        candidate = workspace / "candidate.bin"
        candidate.write_bytes(b"bytes-one")
        candidate.chmod(0o600)
        first = fingerprint()
        self.assertEqual(first, fingerprint(), "identical snapshots stay deterministic")

        candidate.write_bytes(b"bytes-two")
        second = fingerprint()
        with self.subTest(component="untracked-bytes"):
            self.assertNotEqual(first, second)

        candidate.chmod(0o755)
        third = fingerprint()
        with self.subTest(component="mode"):
            self.assertNotEqual(second, third)

        outside_dir = tempfile.TemporaryDirectory(prefix="kora-outside-")
        try:
            outside_file = Path(outside_dir.name) / "outside.txt"
            outside_file.write_text("outside-one\n", encoding="utf-8")
            candidate.unlink()
            candidate.symlink_to(outside_file)
            symlink_first = fingerprint()
            with self.subTest(component="regular-vs-symlink-type"):
                self.assertNotEqual(third, symlink_first)

            outside_file.write_text("outside-two\n", encoding="utf-8")
            symlink_second = fingerprint()
            with self.subTest(component="symlink-not-dereferenced"):
                self.assertEqual(symlink_first, symlink_second)
        finally:
            outside_dir.cleanup()

        candidate.unlink()
        nested = workspace / "nested"
        nested.mkdir()
        nested_candidate = nested / "candidate.bin"
        nested_candidate.write_bytes(b"bytes-two")
        nested_candidate.chmod(0o755)
        different_path = fingerprint()
        with self.subTest(component="canonical-relative-path"):
            self.assertNotEqual(third, different_path)

    def test_post_check_mutation_rejects_evidence_and_task_completion(self) -> None:
        mutation_command = VerificationCommand(
            "mutate candidate after snapshot",
            (
                sys.executable,
                "-c",
                "from pathlib import Path; "
                "Path('candidate.txt').write_text('after\\n', encoding='utf-8')",
            ),
        )
        stable_command = VerificationCommand(
            "stable candidate check",
            (sys.executable, "-c", "pass"),
        )

        with self.subTest(case="post-check-mutation-rejected"):
            service = self._service("post-check-mutation-negative")
            mission_id, task = self._active_fixture(
                service,
                "post-check-mutation-mission",
                "post-check-mutation-task",
            )
            workspace = self._git_workspace(
                self.root / "post-check-mutation-workspace",
                {"candidate.txt": "base\n"},
            )
            resource = str(workspace)
            self._grant(
                service,
                mission_id,
                "mutation-write-grant",
                PermissionAction.WRITE_WORKSPACE,
                resource,
            )
            self._grant(
                service,
                mission_id,
                "mutation-execute-grant",
                PermissionAction.EXECUTE_WORKSPACE,
                resource,
            )
            runtime = RecordingRuntime(writes=(("candidate.txt", "before\n"),))
            spec = self._spec(
                task,
                workspace,
                capabilities=frozenset(
                    {Capability.WORKSPACE_WRITE, Capability.WORKSPACE_EXECUTE}
                ),
                permissions=(
                    PermissionRequirement(
                        "mutation-write-grant",
                        PermissionAction.WRITE_WORKSPACE,
                        resource,
                    ),
                    PermissionRequirement(
                        "mutation-execute-grant",
                        PermissionAction.EXECUTE_WORKSPACE,
                        resource,
                    ),
                ),
                commands=(mutation_command,),
            )
            result = self._coordinator(
                service,
                task,
                spec,
                runtime,
                WorkspaceVerifier(self.root),
            ).run_once(mission_id)
            self.assertNotEqual(result.status, CoordinatorStatus.MISSION_COMPLETED)
            self.assertNotEqual(
                service.get_mission(mission_id).state,
                MissionState.COMPLETED,
            )
            self.assertNotEqual(service.get_task(task.task_id).state, TaskStatus.COMPLETED)
            self.assertEqual(service.store.list_evidence(mission_id), [])

        with self.subTest(case="unchanged-post-check-positive-control"):
            service = self._service("post-check-mutation-positive")
            mission_id, task = self._active_fixture(
                service,
                "post-check-positive-mission",
                "post-check-positive-task",
            )
            workspace = self._git_workspace(
                self.root / "post-check-positive-workspace",
                {"candidate.txt": "base\n"},
            )
            resource = str(workspace)
            self._grant(
                service,
                mission_id,
                "stable-write-grant",
                PermissionAction.WRITE_WORKSPACE,
                resource,
            )
            self._grant(
                service,
                mission_id,
                "stable-execute-grant",
                PermissionAction.EXECUTE_WORKSPACE,
                resource,
            )
            runtime = RecordingRuntime(writes=(("candidate.txt", "before\n"),))
            spec = self._spec(
                task,
                workspace,
                capabilities=frozenset(
                    {Capability.WORKSPACE_WRITE, Capability.WORKSPACE_EXECUTE}
                ),
                permissions=(
                    PermissionRequirement(
                        "stable-write-grant",
                        PermissionAction.WRITE_WORKSPACE,
                        resource,
                    ),
                    PermissionRequirement(
                        "stable-execute-grant",
                        PermissionAction.EXECUTE_WORKSPACE,
                        resource,
                    ),
                ),
                commands=(stable_command,),
            )
            result = self._coordinator(
                service,
                task,
                spec,
                runtime,
                WorkspaceVerifier(self.root),
            ).run_once(mission_id)
            self.assertEqual(result.status, CoordinatorStatus.MISSION_COMPLETED)
            self.assertEqual(service.get_task(task.task_id).state, TaskStatus.COMPLETED)
            self.assertTrue(service.store.list_evidence(mission_id))

    def test_nonfinite_budget_values_are_rejected_before_router_state_mutation(self) -> None:
        nonfinite_values = (math.nan, math.inf, -math.inf)
        profile = TaskProfile(
            task_id="budget-task",
            task_class="budget-review",
            objective="Bound the budget review.",
        )
        route = self._route("budget-route", fixed_cost_usd=0.40)

        for value in nonfinite_values:
            with self.subTest(surface="route-cost", value=value):
                for field_name in (
                    "input_cost_per_million",
                    "output_cost_per_million",
                    "fixed_cost_usd",
                    "predicted_latency_ms",
                ):
                    with self.subTest(field=field_name):
                        with self.assertRaises(WorkforceValidationError):
                            self._route(
                                "nonfinite-route",
                                **{field_name: value},
                            )

        for value in nonfinite_values:
            with self.subTest(surface="task-ceiling", value=value):
                for field_name in ("max_latency_ms", "max_cost_usd"):
                    with self.subTest(field=field_name):
                        with self.assertRaises(WorkforceValidationError):
                            TaskProfile(
                                task_id="nonfinite-ceiling-task",
                                task_class="budget-review",
                                objective="Bound the budget review.",
                                **{field_name: value},
                            )

        for value in nonfinite_values:
            with self.subTest(surface="router-budget-ceiling", value=value):
                with self.assertRaises(WorkforceValidationError):
                    ModelRouter([route], budget_ceiling_usd=value)

        for value in nonfinite_values:
            with self.subTest(surface="route-decision", value=value):
                with self.assertRaises(WorkforceValidationError):
                    RouteDecision(
                        task_id=profile.task_id,
                        route_id=route.route_id,
                        expected_attempt_cost_usd=value,
                        expected_cost_per_accepted_outcome=0.40,
                    )
                with self.assertRaises(WorkforceValidationError):
                    RouteDecision(
                        task_id=profile.task_id,
                        route_id=route.route_id,
                        expected_attempt_cost_usd=0.40,
                        expected_cost_per_accepted_outcome=value,
                    )

        for value in nonfinite_values:
            with self.subTest(surface="route-reservation", value=value):
                with self.assertRaises(WorkforceValidationError):
                    RouteReservation("nonfinite-reservation", route.route_id, value)

        for value in nonfinite_values:
            with self.subTest(surface="select-spent-cost", value=value):
                with self.assertRaises(WorkforceValidationError):
                    ModelRouter([route]).select(profile, spent_cost_usd=value)
            with self.subTest(surface="select-budget-override", value=value):
                with self.assertRaises(WorkforceValidationError):
                    ModelRouter([route]).select(
                        profile,
                        budget_ceiling_usd=value,
                    )

        decision = ModelRouter([route]).select(profile)
        for value in nonfinite_values:
            with self.subTest(surface="reserve-budget-override", value=value):
                router = ModelRouter([route])
                try:
                    with self.assertRaises(WorkforceValidationError):
                        router.reserve(decision, budget_ceiling_usd=value)
                finally:
                    if router.active_concurrency:
                        active = next(iter(router._reservations.values()))
                        router.release(active, actual_cost_usd=0.10)
                self.assertEqual(router.active_concurrency, 0)

        for value in nonfinite_values:
            with self.subTest(surface="actual-settlement", value=value):
                router = ModelRouter([route])
                reservation = router.reserve(decision, reservation_id="settlement")
                try:
                    with self.assertRaises(WorkforceValidationError):
                        router.release(reservation, actual_cost_usd=value)
                finally:
                    if router.active_concurrency:
                        router.release(reservation, actual_cost_usd=0.10)
                self.assertEqual(router.active_concurrency, 0)
                self.assertAlmostEqual(router.spent_cost_usd, 0.10)

        for value in nonfinite_values:
            with self.subTest(surface="observation-cost", value=value):
                with self.assertRaises(WorkforceValidationError):
                    RouteObservation(
                        route_id=route.route_id,
                        task_class=profile.task_class,
                        accepted=True,
                        total_tokens=1,
                        cost_usd=value,
                        latency_ms=1.0,
                    )
            with self.subTest(surface="observation-latency", value=value):
                with self.assertRaises(WorkforceValidationError):
                    RouteObservation(
                        route_id=route.route_id,
                        task_class=profile.task_class,
                        accepted=True,
                        total_tokens=1,
                        cost_usd=0.10,
                        latency_ms=value,
                    )

        with self.subTest(surface="finite-positive-control"):
            router = ModelRouter([route], budget_ceiling_usd=1.0)
            selected = router.select(profile)
            first = router.reserve(selected, reservation_id="finite-first")
            router.release(first, actual_cost_usd=0.20)
            second = router.reserve(selected, reservation_id="finite-second")
            router.release(second, actual_cost_usd=0.20)
            self.assertEqual(router.active_concurrency, 0)
            self.assertAlmostEqual(router.spent_cost_usd, 0.40)


if __name__ == "__main__":
    unittest.main()

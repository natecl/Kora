"""Offline end-to-end dogfood acceptance for one founder implementation cycle.

The fixture is intentionally a tiny real product rather than a mocked output:
the runtime writes a zero-dependency waitlist CLI and its tests into an empty
git repository, and :class:`WorkspaceVerifier` executes those tests before
Kora can persist evidence or finish the mission.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

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
from kora.verification import VerificationCommand, WorkspaceVerifier
from kora.workforce import (
    ModelRoute,
    ModelRouter,
    PrivacyLevel,
    RiskLevel,
    RoleCharter,
    TaskProfile,
    WorkforceCompiler,
)


MISSION_ID = "mission-founder-waitlist"
TASK_ID = "task-build-waitlist-mvp"
ROUTE_ID = "route-deterministic-dogfood"
LEASE_OWNER = "dogfood-coordinator"

PRIVATE_MARKERS = (
    "provider_ref",
    "model_ref",
    "provider-private",
    "model-private",
    "route_id",
    "raw prompt",
    "total_tokens",
    "token_count",
)

WAITLIST_SOURCE = '''\
"""A zero-dependency waitlist CLI for a founder validation experiment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


STORE = Path(__file__).with_name("waitlist.json")


def _read_entries() -> list[dict[str, str]]:
    if not STORE.exists():
        return []
    return json.loads(STORE.read_text(encoding="utf-8"))


def join_waitlist(name: str, email: str) -> dict[str, object]:
    """Add one person to the waitlist and return a stable public result."""

    clean_name = name.strip()
    clean_email = email.strip().lower()
    if not clean_name:
        raise ValueError("name is required")
    if "@" not in clean_email:
        raise ValueError("a valid email is required")

    entries = _read_entries()
    for position, entry in enumerate(entries, start=1):
        if entry["email"] == clean_email:
            return {"status": "already_joined", "position": position}

    entries.append({"name": clean_name, "email": clean_email})
    STORE.write_text(json.dumps(entries, indent=2, sort_keys=True) + "\\n", encoding="utf-8")
    return {"status": "joined", "position": len(entries), "email": clean_email}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="waitlist")
    commands = parser.add_subparsers(dest="command", required=True)
    join = commands.add_parser("join", help="join the waitlist")
    join.add_argument("name")
    join.add_argument("email")
    args = parser.parse_args(argv)

    if args.command == "join":
        print(json.dumps(join_waitlist(args.name, args.email), sort_keys=True))
        return 0
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
'''

WAITLIST_TESTS = '''\
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import waitlist


class WaitlistTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_store = waitlist.STORE
        waitlist.STORE = Path(self.tempdir.name) / "entries.json"

    def tearDown(self) -> None:
        waitlist.STORE = self.original_store
        self.tempdir.cleanup()

    def test_join_is_persisted_and_duplicate_is_idempotent(self) -> None:
        first = waitlist.join_waitlist("Ada Lovelace", "ADA@example.test")
        duplicate = waitlist.join_waitlist("Different Name", "ada@example.test")

        self.assertEqual(first, {"status": "joined", "position": 1, "email": "ada@example.test"})
        self.assertEqual(duplicate, {"status": "already_joined", "position": 1})
        self.assertEqual(waitlist.STORE.read_text(encoding="utf-8").count("ada@example.test"), 1)


if __name__ == "__main__":
    unittest.main()
'''


class DeterministicRuntimeAdapter:
    """A bounded offline runtime that writes the fixture's implementation."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.calls: list[RuntimeJob] = []
        self.fence_error: str | None = None

    def run(self, job: RuntimeJob) -> RuntimeResult:
        self.calls.append(job)
        if job.workspace != self.workspace:
            raise AssertionError("runtime received an unexpected workspace")
        if job.objective != "Implement the approved waitlist MVP slice.":
            raise AssertionError("runtime received an unexpected task objective")
        # This is the same contract an effect-bearing adapter must honor before
        # it writes to the workspace.  The coordinator must provide the ticket.
        try:
            job.validate_execution_fence()
        except Exception as exc:  # pragma: no cover - diagnostic for a boundary failure
            self.fence_error = str(exc)
            raise
        if (self.workspace / "waitlist.py").exists():
            raise AssertionError("dogfood workspace was not empty before execution")
        (self.workspace / "waitlist.py").write_text(WAITLIST_SOURCE, encoding="utf-8")
        (self.workspace / "test_waitlist.py").write_text(WAITLIST_TESTS, encoding="utf-8")
        return RuntimeResult(
            mission_id=job.mission_id,
            task_id=job.task_id,
            status=RuntimeStatus.COMPLETED,
            response=(
                "provider-private runtime completed raw prompt hidden "
                "total_tokens=17 route_id=private-route"
            ),
            exit_code=0,
            total_tokens=17,
            estimated_cost_usd=0.0,
        )


class DogfoodAcceptanceTests(unittest.TestCase):
    """Exercise one complete founder mission without user-driven orchestration."""

    def test_founder_brief_to_usable_waitlist_mvp(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            workspace = root / "waitlist-product"
            workspace.mkdir()
            self._initialize_empty_git_repository(workspace)
            self.assertEqual(
                subprocess.run(
                    ("git", "ls-files"),
                    cwd=workspace,
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout,
                "",
            )

            with MissionService(root / "mission.sqlite3", owner_ref="founder") as service:
                mission = service.create_mission(
                    title="Founder waitlist validation",
                    objective=(
                        "Turn this concise product brief into a tiny waitlist CLI "
                        "for validating founder demand."
                    ),
                    definition_of_done=(
                        "A generated zero-dependency CLI accepts a waitlist signup, "
                        "its independent tests pass, and its public behavior is usable."
                    ),
                    exclusions=(
                        "No hosted deployment",
                        "No outreach or external messaging",
                        "No unrelated product features",
                    ),
                    mission_id=MISSION_ID,
                )
                self.assertEqual(mission.state, MissionState.PROPOSED)
                service.align_mission(mission.mission_id)
                service.activate_mission(mission.mission_id)
                self.assertEqual(
                    service.get_mission(mission.mission_id).state,
                    MissionState.ACTIVE,
                )

                task = service.add_task(
                    mission.mission_id,
                    "Implement waitlist MVP",
                    description="Implement the approved waitlist MVP slice.",
                    priority=100,
                    critical_path=True,
                    task_id=TASK_ID,
                )
                self.assertEqual(task.state, TaskStatus.READY)
                selected = service.select_next_task(mission.mission_id)
                self.assertIsNotNone(selected)
                self.assertEqual(selected.task_id if selected else None, TASK_ID)
                self.assertEqual(selected.priority if selected else None, 100)
                self.assertTrue(selected.critical_path if selected else False)

                write_grant = service.grant_permission(
                    mission.mission_id,
                    PermissionAction.WRITE_WORKSPACE,
                    str(workspace),
                    "Generate the approved MVP files in the disposable workspace.",
                    mode=PermissionMode.BOUNDED_INDEFINITE,
                    scope="this mission only",
                    max_actions=1,
                    grant_id="grant-waitlist-write",
                )
                execute_grant = service.grant_permission(
                    mission.mission_id,
                    PermissionAction.EXECUTE_WORKSPACE,
                    str(workspace),
                    "Run the approved workspace acceptance tests.",
                    mode=PermissionMode.BOUNDED_INDEFINITE,
                    scope="this mission only",
                    max_actions=1,
                    grant_id="grant-waitlist-execute",
                )

                capabilities = frozenset(
                    {Capability.WORKSPACE_WRITE, Capability.WORKSPACE_EXECUTE}
                )
                requirements = (
                    PermissionRequirement(
                        write_grant.grant_id,
                        PermissionAction.WRITE_WORKSPACE,
                        str(workspace),
                    ),
                    PermissionRequirement(
                        execute_grant.grant_id,
                        PermissionAction.EXECUTE_WORKSPACE,
                        str(workspace),
                    ),
                )
                profile = TaskProfile(
                    task_id=task.task_id,
                    task_class="founder-implementation",
                    objective=task.description,
                    required_capabilities=frozenset(
                        capability.value for capability in capabilities
                    ),
                    required_tools=frozenset(),
                    risk=RiskLevel.MEDIUM,
                    privacy=PrivacyLevel.LOCAL_ONLY,
                    quality_floor=0.9,
                    reliability_floor=0.9,
                    evidence_requirements=("diff", "test_report"),
                )
                spec = TaskExecutionSpec(
                    profile=profile,
                    instructions=(
                        "Implement only the approved waitlist MVP slice in the "
                        "provided workspace."
                    ),
                    workspace=workspace,
                    runtime_capabilities=capabilities,
                    toolsets=(),
                    skills=(),
                    isolation=IsolationMode.CLOUD_SANDBOX,
                    permission_requirements=requirements,
                    verification_commands=(
                        VerificationCommand(
                            "waitlist acceptance tests",
                            (sys.executable, "-m", "unittest", "-q", "test_waitlist"),
                        ),
                    ),
                    require_changes=True,
                    baseline_ref="HEAD",
                )
                role = RoleCharter(
                    role_id="role-founder-builder",
                    title="Founder builder",
                    responsibilities=("Build the approved product slice",),
                    non_responsibilities=("Change the mission or contact users",),
                    allowed_capabilities=frozenset(
                        capability.value for capability in capabilities
                    ),
                    default_quality_floor=0.9,
                    max_concurrency=1,
                )
                route = ModelRoute(
                    route_id=ROUTE_ID,
                    provider_ref="provider-private-dogfood",
                    model_ref="model-private-dogfood",
                    supported_capabilities=frozenset(
                        capability.value for capability in capabilities
                    ),
                    privacy_support=PrivacyLevel.LOCAL_ONLY,
                    context_window=4_000,
                    predicted_quality=1.0,
                    reliability=1.0,
                    fixed_cost_usd=0.0,
                    predicted_latency_ms=1.0,
                )
                runtime = DeterministicRuntimeAdapter(workspace)
                coordinator = ExecutionCoordinator(
                    service,
                    role,
                    WorkforceCompiler(max_attempts=1),
                    ModelRouter([route]),
                    MappingTaskSpecProvider({task.task_id: spec}),
                    MappingRuntimeResolver({ROUTE_ID: runtime}),
                    WorkspaceVerifier(root),
                    LEASE_OWNER,
                    30.0,
                    1,
                )

                result = coordinator.run_once(mission.mission_id)

                self.assertEqual(
                    result.status,
                    CoordinatorStatus.MISSION_COMPLETED,
                    msg=(
                        "effect-bearing RuntimeAdapter boundary failure: "
                        f"{runtime.fence_error}"
                    ),
                )
                self.assertEqual(len(runtime.calls), 1)
                self.assertTrue((workspace / "waitlist.py").is_file())
                self.assertTrue((workspace / "test_waitlist.py").is_file())
                self.assertEqual(service.get_task(task.task_id).state, TaskStatus.COMPLETED)
                self.assertEqual(service.get_mission(mission.mission_id).state, MissionState.COMPLETED)

                attempts = service.store.list_attempts(mission.mission_id, task.task_id)
                self.assertEqual(len(attempts), 1)
                self.assertEqual(attempts[0].status, AttemptStatus.SUCCEEDED)

                artifacts = service.store.list_artifacts(mission.mission_id)
                self.assertEqual(
                    {artifact.kind for artifact in artifacts},
                    {ArtifactKind.DIFF, ArtifactKind.TEST_REPORT},
                )
                task_evidence = [
                    evidence
                    for evidence in service.store.list_evidence(mission.mission_id)
                    if evidence.task_id == task.task_id
                ]
                self.assertEqual(
                    {evidence.kind for evidence in task_evidence},
                    {EvidenceKind.ARTIFACT, EvidenceKind.TEST},
                )
                self.assertTrue(all(evidence.verified_at is not None for evidence in task_evidence))
                self.assertTrue(
                    all(
                        evidence.verification_method == "independent workspace verifier"
                        for evidence in task_evidence
                    )
                )
                coverage = [
                    evidence
                    for evidence in service.store.list_evidence(mission.mission_id)
                    if evidence.kind is EvidenceKind.REQUIREMENT_COVERAGE
                ]
                self.assertEqual(len(coverage), 1)
                self.assertIsNotNone(coverage[0].verified_at)
                checkpoint_types = {
                    checkpoint.kind for checkpoint in service.store.list_checkpoints(mission.mission_id)
                }
                self.assertIn(CheckpointType.FIRST_USABLE_SLICE, checkpoint_types)
                self.assertIn(CheckpointType.MISSION_COMPLETE, checkpoint_types)

                output = subprocess.run(
                    [sys.executable, "waitlist.py", "join", "Ada Lovelace", "ADA@example.test"],
                    cwd=workspace,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(
                    json.loads(output.stdout),
                    {"status": "joined", "position": 1, "email": "ada@example.test"},
                )

                self._assert_public_surface_is_semantic(service, mission.mission_id, result)

    @staticmethod
    def _initialize_empty_git_repository(workspace: Path) -> None:
        subprocess.run(("git", "init", "-q"), cwd=workspace, check=True)
        subprocess.run(
            (
                "git",
                "-c",
                "user.name=Kora Dogfood",
                "-c",
                "user.email=kora-dogfood@example.test",
                "commit",
                "--allow-empty",
                "-qm",
                "empty baseline",
            ),
            cwd=workspace,
            check=True,
        )

    @staticmethod
    def _assert_public_surface_is_semantic(
        service: MissionService,
        mission_id: str,
        result: object,
    ) -> None:
        status = service.get_status(mission_id)
        public_strings = [
            str(getattr(result, "summary", "")),
            status.mission.title,
            status.mission.objective,
            status.mission.definition_of_done,
            *(task.title for task in status.tasks),
            *(task.description for task in status.tasks),
            *(escalation.title for escalation in status.open_escalations),
            *(escalation.reason for escalation in status.open_escalations),
            *(artifact.name for artifact in service.store.list_artifacts(mission_id)),
            *(evidence.summary for evidence in service.store.list_evidence(mission_id)),
        ]
        for value in public_strings:
            for marker in PRIVATE_MARKERS:
                if marker in value:
                    raise AssertionError(f"private execution marker leaked: {marker!r}")

        result_fields = set(getattr(result, "__dataclass_fields__", {}))
        expected_fields = {"mission_id", "status", "summary", "task_id", "attempt_id"}
        if result_fields != expected_fields:
            raise AssertionError(f"unexpected user-facing result fields: {result_fields}")


if __name__ == "__main__":
    unittest.main()

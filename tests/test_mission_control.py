from __future__ import annotations

import tempfile
import unittest
import sqlite3
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from kora.mission import (
    ArtifactKind,
    AssumptionStatus,
    CheckpointType,
    ConflictError,
    DependencyError,
    EscalationStatus,
    EvidenceKind,
    EventType,
    InvalidTransitionError,
    Mission,
    MissionService,
    MissionState,
    NotFoundError,
    PermissionAction,
    PermissionMode,
    PermissionUnavailableError,
    SQLiteMissionStore,
    TaskDependency,
    TaskStatus,
    ValidationError,
    utc_now,
)


UTC = timezone.utc


class MissionControlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = SQLiteMissionStore()
        self.service = MissionService(self.store)
        self.mission = self.service.create_mission(
            "Narrow MVP",
            "Turn the approved product idea into a usable narrow MVP.",
            "A deployed, usable MVP passes every approved acceptance test.",
            exclusions=("No unrelated features", "No outreach without approval"),
            mission_id="mission-1",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

    def tearDown(self) -> None:
        self.store.close()

    def _activate(self) -> None:
        self.service.align_mission("mission-1")
        self.service.activate_mission("mission-1")

    def test_round_trip_persists_all_semantic_records(self) -> None:
        self._activate()
        task = self.service.add_task(
            "mission-1",
            "Build slice",
            description="Implement the agreed end-to-end path.",
            priority=10,
            task_id="task-1",
        )
        decision = self.service.record_decision(
            "mission-1", "Data source", "Use the approved local source", rationale="PRD"
        )
        assumption = self.service.record_assumption(
            "mission-1",
            "The test account is available",
            status=AssumptionStatus.CONFIRMED,
        )
        checkpoint = self.service.record_checkpoint(
            "mission-1",
            CheckpointType.PLAN_CHOSEN,
            "The narrow implementation plan is set.",
            task_id=task.task_id,
        )
        escalation = self.service.escalate(
            "mission-1",
            "Need API key",
            "The preview cannot be exercised without it.",
            "Verification is blocked.",
            options=("Provide key", "Use a fixture"),
            recommendation="Use a fixture for this slice.",
            consequence_of_waiting="No end-to-end verification.",
            requested_action="Choose one option.",
            task_id=task.task_id,
            escalation_id="escalation-1",
        )
        artifact = self.service.record_artifact(
            "mission-1",
            "Test report",
            "/tmp/test-report.json",
            kind=ArtifactKind.TEST_REPORT,
            task_id=task.task_id,
        )
        evidence = self.service.record_evidence(
            "mission-1",
            "The automated acceptance tests pass.",
            kind=EvidenceKind.TEST,
            artifact_id=artifact.artifact_id,
            task_id=task.task_id,
        )
        grant = self.service.grant_permission(
            "mission-1",
            PermissionAction.DEPLOY,
            "production/project-a",
            "Deploy the approved MVP",
            mode=PermissionMode.BOUNDED_INDEFINITE,
            scope="this mission and project only",
            max_actions=2,
            budget_limit_cents=0,
            grant_id="grant-1",
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mission.sqlite3"
            first = MissionService(path)
            created = first.create_mission(
                "Persistent",
                "Persist state",
                "Reopen and recover",
                mission_id="persistent-mission",
            )
            first.align_mission(created.mission_id)
            first.activate_mission(created.mission_id)
            first_task = first.add_task(
                created.mission_id, "Persist task", task_id="persistent-task"
            )
            first.record_decision(
                created.mission_id, "A", "B", decision_id="persistent-decision"
            )
            first.close()

            reopened = MissionService(path)
            try:
                self.assertEqual(
                    reopened.store.require_mission("persistent-mission").state,
                    MissionState.ACTIVE,
                )
                self.assertEqual(
                    reopened.store.require_task(first_task.task_id).mission_id,
                    created.mission_id,
                )
                self.assertEqual(
                    len(reopened.store.list_decisions(created.mission_id)), 1
                )
            finally:
                reopened.close()

        self.assertEqual(
            self.store.require_task(task.task_id).state, TaskStatus.NEEDS_USER
        )
        self.assertEqual(self.store.list_decisions("mission-1")[0], decision)
        self.assertEqual(self.store.list_assumptions("mission-1")[0], assumption)
        self.assertEqual(self.store.list_checkpoints("mission-1")[0], checkpoint)
        self.assertEqual(
            self.store.get_escalation(escalation.escalation_id), escalation
        )
        self.assertEqual(self.store.list_artifacts("mission-1")[0], artifact)
        self.assertEqual(self.store.list_evidence("mission-1")[0], evidence)
        self.assertEqual(self.store.get_permission_grant(grant.grant_id), grant)

    def test_mission_transition_matrix_and_terminal_states(self) -> None:
        with self.assertRaises(InvalidTransitionError):
            self.service.complete_mission("mission-1")
        self.assertEqual(
            self.store.require_mission("mission-1").state, MissionState.PROPOSED
        )

        aligned = self.service.align_mission("mission-1")
        self.assertEqual(aligned.state, MissionState.ALIGNED)
        with self.assertRaises(InvalidTransitionError):
            self.service.align_mission("mission-1")
        active = self.service.activate_mission("mission-1")
        waiting = self.service.wait_for_user("mission-1")
        resumed = self.service.resume_mission("mission-1")
        verifying = self.service.begin_verification("mission-1")
        self.assertEqual(
            (active.state, waiting.state, resumed.state, verifying.state),
            (
                MissionState.ACTIVE,
                MissionState.WAITING_FOR_USER,
                MissionState.ACTIVE,
                MissionState.VERIFYING,
            ),
        )
        self.service.resume_mission("mission-1")
        self.service.begin_verification("mission-1")
        evidence = self.service.record_evidence(
            "mission-1",
            "The mission acceptance review passed.",
            kind=EvidenceKind.REVIEW,
            evidence_id="mission-review",
        )
        self.service.verify_evidence(evidence.evidence_id, "independent review")
        completed = self.service.complete_mission("mission-1")
        self.assertEqual(completed.state, MissionState.COMPLETED)
        with self.assertRaises(InvalidTransitionError):
            self.service.resume_mission("mission-1")
        with self.assertRaises(InvalidTransitionError):
            self.service.stop_mission("mission-1", reason="too late")

    def test_stopped_and_failed_are_explicit_terminal_outcomes(self) -> None:
        self.service.stop_mission("mission-1", reason="User stopped the mission.")
        stopped = self.store.require_mission("mission-1")
        self.assertEqual(stopped.state, MissionState.STOPPED)
        self.assertEqual(stopped.stop_reason, "User stopped the mission.")
        self.assertIsNone(self.service.select_next_task("mission-1"))

        other = self.service.create_mission(
            "Other", "Do other", "Other done", mission_id="mission-2"
        )
        self.service.fail_mission(other.mission_id, reason="Unrecoverable failure")
        failed = self.store.require_mission(other.mission_id)
        self.assertEqual(failed.state, MissionState.FAILED)
        self.assertEqual(failed.failure_reason, "Unrecoverable failure")

    def test_only_one_overarching_mission_can_be_active(self) -> None:
        self._activate()
        other_service = MissionService(self.store, owner_ref="other-owner")
        other = other_service.create_mission(
            "Other", "Other objective", "Other done", mission_id="mission-2"
        )
        other_service.align_mission(other.mission_id)
        with self.assertRaises(ConflictError):
            other_service.activate_mission(other.mission_id)
        self.assertEqual(
            self.store.require_mission(other.mission_id).state,
            MissionState.ALIGNED,
        )

    def test_nonterminal_mission_and_records_are_owner_contained(self) -> None:
        with self.assertRaises(ConflictError):
            self.service.create_mission(
                "Second", "Another objective", "Another done", mission_id="same-owner"
            )

        other_service = MissionService(self.store, owner_ref="other-owner")
        other = other_service.create_mission(
            "Other", "Other objective", "Other done", mission_id="other-mission"
        )
        with self.assertRaises(ConflictError):
            self.service.get_mission(other.mission_id)
        with self.assertRaises(ConflictError):
            self.service.add_task(other.mission_id, "Foreign task")

    def test_alignment_freezes_objective_and_stale_revision_fails(self) -> None:
        self.service.align_mission("mission-1")
        aligned = self.store.require_mission("mission-1")
        with self.assertRaises(ConflictError):
            self.store.update_mission(
                replace(aligned, objective="Silently changed"),
                expected_revision=aligned.revision,
            )
        self.assertEqual(
            self.store.require_mission("mission-1").objective, aligned.objective
        )

        with self.assertRaises(ConflictError):
            self.store.update_mission(aligned, expected_revision=aligned.revision - 1)
        self.assertEqual(
            self.store.require_mission("mission-1").revision, aligned.revision
        )

    def test_repository_cannot_bypass_lifecycle_or_contract_guards(self) -> None:
        with self.assertRaises(InvalidTransitionError):
            self.store.create_mission(
                Mission(
                    mission_id="direct-active",
                    title="Direct active",
                    objective="Do not bypass approval",
                    definition_of_done="The guard rejects direct activation",
                    state=MissionState.ACTIVE,
                )
            )

        with self.assertRaises(InvalidTransitionError):
            self.store.update_mission(
                replace(self.mission, state=MissionState.COMPLETED)
            )
        with self.assertRaises(ConflictError):
            self.store.update_mission(
                replace(self.mission, objective="Broadened without re-alignment")
            )
        self.assertEqual(
            self.store.require_mission(self.mission.mission_id).objective,
            self.mission.objective,
        )
        self.service.align_mission("mission-1")
        aligned = self.store.require_mission("mission-1")
        with self.assertRaises(ConflictError):
            self.store.update_mission(replace(aligned, exclusions=("new scope",)))

        task = self.service.add_task("mission-1", "Direct completion", task_id="direct")
        with self.assertRaises(InvalidTransitionError):
            self.store.update_task(replace(task, state=TaskStatus.COMPLETED))
        self.assertEqual(self.store.require_task(task.task_id).state, TaskStatus.READY)

    def test_task_revision_is_compare_and_set_protected(self) -> None:
        task = self.service.add_task("mission-1", "Revisioned task", task_id="revisioned")
        updated = self.store.update_task(replace(task, title="Updated title"))
        self.assertEqual(updated.revision, task.revision + 1)
        with self.assertRaises(ConflictError):
            self.store.update_task(replace(task, title="Stale overwrite"))
        self.assertEqual(
            self.store.require_task(task.task_id).title, "Updated title"
        )

    def test_invalid_multi_write_escalation_rolls_back_everything(self) -> None:
        self._activate()
        with self.assertRaises(NotFoundError):
            self.service.escalate(
                "mission-1",
                "Missing task",
                "Reason",
                "Impact",
                task_id="does-not-exist",
            )
        self.assertEqual(
            self.store.require_mission("mission-1").state, MissionState.ACTIVE
        )
        self.assertEqual(self.store.list_escalations("mission-1"), [])
        self.assertEqual(
            [event.event_type for event in self.store.list_events("mission-1")],
            [
                EventType.MISSION_CREATED,
                EventType.MISSION_TRANSITIONED,
                EventType.MISSION_TRANSITIONED,
            ],
        )

    def test_audit_write_failure_rolls_back_the_state_write(self) -> None:
        aligned = self.service.align_mission("mission-1")
        with patch.object(
            self.store, "create_event", side_effect=RuntimeError("disk full")
        ):
            with self.assertRaisesRegex(RuntimeError, "disk full"):
                self.service.activate_mission("mission-1")
        current = self.store.require_mission("mission-1")
        self.assertEqual(current.state, MissionState.ALIGNED)
        self.assertEqual(current.revision, aligned.revision)
        self.assertEqual(
            [event.event_type for event in self.store.list_events("mission-1")],
            [EventType.MISSION_CREATED, EventType.MISSION_TRANSITIONED],
        )

    def test_task_lifecycle_and_dependency_blocking(self) -> None:
        self._activate()
        prerequisite = self.service.add_task(
            "mission-1", "Prerequisite", task_id="a", priority=1
        )
        dependent = self.service.add_task(
            "mission-1",
            "Dependent",
            task_id="b",
            priority=5,
            depends_on=(prerequisite.task_id,),
        )
        self.assertEqual(dependent.state, TaskStatus.BLOCKED)
        self.assertEqual(self.service.select_next_task("mission-1").task_id, "a")
        with self.assertRaises(InvalidTransitionError):
            self.service.start_task("b")
        self.service.start_task("a")
        self.service.begin_task_verification("a")
        evidence_a = self.service.record_evidence(
            "mission-1",
            "The prerequisite verification passed.",
            kind=EvidenceKind.TEST,
            task_id="a",
            evidence_id="evidence-a",
        )
        self.service.verify_evidence(evidence_a.evidence_id, "test runner")
        self.service.complete_task("a")
        self.assertEqual(self.store.require_task("b").state, TaskStatus.READY)
        self.service.start_task("b")
        self.service.mark_task_needs_user("b")
        self.assertIsNone(self.service.select_next_task("mission-1"))
        self.service.start_task("b")
        self.service.begin_task_verification("b")
        evidence_b = self.service.record_evidence(
            "mission-1",
            "The dependent verification passed.",
            kind=EvidenceKind.TEST,
            task_id="b",
            evidence_id="evidence-b",
        )
        self.service.verify_evidence(evidence_b.evidence_id, "test runner")
        self.service.complete_task("b")
        self.assertEqual(self.store.require_task("b").state, TaskStatus.COMPLETED)

    def test_adding_dependency_refreshes_an_existing_ready_task(self) -> None:
        self._activate()
        prerequisite = self.service.add_task("mission-1", "Prerequisite", task_id="a")
        dependent = self.service.add_task("mission-1", "Dependent", task_id="b")
        self.assertEqual(dependent.state, TaskStatus.READY)

        self.service.add_dependency(
            "mission-1", dependent.task_id, prerequisite.task_id
        )

        self.assertEqual(
            self.store.require_task(dependent.task_id).state, TaskStatus.BLOCKED
        )
        self.assertEqual(self.service.select_next_task("mission-1").task_id, "a")

    def test_task_completion_requires_independently_verified_evidence(self) -> None:
        self._activate()
        task = self.service.add_task("mission-1", "Review me", task_id="review-me")
        self.service.start_task(task.task_id)
        self.service.begin_task_verification(task.task_id)
        with self.assertRaises(ConflictError):
            self.service.complete_task(task.task_id)

        evidence = self.service.record_evidence(
            "mission-1",
            "The runtime reported success.",
            kind=EvidenceKind.TEST,
            task_id=task.task_id,
            evidence_id="candidate-evidence",
        )
        with self.assertRaises(ConflictError):
            self.service.complete_task(task.task_id)
        verified = self.service.verify_evidence(
            evidence.evidence_id, "independent acceptance test"
        )
        self.assertIsNotNone(verified.verified_at)
        self.assertEqual(
            self.service.complete_task(task.task_id).state, TaskStatus.COMPLETED
        )

    def test_failed_task_can_be_retried_only_through_ready(self) -> None:
        self._activate()
        task = self.service.add_task("mission-1", "Retryable", task_id="retryable")
        self.service.start_task(task.task_id)
        failed = self.service.fail_task(task.task_id)
        self.assertEqual(failed.state, TaskStatus.FAILED)
        with self.assertRaises(InvalidTransitionError):
            self.service.start_task(task.task_id)
        ready = self.service.transition_task(task.task_id, TaskStatus.READY)
        self.assertEqual(ready.state, TaskStatus.READY)
        self.assertEqual(
            self.service.start_task(task.task_id).state, TaskStatus.IN_PROGRESS
        )

    def test_cross_mission_and_transitive_cycles_are_rejected(self) -> None:
        self._activate()
        other_service = MissionService(self.store, owner_ref="other-owner")
        second = other_service.create_mission(
            "Second", "Second", "Second done", mission_id="mission-2"
        )
        a = self.service.add_task("mission-1", "A", task_id="a")
        b = self.service.add_task("mission-1", "B", task_id="b")
        c = self.service.add_task("mission-1", "C", task_id="c")
        self.service.add_dependency("mission-1", b.task_id, a.task_id)
        self.service.add_dependency("mission-1", c.task_id, b.task_id)
        with self.assertRaises(DependencyError):
            self.service.add_dependency("mission-1", a.task_id, c.task_id)
        foreign = other_service.add_task(
            second.mission_id, "Foreign", task_id="foreign"
        )
        with self.assertRaises(DependencyError):
            self.service.add_dependency("mission-1", a.task_id, foreign.task_id)
        self.assertEqual(len(self.store.list_dependencies("mission-1")), 2)

    def test_repository_also_rejects_cross_mission_and_cycle_edges(self) -> None:
        self._activate()
        other_service = MissionService(self.store, owner_ref="other-owner")
        second = other_service.create_mission(
            "Second", "Second", "Done", mission_id="mission-2"
        )
        self.service.add_task("mission-1", "A", task_id="a")
        self.service.add_task("mission-1", "B", task_id="b")
        self.store.create_dependency(
            TaskDependency("mission-1", "b", "a", created_at=utc_now())
        )
        other_service.add_task(second.mission_id, "Foreign", task_id="foreign")
        with self.assertRaises(DependencyError):
            self.store.create_dependency(
                TaskDependency("mission-1", "a", "foreign", created_at=utc_now())
            )
        with self.assertRaises(DependencyError):
            self.store.create_dependency(
                TaskDependency("mission-1", "a", "b", created_at=utc_now())
            )

    def test_next_task_is_priority_then_creation_then_id_and_survives_reopen(
        self,
    ) -> None:
        self._activate()
        timestamp = datetime(2026, 1, 2, tzinfo=UTC)
        self.service.add_task(
            "mission-1", "Zed", task_id="z", priority=5, created_at=timestamp
        )
        self.service.add_task(
            "mission-1", "Alpha", task_id="a", priority=5, created_at=timestamp
        )
        self.service.add_task(
            "mission-1", "High", task_id="high", priority=10, created_at=timestamp
        )
        self.assertEqual(self.service.select_next_task("mission-1").task_id, "high")
        self.service.cancel_task("high")
        self.assertEqual(self.service.select_next_task("mission-1").task_id, "a")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reopen.sqlite3"
            first = MissionService(path)
            mission = first.create_mission(
                "Reopen", "Objective", "Done", mission_id="reopen"
            )
            first.align_mission(mission.mission_id)
            first.activate_mission(mission.mission_id)
            first.add_task(
                mission.mission_id, "z", task_id="z", priority=4, created_at=timestamp
            )
            first.add_task(
                mission.mission_id, "a", task_id="a", priority=4, created_at=timestamp
            )
            first.close()
            reopened = MissionService(path)
            try:
                self.assertEqual(reopened.select_next_task("reopen").task_id, "a")
            finally:
                reopened.close()

    def test_next_task_prefers_critical_path_before_priority(self) -> None:
        self._activate()
        self.service.add_task(
            "mission-1", "Unrelated high priority", task_id="unrelated", priority=100
        )
        self.service.add_task(
            "mission-1",
            "Critical path",
            task_id="critical",
            priority=1,
            critical_path=True,
        )
        self.assertEqual(self.service.select_next_task("mission-1").task_id, "critical")

    def test_verified_evidence_and_permission_usage_survive_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "semantic-state.sqlite3"
            first = MissionService(path)
            mission = first.create_mission("Persistent", "Objective", "Done")
            first.align_mission(mission.mission_id)
            first.activate_mission(mission.mission_id)
            task = first.add_task(mission.mission_id, "Persistent task", task_id="persist-task")
            first.start_task(task.task_id)
            first.begin_task_verification(task.task_id)
            evidence = first.record_evidence(
                mission.mission_id,
                "A persistent acceptance result.",
                kind=EvidenceKind.TEST,
                task_id=task.task_id,
                evidence_id="persist-evidence",
            )
            first.verify_evidence(evidence.evidence_id, "independent test")
            grant = first.grant_permission(
                mission.mission_id,
                PermissionAction.SPEND,
                "budget:persistent",
                "Use the bounded test budget",
                mode=PermissionMode.BOUNDED_INDEFINITE,
                scope="persistent test only",
                max_actions=2,
                budget_limit_cents=50,
                grant_id="persist-grant",
            )
            first.use_permission(
                mission.mission_id,
                grant.grant_id,
                spent_cents=25,
                idempotency_key="persist-use",
            )
            first.close()

            reopened = MissionService(path)
            try:
                persisted_evidence = reopened.store.get_evidence(evidence.evidence_id)
                persisted_grant = reopened.store.get_permission_grant(grant.grant_id)
                self.assertIsNotNone(persisted_evidence.verified_at)
                self.assertEqual(persisted_evidence.verification_method, "independent test")
                self.assertEqual(
                    (persisted_grant.actions_used, persisted_grant.spent_cents), (1, 25)
                )
            finally:
                reopened.close()

    def test_no_selection_while_waiting_verifying_or_terminal(self) -> None:
        self._activate()
        self.service.add_task("mission-1", "Work", task_id="work")
        self.service.start_task("work")
        self.service.wait_for_user("mission-1")
        self.assertIsNone(self.service.select_next_task("mission-1"))
        self.service.resume_mission("mission-1")
        self.service.begin_verification("mission-1")
        self.assertIsNone(self.service.select_next_task("mission-1"))
        self.service.begin_task_verification("work")
        evidence = self.service.record_evidence(
            "mission-1",
            "The work passed review.",
            kind=EvidenceKind.REVIEW,
            task_id="work",
            evidence_id="work-evidence",
        )
        self.service.verify_evidence(evidence.evidence_id, "independent review")
        self.service.complete_task("work")
        mission_evidence = self.service.record_evidence(
            "mission-1",
            "The mission acceptance criteria passed.",
            kind=EvidenceKind.REVIEW,
            evidence_id="mission-evidence",
        )
        self.service.verify_evidence(
            mission_evidence.evidence_id, "independent review"
        )
        self.service.complete_mission("mission-1")
        self.assertIsNone(self.service.select_next_task("mission-1"))

    def test_escalation_waiting_and_resolution_resume(self) -> None:
        self._activate()
        task = self.service.add_task("mission-1", "Blocked work", task_id="blocked")
        escalation = self.service.escalate(
            "mission-1",
            "Choose",
            "Two plausible choices exist.",
            "The product could differ.",
            task_id=task.task_id,
            escalation_id="esc-1",
        )
        self.assertEqual(
            self.store.require_mission("mission-1").state, MissionState.WAITING_FOR_USER
        )
        self.assertEqual(
            self.store.require_task(task.task_id).state, TaskStatus.NEEDS_USER
        )

        with self.assertRaises(ValidationError):
            self.service.resolve_escalation(
                escalation.escalation_id, status=EscalationStatus.OPEN.value
            )

        self.assertIsNone(self.service.select_next_task("mission-1"))
        resolved = self.service.resolve_escalation(escalation.escalation_id)
        self.assertEqual(resolved.status, EscalationStatus.RESOLVED)
        self.assertEqual(
            self.store.require_mission("mission-1").state, MissionState.ACTIVE
        )
        self.assertEqual(
            self.store.require_task(task.task_id).state, TaskStatus.READY
        )

    def test_declining_escalation_does_not_auto_resume_mission(self) -> None:
        self._activate()
        task = self.service.add_task("mission-1", "Blocked work", task_id="declined")
        escalation = self.service.escalate(
            "mission-1",
            "Choose",
            "A material choice is unresolved.",
            "The result could change.",
            task_id=task.task_id,
            escalation_id="declined-escalation",
        )
        resolved = self.service.resolve_escalation(
            escalation.escalation_id, status=EscalationStatus.DECLINED
        )
        self.assertEqual(resolved.status, EscalationStatus.DECLINED)
        self.assertEqual(
            self.store.require_mission("mission-1").state,
            MissionState.WAITING_FOR_USER,
        )
        self.assertEqual(
            self.store.require_task(task.task_id).state, TaskStatus.NEEDS_USER
        )
        self.assertIsNone(self.service.select_next_task("mission-1"))

    def test_permission_modes_and_atomic_one_time_consumption(self) -> None:
        self._activate()
        once = self.service.grant_permission(
            "mission-1",
            PermissionAction.SEND_MESSAGE,
            "user:design-partner",
            "Send the approved test invitation",
            grant_id="once",
        )
        standing = self.service.grant_permission(
            "mission-1",
            PermissionAction.OUTREACH,
            "audience:design-partners",
            "Run the approved bounded campaign",
            mode=PermissionMode.BOUNDED_INDEFINITE,
            scope="approved audience only",
            max_actions=10,
            grant_id="standing",
        )
        self.assertTrue(
            self.service.has_permission(
                "mission-1", PermissionAction.SEND_MESSAGE, once.resource
            )
        )
        consumed = self.service.consume_permission(once.grant_id)
        self.assertEqual(
            consumed.consumed_at,
            self.store.get_permission_grant(once.grant_id).consumed_at,
        )
        self.assertFalse(
            self.service.has_permission(
                "mission-1", PermissionAction.SEND_MESSAGE, once.resource
            )
        )
        with self.assertRaises(PermissionUnavailableError):
            self.service.consume_permission(once.grant_id)
        self.assertTrue(
            self.service.has_permission(
                "mission-1", PermissionAction.OUTREACH, standing.resource
            )
        )
        self.service.revoke_permission(standing.grant_id)
        self.assertFalse(
            self.service.has_permission(
                "mission-1", PermissionAction.OUTREACH, standing.resource
            )
        )

        events = self.store.list_events("mission-1")
        self.assertEqual(
            sum(event.event_type is EventType.PERMISSION_CONSUMED for event in events),
            1,
        )

    def test_permission_consumption_rolls_back_if_audit_append_fails(self) -> None:
        self._activate()
        grant = self.service.grant_permission(
            "mission-1",
            PermissionAction.DEPLOY,
            "staging/project-a",
            "Deploy the reviewed preview",
            grant_id="rollback-grant",
        )
        with patch.object(
            self.store, "create_event", side_effect=RuntimeError("audit unavailable")
        ):
            with self.assertRaisesRegex(RuntimeError, "audit unavailable"):
                self.service.consume_permission(grant.grant_id)
        persisted = self.store.get_permission_grant(grant.grant_id)
        self.assertIsNotNone(persisted)
        self.assertIsNone(persisted.consumed_at)
        self.assertTrue(
            self.service.has_permission(
                "mission-1", PermissionAction.DEPLOY, "staging/project-a"
            )
        )

        self.assertEqual(
            self.store.connection.execute(
                "SELECT COUNT(*) FROM permission_uses WHERE grant_id = ?",
                (grant.grant_id,),
            ).fetchone()[0],
            0,
        )

    def test_standing_permission_use_is_bounded_and_idempotency_protected(self) -> None:
        self._activate()
        grant = self.service.grant_permission(
            "mission-1",
            PermissionAction.SPEND,
            "budget:test",
            "Use the approved test budget",
            mode=PermissionMode.BOUNDED_INDEFINITE,
            scope="test budget only",
            max_actions=3,
            budget_limit_cents=100,
            grant_id="bounded",
        )
        first = self.service.use_permission(
            "mission-1", grant.grant_id, spent_cents=60, idempotency_key="use-1"
        )
        self.assertEqual((first.actions_used, first.spent_cents), (1, 60))
        with self.assertRaises(ConflictError):
            self.service.use_permission(
                "mission-1", grant.grant_id, spent_cents=60, idempotency_key="use-1"
            )
        second = self.service.use_permission(
            "mission-1", grant.grant_id, spent_cents=40, idempotency_key="use-2"
        )
        self.assertEqual((second.actions_used, second.spent_cents), (2, 100))
        self.assertFalse(
            self.service.has_permission(
                "mission-1", PermissionAction.SPEND, "budget:test"
            )
        )
        with self.assertRaises(PermissionUnavailableError):
            self.service.use_permission(
                "mission-1", grant.grant_id, idempotency_key="use-3"
            )

    def test_permission_grants_require_bounded_scope_and_owner_approval(self) -> None:
        with self.assertRaises(InvalidTransitionError):
            self.service.grant_permission(
                "mission-1",
                PermissionAction.DEPLOY,
                "staging/project-a",
                "Deploy before alignment",
            )
        self._activate()
        with self.assertRaises(ValidationError):
            self.service.grant_permission(
                "mission-1",
                PermissionAction.OUTREACH,
                "audience:test",
                "Unbounded campaign",
                mode=PermissionMode.BOUNDED_INDEFINITE,
                scope="audience only",
            )
        with self.assertRaises(ValidationError):
            self.service.grant_permission(
                "mission-1",
                PermissionAction.OUTREACH,
                "*",
                "Wildcard campaign",
                mode=PermissionMode.BOUNDED_INDEFINITE,
                scope="*",
                max_actions=1,
            )
        with self.assertRaises(ConflictError):
            self.service.grant_permission(
                "mission-1",
                PermissionAction.DEPLOY,
                "staging/project-a",
                "Another user's grant",
                approved_by="another-user",
            )

    def test_future_schema_is_rejected_on_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "future.sqlite3"
            store = SQLiteMissionStore(path)
            store.connection.execute(
                "UPDATE schema_meta SET value = '999' WHERE key = 'version'"
            )
            store.close()
            with self.assertRaises(ValidationError):
                SQLiteMissionStore(path)

    def test_audit_events_are_append_only_and_semantic_payloads_are_sanitized(self) -> None:
        event = self.store.list_events("mission-1")[0]
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.connection.execute(
                "UPDATE mission_events SET payload_json = '{}' WHERE event_id = ?",
                (event.event_id,),
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.connection.execute(
                "DELETE FROM mission_events WHERE event_id = ?", (event.event_id,)
            )
        with self.assertRaises(ValidationError):
            self.store.create_event(
                replace(
                    event,
                    event_id="leaky-event",
                    payload={"provider": "secret-provider"},
                )
            )


if __name__ == "__main__":
    unittest.main()

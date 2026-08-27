"""Kora-owned mission orchestration over the SQLite mission repository."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping
from uuid import uuid4

from kora.mission.domain import (
    Artifact,
    ArtifactKind,
    Assumption,
    AssumptionStatus,
    Checkpoint,
    CheckpointType,
    Decision,
    DomainEvent,
    Escalation,
    EscalationStatus,
    Evidence,
    EvidenceKind,
    EventType,
    Mission,
    MissionState,
    PermissionAction,
    PermissionGrant,
    PermissionMode,
    Task,
    TaskDependency,
    TaskStatus,
    normalize_timestamp,
    utc_now,
)
from kora.mission.errors import (
    ConflictError,
    DependencyError,
    InvalidTransitionError,
    NotFoundError,
    PermissionUnavailableError,
    ValidationError,
)
from kora.mission.store import SQLiteMissionStore


# Explicit transition matrices make the lifecycle reviewable and prevent a
# caller from inferring a new mission state from a task or runtime result.
MISSION_TRANSITIONS: Mapping[MissionState, frozenset[MissionState]] = {
    MissionState.PROPOSED: frozenset(
        {MissionState.ALIGNED, MissionState.STOPPED, MissionState.FAILED}
    ),
    MissionState.ALIGNED: frozenset(
        {MissionState.ACTIVE, MissionState.STOPPED, MissionState.FAILED}
    ),
    MissionState.ACTIVE: frozenset(
        {
            MissionState.WAITING_FOR_USER,
            MissionState.VERIFYING,
            MissionState.STOPPED,
            MissionState.FAILED,
        }
    ),
    MissionState.WAITING_FOR_USER: frozenset(
        {MissionState.ACTIVE, MissionState.STOPPED, MissionState.FAILED}
    ),
    MissionState.VERIFYING: frozenset(
        {
            MissionState.ACTIVE,
            MissionState.COMPLETED,
            MissionState.STOPPED,
            MissionState.FAILED,
        }
    ),
    MissionState.COMPLETED: frozenset(),
    MissionState.STOPPED: frozenset(),
    MissionState.FAILED: frozenset(),
}


TASK_TRANSITIONS: Mapping[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.READY: frozenset(
        {
            TaskStatus.IN_PROGRESS,
            TaskStatus.NEEDS_USER,
            TaskStatus.BLOCKED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.BLOCKED: frozenset(
        {TaskStatus.READY, TaskStatus.NEEDS_USER, TaskStatus.CANCELLED}
    ),
    TaskStatus.IN_PROGRESS: frozenset(
        {
            TaskStatus.NEEDS_USER,
            TaskStatus.VERIFYING,
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.NEEDS_USER: frozenset(
        {
            TaskStatus.READY,
            TaskStatus.IN_PROGRESS,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.VERIFYING: frozenset(
        {
            TaskStatus.IN_PROGRESS,
            TaskStatus.NEEDS_USER,
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.COMPLETED: frozenset(),
    TaskStatus.FAILED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class MissionStatusReport:
    """A semantic, deterministic snapshot suitable for a headless caller."""

    mission: Mission
    tasks: tuple[Task, ...]
    open_escalations: tuple[Escalation, ...]
    next_task: Task | None


def _coerce_mission_state(value: MissionState | str) -> MissionState:
    if isinstance(value, MissionState):
        return value
    try:
        return MissionState(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"unknown mission state: {value!r}") from exc


def _coerce_task_status(value: TaskStatus | str) -> TaskStatus:
    if isinstance(value, TaskStatus):
        return value
    try:
        return TaskStatus(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"unknown task status: {value!r}") from exc


def _coerce_escalation_status(value: EscalationStatus | str) -> EscalationStatus:
    if isinstance(value, EscalationStatus):
        return value
    try:
        return EscalationStatus(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"unknown escalation status: {value!r}") from exc


def _coerce_permission_action(value: PermissionAction | str) -> PermissionAction:
    if isinstance(value, PermissionAction):
        return value
    try:
        return PermissionAction(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"unknown permission action: {value!r}") from exc


def _coerce_permission_mode(value: PermissionMode | str) -> PermissionMode:
    if isinstance(value, PermissionMode):
        return value
    try:
        return PermissionMode(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"unknown permission mode: {value!r}") from exc


class MissionService:
    """Create and advance one Kora mission without consulting Hermes state."""

    def __init__(self, store: SQLiteMissionStore | str | Path = ":memory:") -> None:
        self.store = (
            store
            if isinstance(store, SQLiteMissionStore)
            else SQLiteMissionStore(store)
        )

    def close(self) -> None:
        self.store.close()

    def __enter__(self) -> "MissionService":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # Mission lifecycle ----------------------------------------------------

    def create_mission(
        self,
        title: str,
        objective: str,
        definition_of_done: str,
        *,
        exclusions: Iterable[str] = (),
        mission_id: str | None = None,
        created_at: datetime | None = None,
    ) -> Mission:
        timestamp = normalize_timestamp(created_at or utc_now())
        if isinstance(exclusions, str):
            raise ValidationError("exclusions must be a sequence of strings")
        mission = Mission(
            mission_id=mission_id or self._new_id("mission"),
            title=title,
            objective=objective,
            definition_of_done=definition_of_done,
            exclusions=tuple(exclusions),
            created_at=timestamp,
            updated_at=timestamp,
        )
        with self.store.transaction(immediate=True):
            self.store.create_mission(mission)
            self._record_event(
                mission_id=mission.mission_id,
                event_type=EventType.MISSION_CREATED,
                entity_id=mission.mission_id,
                payload={"state": mission.state.value, "title": mission.title},
                created_at=timestamp,
            )
        return mission

    def transition_mission(
        self,
        mission_id: str,
        target: MissionState | str,
        *,
        reason: str | None = None,
        at: datetime | None = None,
    ) -> Mission:
        target_state = _coerce_mission_state(target)
        timestamp = normalize_timestamp(at or utc_now())
        with self.store.transaction(immediate=True):
            current = self.store.require_mission(mission_id)
            self._validate_mission_transition(current.state, target_state)
            updated = self._transition_mission_in_transaction(
                current,
                target_state,
                reason=reason,
                at=timestamp,
            )
        return updated

    def align_mission(self, mission_id: str, *, at: datetime | None = None) -> Mission:
        return self.transition_mission(mission_id, MissionState.ALIGNED, at=at)

    transition = transition_mission

    def activate_mission(
        self, mission_id: str, *, at: datetime | None = None
    ) -> Mission:
        return self.transition_mission(mission_id, MissionState.ACTIVE, at=at)

    def wait_for_user(self, mission_id: str, *, at: datetime | None = None) -> Mission:
        return self.transition_mission(mission_id, MissionState.WAITING_FOR_USER, at=at)

    def begin_verification(
        self, mission_id: str, *, at: datetime | None = None
    ) -> Mission:
        return self.transition_mission(mission_id, MissionState.VERIFYING, at=at)

    def complete_mission(
        self, mission_id: str, *, at: datetime | None = None
    ) -> Mission:
        return self.transition_mission(mission_id, MissionState.COMPLETED, at=at)

    def stop_mission(
        self,
        mission_id: str,
        *,
        reason: str | None = None,
        at: datetime | None = None,
    ) -> Mission:
        return self.transition_mission(
            mission_id,
            MissionState.STOPPED,
            reason=reason,
            at=at,
        )

    def fail_mission(
        self,
        mission_id: str,
        *,
        reason: str | None = None,
        at: datetime | None = None,
    ) -> Mission:
        return self.transition_mission(
            mission_id,
            MissionState.FAILED,
            reason=reason,
            at=at,
        )

    def resume_mission(self, mission_id: str, *, at: datetime | None = None) -> Mission:
        current = self.store.require_mission(mission_id)
        if current.state not in {
            MissionState.WAITING_FOR_USER,
            MissionState.VERIFYING,
        }:
            raise InvalidTransitionError(
                "only waiting_for_user or verifying missions can resume"
            )
        return self.transition_mission(mission_id, MissionState.ACTIVE, at=at)

    def get_mission(self, mission_id: str) -> Mission:
        return self.store.require_mission(mission_id)

    def get_task(self, task_id: str) -> Task:
        return self.store.require_task(task_id)

    # Task graph -----------------------------------------------------------

    def add_task(
        self,
        mission_id: str,
        title: str,
        *,
        description: str = "",
        priority: int = 0,
        task_id: str | None = None,
        depends_on: Iterable[str] = (),
        created_at: datetime | None = None,
    ) -> Task:
        timestamp = normalize_timestamp(created_at or utc_now())
        if isinstance(depends_on, str):
            raise ValidationError("depends_on must be a sequence of task IDs")
        dependency_ids = tuple(depends_on)
        if any(
            not isinstance(value, str) or not value.strip() for value in dependency_ids
        ):
            raise ValidationError("depends_on must contain non-empty task IDs")
        with self.store.transaction(immediate=True):
            mission = self.store.require_mission(mission_id)
            self._ensure_mission_accepts_work(mission)
            task = Task(
                task_id=task_id or self._new_id("task"),
                mission_id=mission_id,
                title=title,
                description=description,
                priority=priority,
                created_at=timestamp,
                updated_at=timestamp,
            )
            self.store.create_task(task)
            self._record_event(
                mission_id=mission_id,
                event_type=EventType.TASK_CREATED,
                entity_id=task.task_id,
                payload={"priority": task.priority, "state": task.state.value},
                created_at=timestamp,
            )
            for prerequisite_id in dependency_ids:
                self._add_dependency_in_transaction(
                    mission_id,
                    task.task_id,
                    prerequisite_id,
                    at=timestamp,
                )
            self._refresh_task_states_in_transaction(mission_id, at=timestamp)
            return self.store.require_task(task.task_id)

    def add_dependency(
        self,
        mission_id: str,
        task_id: str,
        depends_on_task_id: str,
        *,
        created_at: datetime | None = None,
    ) -> TaskDependency:
        timestamp = normalize_timestamp(created_at or utc_now())
        with self.store.transaction(immediate=True):
            mission = self.store.require_mission(mission_id)
            self._ensure_mission_accepts_work(mission)
            dependency = self._add_dependency_in_transaction(
                mission_id,
                task_id,
                depends_on_task_id,
                at=timestamp,
            )
            self._refresh_task_states_in_transaction(mission_id, at=timestamp)
        return dependency

    def transition_task(
        self,
        task_id: str,
        target: TaskStatus | str,
        *,
        at: datetime | None = None,
    ) -> Task:
        target_status = _coerce_task_status(target)
        timestamp = normalize_timestamp(at or utc_now())
        with self.store.transaction(immediate=True):
            current = self.store.require_task(task_id)
            mission = self.store.require_mission(current.mission_id)
            self._ensure_mission_accepts_work(mission)
            self._refresh_task_states_in_transaction(current.mission_id, at=timestamp)
            current = self.store.require_task(task_id)
            self._validate_task_transition(current.state, target_status)
            prerequisites = self.store.list_prerequisites(task_id)
            resolved = all(task.state is TaskStatus.COMPLETED for task in prerequisites)
            if target_status is TaskStatus.READY and not resolved:
                raise InvalidTransitionError(
                    f"task {task_id} cannot become ready while dependencies are incomplete"
                )
            if target_status is TaskStatus.BLOCKED and resolved:
                raise InvalidTransitionError(
                    f"task {task_id} cannot become blocked without an incomplete dependency"
                )
            if target_status is TaskStatus.IN_PROGRESS:
                if mission.state is not MissionState.ACTIVE:
                    raise InvalidTransitionError(
                        "a task can start only while its mission is active"
                    )
                if not resolved:
                    raise InvalidTransitionError(
                        f"task {task_id} is blocked by an incomplete dependency"
                    )
            updated = self._transition_task_in_transaction(
                current,
                target_status,
                at=timestamp,
            )
            if target_status is TaskStatus.COMPLETED:
                self._refresh_task_states_in_transaction(
                    current.mission_id, at=timestamp
                )
        return updated

    def start_task(self, task_id: str, *, at: datetime | None = None) -> Task:
        return self.transition_task(task_id, TaskStatus.IN_PROGRESS, at=at)

    def mark_task_needs_user(self, task_id: str, *, at: datetime | None = None) -> Task:
        return self.transition_task(task_id, TaskStatus.NEEDS_USER, at=at)

    def begin_task_verification(
        self, task_id: str, *, at: datetime | None = None
    ) -> Task:
        return self.transition_task(task_id, TaskStatus.VERIFYING, at=at)

    def complete_task(self, task_id: str, *, at: datetime | None = None) -> Task:
        return self.transition_task(task_id, TaskStatus.COMPLETED, at=at)

    def fail_task(self, task_id: str, *, at: datetime | None = None) -> Task:
        return self.transition_task(task_id, TaskStatus.FAILED, at=at)

    def cancel_task(self, task_id: str, *, at: datetime | None = None) -> Task:
        return self.transition_task(task_id, TaskStatus.CANCELLED, at=at)

    def select_next_task(self, mission_id: str) -> Task | None:
        """Select the highest-priority ready task, or none outside ACTIVE."""

        with self.store.transaction(immediate=True):
            mission = self.store.require_mission(mission_id)
            if mission.state is not MissionState.ACTIVE:
                return None
            self._refresh_task_states_in_transaction(mission_id)
            ready = self.store.list_tasks(mission_id, TaskStatus.READY)
            return ready[0] if ready else None

    next_task = select_next_task

    def get_status(self, mission_id: str) -> MissionStatusReport:
        mission = self.store.require_mission(mission_id)
        next_task = self.select_next_task(mission_id)
        mission = self.store.require_mission(mission_id)
        return MissionStatusReport(
            mission=mission,
            tasks=tuple(self.store.list_tasks(mission_id)),
            open_escalations=tuple(
                self.store.list_escalations(mission_id, EscalationStatus.OPEN)
            ),
            next_task=next_task,
        )

    status = get_status

    # Semantic mission records --------------------------------------------

    def record_decision(
        self,
        mission_id: str,
        summary: str,
        decision: str,
        *,
        rationale: str = "",
        decision_id: str | None = None,
        created_at: datetime | None = None,
    ) -> Decision:
        timestamp = normalize_timestamp(created_at or utc_now())
        record = Decision(
            decision_id=decision_id or self._new_id("decision"),
            mission_id=mission_id,
            summary=summary,
            decision=decision,
            rationale=rationale,
            created_at=timestamp,
        )
        with self.store.transaction(immediate=True):
            self.store.require_mission(mission_id)
            self.store.create_decision(record)
            self._record_event(
                mission_id=mission_id,
                event_type=EventType.DECISION_RECORDED,
                entity_id=record.decision_id,
                payload={"summary": record.summary},
                created_at=timestamp,
            )
        return record

    add_decision = record_decision

    def record_assumption(
        self,
        mission_id: str,
        statement: str,
        *,
        rationale: str = "",
        status: AssumptionStatus = AssumptionStatus.OPEN,
        assumption_id: str | None = None,
        created_at: datetime | None = None,
        resolved_at: datetime | None = None,
    ) -> Assumption:
        timestamp = normalize_timestamp(created_at or utc_now())
        record = Assumption(
            assumption_id=assumption_id or self._new_id("assumption"),
            mission_id=mission_id,
            statement=statement,
            rationale=rationale,
            status=status,
            created_at=timestamp,
            resolved_at=resolved_at,
        )
        with self.store.transaction(immediate=True):
            self.store.require_mission(mission_id)
            self.store.create_assumption(record)
            self._record_event(
                mission_id=mission_id,
                event_type=EventType.ASSUMPTION_RECORDED,
                entity_id=record.assumption_id,
                payload={"status": record.status.value},
                created_at=timestamp,
            )
        return record

    add_assumption = record_assumption

    def record_checkpoint(
        self,
        mission_id: str,
        kind: CheckpointType,
        summary: str,
        *,
        task_id: str | None = None,
        checkpoint_id: str | None = None,
        created_at: datetime | None = None,
    ) -> Checkpoint:
        timestamp = normalize_timestamp(created_at or utc_now())
        record = Checkpoint(
            checkpoint_id=checkpoint_id or self._new_id("checkpoint"),
            mission_id=mission_id,
            task_id=task_id,
            kind=kind,
            summary=summary,
            created_at=timestamp,
        )
        with self.store.transaction(immediate=True):
            self.store.require_mission(mission_id)
            self._ensure_task_belongs_to_mission(task_id, mission_id)
            self.store.create_checkpoint(record)
            self._record_event(
                mission_id=mission_id,
                event_type=EventType.CHECKPOINT_RECORDED,
                entity_id=record.checkpoint_id,
                payload={"kind": record.kind.value},
                created_at=timestamp,
            )
        return record

    add_checkpoint = record_checkpoint

    def record_escalation(self, escalation: Escalation) -> Escalation:
        """Persist an escalation without changing mission state."""

        with self.store.transaction(immediate=True):
            self.store.require_mission(escalation.mission_id)
            self._ensure_task_belongs_to_mission(
                escalation.task_id, escalation.mission_id
            )
            self.store.create_escalation(escalation)
            self._record_event(
                mission_id=escalation.mission_id,
                event_type=EventType.ESCALATION_RECORDED,
                entity_id=escalation.escalation_id,
                payload={"status": escalation.status.value},
                created_at=escalation.created_at,
            )
        return escalation

    add_escalation = record_escalation

    def escalate(
        self,
        mission_id: str,
        title: str,
        reason: str,
        impact: str,
        *,
        options: Iterable[str] = (),
        recommendation: str = "",
        consequence_of_waiting: str = "",
        requested_action: str = "",
        task_id: str | None = None,
        escalation_id: str | None = None,
        created_at: datetime | None = None,
    ) -> Escalation:
        timestamp = normalize_timestamp(created_at or utc_now())
        if isinstance(options, str):
            raise ValidationError("options must be a sequence of strings")
        record = Escalation(
            escalation_id=escalation_id or self._new_id("escalation"),
            mission_id=mission_id,
            task_id=task_id,
            title=title,
            reason=reason,
            impact=impact,
            options=tuple(options),
            recommendation=recommendation,
            consequence_of_waiting=consequence_of_waiting,
            requested_action=requested_action,
            created_at=timestamp,
        )
        with self.store.transaction(immediate=True):
            mission = self.store.require_mission(mission_id)
            if mission.state not in {
                MissionState.ACTIVE,
                MissionState.WAITING_FOR_USER,
            }:
                raise InvalidTransitionError(
                    "escalations can only be opened for active or waiting missions"
                )
            self._ensure_task_belongs_to_mission(task_id, mission_id)
            self.store.create_escalation(record)
            self._record_event(
                mission_id=mission_id,
                event_type=EventType.ESCALATION_RECORDED,
                entity_id=record.escalation_id,
                payload={"status": record.status.value},
                created_at=timestamp,
            )
            if task_id is not None:
                task = self.store.require_task(task_id)
                if task.state not in {
                    TaskStatus.COMPLETED,
                    TaskStatus.FAILED,
                    TaskStatus.CANCELLED,
                    TaskStatus.NEEDS_USER,
                }:
                    self._transition_task_in_transaction(
                        task,
                        TaskStatus.NEEDS_USER,
                        at=timestamp,
                    )
            if mission.state is MissionState.ACTIVE:
                self._transition_mission_in_transaction(
                    mission,
                    MissionState.WAITING_FOR_USER,
                    reason=None,
                    at=timestamp,
                )
        return record

    request_user = escalate

    def resolve_escalation(
        self,
        escalation_id: str,
        *,
        status: EscalationStatus | str = EscalationStatus.RESOLVED,
        resolved_at: datetime | None = None,
    ) -> Escalation:
        status_value = _coerce_escalation_status(status)
        if status_value is EscalationStatus.OPEN:
            raise ValidationError("an escalation resolution must be terminal")
        timestamp = normalize_timestamp(resolved_at or utc_now())
        with self.store.transaction(immediate=True):
            current = self.store.get_escalation(escalation_id)
            if current is None:
                raise NotFoundError(f"escalation not found: {escalation_id}")
            if current.status is not EscalationStatus.OPEN:
                raise ConflictError(f"escalation already resolved: {escalation_id}")
            updated = replace(current, status=status_value, resolved_at=timestamp)
            self.store.update_escalation(updated)
            self._record_event(
                mission_id=updated.mission_id,
                event_type=EventType.ESCALATION_RECORDED,
                entity_id=updated.escalation_id,
                payload={"status": updated.status.value},
                created_at=timestamp,
            )
            mission = self.store.require_mission(updated.mission_id)
            remaining = self.store.list_escalations(
                updated.mission_id,
                EscalationStatus.OPEN,
            )
            if mission.state is MissionState.WAITING_FOR_USER and not remaining:
                self._transition_mission_in_transaction(
                    mission,
                    MissionState.ACTIVE,
                    reason=None,
                    at=timestamp,
                )
        return updated

    def record_artifact(
        self,
        mission_id: str,
        name: str,
        locator: str,
        *,
        kind: ArtifactKind = ArtifactKind.OTHER,
        task_id: str | None = None,
        artifact_id: str | None = None,
        created_at: datetime | None = None,
    ) -> Artifact:
        timestamp = normalize_timestamp(created_at or utc_now())
        record = Artifact(
            artifact_id=artifact_id or self._new_id("artifact"),
            mission_id=mission_id,
            task_id=task_id,
            name=name,
            locator=locator,
            kind=kind,
            created_at=timestamp,
        )
        with self.store.transaction(immediate=True):
            self.store.require_mission(mission_id)
            self._ensure_task_belongs_to_mission(task_id, mission_id)
            self.store.create_artifact(record)
            self._record_event(
                mission_id=mission_id,
                event_type=EventType.ARTIFACT_RECORDED,
                entity_id=record.artifact_id,
                payload={"kind": record.kind.value, "name": record.name},
                created_at=timestamp,
            )
        return record

    add_artifact = record_artifact

    def record_evidence(
        self,
        mission_id: str,
        summary: str,
        *,
        kind: EvidenceKind = EvidenceKind.OTHER,
        artifact_id: str | None = None,
        task_id: str | None = None,
        locator: str | None = None,
        evidence_id: str | None = None,
        created_at: datetime | None = None,
    ) -> Evidence:
        timestamp = normalize_timestamp(created_at or utc_now())
        record = Evidence(
            evidence_id=evidence_id or self._new_id("evidence"),
            mission_id=mission_id,
            task_id=task_id,
            artifact_id=artifact_id,
            summary=summary,
            kind=kind,
            locator=locator,
            created_at=timestamp,
        )
        with self.store.transaction(immediate=True):
            self.store.require_mission(mission_id)
            self._ensure_task_belongs_to_mission(task_id, mission_id)
            if artifact_id is not None:
                artifacts = {
                    artifact.artifact_id: artifact
                    for artifact in self.store.list_artifacts(mission_id)
                }
                if artifact_id not in artifacts:
                    raise NotFoundError(f"artifact not found in mission: {artifact_id}")
            self.store.create_evidence(record)
            self._record_event(
                mission_id=mission_id,
                event_type=EventType.EVIDENCE_RECORDED,
                entity_id=record.evidence_id,
                payload={"kind": record.kind.value},
                created_at=timestamp,
            )
        return record

    add_evidence = record_evidence

    # Semantic permissions -------------------------------------------------

    def grant_permission(
        self,
        mission_id: str,
        action: PermissionAction | str,
        resource: str,
        purpose: str,
        *,
        mode: PermissionMode | str = PermissionMode.APPROVE_ONCE,
        scope: str = "",
        max_actions: int | None = None,
        budget_limit_cents: int | None = None,
        approved_by: str = "user",
        user_id: str = "owner",
        kora_id: str = "kora",
        grant_id: str | None = None,
        approved_at: datetime | None = None,
        expires_at: datetime | None = None,
    ) -> PermissionGrant:
        timestamp = normalize_timestamp(approved_at or utc_now())
        record = PermissionGrant(
            grant_id=grant_id or self._new_id("grant"),
            mission_id=mission_id,
            action=_coerce_permission_action(action),
            resource=resource,
            purpose=purpose,
            mode=_coerce_permission_mode(mode),
            scope=scope,
            max_actions=max_actions,
            budget_limit_cents=budget_limit_cents,
            approved_by=approved_by,
            user_id=user_id,
            kora_id=kora_id,
            approved_at=timestamp,
            expires_at=expires_at,
        )
        with self.store.transaction(immediate=True):
            mission = self.store.require_mission(mission_id)
            self._ensure_mission_accepts_work(mission)
            self.store.create_permission_grant(record)
            self._record_event(
                mission_id=mission_id,
                event_type=EventType.PERMISSION_GRANTED,
                entity_id=record.grant_id,
                payload={"action": record.action.value, "mode": record.mode.value},
                created_at=timestamp,
            )
        return record

    create_permission_grant = grant_permission

    def has_permission(
        self,
        mission_id: str,
        action: PermissionAction | str,
        resource: str,
        *,
        at: datetime | None = None,
    ) -> bool:
        action_value = _coerce_permission_action(action)
        moment = normalize_timestamp(at or utc_now())
        mission = self.store.require_mission(mission_id)
        if mission.state in {
            MissionState.COMPLETED,
            MissionState.STOPPED,
            MissionState.FAILED,
        }:
            return False
        return any(
            grant.resource == resource and grant.is_active(moment)
            for grant in self.store.list_permission_grants(mission_id, action_value)
        )

    def consume_permission(
        self,
        grant_id: str,
        *,
        consumed_at: datetime | None = None,
    ) -> PermissionGrant:
        timestamp = normalize_timestamp(consumed_at or utc_now())
        with self.store.transaction(immediate=True):
            existing = self.store.get_permission_grant(grant_id)
            if existing is None:
                raise NotFoundError(f"permission grant not found: {grant_id}")
            mission = self.store.require_mission(existing.mission_id)
            self._ensure_mission_accepts_work(mission)
            grant = self.store.consume_permission(grant_id, consumed_at=timestamp)
            if grant is None:
                raise PermissionUnavailableError(
                    f"permission grant is not available: {grant_id}"
                )
            self._record_event(
                mission_id=grant.mission_id,
                event_type=EventType.PERMISSION_CONSUMED,
                entity_id=grant.grant_id,
                payload={"mode": grant.mode.value},
                created_at=timestamp,
            )
        return grant

    def revoke_permission(
        self,
        grant_id: str,
        *,
        revoked_at: datetime | None = None,
    ) -> PermissionGrant:
        timestamp = normalize_timestamp(revoked_at or utc_now())
        with self.store.transaction(immediate=True):
            grant = self.store.revoke_permission(grant_id, revoked_at=timestamp)
            self._record_event(
                mission_id=grant.mission_id,
                event_type=EventType.PERMISSION_REVOKED,
                entity_id=grant.grant_id,
                payload={},
                created_at=timestamp,
            )
        return grant

    # Internal transaction helpers ----------------------------------------

    def _transition_mission_in_transaction(
        self,
        current: Mission,
        target: MissionState,
        *,
        reason: str | None,
        at: datetime,
    ) -> Mission:
        self._validate_mission_transition(current.state, target)
        if target is MissionState.ACTIVE:
            other_active = [
                mission
                for mission in self.store.list_missions(MissionState.ACTIVE)
                if mission.mission_id != current.mission_id
            ]
            if other_active:
                raise ConflictError(
                    "only one overarching mission may be active at a time"
                )
        failure_reason = current.failure_reason
        stop_reason = current.stop_reason
        if target is MissionState.FAILED:
            failure_reason = reason
        elif target is MissionState.STOPPED:
            stop_reason = reason
        updated = self.store.update_mission(
            replace(
                current,
                state=target,
                updated_at=at,
                failure_reason=failure_reason,
                stop_reason=stop_reason,
            ),
            expected_revision=current.revision,
        )
        self._record_event(
            mission_id=current.mission_id,
            event_type=EventType.MISSION_TRANSITIONED,
            entity_id=current.mission_id,
            payload={
                "from": current.state.value,
                "to": target.value,
                "reason": reason,
                "revision": updated.revision,
            },
            created_at=at,
        )
        return updated

    def _transition_task_in_transaction(
        self,
        current: Task,
        target: TaskStatus,
        *,
        at: datetime,
    ) -> Task:
        started_at = current.started_at
        finished_at = current.finished_at
        if target is TaskStatus.IN_PROGRESS and started_at is None:
            started_at = at
        if target in {
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }:
            finished_at = at
        elif target in {
            TaskStatus.READY,
            TaskStatus.IN_PROGRESS,
            TaskStatus.NEEDS_USER,
            TaskStatus.VERIFYING,
        }:
            finished_at = None
        updated = self.store.update_task(
            replace(
                current,
                state=target,
                updated_at=at,
                started_at=started_at,
                finished_at=finished_at,
            )
        )
        self._record_event(
            mission_id=current.mission_id,
            event_type=EventType.TASK_TRANSITIONED,
            entity_id=current.task_id,
            payload={"from": current.state.value, "to": target.value},
            created_at=at,
        )
        return updated

    def _add_dependency_in_transaction(
        self,
        mission_id: str,
        task_id: str,
        depends_on_task_id: str,
        *,
        at: datetime,
    ) -> TaskDependency:
        task = self.store.get_task(task_id)
        prerequisite = self.store.get_task(depends_on_task_id)
        if task is None or prerequisite is None:
            missing = task_id if task is None else depends_on_task_id
            raise NotFoundError(f"task not found: {missing}")
        if task.mission_id != mission_id or prerequisite.mission_id != mission_id:
            raise DependencyError("cross-mission dependencies are not allowed")
        if task.state in {
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }:
            raise DependencyError("terminal tasks cannot receive new dependencies")
        if (
            task.state not in {TaskStatus.READY, TaskStatus.BLOCKED}
            and prerequisite.state is not TaskStatus.COMPLETED
        ):
            raise DependencyError(
                "an in-progress or user-facing task cannot receive an unresolved dependency"
            )
        graph: dict[str, set[str]] = {}
        for existing in self.store.list_dependencies(mission_id):
            graph.setdefault(existing.task_id, set()).add(existing.depends_on_task_id)
        graph.setdefault(task_id, set()).add(depends_on_task_id)
        if self._reaches(graph, depends_on_task_id, task_id):
            raise DependencyError("task dependency would introduce a cycle")
        dependency = TaskDependency(
            mission_id=mission_id,
            task_id=task_id,
            depends_on_task_id=depends_on_task_id,
            created_at=at,
        )
        self.store.create_dependency(dependency)
        self._record_event(
            mission_id=mission_id,
            event_type=EventType.TASK_DEPENDENCY_ADDED,
            entity_id=task_id,
            payload={"depends_on_task_id": depends_on_task_id},
            created_at=at,
        )
        return dependency

    def _refresh_task_states_in_transaction(
        self,
        mission_id: str,
        *,
        at: datetime | None = None,
    ) -> None:
        timestamp = normalize_timestamp(at or utc_now())
        tasks = self.store.list_tasks(mission_id)
        by_id = {task.task_id: task for task in tasks}
        dependencies = self.store.list_dependencies(mission_id)
        prerequisites: dict[str, list[Task]] = {}
        for dependency in dependencies:
            prerequisite = by_id.get(dependency.depends_on_task_id)
            if prerequisite is not None:
                prerequisites.setdefault(dependency.task_id, []).append(prerequisite)
        for task in tasks:
            if task.state not in {TaskStatus.READY, TaskStatus.BLOCKED}:
                continue
            resolved = all(
                prerequisite.state is TaskStatus.COMPLETED
                for prerequisite in prerequisites.get(task.task_id, [])
            )
            desired = TaskStatus.READY if resolved else TaskStatus.BLOCKED
            if desired is task.state:
                continue
            self.store.update_task(replace(task, state=desired, updated_at=timestamp))
            self._record_event(
                mission_id=mission_id,
                event_type=EventType.TASK_TRANSITIONED,
                entity_id=task.task_id,
                payload={"from": task.state.value, "to": desired.value},
                created_at=timestamp,
            )

    def _record_event(
        self,
        *,
        mission_id: str,
        event_type: EventType,
        entity_id: str,
        payload: Mapping[str, object],
        created_at: datetime,
    ) -> DomainEvent:
        event = DomainEvent(
            event_id=self._new_id("event"),
            mission_id=mission_id,
            event_type=event_type,
            entity_id=entity_id,
            payload=payload,
            created_at=created_at,
        )
        return self.store.create_event(event)

    @staticmethod
    def _validate_mission_transition(
        current: MissionState,
        target: MissionState,
    ) -> None:
        if target not in MISSION_TRANSITIONS[current]:
            raise InvalidTransitionError(
                f"invalid mission transition: {current.value} -> {target.value}"
            )

    @staticmethod
    def _validate_task_transition(current: TaskStatus, target: TaskStatus) -> None:
        if target not in TASK_TRANSITIONS[current]:
            raise InvalidTransitionError(
                f"invalid task transition: {current.value} -> {target.value}"
            )

    @staticmethod
    def _reaches(graph: Mapping[str, set[str]], start: str, target: str) -> bool:
        pending = [start]
        visited: set[str] = set()
        while pending:
            current = pending.pop()
            if current == target:
                return True
            if current in visited:
                continue
            visited.add(current)
            pending.extend(graph.get(current, ()))
        return False

    @staticmethod
    def _new_id(prefix: str) -> str:
        return f"{prefix}-{uuid4().hex}"

    @staticmethod
    def _ensure_mission_accepts_work(mission: Mission) -> None:
        if mission.state in {
            MissionState.COMPLETED,
            MissionState.STOPPED,
            MissionState.FAILED,
        }:
            raise ConflictError(
                f"mission {mission.mission_id} is terminal and cannot change"
            )

    def _ensure_task_belongs_to_mission(
        self,
        task_id: str | None,
        mission_id: str,
    ) -> None:
        if task_id is None:
            return
        task = self.store.get_task(task_id)
        if task is None:
            raise NotFoundError(f"task not found: {task_id}")
        if task.mission_id != mission_id:
            raise ConflictError("task belongs to another mission")


# The control-plane name is useful to callers that prefer the architecture's
# component vocabulary.
MissionControlPlane = MissionService
MissionControlService = MissionService

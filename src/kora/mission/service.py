"""Kora-owned mission orchestration over the SQLite mission repository."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from math import isfinite
from pathlib import Path
from typing import Iterable, Mapping
from uuid import uuid4

from kora.mission.domain import (
    Artifact,
    ArtifactKind,
    AttemptStatus,
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
    TaskAttempt,
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
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.NEEDS_USER: frozenset(
        {
            TaskStatus.READY,
            TaskStatus.BLOCKED,
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
    TaskStatus.FAILED: frozenset({TaskStatus.READY}),
    TaskStatus.CANCELLED: frozenset(),
}


ATTEMPT_TRANSITIONS: Mapping[AttemptStatus, frozenset[AttemptStatus]] = {
    AttemptStatus.CREATED: frozenset(
        {AttemptStatus.RUNNING, AttemptStatus.INTERRUPTED}
    ),
    AttemptStatus.RUNNING: frozenset(
        {
            AttemptStatus.VERIFYING,
            AttemptStatus.FAILED,
            AttemptStatus.INTERRUPTED,
            AttemptStatus.UNKNOWN,
        }
    ),
    AttemptStatus.VERIFYING: frozenset(
        {
            AttemptStatus.SUCCEEDED,
            AttemptStatus.FAILED,
            AttemptStatus.INTERRUPTED,
            AttemptStatus.UNKNOWN,
        }
    ),
    AttemptStatus.SUCCEEDED: frozenset(),
    AttemptStatus.FAILED: frozenset(),
    AttemptStatus.INTERRUPTED: frozenset(),
    AttemptStatus.UNKNOWN: frozenset(
        {
            AttemptStatus.VERIFYING,
            AttemptStatus.FAILED,
            AttemptStatus.INTERRUPTED,
        }
    ),
}


_DEFAULT_ATTEMPT_LEASE_SECONDS = 60.0


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


def _coerce_attempt_status(value: AttemptStatus | str) -> AttemptStatus:
    if isinstance(value, AttemptStatus):
        return value
    try:
        return AttemptStatus(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"unknown attempt status: {value!r}") from exc


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

    def __init__(
        self,
        store: SQLiteMissionStore | str | Path = ":memory:",
        *,
        owner_ref: str = "owner",
    ) -> None:
        if not isinstance(owner_ref, str) or not owner_ref.strip():
            raise ValidationError("owner_ref must be a non-empty string")
        self.owner_ref = owner_ref
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
            owner_ref=self.owner_ref,
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
        expected_revision: int | None = None,
        at: datetime | None = None,
    ) -> Mission:
        target_state = _coerce_mission_state(target)
        timestamp = normalize_timestamp(at or utc_now())
        with self.store.transaction(immediate=True):
            current = self._require_owned_mission(mission_id)
            if expected_revision is not None and expected_revision != current.revision:
                raise ConflictError(
                    f"stale mission revision for {mission_id}: expected "
                    f"{expected_revision}, current {current.revision}"
                )
            self._validate_mission_transition(current.state, target_state)
            if target_state is MissionState.COMPLETED:
                self._ensure_mission_completion_ready(current.mission_id)
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
        self,
        mission_id: str,
        *,
        lease_owner: str | None = None,
        fencing_token: int | None = None,
        expected_revision: int | None = None,
        at: datetime | None = None,
    ) -> Mission | TaskAttempt:
        # The mission API historically owns this name.  Attempt verification
        # uses the same domain vocabulary, so dispatch an attempt ID to the
        # explicit attempt operation while preserving existing mission calls.
        if (
            self.store.get_mission(mission_id) is None
            and self.store.get_attempt(mission_id) is not None
        ):
            return self.begin_attempt_verification(
                mission_id,
                lease_owner=lease_owner,
                fencing_token=fencing_token,
                expected_revision=expected_revision,
                at=at,
            )
        return self.transition_mission(
            mission_id,
            MissionState.VERIFYING,
            expected_revision=expected_revision,
            at=at,
        )

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
        current = self._require_owned_mission(mission_id)
        if current.state not in {
            MissionState.WAITING_FOR_USER,
            MissionState.VERIFYING,
        }:
            raise InvalidTransitionError(
                "only waiting_for_user or verifying missions can resume"
            )
        return self.transition_mission(mission_id, MissionState.ACTIVE, at=at)

    def get_mission(self, mission_id: str) -> Mission:
        return self._require_owned_mission(mission_id)

    def get_task(self, task_id: str) -> Task:
        task = self.store.require_task(task_id)
        self._require_owned_mission(task.mission_id)
        return task

    # Durable execution attempts ------------------------------------------

    def create_attempt(
        self,
        mission_id: str,
        task_id: str,
        idempotency_key: str,
        *,
        worker_role_id: str,
        route_id: str,
        quality_floor: float = 0.0,
        attempt_id: str | None = None,
        created_at: datetime | None = None,
    ) -> TaskAttempt:
        """Create or idempotently retrieve one attempt for a task.

        The role and route values are opaque private identifiers.  They are
        persisted for the coordinator but are intentionally absent from the
        semantic mission status projection and attempt audit payloads.
        """

        timestamp = normalize_timestamp(created_at or utc_now())
        with self.store.transaction(immediate=True):
            mission = self._require_owned_mission(mission_id)
            self._ensure_mission_accepts_work(mission)
            task = self.store.require_task(task_id)
            if task.mission_id != mission_id:
                raise ConflictError("attempt task belongs to another mission")
            requested = TaskAttempt(
                attempt_id=attempt_id or self._new_id("attempt"),
                mission_id=mission_id,
                task_id=task_id,
                idempotency_key=idempotency_key,
                worker_role_id=worker_role_id,
                route_id=route_id,
                quality_floor=quality_floor,
                created_at=timestamp,
                updated_at=timestamp,
            )
            existing = self.store.get_attempt_by_idempotency(
                mission_id, task_id, idempotency_key
            )
            if existing is not None:
                if attempt_id is not None and existing.attempt_id != attempt_id:
                    raise ConflictError(
                        "attempt idempotency key is bound to another attempt ID"
                    )
                self._ensure_attempt_scope_matches(existing, requested)
                return existing
            self.store.create_attempt(requested)
            self._record_event(
                mission_id=mission_id,
                event_type=EventType.ATTEMPT_CREATED,
                entity_id=requested.attempt_id,
                payload={
                    "status": requested.status.value,
                    "quality_floor": requested.quality_floor,
                },
                created_at=timestamp,
            )
            return requested

    def get_attempt(self, attempt_id: str) -> TaskAttempt:
        return self._require_owned_attempt(attempt_id)

    def list_attempts(
        self,
        mission_id: str,
        task_id: str | None = None,
        status: AttemptStatus | str | None = None,
    ) -> list[TaskAttempt]:
        self._require_owned_mission(mission_id)
        if task_id is not None:
            self._ensure_task_belongs_to_mission(task_id, mission_id)
        attempt_status = (
            _coerce_attempt_status(status) if status is not None else None
        )
        return self.store.list_attempts(mission_id, task_id, attempt_status)

    def claim_attempt(
        self,
        attempt_id: str,
        lease_owner: str,
        *,
        lease_expires_at: datetime | None = None,
        lease_ttl_seconds: float | int | None = None,
        lease_seconds: float | int | None = None,
        lease_duration_seconds: float | int | None = None,
        expected_revision: int | None = None,
        at: datetime | None = None,
    ) -> TaskAttempt:
        """Claim a created attempt or reclaim an expired running lease."""

        timestamp = normalize_timestamp(at or utc_now())
        owner = self._validate_lease_owner(lease_owner)
        expiry = self._resolve_lease_expiry(
            timestamp,
            lease_expires_at=lease_expires_at,
            lease_ttl_seconds=lease_ttl_seconds,
            lease_seconds=lease_seconds,
            lease_duration_seconds=lease_duration_seconds,
        )
        with self.store.transaction(immediate=True):
            current = self._require_owned_attempt(attempt_id)
            self._check_expected_attempt_revision(current, expected_revision)
            reclaimed = False
            if current.status is AttemptStatus.CREATED:
                if current.lease_owner is not None:
                    raise ConflictError(
                        f"created attempt already has a lease: {attempt_id}"
                    )
            elif current.status is AttemptStatus.RUNNING:
                if current.lease_expires_at is None:
                    raise ConflictError(
                        f"running attempt has no lease expiry: {attempt_id}"
                    )
                if current.lease_expires_at > timestamp:
                    raise ConflictError(f"attempt lease is still active: {attempt_id}")
                reclaimed = True
            else:
                self._validate_attempt_transition(
                    current.status, AttemptStatus.RUNNING
                )
            competing = self.store.get_live_attempt(current.task_id)
            if competing is not None and competing.attempt_id != current.attempt_id:
                if competing.has_active_lease(timestamp):
                    raise ConflictError(
                        f"task has an active competing attempt lease: {current.task_id}"
                    )
                raise ConflictError(
                    f"task already has a competing live attempt: {current.task_id}"
                )
            updated = self.store.update_attempt(
                replace(
                    current,
                    status=AttemptStatus.RUNNING,
                    lease_owner=owner,
                    lease_expires_at=expiry,
                    fencing_token=current.fencing_token + 1,
                    updated_at=timestamp,
                    started_at=current.started_at or timestamp,
                    finished_at=None,
                ),
                expected_revision=current.revision,
                _allow_status_change=True,
            )
            self._record_event(
                mission_id=updated.mission_id,
                event_type=EventType.ATTEMPT_TRANSITIONED,
                entity_id=updated.attempt_id,
                payload={
                    "from": current.status.value,
                    "to": updated.status.value,
                    "reclaimed": reclaimed,
                    "revision": updated.revision,
                },
                created_at=timestamp,
            )
            return updated

    def renew_lease(
        self,
        attempt_id: str,
        lease_owner: str,
        fencing_token: int,
        *,
        lease_expires_at: datetime | None = None,
        lease_ttl_seconds: float | int | None = None,
        lease_seconds: float | int | None = None,
        lease_duration_seconds: float | int | None = None,
        expected_revision: int | None = None,
        at: datetime | None = None,
    ) -> TaskAttempt:
        """Extend a running lease only when owner and fencing token match."""

        timestamp = normalize_timestamp(at or utc_now())
        owner = self._validate_lease_owner(lease_owner)
        token = self._validate_fencing_token(fencing_token)
        expiry = self._resolve_lease_expiry(
            timestamp,
            lease_expires_at=lease_expires_at,
            lease_ttl_seconds=lease_ttl_seconds,
            lease_seconds=lease_seconds,
            lease_duration_seconds=lease_duration_seconds,
        )
        with self.store.transaction(immediate=True):
            current = self._require_owned_attempt(attempt_id)
            self._check_expected_attempt_revision(current, expected_revision)
            if current.status is not AttemptStatus.RUNNING:
                raise InvalidTransitionError(
                    f"only running attempts can renew a lease: {attempt_id}"
                )
            self._check_attempt_fence(
                current,
                owner,
                token,
                at=timestamp,
                require_active_lease=True,
            )
            updated = self.store.update_attempt(
                replace(current, lease_expires_at=expiry, updated_at=timestamp),
                expected_revision=current.revision,
            )
            self._record_event(
                mission_id=updated.mission_id,
                event_type=EventType.ATTEMPT_LEASE_RENEWED,
                entity_id=updated.attempt_id,
                payload={"revision": updated.revision},
                created_at=timestamp,
            )
            return updated

    def begin_attempt_verification(
        self,
        attempt_id: str,
        *,
        lease_owner: str | None = None,
        fencing_token: int | None = None,
        expected_revision: int | None = None,
        at: datetime | None = None,
    ) -> TaskAttempt:
        timestamp = normalize_timestamp(at or utc_now())
        with self.store.transaction(immediate=True):
            current = self._require_owned_attempt(attempt_id)
            if current.status is not AttemptStatus.RUNNING:
                raise InvalidTransitionError(
                    f"only running attempts can begin verification: {attempt_id}"
                )
            if current.status is AttemptStatus.RUNNING and not current.has_active_lease(
                timestamp
            ):
                raise ConflictError(
                    f"attempt lease is no longer active: {current.attempt_id}"
                )
            self._check_attempt_fence(
                current,
                lease_owner,
                fencing_token,
                at=timestamp,
                require_active_lease=current.status is AttemptStatus.RUNNING,
            )
            return self._transition_attempt_in_transaction(
                current,
                AttemptStatus.VERIFYING,
                at=timestamp,
                expected_revision=expected_revision,
            )

    def succeed_attempt(
        self,
        attempt_id: str,
        *,
        result_summary: str | None = None,
        total_tokens: int | None = None,
        estimated_cost_usd: float | None = None,
        latency_ms: int | None = None,
        accepted: bool = True,
        lease_owner: str | None = None,
        fencing_token: int | None = None,
        expected_revision: int | None = None,
        at: datetime | None = None,
    ) -> TaskAttempt:
        if accepted is not True:
            raise ValidationError("succeeded attempts require accepted=True")
        timestamp = normalize_timestamp(at or utc_now())
        with self.store.transaction(immediate=True):
            current = self._require_owned_attempt(attempt_id)
            if current.status is not AttemptStatus.VERIFYING:
                raise InvalidTransitionError(
                    f"only verifying attempts can succeed: {attempt_id}"
                )
            self._check_attempt_fence(
                current,
                lease_owner,
                fencing_token,
                at=timestamp,
                require_active_lease=current.status is AttemptStatus.RUNNING,
            )
            return self._transition_attempt_in_transaction(
                current,
                AttemptStatus.SUCCEEDED,
                at=timestamp,
                expected_revision=expected_revision,
                result_summary=(
                    current.result_summary
                    if result_summary is None
                    else result_summary
                ),
                total_tokens=(
                    current.total_tokens if total_tokens is None else total_tokens
                ),
                estimated_cost_usd=(
                    current.estimated_cost_usd
                    if estimated_cost_usd is None
                    else estimated_cost_usd
                ),
                latency_ms=current.latency_ms if latency_ms is None else latency_ms,
                accepted=True,
                lease_owner=None,
                lease_expires_at=None,
                finished_at=timestamp,
            )

    def fail_attempt(
        self,
        attempt_id: str,
        *,
        error_summary: str | None = None,
        result_summary: str | None = None,
        total_tokens: int | None = None,
        estimated_cost_usd: float | None = None,
        latency_ms: int | None = None,
        accepted: bool = False,
        lease_owner: str | None = None,
        fencing_token: int | None = None,
        expected_revision: int | None = None,
        at: datetime | None = None,
    ) -> TaskAttempt:
        if accepted is not False:
            raise ValidationError("failed attempts require accepted=False")
        timestamp = normalize_timestamp(at or utc_now())
        with self.store.transaction(immediate=True):
            current = self._require_owned_attempt(attempt_id)
            if current.status not in {
                AttemptStatus.RUNNING,
                AttemptStatus.VERIFYING,
            }:
                raise InvalidTransitionError(
                    f"only running or verifying attempts can fail: {attempt_id}"
                )
            if current.status is AttemptStatus.RUNNING and not current.has_active_lease(
                timestamp
            ):
                raise ConflictError(
                    f"attempt lease is no longer active: {current.attempt_id}"
                )
            self._check_attempt_fence(
                current,
                lease_owner,
                fencing_token,
                at=timestamp,
                require_active_lease=current.status is AttemptStatus.RUNNING,
            )
            return self._transition_attempt_in_transaction(
                current,
                AttemptStatus.FAILED,
                at=timestamp,
                expected_revision=expected_revision,
                result_summary=(
                    current.result_summary
                    if result_summary is None
                    else result_summary
                ),
                error_summary=(
                    current.error_summary
                    if error_summary is None
                    else error_summary
                ),
                total_tokens=(
                    current.total_tokens if total_tokens is None else total_tokens
                ),
                estimated_cost_usd=(
                    current.estimated_cost_usd
                    if estimated_cost_usd is None
                    else estimated_cost_usd
                ),
                latency_ms=current.latency_ms if latency_ms is None else latency_ms,
                accepted=False,
                lease_owner=None,
                lease_expires_at=None,
                finished_at=timestamp,
            )

    def interrupt_attempt(
        self,
        attempt_id: str,
        *,
        reason: str | None = None,
        error_summary: str | None = None,
        lease_owner: str | None = None,
        fencing_token: int | None = None,
        expected_revision: int | None = None,
        at: datetime | None = None,
    ) -> TaskAttempt:
        if reason is not None and error_summary is not None and reason != error_summary:
            raise ValidationError("reason and error_summary must match when both given")
        timestamp = normalize_timestamp(at or utc_now())
        summary = error_summary if error_summary is not None else reason
        with self.store.transaction(immediate=True):
            current = self._require_owned_attempt(attempt_id)
            self._check_attempt_fence(
                current,
                lease_owner,
                fencing_token,
                at=timestamp,
                require_active_lease=current.status is AttemptStatus.RUNNING,
            )
            return self._transition_attempt_in_transaction(
                current,
                AttemptStatus.INTERRUPTED,
                at=timestamp,
                expected_revision=expected_revision,
                error_summary=(
                    current.error_summary if summary is None else summary
                ),
                accepted=None,
                lease_owner=None,
                lease_expires_at=None,
                finished_at=timestamp,
            )

    def mark_expired_attempt_unknown(
        self,
        attempt_id: str,
        *,
        reason: str | None = None,
        error_summary: str | None = None,
        lease_owner: str | None = None,
        fencing_token: int | None = None,
        expected_revision: int | None = None,
        at: datetime | None = None,
    ) -> TaskAttempt:
        if reason is not None and error_summary is not None and reason != error_summary:
            raise ValidationError("reason and error_summary must match when both given")
        timestamp = normalize_timestamp(at or utc_now())
        summary = error_summary if error_summary is not None else reason
        with self.store.transaction(immediate=True):
            current = self._require_owned_attempt(attempt_id)
            self._check_expected_attempt_revision(current, expected_revision)
            if current.status not in {
                AttemptStatus.RUNNING,
                AttemptStatus.VERIFYING,
            }:
                raise InvalidTransitionError(
                    f"only running or verifying attempts can expire to unknown: "
                    f"{attempt_id}"
                )
            if current.lease_expires_at is None:
                raise ConflictError(f"running attempt has no lease expiry: {attempt_id}")
            if current.lease_expires_at > timestamp:
                raise ConflictError(f"attempt lease is still active: {attempt_id}")
            self._check_attempt_fence(
                current,
                lease_owner,
                fencing_token,
                at=timestamp,
                require_active_lease=False,
            )
            return self._transition_attempt_in_transaction(
                current,
                AttemptStatus.UNKNOWN,
                at=timestamp,
                expected_revision=current.revision,
                error_summary=(
                    current.error_summary
                    if summary is None
                    else summary
                ),
                lease_owner=None,
                lease_expires_at=None,
            )

    def reconcile_unknown(
        self,
        attempt_id: str,
        target: AttemptStatus | str | None = None,
        *,
        status: AttemptStatus | str | None = None,
        reason: str | None = None,
        error_summary: str | None = None,
        result_summary: str | None = None,
        total_tokens: int | None = None,
        estimated_cost_usd: float | None = None,
        latency_ms: int | None = None,
        expected_revision: int | None = None,
        at: datetime | None = None,
    ) -> TaskAttempt:
        if target is not None and status is not None:
            if _coerce_attempt_status(target) is not _coerce_attempt_status(status):
                raise ValidationError("target and status must match when both given")
        target_value = target if target is not None else status
        if target_value is None:
            raise ValidationError("reconcile_unknown requires a target status")
        target_status = _coerce_attempt_status(target_value)
        allowed = {
            AttemptStatus.VERIFYING,
            AttemptStatus.FAILED,
            AttemptStatus.INTERRUPTED,
        }
        if target_status not in allowed:
            raise InvalidTransitionError(
                "unknown attempts can reconcile only to verifying, failed, or interrupted"
            )
        if reason is not None and error_summary is not None and reason != error_summary:
            raise ValidationError("reason and error_summary must match when both given")
        timestamp = normalize_timestamp(at or utc_now())
        summary = error_summary if error_summary is not None else reason
        changes: dict[str, object] = {
            "lease_owner": None,
            "lease_expires_at": None,
        }
        if result_summary is not None:
            changes["result_summary"] = result_summary
        if summary is not None:
            changes["error_summary"] = summary
        if total_tokens is not None:
            changes["total_tokens"] = total_tokens
        if estimated_cost_usd is not None:
            changes["estimated_cost_usd"] = estimated_cost_usd
        if latency_ms is not None:
            changes["latency_ms"] = latency_ms
        if target_status is AttemptStatus.VERIFYING:
            changes["accepted"] = None
            changes["finished_at"] = None
        elif target_status is AttemptStatus.FAILED:
            changes["accepted"] = False
            changes["finished_at"] = timestamp
        else:
            changes["accepted"] = None
            changes["finished_at"] = timestamp
        with self.store.transaction(immediate=True):
            current = self._require_owned_attempt(attempt_id)
            if current.status is not AttemptStatus.UNKNOWN:
                raise InvalidTransitionError(
                    f"only unknown attempts can be reconciled: {attempt_id}"
                )
            return self._transition_attempt_in_transaction(
                current,
                target_status,
                at=timestamp,
                expected_revision=expected_revision,
                **changes,
            )

    # Task graph -----------------------------------------------------------

    def add_task(
        self,
        mission_id: str,
        title: str,
        *,
        description: str = "",
        priority: int = 0,
        critical_path: bool = False,
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
            mission = self._require_owned_mission(mission_id)
            self._ensure_mission_accepts_work(mission)
            task = Task(
                task_id=task_id or self._new_id("task"),
                mission_id=mission_id,
                title=title,
                description=description,
                priority=priority,
                critical_path=critical_path,
                created_at=timestamp,
                updated_at=timestamp,
            )
            self.store.create_task(task)
            self._record_event(
                mission_id=mission_id,
                event_type=EventType.TASK_CREATED,
                entity_id=task.task_id,
                payload={
                    "priority": task.priority,
                    "critical_path": task.critical_path,
                    "state": task.state.value,
                },
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
            mission = self._require_owned_mission(mission_id)
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
        expected_revision: int | None = None,
        at: datetime | None = None,
    ) -> Task:
        target_status = _coerce_task_status(target)
        timestamp = normalize_timestamp(at or utc_now())
        with self.store.transaction(immediate=True):
            current = self.store.require_task(task_id)
            mission = self._require_owned_mission(current.mission_id)
            if expected_revision is not None and expected_revision != current.revision:
                raise ConflictError(
                    f"stale task revision for {task_id}: expected "
                    f"{expected_revision}, current {current.revision}"
                )
            self._ensure_mission_accepts_work(mission)
            self._refresh_task_states_in_transaction(current.mission_id, at=timestamp)
            current = self.store.require_task(task_id)
            if expected_revision is not None and expected_revision != current.revision:
                raise ConflictError(
                    f"task {task_id} changed while refreshing dependencies"
                )
            self._validate_task_transition(current.state, target_status)
            if self._task_has_open_escalation(task_id):
                if target_status in {TaskStatus.READY, TaskStatus.IN_PROGRESS}:
                    raise InvalidTransitionError(
                        f"task {task_id} is blocked by an open escalation"
                    )
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
            if target_status is TaskStatus.COMPLETED:
                if current.state is not TaskStatus.VERIFYING:
                    raise InvalidTransitionError(
                        "a task must be verifying before it can be completed"
                    )
                if not self._has_verified_evidence_for_task(current):
                    raise ConflictError(
                        f"task {task_id} cannot complete without verified evidence"
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

    def start_task(
        self,
        task_id: str,
        *,
        expected_revision: int | None = None,
        at: datetime | None = None,
    ) -> Task:
        return self.transition_task(
            task_id, TaskStatus.IN_PROGRESS, expected_revision=expected_revision, at=at
        )

    def mark_task_needs_user(
        self,
        task_id: str,
        *,
        expected_revision: int | None = None,
        at: datetime | None = None,
    ) -> Task:
        return self.transition_task(
            task_id, TaskStatus.NEEDS_USER, expected_revision=expected_revision, at=at
        )

    def begin_task_verification(
        self,
        task_id: str,
        *,
        expected_revision: int | None = None,
        at: datetime | None = None,
    ) -> Task:
        return self.transition_task(
            task_id, TaskStatus.VERIFYING, expected_revision=expected_revision, at=at
        )

    def complete_task(
        self,
        task_id: str,
        *,
        expected_revision: int | None = None,
        at: datetime | None = None,
    ) -> Task:
        return self.transition_task(
            task_id, TaskStatus.COMPLETED, expected_revision=expected_revision, at=at
        )

    def fail_task(
        self,
        task_id: str,
        *,
        expected_revision: int | None = None,
        at: datetime | None = None,
    ) -> Task:
        return self.transition_task(
            task_id, TaskStatus.FAILED, expected_revision=expected_revision, at=at
        )

    def cancel_task(
        self,
        task_id: str,
        *,
        expected_revision: int | None = None,
        at: datetime | None = None,
    ) -> Task:
        return self.transition_task(
            task_id, TaskStatus.CANCELLED, expected_revision=expected_revision, at=at
        )

    def select_next_task(self, mission_id: str) -> Task | None:
        """Select the highest-priority ready task, or none outside ACTIVE."""

        with self.store.transaction(immediate=True):
            mission = self._require_owned_mission(mission_id)
            if mission.state is not MissionState.ACTIVE:
                return None
            self._refresh_task_states_in_transaction(mission_id)
            ready = self.store.list_tasks(mission_id, TaskStatus.READY)
            return self._choose_ready_task(ready, mission_id)

    next_task = select_next_task

    def get_status(self, mission_id: str) -> MissionStatusReport:
        with self.store.transaction(immediate=True):
            mission = self._require_owned_mission(mission_id)
            if mission.state is MissionState.ACTIVE:
                self._refresh_task_states_in_transaction(mission_id)
                mission = self._require_owned_mission(mission_id)
            tasks = tuple(self.store.list_tasks(mission_id))
            open_escalations = tuple(
                self.store.list_escalations(mission_id, EscalationStatus.OPEN)
            )
            ready = [task for task in tasks if task.state is TaskStatus.READY]
            next_task = (
                self._choose_ready_task(ready, mission_id)
                if mission.state is MissionState.ACTIVE
                else None
            )
            return MissionStatusReport(
                mission=mission,
                tasks=tasks,
                open_escalations=open_escalations,
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
            self._require_owned_mission(mission_id)
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
            self._require_owned_mission(mission_id)
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
            self._require_owned_mission(mission_id)
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

        if escalation.status is not EscalationStatus.OPEN:
            raise InvalidTransitionError("an escalation must be recorded as open")
        with self.store.transaction(immediate=True):
            self._require_owned_mission(escalation.mission_id)
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
            mission = self._require_owned_mission(mission_id)
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
            mission = self._require_owned_mission(current.mission_id)
            if current.status is not EscalationStatus.OPEN:
                raise ConflictError(f"escalation already resolved: {escalation_id}")
            updated = replace(current, status=status_value, resolved_at=timestamp)
            self.store.update_escalation(updated, _allow_status_change=True)
            self._record_event(
                mission_id=updated.mission_id,
                event_type=EventType.ESCALATION_RECORDED,
                entity_id=updated.escalation_id,
                payload={"status": updated.status.value},
                created_at=timestamp,
            )
            remaining = self.store.list_escalations(
                updated.mission_id,
                EscalationStatus.OPEN,
            )
            if (
                status_value is EscalationStatus.RESOLVED
                and updated.task_id is not None
                and not any(
                    escalation.task_id == updated.task_id for escalation in remaining
                )
            ):
                task = self.store.get_task(updated.task_id)
                if task is not None and task.state is TaskStatus.NEEDS_USER:
                    prerequisites = self.store.list_prerequisites(task.task_id)
                    desired = (
                        TaskStatus.READY
                        if all(
                            prerequisite.state is TaskStatus.COMPLETED
                            for prerequisite in prerequisites
                        )
                        else TaskStatus.BLOCKED
                    )
                    self._transition_task_in_transaction(
                        task,
                        desired,
                        at=timestamp,
                    )
            if (
                status_value is EscalationStatus.RESOLVED
                and mission.state is MissionState.WAITING_FOR_USER
                and not remaining
            ):
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
            self._require_owned_mission(mission_id)
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
            self._require_owned_mission(mission_id)
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

    def verify_evidence(
        self,
        evidence_id: str,
        verification_method: str,
        *,
        verified_at: datetime | None = None,
    ) -> Evidence:
        timestamp = normalize_timestamp(verified_at or utc_now())
        with self.store.transaction(immediate=True):
            evidence = self.store.get_evidence(evidence_id)
            if evidence is None:
                raise NotFoundError(f"evidence not found: {evidence_id}")
            self._require_owned_mission(evidence.mission_id)
            updated = replace(
                evidence,
                verified_at=timestamp,
                verification_method=verification_method,
            )
            self.store.update_evidence(updated)
            self._record_event(
                mission_id=updated.mission_id,
                event_type=EventType.EVIDENCE_VERIFIED,
                entity_id=updated.evidence_id,
                payload={"method": updated.verification_method},
                created_at=timestamp,
            )
            return updated

    verify_artifact = verify_evidence

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
        approved_by: str | None = None,
        user_id: str | None = None,
        kora_id: str = "kora",
        grant_id: str | None = None,
        approved_at: datetime | None = None,
        expires_at: datetime | None = None,
    ) -> PermissionGrant:
        timestamp = normalize_timestamp(approved_at or utc_now())
        effective_approved_by = (
            self.owner_ref if approved_by in (None, "user") else approved_by
        )
        effective_user_id = self.owner_ref if user_id in (None, "owner") else user_id
        if effective_approved_by != self.owner_ref or effective_user_id != self.owner_ref:
            raise ConflictError("only the mission owner may activate a permission grant")
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
            approved_by=effective_approved_by,
            user_id=effective_user_id,
            kora_id=kora_id,
            approved_at=timestamp,
            expires_at=expires_at,
        )
        with self.store.transaction(immediate=True):
            mission = self._require_owned_mission(mission_id)
            if mission.state in {
                MissionState.PROPOSED,
                MissionState.COMPLETED,
                MissionState.STOPPED,
                MissionState.FAILED,
            }:
                raise InvalidTransitionError(
                    "permission grants require an aligned, non-terminal mission"
                )
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
        mission = self._require_owned_mission(mission_id)
        if mission.state is not MissionState.ACTIVE:
            return False
        return any(
            grant.resource == resource
            and grant.user_id == self.owner_ref
            and grant.is_active(moment)
            for grant in self.store.list_permission_grants(mission_id, action_value)
        )

    def consume_permission(
        self,
        grant_id: str,
        *,
        consumed_at: datetime | None = None,
        idempotency_key: str | None = None,
    ) -> PermissionGrant:
        timestamp = normalize_timestamp(consumed_at or utc_now())
        with self.store.transaction(immediate=True):
            existing = self.store.get_permission_grant(grant_id)
            if existing is None:
                raise NotFoundError(f"permission grant not found: {grant_id}")
            mission = self._require_owned_mission(existing.mission_id)
            if mission.state is not MissionState.ACTIVE:
                raise PermissionUnavailableError(
                    f"mission is not active: {mission.mission_id}"
                )
            grant = self.store.consume_permission(
                grant_id,
                consumed_at=timestamp,
                idempotency_key=idempotency_key,
            )
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

    def use_permission(
        self,
        mission_id: str,
        grant_id: str,
        *,
        action_count: int = 1,
        spent_cents: int = 0,
        idempotency_key: str | None = None,
        used_at: datetime | None = None,
    ) -> PermissionGrant:
        timestamp = normalize_timestamp(used_at or utc_now())
        key = idempotency_key or f"use:{grant_id}:{uuid4().hex}"
        with self.store.transaction(immediate=True):
            mission = self._require_owned_mission(mission_id)
            if mission.state is not MissionState.ACTIVE:
                raise PermissionUnavailableError(
                    f"mission is not active: {mission_id}"
                )
            existing = self.store.get_permission_grant(grant_id)
            if existing is None:
                raise NotFoundError(f"permission grant not found: {grant_id}")
            if existing.mission_id != mission_id:
                raise ConflictError("permission grant belongs to another mission")
            grant = self.store.use_permission(
                grant_id,
                idempotency_key=key,
                action_count=action_count,
                spent_cents=spent_cents,
                used_at=timestamp,
            )
            if grant is None:
                raise PermissionUnavailableError(
                    f"permission grant is not available: {grant_id}"
                )
            event_type = (
                EventType.PERMISSION_CONSUMED
                if grant.mode is PermissionMode.APPROVE_ONCE
                else EventType.PERMISSION_USED
            )
            self._record_event(
                mission_id=mission_id,
                event_type=event_type,
                entity_id=grant.grant_id,
                payload={
                    "mode": grant.mode.value,
                    "action_count": action_count,
                    "spent_cents": spent_cents,
                },
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
            existing = self.store.get_permission_grant(grant_id)
            if existing is None:
                raise NotFoundError(f"permission grant not found: {grant_id}")
            self._require_owned_mission(existing.mission_id)
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

    def _transition_attempt_in_transaction(
        self,
        current: TaskAttempt,
        target: AttemptStatus,
        *,
        at: datetime,
        expected_revision: int | None,
        **changes: object,
    ) -> TaskAttempt:
        self._check_expected_attempt_revision(current, expected_revision)
        self._validate_attempt_transition(current.status, target)
        updated = self.store.update_attempt(
            replace(current, status=target, updated_at=at, **changes),
            expected_revision=current.revision,
            _allow_status_change=True,
        )
        self._record_event(
            mission_id=updated.mission_id,
            event_type=EventType.ATTEMPT_TRANSITIONED,
            entity_id=updated.attempt_id,
            payload={
                "from": current.status.value,
                "to": updated.status.value,
                "revision": updated.revision,
            },
            created_at=at,
        )
        return updated

    @staticmethod
    def _ensure_attempt_scope_matches(
        existing: TaskAttempt, requested: TaskAttempt
    ) -> None:
        for field_name in (
            "mission_id",
            "task_id",
            "idempotency_key",
            "worker_role_id",
            "route_id",
            "quality_floor",
        ):
            if getattr(existing, field_name) != getattr(requested, field_name):
                raise ConflictError(
                    "attempt idempotency key conflicts with immutable attempt scope"
                )

    @staticmethod
    def _check_expected_attempt_revision(
        current: TaskAttempt, expected_revision: int | None
    ) -> None:
        if expected_revision is None:
            return
        if (
            isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision < 0
        ):
            raise ValidationError("expected_revision must be a non-negative integer")
        if expected_revision != current.revision:
            raise ConflictError(
                f"stale attempt revision for {current.attempt_id}: expected "
                f"{expected_revision}, current {current.revision}"
            )

    @staticmethod
    def _validate_lease_owner(lease_owner: str) -> str:
        if not isinstance(lease_owner, str) or not lease_owner.strip():
            raise ValidationError("lease_owner must be a non-empty string")
        return lease_owner

    @staticmethod
    def _validate_fencing_token(fencing_token: int) -> int:
        if (
            isinstance(fencing_token, bool)
            or not isinstance(fencing_token, int)
            or fencing_token < 0
        ):
            raise ValidationError("fencing_token must be a non-negative integer")
        return fencing_token

    @classmethod
    def _resolve_lease_expiry(
        cls,
        at: datetime,
        *,
        lease_expires_at: datetime | None,
        lease_ttl_seconds: float | int | None,
        lease_seconds: float | int | None,
        lease_duration_seconds: float | int | None,
    ) -> datetime:
        ttl_values = tuple(
            value
            for value in (
                lease_ttl_seconds,
                lease_seconds,
                lease_duration_seconds,
            )
            if value is not None
        )
        if lease_expires_at is not None and ttl_values:
            raise ValidationError(
                "lease_expires_at cannot be combined with a lease TTL"
            )
        if ttl_values and any(value != ttl_values[0] for value in ttl_values[1:]):
            raise ValidationError("lease TTL aliases must have the same value")
        if lease_expires_at is not None:
            expiry = normalize_timestamp(lease_expires_at)
        else:
            raw_ttl = (
                ttl_values[0]
                if ttl_values
                else _DEFAULT_ATTEMPT_LEASE_SECONDS
            )
            if isinstance(raw_ttl, bool) or not isinstance(raw_ttl, (int, float)):
                raise ValidationError(
                    "lease TTL must be a finite positive number"
                )
            ttl = float(raw_ttl)
            if not isfinite(ttl) or ttl <= 0.0:
                raise ValidationError("lease TTL must be a finite positive number")
            expiry = at + timedelta(seconds=ttl)
        if expiry <= at:
            raise ValidationError("lease expiry must be after the operation time")
        return expiry

    @classmethod
    def _check_attempt_fence(
        cls,
        current: TaskAttempt,
        lease_owner: str | None,
        fencing_token: int | None,
        *,
        at: datetime,
        require_active_lease: bool,
    ) -> None:
        if lease_owner is None and fencing_token is None:
            return
        if lease_owner is None or fencing_token is None:
            raise ValidationError(
                "lease_owner and fencing_token must be provided together"
            )
        owner = cls._validate_lease_owner(lease_owner)
        token = cls._validate_fencing_token(fencing_token)
        if current.lease_owner != owner or current.fencing_token != token:
            raise ConflictError(
                f"attempt fence does not match current lease: {current.attempt_id}"
            )
        if require_active_lease and not current.has_active_lease(at):
            raise ConflictError(f"attempt lease is no longer active: {current.attempt_id}")

    def _require_owned_attempt(self, attempt_id: str) -> TaskAttempt:
        attempt = self.store.require_attempt(attempt_id)
        self._require_owned_mission(attempt.mission_id)
        return attempt

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
            _allow_state_change=True,
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
            ),
            expected_revision=current.revision,
            _allow_state_change=True,
        )
        self._record_event(
            mission_id=current.mission_id,
            event_type=EventType.TASK_TRANSITIONED,
            entity_id=current.task_id,
            payload={
                "from": current.state.value,
                "to": target.value,
                "revision": updated.revision,
            },
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
            self.store.update_task(
                replace(task, state=desired, updated_at=timestamp),
                expected_revision=task.revision,
                _allow_state_change=True,
            )
            updated = self.store.require_task(task.task_id)
            self._record_event(
                mission_id=mission_id,
                event_type=EventType.TASK_TRANSITIONED,
                entity_id=task.task_id,
                payload={
                    "from": task.state.value,
                    "to": desired.value,
                    "revision": updated.revision,
                },
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
    def _validate_attempt_transition(
        current: AttemptStatus, target: AttemptStatus
    ) -> None:
        if target not in ATTEMPT_TRANSITIONS[current]:
            raise InvalidTransitionError(
                f"invalid attempt transition: {current.value} -> {target.value}"
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

    def _require_owned_mission(self, mission_id: str) -> Mission:
        mission = self.store.require_mission(mission_id)
        if mission.owner_ref != self.owner_ref:
            raise ConflictError(f"mission belongs to another owner: {mission_id}")
        return mission

    def _task_has_open_escalation(self, task_id: str) -> bool:
        task = self.store.require_task(task_id)
        return any(
            escalation.task_id == task_id
            for escalation in self.store.list_escalations(
                task.mission_id, EscalationStatus.OPEN
            )
        )

    def _has_verified_evidence_for_task(self, task: Task) -> bool:
        return any(
            evidence.task_id == task.task_id and evidence.verified_at is not None
            for evidence in self.store.list_evidence(task.mission_id)
        )

    def _ensure_mission_completion_ready(self, mission_id: str) -> None:
        open_escalations = self.store.list_escalations(
            mission_id, EscalationStatus.OPEN
        )
        if open_escalations:
            raise ConflictError("mission cannot complete while an escalation is open")
        tasks = self.store.list_tasks(mission_id)
        incomplete = [task.task_id for task in tasks if task.state is not TaskStatus.COMPLETED]
        if incomplete:
            raise ConflictError(
                "mission cannot complete with incomplete tasks: "
                + ", ".join(incomplete)
            )
        if tasks and not all(self._has_verified_evidence_for_task(task) for task in tasks):
            raise ConflictError("every completed task requires verified evidence")
        if not any(
            evidence.verified_at is not None
            for evidence in self.store.list_evidence(mission_id)
        ):
            raise ConflictError("mission cannot complete without verified evidence")

    def _choose_ready_task(self, ready: Iterable[Task], mission_id: str) -> Task | None:
        candidates = tuple(ready)
        if not candidates:
            return None
        memo: dict[str, int] = {}

        def depth(task_id: str, visiting: frozenset[str] = frozenset()) -> int:
            if task_id in memo:
                return memo[task_id]
            if task_id in visiting:
                return 0
            prerequisites = self.store.list_prerequisites(task_id)
            result = max(
                (1 + depth(task.task_id, visiting | {task_id}) for task in prerequisites),
                default=0,
            )
            memo[task_id] = result
            return result

        return min(
            candidates,
            key=lambda task: (
                -int(task.critical_path),
                -task.priority,
                -depth(task.task_id),
                task.created_at,
                task.task_id,
            ),
        )

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

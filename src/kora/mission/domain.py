"""Typed, user-readable records owned by the Kora mission control plane.

The records in this module intentionally describe missions, work, authority,
and evidence only.  Runtime models, providers, prompts, and worker topology
do not belong in the control-plane data model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping

from kora.mission.errors import ValidationError


def utc_now() -> datetime:
    """Return an aware UTC timestamp suitable for persisted records."""

    return datetime.now(timezone.utc)


def normalize_timestamp(value: datetime) -> datetime:
    """Normalize a timestamp to aware UTC without losing its instant.

    Naive timestamps are treated as UTC.  This makes records created by a
    simple script round-trip safely while ensuring persisted values have one
    deterministic timezone representation.
    """

    if not isinstance(value, datetime):
        raise ValidationError("timestamps must be datetime instances")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _non_empty(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string")
    return value


def _optional_non_empty(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    return _non_empty(value, field_name)


def _tuple_of_strings(
    values: tuple[str, ...] | list[str] | None, field_name: str
) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        raise ValidationError(f"{field_name} must be a sequence of strings")
    result = tuple(values)
    if any(not isinstance(value, str) or not value.strip() for value in result):
        raise ValidationError(f"{field_name} must contain non-empty strings")
    return result


_FORBIDDEN_SEMANTIC_KEYS = frozenset(
    {
        "api_calls",
        "chain_of_thought",
        "estimated_cost_usd",
        "model",
        "model_id",
        "private_reasoning",
        "prompt",
        "provider",
        "provider_id",
        "raw_output",
        "reasoning",
        "runtime_result",
        "session",
        "session_id",
        "token",
        "tokens",
        "total_tokens",
        "trace",
        "trace_id",
        "worker",
        "worker_id",
        "worker_topology",
    }
)


def _validate_semantic_payload(value: Any, path: str = "payload") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise ValidationError(f"{path} keys must be strings")
            normalized = key.strip().lower().replace("-", "_")
            if normalized in _FORBIDDEN_SEMANTIC_KEYS:
                raise ValidationError(
                    f"{path} cannot contain runtime-internal field: {key}"
                )
            _validate_semantic_payload(nested, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _validate_semantic_payload(nested, f"{path}[{index}]")


def _coerce_enum(value: Any, enum_type: type[StrEnum], field_name: str) -> StrEnum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(member.value for member in enum_type)
        raise ValidationError(f"{field_name} must be one of: {allowed}") from exc


class MissionState(StrEnum):
    """Durable state of one approved overarching mission."""

    PROPOSED = "proposed"
    ALIGNED = "aligned"
    ACTIVE = "active"
    WAITING_FOR_USER = "waiting_for_user"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"

    WAITING = WAITING_FOR_USER
    COMPLETE = COMPLETED


# Both names are useful at API boundaries; there is one canonical enum.
MissionStatus = MissionState
MissionLifecycleState = MissionState


class TaskStatus(StrEnum):
    """A task's lifecycle state, including dependency-derived states."""

    READY = "ready"
    BLOCKED = "blocked"
    IN_PROGRESS = "in_progress"
    NEEDS_USER = "needs_user"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TaskState = TaskStatus
TaskLifecycleState = TaskStatus


class AssumptionStatus(StrEnum):
    """Resolution state for an explicit mission assumption."""

    OPEN = "open"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    INVALIDATED = "invalidated"


class CheckpointType(StrEnum):
    """Semantic checkpoints that are meaningful to a user."""

    CONTEXT_ALIGNED = "context_aligned"
    PLAN_CHOSEN = "plan_chosen"
    FIRST_USABLE_SLICE = "first_usable_slice"
    PRD_COVERAGE_REACHED = "prd_coverage_reached"
    DEPLOYMENT_READY = "deployment_ready"
    OUTREACH_READY = "outreach_ready"
    REQUIREMENT_INFEASIBLE = "requirement_infeasible"
    MISSION_COMPLETE = "mission_complete"
    OTHER = "other"


class EscalationStatus(StrEnum):
    """Lifecycle of a human decision or blocker request."""

    OPEN = "open"
    RESOLVED = "resolved"
    DECLINED = "declined"
    EXPIRED = "expired"


class PermissionMode(StrEnum):
    """Whether a grant applies once or remains bounded and revocable."""

    APPROVE_ONCE = "approve_once"
    BOUNDED_INDEFINITE = "bounded_indefinite"

    # Friendly aliases for callers that use shorter vocabulary.
    ONCE = APPROVE_ONCE
    INDEFINITE = BOUNDED_INDEFINITE
    APPROVE_INDEFINITELY = BOUNDED_INDEFINITE
    BOUNDED_ALWAYS = BOUNDED_INDEFINITE


PermissionGrantType = PermissionMode


class PermissionAction(StrEnum):
    """Semantic action classes that may be granted by the user."""

    READ_CONTEXT = "read_context"
    WRITE_WORKSPACE = "write_workspace"
    EXECUTE_WORKSPACE = "execute_workspace"
    DEPLOY = "deploy"
    SEND_MESSAGE = "send_message"
    PUBLISH = "publish"
    OUTREACH = "outreach"
    SPEND = "spend"
    ACCOUNT_CHANGE = "account_change"
    DELETE = "delete"

    EXTERNAL_MESSAGE = SEND_MESSAGE
    PRODUCTION_DEPLOY = DEPLOY
    EXTERNAL_OUTREACH = OUTREACH


class ArtifactKind(StrEnum):
    """Kinds of durable artifacts that can support evidence."""

    SOURCE = "source"
    DIFF = "diff"
    TEST_REPORT = "test_report"
    PREVIEW = "preview"
    DEPLOYMENT = "deployment"
    LOG = "log"
    DOCUMENT = "document"
    OTHER = "other"


class EvidenceKind(StrEnum):
    """Kinds of evidence attached to mission work."""

    TEST = "test"
    WALKTHROUGH = "walkthrough"
    REVIEW = "review"
    ARTIFACT = "artifact"
    APPROVAL = "approval"
    REQUIREMENT_COVERAGE = "requirement_coverage"
    OTHER = "other"


class EventType(StrEnum):
    """Audit event kinds emitted by the control plane."""

    MISSION_CREATED = "mission_created"
    MISSION_TRANSITIONED = "mission_transitioned"
    TASK_CREATED = "task_created"
    TASK_TRANSITIONED = "task_transitioned"
    TASK_DEPENDENCY_ADDED = "task_dependency_added"
    DECISION_RECORDED = "decision_recorded"
    ASSUMPTION_RECORDED = "assumption_recorded"
    CHECKPOINT_RECORDED = "checkpoint_recorded"
    ESCALATION_RECORDED = "escalation_recorded"
    PERMISSION_GRANTED = "permission_granted"
    PERMISSION_CONSUMED = "permission_consumed"
    PERMISSION_USED = "permission_used"
    PERMISSION_REVOKED = "permission_revoked"
    ARTIFACT_RECORDED = "artifact_recorded"
    EVIDENCE_RECORDED = "evidence_recorded"
    EVIDENCE_VERIFIED = "evidence_verified"


@dataclass(frozen=True, slots=True)
class Mission:
    """One user-approved overarching objective."""

    mission_id: str
    title: str
    objective: str
    definition_of_done: str
    state: MissionState = MissionState.PROPOSED
    exclusions: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    failure_reason: str | None = None
    stop_reason: str | None = None
    revision: int = 0
    owner_ref: str = "owner"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "mission_id", _non_empty(self.mission_id, "mission_id")
        )
        object.__setattr__(self, "title", _non_empty(self.title, "title"))
        object.__setattr__(self, "objective", _non_empty(self.objective, "objective"))
        object.__setattr__(
            self,
            "definition_of_done",
            _non_empty(self.definition_of_done, "definition_of_done"),
        )
        object.__setattr__(
            self, "state", _coerce_enum(self.state, MissionState, "state")
        )
        object.__setattr__(
            self, "exclusions", _tuple_of_strings(self.exclusions, "exclusions")
        )
        object.__setattr__(self, "owner_ref", _non_empty(self.owner_ref, "owner_ref"))
        object.__setattr__(self, "created_at", normalize_timestamp(self.created_at))
        object.__setattr__(self, "updated_at", normalize_timestamp(self.updated_at))
        object.__setattr__(
            self,
            "failure_reason",
            _optional_non_empty(self.failure_reason, "failure_reason"),
        )
        object.__setattr__(
            self, "stop_reason", _optional_non_empty(self.stop_reason, "stop_reason")
        )
        if (
            isinstance(self.revision, bool)
            or not isinstance(self.revision, int)
            or self.revision < 0
        ):
            raise ValidationError("revision must be a non-negative integer")

    @property
    def status(self) -> MissionState:
        """Alias for callers that name the lifecycle field ``status``."""

        return self.state


@dataclass(frozen=True, slots=True)
class Task:
    """One unit of work inside a mission-owned dependency graph."""

    task_id: str
    mission_id: str
    title: str
    description: str = ""
    priority: int = 0
    state: TaskStatus = TaskStatus.READY
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    revision: int = 0
    critical_path: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_id", _non_empty(self.task_id, "task_id"))
        object.__setattr__(
            self, "mission_id", _non_empty(self.mission_id, "mission_id")
        )
        object.__setattr__(self, "title", _non_empty(self.title, "title"))
        if not isinstance(self.description, str):
            raise ValidationError("description must be a string")
        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise ValidationError("priority must be an integer")
        if not isinstance(self.critical_path, bool):
            raise ValidationError("critical_path must be a boolean")
        object.__setattr__(self, "state", _coerce_enum(self.state, TaskStatus, "state"))
        object.__setattr__(self, "created_at", normalize_timestamp(self.created_at))
        object.__setattr__(self, "updated_at", normalize_timestamp(self.updated_at))
        if self.started_at is not None:
            object.__setattr__(self, "started_at", normalize_timestamp(self.started_at))
        if self.finished_at is not None:
            object.__setattr__(
                self, "finished_at", normalize_timestamp(self.finished_at)
            )
        if (
            isinstance(self.revision, bool)
            or not isinstance(self.revision, int)
            or self.revision < 0
        ):
            raise ValidationError("revision must be a non-negative integer")

    @property
    def status(self) -> TaskStatus:
        """Alias for callers that name the lifecycle field ``status``."""

        return self.state


@dataclass(frozen=True, slots=True)
class TaskDependency:
    """An edge from a task to a prerequisite task in the same mission."""

    mission_id: str
    task_id: str
    depends_on_task_id: str
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "mission_id", _non_empty(self.mission_id, "mission_id")
        )
        object.__setattr__(self, "task_id", _non_empty(self.task_id, "task_id"))
        object.__setattr__(
            self,
            "depends_on_task_id",
            _non_empty(self.depends_on_task_id, "depends_on_task_id"),
        )
        if self.task_id == self.depends_on_task_id:
            raise ValidationError("a task cannot depend on itself")
        object.__setattr__(self, "created_at", normalize_timestamp(self.created_at))


@dataclass(frozen=True, slots=True)
class Decision:
    """A user-readable decision made for the mission."""

    decision_id: str
    mission_id: str
    summary: str
    decision: str
    rationale: str = ""
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "decision_id", _non_empty(self.decision_id, "decision_id")
        )
        object.__setattr__(
            self, "mission_id", _non_empty(self.mission_id, "mission_id")
        )
        object.__setattr__(self, "summary", _non_empty(self.summary, "summary"))
        object.__setattr__(self, "decision", _non_empty(self.decision, "decision"))
        if not isinstance(self.rationale, str):
            raise ValidationError("rationale must be a string")
        object.__setattr__(self, "created_at", normalize_timestamp(self.created_at))

    @property
    def question(self) -> str:
        """Compatibility-friendly name for the decision's subject."""

        return self.summary


@dataclass(frozen=True, slots=True)
class Assumption:
    """An explicit assumption that can be confirmed or invalidated."""

    assumption_id: str
    mission_id: str
    statement: str
    rationale: str = ""
    status: AssumptionStatus = AssumptionStatus.OPEN
    created_at: datetime = field(default_factory=utc_now)
    resolved_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "assumption_id", _non_empty(self.assumption_id, "assumption_id")
        )
        object.__setattr__(
            self, "mission_id", _non_empty(self.mission_id, "mission_id")
        )
        object.__setattr__(self, "statement", _non_empty(self.statement, "statement"))
        if not isinstance(self.rationale, str):
            raise ValidationError("rationale must be a string")
        object.__setattr__(
            self, "status", _coerce_enum(self.status, AssumptionStatus, "status")
        )
        object.__setattr__(self, "created_at", normalize_timestamp(self.created_at))
        if self.resolved_at is not None:
            object.__setattr__(
                self, "resolved_at", normalize_timestamp(self.resolved_at)
            )


@dataclass(frozen=True, slots=True)
class Checkpoint:
    """A semantic progress checkpoint, not a raw runtime log."""

    checkpoint_id: str
    mission_id: str
    kind: CheckpointType
    summary: str
    task_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "checkpoint_id", _non_empty(self.checkpoint_id, "checkpoint_id")
        )
        object.__setattr__(
            self, "mission_id", _non_empty(self.mission_id, "mission_id")
        )
        object.__setattr__(
            self, "kind", _coerce_enum(self.kind, CheckpointType, "kind")
        )
        object.__setattr__(self, "summary", _non_empty(self.summary, "summary"))
        object.__setattr__(
            self, "task_id", _optional_non_empty(self.task_id, "task_id")
        )
        object.__setattr__(self, "created_at", normalize_timestamp(self.created_at))

    @property
    def checkpoint_type(self) -> CheckpointType:
        return self.kind


@dataclass(frozen=True, slots=True)
class Escalation:
    """A human decision or action request that can block mission progress."""

    escalation_id: str
    mission_id: str
    title: str
    reason: str
    impact: str
    options: tuple[str, ...] = ()
    recommendation: str = ""
    consequence_of_waiting: str = ""
    requested_action: str = ""
    task_id: str | None = None
    status: EscalationStatus = EscalationStatus.OPEN
    created_at: datetime = field(default_factory=utc_now)
    resolved_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "escalation_id", _non_empty(self.escalation_id, "escalation_id")
        )
        object.__setattr__(
            self, "mission_id", _non_empty(self.mission_id, "mission_id")
        )
        object.__setattr__(self, "title", _non_empty(self.title, "title"))
        object.__setattr__(self, "reason", _non_empty(self.reason, "reason"))
        object.__setattr__(self, "impact", _non_empty(self.impact, "impact"))
        object.__setattr__(self, "options", _tuple_of_strings(self.options, "options"))
        for field_name in (
            "recommendation",
            "consequence_of_waiting",
            "requested_action",
        ):
            if not isinstance(getattr(self, field_name), str):
                raise ValidationError(f"{field_name} must be a string")
        object.__setattr__(
            self, "task_id", _optional_non_empty(self.task_id, "task_id")
        )
        object.__setattr__(
            self, "status", _coerce_enum(self.status, EscalationStatus, "status")
        )
        object.__setattr__(self, "created_at", normalize_timestamp(self.created_at))
        if self.resolved_at is not None:
            object.__setattr__(
                self, "resolved_at", normalize_timestamp(self.resolved_at)
            )


@dataclass(frozen=True, slots=True)
class Artifact:
    """A durable, user-readable output or source locator."""

    artifact_id: str
    mission_id: str
    name: str
    locator: str
    kind: ArtifactKind = ArtifactKind.OTHER
    task_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "artifact_id", _non_empty(self.artifact_id, "artifact_id")
        )
        object.__setattr__(
            self, "mission_id", _non_empty(self.mission_id, "mission_id")
        )
        object.__setattr__(self, "name", _non_empty(self.name, "name"))
        object.__setattr__(self, "locator", _non_empty(self.locator, "locator"))
        object.__setattr__(self, "kind", _coerce_enum(self.kind, ArtifactKind, "kind"))
        object.__setattr__(
            self, "task_id", _optional_non_empty(self.task_id, "task_id")
        )
        object.__setattr__(self, "created_at", normalize_timestamp(self.created_at))

    @property
    def artifact_type(self) -> ArtifactKind:
        return self.kind


@dataclass(frozen=True, slots=True)
class Evidence:
    """A claim of progress tied to an artifact, task, or external locator."""

    evidence_id: str
    mission_id: str
    summary: str
    kind: EvidenceKind = EvidenceKind.OTHER
    artifact_id: str | None = None
    task_id: str | None = None
    locator: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    verified_at: datetime | None = None
    verification_method: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "evidence_id", _non_empty(self.evidence_id, "evidence_id")
        )
        object.__setattr__(
            self, "mission_id", _non_empty(self.mission_id, "mission_id")
        )
        object.__setattr__(self, "summary", _non_empty(self.summary, "summary"))
        object.__setattr__(self, "kind", _coerce_enum(self.kind, EvidenceKind, "kind"))
        object.__setattr__(
            self, "artifact_id", _optional_non_empty(self.artifact_id, "artifact_id")
        )
        object.__setattr__(
            self, "task_id", _optional_non_empty(self.task_id, "task_id")
        )
        object.__setattr__(
            self, "locator", _optional_non_empty(self.locator, "locator")
        )
        object.__setattr__(self, "created_at", normalize_timestamp(self.created_at))
        object.__setattr__(
            self,
            "verification_method",
            _optional_non_empty(self.verification_method, "verification_method"),
        )
        if self.verified_at is not None:
            object.__setattr__(self, "verified_at", normalize_timestamp(self.verified_at))
        if (self.verified_at is None) != (self.verification_method is None):
            raise ValidationError(
                "verified_at and verification_method must be provided together"
            )

    @property
    def evidence_type(self) -> EvidenceKind:
        return self.kind


@dataclass(frozen=True, slots=True)
class PermissionGrant:
    """A semantic user grant; this record never executes an external action."""

    grant_id: str
    mission_id: str
    action: PermissionAction
    resource: str
    purpose: str
    mode: PermissionMode = PermissionMode.APPROVE_ONCE
    scope: str = ""
    max_actions: int | None = None
    budget_limit_cents: int | None = None
    approved_by: str = "user"
    user_id: str = "owner"
    kora_id: str = "kora"
    approved_at: datetime = field(default_factory=utc_now)
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    consumed_at: datetime | None = None
    actions_used: int = 0
    spent_cents: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "grant_id", _non_empty(self.grant_id, "grant_id"))
        object.__setattr__(
            self, "mission_id", _non_empty(self.mission_id, "mission_id")
        )
        object.__setattr__(
            self, "action", _coerce_enum(self.action, PermissionAction, "action")
        )
        object.__setattr__(self, "resource", _non_empty(self.resource, "resource"))
        object.__setattr__(self, "purpose", _non_empty(self.purpose, "purpose"))
        object.__setattr__(
            self, "mode", _coerce_enum(self.mode, PermissionMode, "mode")
        )
        if not isinstance(self.scope, str):
            raise ValidationError("scope must be a string")
        if self.max_actions is not None:
            if (
                isinstance(self.max_actions, bool)
                or not isinstance(self.max_actions, int)
                or self.max_actions <= 0
            ):
                raise ValidationError("max_actions must be a positive integer")
        if self.budget_limit_cents is not None:
            if (
                isinstance(self.budget_limit_cents, bool)
                or not isinstance(self.budget_limit_cents, int)
                or self.budget_limit_cents < 0
            ):
                raise ValidationError(
                    "budget_limit_cents must be a non-negative integer"
                )
        object.__setattr__(
            self, "approved_by", _non_empty(self.approved_by, "approved_by")
        )
        object.__setattr__(self, "user_id", _non_empty(self.user_id, "user_id"))
        object.__setattr__(self, "kora_id", _non_empty(self.kora_id, "kora_id"))
        object.__setattr__(self, "approved_at", normalize_timestamp(self.approved_at))
        for field_name in ("expires_at", "revoked_at", "consumed_at"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, normalize_timestamp(value))
        if self.expires_at is not None and self.expires_at <= self.approved_at:
            raise ValidationError("expires_at must be after approved_at")
        if "*" in self.scope:
            raise ValidationError("permission scope cannot use wildcards")
        if self.mode is PermissionMode.BOUNDED_INDEFINITE:
            if not self.scope.strip():
                raise ValidationError("bounded grants require a non-empty scope")
            if (
                self.max_actions is None
                and self.budget_limit_cents is None
                and self.expires_at is None
            ):
                raise ValidationError(
                    "bounded grants require an action limit, budget, or expiry"
                )
        for field_name in ("actions_used", "spent_cents"):
            value = getattr(self, field_name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
            ):
                raise ValidationError(f"{field_name} must be a non-negative integer")
        if self.mode is PermissionMode.APPROVE_ONCE and self.actions_used > 1:
            raise ValidationError("approve-once grants cannot use more than once")
        if self.mode is PermissionMode.APPROVE_ONCE and self.max_actions not in {
            None,
            1,
        }:
            raise ValidationError("approve-once grants can have at most one action")
        if self.max_actions is not None and self.actions_used > self.max_actions:
            raise ValidationError("actions_used cannot exceed max_actions")
        if (
            self.budget_limit_cents is not None
            and self.spent_cents > self.budget_limit_cents
        ):
            raise ValidationError("spent_cents cannot exceed budget_limit_cents")
        if (
            self.mode is PermissionMode.BOUNDED_INDEFINITE
            and self.consumed_at is not None
        ):
            raise ValidationError(
                "bounded indefinite grants cannot be consumed as one-time grants"
            )

    @property
    def action_limit(self) -> int | None:
        """Alias used by callers that describe a grant in action limits."""

        return self.max_actions

    @property
    def approval_mode(self) -> PermissionMode:
        return self.mode

    @property
    def owner_id(self) -> str:
        return self.user_id

    @property
    def is_consumed(self) -> bool:
        return self.consumed_at is not None

    def is_active(self, at: datetime | None = None) -> bool:
        """Return whether this semantic grant can currently authorize a check."""

        now = normalize_timestamp(at or utc_now())
        if (
            self.approved_at > now
            or self.revoked_at is not None
            or self.consumed_at is not None
        ):
            return False
        if self.max_actions is not None and self.actions_used >= self.max_actions:
            return False
        if (
            self.budget_limit_cents is not None
            and self.spent_cents >= self.budget_limit_cents
        ):
            return False
        return self.expires_at is None or self.expires_at > now


@dataclass(frozen=True, slots=True)
class DomainEvent:
    """An append-only audit event for a control-plane mutation."""

    event_id: str
    mission_id: str
    event_type: EventType
    entity_id: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", _non_empty(self.event_id, "event_id"))
        object.__setattr__(
            self, "mission_id", _non_empty(self.mission_id, "mission_id")
        )
        object.__setattr__(
            self, "event_type", _coerce_enum(self.event_type, EventType, "event_type")
        )
        object.__setattr__(self, "entity_id", _non_empty(self.entity_id, "entity_id"))
        if not isinstance(self.payload, Mapping):
            raise ValidationError("payload must be a mapping")
        _validate_semantic_payload(self.payload)
        object.__setattr__(self, "payload", dict(self.payload))
        object.__setattr__(self, "created_at", normalize_timestamp(self.created_at))


# The explicit name makes evidence/artifact pairings easy to discover without
# forcing callers to know which record stores the durable locator.
EvidenceArtifact = Evidence

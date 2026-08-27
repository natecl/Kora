"""Kora's persistent, headless mission control plane.

The package is the authoritative owner of mission state, task dependencies,
semantic escalations, permissions, and evidence.  It intentionally has no
dependency on the Hermes execution runtime.
"""

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
    EvidenceArtifact,
    EvidenceKind,
    EventType,
    Mission,
    MissionState,
    MissionStatus,
    PermissionAction,
    PermissionGrant,
    PermissionMode,
    Task,
    TaskDependency,
    TaskState,
    TaskStatus,
    normalize_timestamp,
    utc_now,
)
from kora.mission.errors import (
    ConflictError,
    DependencyError,
    InvalidTransitionError,
    MissionControlError,
    NotFoundError,
    PermissionUnavailableError,
    ValidationError,
)
from kora.mission.service import (
    MISSION_TRANSITIONS,
    TASK_TRANSITIONS,
    MissionControlPlane,
    MissionControlService,
    MissionService,
    MissionStatusReport,
)
from kora.mission.store import SCHEMA_VERSION, SQLiteMissionStore

MissionLifecycleState = MissionState
TaskLifecycleState = TaskStatus
PermissionGrantType = PermissionMode
MissionRepository = SQLiteMissionStore
MissionStore = SQLiteMissionStore

__all__ = [
    "Artifact",
    "ArtifactKind",
    "Assumption",
    "AssumptionStatus",
    "Checkpoint",
    "CheckpointType",
    "ConflictError",
    "Decision",
    "DependencyError",
    "DomainEvent",
    "Escalation",
    "EscalationStatus",
    "Evidence",
    "EvidenceArtifact",
    "EvidenceKind",
    "EventType",
    "InvalidTransitionError",
    "MISSION_TRANSITIONS",
    "Mission",
    "MissionControlError",
    "MissionControlPlane",
    "MissionControlService",
    "MissionLifecycleState",
    "MissionRepository",
    "MissionService",
    "MissionStore",
    "MissionState",
    "MissionStatus",
    "MissionStatusReport",
    "NotFoundError",
    "PermissionAction",
    "PermissionGrant",
    "PermissionGrantType",
    "PermissionMode",
    "PermissionUnavailableError",
    "SCHEMA_VERSION",
    "SQLiteMissionStore",
    "TASK_TRANSITIONS",
    "Task",
    "TaskDependency",
    "TaskLifecycleState",
    "TaskState",
    "TaskStatus",
    "ValidationError",
    "normalize_timestamp",
    "utc_now",
]

"""SQLite persistence for Kora's mission control plane.

This module is deliberately self-contained and uses only the Python standard
library.  The repository owns the SQLite connection, turns on foreign-key
enforcement, and exposes transaction boundaries so a service operation can
write state and its audit event atomically.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Mapping
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
    ValidationError,
)


SCHEMA_VERSION = 4


def _timestamp(value: datetime) -> str:
    return normalize_timestamp(value).isoformat(timespec="microseconds")


def _parse_timestamp(value: str) -> datetime:
    try:
        return normalize_timestamp(datetime.fromisoformat(value))
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"invalid persisted timestamp: {value!r}") from exc


def _json_default(value: Any) -> Any:
    if hasattr(value, "value") and isinstance(value.value, str):
        return value.value
    if isinstance(value, datetime):
        return _timestamp(value)
    raise TypeError(f"value of type {type(value).__name__} is not JSON serializable")


def _json_dumps(value: Any) -> str:
    return json.dumps(
        value,
        default=_json_default,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _json_loads(value: str) -> Any:
    try:
        return json.loads(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("invalid JSON in persisted mission record") from exc


def _text_tuple(value: str, field_name: str) -> tuple[str, ...]:
    decoded = _json_loads(value)
    if not isinstance(decoded, list) or any(
        not isinstance(item, str) for item in decoded
    ):
        raise ValidationError(f"persisted {field_name} must be a JSON string list")
    return tuple(decoded)


class SQLiteMissionStore:
    """A durable repository for missions and all mission-scoped records."""

    def __init__(
        self,
        database: str | Path | sqlite3.Connection = ":memory:",
    ) -> None:
        self._lock = threading.RLock()
        self._closed = False
        self._owns_connection = not isinstance(database, sqlite3.Connection)
        if isinstance(database, sqlite3.Connection):
            self._connection = database
            self.database = None
        else:
            if isinstance(database, Path):
                database_value = str(database)
            else:
                database_value = database
            if database_value != ":memory:":
                path = Path(database_value).expanduser()
                path.parent.mkdir(parents=True, exist_ok=True)
                database_value = str(path)
            self.database = database_value
            self._connection = sqlite3.connect(
                database_value,
                timeout=30,
                isolation_level=None,
                check_same_thread=False,
            )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA busy_timeout = 30000")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA synchronous = FULL")
        self._initialize_schema()

    @property
    def connection(self) -> sqlite3.Connection:
        """Expose the connection for diagnostics without exposing it in Kora APIs."""

        return self._connection

    def _read_schema_version(self) -> int | None:
        try:
            row = self._connection.execute(
                "SELECT value FROM schema_meta WHERE key = 'version'"
            ).fetchone()
        except sqlite3.OperationalError:
            return None
        if row is None:
            return None
        try:
            version = int(row[0])
        except (TypeError, ValueError) as exc:
            raise ValidationError("persisted schema version is invalid") from exc
        if version < 0:
            raise ValidationError("persisted schema version cannot be negative")
        return version

    def _initialize_schema(self) -> None:
        with self._lock:
            current_version = self._read_schema_version()
            if current_version is not None and current_version > SCHEMA_VERSION:
                raise ValidationError(
                    "database schema is newer than this Kora mission store: "
                    f"{current_version} > {SCHEMA_VERSION}"
                )
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS missions (
                    mission_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    definition_of_done TEXT NOT NULL,
                    state TEXT NOT NULL CHECK (state IN (
                        'proposed', 'aligned', 'active', 'waiting_for_user',
                        'verifying', 'completed', 'stopped', 'failed'
                    )),
                    exclusions_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    failure_reason TEXT,
                    stop_reason TEXT,
                    revision INTEGER NOT NULL DEFAULT 0,
                    owner_ref TEXT NOT NULL DEFAULT 'owner'
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    mission_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    critical_path INTEGER NOT NULL DEFAULT 0 CHECK (critical_path IN (0, 1)),
                    state TEXT NOT NULL CHECK (state IN (
                        'ready', 'blocked', 'in_progress', 'needs_user',
                        'verifying', 'completed', 'failed', 'cancelled'
                    )),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    revision INTEGER NOT NULL DEFAULT 0,
                    UNIQUE (mission_id, task_id),
                    FOREIGN KEY (mission_id) REFERENCES missions(mission_id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS task_attempts (
                    attempt_id TEXT PRIMARY KEY,
                    mission_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    worker_role_id TEXT NOT NULL,
                    route_id TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN (
                        'created', 'running', 'verifying', 'succeeded',
                        'failed', 'interrupted', 'unknown'
                    )),
                    quality_floor REAL NOT NULL CHECK (
                        quality_floor >= 0.0 AND quality_floor <= 1.0
                    ),
                    lease_owner TEXT,
                    fencing_token INTEGER NOT NULL DEFAULT 0 CHECK (
                        fencing_token >= 0
                    ),
                    lease_expires_at TEXT,
                    result_summary TEXT NOT NULL DEFAULT '',
                    error_summary TEXT NOT NULL DEFAULT '',
                    total_tokens INTEGER CHECK (
                        total_tokens IS NULL OR total_tokens >= 0
                    ),
                    estimated_cost_usd REAL CHECK (
                        estimated_cost_usd IS NULL OR estimated_cost_usd >= 0.0
                    ),
                    latency_ms INTEGER CHECK (
                        latency_ms IS NULL OR latency_ms >= 0
                    ),
                    accepted INTEGER CHECK (
                        accepted IS NULL OR accepted IN (0, 1)
                    ),
                    revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    UNIQUE (mission_id, task_id, idempotency_key),
                    CHECK (
                        (lease_owner IS NULL AND lease_expires_at IS NULL)
                        OR (lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)
                    ),
                    FOREIGN KEY (mission_id) REFERENCES missions(mission_id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (mission_id, task_id)
                        REFERENCES tasks(mission_id, task_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS task_dependencies (
                    mission_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    depends_on_task_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (mission_id, task_id, depends_on_task_id),
                    CHECK (task_id <> depends_on_task_id),
                    FOREIGN KEY (mission_id) REFERENCES missions(mission_id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (mission_id, task_id)
                        REFERENCES tasks(mission_id, task_id) ON DELETE CASCADE,
                    FOREIGN KEY (mission_id, depends_on_task_id)
                        REFERENCES tasks(mission_id, task_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS decisions (
                    decision_id TEXT PRIMARY KEY,
                    mission_id TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (mission_id) REFERENCES missions(mission_id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS assumptions (
                    assumption_id TEXT PRIMARY KEY,
                    mission_id TEXT NOT NULL,
                    statement TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN (
                        'open', 'confirmed', 'rejected', 'invalidated'
                    )),
                    created_at TEXT NOT NULL,
                    resolved_at TEXT,
                    FOREIGN KEY (mission_id) REFERENCES missions(mission_id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS checkpoints (
                    checkpoint_id TEXT PRIMARY KEY,
                    mission_id TEXT NOT NULL,
                    task_id TEXT,
                    kind TEXT NOT NULL CHECK (kind IN (
                        'context_aligned', 'plan_chosen', 'first_usable_slice',
                        'prd_coverage_reached', 'deployment_ready',
                        'outreach_ready', 'requirement_infeasible',
                        'mission_complete', 'other'
                    )),
                    summary TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (mission_id) REFERENCES missions(mission_id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (mission_id, task_id)
                        REFERENCES tasks(mission_id, task_id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS escalations (
                    escalation_id TEXT PRIMARY KEY,
                    mission_id TEXT NOT NULL,
                    task_id TEXT,
                    title TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    impact TEXT NOT NULL,
                    options_json TEXT NOT NULL,
                    recommendation TEXT NOT NULL,
                    consequence_of_waiting TEXT NOT NULL,
                    requested_action TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN (
                        'open', 'resolved', 'declined', 'expired'
                    )),
                    created_at TEXT NOT NULL,
                    resolved_at TEXT,
                    FOREIGN KEY (mission_id) REFERENCES missions(mission_id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (mission_id, task_id)
                        REFERENCES tasks(mission_id, task_id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    mission_id TEXT NOT NULL,
                    task_id TEXT,
                    name TEXT NOT NULL,
                    locator TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK (kind IN (
                        'source', 'diff', 'test_report', 'preview', 'deployment',
                        'log', 'document', 'other'
                    )),
                    created_at TEXT NOT NULL,
                    UNIQUE (mission_id, artifact_id),
                    FOREIGN KEY (mission_id) REFERENCES missions(mission_id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (mission_id, task_id)
                        REFERENCES tasks(mission_id, task_id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS evidence (
                    evidence_id TEXT PRIMARY KEY,
                    mission_id TEXT NOT NULL,
                    task_id TEXT,
                    artifact_id TEXT,
                    summary TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK (kind IN (
                        'test', 'walkthrough', 'review', 'artifact', 'approval',
                        'requirement_coverage', 'other'
                    )),
                    locator TEXT,
                    created_at TEXT NOT NULL,
                    verified_at TEXT,
                    verification_method TEXT,
                    FOREIGN KEY (mission_id) REFERENCES missions(mission_id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (mission_id, task_id)
                        REFERENCES tasks(mission_id, task_id) ON DELETE SET NULL,
                    FOREIGN KEY (mission_id, artifact_id)
                        REFERENCES artifacts(mission_id, artifact_id)
                        ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS permission_grants (
                    grant_id TEXT PRIMARY KEY,
                    mission_id TEXT NOT NULL,
                    action TEXT NOT NULL CHECK (action IN (
                        'read_context', 'write_workspace', 'execute_workspace',
                        'deploy', 'send_message', 'publish', 'outreach', 'spend',
                        'account_change', 'delete'
                    )),
                    resource TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    mode TEXT NOT NULL CHECK (mode IN (
                        'approve_once', 'bounded_indefinite'
                    )),
                    scope TEXT NOT NULL,
                    max_actions INTEGER,
                    budget_limit_cents INTEGER,
                    approved_by TEXT NOT NULL,
                    user_id TEXT NOT NULL DEFAULT 'owner',
                    kora_id TEXT NOT NULL DEFAULT 'kora',
                    approved_at TEXT NOT NULL,
                    expires_at TEXT,
                    revoked_at TEXT,
                    consumed_at TEXT,
                    actions_used INTEGER NOT NULL DEFAULT 0,
                    spent_cents INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY (mission_id) REFERENCES missions(mission_id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS permission_uses (
                    use_id TEXT PRIMARY KEY,
                    grant_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    action_count INTEGER NOT NULL CHECK (action_count > 0),
                    spent_cents INTEGER NOT NULL CHECK (spent_cents >= 0),
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (grant_id) REFERENCES permission_grants(grant_id)
                        ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS mission_events (
                    event_id TEXT PRIMARY KEY,
                    mission_id TEXT NOT NULL,
                    event_type TEXT NOT NULL CHECK (event_type IN (
                        'mission_created', 'mission_transitioned', 'task_created',
                        'task_transitioned', 'task_dependency_added',
                        'decision_recorded', 'assumption_recorded',
                        'checkpoint_recorded', 'escalation_recorded',
                        'permission_granted', 'permission_consumed',
                        'permission_used', 'permission_revoked',
                        'artifact_recorded', 'evidence_recorded',
                        'evidence_verified', 'attempt_created',
                        'attempt_transitioned', 'attempt_lease_renewed'
                    )),
                    entity_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (mission_id) REFERENCES missions(mission_id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_missions_order
                    ON missions (created_at, mission_id);
                CREATE INDEX IF NOT EXISTS idx_dependencies_task
                    ON task_dependencies (mission_id, task_id, depends_on_task_id);
                CREATE INDEX IF NOT EXISTS idx_events_order
                    ON mission_events (mission_id, created_at, event_id);
                CREATE INDEX IF NOT EXISTS idx_permissions_lookup
                    ON permission_grants (mission_id, action, resource, mode);
                CREATE INDEX IF NOT EXISTS idx_permission_uses_grant
                    ON permission_uses (grant_id, created_at, use_id);
                """
            )
            mission_columns = {
                row[1]
                for row in self._connection.execute("PRAGMA table_info(missions)")
            }
            if "revision" not in mission_columns:
                self._connection.execute(
                    "ALTER TABLE missions ADD COLUMN revision INTEGER NOT NULL DEFAULT 0"
                )
            if "owner_ref" not in mission_columns:
                self._connection.execute(
                    "ALTER TABLE missions ADD COLUMN owner_ref TEXT NOT NULL DEFAULT 'owner'"
                )

            task_columns = {
                row[1]
                for row in self._connection.execute("PRAGMA table_info(tasks)")
            }
            if "critical_path" not in task_columns:
                self._connection.execute(
                    "ALTER TABLE tasks ADD COLUMN critical_path INTEGER NOT NULL DEFAULT 0"
                )
            if "revision" not in task_columns:
                self._connection.execute(
                    "ALTER TABLE tasks ADD COLUMN revision INTEGER NOT NULL DEFAULT 0"
                )

            evidence_columns = {
                row[1]
                for row in self._connection.execute("PRAGMA table_info(evidence)")
            }
            if "verified_at" not in evidence_columns:
                self._connection.execute("ALTER TABLE evidence ADD COLUMN verified_at TEXT")
            if "verification_method" not in evidence_columns:
                self._connection.execute(
                    "ALTER TABLE evidence ADD COLUMN verification_method TEXT"
                )

            permission_columns = {
                row[1]
                for row in self._connection.execute(
                    "PRAGMA table_info(permission_grants)"
                )
            }
            if "user_id" not in permission_columns:
                self._connection.execute(
                    "ALTER TABLE permission_grants ADD COLUMN user_id TEXT NOT NULL DEFAULT 'owner'"
                )
            if "kora_id" not in permission_columns:
                self._connection.execute(
                    "ALTER TABLE permission_grants ADD COLUMN kora_id TEXT NOT NULL DEFAULT 'kora'"
                )
            if "actions_used" not in permission_columns:
                self._connection.execute(
                    "ALTER TABLE permission_grants ADD COLUMN actions_used INTEGER NOT NULL DEFAULT 0"
                )
            if "spent_cents" not in permission_columns:
                self._connection.execute(
                    "ALTER TABLE permission_grants ADD COLUMN spent_cents INTEGER NOT NULL DEFAULT 0"
                )

            event_table = self._connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'mission_events'"
            ).fetchone()
            event_schema = event_table[0] if event_table is not None else ""
            event_schema = event_schema or ""
            required_event_types = (
                "permission_used",
                "attempt_created",
                "attempt_transitioned",
                "attempt_lease_renewed",
            )
            if event_table is not None and any(
                event_type not in event_schema for event_type in required_event_types
            ):
                # SQLite keeps trigger names when a table is renamed.  Drop
                # the old-table triggers so the append-only guards are
                # recreated for the migrated table below.
                self._connection.execute(
                    "DROP TRIGGER IF EXISTS mission_events_append_only_update"
                )
                self._connection.execute(
                    "DROP TRIGGER IF EXISTS mission_events_append_only_delete"
                )
                self._connection.execute("DROP INDEX IF EXISTS idx_events_order")
                self._connection.execute(
                    "ALTER TABLE mission_events RENAME TO mission_events_legacy"
                )
                self._connection.execute(
                    """
                    CREATE TABLE mission_events (
                        event_id TEXT PRIMARY KEY,
                        mission_id TEXT NOT NULL,
                        event_type TEXT NOT NULL CHECK (event_type IN (
                            'mission_created', 'mission_transitioned', 'task_created',
                            'task_transitioned', 'task_dependency_added',
                            'decision_recorded', 'assumption_recorded',
                            'checkpoint_recorded', 'escalation_recorded',
                            'permission_granted', 'permission_consumed',
                            'permission_used', 'permission_revoked',
                            'artifact_recorded', 'evidence_recorded',
                            'evidence_verified', 'attempt_created',
                            'attempt_transitioned', 'attempt_lease_renewed'
                        )),
                        entity_id TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY (mission_id) REFERENCES missions(mission_id)
                            ON DELETE CASCADE
                    )
                    """
                )
                self._connection.execute(
                    """
                    INSERT INTO mission_events(
                        event_id, mission_id, event_type, entity_id,
                        payload_json, created_at
                    )
                    SELECT event_id, mission_id, event_type, entity_id,
                           payload_json, created_at
                    FROM mission_events_legacy
                    """
                )
                self._connection.execute("DROP TABLE mission_events_legacy")

            self._connection.execute("DROP INDEX IF EXISTS idx_one_active_mission")
            self._connection.execute("DROP INDEX IF EXISTS idx_one_nonterminal_mission")
            duplicate = self._connection.execute(
                """
                SELECT owner_ref
                FROM missions
                WHERE state NOT IN ('completed', 'stopped', 'failed')
                GROUP BY owner_ref
                HAVING COUNT(*) > 1
                LIMIT 1
                """
            ).fetchone()
            if duplicate is not None:
                raise ConflictError(
                    "database contains multiple non-terminal missions for owner "
                    f"{duplicate[0]!r}; resolve the ambiguity before reopening"
                )
            self._connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_one_nonterminal_mission
                    ON missions (owner_ref)
                    WHERE state NOT IN ('completed', 'stopped', 'failed')
                """
            )
            self._connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_mission
                    ON missions (state) WHERE state = 'active'
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_tasks_selection
                    ON tasks (mission_id, state, critical_path DESC,
                              priority DESC, created_at, task_id)
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_attempts_lookup
                    ON task_attempts (mission_id, task_id, created_at, attempt_id)
                """
            )
            self._connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_one_live_attempt_per_task
                    ON task_attempts (task_id)
                    WHERE status IN ('created', 'running', 'verifying', 'unknown')
                """
            )
            self._connection.execute(
                """
                CREATE TRIGGER IF NOT EXISTS mission_events_append_only_update
                BEFORE UPDATE ON mission_events
                BEGIN
                    SELECT RAISE(ABORT, 'mission events are append-only');
                END
                """
            )
            self._connection.execute(
                """
                CREATE TRIGGER IF NOT EXISTS mission_events_append_only_delete
                BEFORE DELETE ON mission_events
                BEGIN
                    SELECT RAISE(ABORT, 'mission events are append-only');
                END
                """
            )
            self._connection.execute(
                """
                INSERT INTO schema_meta(key, value) VALUES('version', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (str(SCHEMA_VERSION),),
            )
            self._connection.execute(
                """
                INSERT OR IGNORE INTO schema_migrations(version, applied_at)
                VALUES (?, ?)
                """,
                (SCHEMA_VERSION, _timestamp(utc_now())),
            )
            self._connection.commit()

    def initialize_schema(self) -> None:
        """Idempotently ensure the Kora-owned schema exists."""

        self._initialize_schema()

    @contextmanager
    def transaction(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        """Run a group of repository writes atomically.

        Nested calls reuse the outer transaction.  ``immediate=True`` is used
        for compare-and-set operations such as one-time permission consumption.
        """

        with self._lock:
            if self._connection.in_transaction:
                yield self._connection
                return
            self._connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            try:
                yield self._connection
            except BaseException:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()

    def close(self) -> None:
        with self._lock:
            if self._owns_connection and not self._closed:
                self._connection.close()
                self._closed = True

    def __enter__(self) -> "SQLiteMissionStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # Missions -------------------------------------------------------------

    def create_mission(self, mission: Mission) -> Mission:
        if mission.state is not MissionState.PROPOSED:
            raise InvalidTransitionError(
                "a mission must be created in the proposed state"
            )
        if mission.revision != 0:
            raise ValidationError("a new mission must start at revision zero")
        with self.transaction():
            try:
                self._connection.execute(
                    """
                    INSERT INTO missions(
                        mission_id, title, objective, definition_of_done, state,
                        exclusions_json, created_at, updated_at, failure_reason,
                        stop_reason, revision, owner_ref
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        mission.mission_id,
                        mission.title,
                        mission.objective,
                        mission.definition_of_done,
                        mission.state.value,
                        _json_dumps(mission.exclusions),
                        _timestamp(mission.created_at),
                        _timestamp(mission.updated_at),
                        mission.failure_reason,
                        mission.stop_reason,
                        mission.revision,
                        mission.owner_ref,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                existing = self.get_mission(mission.mission_id)
                if existing is not None:
                    raise ConflictError(
                        f"mission already exists: {mission.mission_id}"
                    ) from exc
                owner_conflict = self._connection.execute(
                    """
                    SELECT 1 FROM missions
                    WHERE owner_ref = ?
                      AND state NOT IN ('completed', 'stopped', 'failed')
                    LIMIT 1
                    """,
                    (mission.owner_ref,),
                ).fetchone()
                if owner_conflict is not None:
                    raise ConflictError(
                        "only one non-terminal mission may exist per owner"
                    ) from exc
                raise ConflictError("mission violates a persistence constraint") from exc
        return mission

    add_mission = create_mission

    def get_mission(self, mission_id: str) -> Mission | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM missions WHERE mission_id = ?", (mission_id,)
            ).fetchone()
        return self._mission_from_row(row) if row is not None else None

    def require_mission(self, mission_id: str) -> Mission:
        mission = self.get_mission(mission_id)
        if mission is None:
            raise NotFoundError(f"mission not found: {mission_id}")
        return mission

    def update_mission(
        self,
        mission: Mission,
        *,
        expected_revision: int | None = None,
        _allow_state_change: bool = False,
    ) -> Mission:
        with self.transaction():
            current = self.require_mission(mission.mission_id)
            if expected_revision is None:
                expected_revision = mission.revision
            if expected_revision != current.revision:
                raise ConflictError(
                    f"stale mission revision for {mission.mission_id}: "
                    f"expected {expected_revision}, current {current.revision}"
                )
            if mission.owner_ref != current.owner_ref:
                raise ConflictError("mission owner cannot change")
            if mission.state != current.state and not _allow_state_change:
                raise InvalidTransitionError(
                    "mission state changes must go through MissionService"
                )
            if (
                mission.objective != current.objective
                or mission.definition_of_done != current.definition_of_done
                or mission.exclusions != current.exclusions
            ):
                raise ConflictError(
                    "mission contract changes require explicit re-alignment"
                )
            persisted = replace(mission, revision=current.revision + 1)
            cursor = self._connection.execute(
                """
                UPDATE missions
                SET title = ?, objective = ?, definition_of_done = ?, state = ?,
                    exclusions_json = ?, created_at = ?, updated_at = ?,
                    failure_reason = ?, stop_reason = ?, revision = ?
                WHERE mission_id = ? AND revision = ?
                """,
                (
                    persisted.title,
                    persisted.objective,
                    persisted.definition_of_done,
                    persisted.state.value,
                    _json_dumps(persisted.exclusions),
                    _timestamp(persisted.created_at),
                    _timestamp(persisted.updated_at),
                    persisted.failure_reason,
                    persisted.stop_reason,
                    persisted.revision,
                    persisted.mission_id,
                    expected_revision,
                ),
            )
            if cursor.rowcount != 1:
                raise ConflictError(
                    f"stale mission revision for {mission.mission_id}: "
                    f"expected {expected_revision}"
                )
        return persisted

    def list_missions(self, state: MissionState | None = None) -> list[Mission]:
        query = "SELECT * FROM missions"
        params: tuple[str, ...] = ()
        if state is not None:
            if not isinstance(state, MissionState):
                state = MissionState(state)
            query += " WHERE state = ?"
            params = (state.value,)
        query += " ORDER BY created_at ASC, mission_id ASC"
        with self._lock:
            rows = self._connection.execute(query, params).fetchall()
        return [self._mission_from_row(row) for row in rows]

    # Tasks and dependencies ----------------------------------------------

    def create_task(self, task: Task) -> Task:
        if task.state is not TaskStatus.READY:
            raise InvalidTransitionError("a task must be created in the ready state")
        if task.revision != 0:
            raise ValidationError("a new task must start at revision zero")
        with self.transaction():
            try:
                self._connection.execute(
                    """
                    INSERT INTO tasks(
                        task_id, mission_id, title, description, priority,
                        critical_path, state, created_at, updated_at, started_at,
                        finished_at, revision
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task.task_id,
                        task.mission_id,
                        task.title,
                        task.description,
                        task.priority,
                        int(task.critical_path),
                        task.state.value,
                        _timestamp(task.created_at),
                        _timestamp(task.updated_at),
                        _timestamp(task.started_at) if task.started_at else None,
                        _timestamp(task.finished_at) if task.finished_at else None,
                        task.revision,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                if self.get_mission(task.mission_id) is None:
                    raise NotFoundError(
                        f"mission not found: {task.mission_id}"
                    ) from exc
                raise ConflictError(f"task already exists: {task.task_id}") from exc
        return task

    add_task = create_task

    def get_task(self, task_id: str) -> Task | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
        return self._task_from_row(row) if row is not None else None

    def require_task(self, task_id: str) -> Task:
        task = self.get_task(task_id)
        if task is None:
            raise NotFoundError(f"task not found: {task_id}")
        return task

    def update_task(
        self,
        task: Task,
        *,
        expected_revision: int | None = None,
        _allow_state_change: bool = False,
    ) -> Task:
        with self.transaction():
            current = self.require_task(task.task_id)
            if current.mission_id != task.mission_id:
                raise ConflictError("task mission identity cannot change")
            if expected_revision is None:
                expected_revision = task.revision
            if expected_revision != current.revision:
                raise ConflictError(
                    f"stale task revision for {task.task_id}: "
                    f"expected {expected_revision}, current {current.revision}"
                )
            if task.state != current.state and not _allow_state_change:
                raise InvalidTransitionError(
                    "task state changes must go through MissionService"
                )
            persisted = replace(task, revision=current.revision + 1)
            cursor = self._connection.execute(
                """
                UPDATE tasks
                SET mission_id = ?, title = ?, description = ?, priority = ?,
                    critical_path = ?, state = ?, created_at = ?, updated_at = ?,
                    started_at = ?, finished_at = ?, revision = ?
                WHERE task_id = ? AND revision = ?
                """,
                (
                    persisted.mission_id,
                    persisted.title,
                    persisted.description,
                    persisted.priority,
                    int(persisted.critical_path),
                    persisted.state.value,
                    _timestamp(persisted.created_at),
                    _timestamp(persisted.updated_at),
                    _timestamp(persisted.started_at) if persisted.started_at else None,
                    _timestamp(persisted.finished_at) if persisted.finished_at else None,
                    persisted.revision,
                    persisted.task_id,
                    expected_revision,
                ),
            )
            if cursor.rowcount != 1:
                raise ConflictError(
                    f"stale task revision for {task.task_id}: "
                    f"expected {expected_revision}"
                )
        return persisted

    def list_tasks(
        self,
        mission_id: str,
        state: TaskStatus | None = None,
    ) -> list[Task]:
        query = "SELECT * FROM tasks WHERE mission_id = ?"
        params: list[str] = [mission_id]
        if state is not None:
            if not isinstance(state, TaskStatus):
                state = TaskStatus(state)
            query += " AND state = ?"
            params.append(state.value)
        query += (
            " ORDER BY critical_path DESC, priority DESC, created_at ASC, task_id ASC"
        )
        with self._lock:
            rows = self._connection.execute(query, tuple(params)).fetchall()
        return [self._task_from_row(row) for row in rows]

    # Task attempts --------------------------------------------------------

    def create_attempt(self, attempt: TaskAttempt) -> TaskAttempt:
        """Persist a newly-created attempt.

        Idempotent lookup belongs to ``MissionService.create_attempt`` so the
        service can compare the requested immutable scope before returning an
        existing record.  The repository still enforces the database-level
        uniqueness and one-live-attempt guard for direct callers.
        """

        if attempt.status is not AttemptStatus.CREATED:
            raise InvalidTransitionError(
                "an attempt must be created in the created state"
            )
        if attempt.revision != 0:
            raise ValidationError("a new attempt must start at revision zero")
        if attempt.lease_owner is not None or attempt.lease_expires_at is not None:
            raise ValidationError("a new attempt cannot already have a lease")
        if attempt.started_at is not None or attempt.finished_at is not None:
            raise ValidationError("a new attempt cannot already have lifecycle times")
        with self.transaction(immediate=True):
            mission = self._connection.execute(
                "SELECT 1 FROM missions WHERE mission_id = ?",
                (attempt.mission_id,),
            ).fetchone()
            if mission is None:
                raise NotFoundError(f"mission not found: {attempt.mission_id}")
            task = self._connection.execute(
                "SELECT mission_id FROM tasks WHERE task_id = ?",
                (attempt.task_id,),
            ).fetchone()
            if task is None:
                raise NotFoundError(f"task not found: {attempt.task_id}")
            if task["mission_id"] != attempt.mission_id:
                raise ConflictError("attempt task belongs to another mission")
            try:
                self._connection.execute(
                    """
                    INSERT INTO task_attempts(
                        attempt_id, mission_id, task_id, idempotency_key,
                        worker_role_id, route_id, status, quality_floor,
                        lease_owner, fencing_token, lease_expires_at,
                        result_summary, error_summary, total_tokens,
                        estimated_cost_usd, latency_ms, accepted, revision,
                        created_at, updated_at, started_at, finished_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                              ?, ?, ?, ?, ?)
                    """,
                    (
                        attempt.attempt_id,
                        attempt.mission_id,
                        attempt.task_id,
                        attempt.idempotency_key,
                        attempt.worker_role_id,
                        attempt.route_id,
                        attempt.status.value,
                        attempt.quality_floor,
                        attempt.lease_owner,
                        attempt.fencing_token,
                        _timestamp(attempt.lease_expires_at)
                        if attempt.lease_expires_at
                        else None,
                        attempt.result_summary,
                        attempt.error_summary,
                        attempt.total_tokens,
                        attempt.estimated_cost_usd,
                        attempt.latency_ms,
                        None if attempt.accepted is None else int(attempt.accepted),
                        attempt.revision,
                        _timestamp(attempt.created_at),
                        _timestamp(attempt.updated_at),
                        _timestamp(attempt.started_at) if attempt.started_at else None,
                        _timestamp(attempt.finished_at)
                        if attempt.finished_at
                        else None,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                if self.get_attempt(attempt.attempt_id) is not None:
                    raise ConflictError(
                        f"attempt already exists: {attempt.attempt_id}"
                    ) from exc
                existing_key = self._connection.execute(
                    """
                    SELECT attempt_id
                    FROM task_attempts
                    WHERE mission_id = ? AND task_id = ? AND idempotency_key = ?
                    """,
                    (
                        attempt.mission_id,
                        attempt.task_id,
                        attempt.idempotency_key,
                    ),
                ).fetchone()
                if existing_key is not None:
                    raise ConflictError(
                        "attempt idempotency key already exists: "
                        f"{attempt.idempotency_key}"
                    ) from exc
                live = self.get_live_attempt(attempt.task_id)
                if live is not None:
                    raise ConflictError(
                        f"task already has a live attempt: {attempt.task_id}"
                    ) from exc
                raise ConflictError("attempt violates a persistence constraint") from exc
        return attempt

    add_attempt = create_attempt

    def get_attempt(self, attempt_id: str) -> TaskAttempt | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM task_attempts WHERE attempt_id = ?",
                (attempt_id,),
            ).fetchone()
        return self._attempt_from_row(row) if row is not None else None

    get_task_attempt = get_attempt

    def require_attempt(self, attempt_id: str) -> TaskAttempt:
        attempt = self.get_attempt(attempt_id)
        if attempt is None:
            raise NotFoundError(f"attempt not found: {attempt_id}")
        return attempt

    require_task_attempt = require_attempt

    def get_attempt_by_idempotency(
        self,
        mission_id: str,
        task_id: str,
        idempotency_key: str,
    ) -> TaskAttempt | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT * FROM task_attempts
                WHERE mission_id = ? AND task_id = ? AND idempotency_key = ?
                """,
                (mission_id, task_id, idempotency_key),
            ).fetchone()
        return self._attempt_from_row(row) if row is not None else None

    def list_attempts(
        self,
        mission_id: str,
        task_id: str | None = None,
        status: AttemptStatus | None = None,
    ) -> list[TaskAttempt]:
        query = "SELECT * FROM task_attempts WHERE mission_id = ?"
        params: list[Any] = [mission_id]
        if task_id is not None:
            query += " AND task_id = ?"
            params.append(task_id)
        if status is not None:
            if not isinstance(status, AttemptStatus):
                status = AttemptStatus(status)
            query += " AND status = ?"
            params.append(status.value)
        query += " ORDER BY created_at ASC, attempt_id ASC"
        with self._lock:
            rows = self._connection.execute(query, tuple(params)).fetchall()
        return [self._attempt_from_row(row) for row in rows]

    def list_task_attempts(
        self,
        task_id: str,
        status: AttemptStatus | None = None,
    ) -> list[TaskAttempt]:
        task = self.require_task(task_id)
        return self.list_attempts(task.mission_id, task_id, status)

    def get_live_attempt(self, task_id: str) -> TaskAttempt | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT * FROM task_attempts
                WHERE task_id = ?
                  AND status IN ('created', 'running', 'verifying', 'unknown')
                ORDER BY created_at ASC, attempt_id ASC
                LIMIT 1
                """,
                (task_id,),
            ).fetchone()
        return self._attempt_from_row(row) if row is not None else None

    def update_attempt(
        self,
        attempt: TaskAttempt,
        *,
        expected_revision: int | None = None,
        _allow_status_change: bool = False,
    ) -> TaskAttempt:
        with self.transaction():
            current = self.require_attempt(attempt.attempt_id)
            if (
                current.mission_id != attempt.mission_id
                or current.task_id != attempt.task_id
                or current.idempotency_key != attempt.idempotency_key
                or current.worker_role_id != attempt.worker_role_id
                or current.route_id != attempt.route_id
                or current.quality_floor != attempt.quality_floor
                or current.created_at != attempt.created_at
            ):
                raise ConflictError("attempt identity and scope are immutable")
            if expected_revision is None:
                expected_revision = attempt.revision
            if expected_revision != current.revision:
                raise ConflictError(
                    f"stale attempt revision for {attempt.attempt_id}: "
                    f"expected {expected_revision}, current {current.revision}"
                )
            if attempt.status != current.status and not _allow_status_change:
                raise InvalidTransitionError(
                    "attempt state changes must go through MissionService"
                )
            persisted = replace(attempt, revision=current.revision + 1)
            try:
                cursor = self._connection.execute(
                    """
                    UPDATE task_attempts
                    SET status = ?, quality_floor = ?, lease_owner = ?,
                        fencing_token = ?, lease_expires_at = ?,
                        result_summary = ?, error_summary = ?, total_tokens = ?,
                        estimated_cost_usd = ?, latency_ms = ?, accepted = ?,
                        revision = ?, updated_at = ?, started_at = ?,
                        finished_at = ?
                    WHERE attempt_id = ? AND revision = ?
                    """,
                    (
                        persisted.status.value,
                        persisted.quality_floor,
                        persisted.lease_owner,
                        persisted.fencing_token,
                        _timestamp(persisted.lease_expires_at)
                        if persisted.lease_expires_at
                        else None,
                        persisted.result_summary,
                        persisted.error_summary,
                        persisted.total_tokens,
                        persisted.estimated_cost_usd,
                        persisted.latency_ms,
                        None
                        if persisted.accepted is None
                        else int(persisted.accepted),
                        persisted.revision,
                        _timestamp(persisted.updated_at),
                        _timestamp(persisted.started_at)
                        if persisted.started_at
                        else None,
                        _timestamp(persisted.finished_at)
                        if persisted.finished_at
                        else None,
                        persisted.attempt_id,
                        expected_revision,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ConflictError(
                    f"attempt update violates a persistence constraint: "
                    f"{attempt.attempt_id}"
                ) from exc
            if cursor.rowcount != 1:
                raise ConflictError(
                    f"stale attempt revision for {attempt.attempt_id}: "
                    f"expected {expected_revision}"
                )
        return persisted

    def create_dependency(self, dependency: TaskDependency) -> TaskDependency:
        with self.transaction():
            task = self._connection.execute(
                "SELECT mission_id FROM tasks WHERE task_id = ?",
                (dependency.task_id,),
            ).fetchone()
            prerequisite = self._connection.execute(
                "SELECT mission_id FROM tasks WHERE task_id = ?",
                (dependency.depends_on_task_id,),
            ).fetchone()
            if task is None:
                raise NotFoundError(f"task not found: {dependency.task_id}")
            if prerequisite is None:
                raise NotFoundError(f"task not found: {dependency.depends_on_task_id}")
            if (
                task["mission_id"] != dependency.mission_id
                or prerequisite["mission_id"] != dependency.mission_id
            ):
                raise DependencyError("cross-mission dependencies are not allowed")
            graph: dict[str, set[str]] = {}
            rows = self._connection.execute(
                """
                SELECT task_id, depends_on_task_id
                FROM task_dependencies
                WHERE mission_id = ?
                """,
                (dependency.mission_id,),
            ).fetchall()
            for row in rows:
                graph.setdefault(row["task_id"], set()).add(row["depends_on_task_id"])
            graph.setdefault(dependency.task_id, set()).add(
                dependency.depends_on_task_id
            )
            if self._dependency_reaches(
                graph, dependency.depends_on_task_id, dependency.task_id
            ):
                raise DependencyError("task dependency would introduce a cycle")
            try:
                self._connection.execute(
                    """
                    INSERT INTO task_dependencies(
                        mission_id, task_id, depends_on_task_id, created_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        dependency.mission_id,
                        dependency.task_id,
                        dependency.depends_on_task_id,
                        _timestamp(dependency.created_at),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ConflictError(
                    "dependency violates mission/task constraints or already exists"
                ) from exc
        return dependency

    add_dependency = create_dependency

    def list_dependencies(self, mission_id: str) -> list[TaskDependency]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT * FROM task_dependencies
                WHERE mission_id = ?
                ORDER BY created_at ASC, task_id ASC, depends_on_task_id ASC
                """,
                (mission_id,),
            ).fetchall()
        return [
            TaskDependency(
                mission_id=row["mission_id"],
                task_id=row["task_id"],
                depends_on_task_id=row["depends_on_task_id"],
                created_at=_parse_timestamp(row["created_at"]),
            )
            for row in rows
        ]

    def list_prerequisites(self, task_id: str) -> list[Task]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT t.*
                FROM tasks AS t
                JOIN task_dependencies AS d
                  ON d.mission_id = t.mission_id
                 AND d.depends_on_task_id = t.task_id
                WHERE d.task_id = ?
                ORDER BY t.critical_path DESC, t.priority DESC,
                         t.created_at ASC, t.task_id ASC
                """,
                (task_id,),
            ).fetchall()
        return [self._task_from_row(row) for row in rows]

    # Semantic records -----------------------------------------------------

    def create_decision(self, decision: Decision) -> Decision:
        with self.transaction():
            self._insert_mission_record(
                """
                INSERT INTO decisions(
                    decision_id, mission_id, summary, decision, rationale, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    decision.decision_id,
                    decision.mission_id,
                    decision.summary,
                    decision.decision,
                    decision.rationale,
                    _timestamp(decision.created_at),
                ),
                decision.mission_id,
                decision.decision_id,
            )
        return decision

    record_decision = create_decision

    def list_decisions(self, mission_id: str) -> list[Decision]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT * FROM decisions
                WHERE mission_id = ?
                ORDER BY created_at ASC, decision_id ASC
                """,
                (mission_id,),
            ).fetchall()
        return [
            Decision(
                decision_id=row["decision_id"],
                mission_id=row["mission_id"],
                summary=row["summary"],
                decision=row["decision"],
                rationale=row["rationale"],
                created_at=_parse_timestamp(row["created_at"]),
            )
            for row in rows
        ]

    def create_assumption(self, assumption: Assumption) -> Assumption:
        with self.transaction():
            self._insert_mission_record(
                """
                INSERT INTO assumptions(
                    assumption_id, mission_id, statement, rationale, status,
                    created_at, resolved_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    assumption.assumption_id,
                    assumption.mission_id,
                    assumption.statement,
                    assumption.rationale,
                    assumption.status.value,
                    _timestamp(assumption.created_at),
                    _timestamp(assumption.resolved_at)
                    if assumption.resolved_at
                    else None,
                ),
                assumption.mission_id,
                assumption.assumption_id,
            )
        return assumption

    record_assumption = create_assumption

    def list_assumptions(self, mission_id: str) -> list[Assumption]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT * FROM assumptions
                WHERE mission_id = ?
                ORDER BY created_at ASC, assumption_id ASC
                """,
                (mission_id,),
            ).fetchall()
        return [
            Assumption(
                assumption_id=row["assumption_id"],
                mission_id=row["mission_id"],
                statement=row["statement"],
                rationale=row["rationale"],
                status=AssumptionStatus(row["status"]),
                created_at=_parse_timestamp(row["created_at"]),
                resolved_at=(
                    _parse_timestamp(row["resolved_at"]) if row["resolved_at"] else None
                ),
            )
            for row in rows
        ]

    def create_checkpoint(self, checkpoint: Checkpoint) -> Checkpoint:
        with self.transaction():
            self._insert_mission_record(
                """
                INSERT INTO checkpoints(
                    checkpoint_id, mission_id, task_id, kind, summary, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    checkpoint.checkpoint_id,
                    checkpoint.mission_id,
                    checkpoint.task_id,
                    checkpoint.kind.value,
                    checkpoint.summary,
                    _timestamp(checkpoint.created_at),
                ),
                checkpoint.mission_id,
                checkpoint.checkpoint_id,
            )
        return checkpoint

    record_checkpoint = create_checkpoint

    def list_checkpoints(self, mission_id: str) -> list[Checkpoint]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT * FROM checkpoints
                WHERE mission_id = ?
                ORDER BY created_at ASC, checkpoint_id ASC
                """,
                (mission_id,),
            ).fetchall()
        return [
            Checkpoint(
                checkpoint_id=row["checkpoint_id"],
                mission_id=row["mission_id"],
                task_id=row["task_id"],
                kind=CheckpointType(row["kind"]),
                summary=row["summary"],
                created_at=_parse_timestamp(row["created_at"]),
            )
            for row in rows
        ]

    def create_escalation(self, escalation: Escalation) -> Escalation:
        if escalation.status is not EscalationStatus.OPEN:
            raise InvalidTransitionError(
                "an escalation must be created in the open state"
            )
        with self.transaction():
            self._insert_mission_record(
                """
                INSERT INTO escalations(
                    escalation_id, mission_id, task_id, title, reason, impact,
                    options_json, recommendation, consequence_of_waiting,
                    requested_action, status, created_at, resolved_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    escalation.escalation_id,
                    escalation.mission_id,
                    escalation.task_id,
                    escalation.title,
                    escalation.reason,
                    escalation.impact,
                    _json_dumps(escalation.options),
                    escalation.recommendation,
                    escalation.consequence_of_waiting,
                    escalation.requested_action,
                    escalation.status.value,
                    _timestamp(escalation.created_at),
                    _timestamp(escalation.resolved_at)
                    if escalation.resolved_at
                    else None,
                ),
                escalation.mission_id,
                escalation.escalation_id,
            )
        return escalation

    record_escalation = create_escalation

    def update_escalation(
        self,
        escalation: Escalation,
        *,
        _allow_status_change: bool = False,
    ) -> Escalation:
        with self.transaction():
            current = self.get_escalation(escalation.escalation_id)
            if current is None:
                raise NotFoundError(f"escalation not found: {escalation.escalation_id}")
            if current.mission_id != escalation.mission_id:
                raise ConflictError("escalation mission identity cannot change")
            if escalation.status != current.status and not _allow_status_change:
                raise InvalidTransitionError(
                    "escalation status changes must go through MissionService"
                )
            if current.status is not EscalationStatus.OPEN and escalation != current:
                raise ConflictError("resolved escalation records are immutable")
            cursor = self._connection.execute(
                """
                UPDATE escalations
                SET mission_id = ?, task_id = ?, title = ?, reason = ?, impact = ?,
                    options_json = ?, recommendation = ?, consequence_of_waiting = ?,
                    requested_action = ?, status = ?, created_at = ?, resolved_at = ?
                WHERE escalation_id = ?
                """,
                (
                    escalation.mission_id,
                    escalation.task_id,
                    escalation.title,
                    escalation.reason,
                    escalation.impact,
                    _json_dumps(escalation.options),
                    escalation.recommendation,
                    escalation.consequence_of_waiting,
                    escalation.requested_action,
                    escalation.status.value,
                    _timestamp(escalation.created_at),
                    _timestamp(escalation.resolved_at)
                    if escalation.resolved_at
                    else None,
                    escalation.escalation_id,
                ),
            )
            if cursor.rowcount != 1:
                raise NotFoundError(f"escalation not found: {escalation.escalation_id}")
        return escalation

    def get_escalation(self, escalation_id: str) -> Escalation | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM escalations WHERE escalation_id = ?", (escalation_id,)
            ).fetchone()
        return self._escalation_from_row(row) if row is not None else None

    def list_escalations(
        self,
        mission_id: str,
        status: EscalationStatus | None = None,
    ) -> list[Escalation]:
        query = "SELECT * FROM escalations WHERE mission_id = ?"
        params: list[str] = [mission_id]
        if status is not None:
            if not isinstance(status, EscalationStatus):
                status = EscalationStatus(status)
            query += " AND status = ?"
            params.append(status.value)
        query += " ORDER BY created_at ASC, escalation_id ASC"
        with self._lock:
            rows = self._connection.execute(query, tuple(params)).fetchall()
        return [self._escalation_from_row(row) for row in rows]

    def create_artifact(self, artifact: Artifact) -> Artifact:
        with self.transaction():
            self._insert_mission_record(
                """
                INSERT INTO artifacts(
                    artifact_id, mission_id, task_id, name, locator, kind, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact.artifact_id,
                    artifact.mission_id,
                    artifact.task_id,
                    artifact.name,
                    artifact.locator,
                    artifact.kind.value,
                    _timestamp(artifact.created_at),
                ),
                artifact.mission_id,
                artifact.artifact_id,
            )
        return artifact

    record_artifact = create_artifact

    def list_artifacts(self, mission_id: str) -> list[Artifact]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT * FROM artifacts
                WHERE mission_id = ?
                ORDER BY created_at ASC, artifact_id ASC
                """,
                (mission_id,),
            ).fetchall()
        return [
            Artifact(
                artifact_id=row["artifact_id"],
                mission_id=row["mission_id"],
                task_id=row["task_id"],
                name=row["name"],
                locator=row["locator"],
                kind=ArtifactKind(row["kind"]),
                created_at=_parse_timestamp(row["created_at"]),
            )
            for row in rows
        ]

    def create_evidence(self, evidence: Evidence) -> Evidence:
        if evidence.verified_at is not None or evidence.verification_method is not None:
            raise InvalidTransitionError(
                "evidence must be independently verified after it is recorded"
            )
        with self.transaction():
            self._insert_mission_record(
                """
                INSERT INTO evidence(
                    evidence_id, mission_id, task_id, artifact_id, summary, kind,
                    locator, created_at, verified_at, verification_method
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence.evidence_id,
                    evidence.mission_id,
                    evidence.task_id,
                    evidence.artifact_id,
                    evidence.summary,
                    evidence.kind.value,
                    evidence.locator,
                    _timestamp(evidence.created_at),
                    _timestamp(evidence.verified_at) if evidence.verified_at else None,
                    evidence.verification_method,
                ),
                evidence.mission_id,
                evidence.evidence_id,
            )
        return evidence

    record_evidence = create_evidence

    def list_evidence(self, mission_id: str) -> list[Evidence]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT * FROM evidence
                WHERE mission_id = ?
                ORDER BY created_at ASC, evidence_id ASC
                """,
                (mission_id,),
            ).fetchall()
        return [
            Evidence(
                evidence_id=row["evidence_id"],
                mission_id=row["mission_id"],
                task_id=row["task_id"],
                artifact_id=row["artifact_id"],
                summary=row["summary"],
                kind=EvidenceKind(row["kind"]),
                locator=row["locator"],
                created_at=_parse_timestamp(row["created_at"]),
                verified_at=_parse_timestamp(row["verified_at"])
                if row["verified_at"]
                else None,
                verification_method=row["verification_method"],
            )
            for row in rows
        ]

    def update_evidence(self, evidence: Evidence) -> Evidence:
        """Record one irreversible verification outcome for an evidence claim."""

        with self.transaction():
            current = self._get_evidence(evidence.evidence_id)
            if current is None:
                raise NotFoundError(f"evidence not found: {evidence.evidence_id}")
            if current.mission_id != evidence.mission_id:
                raise ConflictError("evidence mission identity cannot change")
            if (
                current.task_id != evidence.task_id
                or current.artifact_id != evidence.artifact_id
                or current.summary != evidence.summary
                or current.kind != evidence.kind
                or current.locator != evidence.locator
                or current.created_at != evidence.created_at
            ):
                raise ConflictError("evidence claims are immutable after recording")
            if current.verified_at is not None:
                raise ConflictError("evidence has already been verified")
            if evidence.verified_at is None or evidence.verification_method is None:
                raise ValidationError("evidence verification requires a method and time")
            cursor = self._connection.execute(
                """
                UPDATE evidence
                SET verified_at = ?, verification_method = ?
                WHERE evidence_id = ? AND verified_at IS NULL
                """,
                (
                    _timestamp(evidence.verified_at),
                    evidence.verification_method,
                    evidence.evidence_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ConflictError("evidence verification lost a race")
        return evidence

    def get_evidence(self, evidence_id: str) -> Evidence | None:
        with self._lock:
            return self._get_evidence(evidence_id)

    def _get_evidence(self, evidence_id: str) -> Evidence | None:
        row = self._connection.execute(
            "SELECT * FROM evidence WHERE evidence_id = ?", (evidence_id,)
        ).fetchone()
        if row is None:
            return None
        return Evidence(
            evidence_id=row["evidence_id"],
            mission_id=row["mission_id"],
            task_id=row["task_id"],
            artifact_id=row["artifact_id"],
            summary=row["summary"],
            kind=EvidenceKind(row["kind"]),
            locator=row["locator"],
            created_at=_parse_timestamp(row["created_at"]),
            verified_at=_parse_timestamp(row["verified_at"])
            if row["verified_at"]
            else None,
            verification_method=row["verification_method"],
        )

    # Permissions ----------------------------------------------------------

    def create_permission_grant(self, grant: PermissionGrant) -> PermissionGrant:
        with self.transaction():
            mission = self.require_mission(grant.mission_id)
            if mission.state in {
                MissionState.PROPOSED,
                MissionState.COMPLETED,
                MissionState.STOPPED,
                MissionState.FAILED,
            }:
                raise InvalidTransitionError(
                    "permission grants require an aligned, non-terminal mission"
                )
            if (
                grant.approved_by != mission.owner_ref
                or grant.user_id != mission.owner_ref
            ):
                raise ConflictError(
                    "only the mission owner may activate a permission grant"
                )
            self._insert_mission_record(
                """
                INSERT INTO permission_grants(
                    grant_id, mission_id, action, resource, purpose, mode, scope,
                    max_actions, budget_limit_cents, approved_by, user_id, kora_id,
                    approved_at, expires_at, revoked_at, consumed_at,
                    actions_used, spent_cents
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    grant.grant_id,
                    grant.mission_id,
                    grant.action.value,
                    grant.resource,
                    grant.purpose,
                    grant.mode.value,
                    grant.scope,
                    grant.max_actions,
                    grant.budget_limit_cents,
                    grant.approved_by,
                    grant.user_id,
                    grant.kora_id,
                    _timestamp(grant.approved_at),
                    _timestamp(grant.expires_at) if grant.expires_at else None,
                    _timestamp(grant.revoked_at) if grant.revoked_at else None,
                    _timestamp(grant.consumed_at) if grant.consumed_at else None,
                    grant.actions_used,
                    grant.spent_cents,
                ),
                grant.mission_id,
                grant.grant_id,
            )
        return grant

    grant_permission = create_permission_grant

    def get_permission_grant(self, grant_id: str) -> PermissionGrant | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM permission_grants WHERE grant_id = ?", (grant_id,)
            ).fetchone()
        return self._permission_from_row(row) if row is not None else None

    def list_permission_grants(
        self,
        mission_id: str,
        action: PermissionAction | None = None,
    ) -> list[PermissionGrant]:
        query = "SELECT * FROM permission_grants WHERE mission_id = ?"
        params: list[str] = [mission_id]
        if action is not None:
            if not isinstance(action, PermissionAction):
                action = PermissionAction(action)
            query += " AND action = ?"
            params.append(action.value)
        query += " ORDER BY approved_at ASC, grant_id ASC"
        with self._lock:
            rows = self._connection.execute(query, tuple(params)).fetchall()
        return [self._permission_from_row(row) for row in rows]

    def update_permission_grant(self, grant: PermissionGrant) -> PermissionGrant:
        with self.transaction():
            current = self.get_permission_grant(grant.grant_id)
            if current is None:
                raise NotFoundError(f"permission grant not found: {grant.grant_id}")
            if current.mission_id != grant.mission_id:
                raise ConflictError("permission grant mission identity cannot change")
            if grant != current:
                raise ConflictError(
                    "permission grants are append-only; use the permission "
                    "broker to record use or revocation"
                )
        return grant

    def use_permission(
        self,
        grant_id: str,
        *,
        idempotency_key: str,
        action_count: int = 1,
        spent_cents: int = 0,
        used_at: datetime | None = None,
    ) -> PermissionGrant | None:
        """Atomically record a bounded action against a semantic grant.

        A ``None`` result means the grant is not usable at the requested time.
        The usage row and grant counters commit together, so an audit failure or
        duplicate write cannot leave a partially consumed grant.
        """

        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ValidationError("idempotency_key must be a non-empty string")
        if (
            isinstance(action_count, bool)
            or not isinstance(action_count, int)
            or action_count <= 0
        ):
            raise ValidationError("action_count must be a positive integer")
        if (
            isinstance(spent_cents, bool)
            or not isinstance(spent_cents, int)
            or spent_cents < 0
        ):
            raise ValidationError("spent_cents must be a non-negative integer")
        used = normalize_timestamp(used_at or utc_now())
        used_text = _timestamp(used)
        with self.transaction(immediate=True):
            existing_use = self._connection.execute(
                "SELECT grant_id FROM permission_uses WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if existing_use is not None:
                raise ConflictError(
                    f"permission use idempotency key already exists: {idempotency_key}"
                )
            row = self._connection.execute(
                "SELECT * FROM permission_grants WHERE grant_id = ?", (grant_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError(f"permission grant not found: {grant_id}")
            if row["mode"] == PermissionMode.APPROVE_ONCE.value and action_count != 1:
                raise ValidationError("approve-once grants permit exactly one action")
            cursor = self._connection.execute(
                """
                UPDATE permission_grants
                SET actions_used = actions_used + ?,
                    spent_cents = spent_cents + ?,
                    consumed_at = CASE
                        WHEN mode = ? THEN ?
                        ELSE consumed_at
                    END
                WHERE grant_id = ?
                  AND revoked_at IS NULL
                  AND approved_at <= ?
                  AND (expires_at IS NULL OR expires_at > ?)
                  AND (consumed_at IS NULL)
                  AND EXISTS (
                      SELECT 1 FROM missions
                      WHERE missions.mission_id = permission_grants.mission_id
                        AND missions.state = 'active'
                  )
                  AND (max_actions IS NULL OR actions_used + ? <= max_actions)
                  AND (budget_limit_cents IS NULL OR spent_cents < budget_limit_cents)
                  AND (budget_limit_cents IS NULL
                       OR spent_cents + ? <= budget_limit_cents)
                """,
                (
                    action_count,
                    spent_cents,
                    PermissionMode.APPROVE_ONCE.value,
                    used_text,
                    grant_id,
                    used_text,
                    used_text,
                    action_count,
                    spent_cents,
                ),
            )
            if cursor.rowcount != 1:
                return None
            self._connection.execute(
                """
                INSERT INTO permission_uses(
                    use_id, grant_id, idempotency_key, action_count,
                    spent_cents, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    f"use-{uuid4().hex}",
                    grant_id,
                    idempotency_key,
                    action_count,
                    spent_cents,
                    used_text,
                ),
            )
            updated_row = self._connection.execute(
                "SELECT * FROM permission_grants WHERE grant_id = ?", (grant_id,)
            ).fetchone()
        return (
            self._permission_from_row(updated_row)
            if updated_row is not None
            else None
        )

    def consume_permission(
        self,
        grant_id: str,
        *,
        consumed_at: datetime | None = None,
        idempotency_key: str | None = None,
    ) -> PermissionGrant | None:
        """Atomically consume an available approve-once grant."""

        consumed = normalize_timestamp(consumed_at or utc_now())
        return self.use_permission(
            grant_id,
            idempotency_key=idempotency_key
            or f"consume:{grant_id}:{_timestamp(consumed)}",
            used_at=consumed,
        )

    def revoke_permission(
        self,
        grant_id: str,
        *,
        revoked_at: datetime | None = None,
    ) -> PermissionGrant:
        revoked = normalize_timestamp(revoked_at or utc_now())
        with self.transaction(immediate=True):
            cursor = self._connection.execute(
                """
                UPDATE permission_grants
                SET revoked_at = ?
                WHERE grant_id = ? AND revoked_at IS NULL
                """,
                (_timestamp(revoked), grant_id),
            )
            if cursor.rowcount != 1:
                if self.get_permission_grant(grant_id) is None:
                    raise NotFoundError(f"permission grant not found: {grant_id}")
                raise ConflictError(f"permission grant already revoked: {grant_id}")
            row = self._connection.execute(
                "SELECT * FROM permission_grants WHERE grant_id = ?", (grant_id,)
            ).fetchone()
        if row is None:
            raise NotFoundError(f"permission grant not found: {grant_id}")
        return self._permission_from_row(row)

    # Audit events ---------------------------------------------------------

    def create_event(self, event: DomainEvent) -> DomainEvent:
        with self.transaction():
            self._insert_mission_record(
                """
                INSERT INTO mission_events(
                    event_id, mission_id, event_type, entity_id, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.mission_id,
                    event.event_type.value,
                    event.entity_id,
                    _json_dumps(dict(event.payload)),
                    _timestamp(event.created_at),
                ),
                event.mission_id,
                event.event_id,
            )
        return event

    record_event = create_event

    def list_events(self, mission_id: str) -> list[DomainEvent]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT * FROM mission_events
                WHERE mission_id = ?
                ORDER BY created_at ASC, event_id ASC
                """,
                (mission_id,),
            ).fetchall()
        result: list[DomainEvent] = []
        for row in rows:
            payload = _json_loads(row["payload_json"])
            if not isinstance(payload, Mapping):
                raise ValidationError("persisted event payload must be an object")
            result.append(
                DomainEvent(
                    event_id=row["event_id"],
                    mission_id=row["mission_id"],
                    event_type=EventType(row["event_type"]),
                    entity_id=row["entity_id"],
                    payload=payload,
                    created_at=_parse_timestamp(row["created_at"]),
                )
            )
        return result

    # Internal conversion and validation helpers -------------------------

    def _insert_mission_record(
        self,
        query: str,
        params: tuple[Any, ...],
        mission_id: str,
        record_id: str,
    ) -> None:
        try:
            self._connection.execute(query, params)
        except sqlite3.IntegrityError as exc:
            if self.get_mission(mission_id) is None:
                raise NotFoundError(f"mission not found: {mission_id}") from exc
            raise ConflictError(f"record already exists: {record_id}") from exc

    @staticmethod
    def _dependency_reaches(
        graph: Mapping[str, set[str]], start: str, target: str
    ) -> bool:
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
    def _mission_from_row(row: sqlite3.Row) -> Mission:
        return Mission(
            mission_id=row["mission_id"],
            title=row["title"],
            objective=row["objective"],
            definition_of_done=row["definition_of_done"],
            state=MissionState(row["state"]),
            exclusions=_text_tuple(row["exclusions_json"], "exclusions"),
            owner_ref=row["owner_ref"],
            created_at=_parse_timestamp(row["created_at"]),
            updated_at=_parse_timestamp(row["updated_at"]),
            failure_reason=row["failure_reason"],
            stop_reason=row["stop_reason"],
            revision=row["revision"],
        )

    @staticmethod
    def _task_from_row(row: sqlite3.Row) -> Task:
        return Task(
            task_id=row["task_id"],
            mission_id=row["mission_id"],
            title=row["title"],
            description=row["description"],
            priority=row["priority"],
            critical_path=bool(row["critical_path"]),
            state=TaskStatus(row["state"]),
            created_at=_parse_timestamp(row["created_at"]),
            updated_at=_parse_timestamp(row["updated_at"]),
            started_at=_parse_timestamp(row["started_at"])
            if row["started_at"]
            else None,
            finished_at=_parse_timestamp(row["finished_at"])
            if row["finished_at"]
            else None,
            revision=row["revision"],
        )

    @staticmethod
    def _attempt_from_row(row: sqlite3.Row) -> TaskAttempt:
        accepted = row["accepted"]
        return TaskAttempt(
            attempt_id=row["attempt_id"],
            mission_id=row["mission_id"],
            task_id=row["task_id"],
            idempotency_key=row["idempotency_key"],
            worker_role_id=row["worker_role_id"],
            route_id=row["route_id"],
            status=AttemptStatus(row["status"]),
            quality_floor=row["quality_floor"],
            lease_owner=row["lease_owner"],
            fencing_token=row["fencing_token"],
            lease_expires_at=_parse_timestamp(row["lease_expires_at"])
            if row["lease_expires_at"]
            else None,
            result_summary=row["result_summary"],
            error_summary=row["error_summary"],
            total_tokens=row["total_tokens"],
            estimated_cost_usd=row["estimated_cost_usd"],
            latency_ms=row["latency_ms"],
            accepted=None if accepted is None else bool(accepted),
            revision=row["revision"],
            created_at=_parse_timestamp(row["created_at"]),
            updated_at=_parse_timestamp(row["updated_at"]),
            started_at=_parse_timestamp(row["started_at"])
            if row["started_at"]
            else None,
            finished_at=_parse_timestamp(row["finished_at"])
            if row["finished_at"]
            else None,
        )

    @staticmethod
    def _escalation_from_row(row: sqlite3.Row) -> Escalation:
        return Escalation(
            escalation_id=row["escalation_id"],
            mission_id=row["mission_id"],
            task_id=row["task_id"],
            title=row["title"],
            reason=row["reason"],
            impact=row["impact"],
            options=_text_tuple(row["options_json"], "options"),
            recommendation=row["recommendation"],
            consequence_of_waiting=row["consequence_of_waiting"],
            requested_action=row["requested_action"],
            status=EscalationStatus(row["status"]),
            created_at=_parse_timestamp(row["created_at"]),
            resolved_at=_parse_timestamp(row["resolved_at"])
            if row["resolved_at"]
            else None,
        )

    @staticmethod
    def _permission_from_row(row: sqlite3.Row) -> PermissionGrant:
        return PermissionGrant(
            grant_id=row["grant_id"],
            mission_id=row["mission_id"],
            action=PermissionAction(row["action"]),
            resource=row["resource"],
            purpose=row["purpose"],
            mode=PermissionMode(row["mode"]),
            scope=row["scope"],
            max_actions=row["max_actions"],
            budget_limit_cents=row["budget_limit_cents"],
            approved_by=row["approved_by"],
            user_id=row["user_id"],
            kora_id=row["kora_id"],
            approved_at=_parse_timestamp(row["approved_at"]),
            expires_at=_parse_timestamp(row["expires_at"])
            if row["expires_at"]
            else None,
            revoked_at=_parse_timestamp(row["revoked_at"])
            if row["revoked_at"]
            else None,
            consumed_at=_parse_timestamp(row["consumed_at"])
            if row["consumed_at"]
            else None,
            actions_used=row["actions_used"],
            spent_cents=row["spent_cents"],
        )


MissionStore = SQLiteMissionStore
MissionRepository = SQLiteMissionStore

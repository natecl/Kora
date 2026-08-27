"""Durable, provider-agnostic orchestration of one mission task at a time.

The execution package is deliberately a narrow seam between Kora's mission
control plane, private workforce/router state, replaceable runtimes, and the
independent workspace verifier.  Route and runtime topology stay inside this
module; coordinator results contain only semantic mission state.
"""

from __future__ import annotations

import math
import time
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from os import PathLike
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from kora.execution.errors import (
    ExecutionError,
    ExecutionValidationError,
    MissingRuntimeRouteError,
    RuntimeResolutionError,
    TaskSpecificationNotFoundError,
    TaskSpecNotFoundError,
)
from kora.mission import (
    AttemptStatus,
    CheckpointType,
    EscalationStatus,
    Evidence,
    EvidenceKind,
    Mission,
    MissionService,
    MissionState,
    PermissionAction,
    Task,
    TaskAttempt,
    TaskStatus,
    utc_now,
)
from kora.runtime.contracts import (
    Capability,
    IsolationMode,
    RuntimeJob,
    RuntimeResult,
    RuntimeStatus,
)
from kora.verification import (
    VerificationArtifact,
    VerificationCommand,
    WorkspaceVerificationRequest,
    WorkspaceVerifier,
)
from kora.workforce import (
    ModelRouter,
    RoleCharter,
    RouteObservation,
    TaskProfile,
    WorkerEnvelope,
    WorkforceCompiler,
)
from kora.workforce.errors import NoEligibleRouteError

_SUMMARY_LIMIT = 1000
_VERIFICATION_METHOD = "independent workspace verifier"


def _non_empty_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExecutionValidationError(f"{field_name} must be a non-empty string")
    return value


def _string(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise ExecutionValidationError(f"{field_name} must be a string")
    return value


def _optional_non_empty(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _non_empty_string(value, field_name)


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        raise ExecutionValidationError(
            f"{field_name} must be a sequence of non-empty strings"
        )
    try:
        values = tuple(value)
    except TypeError as exc:
        raise ExecutionValidationError(
            f"{field_name} must be a sequence of non-empty strings"
        ) from exc
    if any(not isinstance(item, str) or not item.strip() for item in values):
        raise ExecutionValidationError(
            f"{field_name} must contain only non-empty strings"
        )
    return values


def _coerce_capability(value: Any) -> Capability:
    if isinstance(value, Capability):
        return value
    try:
        return Capability(value)
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(capability.value for capability in Capability)
        raise ExecutionValidationError(
            f"runtime_capabilities must contain Capability values: {allowed}"
        ) from exc


def _capability_set(value: Any) -> frozenset[Capability]:
    if isinstance(value, (str, bytes)):
        raise ExecutionValidationError(
            "runtime_capabilities must be a collection of Capability values"
        )
    try:
        values = frozenset(_coerce_capability(item) for item in value)
    except TypeError as exc:
        raise ExecutionValidationError(
            "runtime_capabilities must be a collection of Capability values"
        ) from exc
    return values


def _coerce_isolation(value: Any) -> IsolationMode:
    if isinstance(value, IsolationMode):
        return value
    try:
        return IsolationMode(value)
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(mode.value for mode in IsolationMode)
        raise ExecutionValidationError(
            f"isolation must be one of: {allowed}"
        ) from exc


def _coerce_permission_action(value: Any) -> PermissionAction:
    if isinstance(value, PermissionAction):
        return value
    try:
        return PermissionAction(value)
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(action.value for action in PermissionAction)
        raise ExecutionValidationError(
            f"action must be one of: {allowed}"
        ) from exc


def _positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ExecutionValidationError(f"{field_name} must be a positive integer")
    return value


def _nonnegative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ExecutionValidationError(
            f"{field_name} must be a non-negative integer"
        )
    return value


def _positive_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ExecutionValidationError(f"{field_name} must be a finite positive number")
    result = float(value)
    if not math.isfinite(result) or result <= 0.0:
        raise ExecutionValidationError(f"{field_name} must be a finite positive number")
    return result


def _nonnegative_metric(value: Any, default: float) -> int | float:
    """Normalize opaque runtime metrics without allowing invalid persistence."""

    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value if value >= 0 else default
    if isinstance(value, float):
        return value if math.isfinite(value) and value >= 0.0 else default
    return default


def sanitize_summary(value: Any, fallback: str = "") -> str:
    """Remove control data and cap runtime-derived text before persistence."""

    if not isinstance(value, str):
        value = fallback
    if not isinstance(value, str):
        value = ""
    sanitized: list[str] = []
    for character in value.replace("\r", "\n"):
        if character in "\n\t":
            sanitized.append(character)
            continue
        if unicodedata.category(character).startswith("C"):
            continue
        sanitized.append(character)
    result = "".join(sanitized).strip()
    if len(result) <= _SUMMARY_LIMIT:
        return result
    marker = "\n...[truncated]"
    return result[: _SUMMARY_LIMIT - len(marker)] + marker


def _path(value: Any, field_name: str) -> Path:
    if not isinstance(value, (Path, PathLike)):
        raise ExecutionValidationError(f"{field_name} must be a Path")
    try:
        return Path(value)
    except (TypeError, ValueError, OSError) as exc:
        raise ExecutionValidationError(f"{field_name} must be a Path") from exc


@dataclass(frozen=True, slots=True)
class PermissionRequirement:
    """One exact semantic permission needed immediately before execution."""

    grant_id: str
    action: PermissionAction
    resource: str
    action_count: int = 1
    spent_cents: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "grant_id", _non_empty_string(self.grant_id, "grant_id"))
        object.__setattr__(self, "action", _coerce_permission_action(self.action))
        object.__setattr__(self, "resource", _non_empty_string(self.resource, "resource"))
        object.__setattr__(
            self, "action_count", _positive_int(self.action_count, "action_count")
        )
        object.__setattr__(
            self, "spent_cents", _nonnegative_int(self.spent_cents, "spent_cents")
        )


def _permission_requirements(value: Any) -> tuple[PermissionRequirement, ...]:
    if isinstance(value, (str, bytes)):
        raise ExecutionValidationError(
            "permission_requirements must contain PermissionRequirement values"
        )
    try:
        values = tuple(value)
    except TypeError as exc:
        raise ExecutionValidationError(
            "permission_requirements must contain PermissionRequirement values"
        ) from exc
    if any(not isinstance(item, PermissionRequirement) for item in values):
        raise ExecutionValidationError(
            "permission_requirements must contain PermissionRequirement values"
        )
    grant_ids = [item.grant_id for item in values]
    if len(grant_ids) != len(set(grant_ids)):
        raise ExecutionValidationError(
            "permission_requirements cannot repeat a grant_id"
        )
    return values


def _verification_commands(value: Any) -> tuple[VerificationCommand, ...]:
    if isinstance(value, (str, bytes)):
        raise ExecutionValidationError(
            "verification_commands must contain VerificationCommand values"
        )
    try:
        values = tuple(value)
    except TypeError as exc:
        raise ExecutionValidationError(
            "verification_commands must contain VerificationCommand values"
        ) from exc
    if any(not isinstance(item, VerificationCommand) for item in values):
        raise ExecutionValidationError(
            "verification_commands must contain VerificationCommand values"
        )
    return values


@dataclass(frozen=True, slots=True)
class TaskExecutionSpec:
    """The complete bounded runtime and verification contract for one task."""

    profile: TaskProfile
    instructions: str
    workspace: Path
    runtime_capabilities: frozenset[Capability]
    toolsets: tuple[str, ...]
    skills: tuple[str, ...]
    isolation: IsolationMode
    permission_requirements: tuple[PermissionRequirement, ...]
    verification_commands: tuple[VerificationCommand, ...]
    require_changes: bool = True
    baseline_ref: str = "HEAD"
    material_ambiguity: str = ""
    ambiguity_question: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.profile, TaskProfile):
            raise ExecutionValidationError("profile must be a TaskProfile")
        object.__setattr__(self, "instructions", _non_empty_string(self.instructions, "instructions"))
        object.__setattr__(self, "workspace", _path(self.workspace, "workspace"))
        capabilities = _capability_set(self.runtime_capabilities)
        object.__setattr__(self, "runtime_capabilities", capabilities)
        object.__setattr__(self, "toolsets", _string_tuple(self.toolsets, "toolsets"))
        object.__setattr__(self, "skills", _string_tuple(self.skills, "skills"))
        object.__setattr__(self, "isolation", _coerce_isolation(self.isolation))
        requirements = _permission_requirements(self.permission_requirements)
        object.__setattr__(self, "permission_requirements", requirements)
        object.__setattr__(
            self,
            "verification_commands",
            _verification_commands(self.verification_commands),
        )
        if not isinstance(self.require_changes, bool):
            raise ExecutionValidationError("require_changes must be a boolean")
        object.__setattr__(
            self, "baseline_ref", _non_empty_string(self.baseline_ref, "baseline_ref")
        )
        object.__setattr__(self, "material_ambiguity", _string(self.material_ambiguity, "material_ambiguity"))
        object.__setattr__(self, "ambiguity_question", _string(self.ambiguity_question, "ambiguity_question"))

        if Capability.RUNTIME_MEMORY_WRITE in capabilities:
            raise ExecutionValidationError(
                "RUNTIME_MEMORY_WRITE is forbidden in this execution slice"
            )
        expected_capabilities = frozenset(capability.value for capability in capabilities)
        if self.profile.required_capabilities != expected_capabilities:
            raise ExecutionValidationError(
                "profile.required_capabilities must exactly match runtime_capabilities"
            )
        if self.profile.required_tools != frozenset(self.toolsets):
            raise ExecutionValidationError(
                "profile.required_tools must exactly match toolsets"
            )
        if self.material_ambiguity and not self.ambiguity_question.strip():
            raise ExecutionValidationError(
                "ambiguity_question is required when material_ambiguity is present"
            )

        requirement_actions = {requirement.action for requirement in requirements}
        if (
            Capability.WORKSPACE_WRITE in capabilities
            and PermissionAction.WRITE_WORKSPACE not in requirement_actions
        ):
            raise ExecutionValidationError(
                "WORKSPACE_WRITE requires an exact WRITE_WORKSPACE permission requirement"
            )
        if (
            Capability.WORKSPACE_EXECUTE in capabilities
            and PermissionAction.EXECUTE_WORKSPACE not in requirement_actions
        ):
            raise ExecutionValidationError(
                "WORKSPACE_EXECUTE requires an exact EXECUTE_WORKSPACE permission requirement"
            )


def _validate_spec_for_task(spec: TaskExecutionSpec, task: Task) -> None:
    if not isinstance(task, Task):
        raise ExecutionValidationError("task must be a Task")
    if not isinstance(spec, TaskExecutionSpec):
        raise ExecutionValidationError("task specification must be a TaskExecutionSpec")
    if spec.profile.task_id != task.task_id:
        raise ExecutionValidationError(
            "task execution profile task_id does not match the mission task"
        )
    expected_objective = task.description if task.description else task.title
    if spec.profile.objective != expected_objective:
        raise ExecutionValidationError(
            "task execution profile objective does not match the mission task"
        )


class TaskSpecProvider(Protocol):
    """Resolve one immutable execution specification for a mission task."""

    def get(self, task: Task) -> TaskExecutionSpec:
        """Return the specification for ``task``."""


TaskExecutionSpecProvider = TaskSpecProvider


class MappingTaskSpecProvider:
    """A deterministic task-id keyed provider used by the coordinator."""

    def __init__(self, specs: Mapping[str, TaskExecutionSpec]) -> None:
        if not isinstance(specs, Mapping):
            raise ExecutionValidationError("specs must be a mapping")
        normalized: dict[str, TaskExecutionSpec] = {}
        for task_id, spec in specs.items():
            key = _non_empty_string(task_id, "task_id")
            if not isinstance(spec, TaskExecutionSpec):
                raise ExecutionValidationError(
                    "specs must contain TaskExecutionSpec values"
                )
            if spec.profile.task_id != key:
                raise ExecutionValidationError(
                    "spec profile task_id must match its mapping key"
                )
            normalized[key] = spec
        self._specs = normalized

    def get(self, task: Task) -> TaskExecutionSpec:
        if not isinstance(task, Task):
            raise ExecutionValidationError("task must be a Task")
        try:
            spec = self._specs[task.task_id]
        except KeyError as exc:
            raise TaskSpecNotFoundError(task.task_id) from exc
        _validate_spec_for_task(spec, task)
        return spec

    resolve = get


@runtime_checkable
class Runtime(Protocol):
    """The only runtime surface exposed to this package."""

    def run(self, job: RuntimeJob) -> RuntimeResult:
        """Execute one already-authorized runtime job."""


class RuntimeResolver(Protocol):
    """Resolve private route identifiers to opaque runtime objects."""

    def resolve(self, route_id: str) -> Runtime:
        """Return the runtime for a private route."""


class MappingRuntimeResolver:
    """A private route-id to runtime mapping with typed missing-route errors."""

    def __init__(self, runtimes: Mapping[str, Runtime]) -> None:
        if not isinstance(runtimes, Mapping):
            raise ExecutionValidationError("runtimes must be a mapping")
        normalized: dict[str, Runtime] = {}
        for route_id, runtime in runtimes.items():
            key = _non_empty_string(route_id, "route_id")
            if not callable(getattr(runtime, "run", None)):
                raise ExecutionValidationError(
                    "runtimes must contain values implementing run(RuntimeJob)"
                )
            normalized[key] = runtime
        self._runtimes = normalized

    def resolve(self, route_id: str) -> Runtime:
        key = _non_empty_string(route_id, "route_id")
        try:
            return self._runtimes[key]
        except KeyError as exc:
            raise RuntimeResolutionError(key) from exc

    get = resolve


class CoordinatorStatus(StrEnum):
    """The semantic outcome of one coordinator tick."""

    TASK_COMPLETED = "task_completed"
    MISSION_COMPLETED = "mission_completed"
    WAITING_FOR_USER = "waiting_for_user"
    NO_WORK = "no_work"
    BUSY = "busy"
    RETRY_EXHAUSTED = "retry_exhausted"
    UNKNOWN_OUTCOME = "unknown_outcome"


@dataclass(frozen=True, slots=True)
class CoordinatorResult:
    """A provider/model-agnostic result suitable for a semantic caller."""

    mission_id: str
    status: CoordinatorStatus
    summary: str
    task_id: str | None = None
    attempt_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "mission_id", _non_empty_string(self.mission_id, "mission_id"))
        if not isinstance(self.status, CoordinatorStatus):
            try:
                object.__setattr__(self, "status", CoordinatorStatus(self.status))
            except (TypeError, ValueError) as exc:
                raise ExecutionValidationError("status must be a CoordinatorStatus") from exc
        object.__setattr__(self, "summary", sanitize_summary(self.summary))
        if not self.summary:
            raise ExecutionValidationError("summary must be a non-empty string")
        if not isinstance(self.task_id, (str, type(None))):
            raise ExecutionValidationError("task_id must be a string or None")
        if not isinstance(self.attempt_id, (str, type(None))):
            raise ExecutionValidationError("attempt_id must be a string or None")
        if self.task_id is not None and not self.task_id.strip():
            raise ExecutionValidationError("task_id must be non-empty when provided")
        if self.attempt_id is not None and not self.attempt_id.strip():
            raise ExecutionValidationError(
                "attempt_id must be non-empty when provided"
            )


def _runtime_result_status(result: Any) -> RuntimeStatus | None:
    if not isinstance(result, RuntimeResult):
        return None
    if isinstance(result.status, RuntimeStatus):
        return result.status
    try:
        return RuntimeStatus(result.status)
    except (TypeError, ValueError):
        return None


def _runtime_metrics(result: RuntimeResult, latency_ms: int) -> tuple[int, float, int]:
    total_tokens = _nonnegative_metric(getattr(result, "total_tokens", None), 0)
    if not isinstance(total_tokens, int):
        total_tokens = 0
    estimated_cost = _nonnegative_metric(
        getattr(result, "estimated_cost_usd", None), 0.0
    )
    if not isinstance(estimated_cost, (int, float)):
        estimated_cost = 0.0
    return total_tokens, float(estimated_cost), max(0, int(latency_ms))


class ExecutionCoordinator:
    """Run at most one mission task's bounded execution sequence per tick."""

    def __init__(
        self,
        mission_service: MissionService,
        role_charter: RoleCharter,
        workforce_compiler: WorkforceCompiler,
        model_router: ModelRouter,
        task_spec_provider: TaskSpecProvider,
        runtime_resolver: RuntimeResolver,
        workspace_verifier: WorkspaceVerifier,
        lease_owner: str,
        lease_seconds: float,
        max_attempts: int,
    ) -> None:
        if not isinstance(role_charter, RoleCharter):
            raise ExecutionValidationError("role_charter must be a RoleCharter")
        if not callable(getattr(workforce_compiler, "compile", None)):
            raise ExecutionValidationError("workforce_compiler must provide compile")
        if not callable(getattr(model_router, "select", None)):
            raise ExecutionValidationError("model_router must provide select")
        if not callable(getattr(task_spec_provider, "get", None)):
            raise ExecutionValidationError("task_spec_provider must provide get")
        if not callable(
            getattr(runtime_resolver, "resolve", None)
        ) and not callable(getattr(runtime_resolver, "get", None)):
            raise ExecutionValidationError(
                "runtime_resolver must provide resolve or get"
            )
        if not callable(getattr(workspace_verifier, "verify", None)):
            raise ExecutionValidationError("workspace_verifier must provide verify")
        self.mission_service = mission_service
        self.role_charter = role_charter
        self.workforce_compiler = workforce_compiler
        self.model_router = model_router
        self.task_spec_provider = task_spec_provider
        self.runtime_resolver = runtime_resolver
        self.workspace_verifier = workspace_verifier
        self.lease_owner = _non_empty_string(lease_owner, "lease_owner")
        self.lease_seconds = _positive_number(lease_seconds, "lease_seconds")
        self.max_attempts = _positive_int(max_attempts, "max_attempts")

    def run_once(self, mission_id: str) -> CoordinatorResult:
        """Recover durable state, execute eligible work, and return one outcome."""

        mission_id = _non_empty_string(mission_id, "mission_id")
        recovery = self._recover(mission_id)
        if recovery is not None:
            return recovery

        mission = self.mission_service.get_mission(mission_id)
        if mission.state is not MissionState.ACTIVE:
            return self._safe_no_task_result(mission)
        stranded = self._stranded_tasks(mission_id)
        if len(stranded) > 1:
            return self._result(
                mission_id,
                CoordinatorStatus.BUSY,
                "Multiple stranded tasks require serialized recovery.",
            )

        task: Task | None
        if stranded:
            task = stranded[0]
            if task.state is TaskStatus.VERIFYING:
                task = self.mission_service.start_task(task.task_id)
        else:
            task = self.mission_service.select_next_task(mission_id)

        if task is None:
            mission = self.mission_service.get_mission(mission_id)
            if mission.state is MissionState.ACTIVE and self._all_tasks_completed(
                mission_id
            ):
                return self._complete_mission(mission_id)
            return self._safe_no_task_result(mission)

        return self._execute_task(mission_id, task)

    def _recover(self, mission_id: str) -> CoordinatorResult | None:
        attempts = self.mission_service.list_attempts(mission_id)
        now = utc_now()
        for attempt in attempts:
            if attempt.status not in {AttemptStatus.RUNNING, AttemptStatus.VERIFYING}:
                continue
            if attempt.lease_expires_at is None or attempt.lease_expires_at > now:
                continue
            self.mission_service.mark_expired_attempt_unknown(
                attempt.attempt_id,
                expected_revision=attempt.revision,
                at=now,
            )

        attempts = self.mission_service.list_attempts(mission_id)
        unknown = [attempt for attempt in attempts if attempt.status is AttemptStatus.UNKNOWN]
        if unknown:
            attempt = unknown[-1]
            return self._result(
                mission_id,
                CoordinatorStatus.UNKNOWN_OUTCOME,
                "A prior runtime outcome is unknown and requires reconciliation.",
                task_id=attempt.task_id,
                attempt_id=attempt.attempt_id,
            )

        live = [
            attempt
            for attempt in attempts
            if attempt.status in {AttemptStatus.RUNNING, AttemptStatus.VERIFYING}
            and attempt.lease_expires_at is not None
            and attempt.lease_expires_at > now
        ]
        if live:
            attempt = live[0]
            return self._result(
                mission_id,
                CoordinatorStatus.BUSY,
                "A leased task attempt is already running.",
                task_id=attempt.task_id,
                attempt_id=attempt.attempt_id,
            )

        # A created attempt is a narrow crash window between durable creation and
        # claim.  It has no lease to recover, so leave it untouched and serialize
        # the mission until a caller reconciles or cleans up that state.
        created = [attempt for attempt in attempts if attempt.status is AttemptStatus.CREATED]
        if created:
            attempt = created[0]
            return self._result(
                mission_id,
                CoordinatorStatus.BUSY,
                "A durable task attempt is awaiting claim.",
                task_id=attempt.task_id,
                attempt_id=attempt.attempt_id,
            )
        return None

    def _stranded_tasks(self, mission_id: str) -> list[Task]:
        tasks = self._list_tasks(mission_id)
        stranded: list[Task] = []
        for task in tasks:
            if task.state not in {TaskStatus.IN_PROGRESS, TaskStatus.VERIFYING}:
                continue
            attempts = self.mission_service.list_attempts(mission_id, task.task_id)
            if all(attempt.status in {
                AttemptStatus.SUCCEEDED,
                AttemptStatus.FAILED,
                AttemptStatus.INTERRUPTED,
            } for attempt in attempts):
                stranded.append(task)
        return stranded

    def _execute_task(self, mission_id: str, task: Task) -> CoordinatorResult:
        spec = self.task_spec_provider.get(task)
        _validate_spec_for_task(spec, task)

        if spec.material_ambiguity:
            self._escalate_once(
                mission_id,
                task.task_id,
                title="Clarification required",
                reason=sanitize_summary(spec.material_ambiguity),
                impact="The task is paused until the ambiguity is resolved.",
                requested_action=sanitize_summary(spec.ambiguity_question),
            )
            return self._result(
                mission_id,
                CoordinatorStatus.WAITING_FOR_USER,
                "The task is waiting for clarification before execution.",
                task_id=task.task_id,
            )

        mission = self.mission_service.get_mission(mission_id)
        available_catalog = {
            capability.value: spec.toolsets for capability in spec.runtime_capabilities
        }
        envelope = self.workforce_compiler.compile(
            self.role_charter,
            mission,
            spec.profile,
            available_catalog if available_catalog else spec.runtime_capabilities,
        )
        if not isinstance(envelope, WorkerEnvelope):
            raise ExecutionValidationError("workforce compiler must return WorkerEnvelope")
        expected_objective = task.description if task.description else task.title
        if envelope.objective != expected_objective:
            raise ExecutionValidationError("compiled envelope changed task objective")

        attempts = self.mission_service.list_attempts(mission_id, task.task_id)
        excluded = {
            attempt.route_id
            for attempt in attempts
            if attempt.status in {AttemptStatus.FAILED, AttemptStatus.INTERRUPTED}
        }
        allowed_attempts = min(self.max_attempts, envelope.max_attempts)
        attempt_count = len(attempts)
        if attempt_count >= allowed_attempts:
            return self._retry_exhausted(mission_id, task.task_id)

        last_attempt_id: str | None = None
        while attempt_count < allowed_attempts:
            try:
                decision = self.model_router.select(
                    spec.profile,
                    excluded_route_ids=excluded,
                )
            except NoEligibleRouteError:
                return self._retry_exhausted(
                    mission_id, task.task_id, attempt_id=last_attempt_id
                )

            missing = self._missing_permission(mission_id, spec.permission_requirements)
            if missing is not None:
                self._escalate_permission(mission_id, task.task_id, missing)
                return self._result(
                    mission_id,
                    CoordinatorStatus.WAITING_FOR_USER,
                    "Execution is waiting for the required authority.",
                    task_id=task.task_id,
                )

            ordinal = attempt_count + 1
            idempotency_key = (
                f"attempt:{mission_id}:{task.task_id}:{decision.route_id}:{ordinal}"
            )
            attempt = self.mission_service.create_attempt(
                mission_id,
                task.task_id,
                idempotency_key,
                worker_role_id=envelope.envelope_id,
                route_id=decision.route_id,
                quality_floor=envelope.quality_floor,
            )
            claimed = self.mission_service.claim_attempt(
                attempt.attempt_id,
                self.lease_owner,
                lease_seconds=self.lease_seconds,
            )
            last_attempt_id = claimed.attempt_id
            current_task = self.mission_service.get_task(task.task_id)
            if current_task.state in {TaskStatus.READY, TaskStatus.VERIFYING}:
                current_task = self.mission_service.start_task(current_task.task_id)

            authorization_error = self._authorize_requirements(
                mission_id, current_task, spec.permission_requirements
            )
            if authorization_error is not None:
                self.mission_service.interrupt_attempt(
                    claimed.attempt_id,
                    reason=authorization_error,
                    lease_owner=self.lease_owner,
                    fencing_token=claimed.fencing_token,
                )
                self._escalate_permission(
                    mission_id,
                    task.task_id,
                    None,
                    detail=authorization_error,
                )
                return self._result(
                    mission_id,
                    CoordinatorStatus.WAITING_FOR_USER,
                    "Execution is waiting for the required authority.",
                    task_id=task.task_id,
                    attempt_id=claimed.attempt_id,
                )

            runtime_job = RuntimeJob(
                mission_id=mission_id,
                task_id=task.task_id,
                objective=(task.description if task.description else task.title),
                instructions=spec.instructions,
                workspace=spec.workspace,
                toolsets=spec.toolsets,
                skills=spec.skills,
                capabilities=spec.runtime_capabilities,
                isolation=spec.isolation,
            )
            started = time.monotonic()
            runtime = self._resolve_runtime(decision.route_id)
            try:
                runtime_result = runtime.run(runtime_job)
            except Exception:  # noqa: BLE001 - runtime effects may be unknown
                return self._result(
                    mission_id,
                    CoordinatorStatus.UNKNOWN_OUTCOME,
                    "The runtime outcome is unknown; the leased attempt remains recoverable.",
                    task_id=task.task_id,
                    attempt_id=claimed.attempt_id,
                )
            latency_ms = max(0, round((time.monotonic() - started) * 1000))

            status = _runtime_result_status(runtime_result)
            if not isinstance(runtime_result, RuntimeResult) or (
                runtime_result.mission_id != mission_id
                or runtime_result.task_id != task.task_id
            ):
                status = RuntimeStatus.UNSTRUCTURED

            total_tokens, estimated_cost, latency_ms = _runtime_metrics(
                runtime_result if isinstance(runtime_result, RuntimeResult) else RuntimeResult(
                    mission_id=mission_id,
                    task_id=task.task_id,
                    status=RuntimeStatus.UNSTRUCTURED,
                    response="",
                    exit_code=1,
                ),
                latency_ms,
            )

            if status is RuntimeStatus.NEEDS_USER:
                response = sanitize_summary(
                    runtime_result.response,
                    fallback="The runtime needs user input before it can continue.",
                )
                if not response:
                    response = "The runtime needs user input before it can continue."
                self.mission_service.interrupt_attempt(
                    claimed.attempt_id,
                    reason=response,
                    lease_owner=self.lease_owner,
                    fencing_token=claimed.fencing_token,
                )
                self._escalate_once(
                    mission_id,
                    task.task_id,
                    title="Runtime needs user input",
                    reason=response,
                    impact="The task cannot continue until the requested input is provided.",
                    requested_action=response,
                )
                return self._result(
                    mission_id,
                    CoordinatorStatus.WAITING_FOR_USER,
                    response,
                    task_id=task.task_id,
                    attempt_id=claimed.attempt_id,
                )

            if status is not RuntimeStatus.COMPLETED:
                failure_summary = sanitize_summary(
                    getattr(runtime_result, "response", ""),
                    fallback="The runtime did not produce a usable result.",
                )
                if not failure_summary:
                    failure_summary = "The runtime did not produce a usable result."
                self.mission_service.fail_attempt(
                    claimed.attempt_id,
                    error_summary=failure_summary,
                    result_summary=failure_summary,
                    total_tokens=total_tokens,
                    estimated_cost_usd=estimated_cost,
                    latency_ms=latency_ms,
                    lease_owner=self.lease_owner,
                    fencing_token=claimed.fencing_token,
                )
                self._record_observation(
                    decision.route_id,
                    spec.profile,
                    accepted=False,
                    total_tokens=total_tokens,
                    cost_usd=estimated_cost,
                    latency_ms=latency_ms,
                )
                excluded.add(decision.route_id)
                attempt_count += 1
                continue

            verification = self._verify_candidate(
                mission_id,
                task,
                spec,
                claimed,
                decision.route_id,
                total_tokens,
                estimated_cost,
                latency_ms,
            )
            if verification is not None:
                if verification.status is CoordinatorStatus.TASK_COMPLETED:
                    return verification
                if verification.status is CoordinatorStatus.MISSION_COMPLETED:
                    return verification
                if verification.status is CoordinatorStatus.WAITING_FOR_USER:
                    return verification
                # A rejected verification is represented by None after its
                # durable fail/observation/task reset; continue to fallback.
                excluded.add(decision.route_id)
                attempt_count += 1
                continue

            # This branch is unreachable with the current verifier helper but
            # retains the loop's retry invariant if the helper evolves.
            excluded.add(decision.route_id)
            attempt_count += 1

        return self._retry_exhausted(
            mission_id, task.task_id, attempt_id=last_attempt_id
        )

    def _resolve_runtime(self, route_id: str) -> Runtime:
        resolver = self.runtime_resolver
        resolve = getattr(resolver, "resolve", None)
        if callable(resolve):
            return resolve(route_id)
        get = getattr(resolver, "get", None)
        if callable(get):
            try:
                return get(route_id)
            except KeyError as exc:
                raise RuntimeResolutionError(route_id) from exc
        raise RuntimeResolutionError(route_id)

    def _authorize_requirements(
        self,
        mission_id: str,
        task: Task,
        requirements: Sequence[PermissionRequirement],
    ) -> str | None:
        for requirement in requirements:
            key = (
                f"authority:{mission_id}:{task.task_id}:{requirement.grant_id}:"
                f"{requirement.action.value}:{requirement.resource}"
            )
            try:
                self.mission_service.authorize_action(
                    mission_id,
                    requirement.grant_id,
                    requirement.action,
                    requirement.resource,
                    idempotency_key=key,
                    action_count=requirement.action_count,
                    spent_cents=requirement.spent_cents,
                )
            except Exception:  # noqa: BLE001 - exact authority failure is recoverable
                return sanitize_summary(
                    f"Required authority could not be authorized for "
                    f"{requirement.action.value} on {requirement.resource}.",
                    fallback="Required authority could not be authorized.",
                )
        return None

    def _missing_permission(
        self,
        mission_id: str,
        requirements: Sequence[PermissionRequirement],
    ) -> PermissionRequirement | None:
        for requirement in requirements:
            if not self.mission_service.has_permission(
                mission_id, requirement.action, requirement.resource
            ):
                return requirement
        return None

    def _verify_candidate(
        self,
        mission_id: str,
        task: Task,
        spec: TaskExecutionSpec,
        attempt: TaskAttempt,
        route_id: str,
        total_tokens: int,
        estimated_cost: float,
        latency_ms: int,
    ) -> CoordinatorResult | None:
        try:
            self.mission_service.begin_attempt_verification(
                attempt.attempt_id,
                lease_owner=self.lease_owner,
                fencing_token=attempt.fencing_token,
            )
            self.mission_service.begin_task_verification(task.task_id)
            verification = self.workspace_verifier.verify(
                WorkspaceVerificationRequest(
                    workspace=spec.workspace,
                    commands=spec.verification_commands,
                    require_changes=spec.require_changes,
                    baseline_ref=spec.baseline_ref,
                )
            )
            artifacts = tuple(getattr(verification, "artifacts", ()))
            persisted_evidence: list[Evidence] = []
            for artifact in artifacts:
                if not isinstance(artifact, VerificationArtifact):
                    raise ExecutionValidationError(
                        "workspace verifier returned an invalid artifact"
                    )
                record = self.mission_service.record_artifact(
                    mission_id,
                    artifact.name,
                    artifact.locator,
                    kind=artifact.artifact_kind,
                    task_id=task.task_id,
                )
                evidence = self.mission_service.record_evidence(
                    mission_id,
                    sanitize_summary(
                        artifact.summary,
                        fallback="Verified workspace artifact.",
                    )
                    or "Verified workspace artifact.",
                    kind=artifact.evidence_kind,
                    artifact_id=record.artifact_id,
                    task_id=task.task_id,
                    locator=artifact.locator,
                )
                persisted_evidence.append(evidence)

            accepted = bool(getattr(verification, "accepted", False))
            verified_count = 0
            if accepted:
                for evidence in persisted_evidence:
                    verified = self.mission_service.verify_evidence(
                        evidence.evidence_id,
                        _VERIFICATION_METHOD,
                    )
                    if getattr(verified, "verified_at", None) is not None:
                        verified_count += 1
            accepted = accepted and bool(artifacts) and verified_count > 0
            if not accepted:
                summary = sanitize_summary(
                    getattr(verification, "summary", ""),
                    fallback="Independent workspace verification rejected the result.",
                )
                if not summary:
                    summary = "Independent workspace verification rejected the result."
                self._fail_verification(
                    mission_id,
                    task,
                    spec.profile,
                    attempt,
                    route_id,
                    summary,
                    total_tokens,
                    estimated_cost,
                    latency_ms,
                )
                return None

            summary = sanitize_summary(
                getattr(verification, "summary", ""),
                fallback="Independent workspace verification accepted the result.",
            )
            if not summary:
                summary = "Independent workspace verification accepted the result."
            self.mission_service.succeed_attempt(
                attempt.attempt_id,
                result_summary=summary,
                total_tokens=total_tokens,
                estimated_cost_usd=estimated_cost,
                latency_ms=latency_ms,
                lease_owner=self.lease_owner,
                fencing_token=attempt.fencing_token,
            )
            self._record_observation(
                route_id,
                spec.profile,
                accepted=True,
                total_tokens=total_tokens,
                cost_usd=estimated_cost,
                latency_ms=latency_ms,
            )
            self.mission_service.complete_task(task.task_id)
            self.mission_service.record_checkpoint(
                mission_id,
                CheckpointType.FIRST_USABLE_SLICE,
                "Task completed with independently verified workspace evidence.",
                task_id=task.task_id,
            )
            if self._all_tasks_completed(mission_id):
                return self._complete_mission(mission_id)
            return self._result(
                mission_id,
                CoordinatorStatus.TASK_COMPLETED,
                summary,
                task_id=task.task_id,
                attempt_id=attempt.attempt_id,
            )
        except Exception:  # noqa: BLE001 - verifier failures must be retryable
            self._fail_verification(
                mission_id,
                task,
                spec.profile,
                attempt,
                route_id,
                "Independent workspace verification failed.",
                total_tokens,
                estimated_cost,
                latency_ms,
            )
            return None

    def _fail_verification(
        self,
        mission_id: str,
        task: Task,
        profile: TaskProfile,
        attempt: TaskAttempt,
        route_id: str,
        summary: str,
        total_tokens: int,
        estimated_cost: float,
        latency_ms: int,
    ) -> None:
        current_attempt = self.mission_service.get_attempt(attempt.attempt_id)
        if current_attempt.status in {AttemptStatus.RUNNING, AttemptStatus.VERIFYING}:
            self.mission_service.fail_attempt(
                attempt.attempt_id,
                error_summary=sanitize_summary(summary),
                result_summary=sanitize_summary(summary),
                total_tokens=total_tokens,
                estimated_cost_usd=estimated_cost,
                latency_ms=latency_ms,
                lease_owner=self.lease_owner,
                fencing_token=attempt.fencing_token,
            )
        self._record_observation(
            route_id,
            profile,
            accepted=False,
            total_tokens=total_tokens,
            cost_usd=estimated_cost,
            latency_ms=latency_ms,
        )
        current_task = self.mission_service.get_task(task.task_id)
        if current_task.state is TaskStatus.VERIFYING:
            self.mission_service.start_task(task.task_id)

    def _record_observation(
        self,
        route_id: str,
        profile: TaskProfile,
        *,
        accepted: bool,
        total_tokens: int,
        cost_usd: float,
        latency_ms: int,
    ) -> None:
        self.model_router.record_observation(
            RouteObservation(
                route_id=route_id,
                task_class=profile.task_class,
                accepted=accepted,
                total_tokens=total_tokens,
                cost_usd=cost_usd,
                latency_ms=latency_ms,
            )
        )

    def _complete_mission(self, mission_id: str) -> CoordinatorResult:
        tasks = self._list_tasks(mission_id)
        if not tasks:
            return self._result(
                mission_id,
                CoordinatorStatus.NO_WORK,
                "The mission has no tasks to complete.",
            )
        task_evidence = [
            evidence
            for evidence in self._list_evidence(mission_id)
            if evidence.task_id is not None and evidence.verified_at is not None
        ]
        if not task_evidence or any(
            not any(
                evidence.task_id == task.task_id
                and evidence.verified_at is not None
                for evidence in task_evidence
            )
            for task in tasks
        ):
            return self._result(
                mission_id,
                CoordinatorStatus.NO_WORK,
                "Mission completion is blocked until every task has verified evidence.",
            )

        coverage = next(
            (
                evidence
                for evidence in self._list_evidence(mission_id)
                if evidence.task_id is None
                and evidence.kind is EvidenceKind.REQUIREMENT_COVERAGE
            ),
            None,
        )
        evidence_ids = ",".join(
            sorted(evidence.evidence_id for evidence in task_evidence)
        )
        locator = f"verified-task-evidence://aggregate/{evidence_ids}"
        if coverage is None:
            coverage = self.mission_service.record_evidence(
                mission_id,
                "All completed tasks have independently verified evidence.",
                kind=EvidenceKind.REQUIREMENT_COVERAGE,
                locator=locator,
            )
        if coverage.verified_at is None:
            coverage = self.mission_service.verify_evidence(
                coverage.evidence_id,
                _VERIFICATION_METHOD,
            )

        mission = self.mission_service.get_mission(mission_id)
        if mission.state is MissionState.ACTIVE:
            self.mission_service.begin_verification(mission_id)
        mission = self.mission_service.get_mission(mission_id)
        if mission.state is MissionState.VERIFYING:
            self.mission_service.complete_mission(mission_id)
        return self._result(
            mission_id,
            CoordinatorStatus.MISSION_COMPLETED,
            "Mission completed with independently verified task evidence.",
        )

    def _retry_exhausted(
        self,
        mission_id: str,
        task_id: str,
        *,
        attempt_id: str | None = None,
    ) -> CoordinatorResult:
        self._escalate_once(
            mission_id,
            task_id,
            title="Technical blocker",
            reason="No permitted execution route can produce an accepted result within the attempt limit.",
            impact="The task is paused rather than being reported as complete without evidence.",
            requested_action="Choose a route, revise the task constraints, or provide guidance to continue.",
        )
        return self._result(
            mission_id,
            CoordinatorStatus.RETRY_EXHAUSTED,
            "Execution attempts were exhausted; user guidance is required.",
            task_id=task_id,
            attempt_id=attempt_id,
        )

    def _escalate_permission(
        self,
        mission_id: str,
        task_id: str,
        requirement: PermissionRequirement | None,
        *,
        detail: str | None = None,
    ) -> None:
        if requirement is not None:
            action = requirement.action.value
            resource = requirement.resource
            reason = f"The task requires {action} authority for {resource}."
            requested_action = f"Approve {action} for {resource}."
        else:
            reason = detail or "The exact requested authority could not be authorized."
            requested_action = "Approve the exact authority needed for this task."
        self._escalate_once(
            mission_id,
            task_id,
            title="Permission required",
            reason=sanitize_summary(reason),
            impact="Execution is paused until the exact authority is available.",
            requested_action=sanitize_summary(requested_action),
        )

    def _escalate_once(
        self,
        mission_id: str,
        task_id: str,
        *,
        title: str,
        reason: str,
        impact: str,
        requested_action: str,
    ) -> None:
        for escalation in self._list_open_escalations(mission_id):
            if escalation.task_id == task_id and escalation.title == title:
                return
        self.mission_service.escalate(
            mission_id,
            title,
            sanitize_summary(reason) or "Execution requires user guidance.",
            sanitize_summary(impact) or "The task is paused.",
            requested_action=sanitize_summary(requested_action)
            or "Provide guidance to continue.",
            task_id=task_id,
        )

    def _list_tasks(self, mission_id: str) -> tuple[Task, ...]:
        store = getattr(self.mission_service, "store", None)
        list_tasks = getattr(store, "list_tasks", None)
        if callable(list_tasks):
            return tuple(list_tasks(mission_id))
        status = self.mission_service.get_status(mission_id)
        return tuple(status.tasks)

    def _list_evidence(self, mission_id: str) -> tuple[Evidence, ...]:
        store = getattr(self.mission_service, "store", None)
        list_evidence = getattr(store, "list_evidence", None)
        if callable(list_evidence):
            return tuple(list_evidence(mission_id))
        values = getattr(self.mission_service, "list_evidence", None)
        if callable(values):
            return tuple(values(mission_id))
        return ()

    def _list_open_escalations(self, mission_id: str) -> tuple[Any, ...]:
        store = getattr(self.mission_service, "store", None)
        list_escalations = getattr(store, "list_escalations", None)
        if callable(list_escalations):
            return tuple(list_escalations(mission_id, EscalationStatus.OPEN))
        return ()

    def _all_tasks_completed(self, mission_id: str) -> bool:
        tasks = self._list_tasks(mission_id)
        return bool(tasks) and all(task.state is TaskStatus.COMPLETED for task in tasks)

    def _safe_no_task_result(self, mission: Mission) -> CoordinatorResult:
        if mission.state is MissionState.WAITING_FOR_USER:
            return self._result(
                mission.mission_id,
                CoordinatorStatus.WAITING_FOR_USER,
                "The mission is waiting for user guidance.",
            )
        if mission.state is MissionState.COMPLETED:
            return self._result(
                mission.mission_id,
                CoordinatorStatus.MISSION_COMPLETED,
                "The mission is already complete.",
            )
        return self._result(
            mission.mission_id,
            CoordinatorStatus.NO_WORK,
            "There is no executable task available.",
        )

    @staticmethod
    def _result(
        mission_id: str,
        status: CoordinatorStatus,
        summary: str,
        *,
        task_id: str | None = None,
        attempt_id: str | None = None,
    ) -> CoordinatorResult:
        return CoordinatorResult(
            mission_id=mission_id,
            status=status,
            summary=sanitize_summary(summary),
            task_id=task_id,
            attempt_id=attempt_id,
        )


__all__ = [
    "CoordinatorResult",
    "CoordinatorStatus",
    "ExecutionCoordinator",
    "ExecutionError",
    "ExecutionValidationError",
    "MappingRuntimeResolver",
    "MappingTaskSpecProvider",
    "MissingRuntimeRouteError",
    "PermissionRequirement",
    "Runtime",
    "RuntimeResolutionError",
    "RuntimeResolver",
    "TaskExecutionSpec",
    "TaskExecutionSpecProvider",
    "TaskSpecNotFoundError",
    "TaskSpecProvider",
    "TaskSpecificationNotFoundError",
    "sanitize_summary",
]

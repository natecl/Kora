"""Public contracts between Kora's control plane and an execution runtime.

These records deliberately contain mission and authority data without exposing
runtime-specific models, providers, prompts, or worker topology to product
surfaces.
"""

from __future__ import annotations

from dataclasses import InitVar, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from math import isfinite
from pathlib import Path
from typing import Any, Callable, Protocol

from kora._workspace import WorkspaceIdentity, WorkspaceIdentityError
from kora._process_local import attach as attach_process_local
from kora._process_local import get as get_process_local
from kora._process_local import invoke as invoke_process_local


class RuntimeContractError(ValueError):
    """A runtime contract is missing or contains invalid Kora data."""


class LiveFenceValidator(Protocol):
    """Kora-owned process-local validation immediately before an effect."""

    def __call__(self, ticket: "ExecutionFenceTicket") -> object: ...


def _non_empty(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeContractError(f"{field_name} must be a non-empty string")
    return value


def _timestamp(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise RuntimeContractError(f"{field_name} must be a datetime")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class ExecutionFenceTicket:
    """A Kora-issued lease/fence credential carried into runtime work."""

    attempt_id: str
    lease_owner: str
    fencing_token: int
    lease_expires_at: datetime
    cancellation_identity: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "attempt_id", _non_empty(self.attempt_id, "attempt_id"))
        object.__setattr__(
            self, "lease_owner", _non_empty(self.lease_owner, "lease_owner")
        )
        if (
            isinstance(self.fencing_token, bool)
            or not isinstance(self.fencing_token, int)
            or self.fencing_token < 0
        ):
            raise RuntimeContractError(
                "fencing_token must be a non-negative integer"
            )
        object.__setattr__(
            self,
            "lease_expires_at",
            _timestamp(self.lease_expires_at, "lease_expires_at"),
        )
        object.__setattr__(
            self,
            "cancellation_identity",
            _non_empty(self.cancellation_identity, "cancellation_identity"),
        )

    @property
    def expires_at(self) -> datetime:
        """Compatibility alias for callers that use the shorter name."""

        return self.lease_expires_at

    @property
    def cancellation_id(self) -> str:
        """Compatibility alias for the cancellation identity."""

        return self.cancellation_identity

    def is_active(self, at: datetime | None = None) -> bool:
        """Return whether this ticket still authorizes effect-bearing work."""

        moment = _timestamp(at or datetime.now(timezone.utc), "at")
        return self.lease_expires_at > moment

    def validate(
        self,
        *,
        attempt_id: str | None = None,
        cancellation_identity: str | None = None,
        at: datetime | None = None,
    ) -> "ExecutionFenceTicket":
        """Validate identity and lease freshness at the effect timestamp."""

        if attempt_id is not None and self.attempt_id != _non_empty(
            attempt_id, "attempt_id"
        ):
            raise RuntimeContractError("execution fence attempt_id does not match")
        if cancellation_identity is not None and self.cancellation_identity != _non_empty(
            cancellation_identity, "cancellation_identity"
        ):
            raise RuntimeContractError(
                "execution fence cancellation identity does not match"
            )
        if not self.is_active(at):
            raise RuntimeContractError("execution fence lease is no longer active")
        return self

    @classmethod
    def from_attempt(
        cls,
        attempt: object,
        *,
        cancellation_identity: str,
        at: datetime | None = None,
    ) -> "ExecutionFenceTicket":
        """Issue a ticket from an active Kora attempt projection."""

        attempt_id = _non_empty(getattr(attempt, "attempt_id", None), "attempt_id")
        lease_owner = _non_empty(
            getattr(attempt, "lease_owner", None), "lease_owner"
        )
        lease_expires_at = getattr(attempt, "lease_expires_at", None)
        if lease_expires_at is None:
            raise RuntimeContractError("attempt does not have an active lease")
        ticket = cls(
            attempt_id=attempt_id,
            lease_owner=lease_owner,
            fencing_token=getattr(attempt, "fencing_token", None),
            lease_expires_at=lease_expires_at,
            cancellation_identity=cancellation_identity,
        )
        return ticket.validate(at=at)

    issue = from_attempt


ExecutionFence = ExecutionFenceTicket
RuntimeFenceTicket = ExecutionFenceTicket
KoraExecutionFence = ExecutionFenceTicket


class Capability(StrEnum):
    """A capability Kora may grant to one runtime job."""

    NETWORK_READ = "network.read"
    WORKSPACE_READ = "workspace.read"
    WORKSPACE_WRITE = "workspace.write"
    WORKSPACE_EXECUTE = "workspace.execute"
    RUNTIME_MEMORY_WRITE = "runtime.memory.write"
    WORKER_DELEGATE = "worker.delegate"


class IsolationMode(StrEnum):
    """Where Hermes is allowed to execute a task."""

    READ_ONLY = "read_only"
    CLOUD_SANDBOX = "cloud_sandbox"


class RuntimeStatus(StrEnum):
    """Kora-level interpretation of a runtime result."""

    COMPLETED = "completed"
    NEEDS_USER = "needs_user"
    FAILED = "failed"
    UNSTRUCTURED = "unstructured"


@dataclass(frozen=True, slots=True, weakref_slot=True)
class RuntimeJob:
    """One task scoped to an already-approved Kora mission."""

    mission_id: str
    task_id: str
    objective: str
    instructions: str
    workspace: Path
    toolsets: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    capabilities: frozenset[Capability] = field(default_factory=frozenset)
    isolation: IsolationMode = IsolationMode.READ_ONLY
    timeout_seconds: float = 300.0
    session_id: str | None = None
    execution_fence: ExecutionFenceTicket | None = None
    live_fence_validator: InitVar[Callable[..., object] | None] = None
    _workspace_identity: WorkspaceIdentity | None = field(
        default=None,
        repr=False,
        compare=False,
        kw_only=True,
    )

    def __post_init__(
        self,
        live_fence_validator: Callable[..., object] | None,
    ) -> None:
        if self.execution_fence is not None and not isinstance(
            self.execution_fence, ExecutionFenceTicket
        ):
            raise RuntimeContractError(
                "execution_fence must be an ExecutionFenceTicket or None"
            )
        if live_fence_validator is not None:
            attach_process_local(self, live_fence_validator)
        provided_identity = self._workspace_identity
        if provided_identity is not None and not isinstance(
            provided_identity, WorkspaceIdentity
        ):
            raise RuntimeContractError(
                "_workspace_identity must be a WorkspaceIdentity or None"
            )
        try:
            if provided_identity is None:
                identity = WorkspaceIdentity.capture(self.workspace)
            else:
                provided_identity.assert_path(self.workspace)
                identity = provided_identity
        except WorkspaceIdentityError as exc:
            if provided_identity is not None:
                raise RuntimeContractError(
                    "workspace identity could not be carried safely"
                ) from exc
            # The adapter owns the final error for a missing/non-directory
            # workspace.  Existing directories are bound to their real target
            # here when the private descriptor primitive is available.
            try:
                workspace = Path(self.workspace).expanduser()
                if workspace.exists():
                    object.__setattr__(
                        self,
                        "workspace",
                        workspace.resolve(strict=True),
                    )
            except (OSError, RuntimeError, TypeError, ValueError):
                pass
        else:
            object.__setattr__(self, "workspace", identity.canonical_path)
            object.__setattr__(self, "_workspace_identity", identity)
        if isinstance(self.timeout_seconds, bool) or not isinstance(
            self.timeout_seconds, (int, float)
        ):
            raise RuntimeContractError("timeout_seconds must be a positive number")
        timeout_seconds = float(self.timeout_seconds)
        if not isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise RuntimeContractError("timeout_seconds must be a positive number")
        object.__setattr__(self, "timeout_seconds", timeout_seconds)

    @property
    def fence_ticket(self) -> ExecutionFenceTicket | None:
        """Compatibility alias for the Kora-issued execution fence."""

        return self.execution_fence

    @property
    def is_effect_bearing(self) -> bool:
        """Whether this job requests a capability that can change state."""

        return bool(
            self.capabilities.intersection(
                {
                    Capability.WORKSPACE_WRITE,
                    Capability.WORKSPACE_EXECUTE,
                    Capability.RUNTIME_MEMORY_WRITE,
                    Capability.WORKER_DELEGATE,
                }
            )
        )

    @property
    def requires_execution_fence(self) -> bool:
        """Whether callers must validate a fence before effect-bearing work."""

        return self.is_effect_bearing

    def validate_execution_fence(
        self,
        *,
        attempt_id: str | None = None,
        at: datetime | None = None,
        cancellation_identity: str | None = None,
    ) -> ExecutionFenceTicket | None:
        """Validate this job's Kora fence when an effect may be requested.

        Read-only jobs retain the historical ``None`` default.  A caller that
        submits an effect-bearing job must explicitly validate a Kora-issued
        ticket immediately before invoking its adapter.
        """

        if self.execution_fence is None:
            if self.requires_execution_fence:
                raise RuntimeContractError(
                    "effect-bearing runtime jobs require a Kora execution fence"
                )
            return None
        ticket = self.execution_fence.validate(
            attempt_id=attempt_id,
            cancellation_identity=cancellation_identity,
            at=at,
        )
        callback = get_process_local(self)
        if callback is None:
            # MissionService-issued tickets carry the Kora-owned validator in
            # the same process-local channel.  This keeps direct adapter use
            # fail-closed without putting a controller or database handle in
            # the public ticket representation.
            callback = get_process_local(ticket)
        if callback is not None:
            try:
                result = invoke_process_local(callback, ticket)
            except Exception as exc:  # noqa: BLE001 - preserve the boundary error
                if isinstance(exc, RuntimeContractError):
                    raise
                raise RuntimeContractError(
                    "live Kora execution fence validation failed"
                ) from exc
            if result is False:
                raise RuntimeContractError(
                    "live Kora execution fence validation was rejected"
                )
        return ticket

    validate_fence = validate_execution_fence
    validate_for_execution = validate_execution_fence


def _runtime_job_live_fence_validator(
    job: RuntimeJob,
) -> Callable[..., object] | None:
    """Expose the process-local hook without adding a dataclass field."""

    return get_process_local(job)


RuntimeJob.live_fence_validator = property(_runtime_job_live_fence_validator)


@dataclass(frozen=True, slots=True)
class RuntimeResult:
    """Sanitized result returned to Kora's mission controller."""

    mission_id: str
    task_id: str
    status: RuntimeStatus
    response: str
    exit_code: int
    api_calls: int | None = None
    total_tokens: int | None = None
    estimated_cost_usd: float | None = None
    session_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, RuntimeStatus):
            try:
                object.__setattr__(self, "status", RuntimeStatus(self.status))
            except (TypeError, ValueError) as exc:
                raise RuntimeContractError("status must be a RuntimeStatus") from exc
        if not isinstance(self.response, str):
            raise RuntimeContractError("response must be a string")
        if isinstance(self.exit_code, bool) or not isinstance(self.exit_code, int):
            raise RuntimeContractError("exit_code must be an integer")
        for field_name in ("api_calls", "total_tokens"):
            value = getattr(self, field_name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise RuntimeContractError(
                    f"{field_name} must be a non-negative integer or None"
                )
        if self.estimated_cost_usd is not None:
            if isinstance(self.estimated_cost_usd, bool) or not isinstance(
                self.estimated_cost_usd, (int, float)
            ):
                raise RuntimeContractError(
                    "estimated_cost_usd must be a finite non-negative number or None"
                )
            cost = float(self.estimated_cost_usd)
            if not isfinite(cost) or cost < 0:
                raise RuntimeContractError(
                    "estimated_cost_usd must be a finite non-negative number or None"
                )
            object.__setattr__(self, "estimated_cost_usd", cost)

    @property
    def completed(self) -> bool:
        return self.status is RuntimeStatus.COMPLETED

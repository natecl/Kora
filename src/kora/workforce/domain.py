"""Profession-agnostic private workforce contracts.

The records in this module are intentionally small, immutable value objects.
They describe the semantic work boundary and private routing state without
coupling Kora to a profession, runtime, provider, or model SDK.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from math import isfinite
from typing import Any

from kora.workforce.errors import WorkforceValidationError


class RiskLevel(StrEnum):
    """The consequence of an incorrect or incomplete task result."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return _RISK_RANK[self]

    def __lt__(self, other: object) -> bool:
        if isinstance(other, RiskLevel):
            return self.rank < other.rank
        return NotImplemented

    def __le__(self, other: object) -> bool:
        if isinstance(other, RiskLevel):
            return self.rank <= other.rank
        return NotImplemented

    def __gt__(self, other: object) -> bool:
        if isinstance(other, RiskLevel):
            return self.rank > other.rank
        return NotImplemented

    def __ge__(self, other: object) -> bool:
        if isinstance(other, RiskLevel):
            return self.rank >= other.rank
        return NotImplemented


class PrivacyLevel(StrEnum):
    """The most restrictive data boundary a task may require."""

    EXTERNAL_OK = "external_ok"
    PRIVATE = "private"
    LOCAL_ONLY = "local_only"

    @property
    def rank(self) -> int:
        return _PRIVACY_RANK[self]

    def __lt__(self, other: object) -> bool:
        if isinstance(other, PrivacyLevel):
            return self.rank < other.rank
        return NotImplemented

    def __le__(self, other: object) -> bool:
        if isinstance(other, PrivacyLevel):
            return self.rank <= other.rank
        return NotImplemented

    def __gt__(self, other: object) -> bool:
        if isinstance(other, PrivacyLevel):
            return self.rank > other.rank
        return NotImplemented

    def __ge__(self, other: object) -> bool:
        if isinstance(other, PrivacyLevel):
            return self.rank >= other.rank
        return NotImplemented


_RISK_RANK = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.HIGH: 2,
    RiskLevel.CRITICAL: 3,
}
_PRIVACY_RANK = {
    PrivacyLevel.EXTERNAL_OK: 0,
    PrivacyLevel.PRIVATE: 1,
    PrivacyLevel.LOCAL_ONLY: 2,
}


def _non_empty(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkforceValidationError(f"{field_name} must be a non-empty string")
    return value


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        value = (value,)
    try:
        values = tuple(value)
    except TypeError as exc:
        raise WorkforceValidationError(
            f"{field_name} must be a sequence of strings"
        ) from exc
    if any(not isinstance(item, str) or not item.strip() for item in values):
        raise WorkforceValidationError(f"{field_name} must contain non-empty strings")
    return values


def _string_set(value: Any, field_name: str) -> frozenset[str]:
    if value is None:
        return frozenset()
    if isinstance(value, str):
        value = (value,)
    try:
        values = frozenset(value)
    except TypeError as exc:
        raise WorkforceValidationError(
            f"{field_name} must be a set-like collection of strings"
        ) from exc
    if any(not isinstance(item, str) or not item.strip() for item in values):
        raise WorkforceValidationError(f"{field_name} must contain non-empty strings")
    return values


def _score(value: Any, field_name: str) -> float:
    if isinstance(value, bool):
        raise WorkforceValidationError(f"{field_name} must be a number from 0 to 1")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise WorkforceValidationError(
            f"{field_name} must be a number from 0 to 1"
        ) from exc
    if not isfinite(result) or not 0.0 <= result <= 1.0:
        raise WorkforceValidationError(f"{field_name} must be a number from 0 to 1")
    return result


def _nonnegative_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool):
        raise WorkforceValidationError(f"{field_name} must be non-negative")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise WorkforceValidationError(f"{field_name} must be non-negative") from exc
    if not isfinite(result) or result < 0.0:
        raise WorkforceValidationError(f"{field_name} must be non-negative")
    return result


def _nonnegative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise WorkforceValidationError(f"{field_name} must be a non-negative integer")
    return value


def _positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise WorkforceValidationError(f"{field_name} must be a positive integer")
    return value


def _enum_value(value: Any, enum_type: type[StrEnum], field_name: str) -> StrEnum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(member.value for member in enum_type)
        raise WorkforceValidationError(
            f"{field_name} must be one of: {allowed}"
        ) from exc


@dataclass(frozen=True, slots=True)
class RoleCharter:
    """A person's profession-agnostic operating boundary."""

    role_id: str
    title: str
    responsibilities: tuple[str, ...] = ()
    non_responsibilities: tuple[str, ...] = ()
    allowed_capabilities: frozenset[str] = field(default_factory=frozenset)
    authority_constraints: tuple[str, ...] = ()
    default_quality_floor: float = 0.0
    max_concurrency: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "role_id", _non_empty(self.role_id, "role_id"))
        object.__setattr__(self, "title", _non_empty(self.title, "title"))
        object.__setattr__(
            self,
            "responsibilities",
            _string_tuple(self.responsibilities, "responsibilities"),
        )
        object.__setattr__(
            self,
            "non_responsibilities",
            _string_tuple(self.non_responsibilities, "non_responsibilities"),
        )
        object.__setattr__(
            self,
            "allowed_capabilities",
            _string_set(self.allowed_capabilities, "allowed_capabilities"),
        )
        object.__setattr__(
            self,
            "authority_constraints",
            _string_tuple(self.authority_constraints, "authority_constraints"),
        )
        object.__setattr__(
            self,
            "default_quality_floor",
            _score(self.default_quality_floor, "default_quality_floor"),
        )
        object.__setattr__(
            self, "max_concurrency", _positive_int(self.max_concurrency, "max_concurrency")
        )


@dataclass(frozen=True, slots=True)
class TaskProfile:
    """The hard requirements for one bounded task attempt."""

    task_id: str
    task_class: str
    objective: str
    required_capabilities: frozenset[str] = field(default_factory=frozenset)
    required_tools: frozenset[str] = field(default_factory=frozenset)
    risk: RiskLevel = RiskLevel.LOW
    ambiguity: float = 0.0
    privacy: PrivacyLevel = PrivacyLevel.EXTERNAL_OK
    estimated_input_tokens: int = 0
    estimated_output_tokens: int = 0
    required_context_tokens: int = 0
    quality_floor: float = 0.0
    reliability_floor: float = 0.0
    evidence_requirements: tuple[str, ...] = ()
    max_latency_ms: float | None = None
    max_cost_usd: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_id", _non_empty(self.task_id, "task_id"))
        object.__setattr__(
            self, "task_class", _non_empty(self.task_class, "task_class")
        )
        object.__setattr__(self, "objective", _non_empty(self.objective, "objective"))
        object.__setattr__(
            self,
            "required_capabilities",
            _string_set(self.required_capabilities, "required_capabilities"),
        )
        object.__setattr__(
            self, "required_tools", _string_set(self.required_tools, "required_tools")
        )
        object.__setattr__(self, "risk", _enum_value(self.risk, RiskLevel, "risk"))
        object.__setattr__(self, "ambiguity", _score(self.ambiguity, "ambiguity"))
        object.__setattr__(
            self, "privacy", _enum_value(self.privacy, PrivacyLevel, "privacy")
        )
        for field_name in (
            "estimated_input_tokens",
            "estimated_output_tokens",
            "required_context_tokens",
        ):
            object.__setattr__(
                self,
                field_name,
                _nonnegative_int(getattr(self, field_name), field_name),
            )
        object.__setattr__(self, "quality_floor", _score(self.quality_floor, "quality_floor"))
        object.__setattr__(
            self,
            "reliability_floor",
            _score(self.reliability_floor, "reliability_floor"),
        )
        object.__setattr__(
            self,
            "evidence_requirements",
            _string_tuple(self.evidence_requirements, "evidence_requirements"),
        )
        for field_name in ("max_latency_ms", "max_cost_usd"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(
                    self, field_name, _nonnegative_number(value, field_name)
                )


@dataclass(frozen=True, slots=True)
class WorkerEnvelope:
    """A bounded, dynamically compiled worker assignment."""

    envelope_id: str
    task_id: str
    role_id: str
    role_label: str
    objective: str
    capabilities: frozenset[str]
    tools: frozenset[str]
    evidence_requirements: tuple[str, ...]
    quality_floor: float
    risk: RiskLevel
    max_attempts: int
    max_concurrency: int

    def __post_init__(self) -> None:
        for field_name in (
            "envelope_id",
            "task_id",
            "role_id",
            "role_label",
            "objective",
        ):
            object.__setattr__(
                self, field_name, _non_empty(getattr(self, field_name), field_name)
            )
        object.__setattr__(
            self, "capabilities", _string_set(self.capabilities, "capabilities")
        )
        object.__setattr__(self, "tools", _string_set(self.tools, "tools"))
        object.__setattr__(
            self,
            "evidence_requirements",
            _string_tuple(self.evidence_requirements, "evidence_requirements"),
        )
        object.__setattr__(self, "quality_floor", _score(self.quality_floor, "quality_floor"))
        object.__setattr__(self, "risk", _enum_value(self.risk, RiskLevel, "risk"))
        object.__setattr__(self, "max_attempts", _positive_int(self.max_attempts, "max_attempts"))
        object.__setattr__(
            self,
            "max_concurrency",
            _positive_int(self.max_concurrency, "max_concurrency"),
        )


@dataclass(frozen=True, slots=True)
class ModelRoute:
    """Private route metadata used only by :class:`ModelRouter`.

    ``provider_ref`` and ``model_ref`` are deliberately private execution
    references.  They are not part of the semantic mission or worker
    envelopes, and this package never calls either reference.
    """

    route_id: str
    provider_ref: str = field(default="internal", repr=False)
    model_ref: str = field(default="internal", repr=False)
    supported_capabilities: frozenset[str] = field(default_factory=frozenset)
    supported_tools: frozenset[str] = field(default_factory=frozenset)
    privacy_support: PrivacyLevel = PrivacyLevel.EXTERNAL_OK
    context_window: int = 0
    predicted_quality: float = 0.0
    reliability: float = 0.0
    input_cost_per_million: float = 0.0
    output_cost_per_million: float = 0.0
    fixed_cost_usd: float = 0.0
    predicted_latency_ms: float = 0.0
    enabled: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "route_id", _non_empty(self.route_id, "route_id"))
        object.__setattr__(
            self, "provider_ref", _non_empty(self.provider_ref, "provider_ref")
        )
        object.__setattr__(self, "model_ref", _non_empty(self.model_ref, "model_ref"))
        object.__setattr__(
            self,
            "supported_capabilities",
            _string_set(self.supported_capabilities, "supported_capabilities"),
        )
        object.__setattr__(
            self, "supported_tools", _string_set(self.supported_tools, "supported_tools")
        )
        object.__setattr__(
            self,
            "privacy_support",
            _enum_value(self.privacy_support, PrivacyLevel, "privacy_support"),
        )
        object.__setattr__(
            self, "context_window", _nonnegative_int(self.context_window, "context_window")
        )
        object.__setattr__(
            self,
            "predicted_quality",
            _score(self.predicted_quality, "predicted_quality"),
        )
        object.__setattr__(
            self, "reliability", _score(self.reliability, "reliability")
        )
        for field_name in (
            "input_cost_per_million",
            "output_cost_per_million",
            "fixed_cost_usd",
            "predicted_latency_ms",
        ):
            object.__setattr__(
                self,
                field_name,
                _nonnegative_number(getattr(self, field_name), field_name),
            )
        if not isinstance(self.enabled, bool):
            raise WorkforceValidationError("enabled must be a boolean")

    def attempt_cost(self, task: TaskProfile) -> float:
        """Return the exact predicted cost for one task attempt."""

        return (
            self.fixed_cost_usd
            + task.estimated_input_tokens * self.input_cost_per_million / 1_000_000
            + task.estimated_output_tokens
            * self.output_cost_per_million
            / 1_000_000
        )

    calculate_attempt_cost = attempt_cost

    def expected_cost_per_accepted_outcome(self, task: TaskProfile) -> float:
        """Return this route's predicted cost per accepted task outcome."""

        acceptance_probability = self.predicted_quality * self.reliability
        return self.attempt_cost(task) / max(acceptance_probability, 0.01)


@dataclass(frozen=True, slots=True)
class RouteDecision:
    """Private selection state returned by the deterministic router."""

    task_id: str
    route_id: str
    expected_attempt_cost_usd: float
    expected_cost_per_accepted_outcome: float
    rationale_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_id", _non_empty(self.task_id, "task_id"))
        object.__setattr__(self, "route_id", _non_empty(self.route_id, "route_id"))
        object.__setattr__(
            self,
            "expected_attempt_cost_usd",
            _nonnegative_number(
                self.expected_attempt_cost_usd, "expected_attempt_cost_usd"
            ),
        )
        object.__setattr__(
            self,
            "expected_cost_per_accepted_outcome",
            _nonnegative_number(
                self.expected_cost_per_accepted_outcome,
                "expected_cost_per_accepted_outcome",
            ),
        )
        object.__setattr__(
            self, "rationale_codes", _string_tuple(self.rationale_codes, "rationale_codes")
        )

    @property
    def selected_route_id(self) -> str:
        """Readable alias for the selected private route identifier."""

        return self.route_id


@dataclass(frozen=True, slots=True)
class RouteObservation:
    """One completed private route observation for later empirical analysis."""

    route_id: str
    task_class: str
    accepted: bool
    total_tokens: int
    cost_usd: float
    latency_ms: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "route_id", _non_empty(self.route_id, "route_id"))
        object.__setattr__(
            self, "task_class", _non_empty(self.task_class, "task_class")
        )
        if not isinstance(self.accepted, bool):
            raise WorkforceValidationError("accepted must be a boolean")
        object.__setattr__(
            self, "total_tokens", _nonnegative_int(self.total_tokens, "total_tokens")
        )
        object.__setattr__(self, "cost_usd", _nonnegative_number(self.cost_usd, "cost_usd"))
        object.__setattr__(
            self, "latency_ms", _nonnegative_number(self.latency_ms, "latency_ms")
        )


__all__ = [
    "ModelRoute",
    "PrivacyLevel",
    "RiskLevel",
    "RoleCharter",
    "RouteDecision",
    "RouteObservation",
    "TaskProfile",
    "WorkerEnvelope",
]

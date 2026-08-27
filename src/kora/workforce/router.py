"""Deterministic private route selection and in-memory route observations."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from math import fsum, isfinite
from threading import RLock
from typing import Any
from uuid import uuid4

from kora.workforce.domain import (
    ModelRoute,
    RouteDecision,
    RouteObservation,
    TaskProfile,
)
from kora.workforce.errors import NoEligibleRouteError, WorkforceValidationError


def _finite_nonnegative(value: Any, field_name: str) -> float:
    if isinstance(value, bool):
        raise WorkforceValidationError(f"{field_name} must be finite and non-negative")
    try:
        result = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise WorkforceValidationError(
            f"{field_name} must be finite and non-negative"
        ) from exc
    if not isfinite(result) or result < 0.0:
        raise WorkforceValidationError(f"{field_name} must be finite and non-negative")
    return result


def _route_ids(value: Any, field_name: str = "excluded_route_ids") -> frozenset[str]:
    if value is None:
        return frozenset()
    if isinstance(value, str):
        value = (value,)
    try:
        result = frozenset(value)
    except TypeError as exc:
        raise WorkforceValidationError(f"{field_name} must be a collection") from exc
    if any(not isinstance(item, str) or not item.strip() for item in result):
        raise WorkforceValidationError(f"{field_name} must contain route IDs")
    return result


def _finite_sum(values: Iterable[float], field_name: str) -> float:
    try:
        result = fsum(values)
    except OverflowError as exc:
        raise WorkforceValidationError(
            f"{field_name} must remain finite"
        ) from exc
    if not isfinite(result) or result < 0.0:
        raise WorkforceValidationError(f"{field_name} must remain finite")
    return result


@dataclass(frozen=True, slots=True)
class RouteStatistics:
    """Deterministic aggregate data; it never changes route predictions."""

    route_id: str | None
    task_class: str | None
    sample_count: int
    accepted_count: int
    acceptance_rate: float
    total_tokens: int
    total_cost_usd: float
    mean_cost_usd: float
    mean_latency_ms: float

    def __post_init__(self) -> None:
        for field_name in ("route_id", "task_class"):
            value = getattr(self, field_name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise WorkforceValidationError(
                    f"{field_name} must be a non-empty string or None"
                )
        for field_name in ("sample_count", "accepted_count", "total_tokens"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise WorkforceValidationError(
                    f"{field_name} must be a non-negative integer"
                )
        if self.accepted_count > self.sample_count:
            raise WorkforceValidationError(
                "accepted_count cannot exceed sample_count"
            )
        for field_name in (
            "acceptance_rate",
            "total_cost_usd",
            "mean_cost_usd",
            "mean_latency_ms",
        ):
            object.__setattr__(
                self,
                field_name,
                _finite_nonnegative(getattr(self, field_name), field_name),
            )
        if self.acceptance_rate > 1.0:
            raise WorkforceValidationError("acceptance_rate must be at most 1")

    @property
    def accepted_rate(self) -> float:
        """Alias used by callers that call acceptance ``accepted_rate``."""

        return self.acceptance_rate


class RouteObservationStats:
    """An in-memory append-only observation helper for future model fitting.

    The helper intentionally does not modify ``ModelRoute`` predictions or
    participate in route selection.  It only stores observations and computes
    stable aggregates for later empirical policy work.
    """

    def __init__(self) -> None:
        self._observations: list[RouteObservation] = []
        self._lock = RLock()

    @property
    def observations(self) -> tuple[RouteObservation, ...]:
        with self._lock:
            return tuple(self._observations)

    def record(self, observation: RouteObservation) -> None:
        if not isinstance(observation, RouteObservation):
            raise WorkforceValidationError(
                "observation must be a RouteObservation"
            )
        with self._lock:
            self._observations.append(observation)

    add = record
    observe = record

    def aggregate(
        self,
        route_id: str | None = None,
        task_class: str | None = None,
    ) -> RouteStatistics:
        if route_id is not None and (not isinstance(route_id, str) or not route_id.strip()):
            raise WorkforceValidationError("route_id must be a non-empty string")
        if task_class is not None and (
            not isinstance(task_class, str) or not task_class.strip()
        ):
            raise WorkforceValidationError("task_class must be a non-empty string")
        with self._lock:
            matching = [
                observation
                for observation in self._observations
                if (route_id is None or observation.route_id == route_id)
                and (task_class is None or observation.task_class == task_class)
            ]
        sample_count = len(matching)
        accepted_count = sum(observation.accepted for observation in matching)
        total_tokens = sum(observation.total_tokens for observation in matching)
        total_cost = _finite_sum(
            (observation.cost_usd for observation in matching),
            "total_cost_usd",
        )
        total_latency = _finite_sum(
            (observation.latency_ms for observation in matching),
            "total_latency_ms",
        )
        return RouteStatistics(
            route_id=route_id,
            task_class=task_class,
            sample_count=sample_count,
            accepted_count=accepted_count,
            acceptance_rate=(accepted_count / sample_count if sample_count else 0.0),
            total_tokens=total_tokens,
            total_cost_usd=total_cost,
            mean_cost_usd=(total_cost / sample_count if sample_count else 0.0),
            mean_latency_ms=(total_latency / sample_count if sample_count else 0.0),
        )

    summary = aggregate

    def snapshot(self) -> tuple[RouteStatistics, ...]:
        """Return grouped statistics in stable route/task-class order."""

        with self._lock:
            groups = sorted(
                {(item.route_id, item.task_class) for item in self._observations}
            )
        return tuple(self.aggregate(route_id, task_class) for route_id, task_class in groups)


@dataclass(frozen=True, slots=True)
class RouteReservation:
    """A local concurrency/budget reservation for one private attempt."""

    reservation_id: str
    route_id: str
    reserved_cost_usd: float

    def __post_init__(self) -> None:
        for field_name in ("reservation_id", "route_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise WorkforceValidationError(
                    f"{field_name} must be a non-empty string"
                )
        object.__setattr__(
            self,
            "reserved_cost_usd",
            _finite_nonnegative(self.reserved_cost_usd, "reserved_cost_usd"),
        )


class ModelRouter:
    """Choose an eligible route using a deterministic economic policy.

    The router uses only the static predictions on ``ModelRoute``.  Recorded
    observations are retained for later empirical updates but never silently
    become a learned policy in this slice.
    """

    def __init__(
        self,
        routes: Iterable[ModelRoute] | Mapping[str, ModelRoute],
        *,
        max_concurrency: int | None = None,
        budget_ceiling_usd: float | None = None,
        observation_stats: RouteObservationStats | None = None,
    ) -> None:
        if isinstance(routes, Mapping):
            routes = routes.values()
        try:
            normalized_routes = tuple(routes)
        except TypeError as exc:
            raise WorkforceValidationError("routes must be a collection") from exc
        if any(not isinstance(route, ModelRoute) for route in normalized_routes):
            raise WorkforceValidationError("routes must contain ModelRoute values")
        route_ids = [route.route_id for route in normalized_routes]
        if len(route_ids) != len(set(route_ids)):
            raise WorkforceValidationError("route_id values must be unique")
        if max_concurrency is not None:
            if isinstance(max_concurrency, bool) or not isinstance(max_concurrency, int):
                raise WorkforceValidationError(
                    "max_concurrency must be a positive integer when provided"
                )
            if max_concurrency <= 0:
                raise WorkforceValidationError(
                    "max_concurrency must be a positive integer when provided"
                )
        if budget_ceiling_usd is not None:
            if isinstance(budget_ceiling_usd, bool):
                raise WorkforceValidationError(
                    "budget_ceiling_usd must be non-negative when provided"
                )
            try:
                budget_ceiling_usd = float(budget_ceiling_usd)
            except (TypeError, ValueError) as exc:
                raise WorkforceValidationError(
                    "budget_ceiling_usd must be non-negative when provided"
                ) from exc
            if not isfinite(budget_ceiling_usd) or budget_ceiling_usd < 0.0:
                raise WorkforceValidationError(
                    "budget_ceiling_usd must be finite and non-negative when provided"
                )
        if observation_stats is not None and not isinstance(
            observation_stats, RouteObservationStats
        ):
            raise WorkforceValidationError(
                "observation_stats must be a RouteObservationStats"
            )

        self._routes = normalized_routes
        self.max_concurrency = max_concurrency
        self.budget_ceiling_usd = budget_ceiling_usd
        self._stats = observation_stats or RouteObservationStats()
        self._lock = RLock()
        self._reservations: dict[str, RouteReservation] = {}
        self._reserved_cost_usd = 0.0
        self._spent_cost_usd = 0.0

    @property
    def routes(self) -> tuple[ModelRoute, ...]:
        """Configured routes in their caller-provided order."""

        return self._routes

    @property
    def observation_stats(self) -> RouteObservationStats:
        return self._stats

    @property
    def observations(self) -> tuple[RouteObservation, ...]:
        return self._stats.observations

    @property
    def active_concurrency(self) -> int:
        with self._lock:
            return len(self._reservations)

    @property
    def reserved_cost_usd(self) -> float:
        with self._lock:
            return self._reserved_cost_usd

    @property
    def spent_cost_usd(self) -> float:
        with self._lock:
            return self._spent_cost_usd

    @staticmethod
    def attempt_cost(task: TaskProfile, route: ModelRoute) -> float:
        """Calculate an attempt cost using the contract's exact formula."""

        if not isinstance(task, TaskProfile) or not isinstance(route, ModelRoute):
            raise WorkforceValidationError("attempt_cost requires task and route records")
        return route.attempt_cost(task)

    calculate_attempt_cost = attempt_cost

    @staticmethod
    def expected_cost_per_accepted_outcome(
        task: TaskProfile, route: ModelRoute
    ) -> float:
        return route.expected_cost_per_accepted_outcome(task)

    calculate_expected_cost_per_accepted_outcome = (
        expected_cost_per_accepted_outcome
    )

    def _rejection_reasons(
        self,
        task: TaskProfile,
        route: ModelRoute,
        excluded_route_ids: frozenset[str],
    ) -> tuple[str, ...]:
        if route.route_id in excluded_route_ids:
            return ("excluded",)
        reasons: list[str] = []
        if not route.enabled:
            reasons.append("disabled")
        missing_capabilities = task.required_capabilities - route.supported_capabilities
        if missing_capabilities:
            reasons.append("missing_capabilities")
        missing_tools = task.required_tools - route.supported_tools
        if missing_tools:
            reasons.append("missing_tools")
        if route.privacy_support.rank < task.privacy.rank:
            reasons.append("privacy")
        if route.context_window < task.required_context_tokens:
            reasons.append("context")
        if route.predicted_quality < task.quality_floor:
            reasons.append("quality_floor")
        if route.reliability < task.reliability_floor:
            reasons.append("reliability_floor")
        if (
            task.max_latency_ms is not None
            and route.predicted_latency_ms > task.max_latency_ms
        ):
            reasons.append("latency_ceiling")
        attempt_cost = self.attempt_cost(task, route)
        if task.max_cost_usd is not None and attempt_cost > task.max_cost_usd:
            reasons.append("attempt_cost_ceiling")
        return tuple(reasons)

    @staticmethod
    def _rationale_codes(task: TaskProfile) -> tuple[str, ...]:
        codes = [
            "capabilities_satisfied",
            "tools_satisfied",
            "privacy_satisfied",
            "context_satisfied",
            "quality_floor_met",
            "reliability_floor_met",
        ]
        if task.max_latency_ms is not None:
            codes.append("latency_within_ceiling")
        if task.max_cost_usd is not None:
            codes.append("attempt_cost_within_ceiling")
        codes.append("expected_cost_per_accepted_outcome")
        return tuple(codes)

    def select(
        self,
        task: TaskProfile | None = None,
        excluded_route_ids: Iterable[str] | None = None,
        *,
        task_profile: TaskProfile | None = None,
        excluded_routes: Iterable[str] | None = None,
        active_concurrency: int = 0,
        spent_cost_usd: float = 0.0,
        concurrency_limit: int | None = None,
        budget_ceiling_usd: float | None = None,
    ) -> RouteDecision:
        """Select the least expected-cost eligible route.

        ``excluded_route_ids`` is the fallback mechanism: passing the prior
        route IDs back into this method reruns the same filters and sort key.
        All task constraints are read directly from the unchanged
        ``TaskProfile`` on every selection.
        """

        if task is None:
            task = task_profile
        elif task_profile is not None:
            raise WorkforceValidationError("provide either task or task_profile, not both")
        if excluded_route_ids is None:
            excluded_route_ids = excluded_routes
        elif excluded_routes is not None:
            raise WorkforceValidationError(
                "provide either excluded_route_ids or excluded_routes, not both"
            )
        if not isinstance(task, TaskProfile):
            raise WorkforceValidationError("task must be a TaskProfile")
        excluded = _route_ids(excluded_route_ids)
        if isinstance(active_concurrency, bool) or not isinstance(active_concurrency, int):
            raise WorkforceValidationError("active_concurrency must be non-negative")
        if active_concurrency < 0:
            raise WorkforceValidationError("active_concurrency must be non-negative")
        if isinstance(spent_cost_usd, bool):
            raise WorkforceValidationError("spent_cost_usd must be non-negative")
        try:
            spent_cost_usd = float(spent_cost_usd)
        except (TypeError, ValueError) as exc:
            raise WorkforceValidationError("spent_cost_usd must be non-negative") from exc
        if not isfinite(spent_cost_usd) or spent_cost_usd < 0.0:
            raise WorkforceValidationError(
                "spent_cost_usd must be finite and non-negative"
            )

        limit = self.max_concurrency
        if concurrency_limit is not None:
            if isinstance(concurrency_limit, bool) or not isinstance(concurrency_limit, int):
                raise WorkforceValidationError(
                    "concurrency_limit must be a positive integer when provided"
                )
            if concurrency_limit <= 0:
                raise WorkforceValidationError(
                    "concurrency_limit must be a positive integer when provided"
                )
            limit = concurrency_limit if limit is None else min(limit, concurrency_limit)

        budget = self.budget_ceiling_usd
        if budget_ceiling_usd is not None:
            if isinstance(budget_ceiling_usd, bool):
                raise WorkforceValidationError(
                    "budget_ceiling_usd must be non-negative when provided"
                )
            try:
                budget_ceiling_usd = float(budget_ceiling_usd)
            except (TypeError, ValueError) as exc:
                raise WorkforceValidationError(
                    "budget_ceiling_usd must be non-negative when provided"
                ) from exc
            if not isfinite(budget_ceiling_usd) or budget_ceiling_usd < 0.0:
                raise WorkforceValidationError(
                    "budget_ceiling_usd must be finite and non-negative when provided"
                )
            budget = budget_ceiling_usd if budget is None else min(budget, budget_ceiling_usd)

        with self._lock:
            active = len(self._reservations) + active_concurrency
            reserved = self._reserved_cost_usd
            committed = self._spent_cost_usd
        base_spend = _finite_sum(
            (committed, reserved, spent_cost_usd),
            "projected route spend",
        )
        if limit is not None and active >= limit:
            raise NoEligibleRouteError(
                task.task_id,
                {route.route_id: ("concurrency_limit",) for route in self._routes},
                excluded_route_ids=excluded,
            )

        reasons: dict[str, tuple[str, ...]] = {}
        candidates: list[tuple[float, float, str, ModelRoute, float]] = []
        for route in self._routes:
            route_reasons = self._rejection_reasons(task, route, excluded)
            if route_reasons:
                reasons[route.route_id] = route_reasons
                continue
            attempt_cost = self.attempt_cost(task, route)
            expected_cost = self.expected_cost_per_accepted_outcome(task, route)
            if not isfinite(attempt_cost) or not isfinite(expected_cost):
                raise WorkforceValidationError(
                    "route cost predictions must be finite and non-negative"
                )
            projected_spend = _finite_sum(
                (base_spend, expected_cost),
                "projected route spend",
            )
            if budget is not None and projected_spend > budget:
                reasons[route.route_id] = ("budget_ceiling",)
                continue
            candidates.append(
                (
                    expected_cost,
                    route.predicted_latency_ms,
                    route.route_id,
                    route,
                    attempt_cost,
                )
            )

        if not candidates:
            raise NoEligibleRouteError(
                task.task_id,
                reasons,
                excluded_route_ids=excluded,
            )

        expected_cost, _, route_id, _, attempt_cost = min(
            candidates,
            key=lambda candidate: candidate[:3],
        )
        return RouteDecision(
            task_id=task.task_id,
            route_id=route_id,
            expected_attempt_cost_usd=attempt_cost,
            expected_cost_per_accepted_outcome=expected_cost,
            rationale_codes=self._rationale_codes(task),
        )

    route = select
    choose = select
    decide = select
    select_route = select
    choose_route = select

    def fallback(
        self,
        task: TaskProfile | None = None,
        excluded_route_ids: Iterable[str] | None = None,
        *,
        task_profile: TaskProfile | None = None,
        excluded_routes: Iterable[str] | None = None,
    ) -> RouteDecision:
        """Rerun selection with failed/rejected route IDs excluded."""

        return self.select(
            task,
            excluded_route_ids=excluded_route_ids,
            task_profile=task_profile,
            excluded_routes=excluded_routes,
        )

    select_fallback = fallback

    def reserve(
        self,
        decision: RouteDecision,
        *,
        reservation_id: str | None = None,
        concurrency_limit: int | None = None,
        budget_ceiling_usd: float | None = None,
    ) -> RouteReservation:
        """Reserve one bounded attempt without contacting a provider."""

        if not isinstance(decision, RouteDecision):
            raise WorkforceValidationError("decision must be a RouteDecision")
        if reservation_id is None:
            reservation_id = "reservation-" + uuid4().hex
        if not isinstance(reservation_id, str) or not reservation_id.strip():
            raise WorkforceValidationError("reservation_id must be a non-empty string")
        limit = self.max_concurrency
        if concurrency_limit is not None:
            if isinstance(concurrency_limit, bool) or not isinstance(concurrency_limit, int):
                raise WorkforceValidationError(
                    "concurrency_limit must be a positive integer when provided"
                )
            if concurrency_limit <= 0:
                raise WorkforceValidationError(
                    "concurrency_limit must be a positive integer when provided"
                )
            limit = concurrency_limit if limit is None else min(limit, concurrency_limit)
        budget = self.budget_ceiling_usd
        if budget_ceiling_usd is not None:
            if isinstance(budget_ceiling_usd, bool):
                raise WorkforceValidationError(
                    "budget_ceiling_usd must be non-negative when provided"
                )
            try:
                budget_ceiling_usd = float(budget_ceiling_usd)
            except (TypeError, ValueError) as exc:
                raise WorkforceValidationError(
                    "budget_ceiling_usd must be non-negative when provided"
                ) from exc
            if not isfinite(budget_ceiling_usd) or budget_ceiling_usd < 0.0:
                raise WorkforceValidationError(
                    "budget_ceiling_usd must be finite and non-negative when provided"
                )
            budget = budget_ceiling_usd if budget is None else min(budget, budget_ceiling_usd)

        with self._lock:
            if reservation_id in self._reservations:
                raise WorkforceValidationError("reservation_id is already active")
            if limit is not None and len(self._reservations) >= limit:
                raise NoEligibleRouteError(
                    decision.task_id,
                    {decision.route_id: ("concurrency_limit",)},
                )
            projected_spend = _finite_sum(
                (
                    self._spent_cost_usd,
                    self._reserved_cost_usd,
                    decision.expected_attempt_cost_usd,
                ),
                "projected route spend",
            )
            if budget is not None and projected_spend > budget:
                raise NoEligibleRouteError(
                    decision.task_id,
                    {decision.route_id: ("budget_ceiling",)},
                )
            _finite_sum(
                (self._reserved_cost_usd, decision.expected_attempt_cost_usd),
                "reserved route cost",
            )
            reservation = RouteReservation(
                reservation_id=reservation_id,
                route_id=decision.route_id,
                reserved_cost_usd=decision.expected_attempt_cost_usd,
            )
            self._reservations[reservation_id] = reservation
            self._reserved_cost_usd += reservation.reserved_cost_usd
            return reservation

    acquire = reserve

    def release(
        self,
        reservation: RouteReservation,
        *,
        actual_cost_usd: float | None = None,
    ) -> None:
        """Release a reservation and optionally commit observed spend."""

        if not isinstance(reservation, RouteReservation):
            raise WorkforceValidationError("reservation must be a RouteReservation")
        if actual_cost_usd is not None:
            actual_cost_usd = _finite_nonnegative(
                actual_cost_usd, "actual_cost_usd"
            )
        with self._lock:
            current = self._reservations.get(reservation.reservation_id)
            if current is None or current != reservation:
                raise WorkforceValidationError("reservation is not active")
            committed_cost = (
                actual_cost_usd
                if actual_cost_usd is not None
                else current.reserved_cost_usd
            )
            next_reserved = self._reserved_cost_usd - current.reserved_cost_usd
            next_spent = self._spent_cost_usd + committed_cost
            if not isfinite(next_reserved) or next_reserved < 0.0:
                raise WorkforceValidationError("reserved route cost must remain finite")
            if not isfinite(next_spent) or next_spent < 0.0:
                raise WorkforceValidationError("spent route cost must remain finite")
            self._reservations.pop(reservation.reservation_id, None)
            self._reserved_cost_usd = next_reserved
            self._spent_cost_usd = next_spent

    def record_observation(self, observation: RouteObservation) -> None:
        """Store route telemetry without changing deterministic selection."""

        self._stats.record(observation)

    record = record_observation
    observe = record_observation


# A descriptive alias for integrations that call this a metrics store.
InMemoryRouteStats = RouteObservationStats


__all__ = [
    "InMemoryRouteStats",
    "ModelRouter",
    "RouteObservationStats",
    "RouteReservation",
    "RouteStatistics",
]

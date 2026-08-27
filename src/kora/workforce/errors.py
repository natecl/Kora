"""Errors raised by Kora's private workforce compiler and router."""

from __future__ import annotations

from collections.abc import Mapping


class WorkforceError(RuntimeError):
    """Base class for workforce compilation and routing failures."""


class WorkforceValidationError(WorkforceError, ValueError):
    """A workforce contract contains invalid or unsafe input."""


class CapabilityBoundaryError(WorkforceValidationError):
    """A task asks a worker to use a capability outside its role charter."""

    def __init__(self, capabilities: set[str] | frozenset[str]) -> None:
        self.capabilities = frozenset(capabilities)
        names = ", ".join(sorted(self.capabilities))
        super().__init__(
            "task capabilities are outside the role charter allowance: " + names
        )


class UnavailableCapabilityError(WorkforceValidationError):
    """A required capability is not present in the available capability set."""

    def __init__(self, capabilities: set[str] | frozenset[str]) -> None:
        self.capabilities = frozenset(capabilities)
        names = ", ".join(sorted(self.capabilities))
        super().__init__("required capabilities are unavailable: " + names)


class UnavailableToolError(WorkforceValidationError):
    """A required tool is not present in the available capability catalog."""

    def __init__(self, tools: set[str] | frozenset[str]) -> None:
        self.tools = frozenset(tools)
        names = ", ".join(sorted(self.tools))
        super().__init__("required tools are unavailable: " + names)


class NoEligibleRouteError(WorkforceError):
    """No enabled route can satisfy a task's hard constraints."""

    def __init__(
        self,
        task_id: str,
        reasons: Mapping[str, tuple[str, ...]] | None = None,
        *,
        excluded_route_ids: set[str] | frozenset[str] = frozenset(),
    ) -> None:
        self.task_id = task_id
        self.reasons = dict(reasons or {})
        self.excluded_route_ids = frozenset(excluded_route_ids)
        detail = "; ".join(
            f"{route_id}: {', '.join(route_reasons)}"
            for route_id, route_reasons in sorted(self.reasons.items())
        )
        if not detail:
            detail = "no routes were configured"
        super().__init__(f"no eligible route for task {task_id!r}: {detail}")

    @property
    def route_reasons(self) -> Mapping[str, tuple[str, ...]]:
        """Alias for callers that use the more explicit name."""

        return self.reasons

    @property
    def failure_reasons(self) -> Mapping[str, tuple[str, ...]]:
        """Alias for callers that describe ineligible routes as failures."""

        return self.reasons


# Short aliases keep the package pleasant to use without creating a second
# error hierarchy or exposing implementation-specific provider errors.
NoEligibleRoute = NoEligibleRouteError
ValidationError = WorkforceValidationError


__all__ = [
    "CapabilityBoundaryError",
    "NoEligibleRoute",
    "NoEligibleRouteError",
    "UnavailableCapabilityError",
    "UnavailableToolError",
    "ValidationError",
    "WorkforceError",
    "WorkforceValidationError",
]

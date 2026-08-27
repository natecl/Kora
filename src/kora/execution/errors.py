"""Errors raised by Kora's bounded execution coordinator."""

from __future__ import annotations


class ExecutionError(RuntimeError):
    """Base class for expected execution-coordinator failures."""


class ExecutionValidationError(ExecutionError, ValueError):
    """An execution contract is invalid or outside the supported boundary."""


class TaskSpecNotFoundError(ExecutionError, LookupError):
    """No execution specification is registered for a task."""

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        super().__init__(f"no execution specification for task {task_id!r}")


class RuntimeResolutionError(ExecutionError, LookupError):
    """A private route cannot be resolved to an execution runtime."""

    def __init__(self, route_id: str) -> None:
        self.route_id = route_id
        super().__init__(f"no runtime is registered for private route {route_id!r}")


# Descriptive aliases keep integrations from depending on one exact noun while
# retaining a single typed error hierarchy.
MissingRuntimeRouteError = RuntimeResolutionError
MissingRouteError = RuntimeResolutionError
TaskSpecificationNotFoundError = TaskSpecNotFoundError


__all__ = [
    "ExecutionError",
    "ExecutionValidationError",
    "MissingRouteError",
    "MissingRuntimeRouteError",
    "RuntimeResolutionError",
    "TaskSpecNotFoundError",
    "TaskSpecificationNotFoundError",
]

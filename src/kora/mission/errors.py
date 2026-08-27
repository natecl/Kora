"""Errors raised by Kora's persistent mission control plane."""

from __future__ import annotations


class MissionControlError(RuntimeError):
    """Base class for expected mission-control failures."""


class ValidationError(MissionControlError, ValueError):
    """A domain record or operation contains invalid data."""


class NotFoundError(MissionControlError, LookupError):
    """A requested mission-control record does not exist."""


class ConflictError(MissionControlError):
    """An operation conflicts with already-persisted state."""


class InvalidTransitionError(ConflictError):
    """A state transition is not allowed by the domain state machine."""


class DependencyError(ConflictError):
    """A task dependency is invalid or would introduce a cycle."""


class PermissionUnavailableError(ConflictError):
    """A permission grant is absent, revoked, expired, or already consumed."""

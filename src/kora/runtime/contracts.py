"""Public contracts between Kora's control plane and an execution runtime.

These records deliberately contain mission and authority data without exposing
runtime-specific models, providers, prompts, or worker topology to product
surfaces.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


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


@dataclass(frozen=True, slots=True)
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

    @property
    def completed(self) -> bool:
        return self.status is RuntimeStatus.COMPLETED

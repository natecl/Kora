"""Compilation of bounded private worker envelopes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any

from kora.workforce.domain import RoleCharter, TaskProfile, WorkerEnvelope
from kora.workforce.errors import (
    CapabilityBoundaryError,
    UnavailableCapabilityError,
    UnavailableToolError,
    WorkforceValidationError,
)


def _capability_name(value: Any, field_name: str = "capability") -> str:
    if isinstance(value, str):
        name = value
    else:
        name = getattr(value, "name", None)
        if name is None:
            name = getattr(value, "value", None)
    if not isinstance(name, str) or not name.strip():
        raise WorkforceValidationError(f"{field_name} names must be non-empty strings")
    return name


def _tool_names(value: Any, field_name: str = "tools") -> frozenset[str]:
    if value is None:
        return frozenset()
    if isinstance(value, str):
        value = (value,)
    try:
        names = frozenset(value)
    except TypeError as exc:
        raise WorkforceValidationError(
            f"{field_name} must be a collection of strings"
        ) from exc
    if any(not isinstance(name, str) or not name.strip() for name in names):
        raise WorkforceValidationError(f"{field_name} must contain non-empty strings")
    return names


def _mission_objective(mission: Any) -> str:
    """Read only the objective needed to establish mission scope.

    The compiler accepts the repository's ``Mission`` record, a small mapping,
    or a plain objective string so it remains independent of mission storage.
    The value is intentionally not copied into the worker envelope: the task
    objective is the only executable objective at this boundary.
    """

    if isinstance(mission, str):
        objective = mission
    elif isinstance(mission, Mapping):
        objective = mission.get("objective")
    else:
        objective = getattr(mission, "objective", None)
    if not isinstance(objective, str) or not objective.strip():
        raise WorkforceValidationError("mission must provide a non-empty objective")
    return objective


def _available_catalog(
    available_capabilities: Any,
) -> tuple[frozenset[str], frozenset[str], bool]:
    """Normalize capability availability and optional capability-owned tools.

    The stable input is an iterable of capability names.  A mapping is also
    accepted as a compact internal catalog, where each value is either a tool
    iterable or ``{"tools": ...}``.  The final boolean indicates whether a
    tool catalog was actually supplied; plain capability names cannot be used
    to infer that a tool is unavailable.
    """

    if available_capabilities is None:
        return frozenset(), frozenset(), False

    if isinstance(available_capabilities, Mapping):
        capabilities: set[str] = set()
        tools: set[str] = set()
        for raw_name, raw_spec in available_capabilities.items():
            name = _capability_name(raw_name, "available capability")
            capabilities.add(name)
            if isinstance(raw_spec, Mapping):
                raw_spec = raw_spec.get("tools", ())
            elif isinstance(raw_spec, bool):
                raw_spec = ()
            elif hasattr(raw_spec, "tools"):
                raw_spec = getattr(raw_spec, "tools")
            tools.update(_tool_names(raw_spec, "available tools"))
        return frozenset(capabilities), frozenset(tools), True

    if isinstance(available_capabilities, str):
        available_capabilities = (available_capabilities,)
    try:
        values = tuple(available_capabilities)
    except TypeError as exc:
        raise WorkforceValidationError(
            "available_capabilities must be a capability collection or mapping"
        ) from exc

    capabilities = frozenset(
        _capability_name(value, "available capability") for value in values
    )
    # A plain capability set carries no authoritative tool catalog.  Required
    # task tools are still copied into the bounded envelope, while a mapping
    # can opt into strict tool availability checks above.
    return capabilities, frozenset(), False


def deterministic_envelope_id(
    role_id: str, task_id: str, capabilities: Iterable[str]
) -> str:
    """Return a stable opaque ID derived from the requested worker boundary."""

    canonical_capabilities = tuple(sorted(set(capabilities)))
    payload = json.dumps(
        [role_id, task_id, canonical_capabilities],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "envelope-" + hashlib.sha256(payload).hexdigest()


class WorkforceCompiler:
    """Compile bounded capability workers without changing mission intent."""

    def __init__(
        self,
        *,
        max_attempts: int = 3,
        max_concurrency: int | None = None,
    ) -> None:
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int):
            raise WorkforceValidationError("max_attempts must be a positive integer")
        if max_attempts <= 0:
            raise WorkforceValidationError("max_attempts must be a positive integer")
        if max_concurrency is not None:
            if isinstance(max_concurrency, bool) or not isinstance(max_concurrency, int):
                raise WorkforceValidationError(
                    "max_concurrency must be a positive integer when provided"
                )
            if max_concurrency <= 0:
                raise WorkforceValidationError(
                    "max_concurrency must be a positive integer when provided"
                )
        self.max_attempts = max_attempts
        self.max_concurrency = max_concurrency

    def compile(
        self,
        role_charter: RoleCharter,
        mission: Any,
        task_profile: TaskProfile | None = None,
        available_capabilities: Any = None,
        *,
        task: TaskProfile | None = None,
    ) -> WorkerEnvelope:
        """Compile one task profile into a bounded worker envelope.

        ``mission`` is read for scope validation only.  The compiled envelope
        executes exactly ``task_profile.objective`` and cannot manufacture a
        new overarching objective.
        """

        if task_profile is None:
            task_profile = task
        elif task is not None:
            raise WorkforceValidationError(
                "provide either task_profile or task, not both"
            )
        if not isinstance(role_charter, RoleCharter):
            raise WorkforceValidationError("role_charter must be a RoleCharter")
        if not isinstance(task_profile, TaskProfile):
            raise WorkforceValidationError("task_profile must be a TaskProfile")
        _mission_objective(mission)

        requested = task_profile.required_capabilities
        outside_charter = requested - role_charter.allowed_capabilities
        if outside_charter:
            raise CapabilityBoundaryError(outside_charter)

        if available_capabilities is None:
            available = role_charter.allowed_capabilities
            available_tools = frozenset()
            strict_tools = False
        else:
            available, available_tools, strict_tools = _available_catalog(
                available_capabilities
            )
        unavailable = requested - available
        if unavailable:
            raise UnavailableCapabilityError(unavailable)

        if strict_tools:
            unavailable_tools = task_profile.required_tools - available_tools
            if unavailable_tools:
                raise UnavailableToolError(unavailable_tools)

        max_concurrency = role_charter.max_concurrency
        if self.max_concurrency is not None:
            max_concurrency = min(max_concurrency, self.max_concurrency)
        quality_floor = max(
            task_profile.quality_floor, role_charter.default_quality_floor
        )
        envelope_id = deterministic_envelope_id(
            role_charter.role_id,
            task_profile.task_id,
            requested,
        )
        envelope = WorkerEnvelope(
            envelope_id=envelope_id,
            task_id=task_profile.task_id,
            role_id=role_charter.role_id,
            role_label=f"{role_charter.title} / {task_profile.task_class}",
            objective=task_profile.objective,
            capabilities=requested,
            tools=task_profile.required_tools,
            evidence_requirements=task_profile.evidence_requirements,
            quality_floor=quality_floor,
            risk=task_profile.risk,
            max_attempts=self.max_attempts,
            max_concurrency=max_concurrency,
        )
        # Keep the invariant explicit in case the envelope implementation ever
        # gains transformations: compilation may never rewrite task intent.
        if envelope.objective != task_profile.objective:
            raise WorkforceValidationError("compiled envelope changed task objective")
        return envelope

    compile_envelope = compile
    compile_task = compile
    compile_worker = compile

    def compile_many(
        self,
        role_charter: RoleCharter,
        mission: Any,
        task_profiles: Iterable[TaskProfile],
        available_capabilities: Any = None,
    ) -> tuple[WorkerEnvelope, ...]:
        """Compile task profiles in input order with identical scope rules."""

        return tuple(
            self.compile(
                role_charter,
                mission,
                task_profile,
                available_capabilities,
            )
            for task_profile in task_profiles
        )


__all__ = ["WorkforceCompiler", "deterministic_envelope_id"]

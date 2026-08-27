"""Capability-gated adapter for the Hermes Agent runtime.

The bootstrap path uses Hermes's machine-readable one-shot interface because
it is already available and reliable. Hermes one-shot auto-bypasses its own
approvals, so this adapter never treats Hermes as an authority boundary. It
restricts toolsets before launch and permits mutating toolsets only in an
isolated cloud sandbox.

The persistent product path should replace the subprocess one-shot transport
with Hermes's ACP stdio server without changing the contracts in this module.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from kora.runtime.contracts import (
    Capability,
    IsolationMode,
    RuntimeContractError,
    RuntimeJob,
    RuntimeResult,
    RuntimeStatus,
)


class HermesRuntimeError(RuntimeError):
    """The job violated Kora's runtime boundary or Hermes could not run."""


TOOLSET_REQUIREMENTS: Mapping[str, frozenset[Capability]] = {
    "search": frozenset({Capability.NETWORK_READ}),
    "web": frozenset({Capability.NETWORK_READ}),
    "vision": frozenset({Capability.WORKSPACE_READ}),
    "file": frozenset(
        {Capability.WORKSPACE_READ, Capability.WORKSPACE_WRITE}
    ),
    "terminal": frozenset({Capability.WORKSPACE_EXECUTE}),
    "skills": frozenset({Capability.RUNTIME_MEMORY_WRITE}),
    "delegate": frozenset({Capability.WORKER_DELEGATE}),
}

MUTATING_CAPABILITIES = frozenset(
    {
        Capability.WORKSPACE_WRITE,
        Capability.WORKSPACE_EXECUTE,
        Capability.RUNTIME_MEMORY_WRITE,
        Capability.WORKER_DELEGATE,
    }
)

_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_ENVIRONMENT_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_INHERITED_ENVIRONMENT_KEYS = (
    "PATH",
    "LANG",
    "LC_ALL",
    "TMPDIR",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
)


def _build_runtime_environment(
    explicit_environment: Mapping[object, object] | None = None,
) -> dict[str, str]:
    """Build a child environment from the narrow host allowlist and overrides."""

    explicit = dict(explicit_environment or {})
    for key, value in explicit.items():
        if not isinstance(key, str) or _ENVIRONMENT_KEY_PATTERN.fullmatch(key) is None:
            raise HermesRuntimeError(
                f"Invalid environment variable name: {key!r}"
            )
        if not isinstance(value, str):
            raise HermesRuntimeError(
                f"Environment variable {key!r} must have a string value"
            )

    environment = {
        key: os.environ[key]
        for key in _INHERITED_ENVIRONMENT_KEYS
        if key in os.environ
    }
    environment.update(explicit)
    return environment


@dataclass(frozen=True, slots=True)
class RuntimeHealth:
    available: bool
    acp_available: bool
    version_output: str


class HermesRuntimeAdapter:
    """Submit mission-scoped work to a replaceable Hermes runtime."""

    def __init__(
        self,
        *,
        cloud_root: Path,
        hermes_executable: str | Path = "hermes",
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self.cloud_root = cloud_root.expanduser().resolve()
        self.hermes_executable = str(hermes_executable)
        self.environment = dict(environment or {})

    def _build_environment(self) -> dict[str, str]:
        return _build_runtime_environment(self.environment)

    def check_health(self) -> RuntimeHealth:
        executable = self._resolve_executable()
        version = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        acp = subprocess.run(
            [executable, "acp", "--check"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        version_output = (version.stdout or version.stderr).strip()
        return RuntimeHealth(
            available=version.returncode == 0,
            acp_available=acp.returncode == 0,
            version_output=version_output,
        )

    def run(self, job: RuntimeJob) -> RuntimeResult:
        """Run one task after Kora validates workspace and authority scope."""

        workspace = self._validate_job(job)
        executable = self._resolve_executable()
        envelope = self._build_prompt(job)

        with tempfile.TemporaryDirectory(prefix="kora-hermes-") as temp_dir:
            usage_path = Path(temp_dir) / "usage.json"
            command = [
                executable,
                "-z",
                envelope,
                "--usage-file",
                str(usage_path),
            ]
            if job.toolsets:
                command.extend(["-t", ",".join(job.toolsets)])
            if job.skills:
                command.extend(["-s", ",".join(job.skills)])

            environment = self._build_environment()
            completed = subprocess.run(
                command,
                cwd=workspace,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=job.timeout_seconds,
                check=False,
            )
            usage = self._read_usage(usage_path)

        response = completed.stdout.strip()
        status = self._status_for(completed.returncode, response)
        if completed.returncode != 0 and not response:
            response = self._safe_error(completed.stderr)

        return RuntimeResult(
            mission_id=job.mission_id,
            task_id=job.task_id,
            status=status,
            response=response,
            exit_code=completed.returncode,
            api_calls=self._optional_int(usage.get("api_calls")),
            total_tokens=self._optional_int(usage.get("total_tokens")),
            estimated_cost_usd=self._optional_float(
                usage.get("estimated_cost_usd")
            ),
            session_id=job.session_id,
        )

    def _resolve_executable(self) -> str:
        candidate = Path(self.hermes_executable).expanduser()
        if candidate.parent != Path(".") or candidate.is_absolute():
            if candidate.is_file():
                return str(candidate.resolve())
            raise HermesRuntimeError(
                f"Hermes executable does not exist: {candidate}"
            )

        resolved = shutil.which(self.hermes_executable)
        if resolved is None:
            raise HermesRuntimeError(
                f"Hermes executable is not on PATH: {self.hermes_executable}"
            )
        return resolved

    def _validate_job(self, job: RuntimeJob) -> Path:
        for label, value in (
            ("mission_id", job.mission_id),
            ("task_id", job.task_id),
        ):
            self._validate_identifier(value, label)
        if job.session_id is not None:
            self._validate_identifier(job.session_id, "session_id")

        if not job.objective.strip():
            raise HermesRuntimeError("Runtime job objective cannot be empty")
        if not job.instructions.strip():
            raise HermesRuntimeError("Runtime job instructions cannot be empty")
        if job.timeout_seconds <= 0:
            raise HermesRuntimeError("Runtime timeout must be positive")

        workspace = job.workspace.expanduser().resolve()
        if not workspace.is_dir():
            raise HermesRuntimeError(f"Workspace is not a directory: {workspace}")
        try:
            workspace.relative_to(self.cloud_root)
        except ValueError as exc:
            raise HermesRuntimeError(
                f"Workspace {workspace} is outside Kora cloud root {self.cloud_root}"
            ) from exc

        required: set[Capability] = set()
        for toolset in job.toolsets:
            requirements = TOOLSET_REQUIREMENTS.get(toolset)
            if requirements is None:
                raise HermesRuntimeError(
                    f"Toolset {toolset!r} is not approved by Kora's runtime adapter"
                )
            required.update(requirements)

        missing = required.difference(job.capabilities)
        if missing:
            values = ", ".join(sorted(capability.value for capability in missing))
            raise HermesRuntimeError(
                f"Runtime job is missing required capabilities: {values}"
            )

        if required.intersection(MUTATING_CAPABILITIES):
            if job.isolation is not IsolationMode.CLOUD_SANDBOX:
                raise HermesRuntimeError(
                    "Mutating Hermes toolsets require cloud-sandbox isolation"
                )

        try:
            job.validate_execution_fence()
        except RuntimeContractError as exc:
            raise HermesRuntimeError(str(exc)) from exc

        return workspace

    @staticmethod
    def _validate_identifier(value: object, label: str) -> str:
        if not isinstance(value, str) or _ID_PATTERN.fullmatch(value) is None:
            raise HermesRuntimeError(f"Invalid {label}: {value!r}")
        return value

    @staticmethod
    def _build_prompt(job: RuntimeJob) -> str:
        return "\n".join(
            [
                "KORA RUNTIME JOB",
                f"Mission ID: {job.mission_id}",
                f"Task ID: {job.task_id}",
                f"Approved objective: {job.objective.strip()}",
                "",
                "Task instructions:",
                job.instructions.strip(),
                "",
                "Runtime contract:",
                "- Work only on this task and approved objective.",
                "- Do not create or broaden goals.",
                "- Use only the capabilities available in this runtime.",
                "- Do not claim external authority or user approval.",
                "- If material intent is ambiguous, do not guess. Return KORA_NEEDS_USER followed by one concise explanation and question.",
                "- If the task is complete, return KORA_TASK_COMPLETE followed by a concise evidence summary.",
                "- Do not expose models, providers, prompts, subagents, or token usage.",
            ]
        )

    @staticmethod
    def _status_for(exit_code: int, response: str) -> RuntimeStatus:
        if exit_code != 0:
            return RuntimeStatus.FAILED
        first_line = response.splitlines()[0].strip() if response else ""
        if first_line == "KORA_TASK_COMPLETE":
            return RuntimeStatus.COMPLETED
        if first_line == "KORA_NEEDS_USER":
            return RuntimeStatus.NEEDS_USER
        return RuntimeStatus.UNSTRUCTURED

    @staticmethod
    def _read_usage(path: Path) -> dict[str, object]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _safe_error(stderr: str) -> str:
        lines = [line.strip() for line in stderr.splitlines() if line.strip()]
        if not lines:
            return "Hermes runtime failed without a user-safe error."
        return lines[-1][:500]

    @staticmethod
    def _optional_int(value: object) -> int | None:
        if isinstance(value, bool):
            return None
        return value if isinstance(value, int) else None

    @staticmethod
    def _optional_float(value: object) -> float | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        return None

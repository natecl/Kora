"""Deterministic, independent verification of a changed workspace.

This module deliberately returns candidate verification records only.  It does
not persist evidence, alter mission state, or interpret a command's output as
an authority to complete work.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess
import threading
import time
import unicodedata
from dataclasses import InitVar, dataclass
from enum import StrEnum
from math import isfinite
from pathlib import Path
from typing import Any, BinaryIO, Callable, Mapping
from urllib.parse import quote

from kora.mission.domain import ArtifactKind, EvidenceKind
from kora.mission.errors import ValidationError
from kora._process_local import attach as attach_process_local
from kora._process_local import get as get_process_local
from kora._process_local import invoke_noarg as invoke_process_local_noarg


class WorkspaceVerificationError(ValidationError):
    """A workspace or verification contract is outside the allowed boundary."""


_ENVIRONMENT_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ANSI_ESCAPE_PATTERN = re.compile(
    r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))"
)
_INHERITED_ENVIRONMENT_KEYS = (
    "PATH",
    "LANG",
    "LC_ALL",
    "TMPDIR",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
)
_SUMMARY_LIMIT = 4000
_COMMAND_CAPTURE_LIMIT = 4096
_PIPE_READ_SIZE = 16 * 1024
_GIT_TIMEOUT_SECONDS = 30.0
_GIT_CAPTURE_LIMIT = 4096
_UNTRACKED_PATH_CAPTURE_LIMIT = 1024 * 1024


def _non_empty_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkspaceVerificationError(
            f"{field_name} must be a non-empty string"
        )
    return value


def _sanitize_summary(value: str) -> str:
    """Remove terminal/control characters and cap user-visible output."""

    value = _ANSI_ESCAPE_PATTERN.sub("", value)
    sanitized: list[str] = []
    for character in value:
        if character == "\r":
            sanitized.append("\n")
            continue
        if character in "\n\t":
            sanitized.append(character)
            continue
        if unicodedata.category(character).startswith("C"):
            continue
        sanitized.append(character)

    result = "".join(sanitized)
    if len(result) <= _SUMMARY_LIMIT:
        return result
    marker = "\n...[truncated]"
    return result[: _SUMMARY_LIMIT - len(marker)] + marker


def _coerce_enum(
    value: object,
    enum_type: type[StrEnum],
    field_name: str,
) -> StrEnum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(member.value for member in enum_type)
        raise WorkspaceVerificationError(
            f"{field_name} must be one of: {allowed}"
        ) from exc


@dataclass(frozen=True, slots=True)
class VerificationCommand:
    """One explicitly argv-shaped command run by the verifier."""

    name: str
    argv: tuple[str, ...]
    timeout_seconds: float = 120.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _non_empty_string(self.name, "name"))

        if isinstance(self.argv, (str, bytes)):
            raise WorkspaceVerificationError("argv must be a non-empty sequence")
        try:
            argv = tuple(self.argv)
        except TypeError as exc:
            raise WorkspaceVerificationError(
                "argv must be a non-empty sequence"
            ) from exc
        if not argv:
            raise WorkspaceVerificationError("argv must be a non-empty sequence")
        if any(not isinstance(item, str) for item in argv):
            raise WorkspaceVerificationError("every argv item must be a string")
        object.__setattr__(self, "argv", argv)

        if isinstance(self.timeout_seconds, bool) or not isinstance(
            self.timeout_seconds, (int, float)
        ):
            raise WorkspaceVerificationError(
                "timeout_seconds must be a positive number"
            )
        timeout_seconds = float(self.timeout_seconds)
        if not isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise WorkspaceVerificationError(
                "timeout_seconds must be a positive number"
            )
        object.__setattr__(self, "timeout_seconds", timeout_seconds)


@dataclass(frozen=True, slots=True)
class VerificationCheckResult:
    """The bounded, sanitized result of one executed verification command."""

    name: str
    passed: bool
    exit_code: int | None
    summary: str
    duration_ms: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _non_empty_string(self.name, "name"))
        if not isinstance(self.passed, bool):
            raise WorkspaceVerificationError("passed must be a boolean")
        if self.exit_code is not None and (
            isinstance(self.exit_code, bool) or not isinstance(self.exit_code, int)
        ):
            raise WorkspaceVerificationError(
                "exit_code must be an integer or None"
            )
        if not isinstance(self.summary, str):
            raise WorkspaceVerificationError("summary must be a string")
        object.__setattr__(self, "summary", _sanitize_summary(self.summary))
        if isinstance(self.duration_ms, bool) or not isinstance(
            self.duration_ms, (int, float)
        ):
            raise WorkspaceVerificationError(
                "duration_ms must be a non-negative number"
            )
        duration_ms = float(self.duration_ms)
        if not isfinite(duration_ms) or duration_ms < 0:
            raise WorkspaceVerificationError(
                "duration_ms must be a non-negative number"
            )
        object.__setattr__(self, "duration_ms", duration_ms)


@dataclass(frozen=True, slots=True)
class VerificationArtifact:
    """A virtual artifact locator produced by workspace verification."""

    name: str
    locator: str
    artifact_kind: ArtifactKind
    evidence_kind: EvidenceKind
    summary: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _non_empty_string(self.name, "name"))
        object.__setattr__(
            self, "locator", _non_empty_string(self.locator, "locator")
        )
        object.__setattr__(
            self,
            "artifact_kind",
            _coerce_enum(self.artifact_kind, ArtifactKind, "artifact_kind"),
        )
        object.__setattr__(
            self,
            "evidence_kind",
            _coerce_enum(self.evidence_kind, EvidenceKind, "evidence_kind"),
        )
        summary = _non_empty_string(self.summary, "summary")
        object.__setattr__(self, "summary", _sanitize_summary(summary))


@dataclass(frozen=True, slots=True, weakref_slot=True)
class WorkspaceVerificationRequest:
    """The immutable input to one independent workspace verification."""

    workspace: Path
    commands: tuple[VerificationCommand, ...]
    require_changes: bool = True
    baseline_ref: str = "HEAD"
    # These authority fields are populated by ExecutionCoordinator.  The
    # unmarked legacy mode keeps direct read-only verifier callers source
    # compatible; production coordinator requests set the required flag.
    execution_authorized: bool | None = None
    execution_capability: bool | None = None
    execution_granted: bool | None = None
    require_execution_authority: bool = False
    live_fence_validator: InitVar[Callable[..., object] | None] = None

    def __post_init__(
        self,
        live_fence_validator: Callable[..., object] | None,
    ) -> None:
        try:
            workspace = Path(self.workspace).expanduser().resolve(strict=True)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise WorkspaceVerificationError(
                "workspace must resolve to an existing directory"
            ) from exc
        if not workspace.is_dir():
            raise WorkspaceVerificationError(
                f"workspace is not a directory: {workspace}"
            )
        object.__setattr__(self, "workspace", workspace)

        if isinstance(self.commands, (str, bytes)):
            raise WorkspaceVerificationError(
                "commands must be a sequence of VerificationCommand values"
            )
        try:
            commands = tuple(self.commands)
        except TypeError as exc:
            raise WorkspaceVerificationError(
                "commands must be a sequence of VerificationCommand values"
            ) from exc
        if any(not isinstance(command, VerificationCommand) for command in commands):
            raise WorkspaceVerificationError(
                "commands must contain only VerificationCommand values"
            )
        object.__setattr__(self, "commands", commands)

        if not isinstance(self.require_changes, bool):
            raise WorkspaceVerificationError("require_changes must be a boolean")
        object.__setattr__(
            self,
            "baseline_ref",
            _non_empty_string(self.baseline_ref, "baseline_ref"),
        )
        for field_name in (
            "execution_authorized",
            "execution_capability",
            "execution_granted",
        ):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, bool):
                raise WorkspaceVerificationError(
                    f"{field_name} must be a boolean or None"
                )
        if not isinstance(self.require_execution_authority, bool):
            raise WorkspaceVerificationError(
                "require_execution_authority must be a boolean"
            )
        if live_fence_validator is not None:
            attach_process_local(self, live_fence_validator)

    @property
    def authority_is_explicit(self) -> bool:
        return self.require_execution_authority or any(
            value is not None
            for value in (
                self.execution_authorized,
                self.execution_capability,
                self.execution_granted,
            )
        )


def _verification_request_live_fence_validator(
    request: WorkspaceVerificationRequest,
) -> Callable[..., object] | None:
    """Expose the process-local hook without adding a dataclass field."""

    return get_process_local(request)


WorkspaceVerificationRequest.live_fence_validator = property(
    _verification_request_live_fence_validator
)


@dataclass(frozen=True, slots=True)
class WorkspaceVerificationResult:
    """A candidate verification record; it does not change mission state."""

    accepted: bool
    summary: str
    change_fingerprint: str | None
    checks: tuple[VerificationCheckResult, ...]
    artifacts: tuple[VerificationArtifact, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.accepted, bool):
            raise WorkspaceVerificationError("accepted must be a boolean")
        if not isinstance(self.summary, str):
            raise WorkspaceVerificationError("summary must be a string")
        object.__setattr__(self, "summary", _sanitize_summary(self.summary))
        if self.change_fingerprint is not None and not isinstance(
            self.change_fingerprint, str
        ):
            raise WorkspaceVerificationError(
                "change_fingerprint must be a string or None"
            )

        checks = tuple(self.checks)
        if any(not isinstance(check, VerificationCheckResult) for check in checks):
            raise WorkspaceVerificationError(
                "checks must contain only VerificationCheckResult values"
            )
        object.__setattr__(self, "checks", checks)

        artifacts = tuple(self.artifacts)
        if any(
            not isinstance(artifact, VerificationArtifact) for artifact in artifacts
        ):
            raise WorkspaceVerificationError(
                "artifacts must contain only VerificationArtifact values"
            )
        object.__setattr__(self, "artifacts", artifacts)


@dataclass(slots=True)
class _PipeCapture:
    data: bytearray
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class _ProcessResult:
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: float
    timed_out: bool = False
    error: str | None = None
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    stdout_bytes: bytes = b""


@dataclass(frozen=True, slots=True)
class _WorkspaceSnapshot:
    """Bounded digest of one workspace state at one exact observation point."""

    fingerprint: str
    has_changes: bool
    relative_workspace: Path


def _read_pipe(
    stream: BinaryIO,
    capture: _PipeCapture,
    limit: int | None,
    stream_digest: Any = None,
) -> None:
    """Drain a child pipe while retaining no more than the requested bytes."""

    try:
        while True:
            chunk = stream.read(_PIPE_READ_SIZE)
            if not chunk:
                return
            if stream_digest is not None:
                stream_digest.update(chunk)
            if limit is None:
                capture.data.extend(chunk)
                continue
            remaining = limit - len(capture.data)
            if remaining > 0:
                capture.data.extend(chunk[:remaining])
            if len(chunk) > max(remaining, 0):
                capture.truncated = True
    except (OSError, ValueError):
        capture.truncated = True


class WorkspaceVerifier:
    """Run deterministic git inspection and bounded verification commands."""

    def __init__(
        self,
        cloud_root: Path,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        try:
            self.cloud_root = Path(cloud_root).expanduser().resolve()
        except TypeError as exc:
            raise WorkspaceVerificationError("cloud_root must be a path") from exc
        try:
            self.environment = dict(environment or {})
        except (TypeError, ValueError) as exc:
            raise WorkspaceVerificationError(
                "environment must be a mapping of strings"
            ) from exc

    def _build_environment(self) -> dict[str, str]:
        """Return only the narrow inherited allowlist plus validated overrides."""

        for key, value in self.environment.items():
            if not isinstance(key, str) or _ENVIRONMENT_KEY_PATTERN.fullmatch(key) is None:
                raise WorkspaceVerificationError(
                    f"Invalid environment variable name: {key!r}"
                )
            if not isinstance(value, str):
                raise WorkspaceVerificationError(
                    f"Environment variable {key!r} must have a string value"
                )

        environment = {
            key: os.environ[key]
            for key in _INHERITED_ENVIRONMENT_KEYS
            if key in os.environ
        }
        environment.update(self.environment)
        # Verification must not leave interpreter bytecode or other implicit
        # files that would invalidate the post-command immutable snapshot.
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        return environment

    def verify(self, request: WorkspaceVerificationRequest) -> WorkspaceVerificationResult:
        """Inspect, execute, and return a candidate verification record."""

        if not isinstance(request, WorkspaceVerificationRequest):
            raise WorkspaceVerificationError(
                "request must be a WorkspaceVerificationRequest"
            )

        workspace, relative_workspace = self._validate_workspace(request.workspace)
        environment = self._build_environment()
        live_fence_validator = request.live_fence_validator

        if request.authority_is_explicit:
            if (
                request.execution_authorized is not True
                or live_fence_validator is None
            ):
                return self._authority_rejection()
            if request.commands and (
                request.execution_capability is not True
                or request.execution_granted is not True
            ):
                return self._authority_rejection()
        try:
            self._validate_live_fence(live_fence_validator)
        except WorkspaceVerificationError:
            return self._authority_rejection()

        pre_snapshot, snapshot_error = self._capture_snapshot(
            workspace,
            relative_workspace,
            request.baseline_ref,
            environment,
            live_fence_validator,
        )
        if pre_snapshot is None:
            return WorkspaceVerificationResult(
                accepted=False,
                summary=(
                    "Candidate verification rejected: "
                    + (snapshot_error or "workspace snapshot failed safely.")
                ),
                change_fingerprint=None,
                checks=(),
                artifacts=(),
            )

        if request.require_changes and not pre_snapshot.has_changes:
            return WorkspaceVerificationResult(
                accepted=False,
                summary=(
                    "Candidate verification rejected: "
                    "workspace has no changes relative to the baseline."
                ),
                change_fingerprint=pre_snapshot.fingerprint,
                checks=(),
                artifacts=(),
            )

        executed: list[tuple[VerificationCommand, VerificationCheckResult]] = []
        for command in request.commands:
            process_result = self._run_process(
                command.argv,
                workspace=workspace,
                environment=environment,
                timeout_seconds=command.timeout_seconds,
                stdout_limit=_COMMAND_CAPTURE_LIMIT,
                stderr_limit=_COMMAND_CAPTURE_LIMIT,
                live_fence_validator=live_fence_validator,
            )
            passed = process_result.exit_code == 0 and not process_result.timed_out
            check = VerificationCheckResult(
                name=command.name,
                passed=passed,
                exit_code=process_result.exit_code,
                summary=self._check_summary(process_result),
                duration_ms=process_result.duration_ms,
            )
            executed.append((command, check))
            if not passed:
                break

        checks = tuple(check for _, check in executed)
        all_checks_passed = all(check.passed for check in checks)

        post_snapshot, post_error = self._capture_snapshot(
            workspace,
            relative_workspace,
            request.baseline_ref,
            environment,
            live_fence_validator,
        )
        if post_snapshot is None:
            return WorkspaceVerificationResult(
                accepted=False,
                summary=(
                    "Candidate verification rejected: "
                    + (post_error or "post-command workspace snapshot failed safely.")
                ),
                change_fingerprint=None,
                checks=checks,
                artifacts=(),
            )
        if post_snapshot != pre_snapshot:
            return WorkspaceVerificationResult(
                accepted=False,
                summary=(
                    "Candidate verification rejected: verification commands "
                    "mutated the workspace."
                ),
                change_fingerprint=post_snapshot.fingerprint,
                checks=checks,
                artifacts=(),
            )

        # Artifacts are constructed only from the snapshot that survived the
        # post-command equality check.
        change_fingerprint = post_snapshot.fingerprint
        has_changes = post_snapshot.has_changes
        artifacts: list[VerificationArtifact] = []
        locator_path = self._locator_path(relative_workspace)
        if has_changes:
            artifacts.append(
                VerificationArtifact(
                    name="Workspace diff",
                    locator=(
                        f"workspace-diff://{locator_path}?sha256={change_fingerprint}"
                    ),
                    artifact_kind=ArtifactKind.DIFF,
                    evidence_kind=EvidenceKind.ARTIFACT,
                    summary="Candidate diff for the verified changed workspace.",
                )
            )

        for command, check in executed:
            status_word = "passed" if check.passed else "failed"
            exit_detail = (
                "exit code " + str(check.exit_code)
                if check.exit_code is not None
                else "no exit code"
            )
            artifacts.append(
                VerificationArtifact(
                    name=command.name,
                    locator=(
                        f"workspace-test://{locator_path}?command="
                        f"{quote(command.name, safe='')}&sha256={change_fingerprint}"
                    ),
                    artifact_kind=ArtifactKind.TEST_REPORT,
                    evidence_kind=EvidenceKind.TEST,
                    summary=(
                        f"Verification command {command.name!r} {status_word} "
                        f"({exit_detail})."
                    ),
                )
            )

        accepted = all_checks_passed and post_snapshot == pre_snapshot
        if accepted:
            summary = (
                "Candidate verification accepted: git inspection and "
                f"{len(checks)} verification command(s) passed."
            )
        else:
            failed_check = next(check for check in checks if not check.passed)
            summary = (
                "Candidate verification rejected: verification command "
                f"{failed_check.name!r} failed."
            )

        return WorkspaceVerificationResult(
            accepted=accepted,
            summary=summary,
            change_fingerprint=change_fingerprint,
            checks=checks,
            artifacts=tuple(artifacts),
        )

    @staticmethod
    def _authority_rejection() -> WorkspaceVerificationResult:
        return WorkspaceVerificationResult(
            accepted=False,
            summary=(
                "Candidate verification rejected: workspace execute authority "
                "or the live Kora execution fence was not confirmed."
            ),
            change_fingerprint=None,
            checks=(),
            artifacts=(),
        )

    @staticmethod
    def _validate_live_fence(
        validator: Callable[..., object] | None,
    ) -> None:
        if validator is None:
            return
        try:
            result = invoke_process_local_noarg(validator)
        except Exception as exc:  # noqa: BLE001 - verifier authority boundary
            raise WorkspaceVerificationError(
                "live Kora execution fence validation failed"
            ) from exc
        if result is False:
            raise WorkspaceVerificationError(
                "live Kora execution fence validation was rejected"
            )

    def _capture_snapshot(
        self,
        workspace: Path,
        relative_workspace: Path,
        baseline_ref: str,
        environment: Mapping[str, str],
        live_fence_validator: Callable[..., object] | None,
    ) -> tuple[_WorkspaceSnapshot | None, str | None]:
        """Capture tracked git state and untracked content in bounded memory."""

        digest = hashlib.sha256()
        status_result = self._run_process(
            ("git", "status", "--porcelain=v1"),
            workspace=workspace,
            environment=environment,
            timeout_seconds=_GIT_TIMEOUT_SECONDS,
            stdout_limit=_GIT_CAPTURE_LIMIT,
            stderr_limit=_COMMAND_CAPTURE_LIMIT,
            stream_digest=digest,
            live_fence_validator=live_fence_validator,
        )
        if not self._process_succeeded(status_result):
            return None, (
                "git status failed ("
                + self._process_failure_detail(status_result)
                + ")."
            )

        digest.update(b"\n")
        diff_result = self._run_process(
            ("git", "diff", "--no-ext-diff", "--binary", baseline_ref, "--"),
            workspace=workspace,
            environment=environment,
            timeout_seconds=_GIT_TIMEOUT_SECONDS,
            stdout_limit=_GIT_CAPTURE_LIMIT,
            stderr_limit=_COMMAND_CAPTURE_LIMIT,
            stream_digest=digest,
            live_fence_validator=live_fence_validator,
        )
        if not self._process_succeeded(diff_result):
            return None, (
                "git diff failed ("
                + self._process_failure_detail(diff_result)
                + ")."
            )

        untracked_result = self._run_process(
            ("git", "ls-files", "--others", "--exclude-standard", "-z"),
            workspace=workspace,
            environment=environment,
            timeout_seconds=_GIT_TIMEOUT_SECONDS,
            stdout_limit=_UNTRACKED_PATH_CAPTURE_LIMIT,
            stderr_limit=_COMMAND_CAPTURE_LIMIT,
            live_fence_validator=live_fence_validator,
        )
        if not self._process_succeeded(untracked_result):
            return None, (
                "git untracked-file inspection failed ("
                + self._process_failure_detail(untracked_result)
                + ")."
            )
        if untracked_result.stdout_truncated:
            return None, "workspace contains too many untracked paths to inspect safely."

        try:
            untracked_paths = tuple(
                sorted(
                    {
                        Path(os.fsdecode(path))
                        for path in untracked_result.stdout_bytes.split(b"\0")
                        if path
                    },
                    key=lambda path: path.as_posix().encode(
                        "utf-8", errors="surrogateescape"
                    ),
                )
            )
            for path in untracked_paths:
                self._hash_untracked_entry(digest, workspace, path)
        except WorkspaceVerificationError as exc:
            return None, str(exc)

        return (
            _WorkspaceSnapshot(
                fingerprint=digest.hexdigest(),
                has_changes=bool(status_result.stdout) or bool(untracked_paths),
                relative_workspace=relative_workspace,
            ),
            None,
        )

    @staticmethod
    def _process_succeeded(result: _ProcessResult) -> bool:
        return (
            result.exit_code == 0
            and not result.timed_out
            and result.error is None
        )

    @staticmethod
    def _hash_untracked_entry(
        digest: Any,
        workspace: Path,
        relative_path: Path,
    ) -> None:
        """Hash one untracked entry without following links or buffering files."""

        if (
            relative_path.is_absolute()
            or not relative_path.parts
            or any(part in {"", ".", ".."} for part in relative_path.parts)
            or relative_path.parts[0] == ".git"
        ):
            raise WorkspaceVerificationError(
                "untracked path is not a safe workspace-relative entry"
            )
        candidate = workspace.joinpath(*relative_path.parts)
        lexical_candidate = Path(os.path.abspath(os.fspath(candidate)))
        try:
            lexical_candidate.relative_to(workspace)
        except ValueError as exc:
            raise WorkspaceVerificationError(
                "untracked path escapes the canonical workspace"
            ) from exc

        # Do not follow a symlink or special entry in any parent component.
        # The final component is inspected with lstat below so a symlink itself
        # can be fingerprinted by its link target without dereferencing it.
        parent = workspace
        for part in relative_path.parts[:-1]:
            parent = parent / part
            try:
                parent_stat = os.lstat(parent)
            except OSError as exc:
                raise WorkspaceVerificationError(
                    "untracked workspace parent could not be inspected safely"
                ) from exc
            if stat.S_ISLNK(parent_stat.st_mode) or not stat.S_ISDIR(
                parent_stat.st_mode
            ):
                raise WorkspaceVerificationError(
                    "untracked workspace path contains an unsafe parent entry"
                )

        try:
            entry_stat = os.lstat(candidate)
        except OSError as exc:
            raise WorkspaceVerificationError(
                "untracked workspace entry could not be inspected safely"
            ) from exc

        path_bytes = relative_path.as_posix().encode(
            "utf-8", errors="surrogateescape"
        )
        mode = entry_stat.st_mode
        digest.update(b"\0KORA-UNTRACKED\0")
        digest.update(len(path_bytes).to_bytes(8, "big"))
        digest.update(path_bytes)
        digest.update(stat.S_IFMT(mode).to_bytes(4, "big"))
        digest.update((mode & 0o7777).to_bytes(4, "big"))

        if stat.S_ISREG(mode):
            digest.update(b"F")
            digest.update(entry_stat.st_size.to_bytes(8, "big", signed=False))
            flags = os.O_RDONLY
            flags |= getattr(os, "O_NOFOLLOW", 0)
            try:
                descriptor = os.open(candidate, flags)
            except OSError as exc:
                raise WorkspaceVerificationError(
                    "untracked file could not be opened without following links"
                ) from exc
            try:
                opened_stat = os.fstat(descriptor)
                if (
                    opened_stat.st_dev != entry_stat.st_dev
                    or opened_stat.st_ino != entry_stat.st_ino
                    or opened_stat.st_size != entry_stat.st_size
                    or stat.S_IFMT(opened_stat.st_mode) != stat.S_IFMT(mode)
                    or (opened_stat.st_mode & 0o7777) != (mode & 0o7777)
                ):
                    raise WorkspaceVerificationError(
                        "untracked file changed while it was being inspected"
                    )
                with os.fdopen(descriptor, "rb", closefd=True) as stream:
                    while True:
                        chunk = stream.read(_PIPE_READ_SIZE)
                        if not chunk:
                            break
                        digest.update(chunk)
                    descriptor = -1
                final_stat = os.stat(candidate, follow_symlinks=False)
                if (
                    final_stat.st_dev != entry_stat.st_dev
                    or final_stat.st_ino != entry_stat.st_ino
                    or final_stat.st_size != entry_stat.st_size
                    or (final_stat.st_mode & 0o7777) != (mode & 0o7777)
                ):
                    raise WorkspaceVerificationError(
                        "untracked file changed while it was being inspected"
                    )
            finally:
                if descriptor >= 0:
                    os.close(descriptor)
            return

        if stat.S_ISLNK(mode):
            digest.update(b"L")
            try:
                target = os.readlink(os.fsencode(candidate))
            except OSError as exc:
                raise WorkspaceVerificationError(
                    "untracked symlink could not be inspected safely"
                ) from exc
            if isinstance(target, str):
                target = target.encode("utf-8", errors="surrogateescape")
            digest.update(len(target).to_bytes(8, "big"))
            digest.update(target)
            return

        if stat.S_ISDIR(mode):
            digest.update(b"D")
            return

        raise WorkspaceVerificationError(
            "special untracked workspace entries are not permitted"
        )

    def _validate_workspace(self, workspace_value: Path) -> tuple[Path, Path]:
        try:
            workspace = Path(workspace_value).expanduser().resolve(strict=True)
        except (TypeError, OSError, RuntimeError, ValueError) as exc:
            raise WorkspaceVerificationError(
                "workspace must resolve to an existing directory"
            ) from exc
        if not workspace.is_dir():
            raise WorkspaceVerificationError(
                f"workspace is not a directory: {workspace}"
            )
        try:
            relative_workspace = workspace.relative_to(self.cloud_root)
        except ValueError as exc:
            raise WorkspaceVerificationError(
                f"workspace is outside Kora cloud root: {workspace}"
            ) from exc
        return workspace, relative_workspace

    def _run_process(
        self,
        argv: tuple[str, ...],
        *,
        workspace: Path,
        environment: Mapping[str, str],
        timeout_seconds: float,
        stdout_limit: int | None,
        stderr_limit: int | None,
        stream_digest: Any = None,
        live_fence_validator: Callable[..., object] | None = None,
    ) -> _ProcessResult:
        started = time.monotonic()
        try:
            self._validate_live_fence(live_fence_validator)
            process = subprocess.Popen(
                list(argv),
                cwd=workspace,
                env=dict(environment),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
            )
        except (OSError, ValueError, WorkspaceVerificationError) as exc:
            return _ProcessResult(
                exit_code=None,
                stdout="",
                stderr="",
                duration_ms=self._duration_ms(started),
                error=str(exc),
                stdout_bytes=b"",
            )

        stdout_capture = _PipeCapture(bytearray())
        stderr_capture = _PipeCapture(bytearray())
        assert process.stdout is not None
        assert process.stderr is not None
        stdout_thread = threading.Thread(
            target=_read_pipe,
            args=(process.stdout, stdout_capture, stdout_limit, stream_digest),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=_read_pipe,
            args=(process.stderr, stderr_capture, stderr_limit),
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()

        timed_out = False
        exit_code: int | None
        error: str | None = None
        try:
            exit_code = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            exit_code = None
            try:
                process.kill()
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=5.0)
            except (OSError, subprocess.TimeoutExpired) as exc:
                error = str(exc)
        except OSError as exc:
            exit_code = None
            error = str(exc)

        stdout_thread.join(timeout=1.0)
        stderr_thread.join(timeout=1.0)
        for stream in (process.stdout, process.stderr):
            try:
                stream.close()
            except OSError:
                pass
        stdout_thread.join(timeout=0.1)
        stderr_thread.join(timeout=0.1)

        stdout_bytes = bytes(stdout_capture.data)
        return _ProcessResult(
            exit_code=exit_code,
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=bytes(stderr_capture.data).decode("utf-8", errors="replace"),
            duration_ms=self._duration_ms(started),
            timed_out=timed_out,
            error=error,
            stdout_truncated=stdout_capture.truncated,
            stderr_truncated=stderr_capture.truncated,
            stdout_bytes=stdout_bytes,
        )

    @staticmethod
    def _duration_ms(started: float) -> float:
        return max(0.0, (time.monotonic() - started) * 1000.0)

    @staticmethod
    def _check_summary(result: _ProcessResult) -> str:
        parts: list[str] = []
        if result.stdout:
            parts.append("stdout:\n" + result.stdout)
        if result.stderr:
            parts.append("stderr:\n" + result.stderr)
        if result.stdout_truncated or result.stderr_truncated:
            parts.append("[output truncated]")
        if result.timed_out:
            parts.insert(0, "command timed out")
        if result.error:
            parts.insert(0, "process error: " + result.error)
        if not parts:
            return "command completed with no output"
        return "\n".join(parts)

    @staticmethod
    def _process_failure_detail(result: _ProcessResult) -> str:
        if result.timed_out:
            return "timed out"
        if result.exit_code is not None:
            return "exit code " + str(result.exit_code)
        if result.error:
            return "process error: " + result.error
        return "process did not complete"

    @staticmethod
    def _locator_path(relative_workspace: Path) -> str:
        return quote(relative_workspace.as_posix(), safe="/._-~")


__all__ = [
    "VerificationArtifact",
    "VerificationCheckResult",
    "VerificationCommand",
    "WorkspaceVerificationError",
    "WorkspaceVerificationRequest",
    "WorkspaceVerificationResult",
    "WorkspaceVerifier",
]

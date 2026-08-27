"""Private workspace identity and descriptor-bound process helpers."""

from __future__ import annotations

import functools
import os
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


class WorkspaceIdentityError(ValueError):
    """A workspace cannot be bound to its previously authorized identity."""


def _directory_open_flags() -> int:
    """Return the strict directory-open flags supported by this platform."""

    if os.name != "posix":
        raise WorkspaceIdentityError(
            "descriptor-bound workspace execution is unsupported on this platform"
        )
    directory_flag = getattr(os, "O_DIRECTORY", None)
    nofollow_flag = getattr(os, "O_NOFOLLOW", None)
    if not isinstance(directory_flag, int) or not isinstance(nofollow_flag, int):
        raise WorkspaceIdentityError(
            "descriptor-bound workspace execution is unsupported on this platform"
        )
    return os.O_RDONLY | directory_flag | nofollow_flag


def _open_directory(path: Path) -> int:
    try:
        descriptor = os.open(path, _directory_open_flags())
    except (OSError, TypeError, ValueError) as exc:
        raise WorkspaceIdentityError(
            "authorized workspace could not be opened as a stable directory"
        ) from exc
    try:
        observed = os.fstat(descriptor)
        if not stat.S_ISDIR(observed.st_mode):
            raise WorkspaceIdentityError(
                "authorized workspace descriptor is not a directory"
            )
    except Exception:
        os.close(descriptor)
        raise
    return descriptor


@dataclass(frozen=True, slots=True)
class WorkspaceIdentity:
    """The private identity of one authorized workspace directory."""

    canonical_path: Path
    st_dev: int
    st_ino: int

    def __post_init__(self) -> None:
        if not isinstance(self.canonical_path, Path) or not self.canonical_path.is_absolute():
            raise WorkspaceIdentityError(
                "workspace identity must contain an absolute canonical path"
            )
        for field_name in ("st_dev", "st_ino"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise WorkspaceIdentityError(
                    f"workspace identity {field_name} must be an integer"
                )

    @classmethod
    def capture(cls, workspace: Path) -> "WorkspaceIdentity":
        """Resolve and capture a directory identity without retaining a handle."""

        try:
            canonical_path = Path(workspace).expanduser().resolve(strict=True)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise WorkspaceIdentityError(
                "workspace must resolve to an existing directory"
            ) from exc

        descriptor = _open_directory(canonical_path)
        try:
            observed = os.fstat(descriptor)
            return cls(
                canonical_path=canonical_path,
                st_dev=observed.st_dev,
                st_ino=observed.st_ino,
            )
        finally:
            os.close(descriptor)

    def assert_path(self, workspace: Path) -> None:
        """Reject a path that no longer resolves to this captured identity."""

        try:
            canonical_path = Path(workspace).expanduser().resolve(strict=True)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise WorkspaceIdentityError(
                "workspace no longer resolves to its authorized directory"
            ) from exc
        if canonical_path != self.canonical_path:
            raise WorkspaceIdentityError(
                "workspace path no longer resolves to its authorized directory"
            )

    @contextmanager
    def open_descriptor(self) -> Iterator[int]:
        """Open and verify a fresh descriptor for this exact directory."""

        descriptor = _open_directory(self.canonical_path)
        try:
            observed = os.fstat(descriptor)
            if (
                observed.st_dev != self.st_dev
                or observed.st_ino != self.st_ino
            ):
                raise WorkspaceIdentityError(
                    "workspace identity changed before the effect boundary"
                )
            yield descriptor
        finally:
            os.close(descriptor)


def _fchdir_and_close(descriptor: int) -> None:
    """Bind a child cwd to an inherited descriptor, then drop the handle."""

    try:
        os.fchdir(descriptor)
    finally:
        os.close(descriptor)


def descriptor_cwd_kwargs(descriptor: int) -> dict[str, object]:
    """Return subprocess kwargs that never resolve a workspace pathname."""

    if os.name != "posix" or not callable(getattr(os, "fchdir", None)):
        raise WorkspaceIdentityError(
            "descriptor-bound workspace execution is unsupported on this platform"
        )
    if isinstance(descriptor, bool) or not isinstance(descriptor, int) or descriptor < 0:
        raise WorkspaceIdentityError("workspace descriptor is invalid")
    return {
        "cwd": None,
        "pass_fds": (descriptor,),
        "preexec_fn": functools.partial(_fchdir_and_close, descriptor),
    }


__all__ = ["WorkspaceIdentity", "WorkspaceIdentityError", "descriptor_cwd_kwargs"]

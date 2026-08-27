"""Process-local hooks that must never cross a public data boundary.

The mission controller uses these hooks to re-check authority at the exact
effect boundary.  Keeping callbacks in a weak process-local registry means
``dataclasses.asdict`` and normal representations of the immutable contracts
cannot serialize a controller, database connection, or closure by accident.
"""

from __future__ import annotations

import inspect
import weakref
from collections.abc import Callable
from threading import RLock
from typing import Any


_lock = RLock()
_callbacks: dict[int, tuple[weakref.ReferenceType[Any], Callable[..., object]]] = {}


def attach(owner: object, callback: Callable[..., object] | None) -> None:
    """Attach a callback to ``owner`` without storing it on the public record."""

    if callback is None:
        return
    if not callable(callback):
        raise TypeError("process-local callback must be callable")

    key = id(owner)

    def remove(reference: weakref.ReferenceType[Any], *, key: int = key) -> None:
        with _lock:
            current = _callbacks.get(key)
            if current is not None and current[0] is reference:
                _callbacks.pop(key, None)

    reference = weakref.ref(owner, remove)
    with _lock:
        _callbacks[key] = (reference, callback)


def get(owner: object) -> Callable[..., object] | None:
    """Return the live callback attached to ``owner``, if any."""

    key = id(owner)
    with _lock:
        current = _callbacks.get(key)
        if current is None:
            return None
        if current[0]() is owner:
            return current[1]
        _callbacks.pop(key, None)
        return None


def invoke(callback: Callable[..., object], argument: object) -> object:
    """Invoke a one-argument hook, accepting a legacy zero-argument hook too."""

    try:
        signature = inspect.signature(callback)
    except (TypeError, ValueError):
        return callback(argument)
    try:
        signature.bind(argument)
    except TypeError:
        signature.bind()
        return callback()
    return callback(argument)


def invoke_noarg(callback: Callable[..., object]) -> object:
    """Invoke a hook that normally has no public data argument."""

    try:
        signature = inspect.signature(callback)
    except (TypeError, ValueError):
        return callback()
    try:
        signature.bind()
    except TypeError:
        signature.bind(None)
        return callback(None)
    return callback()

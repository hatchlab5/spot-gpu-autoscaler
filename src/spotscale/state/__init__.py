"""State backends. `get_state()` builds one by name."""

from __future__ import annotations

from .base import StateBackend
from .json_state import JsonStateBackend
from .sqlite_state import SqliteStateBackend

__all__ = [
    "StateBackend",
    "JsonStateBackend",
    "SqliteStateBackend",
    "get_state",
]


def get_state(kind: str = "json", path: str = None) -> StateBackend:
    kind = (kind or "json").lower()
    if kind == "json":
        return JsonStateBackend(path or "spotscale-state.json")
    if kind == "sqlite":
        return SqliteStateBackend(path or "spotscale-state.db")
    raise ValueError(f"unknown state backend: {kind!r} (known: json, sqlite)")


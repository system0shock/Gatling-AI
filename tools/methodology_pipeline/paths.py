"""Helpers for reading and writing dotted mapping targets."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


MISSING = object()


def is_blank_string(value: Any) -> bool:
    """Return whether a value is a string with no non-whitespace content."""
    return isinstance(value, str) and not value.strip()


def get_target(root: Mapping[str, Any], dotted: str) -> Any:
    """Return a dotted target's value, or MISSING when it is absent."""
    current: Any = root
    for part in dotted.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return MISSING
        current = current[part]
    return current


def set_target(root: dict[str, Any], dotted: str, value: Any) -> None:
    """Set a dotted target, creating intermediate mappings as needed."""
    parts = dotted.split(".")
    current = root
    for part in parts[:-1]:
        child = current.setdefault(part, {})
        if not isinstance(child, dict):
            raise ValueError(f"{dotted}: {part} is not an object")
        current = child
    current[parts[-1]] = value

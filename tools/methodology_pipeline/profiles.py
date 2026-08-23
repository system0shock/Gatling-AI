"""Resolve a methodology profile with deterministic value provenance."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from .contracts import validate_artifact
from .paths import set_target


def _default_sources(profile: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    sources: dict[str, dict[str, str]] = {}

    def visit(value: Any, prefix: str = "") -> None:
        if isinstance(value, Mapping):
            for key in sorted(value):
                if key != "sources":
                    child_prefix = f"{prefix}.{key}" if prefix else key
                    visit(value[key], child_prefix)
        elif isinstance(value, (str, int, float, bool)):
            sources[prefix] = {"source": "default-v1"}

    visit(profile)
    return sources


def resolve_profile(
    default_profile: Mapping[str, Any],
    answers: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply manual metadata then user overrides to a default profile."""
    resolved = copy.deepcopy(dict(default_profile))
    resolved["sources"] = _default_sources(resolved)
    profile_answers = answers.get("profile", {})

    accepted = profile_answers.get("accepted", False)
    if not isinstance(accepted, bool):
        raise ValueError("profile.accepted must be boolean")

    for target, item in sorted(profile_answers.get("meta_values", {}).items()):
        set_target(resolved, target, item["value"])
        source = {"source": "meta-manual"}
        if "source_reference" in item:
            source["source_reference"] = item["source_reference"]
        resolved["sources"][target] = source
    for target, item in sorted(profile_answers.get("overrides", {}).items()):
        set_target(resolved, target, item["value"])
        source = {"source": "user"}
        if "source_reference" in item:
            source["source_reference"] = item["source_reference"]
        resolved["sources"][target] = source
    resolved["accepted"] = accepted
    validate_artifact(resolved, "methodology-profile.schema.json")
    return resolved

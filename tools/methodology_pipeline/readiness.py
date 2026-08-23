"""Blocking readiness evaluation for methodology execution inputs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .paths import MISSING, get_target


CRITICAL_TARGETS = (
    "profile.accepted",
    "load.unit",
    "load.initial",
    "load.step_increment",
    "load.operation_mix",
    "environment.name",
    "observability.cpu_signal",
    "observability.memory_signal",
    "observability.memory_growth_window",
    "observability.dashboard",
    "test_data.ready",
)


def readiness_report(
    methodology_input: Mapping[str, Any],
    pending_questions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Return the deterministic set of missing inputs that block testing."""
    by_target = {item["target"]: item["id"] for item in pending_questions}
    missing: list[dict[str, Any]] = []
    surface = methodology_input.get("surface", {})
    if (
        surface.get("status") != "confirmed"
        or not (surface.get("included", []) or surface.get("added", []))
    ):
        missing.append({
            "target": "surface.entities",
            "question_id": None,
            "message": "confirmed test surface must contain at least one entity",
        })
    for target in CRITICAL_TARGETS:
        value = get_target(methodology_input, target)
        if value is MISSING or value is None or value == "" or value is False:
            missing.append({
                "target": target,
                "question_id": by_target.get(target),
                "message": f"required execution input is missing: {target}",
            })
    return {
        "version": 1,
        "status": "ready" if not missing else "blocked",
        "ready_for_test": not missing,
        "workspace_snapshot_id": methodology_input["workspace_snapshot_id"],
        "missing": missing,
    }

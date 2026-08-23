"""Assembly of the canonical methodology rendering input."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from .contracts import validate_artifact
from .questionnaire import apply_scalar_answers


def build_input(
    snapshot: Mapping[str, Any],
    surface_review: Mapping[str, Any],
    resolved_profile: Mapping[str, Any],
    catalog: Mapping[str, Any],
    answers: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind approved inputs and answers into one valid methodology input."""
    if surface_review["snapshot_id"] != snapshot["snapshot_id"]:
        raise ValueError("surface review does not match workspace snapshot")
    base = {
        "version": 1,
        "workspace_snapshot_id": snapshot["snapshot_id"],
        "surface": copy.deepcopy(dict(surface_review)),
        "profile": copy.deepcopy(dict(resolved_profile)),
        "load": {},
        "environment": {},
        "observability": {},
        "test_data": {},
        "document": {},
        "not_applicable_sections": copy.deepcopy(
            list(answers.get("not_applicable_sections", []))
        ),
    }
    result = apply_scalar_answers(base, catalog, answers)
    validate_artifact(result, "methodology-input.schema.json")
    return result

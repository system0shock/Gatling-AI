"""Assembly of the canonical methodology rendering input."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from typing import Any

from .contracts import validate_artifact
from .questionnaire import apply_scalar_answers
from .sections import SURFACE_ENTITY_TYPES_BY_SECTION


_SNAPSHOT_ID = re.compile(r"^[0-9a-f]{64}$")


def _snapshot_id(snapshot: Mapping[str, Any]) -> str:
    if not isinstance(snapshot, Mapping):
        raise ValueError("workspace snapshot must be a mapping")
    snapshot_id = snapshot.get("snapshot_id")
    if not isinstance(snapshot_id, str) or not _SNAPSHOT_ID.fullmatch(snapshot_id):
        raise ValueError("workspace snapshot must contain a lowercase hexadecimal snapshot_id")
    return snapshot_id


def capabilities_from_surface(surface_review: Mapping[str, Any]) -> tuple[str, ...]:
    """Derive normalized protocol capabilities from confirmed test entities."""
    capabilities = set()
    for group in ("included", "added"):
        for entity in surface_review.get(group, []):
            if not isinstance(entity, Mapping):
                continue
            attributes = entity.get("attributes", {})
            protocol = attributes.get("protocol") if isinstance(attributes, Mapping) else None
            if isinstance(protocol, str) and (normalized := protocol.strip().lower()):
                capabilities.add(normalized)
    return tuple(sorted(capabilities))


def _validate_not_applicable_surface(
    surface_review: Mapping[str, Any], answers: Mapping[str, Any]
) -> None:
    selected_types = {
        entity["entity_type"]
        for group in ("included", "added")
        for entity in surface_review[group]
    }
    for decision in answers["not_applicable_sections"]:
        section_id = decision["section_id"]
        entity_types = SURFACE_ENTITY_TYPES_BY_SECTION.get(section_id)
        if entity_types is not None and not selected_types.isdisjoint(entity_types):
            raise ValueError(
                "not applicable section conflicts with selected surface entities: "
                f"{section_id}"
            )


def build_input(
    snapshot: Mapping[str, Any],
    surface_review: Mapping[str, Any],
    resolved_profile: Mapping[str, Any],
    catalog: Mapping[str, Any],
    answers: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind approved inputs and answers into one valid methodology input."""
    snapshot_id = _snapshot_id(snapshot)
    validate_artifact(surface_review, "methodology-surface-review.schema.json")
    validate_artifact(resolved_profile, "methodology-profile.schema.json")
    validate_artifact(catalog, "methodology-questions.schema.json")
    validate_artifact(answers, "methodology-answers.schema.json")
    if surface_review["snapshot_id"] != snapshot_id:
        raise ValueError("surface review does not match workspace snapshot")
    _validate_not_applicable_surface(surface_review, answers)
    base = {
        "version": 1,
        "workspace_snapshot_id": snapshot_id,
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

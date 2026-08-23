"""Apply explicit grouped decisions to one validated discovery candidate."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
import json
from typing import Any

if __package__:
    from . import contracts, merge
else:
    import contracts
    import merge


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"value is not canonical JSON: {exc}") from exc


def _unique_index(records: Sequence[Mapping[str, Any]], key: str, label: str) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for raw in records:
        value = raw[key]
        if value in indexed:
            raise ValueError(f"duplicate {label}: {value}")
        indexed[value] = deepcopy(dict(raw))
    return indexed


def _source_key(source: Mapping[str, Any]) -> tuple[str, str, str, str, str, str]:
    return (
        source["repo_id"], source["revision"], source["path"], source["pointer"], source["selection_reason"], source["sha256"]
    )


def _review_source(source: Mapping[str, Any]) -> dict[str, str]:
    return {
        "repo_id": source["repo_id"],
        "revision": source["revision"],
        "relative_path": source["path"],
        "pointer": source["pointer"],
        "selection_reason": source["selection_reason"],
        "sha256": source["sha256"],
    }


_OMIT = object()


def _review_attribute_value(value: Any) -> Any:
    if value is None:
        return _OMIT
    if isinstance(value, list):
        return [deepcopy(item) for item in value if item is not None]
    return deepcopy(value)


def _review_attributes(attributes: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in sorted(attributes):
        value = _review_attribute_value(attributes[key])
        if value is not _OMIT:
            result[key] = value
    return result


def _review_entity(entity: Mapping[str, Any], *, excluded: bool = False) -> dict[str, Any]:
    attributes = _review_attributes(entity["attributes"])
    if excluded:
        attributes["exclusion_reason"] = "scope-excluded"
    return {
        "entity_type": entity["entity_type"],
        "canonical_key": entity["canonical_key"],
        "display_name": entity["display_name"],
        "attributes": {key: attributes[key] for key in sorted(attributes)},
        "sources": [_review_source(source) for source in sorted(entity["sources"], key=_source_key)],
    }


def _selection(candidate_keys: set[str], decisions: Mapping[str, Any]) -> tuple[set[str], set[str]]:
    include = set(decisions["include"])
    exclude = set(decisions["exclude"])
    unknown = (include | exclude) - candidate_keys
    if unknown:
        raise ValueError(f"unknown entity reference: {sorted(unknown)[0]}")
    overlap = include & exclude
    if overlap:
        raise ValueError(f"entity appears in both include and exclude: {sorted(overlap)[0]}")
    included = candidate_keys - exclude if decisions["accept_all"] else include
    return included, candidate_keys - included


def _validate_candidate_references(candidate: Mapping[str, Any], entity_keys: set[str]) -> None:
    _unique_index(candidate["review_groups"], "group_id", "review group")
    _unique_index(candidate["conflicts"], "conflict_id", "candidate conflict")
    _unique_index(candidate["possible_duplicates"], "duplicate_id", "candidate duplicate")
    conflict_targets: set[tuple[str, str]] = set()
    for group in candidate["review_groups"]:
        missing = set(group["entity_keys"]) - entity_keys
        if missing:
            raise ValueError(f"review group references unknown entity: {sorted(missing)[0]}")
    expected_groups = merge.review_groups_for(candidate["entities"])
    if candidate["review_groups"] != expected_groups:
        raise ValueError("review_groups do not match deterministic derivation")
    for conflict in candidate["conflicts"]:
        canonical_key = conflict["canonical_key"]
        if canonical_key not in entity_keys:
            raise ValueError(f"conflict references unknown entity: {canonical_key}")
        target = (canonical_key, conflict["attribute"])
        if target in conflict_targets:
            raise ValueError(f"duplicate conflict target: {canonical_key}/{conflict['attribute']}")
        conflict_targets.add(target)
    for duplicate in candidate["possible_duplicates"]:
        missing = set(duplicate["entity_keys"]) - entity_keys
        if missing:
            raise ValueError(f"possible duplicate references unknown entity: {sorted(missing)[0]}")
    expected_duplicates = merge.possible_duplicates_for(candidate["entities"])
    if candidate["possible_duplicates"] != expected_duplicates:
        raise ValueError("possible_duplicates do not match deterministic derivation")


def _apply_conflicts(
    entities: dict[str, dict[str, Any]],
    conflicts: Sequence[Mapping[str, Any]],
    resolutions: Sequence[Mapping[str, Any]],
) -> None:
    by_conflict = _unique_index(conflicts, "conflict_id", "candidate conflict")
    by_resolution = _unique_index(resolutions, "conflict_id", "conflict resolution")
    unknown = set(by_resolution) - set(by_conflict)
    if unknown:
        raise ValueError(f"unknown conflict resolution: {sorted(unknown)[0]}")
    missing = set(by_conflict) - set(by_resolution)
    if missing:
        raise ValueError(f"unresolved conflict: {sorted(missing)[0]}")
    for conflict_id in sorted(by_conflict):
        conflict = by_conflict[conflict_id]
        resolution = by_resolution[conflict_id]
        offered = {_canonical_json(item["value"]): deepcopy(item["value"]) for item in conflict["values"]}
        token = _canonical_json(resolution["value"])
        if token not in offered:
            raise ValueError(f"conflict resolution is not an offered value: {conflict_id}")
        canonical_key = conflict["canonical_key"]
        if canonical_key not in entities:
            raise ValueError(f"conflict references unknown entity: {canonical_key}")
        selected = offered[token]
        attribute = conflict["attribute"]
        entity = entities[canonical_key]
        if attribute == merge.ENTITY_TYPE_CONFLICT:
            if selected not in {"component", "interface", "integration", "flow"}:
                raise ValueError(f"invalid entity_type conflict resolution: {conflict_id}")
            entity["entity_type"] = selected
        elif attribute == merge.DISPLAY_NAME_CONFLICT:
            if not isinstance(selected, str) or not selected:
                raise ValueError(f"invalid display_name conflict resolution: {conflict_id}")
            entity["display_name"] = selected
        elif attribute == merge.SERVICE_IDENTITY_CONFLICT:
            if (
                not isinstance(selected, list)
                or len(selected) != 2
                or not isinstance(selected[0], str)
                or not selected[0]
                or selected[1] not in {"contract", "manifest", "metadata", "unknown"}
            ):
                raise ValueError(f"invalid service_identity conflict resolution: {conflict_id}")
            entity["service_identity"] = {"value": selected[0], "basis": selected[1]}
        elif selected is None:
            entity["attributes"].pop(attribute, None)
        else:
            entity["attributes"][attribute] = selected
        entities[canonical_key]["attributes"] = {
            key: entities[canonical_key]["attributes"][key]
            for key in sorted(entities[canonical_key]["attributes"])
        }


def _merge_duplicate_entities(target: str, members: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    entity_types = {item["entity_type"] for item in members}
    if len(entity_types) != 1:
        raise ValueError("duplicate merge members must have one entity_type")
    attributes: dict[str, Any] = {}
    for member in members:
        for name, value in member["attributes"].items():
            if name in attributes and _canonical_json(attributes[name]) != _canonical_json(value):
                raise ValueError(f"duplicate merge has unresolved attribute conflict: {name}")
            attributes[name] = deepcopy(value)
    sources: dict[str, dict[str, Any]] = {}
    for member in members:
        for source in member["sources"]:
            sources[_canonical_json(source)] = deepcopy(dict(source))
    selected = next(item for item in members if item["canonical_key"] == target)
    result = deepcopy(dict(selected))
    result["attributes"] = {key: attributes[key] for key in sorted(attributes)}
    result["sources"] = sorted(sources.values(), key=_source_key)
    result["confidence"] = "confirmed" if any(item["confidence"] == "confirmed" for item in members) else "candidate"
    return result


def _apply_duplicate_merges(
    entities: dict[str, dict[str, Any]],
    included: set[str],
    excluded: set[str],
    duplicates: Sequence[Mapping[str, Any]],
    decisions: Sequence[Mapping[str, Any]],
) -> None:
    by_duplicate = _unique_index(duplicates, "duplicate_id", "candidate duplicate")
    by_decision = _unique_index(decisions, "duplicate_id", "duplicate merge")
    unknown = set(by_decision) - set(by_duplicate)
    if unknown:
        raise ValueError(f"unknown duplicate merge: {sorted(unknown)[0]}")
    used_members: set[str] = set()
    for duplicate_id in sorted(by_decision):
        duplicate = by_duplicate[duplicate_id]
        target = by_decision[duplicate_id]["canonical_key"]
        members = list(duplicate["entity_keys"])
        if target not in members:
            raise ValueError(f"duplicate merge canonical_key must be a member: {duplicate_id}")
        missing = set(members) - set(entities)
        if missing:
            raise ValueError(f"duplicate merge references unknown entity: {sorted(missing)[0]}")
        overlap = used_members & set(members)
        if overlap:
            raise ValueError(f"duplicate merge groups overlap: {sorted(overlap)[0]}")
        used_members.update(members)
        dispositions = {"included" if key in included else "excluded" for key in members}
        if len(dispositions) != 1:
            raise ValueError(f"duplicate merge members have different scope decisions: {duplicate_id}")
        merged = _merge_duplicate_entities(target, [entities[key] for key in members])
        for key in members:
            entities.pop(key)
            included.discard(key)
            excluded.discard(key)
        entities[target] = merged
        if "included" in dispositions:
            included.add(target)
        else:
            excluded.add(target)


def _manual_entities(
    additions: Sequence[Mapping[str, Any]],
    candidate_id: str,
    forbidden_keys: set[str],
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for raw in additions:
        canonical_key = raw["canonical_key"]
        if canonical_key in seen:
            raise ValueError(f"duplicate manual canonical_key: {canonical_key}")
        if canonical_key in forbidden_keys:
            raise ValueError(f"manual canonical_key already exists: {canonical_key}")
        seen.add(canonical_key)
        result.append({
            "entity_type": raw["entity_type"],
            "canonical_key": canonical_key,
            "display_name": raw["display_name"],
            "attributes": _review_attributes(raw["attributes"]),
            "sources": [{
                "repo_id": "user",
                "revision": candidate_id,
                "relative_path": "surface-review",
                "pointer": canonical_key,
                "selection_reason": "manual-addition",
                "sha256": candidate_id,
            }],
        })
    return result


def apply_surface_decisions(
    candidate: Mapping[str, Any], decisions: Mapping[str, Any]
) -> dict[str, Any]:
    """Validate and apply one complete, explicit decision set without mutation."""
    if not isinstance(candidate, Mapping):
        raise ValueError("candidate must be a mapping")
    if not isinstance(decisions, Mapping):
        raise ValueError("decisions must be a mapping")
    candidate_value = deepcopy(dict(candidate))
    decisions_value = deepcopy(dict(decisions))
    contracts.validate_artifact(candidate_value, "methodology-surface-candidate.schema.json")
    contracts.validate_artifact(decisions_value, "methodology-surface-decisions.schema.json")
    if candidate_value["candidate_id"] != merge.candidate_id_for(candidate_value):
        raise ValueError("candidate_id does not match candidate content")
    if decisions_value["candidate_id"] != candidate_value["candidate_id"]:
        raise ValueError("candidate_id does not match the reviewed candidate")

    entities = _unique_index(candidate_value["entities"], "canonical_key", "candidate entity")
    original_entity_keys = set(entities)
    _validate_candidate_references(candidate_value, set(entities))
    included, excluded = _selection(set(entities), decisions_value)
    _apply_conflicts(entities, candidate_value["conflicts"], decisions_value["conflict_resolutions"])
    _apply_duplicate_merges(
        entities,
        included,
        excluded,
        candidate_value["possible_duplicates"],
        decisions_value["duplicate_merges"],
    )
    additions = _manual_entities(
        decisions_value["add"], candidate_value["candidate_id"], original_entity_keys
    )

    order = lambda item: (item["entity_type"], item["canonical_key"])
    review = {
        "version": 1,
        "snapshot_id": candidate_value["snapshot_id"],
        "status": "confirmed",
        "included": sorted((_review_entity(entities[key]) for key in included), key=order),
        "excluded": sorted((_review_entity(entities[key], excluded=True) for key in excluded), key=order),
        "added": sorted(additions, key=order),
    }
    contracts.validate_artifact(review, "methodology-surface-review.schema.json")
    return review

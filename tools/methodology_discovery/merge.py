"""Deterministically merge bounded repository findings into one review candidate."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from copy import deepcopy
import hashlib
import json
import re
from typing import Any

if __package__:
    from . import contracts
else:
    import contracts


_HTTP_PARAMETER = re.compile(r"\{\s*([^{}]+?)\s*\}")
_EXPLICIT_IDENTITY_BASES = frozenset({"contract", "manifest"})
ENTITY_TYPE_CONFLICT = "__entity_type__"
DISPLAY_NAME_CONFLICT = "__display_name__"
SERVICE_IDENTITY_CONFLICT = "__service_identity__"
_DIRECTION = {
    "publish": "publish",
    "send": "publish",
    "subscribe": "subscribe",
    "receive": "subscribe",
    "unspecified": "unspecified",
}


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"value is not canonical JSON: {exc}") from exc


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        value = value.to_dict()
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping or expose to_dict()")
    return deepcopy(dict(value))


def _source_key(source: Mapping[str, Any]) -> tuple[str, str, str, str, str, str]:
    return (
        source["repo_id"],
        source["revision"],
        source["path"],
        source["pointer"],
        source["selection_reason"],
        source["sha256"],
    )


def _diagnostic_key(value: Mapping[str, Any]) -> tuple[str, str, str]:
    return (str(value.get("code", "")), str(value.get("path", "")), str(value.get("message", "")))


def _unique_sorted(records: Sequence[Mapping[str, Any]], key: Any) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for record in records:
        copied = deepcopy(dict(record))
        unique[_canonical_json(copied)] = copied
    return sorted(unique.values(), key=key)


def _canonical_scalar_or_array(value: Any) -> Any:
    return deepcopy(value)


def _canonical_path(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError("HTTP path must be a non-empty string")
    path = value.strip().replace("\\", "/")
    path = re.sub(r"/+", "/", path)
    if not path.startswith("/"):
        path = "/" + path
    path = _HTTP_PARAMETER.sub(lambda match: "{" + match.group(1).strip().casefold() + "}", path)
    return path.rstrip("/") or "/"


def _key_parts(canonical_key: str) -> list[str]:
    if not isinstance(canonical_key, str) or not canonical_key.strip():
        raise ValueError("candidate canonical_key must be non-empty")
    return [part.strip() for part in canonical_key.strip().split(":")]


def _protocol_kind(candidate: Mapping[str, Any]) -> str:
    parts = _key_parts(candidate["canonical_key"])
    return parts[0].casefold()


def _service_segment(candidate: Mapping[str, Any]) -> tuple[str, bool]:
    identity = candidate["service_identity"]
    basis = identity["basis"]
    explicit = basis in _EXPLICIT_IDENTITY_BASES
    if explicit:
        return str(identity["value"]).strip(), True
    repo_id = str(candidate["source"]["repo_id"]).strip()
    return f"repo-{repo_id}", False


def _from_key(parts: Sequence[str], index: int, default: str = "") -> str:
    return parts[index] if len(parts) > index else default


def _normalize_candidate(value: Mapping[str, Any]) -> tuple[dict[str, Any], str | None, bool]:
    item = deepcopy(dict(value))
    parts = _key_parts(item["canonical_key"])
    attributes = {
        key: _canonical_scalar_or_array(raw)
        for key, raw in sorted(item["attributes"].items())
    }
    service, explicit = _service_segment(item)
    kind = _protocol_kind(item)
    signature: str | None = None

    if kind == "http":
        method = str(attributes.get("method") or _from_key(parts, 2)).strip().upper()
        path = _canonical_path(attributes.get("path") or ":".join(parts[3:]))
        if not method:
            raise ValueError("HTTP candidate requires a method")
        attributes.update({"protocol": "HTTP", "method": method, "path": path})
        if "operation" in attributes:
            attributes["operation"] = f"{method} {path}"
        canonical_key = f"http:{service}:{method}:{path}"
        signature = f"http:{method}:{path}"
    elif kind == "graphql":
        raw_root = str(attributes.get("root_operation") or _from_key(parts, 2)).strip()
        root = {
            "query": "Query",
            "mutation": "Mutation",
            "subscription": "Subscription",
        }.get(raw_root.casefold(), raw_root)
        field = str(attributes.get("field") or ":".join(parts[3:])).strip()
        if not root or not field:
            raise ValueError("GraphQL candidate requires root_operation and field")
        attributes.update({"protocol": "GraphQL", "root_operation": root, "field": field})
        if "operation" in attributes:
            attributes["operation"] = f"{root}.{field}"
        canonical_key = f"graphql:{service}:{root}:{field}"
        signature = f"graphql:{root}:{field}"
    elif kind == "message":
        channel = str(
            attributes.get("channel")
            or attributes.get("destination")
            or _from_key(parts, 2)
        ).strip()
        raw_direction = str(attributes.get("direction") or _from_key(parts, 3, "unspecified")).strip().casefold()
        direction = _DIRECTION.get(raw_direction, "unspecified")
        if not channel:
            raise ValueError("message candidate requires a channel or destination")
        if "channel" in attributes or "direction" in attributes or parts[0].casefold() == "message":
            attributes["channel"] = channel
            attributes["direction"] = direction
        if "operation" in attributes:
            attributes["operation"] = f"{direction} {channel}"
        canonical_key = f"message:{service}:{channel}:{direction}"
        signature = f"message:{channel}:{direction}"
    else:
        tail = ":".join(parts[2:]).strip() if len(parts) > 2 else ":".join(parts[1:]).strip()
        prefix = parts[0].casefold()
        canonical_key = f"{prefix}:{service}:{tail}" if tail else f"{prefix}:{service}"

    item["canonical_key"] = canonical_key
    item["attributes"] = {key: attributes[key] for key in sorted(attributes)}
    item["source"] = deepcopy(dict(item["source"]))
    return item, signature, explicit


def _variants(
    candidates: Sequence[Mapping[str, Any]], value_for: Any
) -> dict[str, dict[str, Any]]:
    variants: dict[str, dict[str, Any]] = {}
    for item in candidates:
        value = deepcopy(value_for(item))
        token = _canonical_json(value)
        bucket = variants.setdefault(token, {"value": value, "sources": []})
        bucket["sources"].append(item["source"])
    return variants


def _conflict_record(
    canonical_key: str,
    attribute: str,
    variants: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    values = [
        {
            "value": deepcopy(variants[token]["value"]),
            "sources": _unique_sorted(variants[token]["sources"], _source_key),
        }
        for token in sorted(variants)
    ]
    seed = {"canonical_key": canonical_key, "attribute": attribute, "values": values}
    return {"conflict_id": f"conflict:{_hash(seed)}", **seed}


def _merge_entity(
    canonical_key: str, candidates: Sequence[Mapping[str, Any]]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    sources = _unique_sorted([item["source"] for item in candidates], _source_key)
    by_attribute: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for item in candidates:
        for attribute, value in item["attributes"].items():
            canonical_value = _canonical_scalar_or_array(value)
            token = _canonical_json(canonical_value)
            bucket = by_attribute[attribute].setdefault(token, {"value": canonical_value, "sources": []})
            bucket["sources"].append(item["source"])

    attributes: dict[str, Any] = {}
    conflicts: list[dict[str, Any]] = []
    for attribute in sorted(by_attribute):
        variants = by_attribute[attribute]
        if len(variants) == 1:
            attributes[attribute] = next(iter(variants.values()))["value"]
            continue
        conflicts.append(_conflict_record(canonical_key, attribute, variants))

    top_level = (
        (ENTITY_TYPE_CONFLICT, lambda item: item["entity_type"]),
        (DISPLAY_NAME_CONFLICT, lambda item: item["display_name"]),
        (
            SERVICE_IDENTITY_CONFLICT,
            lambda item: [
                item["service_identity"]["value"],
                item["service_identity"]["basis"],
            ],
        ),
    )
    provisional: dict[str, Any] = {}
    for reserved_name, value_for in top_level:
        variants = _variants(candidates, value_for)
        first_token = sorted(variants)[0]
        provisional[reserved_name] = deepcopy(variants[first_token]["value"])
        if len(variants) > 1:
            conflicts.append(_conflict_record(canonical_key, reserved_name, variants))

    identity_value, identity_basis = provisional[SERVICE_IDENTITY_CONFLICT]
    entity = {
        "entity_type": provisional[ENTITY_TYPE_CONFLICT],
        "canonical_key": canonical_key,
        "display_name": provisional[DISPLAY_NAME_CONFLICT],
        "service_identity": {"value": identity_value, "basis": identity_basis},
        "attributes": attributes,
        "sources": sources,
        "confidence": "confirmed" if any(item["confidence"] == "confirmed" for item in candidates) else "candidate",
    }
    return entity, conflicts


def review_groups_for(entities: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Derive the exact grouped-review presentation from canonical entities."""
    grouped: dict[str, dict[str, Any]] = {}
    for entity in entities:
        prefix = entity["canonical_key"].split(":", 1)[0].casefold()
        category = "components" if entity["entity_type"] == "component" else "flows" if entity["entity_type"] == "flow" else prefix
        identity = str(entity["service_identity"]["value"])
        group_id = f"{identity}:{category}"
        group = grouped.setdefault(
            group_id,
            {"group_id": group_id, "display_name": f"{identity} / {category}", "entity_keys": []},
        )
        group["entity_keys"].append(entity["canonical_key"])
    for group in grouped.values():
        group["entity_keys"] = sorted(set(group["entity_keys"]))
    return [grouped[key] for key in sorted(grouped)]


def protocol_signature_for(entity: Mapping[str, Any]) -> str | None:
    """Return a service-free signature only for supported protocol key prefixes."""
    parts = _key_parts(entity["canonical_key"])
    prefix = parts[0].casefold()
    attributes = entity["attributes"]
    if prefix == "http":
        method = str(attributes.get("method") or _from_key(parts, 2)).strip().upper()
        path = _canonical_path(attributes.get("path") or ":".join(parts[3:]))
        return f"http:{method}:{path}"
    if prefix == "graphql":
        raw_root = str(attributes.get("root_operation") or _from_key(parts, 2)).strip()
        root = {
            "query": "Query",
            "mutation": "Mutation",
            "subscription": "Subscription",
        }.get(raw_root.casefold(), raw_root)
        field = str(attributes.get("field") or ":".join(parts[3:])).strip()
        return f"graphql:{root}:{field}"
    if prefix == "message":
        channel = str(
            attributes.get("channel")
            or attributes.get("destination")
            or _from_key(parts, 2)
        ).strip()
        raw_direction = str(
            attributes.get("direction") or _from_key(parts, 3, "unspecified")
        ).strip().casefold()
        return f"message:{channel}:{_DIRECTION.get(raw_direction, 'unspecified')}"
    return None


def possible_duplicates_for(
    entities: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Derive exact possible duplicates, linking fallback keys to explicit peers."""
    buckets: dict[str, set[str]] = defaultdict(set)
    fallback_signatures: set[str] = set()
    for entity in entities:
        signature = protocol_signature_for(entity)
        if signature is None:
            continue
        buckets[signature].add(entity["canonical_key"])
        if entity["service_identity"]["basis"] not in _EXPLICIT_IDENTITY_BASES:
            fallback_signatures.add(signature)

    duplicates: list[dict[str, Any]] = []
    for signature in sorted(buckets):
        entity_keys = sorted(buckets[signature])
        if len(entity_keys) < 2 or signature not in fallback_signatures:
            continue
        seed = {"protocol_signature": signature, "entity_keys": entity_keys}
        duplicates.append({"duplicate_id": f"duplicate:{_hash(seed)}", **seed})
    return duplicates


def _repository_diagnostics(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError("repository_diagnostics must be a sequence")
    combined: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw in value:
        item = _mapping(raw, "repository diagnostic")
        repo_id = item.get("repo_id")
        diagnostics = item.get("diagnostics")
        if not isinstance(repo_id, str) or not repo_id or not isinstance(diagnostics, list):
            raise ValueError("repository diagnostic requires repo_id and diagnostics")
        combined[repo_id].extend(deepcopy(diagnostics))
    return [
        {"repo_id": repo_id, "diagnostics": _unique_sorted(combined[repo_id], _diagnostic_key)}
        for repo_id in sorted(combined)
    ]


def _candidate_identity_payload(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Return the exact canonical content protected by ``candidate_id``."""
    return {
        "snapshot_id": candidate["snapshot_id"],
        "entities": candidate["entities"],
        "conflicts": candidate["conflicts"],
        "possible_duplicates": candidate["possible_duplicates"],
        "repository_diagnostics": candidate["repository_diagnostics"],
        "warnings": candidate["warnings"],
    }


def candidate_id_for(candidate: Mapping[str, Any]) -> str:
    """Recompute a candidate integrity ID from its canonical protected payload."""
    return _hash(_candidate_identity_payload(candidate))


def merge_results(
    snapshot_id: str,
    results: Sequence[Any],
    repository_diagnostics: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Merge validated extractor results without mutating any caller-owned value."""
    if not isinstance(snapshot_id, str) or not re.fullmatch(r"[0-9a-f]{64}", snapshot_id):
        raise ValueError("snapshot_id must be a lowercase SHA-256")
    if not isinstance(results, Sequence) or isinstance(results, (str, bytes, bytearray)):
        raise ValueError("results must be a sequence")

    normalized: list[tuple[dict[str, Any], str | None, bool]] = []
    warnings: list[dict[str, Any]] = []
    for raw_result in results:
        result = _mapping(raw_result, "extractor result")
        contracts.validate_artifact(result, "methodology-extractor-result.schema.json")
        warnings.extend(deepcopy(result["warnings"]))
        warnings.extend(deepcopy(result["errors"]))
        for raw_candidate in result["candidates"]:
            if raw_candidate["source"]["repo_id"] != result["repo_id"]:
                raise ValueError(
                    "candidate source repo_id must match extractor result repo_id"
                )
            normalized.append(_normalize_candidate(raw_candidate))

    by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item, _signature, _explicit in normalized:
        by_key[item["canonical_key"]].append(item)

    entities: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    for canonical_key in sorted(by_key):
        entity, entity_conflicts = _merge_entity(canonical_key, by_key[canonical_key])
        entities.append(entity)
        conflicts.extend(entity_conflicts)
    conflicts.sort(key=lambda item: (item["canonical_key"], item["attribute"], item["conflict_id"]))

    possible_duplicates = possible_duplicates_for(entities)

    diagnostics = _repository_diagnostics(repository_diagnostics)
    sorted_warnings = _unique_sorted(warnings, _diagnostic_key)
    identity_payload = {
        "snapshot_id": snapshot_id,
        "entities": entities,
        "conflicts": conflicts,
        "possible_duplicates": possible_duplicates,
        "repository_diagnostics": diagnostics,
        "warnings": sorted_warnings,
    }
    candidate = {
        "version": 1,
        "candidate_id": _hash(identity_payload),
        "snapshot_id": snapshot_id,
        "entities": entities,
        "review_groups": review_groups_for(entities),
        "conflicts": conflicts,
        "possible_duplicates": possible_duplicates,
        "repository_diagnostics": diagnostics,
        "warnings": sorted_warnings,
    }
    contracts.validate_artifact(candidate, "methodology-surface-candidate.schema.json")
    return candidate

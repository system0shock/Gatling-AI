"""Validation and durable serialization for discovery artifacts."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import jsonschema

try:
    from tools.methodology_pipeline.contracts import load_schema, write_json_atomic
except ModuleNotFoundError:  # Direct execution of discovery tests.
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from methodology_pipeline.contracts import load_schema, write_json_atomic


def validate_artifact(value: Mapping[str, Any], schema_name: str) -> None:
    """Validate one closed discovery artifact and its deterministic ordering rules."""
    try:
        jsonschema.validate(dict(value), load_schema(schema_name))
    except jsonschema.ValidationError as exc:
        location = "/".join(str(part) for part in exc.absolute_path)
        detail = f" at {location}" if location else ""
        raise ValueError(f"{schema_name}{detail}: {exc.message}") from exc

    if schema_name == "methodology-surface-candidate.schema.json":
        _require_sorted(value["entities"], "canonical_key", "entities")
        _require_sorted(value["review_groups"], "group_id", "review_groups")
        for entity in value["entities"]:
            _require_sorted(entity["sources"], "path", "entity sources")


def _require_sorted(records: Any, key: str, label: str) -> None:
    values = [record[key] for record in records]
    if values != sorted(values):
        raise ValueError(f"{label} must be sorted by {key}")

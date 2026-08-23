"""Loading, validation, and durable writes for methodology artifacts."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import jsonschema
import yaml


SCHEMA_ROOT = Path(__file__).resolve().parents[2] / "schemas"


def load_schema(name: str) -> dict[str, Any]:
    value = json.loads((SCHEMA_ROOT / name).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{name}: schema must be an object")
    return value


def validate_artifact(value: Mapping[str, Any], schema_name: str) -> None:
    try:
        jsonschema.validate(dict(value), load_schema(schema_name))
    except jsonschema.ValidationError as exc:
        raise ValueError(f"{schema_name}: {exc.message}") from exc
    if schema_name == "methodology-generation-state.schema.json":
        for block in value["blocks"]:
            if block["resolution"] == "rendered" and block["actual_sha256"] != block["rendered_sha256"]:
                raise ValueError(f"{schema_name}: rendered block hashes must match")
    if schema_name == "methodology-drift-decisions.schema.json":
        sections = [decision["section"] for decision in value["decisions"]]
        if len(sections) != len(set(sections)):
            raise ValueError(f"{schema_name}: each section needs one decision")


def load_yaml_mapping(path: Path, schema_name: str) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"{path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a mapping")
    validate_artifact(value, schema_name)
    return value


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    _atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def write_yaml_atomic(path: Path, value: Mapping[str, Any]) -> None:
    _atomic_write(path, yaml.safe_dump(dict(value), allow_unicode=True, sort_keys=True))

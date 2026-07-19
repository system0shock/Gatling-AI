"""Typed workspace manifest contracts and loading helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema
import yaml


@dataclass(frozen=True)
class ModuleConfig:
    module_id: str
    path: str
    kind: str
    required: bool = False
    inspect: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    authoritative_for: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkspaceManifest:
    system: str
    workspace_root: str
    load_test_module: str
    modules: tuple[ModuleConfig, ...]
    allowed_modules: tuple[str, ...]


def load_schema(name: str) -> dict[str, Any]:
    """Load a bundled JSON schema by filename."""
    schema_path = Path(__file__).resolve().parents[2] / "schemas" / name
    with schema_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def parse_manifest(doc: dict[str, Any]) -> WorkspaceManifest:
    """Validate and convert one decoded manifest document."""
    jsonschema.validate(doc, load_schema("workspace.schema.json"))
    modules = tuple(
        ModuleConfig(
            module_id=item["id"],
            path=item["path"],
            kind=item["kind"],
            required=bool(item.get("required", False)),
            inspect=tuple(item.get("inspect", [])),
            exclude=tuple(item.get("exclude", [])),
            authoritative_for=tuple(item.get("authoritative_for", [])),
        )
        for item in doc["modules"]
    )
    for module in modules:
        if Path(module.path).is_absolute():
            raise ValueError(f"module path must be relative: {module.path}")
    return WorkspaceManifest(
        system=doc["system"],
        workspace_root=doc["workspace_root"],
        load_test_module=doc["load_test_module"],
        modules=modules,
        allowed_modules=tuple(doc["write_policy"]["allowed_modules"]),
    )


def load_manifest(path: Path) -> WorkspaceManifest:
    """Load and validate a YAML manifest, identifying failures by manifest path."""
    try:
        with path.open("r", encoding="utf-8") as handle:
            document = yaml.safe_load(handle)
        if not isinstance(document, dict):
            raise ValueError("manifest must contain a mapping")
        return parse_manifest(document)
    except (OSError, ValueError, yaml.YAMLError, json.JSONDecodeError, jsonschema.ValidationError) as exc:
        raise ValueError(f"{path}: {exc}") from exc


def resolve_workspace_root(manifest_path: Path, value: str) -> Path:
    """Resolve an existing workspace root relative to its manifest location."""
    try:
        return (manifest_path.parent / value).resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError(f"{manifest_path}: cannot resolve workspace root {value!r}: {exc}") from exc

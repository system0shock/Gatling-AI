"""Typed workspace manifest contracts and loading helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

import jsonschema
import yaml


@dataclass(frozen=True)
class ModuleConfig:
    module_id: str
    path: str
    kind: str | None = None
    required: bool = False
    inspect: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    authoritative_for: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()
    service_id: str | None = None

    @property
    def effective_roles(self) -> tuple[str, ...]:
        """Return explicit v2 roles or the compatible v1 kind role."""
        return self.roles or ((self.kind,) if self.kind else ())

    @property
    def primary_role(self) -> str:
        """Return the first prioritization role, falling back to ``other``."""
        return self.effective_roles[0] if self.effective_roles else "other"


@dataclass(frozen=True)
class WorkspaceManifest:
    system: str
    workspace_root: str
    load_test_module: str
    modules: tuple[ModuleConfig, ...]
    allowed_modules: tuple[str, ...]
    version: int = 1

    @property
    def repositories(self) -> tuple[ModuleConfig, ...]:
        """Expose repositories without breaking callers that use ``modules``."""
        return self.modules


def load_schema(name: str) -> dict[str, Any]:
    """Load a bundled JSON schema by filename."""
    schema_path = Path(__file__).resolve().parents[2] / "schemas" / name
    with schema_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _is_genuinely_relative(path: str) -> bool:
    """Return whether *path* is relative under both POSIX and Windows rules."""
    windows_path = PureWindowsPath(path)
    return (
        not Path(path).is_absolute()
        and not PurePosixPath(path).is_absolute()
        and not windows_path.drive
        and not windows_path.root
    )


def parse_manifest(doc: dict[str, Any]) -> WorkspaceManifest:
    """Validate and convert one decoded manifest document."""
    version = doc.get("version")
    if version == 1:
        schema_name = "workspace.schema.json"
        item_key = "modules"
        required_default = False
    elif version == 2:
        schema_name = "workspace-v2.schema.json"
        item_key = "repositories"
        required_default = True
    else:
        raise ValueError(f"unsupported workspace manifest version: {version!r}")
    try:
        jsonschema.validate(doc, load_schema(schema_name))
    except jsonschema.ValidationError as exc:
        raise ValueError(str(exc)) from exc
    modules = tuple(
        ModuleConfig(
            module_id=item["id"],
            path=item["path"],
            kind=item.get("kind"),
            required=bool(item.get("required", required_default)),
            inspect=tuple(item.get("inspect", [])),
            exclude=tuple(item.get("exclude", [])),
            authoritative_for=tuple(item.get("authoritative_for", [])),
            roles=(tuple(item.get("roles", [])) if version == 2 else (item["kind"],)),
            service_id=item.get("service_id"),
        )
        for item in doc[item_key]
    )
    ids = [module.module_id for module in modules]
    if len(ids) != len(set(ids)):
        noun = "repository" if version == 2 else "module"
        raise ValueError(f"duplicate {noun} id in workspace manifest")
    if not _is_genuinely_relative(doc["workspace_root"]):
        raise ValueError(f"workspace root path must be relative: {doc['workspace_root']}")
    for module in modules:
        if not _is_genuinely_relative(module.path):
            noun = "repository" if version == 2 else "module"
            raise ValueError(f"{noun} path must be relative: {module.path}")
    allowed_modules = tuple(doc["write_policy"]["allowed_modules"])
    if allowed_modules != (doc["load_test_module"],):
        raise ValueError("only the configured load-test module may be writable")
    return WorkspaceManifest(
        system=doc["system"],
        workspace_root=doc["workspace_root"],
        load_test_module=doc["load_test_module"],
        modules=modules,
        allowed_modules=allowed_modules,
        version=version,
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

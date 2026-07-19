"""Deterministic, offline planning for selective methodology refreshes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

SNAPSHOT_ID_RE = re.compile(r"[0-9a-f]{64}\Z")
KNOWN_KINDS = frozenset({"load-tests", "backend", "frontend", "api-spec", "infrastructure", "shared-library", "database", "other"})
ALL_SECTIONS = (
    "Паспорт документа", "Назначение и область тестирования", "Описание системы и функциональности", "Архитектура", "Реестр интеграций", "Реестр тестируемых интерфейсов", "Пользовательские и технические потоки", "Модель нагрузки", "Виды тестов", "SLA, SLO и критерии приемки", "Тестовый стенд", "Требования к тестовым данным", "Наблюдаемость и диагностика", "Порядок проведения тестов", "Риски, ограничения и допущения", "Артефакты и отчетность", "Актуализация методики",
)
KIND_SECTIONS = {
    "api-spec": ("Реестр тестируемых интерфейсов",),
    "backend": ("Архитектура", "Реестр интеграций", "Реестр тестируемых интерфейсов", "Наблюдаемость и диагностика"),
    "frontend": ("Описание системы и функциональности", "Пользовательские и технические потоки"),
    "infrastructure": ("Архитектура", "Тестовый стенд"),
    "database": ("Архитектура", "Риски, ограничения и допущения"),
}
ROLE_SECTIONS = {
    "sla": ("SLA, SLO и критерии приемки",),
    "architecture": ("Архитектура",),
    "integrations": ("Реестр интеграций",),
    "workload": ("Модель нагрузки",),
}


@dataclass(frozen=True)
class SourceChange:
    source_type: str
    source_id: str
    previous_revision: str | int | None
    current_revision: str | int | None
    previous_snapshot_id: str
    current_snapshot_id: str
    reason: str
    roles: tuple[str, ...] = ()


def _revision(state: dict[str, Any] | None) -> str | None:
    return None if state is None else f"{state.get('commit')}:{state.get('dirty')}"


def compare_snapshots(previous: dict, current: dict) -> tuple[SourceChange, ...]:
    """Compare only module commit/dirty state in stable module-id order."""
    before_modules, after_modules = previous.get("modules", {}), current.get("modules", {})
    if not isinstance(before_modules, dict) or not isinstance(after_modules, dict):
        raise ValueError("snapshots must contain module mappings")
    changes = []
    for module_id in sorted(before_modules.keys() | after_modules.keys()):
        before, after = before_modules.get(module_id), after_modules.get(module_id)
        before_revision, after_revision = _revision(before), _revision(after)
        if before_revision != after_revision:
            reason = "module-added" if before is None else "module-removed" if after is None else "git-state-changed"
            changes.append(SourceChange("module", module_id, before_revision, after_revision,
                previous.get("snapshot_id", "unknown"), current.get("snapshot_id", "unknown"), reason))
    return tuple(changes)


def compare_confluence_pages(previous: dict, current: dict, page_roles: dict[str, list[str]]) -> tuple[SourceChange, ...]:
    """Compare page versions and preserve deterministic, explicit roles."""
    before_pages, after_pages = previous.get("pages", {}), current.get("pages", {})
    if not isinstance(before_pages, dict) or not isinstance(after_pages, dict):
        raise ValueError("page snapshots must contain page mappings")
    changes = []
    for page_id in sorted(before_pages.keys() | after_pages.keys()):
        before, after = before_pages.get(page_id, {}), after_pages.get(page_id, {})
        if not isinstance(before, dict) or not isinstance(after, dict):
            raise ValueError(f"page state must be an object: {page_id}")
        before_version = None if page_id not in before_pages else before.get("version")
        after_version = None if page_id not in after_pages else after.get("version")
        if before_version != after_version:
            roles = page_roles.get(page_id, [])
            if not isinstance(roles, list) or not all(isinstance(role, str) and role for role in roles):
                raise ValueError(f"page roles must be non-empty strings: {page_id}")
            reason = "page-added" if page_id not in before_pages else "page-removed" if page_id not in after_pages else "page-version-changed"
            changes.append(SourceChange("confluence", page_id, before_version, after_version,
                previous.get("snapshot_id", "unknown"), current.get("snapshot_id", "unknown"), reason,
                tuple(sorted(set(roles)))))
    return tuple(changes)


def _module_kinds(manifest: dict[str, Any]) -> dict[str, str]:
    modules = manifest.get("modules")
    if not isinstance(modules, list):
        raise ValueError("manifest must contain modules")
    result = {}
    for item in modules:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
            raise ValueError("manifest module requires a non-empty id")
        if item.get("kind") not in KNOWN_KINDS:
            raise ValueError(f"unknown manifest module kind: {item.get('kind')!r}")
        if item["id"] in result:
            raise ValueError(f"duplicate manifest module: {item['id']}")
        result[item["id"]] = item["kind"]
    return result


def _source_mapping(source_map: dict[str, Any], source_key: str) -> tuple[set[str], set[str]]:
    """Read only a well-formed optional source-to-entity mapping."""
    sources = source_map.get("sources", {})
    if not isinstance(sources, dict):
        raise ValueError("source map sources must be an object")
    if source_key not in sources:
        return set(), set()
    mapping = sources[source_key]
    if not isinstance(mapping, dict):
        raise ValueError(f"source mapping must be an object: {source_key}")
    if set(mapping) != {"entity_ids", "sections"}:
        raise ValueError(f"invalid source mapping: {source_key}")
    entity_ids, direct_sections = mapping["entity_ids"], mapping["sections"]
    valid_entities = isinstance(entity_ids, list) and len(entity_ids) == len(set(entity_ids)) and all(isinstance(value, str) and value for value in entity_ids)
    valid_sections = isinstance(direct_sections, list) and len(direct_sections) == len(set(direct_sections)) and all(isinstance(value, str) and value in ALL_SECTIONS for value in direct_sections)
    if not valid_entities or not valid_sections:
        raise ValueError(f"invalid source mapping: {source_key}")
    entities, sections = set(entity_ids), set(direct_sections)
    if entities and isinstance(source_map.get("sections"), dict):
        sections.update(section for section, evidence_ids in source_map["sections"].items()
                        if section in ALL_SECTIONS and isinstance(evidence_ids, list) and entities.intersection(evidence_ids))
    return entities, sections

def _change_dict(change: SourceChange) -> dict[str, Any]:
    """Return a JSON-native change envelope; dataclasses preserve tuple roles."""
    payload = asdict(change)
    payload["roles"] = list(change.roles)
    return payload

def _valid_snapshot_id(value: object) -> bool:
    return isinstance(value, str) and SNAPSHOT_ID_RE.fullmatch(value) is not None


def _plan_snapshot_ids(changes: tuple[SourceChange, ...], source_map: dict[str, Any], previous_snapshot_id: str | None, current_snapshot_id: str | None) -> tuple[str, str]:
    """Bind one plan to one immutable snapshot pair, including no-op plans."""
    if (previous_snapshot_id is None) != (current_snapshot_id is None):
        raise ValueError("previous_snapshot_id and current_snapshot_id must be supplied together")
    if changes:
        pairs = {(change.previous_snapshot_id, change.current_snapshot_id) for change in changes}
        if len(pairs) != 1:
            raise ValueError("mixed snapshot histories are not allowed in one refresh plan")
        before, after = pairs.pop()
        if not _valid_snapshot_id(before) or not _valid_snapshot_id(after):
            raise ValueError("refresh changes require immutable snapshot IDs")
        if previous_snapshot_id is not None and (before, after) != (previous_snapshot_id, current_snapshot_id):
            raise ValueError("explicit snapshot IDs do not match every source change")
        return before, after
    if previous_snapshot_id is not None:
        if not _valid_snapshot_id(previous_snapshot_id) or not _valid_snapshot_id(current_snapshot_id):
            raise ValueError("refresh plan requires immutable snapshot IDs")
        return previous_snapshot_id, current_snapshot_id
    mapped = source_map.get("workspace_snapshot") if isinstance(source_map, dict) else None
    if not isinstance(mapped, dict) or set(mapped) != {"version", "snapshot_id", "fresh"} or mapped.get("version") != 1 or mapped.get("fresh") is not True or not _valid_snapshot_id(mapped.get("snapshot_id")):
        raise ValueError("empty refresh plan requires a valid source-map workspace snapshot identity")
    return mapped["snapshot_id"], mapped["snapshot_id"]

def build_refresh_plan(changes: tuple[SourceChange, ...], source_map: dict, manifest: dict, *, previous_snapshot_id: str | None = None, current_snapshot_id: str | None = None) -> dict[str, Any]:
    """Schedule changed collectors only; reject unknown modules and broaden unknown page roles."""
    module_kinds = _module_kinds(manifest)
    inspect_modules, fetch_pages, entities, sections, reasons = set(), set(), set(), set(), []
    for change in changes:
        source_key = f"{change.source_type}:{change.source_id}"
        mapped_entities, mapped_sections = _source_mapping(source_map, source_key)
        entities.update(mapped_entities)
        if change.source_type == "module":
            kind = module_kinds.get(change.source_id)
            if kind is None:
                raise ValueError(f"unknown module change: {change.source_id}")
            defaults = KIND_SECTIONS.get(kind)
            if defaults is None:
                raise ValueError(f"unknown impact rules for module kind: {kind}")
            if change.current_revision is not None:
                inspect_modules.add(change.source_id)
        elif change.source_type == "confluence":
            defaults = set(ALL_SECTIONS) if not change.roles or set(change.roles).difference(ROLE_SECTIONS) else {section for role in change.roles for section in ROLE_SECTIONS[role]}
            if change.current_revision is not None:
                fetch_pages.add(change.source_id)
        else:
            raise ValueError(f"unknown source type: {change.source_type}")
        sections.update(mapped_sections or defaults)
        reasons.append({"source": source_key, "reason": change.reason})
    before_id, after_id = _plan_snapshot_ids(changes, source_map, previous_snapshot_id, current_snapshot_id)
    return {
        "version": 1,
        "previous_snapshot_id": before_id,
        "current_snapshot_id": after_id,
        "changed_sources": [_change_dict(change) for change in changes],
        "inspect_modules": sorted(inspect_modules), "fetch_page_ids": sorted(fetch_pages),
        "affected_entity_ids": sorted(entities), "affected_sections": sorted(sections),
        "reconciliation_scope": sorted(entities) or ["affected-sections"], "reasons": reasons,
    }


def validate_workspace_snapshot(snapshot: dict[str, Any]) -> None:
    required_state = {"commit", "branch", "dirty", "remote", "path", "kind", "dirty_policy"}
    if not isinstance(snapshot, dict) or set(snapshot) != {"version", "snapshot_id", "workspace_root", "modules"} or type(snapshot.get("version")) is not int or snapshot["version"] != 1 or not isinstance(snapshot.get("workspace_root"), str) or not snapshot["workspace_root"] or not isinstance(snapshot.get("snapshot_id"), str) or SNAPSHOT_ID_RE.fullmatch(snapshot["snapshot_id"]) is None or not isinstance(snapshot.get("modules"), dict):
        raise ValueError("workspace snapshot envelope is invalid")
    for module_id, state in snapshot["modules"].items():
        if not isinstance(module_id, str) or not module_id or not isinstance(state, dict) or set(state) != required_state or not isinstance(state.get("commit"), str) or not state["commit"] or not isinstance(state.get("path"), str) or not state["path"] or state.get("kind") not in KNOWN_KINDS or type(state.get("dirty")) is not bool or state.get("dirty_policy") not in {"clean", "HEAD", "working-tree"}:
            raise ValueError("workspace snapshot module is invalid")
    canonical = json.dumps(snapshot["modules"], sort_keys=True, separators=(",", ":")).encode("utf-8")
    if hashlib.sha256(canonical).hexdigest() != snapshot["snapshot_id"]:
        raise ValueError("workspace snapshot_id does not match modules")


def validate_snapshot_manifest_consistency(previous: dict[str, Any], current: dict[str, Any], current_manifest: dict[str, Any], previous_manifest: dict[str, Any] | None = None) -> None:
    """Keep snapshot identities bound to their confirmed manifest, including removals."""
    current_kinds = _module_kinds(current_manifest)
    current_modules, previous_modules = current["modules"], previous["modules"]
    if set(current_modules) != set(current_kinds):
        raise ValueError("current snapshot module IDs do not match the current manifest")
    for module_id, kind in current_kinds.items():
        if current_modules[module_id].get("kind") != kind:
            raise ValueError("current snapshot module kind does not match the current manifest")
    if previous_manifest is not None:
        previous_kinds = _module_kinds(previous_manifest)
        if set(previous_modules) != set(previous_kinds):
            raise ValueError("previous snapshot module IDs do not match the historical manifest")
        for module_id, kind in previous_kinds.items():
            if previous_modules[module_id].get("kind") != kind:
                raise ValueError("previous snapshot module kind does not match the historical manifest")
        return
    for module_id in set(previous_modules).intersection(current_modules):
        if previous_modules[module_id].get("kind") != current_modules[module_id].get("kind"):
            raise ValueError("common snapshot module kind does not match the current manifest")
    for module_id in set(previous_modules).difference(current_modules):
        if previous_modules[module_id].get("kind") not in KIND_SECTIONS:
            raise ValueError("removed module must carry a supported embedded kind without a historical manifest")

def validate_source_map(source_map: dict[str, Any], previous_snapshot_id: str) -> None:
    allowed = {"version", "sections", "workspace_snapshot", "sources"}
    snapshot = source_map.get("workspace_snapshot") if isinstance(source_map, dict) else None
    if not isinstance(source_map, dict) or not set(source_map).issubset(allowed) or {"version", "sections", "workspace_snapshot"}.difference(source_map) or source_map.get("version") != 1 or not isinstance(source_map.get("sections"), dict) or not isinstance(source_map.get("sources", {}), dict) or not isinstance(snapshot, dict) or set(snapshot) != {"version", "snapshot_id", "fresh"} or snapshot.get("version") != 1 or snapshot.get("fresh") is not True or snapshot.get("snapshot_id") != previous_snapshot_id:
        raise ValueError("source map is stale or malformed")
    if set(source_map["sections"]) != set(ALL_SECTIONS) or not all(isinstance(values, list) and len(values) == len(set(values)) and all(isinstance(value, str) and value for value in values) for values in source_map["sections"].values()):
        raise ValueError("source map sections do not match canonical MNT headings")
    for source_key in source_map.get("sources", {}):
        _source_mapping(source_map, source_key)


def validate_refresh_plan(plan: dict[str, Any]) -> None:
    required = {"version", "previous_snapshot_id", "current_snapshot_id", "changed_sources", "inspect_modules", "fetch_page_ids", "affected_entity_ids", "affected_sections", "reconciliation_scope", "reasons"}
    if not isinstance(plan, dict) or set(plan) != required or plan.get("version") != 1 or any(not isinstance(plan[key], str) or SNAPSHOT_ID_RE.fullmatch(plan[key]) is None for key in ("previous_snapshot_id", "current_snapshot_id")):
        raise ValueError("refresh plan requires immutable snapshot IDs")
    if not all(isinstance(plan[key], list) for key in ("changed_sources", "inspect_modules", "fetch_page_ids", "affected_entity_ids", "affected_sections", "reconciliation_scope", "reasons")) or not all(section in ALL_SECTIONS for section in plan["affected_sections"]):
        raise ValueError("refresh plan envelope is invalid")


def load_manifest(path: Path) -> dict[str, Any]:
    """Parse the Phase 3a YAML subset needed for module id/kind validation, with no runtime dependencies."""
    text = path.read_text(encoding="utf-8")
    if text.lstrip().startswith("{"):
        document = json.loads(text)
        if not isinstance(document, dict):
            raise ValueError("manifest must be an object")
        _module_kinds(document)
        return document
    document: dict[str, Any] = {"modules": []}; in_modules = False; current = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent, value = len(line) - len(line.lstrip(" ")), line.strip()
        if indent == 0:
            in_modules = value in {"modules:", "modules: []"}; current = None
            if value == "modules: []":
                document["modules"] = []
            elif ":" in value and not in_modules:
                key, scalar = value.split(":", 1); document[key] = scalar.strip().strip("'\"")
        elif in_modules and indent == 2 and value.startswith("- "):
            current = {}; document["modules"].append(current); key, scalar = value[2:].split(":", 1); current[key] = scalar.strip().strip("'\"")
        elif in_modules and indent >= 4 and current is not None and ":" in value:
            key, scalar = value.split(":", 1); current[key] = scalar.strip().strip("'\"")
    if document.get("version") != "1" or not document.get("system") or not document.get("load_test_module"):
        raise ValueError(f"{path}: invalid Phase 3a workspace manifest")
    _module_kinds(document)
    return document


def _load_json(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2); handle.write("\n")
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True); raise


def resolve_output_inside_load_test_root(load_test_root: Path, output: Path) -> Path:
    """Resolve all existing links/reparse points before any output directory is created."""
    root = load_test_root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("load-test root must be a directory")
    candidate = output if output.is_absolute() else root / output
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"output resolves outside load-test root: {output}") from exc
    return resolved

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plan an offline selective methodology refresh.")
    parser.add_argument("--previous-run", type=Path, required=True); parser.add_argument("--current-run", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True); parser.add_argument("--previous-workspace", type=Path); parser.add_argument("--source-map", type=Path, required=True); parser.add_argument("--load-test-root", type=Path, required=True); parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        previous = _load_json(args.previous_run / "workspace-snapshot.json", "previous workspace snapshot")
        current = _load_json(args.current_run / "workspace-snapshot.json", "current workspace snapshot")
        source_map = _load_json(args.source_map, "source map")
        validate_workspace_snapshot(previous); validate_workspace_snapshot(current); validate_source_map(source_map, previous["snapshot_id"])
        current_manifest = load_manifest(args.workspace)
        previous_manifest = load_manifest(args.previous_workspace) if args.previous_workspace else None
        validate_snapshot_manifest_consistency(previous, current, current_manifest, previous_manifest)
        output = resolve_output_inside_load_test_root(args.load_test_root, args.out)
        plan = build_refresh_plan(compare_snapshots(previous, current), source_map, current_manifest, previous_snapshot_id=previous["snapshot_id"], current_snapshot_id=current["snapshot_id"])
        validate_refresh_plan(plan); atomic_write_json(output, plan)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr); return 2
    print(json.dumps({"out": str(output), "changed_source_count": len(plan["changed_sources"])}, ensure_ascii=False, sort_keys=True)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
"""Small UTF-8 fixture builder used by the methodology quality-gate tests."""

from __future__ import annotations

import difflib
import hashlib
import json
from pathlib import Path

from methodology_evidence.reconcile import NO_DATA, REQUIRED_MNT_SECTIONS


HEADINGS = tuple(heading for heading, _ in REQUIRED_MNT_SECTIONS)


def write_gate_fixture(
    root: Path,
    *,
    omit: str | None = None,
    extra: str = "",
    sla: str | None = None,
    source_map: dict | None = None,
) -> dict[str, Path]:
    """Write a complete, contract-valid candidate and companions beneath *root*."""
    paths = {
        name: root / name
        for name in (
            "candidate.md", "resolved.json", "coverage.json", "source-map.json",
            "methodology.patch", "base.md", "workspace-snapshot.json",
        )
    }
    body = ["# РњРќРў"]
    for heading in HEADINGS:
        if heading != omit:
            body.extend(["", f"## {heading}", "", sla if heading.startswith("SLA") and sla else NO_DATA])
    if extra:
        body.extend(["", extra])
    candidate_text = "\n".join(body) + "\n"
    base_text = "# РњРќРў\n"
    paths["candidate.md"].write_text(candidate_text, encoding="utf-8")
    paths["base.md"].write_text(base_text, encoding="utf-8")
    evidence_ids = {heading: [f"fact.section-{index}.value"] for index, heading in enumerate(HEADINGS, start=1)}
    entities = [
        {"entity_type": "fact", "entity_id": f"section-{index}", "status": "confirmed", "fields": {"value": [{"entity_type": "fact", "entity_id": f"section-{index}", "field": "value", "statement": "fixture", "source": {"source_type": "repository", "ref": "fixture.md", "module_id": "fixture", "revision": "abc"}, "confidence": "confirmed", "freshness": "current"}]}}
        for index, _ in enumerate(HEADINGS, start=1)
    ]
    paths["resolved.json"].write_text(json.dumps({"version": 1, "entities": entities, "blocking_gaps": []}), encoding="utf-8")
    paths["coverage.json"].write_text(json.dumps({
        "version": 1,
        "sections": {heading: "covered" for heading in HEADINGS},
        "evidence_ids": evidence_ids,
    }), encoding="utf-8")
    mapped = source_map if source_map is not None else evidence_ids
    modules = {"fixture": {"commit": "abc", "path": "fixture", "kind": "backend", "dirty": False, "dirty_policy": "clean"}}
    snapshot_id = hashlib.sha256(json.dumps(modules, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    paths["workspace-snapshot.json"].write_text(json.dumps({"version": 1, "snapshot_id": snapshot_id, "workspace_root": "fixture", "modules": modules}), encoding="utf-8")
    paths["source-map.json"].write_text(json.dumps({
        "version": 1,
        "sections": mapped,
        "workspace_snapshot": {"version": 1, "snapshot_id": snapshot_id, "fresh": True},
    }), encoding="utf-8")
    patch = "".join(difflib.unified_diff(
        base_text.splitlines(keepends=True), candidate_text.splitlines(keepends=True),
        fromfile=str(paths["base.md"]), tofile=str(paths["candidate.md"]),
    ))
    paths["methodology.patch"].write_text(patch, encoding="utf-8")
    return {"candidate": paths["candidate.md"], "resolved_evidence": paths["resolved.json"],
            "coverage": paths["coverage.json"], "source_map": paths["source-map.json"],
            "patch": paths["methodology.patch"], "base": paths["base.md"], "workspace_snapshot": paths["workspace-snapshot.json"]}
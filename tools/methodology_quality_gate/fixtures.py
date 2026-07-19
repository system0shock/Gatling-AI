"""Small UTF-8 fixture builder used by the methodology quality-gate tests."""

from __future__ import annotations

import difflib
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
            "methodology.patch", "base.md",
        )
    }
    body = ["# МНТ"]
    for heading in HEADINGS:
        if heading != omit:
            body.extend(["", f"## {heading}", "", sla if heading.startswith("SLA") and sla else NO_DATA])
    if extra:
        body.extend(["", extra])
    candidate_text = "\n".join(body) + "\n"
    base_text = "# МНТ\n"
    paths["candidate.md"].write_text(candidate_text, encoding="utf-8")
    paths["base.md"].write_text(base_text, encoding="utf-8")
    evidence_ids = {heading: [f"fact.section-{index}.value"] for index, heading in enumerate(HEADINGS, start=1)}
    entities = [
        {"entity_type": "fact", "entity_id": f"section-{index}", "fields": {"value": []}}
        for index, _ in enumerate(HEADINGS, start=1)
    ]
    paths["resolved.json"].write_text(json.dumps({"entities": entities, "blocking_gaps": []}), encoding="utf-8")
    paths["coverage.json"].write_text(json.dumps({
        "version": 1,
        "sections": {heading: "covered" for heading in HEADINGS},
        "evidence_ids": evidence_ids,
    }), encoding="utf-8")
    mapped = source_map if source_map is not None else evidence_ids
    paths["source-map.json"].write_text(json.dumps({
        "version": 1,
        "sections": mapped,
        "workspace_snapshot": {"version": 1, "snapshot_id": "a" * 64, "fresh": True},
    }), encoding="utf-8")
    patch = "".join(difflib.unified_diff(
        base_text.splitlines(keepends=True), candidate_text.splitlines(keepends=True),
        fromfile=str(paths["base.md"]), tofile=str(paths["candidate.md"]),
    ))
    paths["methodology.patch"].write_text(patch, encoding="utf-8")
    return {"candidate": paths["candidate.md"], "resolved_evidence": paths["resolved.json"],
            "coverage": paths["coverage.json"], "source_map": paths["source-map.json"],
            "patch": paths["methodology.patch"], "base": paths["base.md"]}
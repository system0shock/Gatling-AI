"""Small UTF-8 fixture builder used by the methodology quality-gate tests."""

from __future__ import annotations

import json
from pathlib import Path

from methodology_evidence.reconcile import REQUIRED_MNT_SECTIONS


HEADINGS = tuple(heading for heading, _ in REQUIRED_MNT_SECTIONS)
NO_DATA = "Нет подтвержденных данных."


def write_gate_fixture(
    root: Path,
    *,
    omit: str | None = None,
    extra: str = "",
    sla: str | None = None,
    source_map: dict | None = None,
) -> dict[str, Path]:
    """Write a complete candidate and its companion artifacts beneath *root*."""
    paths = {
        name: root / name
        for name in (
            "candidate.md",
            "resolved.json",
            "coverage.json",
            "source-map.json",
            "methodology.patch",
            "base.md",
        )
    }
    body = ["# МНТ"]
    for heading in HEADINGS:
        if heading != omit:
            content = sla if heading.startswith("SLA") and sla else NO_DATA
            body.extend(["", f"## {heading}", "", content])
    if extra:
        body.extend(["", extra])
    paths["candidate.md"].write_text("\n".join(body) + "\n", encoding="utf-8")
    paths["base.md"].write_text("# МНТ\n", encoding="utf-8")
    paths["methodology.patch"].write_text("fixture patch\n", encoding="utf-8")
    paths["resolved.json"].write_text(
        json.dumps({"entities": [], "blocking_gaps": []}), encoding="utf-8"
    )
    paths["coverage.json"].write_text(
        json.dumps({"version": 1, "sections": {heading: "covered" for heading in HEADINGS}}),
        encoding="utf-8",
    )
    mapped = source_map if source_map is not None else {heading: ["fact.fixture"] for heading in HEADINGS}
    paths["source-map.json"].write_text(
        json.dumps({"version": 1, "sections": mapped}), encoding="utf-8"
    )
    return {
        "candidate": paths["candidate.md"],
        "resolved_evidence": paths["resolved.json"],
        "coverage": paths["coverage.json"],
        "source_map": paths["source-map.json"],
        "patch": paths["methodology.patch"],
        "base": paths["base.md"],
    }

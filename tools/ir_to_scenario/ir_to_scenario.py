#!/usr/bin/env python3
"""Convert a JMeter IR (jmx_parser output) into a Phase-2b scenario.yaml + report.

Element-mapping rules for HTTP functions, extractors, redirects, and CSV
shareMode are adapted from Gatling's Apache-2.0 `gatling-convert-from-jmeter`
skill (github.com/gatling/gatling-ai-extensions). The contract-first pipeline
(IR -> scenario.yaml -> generator) and the disposition reconciliation are ours.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _shared.common import Finding  # noqa: E402

CONVERTED = "converted"
PARTIAL = "partial"
TODO = "todo"
SKIPPED = "skipped-disabled"


@dataclass
class Conversion:
    scenario: dict[str, Any]
    report_rows: list[dict[str, str]] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    _populations: list = field(default_factory=list)

    def record(self, element: dict[str, Any], status: str, note: str = "") -> None:
        self.report_rows.append(
            {"id": element.get("id", "?"), "kind": element.get("kind", "?"),
             "name": element.get("name", ""), "status": status, "note": note}
        )

    def disposition_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self.report_rows:
            counts[row["status"]] = counts.get(row["status"], 0) + 1
        return counts


def kebab(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "flow"


def load_from_normalized(normalized: dict[str, Any]) -> dict[str, Any]:
    model = normalized["model"]
    return {"model": model, "profile": "stages", "stages": normalized["stages"]}


def thread_groups(children: list[Any]) -> list[dict[str, Any]]:
    return [n for n in children if isinstance(n, dict) and n.get("kind") == "thread_group" and n.get("enabled", True)]


def add_finding(conv: Conversion, rule: str, message: str, element_id: str) -> None:
    conv.findings.append(Finding(rule=rule, message=message, severity="blocking", path=element_id))


def convert(ir: dict[str, Any], *, system: str, scenario_id: str, number: int) -> Conversion:
    scenario: dict[str, Any] = {
        "id": scenario_id,
        "system": system,
        "number": number,
        "title": ir.get("test_plan", {}).get("name") or scenario_id,
        "source": {"type": "jmeter", "ref": ir.get("source", {}).get("file", "")},
        "sut": {"base_url": "${BASE_URL}"},
    }
    conv = Conversion(scenario={"scenario": scenario})

    groups = thread_groups(ir.get("children", []))
    populations: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for tg in groups:
        normalized = (tg.get("load") or {}).get("normalized")
        if normalized is None:
            note = (tg.get("load") or {}).get("note") or "load could not be normalized"
            add_finding(conv, "convert.load-not-normalized",
                        f"thread group '{tg.get('name')}' load not normalized: {note}", tg["id"])
            conv.record(tg, PARTIAL, note)
            load = {"model": "closed", "profile": "stages", "stages": [{"users": 1, "ramp_seconds": 0, "hold_seconds": 1}]}
        else:
            conv.record(tg, CONVERTED)
            load = load_from_normalized(normalized)
        population = {"name": kebab(tg.get("name", "flow")), "load": load, "steps": []}
        start_after = (normalized or {}).get("start_after_seconds") or 0
        if start_after > 0:
            population["start_after_seconds"] = start_after
        populations.append((tg, population))

    if len(populations) == 1:
        _, only = populations[0]
        scenario["steps"] = only["steps"]
        scenario["load"] = only["load"]
        if "start_after_seconds" in only:
            add_finding(conv, "convert.single-flow-start-after-dropped",
                        "single thread group has an initial delay; not representable in single-flow form", groups[0]["id"])
    elif populations:
        scenario["populations"] = [p for _tg, p in populations]
    conv._populations = populations

    # Walk descendants of thread groups as todo (Task 3 will replace with real mapping).
    # Thread groups themselves are already recorded above — only recurse into their children.
    top_level_children = ir.get("children", [])
    tg_ids = {tg["id"] for tg in groups}
    for child in top_level_children:
        if not isinstance(child, dict):
            continue
        if child.get("id") in tg_ids:
            # Thread group recorded above; descend into its children
            walk_children(child.get("children", []), conv)
        else:
            # Non-thread-group top-level child
            walk_children([child], conv)

    return conv


def walk_children(children: list[Any], conv: Conversion) -> None:
    """Record a disposition for every element so counts reconcile. Replaced with
    real mapping in later tasks; for now every element is recorded as todo."""
    for node in children:
        if not isinstance(node, dict):
            continue
        if not node.get("enabled", True):
            conv.record(node, SKIPPED)
        else:
            conv.record(node, TODO, "not yet mapped")
        walk_children(node.get("children", []), conv)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Convert JMeter IR to a scenario.yaml")
    parser.add_argument("ir_json")
    parser.add_argument("--system", required=True)
    parser.add_argument("--id", required=True, dest="scenario_id")
    parser.add_argument("--number", required=True, type=int)
    args = parser.parse_args(argv)
    ir = json.loads(Path(args.ir_json).read_text(encoding="utf-8"))
    conv = convert(ir, system=args.system, scenario_id=args.scenario_id, number=args.number)
    print(json.dumps(conv.disposition_counts()))
    return 0


if __name__ == "__main__":
    sys.exit(main())

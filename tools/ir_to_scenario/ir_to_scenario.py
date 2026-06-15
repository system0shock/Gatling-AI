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
    walk_children(ir.get("children", []), conv)
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

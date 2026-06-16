#!/usr/bin/env python3
"""Stop hook: remind to run the quality gate when the report is stale.

Advisory only. Compares the mtime of quality-gate-report.json against the
newest scenario.yaml under scenarios/ and examples/scenarios/. If the report is
missing or older than the newest scenario, emit a user-visible reminder.
Always exits 0; never blocks the Stop event.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT = REPO_ROOT / "quality-gate-report.json"
SCENARIO_ROOTS = (REPO_ROOT / "scenarios", REPO_ROOT / "examples" / "scenarios")


def needs_reminder(scenario_mtimes: list[float], report_mtime: float | None) -> bool:
    if not scenario_mtimes:
        return False
    if report_mtime is None:
        return True
    return max(scenario_mtimes) > report_mtime


def scenario_mtimes() -> list[float]:
    mtimes: list[float] = []
    for root in SCENARIO_ROOTS:
        if root.exists():
            for path in root.glob("**/scenario.yaml"):
                mtimes.append(path.stat().st_mtime)
    return mtimes


def main() -> int:
    try:
        sys.stdin.read()  # drain the payload; we rely on the filesystem
        report_mtime = REPORT.stat().st_mtime if REPORT.exists() else None
        if needs_reminder(scenario_mtimes(), report_mtime):
            print(json.dumps({
                "systemMessage": (
                    "Reminder: a scenario.yaml is newer than quality-gate-report.json "
                    "(or no report exists). Run the quality-gate skill before reporting done."
                )
            }))
    except Exception:
        return 0  # never block Stop on hook failure
    return 0


if __name__ == "__main__":
    sys.exit(main())

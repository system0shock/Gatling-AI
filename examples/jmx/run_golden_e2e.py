# examples/jmx/run_golden_e2e.py
"""Opt-in golden e2e: generate + quality-gate both migration goldens.

Run:  GATLING_AI_E2E=1 python examples/jmx/run_golden_e2e.py
Requires Maven + JDK on PATH. The smoke run (loads a SUT) is NOT performed here.
Exits non-zero if either golden misses its expected gate status.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDENS = [
    ("examples/scenarios/SHOP/legacy-backend-010/scenario.yaml", "passed"),
    ("examples/scenarios/SHOP/legacy-staged-011/scenario.yaml", "passed_with_warnings"),
]


def run_gate(scenario: str, project: Path) -> str:
    json_report = project / "quality-gate-report.json"
    subprocess.run(
        [sys.executable, "tools/gatling_generator/gatling_generator.py", scenario, str(project), "--format", "json"],
        cwd=REPO_ROOT, check=True,
    )
    subprocess.run(
        [sys.executable, "tools/quality_gate/quality_gate.py",
         "--scenario", scenario, "--project", str(project), "--profile", "mvp",
         "--json-report", str(json_report)],
        cwd=REPO_ROOT, check=False,
    )
    return json.loads(json_report.read_text(encoding="utf-8"))["status"]


def main() -> int:
    if os.environ.get("GATLING_AI_E2E") != "1":
        print("skipped (set GATLING_AI_E2E=1 to run the Maven gate tier)")
        return 0
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, (scenario, expected) in enumerate(GOLDENS):
            project = Path(tmp) / f"golden-{i}"
            status = run_gate(scenario, project)
            ok = status == expected
            print(f"{'OK ' if ok else 'FAIL'} {scenario} -> {status} (expected {expected})")
            if not ok:
                failures.append((scenario, status, expected))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""End-to-end acceptance tests for the RUN-001 coverage contract."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from methodology_evidence.reconcile import MANDATORY_MNT_SECTIONS
from methodology_quality_gate import methodology_quality_gate as gate
from methodology_quality_gate.fixtures import write_run_001_fixture


class Run001CoverageContractE2ETest(unittest.TestCase):
    def test_open_run_is_blocked_by_the_five_new_mandatory_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_run_001_fixture(Path(tmp), closed=False)
            resolved = json.loads(paths["resolved_evidence"].read_text(encoding="utf-8"))
            report = gate.run_gate(**paths)
        rules = {item["rule"] for item in resolved["blocking_gaps"]}
        self.assertEqual(rules, {"mandatory-section-missing"})
        self.assertEqual(len(resolved["blocking_gaps"]), 5)
        self.assertEqual(report.status, "blocked")
        self.assertTrue(any(item.rule == "blocking-conflicts" for item in report.findings))

    def test_reviews_and_confirmations_close_mandatory_bar_with_optional_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_run_001_fixture(Path(tmp), closed=True)
            coverage = json.loads(paths["coverage"].read_text(encoding="utf-8"))
            resolved = json.loads(paths["resolved_evidence"].read_text(encoding="utf-8"))
            report = gate.run_gate(**paths)
        mandatory = {heading for heading, _ in MANDATORY_MNT_SECTIONS}
        self.assertTrue(all(coverage["sections"][heading] == "covered" for heading in mandatory))
        self.assertEqual(
            sum(
                status == "partial"
                for heading, status in coverage["sections"].items()
                if heading not in mandatory
            ),
            12,
        )
        self.assertEqual(resolved["blocking_gaps"], [])
        self.assertEqual(report.status, "passed_with_warnings")
        self.assertEqual(gate.exit_code_for(report), 1)
        self.assertTrue(all(item.severity == "warning" for item in report.findings))


if __name__ == "__main__":
    unittest.main()

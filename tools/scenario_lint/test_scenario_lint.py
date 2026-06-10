#!/usr/bin/env python3
"""Unit tests for scenario lint."""

from __future__ import annotations

import json
import sys
import unittest
from datetime import date
from pathlib import Path

import scenario_lint

REPO_ROOT = Path(__file__).resolve().parents[2]


class SchemaContractTest(unittest.TestCase):
    def test_schema_requires_checks_per_step(self) -> None:
        schema = json.loads(
            (REPO_ROOT / "schemas" / "scenario.schema.json").read_text(encoding="utf-8")
        )
        step_schema = schema["properties"]["scenario"]["properties"]["steps"]["items"]
        self.assertIn("checks", step_schema["required"])


class DeadCodeRemovedTest(unittest.TestCase):
    def test_columns_helper_is_gone(self) -> None:
        self.assertFalse(hasattr(scenario_lint, "feeder_columns_from_config"))


def waived_document():
    return {
        "scenario": {
            "id": "demo",
            "title": "Demo",
            "source": {"type": "manual", "ref": "t"},
            "sut": {"base_url": "${BASE_URL}"},
            "steps": [
                {
                    "name": "post-thing",
                    "title": "Post thing",
                    "transaction": "01 demo.post-thing - Post thing",
                    "protocol": "http",
                    "request": {"method": "POST", "path": "/thing"},
                    "checks": [{"extract": {"type": "css", "expr": "a", "saveAs": "x"}}],
                }
            ],
            "load": {
                "model": "closed",
                "profile": "ramp",
                "users": 1,
                "ramp_seconds": 1,
                "duration_seconds": 1,
            },
            "assertions": [
                {"name": "a", "metric": "global.responseTime.p95", "op": "<", "value": 1}
            ],
        },
        "lint_waivers": [
            {
                "rule": "check-lint.mutating-status-check",
                "reason": "endpoint returns only 200 with empty body",
                "owner": "perf-team",
                "expires": "2999-01-01",
            }
        ],
    }


class WaiverTest(unittest.TestCase):
    def test_waiver_downgrades_blocking_finding(self) -> None:
        result = scenario_lint.lint_with_waivers(waived_document(), None, today=date(2026, 6, 10))
        blocking_rules = [f.rule for f in result.blocking]
        self.assertNotIn("check-lint.mutating-status-check", blocking_rules)
        self.assertEqual(result.waivers[0]["rule"], "check-lint.mutating-status-check")

    def test_expired_waiver_does_not_apply_and_warns(self) -> None:
        document = waived_document()
        document["lint_waivers"][0]["expires"] = "2020-01-01"
        result = scenario_lint.lint_with_waivers(document, None, today=date(2026, 6, 10))
        self.assertIn("check-lint.mutating-status-check", [f.rule for f in result.blocking])
        self.assertIn("waiver-lint.expired", [f.rule for f in result.warnings])

    def test_unused_waiver_warns(self) -> None:
        document = waived_document()
        document["scenario"]["steps"][0]["checks"].append({"status": 200})
        result = scenario_lint.lint_with_waivers(document, None, today=date(2026, 6, 10))
        self.assertIn("waiver-lint.unused", [f.rule for f in result.warnings])


if __name__ == "__main__":
    sys.exit(unittest.main())

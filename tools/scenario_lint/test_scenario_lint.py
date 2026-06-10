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


class ExtractTypeEnumTest(unittest.TestCase):
    def test_schema_restricts_extract_types(self) -> None:
        schema = json.loads(
            (REPO_ROOT / "schemas" / "scenario.schema.json").read_text(encoding="utf-8")
        )
        step_schema = schema["properties"]["scenario"]["properties"]["steps"]["items"]
        checks_schema = step_schema["properties"]["checks"]
        extract_variant = checks_schema["items"]["oneOf"][1]
        enum = extract_variant["properties"]["extract"]["properties"]["type"]["enum"]
        self.assertEqual(set(enum), {"css", "jsonPath", "regex"})


class LoadProfileLintTest(unittest.TestCase):
    def lint(self, load):
        document = {
            "scenario": {
                "id": "demo",
                "title": "Demo",
                "source": {"type": "manual", "ref": "t"},
                "sut": {"base_url": "${BASE_URL}"},
                "steps": [
                    {
                        "name": "open",
                        "title": "Open",
                        "transaction": "01 demo.open - Open",
                        "protocol": "http",
                        "request": {"method": "GET", "path": "/"},
                        "checks": [{"status": 200}],
                    }
                ],
                "load": load,
                "assertions": [
                    {"name": "a", "metric": "global.responseTime.p95", "op": "<", "value": 1}
                ],
            }
        }
        return [f.rule for f in scenario_lint.lint_document(document)]

    def test_stress_users_must_divide_by_levels(self) -> None:
        rules = self.lint(
            {"model": "closed", "profile": "stress", "users": 10, "levels": 3,
             "level_duration_seconds": 60}
        )
        self.assertIn("scenario-lint.stress-step-mismatch", rules)

    def test_spike_baseline_must_be_below_peak(self) -> None:
        rules = self.lint(
            {"model": "closed", "profile": "spike", "users": 5, "baseline_users": 5,
             "baseline_seconds": 60, "spike_rise_seconds": 5, "spike_hold_seconds": 10}
        )
        self.assertIn("scenario-lint.spike-baseline-not-below-peak", rules)

    def test_short_soak_warns(self) -> None:
        document_rules = self.lint(
            {"model": "closed", "profile": "soak", "users": 5, "duration_seconds": 600}
        )
        self.assertIn("scenario-lint.soak-too-short", document_rules)

    def test_valid_open_constant_has_no_load_findings(self) -> None:
        rules = self.lint(
            {"model": "open", "profile": "constant", "users_per_second": 2.5,
             "duration_seconds": 120}
        )
        self.assertEqual(rules, [])


if __name__ == "__main__":
    sys.exit(unittest.main())

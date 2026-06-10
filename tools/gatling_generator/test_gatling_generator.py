#!/usr/bin/env python3
"""Unit tests for the Gatling generator."""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import gatling_generator


def minimal_scenario(**overrides):
    scenario = {
        "id": "demo-flow",
        "title": "Demo flow",
        "source": {"type": "manual", "ref": "test"},
        "sut": {"base_url": "${BASE_URL}"},
        "steps": [
            {
                "name": "open-home",
                "title": "Open home",
                "transaction": "01 demo.open-home - Open home",
                "protocol": "http",
                "request": {"method": "GET", "path": "/"},
                "checks": [{"status": 200}],
            }
        ],
        "load": {
            "model": "closed",
            "profile": "ramp",
            "users": 5,
            "ramp_seconds": 10,
            "duration_seconds": 60,
        },
        "assertions": [
            {"name": "p95-under-800ms", "metric": "global.responseTime.p95", "op": "<", "value": 800},
            {"name": "ok-rate", "metric": "global.successfulRequests.percent", "op": ">", "value": 99},
        ],
    }
    scenario.update(overrides)
    return {"scenario": scenario}


class RenderAssertionsTest(unittest.TestCase):
    def test_simulation_contains_assertions(self) -> None:
        _, content = gatling_generator.render_simulation(minimal_scenario())
        self.assertIn(".assertions(", content)
        self.assertIn("global().responseTime().percentile(95.0).lt(800)", content)
        self.assertIn("global().successfulRequests().percent().gt(99)", content)

    def test_unknown_metric_is_rejected(self) -> None:
        document = minimal_scenario(
            assertions=[{"name": "x", "metric": "global.unknown.p95", "op": "<", "value": 1}]
        )
        with self.assertRaises(ValueError):
            gatling_generator.render_simulation(document)

    def test_unknown_op_is_rejected(self) -> None:
        document = minimal_scenario(
            assertions=[
                {"name": "x", "metric": "global.responseTime.p95", "op": "~", "value": 1}
            ]
        )
        with self.assertRaises(ValueError):
            gatling_generator.render_simulation(document)

    def test_missing_assertions_is_rejected(self) -> None:
        document = minimal_scenario()
        del document["scenario"]["assertions"]
        with self.assertRaises(ValueError):
            gatling_generator.render_simulation(document)


class FeederContainmentTest(unittest.TestCase):
    def test_feeder_resolving_outside_scenario_dir_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scenario_dir = root / "scenarios"
            scenario_dir.mkdir()
            outside = root / "outside.csv"
            outside.write_text("username\nalice\n", encoding="utf-8")
            link = scenario_dir / "users.csv"
            try:
                link.symlink_to(outside)
            except OSError:
                self.skipTest("symlinks unavailable without privileges")
            scenario_path = scenario_dir / "demo.yaml"
            scenario_path.write_text("placeholder", encoding="utf-8")
            document = minimal_scenario(
                data={"feeders": [{"name": "users", "file": "users.csv", "strategy": "circular"}]}
            )
            with self.assertRaises(ValueError):
                gatling_generator.copy_feeder_resources(document, scenario_path, root / "out")


class JsonOutputTest(unittest.TestCase):
    def test_failure_emits_findings_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scenario = Path(tmp) / "bad.yaml"
            scenario.write_text("scenario:\n  id: Bad_Id\n", encoding="utf-8")
            stdout = io.StringIO()
            with patch.object(sys, "stdout", stdout):
                code = gatling_generator.main(
                    [str(scenario), str(Path(tmp) / "out"), "--format", "json"]
                )
            self.assertEqual(code, 1)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["blocking"][0]["rule"], "generator.invalid-scenario")
            self.assertIn("message", payload["blocking"][0])


if __name__ == "__main__":
    sys.exit(unittest.main())

#!/usr/bin/env python3
"""Unit tests for the Gatling generator."""

from __future__ import annotations

import sys
import unittest

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


if __name__ == "__main__":
    sys.exit(unittest.main())

"""Behavior tests for deterministic methodology readiness."""

from __future__ import annotations

import unittest

from . import fixtures, readiness


class ReadinessTest(unittest.TestCase):
    def test_missing_environment_blocks_but_template_fields_do_not(self) -> None:
        value = fixtures.methodology_input()
        del value["environment"]["name"]
        report = readiness.readiness_report(
            value,
            [{"id": "environment.name", "target": "environment.name"}],
        )
        self.assertEqual(report["status"], "blocked")
        self.assertFalse(report["ready_for_test"])
        self.assertEqual(report["missing"][0]["question_id"], "environment.name")

    def test_confirmed_but_empty_surface_blocks(self) -> None:
        value = fixtures.methodology_input()
        value["surface"]["included"] = []
        value["surface"]["added"] = []
        report = readiness.readiness_report(value, [])
        self.assertEqual(report["status"], "blocked")
        self.assertIn("surface.entities", {item["target"] for item in report["missing"]})

    def test_unconfirmed_surface_blocks(self) -> None:
        value = fixtures.methodology_input()
        value["surface"]["status"] = "draft"
        report = readiness.readiness_report(value, [])
        self.assertFalse(report["ready_for_test"])
        self.assertEqual(report["missing"][0]["target"], "surface.entities")

    def test_false_profile_acceptance_and_test_data_readiness_block(self) -> None:
        value = fixtures.methodology_input()
        value["profile"]["accepted"] = False
        value["test_data"]["ready"] = False
        report = readiness.readiness_report(value, [])
        self.assertEqual(
            [item["target"] for item in report["missing"]],
            ["profile.accepted", "test_data.ready"],
        )

    def test_missing_targets_follow_critical_target_order(self) -> None:
        value = fixtures.methodology_input()
        del value["load"]["initial"]
        del value["observability"]["dashboard"]
        report = readiness.readiness_report(
            value,
            [{"id": "observability.dashboard", "target": "observability.dashboard"}],
        )
        self.assertEqual(
            [(item["target"], item["question_id"]) for item in report["missing"]],
            [("load.initial", None), ("observability.dashboard", "observability.dashboard")],
        )


if __name__ == "__main__":
    unittest.main()

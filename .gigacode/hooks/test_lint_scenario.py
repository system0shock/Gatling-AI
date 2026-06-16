#!/usr/bin/env python3
"""Unit tests for the lint_scenario PostToolUse hook."""
from __future__ import annotations

import unittest
from pathlib import Path

import lint_scenario

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_REL = "examples/scenarios/SHOP/checkout-mix-001/scenario.yaml"


class ScenarioPathExtractionTest(unittest.TestCase):
    def test_extracts_scenario_yaml_from_tool_input(self) -> None:
        existing = (REPO_ROOT / FIXTURE_REL).resolve()
        self.assertTrue(existing.exists(), "fixture scenario must exist")
        payload = {"cwd": str(REPO_ROOT), "tool_input": {"file_path": FIXTURE_REL}}
        self.assertEqual(lint_scenario.scenario_paths_from_payload(payload, REPO_ROOT), [existing])

    def test_ignores_non_scenario_files(self) -> None:
        payload = {"cwd": str(REPO_ROOT), "tool_input": {"file_path": "README.md"}}
        self.assertEqual(lint_scenario.scenario_paths_from_payload(payload, REPO_ROOT), [])

    def test_ignores_missing_scenario_files(self) -> None:
        payload = {"cwd": str(REPO_ROOT), "tool_input": {"file_path": "scenarios/NOPE/x-001/scenario.yaml"}}
        self.assertEqual(lint_scenario.scenario_paths_from_payload(payload, REPO_ROOT), [])

    def test_deduplicates_repeated_paths(self) -> None:
        payload = {"cwd": str(REPO_ROOT), "tool_input": {"a": FIXTURE_REL, "b": FIXTURE_REL}}
        self.assertEqual(len(lint_scenario.scenario_paths_from_payload(payload, REPO_ROOT)), 1)

    def test_handles_payload_without_cwd(self) -> None:
        payload = {"tool_input": {"file_path": FIXTURE_REL}}
        self.assertEqual(lint_scenario.scenario_paths_from_payload(payload, REPO_ROOT),
                         [(REPO_ROOT / FIXTURE_REL).resolve()])


if __name__ == "__main__":
    unittest.main()

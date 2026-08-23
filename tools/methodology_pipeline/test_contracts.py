#!/usr/bin/env python3
"""Behavior tests for methodology-first configuration contracts."""

from __future__ import annotations

import unittest
from pathlib import Path

if __package__:
    from . import contracts
    from .sections import CANONICAL_HEADINGS
else:
    import contracts
    from sections import CANONICAL_HEADINGS


REPO_ROOT = Path(__file__).resolve().parents[2]


class MethodologyAssetContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.package = REPO_ROOT / ".gigacode" / "skills" / "manage-methodology"

    def test_default_profile_contains_approved_values(self) -> None:
        profile = contracts.load_yaml_mapping(
            self.package / "profiles" / "default-v1.yaml",
            "methodology-profile.schema.json",
        )
        self.assertEqual(profile["profile_id"], "default-v1")
        self.assertEqual(profile["profile_version"], 1)
        self.assertEqual(profile["tests"]["maximum_search"]["step_minutes"], 20)
        self.assertEqual(profile["tests"]["maximum_confirmation"]["duration_minutes"], 120)
        self.assertEqual(profile["tests"]["stability"]["duration_minutes"], 480)
        self.assertEqual(profile["tests"]["stability"]["load_factor"], 0.8)
        self.assertEqual(profile["criteria"]["response_time"]["percentile"], "p95")
        self.assertEqual(profile["criteria"]["response_time"]["threshold_ms"], 1000)
        self.assertEqual(profile["criteria"]["technical_errors"]["max_percent"], 5)
        self.assertEqual(profile["criteria"]["cpu"]["max_percent"], 40)
        self.assertEqual(profile["criteria"]["memory"]["max_percent"], 80)

    def test_question_ids_and_targets_are_unique(self) -> None:
        catalog = contracts.load_yaml_mapping(
            self.package / "questions.yaml",
            "methodology-questions.schema.json",
        )
        ids = [item["id"] for item in catalog["questions"]]
        targets = [item["target"] for item in catalog["questions"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(targets), len(set(targets)))

    def test_template_contract_matches_all_canonical_headings(self) -> None:
        contract = contracts.load_yaml_mapping(
            self.package / "templates" / "methodology-template-contract.yaml",
            "methodology-template-contract.schema.json",
        )
        self.assertEqual(
            [item["heading"] for item in contract["sections"]],
            CANONICAL_HEADINGS,
        )


if __name__ == "__main__":
    unittest.main()

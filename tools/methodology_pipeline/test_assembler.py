"""Behavior tests for canonical methodology input assembly."""

from __future__ import annotations

import unittest

from . import assembler, fixtures


class AssemblyTest(unittest.TestCase):
    def test_build_input_binds_snapshot_surface_profile_and_answers(self) -> None:
        result = assembler.build_input(
            fixtures.workspace_snapshot(),
            fixtures.surface_review(),
            fixtures.resolved_profile(),
            fixtures.question_catalog(),
            fixtures.complete_answers(),
        )
        self.assertEqual(result["workspace_snapshot_id"], "a" * 64)
        self.assertEqual(result["profile"]["profile_id"], "default-v1")
        self.assertEqual(result["surface"]["status"], "confirmed")
        self.assertEqual(result["load"]["unit"], "rps")

    def test_build_input_rejects_surface_for_different_snapshot(self) -> None:
        surface = fixtures.surface_review()
        surface["snapshot_id"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "surface review does not match workspace snapshot"):
            assembler.build_input(
                fixtures.workspace_snapshot(), surface, fixtures.resolved_profile(),
                fixtures.question_catalog(), fixtures.complete_answers(),
            )

    def test_build_input_does_not_retain_mutable_input_references(self) -> None:
        surface = fixtures.surface_review()
        profile = fixtures.resolved_profile()
        answers = fixtures.complete_answers()
        result = assembler.build_input(
            fixtures.workspace_snapshot(), surface, profile,
            fixtures.question_catalog(), answers,
        )
        surface["included"][0]["display_name"] = "Changed"
        profile["criteria"]["cpu"]["max_percent"] = 0
        answers["not_applicable_sections"][0]["reason"] = "Changed"
        self.assertEqual(result["surface"]["included"][0]["display_name"], "Orders")
        self.assertEqual(result["profile"]["criteria"]["cpu"]["max_percent"], 40)
        self.assertEqual(result["not_applicable_sections"][0]["reason"], "No external interfaces")


if __name__ == "__main__":
    unittest.main()

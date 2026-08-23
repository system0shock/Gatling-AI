"""Behavior tests for canonical methodology input assembly."""

from __future__ import annotations

from copy import deepcopy
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

    def test_build_input_validates_catalog_and_answers_before_assembly(self) -> None:
        catalog = fixtures.question_catalog()
        catalog["unexpected"] = True
        with self.assertRaisesRegex(ValueError, "methodology-questions.schema.json"):
            assembler.build_input(
                fixtures.workspace_snapshot(), fixtures.surface_review(),
                fixtures.resolved_profile(), catalog, fixtures.complete_answers(),
            )

        answers = fixtures.complete_answers()
        answers["unexpected"] = True
        with self.assertRaisesRegex(ValueError, "methodology-answers.schema.json"):
            assembler.build_input(
                fixtures.workspace_snapshot(), fixtures.surface_review(),
                fixtures.resolved_profile(), fixtures.question_catalog(), answers,
            )

    def test_build_input_rejects_structurally_invalid_snapshot(self) -> None:
        with self.assertRaisesRegex(ValueError, "workspace snapshot"):
            assembler.build_input(
                [], fixtures.surface_review(), fixtures.resolved_profile(),
                fixtures.question_catalog(), fixtures.complete_answers(),
            )

    def test_build_input_keeps_snapshot_metadata_outside_the_structural_boundary(self) -> None:
        snapshot = {
            "snapshot_id": "a" * 64,
            "version": 2,
            "discovery": {"source": "workspace"},
        }
        result = assembler.build_input(
            snapshot, fixtures.surface_review(), fixtures.resolved_profile(),
            fixtures.question_catalog(), fixtures.complete_answers(),
        )
        self.assertEqual(result["workspace_snapshot_id"], "a" * 64)

    def test_build_input_validates_surface_and_profile_before_snapshot_matching(self) -> None:
        surface = fixtures.surface_review()
        surface["status"] = "draft"
        with self.assertRaisesRegex(ValueError, "methodology-surface-review.schema.json"):
            assembler.build_input(
                {"snapshot_id": "b" * 64}, surface, fixtures.resolved_profile(),
                fixtures.question_catalog(), fixtures.complete_answers(),
            )

        profile = fixtures.resolved_profile()
        profile["unexpected"] = True
        with self.assertRaisesRegex(ValueError, "methodology-profile.schema.json"):
            assembler.build_input(
                {"snapshot_id": "b" * 64}, fixtures.surface_review(), profile,
                fixtures.question_catalog(), fixtures.complete_answers(),
            )

    def test_capabilities_use_only_normalized_included_and_added_protocols(self) -> None:
        surface = fixtures.surface_review()
        surface["included"][0]["attributes"]["protocol"] = " HTTP "
        surface["included"].append({"attributes": {}})
        surface["added"] = [
            {"attributes": {"protocol": "grpc"}},
            {"attributes": {"protocol": 42}},
        ]
        surface["excluded"] = [{"attributes": {"protocol": "kafka"}}]
        self.assertEqual(
            assembler.capabilities_from_surface(surface),
            ("grpc", "http"),
        )

    def test_build_input_allows_a_valid_draft_with_absent_optional_execution_fields(self) -> None:
        result = assembler.build_input(
            fixtures.workspace_snapshot(), fixtures.surface_review(),
            fixtures.resolved_profile(), fixtures.question_catalog(), fixtures.answers(),
        )
        self.assertEqual(result["load"], {})
        self.assertEqual(result["observability"], {})

    def test_build_input_rejects_na_for_included_surface_entity_aliases(self) -> None:
        cases = (
            ("integrations", "integration"),
            ("interfaces", "interface"),
            ("interfaces", "http-interface"),
            ("interfaces", "async-interface"),
            ("flows", "flow"),
            ("flows", "user-flow"),
            ("flows", "technical-flow"),
        )
        for section_id, entity_type in cases:
            with self.subTest(section_id=section_id, entity_type=entity_type):
                surface = fixtures.surface_review()
                surface["included"][0]["entity_type"] = entity_type
                answers = fixtures.complete_answers()
                answers["not_applicable_sections"] = [{
                    "section_id": section_id,
                    "reason": "No applicable entities",
                }]
                with self.assertRaisesRegex(
                    ValueError,
                    f"not applicable section conflicts with selected surface entities: {section_id}",
                ):
                    assembler.build_input(
                        fixtures.workspace_snapshot(), surface,
                        fixtures.resolved_profile(), fixtures.question_catalog(),
                        answers,
                    )

    def test_build_input_rejects_na_for_user_added_surface_entity(self) -> None:
        surface = fixtures.surface_review()
        entity = deepcopy(surface["included"].pop())
        entity["entity_type"] = "integration"
        entity["sources"][0]["repo_id"] = "user"
        entity["sources"][0]["relative_path"] = "surface-review"
        surface["added"] = [entity]
        answers = fixtures.complete_answers()
        with self.assertRaisesRegex(
            ValueError,
            "not applicable section conflicts with selected surface entities: integrations",
        ):
            assembler.build_input(
                fixtures.workspace_snapshot(), surface,
                fixtures.resolved_profile(), fixtures.question_catalog(), answers,
            )

    def test_build_input_allows_na_for_an_empty_matching_surface_section(self) -> None:
        result = assembler.build_input(
            fixtures.workspace_snapshot(), fixtures.surface_review(),
            fixtures.resolved_profile(), fixtures.question_catalog(),
            fixtures.complete_answers(),
        )
        self.assertEqual(
            result["not_applicable_sections"],
            [{"section_id": "integrations", "reason": "No external interfaces"}],
        )


if __name__ == "__main__":
    unittest.main()

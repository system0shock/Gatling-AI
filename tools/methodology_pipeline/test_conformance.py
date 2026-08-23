#!/usr/bin/env python3
"""Behavior tests for methodology readiness and template conformance reports."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re
import sys
import unittest

if __package__:
    from . import conformance, fixtures, readiness
    from .contracts import validate_artifact
    from .renderer import NO_DATA
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from tools.methodology_pipeline import conformance, fixtures, readiness
    from tools.methodology_pipeline.contracts import validate_artifact
    from tools.methodology_pipeline.renderer import NO_DATA


class ConformanceTest(unittest.TestCase):
    def test_missing_optional_section_is_advisory(self) -> None:
        report = conformance.template_report(
            fixtures.rendered_methodology(missing="Архитектура"),
            fixtures.template_contract(),
            fixtures.methodology_input(),
        )
        section = next(item for item in report["sections"] if item["heading"] == "Архитектура")
        self.assertEqual(section["status"], "missing")
        self.assertEqual(report["status"], "incomplete")
        self.assertFalse(report["template_complete"])

    def test_not_applicable_requires_explicit_reason(self) -> None:
        value = fixtures.methodology_input()
        value["not_applicable_sections"] = [
            {"section_id": "integrations", "reason": "Система не имеет внешних интеграций."}
        ]
        report = conformance.template_report(
            fixtures.rendered_methodology(missing="Реестр интеграций"),
            fixtures.template_contract(),
            value,
        )
        section = next(item for item in report["sections"] if item["id"] == "integrations")
        self.assertEqual(section["status"], "not_applicable")

    def test_manual_text_does_not_make_readiness_green(self) -> None:
        value = fixtures.methodology_input()
        del value["environment"]["name"]
        readiness_result = readiness.readiness_report(value, [])
        self.assertEqual(readiness_result["status"], "blocked")

    def test_manual_prose_does_not_supply_required_generated_construct(self) -> None:
        markdown = fixtures.rendered_methodology().replace(
            "<!-- mnt:construct:test-step-search -->\n", "", 1
        ).replace(
            "<!-- mnt:manual:start id=test-types -->\n",
            "<!-- mnt:manual:start id=test-types -->\nThe search stage is documented manually.\n",
            1,
        )
        report = conformance.template_report(
            markdown, fixtures.template_contract(), fixtures.methodology_input()
        )
        section = next(item for item in report["sections"] if item["id"] == "test-types")
        self.assertEqual(section["status"], "partial")
        self.assertIn("missing required construct: <!-- mnt:construct:test-step-search -->", section["gaps"])

    def test_no_data_marker_makes_section_missing_without_na_decision(self) -> None:
        value = fixtures.methodology_input()
        value["not_applicable_sections"] = []
        markdown = fixtures.rendered_methodology().replace(
            "> Не применимо: No external interfaces.\n", NO_DATA + "\n", 1
        )
        report = conformance.template_report(markdown, fixtures.template_contract(), value)
        section = next(item for item in report["sections"] if item["id"] == "integrations")
        self.assertEqual(section["status"], "missing")

    def test_table_requires_exact_header_and_minimum_data_rows(self) -> None:
        original = fixtures.rendered_methodology()
        markdown = original.replace(
            "| Компонент | Связи | Источники |\n", "| Компонент | Источники | Связи |\n", 1
        )
        report = conformance.template_report(
            markdown, fixtures.template_contract(), fixtures.methodology_input()
        )
        section = next(item for item in report["sections"] if item["id"] == "architecture")
        self.assertEqual(section["status"], "partial")
        self.assertIn("required table header is missing", section["gaps"])
        header = "| Компонент | Связи | Источники |"
        header_start = original.index(header)
        separator_end = original.index("\n", original.index("\n", header_start) + 1) + 1
        row_end = original.index("\n", separator_end) + 1
        no_rows = original[:separator_end] + original[row_end:]
        report = conformance.template_report(
            no_rows, fixtures.template_contract(), fixtures.methodology_input()
        )
        section = next(item for item in report["sections"] if item["id"] == "architecture")
        self.assertEqual(section["status"], "partial")
        self.assertIn("required table has fewer than 1 data rows", section["gaps"])

    def test_missing_required_input_makes_existing_section_partial(self) -> None:
        value = fixtures.methodology_input()
        del value["environment"]["name"]
        report = conformance.template_report(
            fixtures.rendered_methodology(), fixtures.template_contract(), value
        )
        section = next(item for item in report["sections"] if item["id"] == "environment")
        self.assertEqual(section["status"], "partial")
        self.assertEqual(section["question_links"], ["environment.name"])
        self.assertIn("required input is missing: environment.name", section["gaps"])

    def test_false_boolean_required_input_is_present(self) -> None:
        value = fixtures.methodology_input()
        value["test_data"]["ready"] = False
        report = conformance.template_report(
            fixtures.rendered_methodology(), fixtures.template_contract(), value
        )
        section = next(item for item in report["sections"] if item["id"] == "test-data")
        self.assertEqual(section["status"], "complete")
        self.assertNotIn("required input is missing: test_data.ready", section["gaps"])

    def test_nonempty_manual_and_legacy_sections_without_generated_block_are_partial(self) -> None:
        markdown = fixtures.rendered_methodology()
        manual_only = re.sub(
            r"(?s)<!-- mnt:generated:start id=environment -->\n.*?<!-- mnt:generated:end -->\n\n",
            "",
            markdown,
            count=1,
        ).replace(
            "<!-- mnt:manual:start id=environment -->\n",
            "<!-- mnt:manual:start id=environment -->\nManual environment evidence.\n",
            1,
        )
        legacy = re.sub(
            r"(?ms)(## Тестовый стенд\n).*?(?=^## )",
            r"\1Legacy environment evidence.\n\n",
            markdown,
            count=1,
        )
        for candidate in (manual_only, legacy):
            with self.subTest(candidate="manual" if candidate == manual_only else "legacy"):
                report = conformance.template_report(
                    candidate, fixtures.template_contract(), fixtures.methodology_input()
                )
                section = next(item for item in report["sections"] if item["id"] == "environment")
                self.assertEqual(section["status"], "partial")
                self.assertIn("generated block is missing", section["gaps"])

    def test_legal_not_applicable_section_counts_as_satisfied_in_summary(self) -> None:
        value = fixtures.methodology_input()
        value["not_applicable_sections"] = [
            {"section_id": section_id, "reason": "No applicable data."}
            for section_id in ("integrations", "interfaces", "flows", "risks")
        ]
        candidate = fixtures.empty_methodology_template()
        if __package__:
            from . import renderer
        else:
            from tools.methodology_pipeline import renderer
        candidate = renderer.render_candidate(
            candidate, value, fixtures.generation_state(candidate)
        ).markdown
        report = conformance.template_report(candidate, fixtures.template_contract(), value)
        self.assertTrue(report["template_complete"])
        self.assertEqual(report["status"], "complete")
        self.assertIn("Complete: 17/17", conformance.render_template_markdown(report))

    def test_duplicate_table_separator_is_not_a_data_row(self) -> None:
        original = fixtures.rendered_methodology()
        header = "| Компонент | Связи | Источники |"
        header_start = original.index(header)
        separator_start = original.index("\n", header_start) + 1
        separator_end = original.index("\n", separator_start) + 1
        row_end = original.index("\n", separator_end) + 1
        candidate = (
            original[:separator_end]
            + original[separator_start:separator_end]
            + original[row_end:]
        )
        report = conformance.template_report(
            candidate, fixtures.template_contract(), fixtures.methodology_input()
        )
        section = next(item for item in report["sections"] if item["id"] == "architecture")
        self.assertEqual(section["status"], "partial")
        self.assertIn("required table has fewer than 1 data rows", section["gaps"])

    def test_illegal_empty_and_unknown_not_applicable_decisions_are_rejected(self) -> None:
        for section_id, reason, expected in (
            ("environment", "Not needed", "does not allow not applicable"),
            ("unknown-section", "Not needed", "unknown not applicable section"),
            ("integrations", "", "methodology-input.schema.json"),
        ):
            with self.subTest(section_id=section_id, reason=reason):
                value = fixtures.methodology_input()
                value["not_applicable_sections"] = [{"section_id": section_id, "reason": reason}]
                with self.assertRaisesRegex(ValueError, expected):
                    conformance.template_report(
                        fixtures.rendered_methodology(), fixtures.template_contract(), value
                    )

    def test_duplicate_and_malformed_document_markers_fail_deterministically(self) -> None:
        markdown = fixtures.rendered_methodology()
        duplicate = markdown.replace("## Архитектура\n", "## Архитектура\n", 1) + "\n## Архитектура\n"
        with self.assertRaisesRegex(ValueError, "duplicate canonical heading: Архитектура"):
            conformance.template_report(duplicate, fixtures.template_contract(), fixtures.methodology_input())
        malformed = markdown.replace("<!-- mnt:generated:end -->", "<!-- mnt:generated:broken -->", 1)
        with self.assertRaisesRegex(ValueError, "malformed managed marker"):
            conformance.template_report(malformed, fixtures.template_contract(), fixtures.methodology_input())

    def test_malformed_canonical_heading_fails_deterministically(self) -> None:
        for replacement in (
            "### Архитектура\n",
            "##  Архитектура\n",
            "##\tАрхитектура\n",
            "## Архитектура \n",
            "## Архитектура ##\n",
        ):
            with self.subTest(replacement=replacement):
                markdown = fixtures.rendered_methodology().replace("## Архитектура\n", replacement, 1)
                with self.assertRaisesRegex(ValueError, "malformed canonical heading: Архитектура"):
                    conformance.template_report(markdown, fixtures.template_contract(), fixtures.methodology_input())

    def test_report_has_exactly_17_ordered_records_and_valid_schema(self) -> None:
        contract = fixtures.template_contract()
        report = conformance.template_report(
            fixtures.rendered_methodology(), contract, fixtures.methodology_input()
        )
        self.assertEqual(len(report["sections"]), 17)
        self.assertEqual(
            [item["id"] for item in report["sections"]],
            [item["id"] for item in contract["sections"]],
        )
        validate_artifact(report, "methodology-template-report.schema.json")

    def test_template_conformance_does_not_change_readiness(self) -> None:
        value = fixtures.methodology_input()
        ready = readiness.readiness_report(value, [])
        markdown = fixtures.rendered_methodology().replace(
            "<!-- mnt:construct:test-step-search -->\n", "", 1
        )
        conformance.template_report(markdown, fixtures.template_contract(), value)
        self.assertTrue(ready["ready_for_test"])
        self.assertEqual(ready["status"], "ready")

    def test_markdown_summaries_are_deterministic_and_group_questions(self) -> None:
        readiness_report = {
            "version": 1, "status": "blocked", "ready_for_test": False,
            "workspace_snapshot_id": "a" * 64,
            "missing": [{"target": "environment.name", "question_id": "environment.name", "message": "required execution input is missing: environment.name"}],
        }
        template_report = {
            "version": 1, "status": "incomplete", "template_complete": False,
            "sections": [
                {"id": f"section-{index}", "heading": f"Section {index}", "status": "complete" if index < 14 else "missing", "gaps": [] if index < 14 else ["section is absent"], "question_links": [] if index < 16 else ["environment.name"]}
                for index in range(17)
            ],
        }
        self.assertEqual(
            conformance.render_readiness_markdown(readiness_report),
            "# Methodology readiness\n\nStatus: BLOCKED\n\n- environment.name (question: environment.name): required execution input is missing: environment.name\n",
        )
        rendered = conformance.render_template_markdown(template_report)
        self.assertEqual(rendered, conformance.render_template_markdown(deepcopy(template_report)))
        self.assertTrue(rendered.startswith("# Methodology template conformance\n\nComplete: 14/17\n"))
        self.assertIn("## Missing\n\n- Section 14: section is absent\n- Section 15: section is absent\n- Section 16 [questions: environment.name]: section is absent\n", rendered)


if __name__ == "__main__":
    unittest.main()

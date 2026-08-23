"""Behavior tests for catalog-driven scalar methodology answers."""

from __future__ import annotations

import unittest

from . import fixtures, questionnaire


class QuestionnaireTest(unittest.TestCase):
    def test_only_missing_applicable_required_questions_are_returned(self) -> None:
        model = {"load": {"unit": "rps"}, "environment": {}, "observability": {}}
        pending = questionnaire.unresolved_questions(
            model,
            fixtures.question_catalog(),
            {"http"},
        )
        ids = [item["id"] for item in pending]
        self.assertNotIn("load.unit", ids)
        self.assertIn("environment.name", ids)

    def test_whitespace_only_required_text_is_invalid_and_remains_pending(self) -> None:
        with self.assertRaisesRegex(ValueError, "environment.name"):
            questionnaire.validate_answer(
                fixtures.question("environment.name"), " \t"
            )
        model = {
            "load": {"unit": "rps", "operation_mix": " \t"},
            "environment": {"name": "\n"},
            "observability": {"cpu_signal": "   "},
        }
        pending = questionnaire.unresolved_questions(
            model, fixtures.question_catalog(), {"http"}
        )
        pending_ids = {item["id"] for item in pending}
        self.assertTrue({
            "load.operation_mix",
            "environment.name",
            "observability.cpu_signal",
        }.issubset(pending_ids))

    def test_scalar_types_and_choices_are_catalog_driven(self) -> None:
        with self.assertRaisesRegex(ValueError, "load.unit"):
            questionnaire.validate_answer(
                fixtures.question("load.unit"), "unsupported-unit"
            )
        with self.assertRaisesRegex(ValueError, "load.initial"):
            questionnaire.validate_answer(
                fixtures.question("load.initial"), True
            )

    def test_choice_rejects_boolean_values_matching_numeric_choices(self) -> None:
        question = {
            "id": "load.parallelism",
            "type": "choice",
            "choices": [0, 1],
        }
        for value in (False, True):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "load.parallelism"):
                    questionnaire.validate_answer(question, value)

    def test_apply_scalar_answers_uses_catalog_target_without_mutating_base(self) -> None:
        base = {"load": {}, "environment": {}}
        resolved = questionnaire.apply_scalar_answers(
            base,
            fixtures.question_catalog(),
            {"questions": {"load.unit": {"value": "rps"}}},
        )
        self.assertEqual(resolved["load"]["unit"], "rps")
        self.assertEqual(base, {"load": {}, "environment": {}})

    def test_apply_scalar_answers_rejects_unknown_question_id(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown question id: unknown.answer"):
            questionnaire.apply_scalar_answers(
                {}, fixtures.question_catalog(), {"questions": {"unknown.answer": {"value": "x"}}}
            )

    def test_capability_inapplicable_questions_are_not_pending(self) -> None:
        catalog = {
            "version": 1,
            "questions": [{
                "id": "observability.http_status",
                "section": "Observability",
                "prompt": "HTTP status signal",
                "target": "observability.cpu_signal",
                "type": "text",
                "required": True,
                "applies_to": ["http"],
            }],
        }
        pending = questionnaire.unresolved_questions(
            {"load": {}, "environment": {}, "observability": {}},
            catalog,
            {"grpc"},
        )
        self.assertNotIn("observability.http_status", [item["id"] for item in pending])


if __name__ == "__main__":
    unittest.main()

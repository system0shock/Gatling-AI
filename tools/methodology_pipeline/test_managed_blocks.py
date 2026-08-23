#!/usr/bin/env python3
"""Behavior tests for byte-safe methodology managed blocks."""

from __future__ import annotations

import unittest

if __package__:
    from . import fixtures, managed_blocks
    from .sections import CANONICAL_SECTIONS
else:
    import fixtures
    import managed_blocks
    from sections import CANONICAL_SECTIONS


TEST_TYPES_HEADING = dict(CANONICAL_SECTIONS)["test-types"]
SCOPE_HEADING = dict(CANONICAL_SECTIONS)["scope"]


class ManagedBlocksTest(unittest.TestCase):
    def test_merge_replaces_generated_and_preserves_manual_bytes(self) -> None:
        current = fixtures.document_with_blocks(manual="ручной текст\r\n")
        result = managed_blocks.merge_generated(
            current,
            {"test-types": "новый generated\n"},
            fixtures.generation_state(current),
        )
        self.assertIn("новый generated\n", result.markdown)
        self.assertIn("ручной текст\r\n", result.markdown)
        self.assertEqual(result.conflicts, ())
        self.assertEqual(result.warnings, ())
        self.assertIn("test-types", result.generation_state["blocks"])

    def test_changed_generated_block_is_a_conflict(self) -> None:
        original = fixtures.document_with_blocks(generated="исходный\n")
        changed = original.replace(
            "исходный", "ручная правка внутри generated"
        )
        result = managed_blocks.merge_generated(
            changed,
            {"test-types": "новый\n"},
            fixtures.generation_state(original),
        )
        self.assertEqual(result.conflicts[0]["rule"], "managed-block-drift")
        self.assertEqual(result.markdown, changed)

    def test_nonempty_generated_block_without_prior_state_is_not_overwritten(self) -> None:
        current = fixtures.document_with_blocks(
            generated="неизвестный источник\n"
        )
        result = managed_blocks.merge_generated(
            current, {"test-types": "новый\n"}, {"version": 1, "blocks": {}}
        )
        self.assertEqual(result.conflicts[0]["rule"], "generation-state-missing")
        self.assertEqual(result.markdown, current)

    def test_empty_generated_block_without_prior_state_is_safe_first_generation(self) -> None:
        current = fixtures.document_with_blocks(generated="")
        result = managed_blocks.merge_generated(
            current, {"test-types": "первый render\n"}, {"version": 1, "blocks": {}}
        )
        self.assertEqual(result.conflicts, ())
        self.assertIn("первый render\n", result.markdown)

    def test_partial_merge_preserves_untouched_state_for_later_render(self) -> None:
        current = (
            fixtures.document_with_blocks(generated="types original\n")
            + fixtures.document_with_blocks(
                generated="scope original\n", section_id="scope"
            )
        )
        state = fixtures.generation_state(current)
        expected_scope = dict(state["blocks"]["scope"])
        first = managed_blocks.merge_generated(
            current, {"test-types": "types next\n"}, state
        )
        state["blocks"]["scope"]["resolution"] = "keep"
        self.assertEqual(first.generation_state["blocks"]["scope"], expected_scope)

        second = managed_blocks.merge_generated(
            first.markdown,
            {"scope": "scope next\n"},
            first.generation_state,
        )
        self.assertEqual(second.conflicts, ())
        self.assertEqual(
            second.generation_state["blocks"]["test-types"],
            first.generation_state["blocks"]["test-types"],
        )

    def test_partial_resolution_preserves_untouched_state_for_later_render(self) -> None:
        original = (
            fixtures.document_with_blocks(generated="types original\n")
            + fixtures.document_with_blocks(
                generated="scope original\n", section_id="scope"
            )
        )
        changed = original.replace("types original", "types edited")
        state = fixtures.generation_state(original)
        expected_scope = dict(state["blocks"]["scope"])
        resolved = managed_blocks.resolve_drift(
            changed,
            {"test-types": "types next\n"},
            state,
            {"test-types": "replace"},
        )
        self.assertEqual(resolved.generation_state["blocks"]["scope"], expected_scope)

        next_run = managed_blocks.merge_generated(
            resolved.markdown,
            {"scope": "scope next\n"},
            resolved.generation_state,
        )
        self.assertEqual(next_run.conflicts, ())

    def test_merge_rejects_nonempty_renderer_body_without_terminal_newline(self) -> None:
        current = fixtures.document_with_blocks(generated="old\n")
        state = fixtures.generation_state(current)
        expected_state = fixtures.generation_state(current)
        with self.assertRaisesRegex(ValueError, "terminal newline"):
            managed_blocks.merge_generated(
                current, {"test-types": "new"}, state
            )
        self.assertEqual(state, expected_state)

    def test_merge_rejects_renderer_body_with_managed_marker_line(self) -> None:
        current = fixtures.document_with_blocks(generated="old\n")
        with self.assertRaisesRegex(ValueError, "managed marker"):
            managed_blocks.merge_generated(
                current,
                {
                    "test-types":
                        "safe\n<!-- mnt:manual:start id=test-types -->\n"
                },
                fixtures.generation_state(current),
            )

    def test_resolve_rejects_nonempty_renderer_body_without_terminal_newline(self) -> None:
        original = fixtures.document_with_blocks(generated="old\n")
        changed = original.replace("old", "edited")
        with self.assertRaisesRegex(ValueError, "terminal newline"):
            managed_blocks.resolve_drift(
                changed,
                {"test-types": "new"},
                fixtures.generation_state(original),
                {"test-types": "replace"},
            )

    def test_resolve_rejects_renderer_body_with_managed_marker_line(self) -> None:
        original = fixtures.document_with_blocks(generated="old\n")
        changed = original.replace("old", "edited")
        with self.assertRaisesRegex(ValueError, "managed marker"):
            managed_blocks.resolve_drift(
                changed,
                {
                    "test-types":
                        "safe\n<!-- mnt:generated:end -->\n"
                },
                fixtures.generation_state(original),
                {"test-types": "replace"},
            )

    def test_legacy_section_body_moves_to_manual_block(self) -> None:
        legacy = (
            f"# Методика\r\n\r\n## {TEST_TYPES_HEADING}\r\n"
            "\r\n \tСуществующий текст  \r\n\r\nПоследняя строка\t\r\n"
        )
        expected = (
            f"# Методика\r\n\r\n## {TEST_TYPES_HEADING}\r\n"
            "<!-- mnt:generated:start id=test-types -->\r\n"
            "<!-- mnt:generated:end -->\r\n\r\n"
            "<!-- mnt:manual:start id=test-types -->\r\n"
            "\r\n \tСуществующий текст  \r\n\r\nПоследняя строка\t\r\n"
            "<!-- mnt:manual:end -->\r\n"
        )
        self.assertEqual(
            managed_blocks.migrate_legacy(legacy, [TEST_TYPES_HEADING]),
            expected,
        )

    def test_parse_sections_returns_canonical_bodies_in_document_order(self) -> None:
        markdown = (
            f"## {SCOPE_HEADING}\nScope body\n"
            f"## {TEST_TYPES_HEADING}\nTypes body\n"
        )
        sections = managed_blocks.parse_sections(markdown)
        self.assertEqual(list(sections), ["scope", "test-types"])
        self.assertEqual(sections["scope"], "Scope body\n")
        self.assertEqual(sections["test-types"], "Types body\n")

    def test_duplicate_canonical_heading_is_rejected(self) -> None:
        markdown = (
            f"## {TEST_TYPES_HEADING}\nfirst\n"
            f"## {TEST_TYPES_HEADING}\nsecond\n"
        )
        with self.assertRaisesRegex(ValueError, "duplicate canonical heading"):
            managed_blocks.parse_sections(markdown)

    def test_nested_markers_are_rejected(self) -> None:
        current = fixtures.document_with_blocks().replace(
            "исходный\n",
            "<!-- mnt:manual:start id=test-types -->\nnested\n",
        )
        with self.assertRaisesRegex(ValueError, "nested managed marker"):
            managed_blocks.merge_generated(
                current, {"test-types": "new\n"}, fixtures.generation_state(current)
            )

    def test_mismatched_marker_end_is_rejected(self) -> None:
        current = fixtures.document_with_blocks().replace(
            "<!-- mnt:generated:end -->", "<!-- mnt:manual:end -->", 1
        )
        with self.assertRaisesRegex(ValueError, "mismatched managed marker"):
            managed_blocks.merge_generated(
                current, {"test-types": "new\n"}, {"version": 1, "blocks": {}}
            )

    def test_marker_id_must_match_containing_canonical_heading(self) -> None:
        current = fixtures.document_with_blocks().replace(
            "id=test-types", "id=scope"
        )
        with self.assertRaisesRegex(ValueError, "marker id does not match canonical section"):
            managed_blocks.merge_generated(
                current, {"scope": "new\n"}, fixtures.generation_state(current)
            )

    def test_duplicate_generated_id_is_rejected(self) -> None:
        current = fixtures.document_with_blocks().replace(
            "<!-- mnt:manual:start id=test-types -->",
            "<!-- mnt:generated:start id=test-types -->\nextra\n"
            "<!-- mnt:generated:end -->\n"
            "<!-- mnt:manual:start id=test-types -->",
        )
        with self.assertRaisesRegex(ValueError, "duplicate generated marker"):
            managed_blocks.merge_generated(
                current, {"test-types": "new\n"}, fixtures.generation_state(current)
            )

    def test_duplicate_manual_id_is_rejected(self) -> None:
        current = fixtures.document_with_blocks().replace(
            "<!-- mnt:manual:end -->",
            "<!-- mnt:manual:end -->\n"
            "<!-- mnt:manual:start id=test-types -->\nextra\n"
            "<!-- mnt:manual:end -->",
        )
        with self.assertRaisesRegex(ValueError, "duplicate manual marker"):
            managed_blocks.merge_generated(
                current, {"test-types": "new\n"}, fixtures.generation_state(current)
            )

    def test_unterminated_marker_is_rejected(self) -> None:
        current = fixtures.document_with_blocks().replace(
            "<!-- mnt:manual:end -->\n", ""
        )
        with self.assertRaisesRegex(ValueError, "unterminated managed marker"):
            managed_blocks.merge_generated(
                current, {"test-types": "new\n"}, fixtures.generation_state(current)
            )

    def test_explicit_drift_actions_have_distinct_results(self) -> None:
        changed = fixtures.document_with_blocks(
            generated="ручная правка\n", manual="существующий manual\n"
        )
        state = fixtures.generation_state(
            fixtures.document_with_blocks(generated="исходный\n")
        )
        keep = managed_blocks.resolve_drift(
            changed, {"test-types": "новый\n"}, state,
            {"test-types": "keep"},
        )
        replace = managed_blocks.resolve_drift(
            changed, {"test-types": "новый\n"}, state,
            {"test-types": "replace"},
        )
        moved = managed_blocks.resolve_drift(
            changed, {"test-types": "новый\n"}, state,
            {"test-types": "move-to-manual"},
        )
        self.assertIn("ручная правка", keep.markdown)
        self.assertEqual(keep.warnings[0]["rule"], "user-kept-generated-block")
        self.assertEqual(
            keep.generation_state["blocks"]["test-types"],
            {
                "sha256": "df451a1ea6fe0eabfd10c0b3988b5c0ddfe2cc4441f03fbc64b4649fa2d96a80",
                "rendered_sha256": "ac7042e727f32e9e6d3f39319e96a4f2cd9bb03bea6444c189bd605f01507de9",
                "resolution": "keep",
            },
        )
        expected_rendered_state = {
            "sha256": "ac7042e727f32e9e6d3f39319e96a4f2cd9bb03bea6444c189bd605f01507de9",
            "rendered_sha256": "ac7042e727f32e9e6d3f39319e96a4f2cd9bb03bea6444c189bd605f01507de9",
            "resolution": "rendered",
        }
        self.assertEqual(
            replace.generation_state["blocks"]["test-types"],
            expected_rendered_state,
        )
        self.assertEqual(
            moved.generation_state["blocks"]["test-types"],
            expected_rendered_state,
        )
        self.assertNotIn("ручная правка", replace.markdown)
        self.assertIn("ручная правка", moved.markdown)
        self.assertIn("существующий manual\n\nручная правка\n", moved.markdown)
        self.assertIn("новый", moved.markdown)
        self.assertEqual(keep.conflicts, ())
        self.assertEqual(replace.conflicts, ())
        self.assertEqual(moved.conflicts, ())

    def test_drift_resolution_requires_all_and_only_conflicted_sections(self) -> None:
        first = fixtures.document_with_blocks(generated="original\n")
        second = fixtures.document_with_blocks(
            generated="scope original\n", section_id="scope"
        )
        original = first + second
        changed = original.replace("original", "edited")
        state = fixtures.generation_state(original)
        generated = {"test-types": "new\n", "scope": "scope new\n"}
        with self.assertRaisesRegex(ValueError, "missing drift decision: scope"):
            managed_blocks.resolve_drift(
                changed, generated, state, {"test-types": "keep"}
            )
        with self.assertRaisesRegex(ValueError, "unknown drift decision: risks"):
            managed_blocks.resolve_drift(
                changed,
                generated,
                state,
                {"test-types": "replace", "scope": "keep", "risks": "keep"},
            )

    def test_versioned_decision_artifact_is_validated(self) -> None:
        current = fixtures.document_with_blocks(generated="")
        with self.assertRaisesRegex(ValueError, "methodology-drift-decisions.schema.json"):
            managed_blocks.resolve_drift(
                current,
                {"test-types": "new\n"},
                {"version": 2, "blocks": {}},
                {"version": 2, "decisions": {}},
            )

    def test_keep_is_a_one_run_exception(self) -> None:
        original = fixtures.document_with_blocks(generated="original\n")
        changed = original.replace("original", "edited by user")
        kept = managed_blocks.resolve_drift(
            changed,
            {"test-types": "renderer one\n"},
            fixtures.generation_state(original),
            {"test-types": "keep"},
        )
        next_run = managed_blocks.merge_generated(
            kept.markdown,
            {"test-types": "renderer two\n"},
            kept.generation_state,
        )
        self.assertEqual(next_run.conflicts, ())
        self.assertNotIn("edited by user", next_run.markdown)
        self.assertIn("renderer two\n", next_run.markdown)

    def test_crlf_outside_generated_body_remains_byte_identical(self) -> None:
        current = fixtures.document_with_blocks(
            generated="old\n", manual="manual line\r\nsecond manual\r\n"
        ).replace("# Методика\n\n", "# Методика\r\n\r\n")
        old_body = "old\n"
        before, after = current.split(old_body, 1)
        result = managed_blocks.merge_generated(
            current,
            {"test-types": "new\n"},
            fixtures.generation_state(current),
        )
        self.assertEqual(result.markdown, before + "new\n" + after)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Behavior tests for deterministic methodology rendering."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

if __package__:
    from . import contracts, fixtures, renderer
    from .sections import CANONICAL_SECTIONS
else:
    import contracts
    import fixtures
    import renderer
    from sections import CANONICAL_SECTIONS


NO_DATA = "> Нет подтверждённых данных."


def _template_contract() -> dict[str, object]:
    path = (
        Path(__file__).resolve().parents[2]
        / ".gigacode"
        / "skills"
        / "manage-methodology"
        / "templates"
        / "methodology-template-contract.yaml"
    )
    return contracts.load_yaml_mapping(
        path, "methodology-template-contract.schema.json"
    )


def _markdown_table(body: str) -> tuple[list[str], list[list[str]]]:
    lines = [line for line in body.splitlines() if line.startswith("|")]
    if len(lines) < 2:
        raise AssertionError("expected a Markdown table")

    def cells(line: str) -> list[str]:
        return [value.strip() for value in line[1:-1].split(" | ")]

    return cells(lines[0]), [cells(line) for line in lines[2:]]


def _entity(
    entity_type: str,
    canonical_key: str,
    display_name: str,
    *,
    attributes: dict[str, object] | None = None,
    relative_path: str = "catalog/service.yaml",
) -> dict[str, object]:
    return {
        "entity_type": entity_type,
        "canonical_key": canonical_key,
        "display_name": display_name,
        "attributes": attributes or {},
        "sources": [{
            "repo_id": "catalog",
            "revision": "r1",
            "relative_path": relative_path,
            "pointer": "#entity",
            "selection_reason": "fixture",
            "sha256": "b" * 64,
        }],
    }


class RendererTest(unittest.TestCase):
    def test_renders_all_headings_and_approved_profile_values(self) -> None:
        result = renderer.render_candidate(
            fixtures.empty_methodology_template(),
            fixtures.methodology_input(),
            {"version": 1, "blocks": {}},
        )
        for heading in fixtures.canonical_headings():
            self.assertEqual(result.markdown.count(f"## {heading}"), 1)
        positions = [result.markdown.index(f"## {heading}") for heading in fixtures.canonical_headings()]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("20 минут", result.markdown)
        self.assertIn("2 часа", result.markdown)
        self.assertIn("8 часов", result.markdown)
        self.assertIn("80% подтверждённого максимума", result.markdown)
        self.assertIn("p95", result.markdown)
        self.assertIn("5%", result.markdown)
        self.assertEqual(result.conflicts, ())

    def test_same_input_produces_identical_bytes(self) -> None:
        first = renderer.render_candidate(
            fixtures.empty_methodology_template(),
            fixtures.methodology_input(),
            {"version": 1, "blocks": {}},
        )
        second = renderer.render_candidate(
            first.markdown,
            fixtures.methodology_input(),
            first.generation_state,
        )
        self.assertEqual(second.markdown.encode("utf-8"), first.markdown.encode("utf-8"))

    def test_registry_matches_all_canonical_ids_and_bodies_are_merge_safe(self) -> None:
        rendered = renderer.render_generated_sections(fixtures.methodology_input())
        self.assertEqual(tuple(rendered), tuple(section_id for section_id, _ in CANONICAL_SECTIONS))
        self.assertTrue(all(body.endswith("\n") for body in rendered.values()))
        self.assertTrue(all("mnt:generated:" not in body and "mnt:manual:" not in body for body in rendered.values()))

    def test_construct_comments_match_validated_contract_per_section(self) -> None:
        rendered = renderer.render_generated_sections(fixtures.methodology_input())
        contract = _template_contract()
        for section in contract["sections"]:
            section_id = section["id"]
            expected = section["required_literals"]
            actual = [
                line for line in rendered[section_id].splitlines()
                if line.startswith("<!-- mnt:construct:")
            ]
            self.assertEqual(actual, expected, section_id)

    def test_moved_construct_is_rejected_before_candidate_output(self) -> None:
        passport = renderer.RENDERERS["document-passport"]
        scope = renderer.RENDERERS["scope"]
        with patch.dict(renderer.RENDERERS, {
            "document-passport": lambda value: passport(value).replace(
                "<!-- mnt:construct:snapshot-id -->\n", "", 1
            ),
            "scope": lambda value: scope(value)
            + "<!-- mnt:construct:snapshot-id -->\n",
        }):
            with self.assertRaisesRegex(ValueError, "document-passport.*construct"):
                renderer.render_candidate(
                    fixtures.empty_methodology_template(),
                    fixtures.methodology_input(),
                    {"version": 1, "blocks": {}},
                )

    def test_undeclared_construct_is_rejected_before_generated_output(self) -> None:
        scope = renderer.RENDERERS["scope"]
        with patch.dict(renderer.RENDERERS, {
            "scope": lambda value: scope(value)
            + "<!-- mnt:construct:spoofed -->\n",
        }):
            with self.assertRaisesRegex(ValueError, "scope.*construct"):
                renderer.render_generated_sections(fixtures.methodology_input())

    def test_duplicate_construct_is_rejected_before_generated_output(self) -> None:
        scope = renderer.RENDERERS["scope"]
        with patch.dict(renderer.RENDERERS, {
            "scope": lambda value: scope(value)
            + "<!-- mnt:construct:confirmed-surface -->\n",
        }):
            with self.assertRaisesRegex(ValueError, "scope.*construct"):
                renderer.render_generated_sections(fixtures.methodology_input())

    def test_test_types_keeps_the_approved_profile_wording_contiguous(self) -> None:
        expected = (
            "1. **Ступенчатый поиск максимума.** Длительность ступени — 20 минут. "
            "Максимумом считается последняя полностью пройденная ступень.\n"
            "2. **Подтверждение максимума.** Нагрузка на найденном максимуме "
            "удерживается 2 часа.\n"
            "3. **Стабильность.** Нагрузка 80% подтверждённого максимума "
            "удерживается 8 часов.\n"
        )
        body = renderer.render_test_types(fixtures.methodology_input())
        self.assertTrue(body.endswith(expected))

    def test_permanent_template_is_directly_compatible_with_all_rendered_blocks(self) -> None:
        result = renderer.render_candidate(
            fixtures.empty_methodology_template(),
            fixtures.methodology_input(),
            {"version": 1, "blocks": {}},
        )
        self.assertEqual(result.conflicts, ())
        for section_id, _ in CANONICAL_SECTIONS:
            self.assertEqual(result.markdown.count(f"<!-- mnt:generated:start id={section_id} -->"), 1)
            self.assertEqual(result.markdown.count(f"<!-- mnt:manual:start id={section_id} -->"), 1)

    def test_empty_surface_sections_use_the_exact_no_data_marker(self) -> None:
        value = fixtures.methodology_input()
        value["surface"]["included"] = []
        value["surface"]["added"] = []
        rendered = renderer.render_generated_sections(value)
        for section_id in ("system-description", "architecture", "interfaces", "flows", "risks"):
            self.assertEqual(rendered[section_id], NO_DATA + "\n")
        self.assertIn("Не применимо: No external interfaces", rendered["integrations"])

    def test_surface_tables_keep_partial_rows_and_sort_by_type_then_key(self) -> None:
        value = fixtures.methodology_input()
        value["surface"]["included"] = [
            _entity("service", "zeta", "Zeta"),
            _entity("component", "beta", "Beta", attributes={"responsibility": "worker"}),
        ]
        value["surface"]["added"] = [
            _entity("component", "alpha", "Alpha", attributes={"relationship": "calls Beta"}),
        ]
        rendered = renderer.render_generated_sections(value)
        self.assertLess(rendered["scope"].index("Alpha"), rendered["scope"].index("Beta"))
        self.assertLess(rendered["scope"].index("Beta"), rendered["scope"].index("Zeta"))
        self.assertIn("| Beta | worker |", rendered["system-description"])
        self.assertIn("| Alpha | calls Beta |", rendered["architecture"])

    def test_user_text_is_escaped_in_prose_and_table_cells(self) -> None:
        value = fixtures.methodology_input()
        value["load"]["operation_mix"] = (
            "safe &copy; <tag>\n"
            "| injected |\n|---|\n---\n- list\n1. ordered\n"
            "# heading\n> quote\n```python\n"
            "*em* _em_ ~~strike~~ `code` [link](target) ![image](target)\n"
            "https://example.invalid user@example.invalid\r\n"
            "===\r+ plus\r    indented code"
        )
        value["surface"]["included"] = [
            _entity(
                "component", "escape", "A|B\n# row & <x>",
                attributes={"responsibility": "<!-- mnt:generated:end -->"},
            )
        ]
        value["surface"]["included"][0]["sources"][0]["repo_id"] = "repo&<x>"
        rendered = renderer.render_generated_sections(value)
        self.assertIn("safe &amp;copy; &lt;tag\\>", rendered["workload"])
        self.assertIn("\\| injected \\|", rendered["workload"])
        self.assertIn("\\|---\\|", rendered["workload"])
        self.assertIn("\\-\\-\\-", rendered["workload"])
        self.assertIn("\\- list", rendered["workload"])
        self.assertIn("1\\. ordered", rendered["workload"])
        self.assertIn("\\# heading", rendered["workload"])
        self.assertIn("\\> quote", rendered["workload"])
        self.assertIn("\\`\\`\\`python", rendered["workload"])
        self.assertIn(
            "\\*em\\* \\_em\\_ \\~\\~strike\\~\\~ \\`code\\` "
            "\\[link\\]\\(target\\) \\!\\[image\\]\\(target\\)",
            rendered["workload"],
        )
        self.assertIn(
            "https\\://example\\.invalid user\\@example\\.invalid",
            rendered["workload"],
        )
        self.assertIn("\\=\\=\\=", rendered["workload"])
        self.assertIn("\\+ plus", rendered["workload"])
        self.assertIn("&#32;   indented code", rendered["workload"])
        self.assertNotIn("\r", rendered["workload"])
        self.assertIn("A\\|B<br>\\# row &amp; &lt;x\\>", rendered["system-description"])
        self.assertIn("&lt;\\!-- mnt\\:generated\\:end --\\>", rendered["system-description"])
        self.assertNotIn("<!-- mnt:generated:end -->", rendered["system-description"])
        self.assertIn("repo&amp;&lt;x\\>@r1", rendered["system-description"])
        self.assertNotIn("repo&amp;amp;", rendered["system-description"])

    def test_only_safe_normalized_relative_source_paths_become_links(self) -> None:
        value = fixtures.methodology_input()
        paths = (
            "catalog/safe.yaml", "../secret", "/etc/passwd", "C:\\secret",
            "catalog/../secret", "https://example.invalid/x", "%2e%2e/secret",
        )
        value["surface"]["included"] = [
            _entity("service", f"s{index}", f"S{index}", relative_path=path)
            for index, path in enumerate(paths)
        ]
        body = renderer.render_generated_sections(value)["system-description"]
        self.assertIn("[catalog/safe.yaml](catalog/safe.yaml)", body)
        for unsafe in paths[1:]:
            self.assertNotIn(unsafe, body)

    def test_sla_has_exact_defaults_sources_and_monitoring_semantics(self) -> None:
        value = fixtures.methodology_input()
        value["profile"]["sources"] = {
            "criteria.response_time.percentile": {"source": "default-v1"},
            "criteria.response_time.threshold_ms": {"source": "meta-manual", "source_reference": "META-42"},
            "criteria.technical_errors.max_percent": {"source": "default-v1"},
            "criteria.cpu.max_percent": {"source": "user"},
            "criteria.memory.max_percent": {"source": "default-v1"},
        }
        value["observability"] = {
            "cpu_signal": "cpu_usage",
            "memory_signal": "rss_bytes",
            "memory_growth_window": 45,
            "dashboard": "grafana",
        }
        body = renderer.render_generated_sections(value)["sla-slo"]
        self.assertIn("p95 ≤ 1000 мс", body)
        self.assertIn("≤ 5%", body)
        self.assertIn("≤ 40%", body)
        self.assertIn("≤ 80%", body)
        self.assertIn("default-v1", body)
        self.assertIn("meta-manual \\(META-42\\)", body)
        self.assertIn("cpu\\_usage", body)
        self.assertIn("rss\\_bytes", body)
        self.assertIn("45 минут", body)

    def test_risks_table_uses_the_contract_column_shape(self) -> None:
        value = fixtures.methodology_input()
        value["surface"]["included"] = [
            _entity("risk", "capacity", "Недостаточная ёмкость", attributes={"mitigation": "масштабировать"})
        ]
        body = renderer.render_generated_sections(value)["risks"]
        self.assertIn("| Риск | Мера |\n|---|---|", body)
        self.assertNotIn("| Риск | Мера | Источники |", body)

    def test_every_contract_table_has_exact_headers_and_column_counts(self) -> None:
        value = fixtures.methodology_input()
        value["surface"]["included"] = [
            _entity("component", "component", "Component", attributes={"responsibility": "worker", "relationship": "calls API"}),
            _entity("integration", "integration", "Integration", attributes={"protocol": "kafka"}),
            _entity("interface", "interface", "Interface", attributes={"operation": "create"}),
            _entity("technical-flow", "flow", "Flow", attributes={"steps": ["one", "two"]}),
            _entity("risk", "risk", "Risk", attributes={"mitigation": "scale"}),
        ]
        value["surface"]["added"] = []
        rendered = renderer.render_generated_sections(value)
        contract = _template_contract()
        for section in contract["sections"]:
            expected = section.get("table_columns")
            if expected is None:
                continue
            header, rows = _markdown_table(rendered[section["id"]])
            self.assertEqual(header, expected, section["id"])
            self.assertGreaterEqual(len(rows), section["minimum_data_rows"])
            self.assertTrue(
                all(len(row) == len(expected) for row in rows), section["id"]
            )

    def test_sla_table_has_exact_approved_shape(self) -> None:
        body = renderer.render_generated_sections(fixtures.methodology_input())["sla-slo"]
        header, rows = _markdown_table(body)
        self.assertEqual(
            header,
            ["ID", "Метрика", "Критерий", "Область действия", "Нормативный источник"],
        )
        self.assertEqual([row[0] for row in rows], ["RT", "ERR", "CPU", "MEM"])
        self.assertTrue(all(len(row) == 5 for row in rows))

    def test_drift_conflicts_and_explicit_keep_warning_are_propagated(self) -> None:
        first = renderer.render_candidate(
            fixtures.empty_methodology_template(), fixtures.methodology_input(),
            {"version": 1, "blocks": {}},
        )
        changed = first.markdown.replace("Профиль: default-v1", "Профиль: ручная правка", 1)
        conflicted = renderer.render_candidate(
            changed, fixtures.methodology_input(), first.generation_state,
        )
        self.assertEqual(conflicted.conflicts[0]["rule"], "managed-block-drift")
        self.assertEqual(conflicted.markdown, changed)
        kept = renderer.render_candidate(
            changed, fixtures.methodology_input(), first.generation_state,
            {"document-passport": "keep"},
        )
        self.assertEqual(kept.conflicts, ())
        self.assertEqual(kept.warnings[0]["rule"], "user-kept-generated-block")
        self.assertIn("Профиль: ручная правка", kept.markdown)

    def test_draft_scalar_sections_render_no_data_without_guessing(self) -> None:
        value = fixtures.methodology_input()
        value["load"] = {}
        value["environment"] = {}
        value["observability"] = {}
        value["test_data"] = {}
        rendered = renderer.render_generated_sections(value)
        self.assertEqual(rendered["workload"], NO_DATA + "\n")
        self.assertEqual(rendered["environment"], NO_DATA + "\n")
        self.assertEqual(rendered["observability"], NO_DATA + "\n")
        self.assertEqual(rendered["test-data"], NO_DATA + "\n")


if __name__ == "__main__":
    unittest.main()

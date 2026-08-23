#!/usr/bin/env python3
"""Behavior tests for deterministic methodology rendering."""

from __future__ import annotations

from copy import deepcopy
import unittest

if __package__:
    from . import fixtures, managed_blocks, renderer
    from .sections import CANONICAL_SECTIONS
else:
    import fixtures
    import managed_blocks
    import renderer
    from sections import CANONICAL_SECTIONS


NO_DATA = "> Нет подтверждённых данных."
CONSTRUCTS = (
    "snapshot-id", "profile-id", "profile-version", "confirmed-surface",
    "included-entity", "test-step-search", "test-maximum-confirmation",
    "test-stability", "response-time-criterion",
    "technical-errors-criterion", "cpu-criterion", "memory-criterion",
    "criterion-sources", "stage-step-search",
    "stage-maximum-confirmation", "stage-stability",
    "readiness-artifact", "template-artifact", "gatling-artifact",
    "monitoring-artifact", "test-result-artifact", "profile-id-version",
    "regeneration-rule",
)


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

    def test_all_contract_construct_comments_are_emitted_once(self) -> None:
        rendered = renderer.render_generated_sections(fixtures.methodology_input())
        document = "".join(rendered.values())
        for construct in CONSTRUCTS:
            self.assertEqual(document.count(f"<!-- mnt:construct:{construct} -->"), 1)

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
        template = fixtures.empty_methodology_template()
        result = managed_blocks.merge_generated(
            template,
            renderer.render_generated_sections(fixtures.methodology_input()),
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
        value["load"]["operation_mix"] = "safe & <tag>\n# heading\n> quote\n```python"
        value["surface"]["included"] = [
            _entity(
                "component", "escape", "A|B\n# row & <x>",
                attributes={"responsibility": "<!-- mnt:generated:end -->"},
            )
        ]
        value["surface"]["included"][0]["sources"][0]["repo_id"] = "repo&<x>"
        rendered = renderer.render_generated_sections(value)
        self.assertIn("safe &amp; &lt;tag>", rendered["workload"])
        self.assertIn("\\# heading", rendered["workload"])
        self.assertIn("\\> quote", rendered["workload"])
        self.assertIn("\\```python", rendered["workload"])
        self.assertIn("A\\|B<br>\\# row &amp; &lt;x>", rendered["system-description"])
        self.assertIn("&lt;!-- mnt:generated:end -->", rendered["system-description"])
        self.assertNotIn("<!-- mnt:generated:end -->", rendered["system-description"])
        self.assertIn("repo&amp;&lt;x>@r1", rendered["system-description"])
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
        self.assertIn("meta-manual (META-42)", body)
        self.assertIn("cpu_usage", body)
        self.assertIn("rss_bytes", body)
        self.assertIn("45 минут", body)

    def test_risks_table_uses_the_contract_column_shape(self) -> None:
        value = fixtures.methodology_input()
        value["surface"]["included"] = [
            _entity("risk", "capacity", "Недостаточная ёмкость", attributes={"mitigation": "масштабировать"})
        ]
        body = renderer.render_generated_sections(value)["risks"]
        self.assertIn("| Риск | Мера |\n|---|---|", body)
        self.assertNotIn("| Риск | Мера | Источники |", body)

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

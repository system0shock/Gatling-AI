#!/usr/bin/env python3
"""Unit tests for the scenario Markdown renderer."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import scenario_renderer

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_SCENARIO = REPO_ROOT / "examples" / "scenarios" / "login-and-search.yaml"


class RendererTest(unittest.TestCase):
    def render(self) -> str:
        document = scenario_renderer.load_yaml(GOLDEN_SCENARIO)
        return scenario_renderer.render_markdown(
            document,
            "examples/scenarios/login-and-search.yaml",
            scenario_renderer.source_digest(GOLDEN_SCENARIO),
        )

    def test_header_marks_generated_artifact(self) -> None:
        content = self.render()
        self.assertIn("login-and-search.yaml", content.splitlines()[2])
        self.assertIn("Не редактировать вручную", content)

    def test_steps_table_lists_transactions(self) -> None:
        content = self.render()
        self.assertIn("01 auth.open-login - Open login page", content)
        self.assertIn("| POST | /login |", content)

    def test_correlations_table_tracks_csrf(self) -> None:
        content = self.render()
        self.assertIn("csrf", content)
        self.assertIn("извлекается в шаге `open-login`", content)

    def test_sla_section_lists_assertions(self) -> None:
        content = self.render()
        self.assertIn("global.responseTime.p95", content)
        self.assertIn("< 800", content)

    def test_render_is_deterministic(self) -> None:
        self.assertEqual(self.render(), self.render())


class PauseColumnTest(unittest.TestCase):
    def test_steps_table_has_pause_column(self) -> None:
        document = scenario_renderer.load_yaml(GOLDEN_SCENARIO)
        content = scenario_renderer.render_markdown(
            document,
            "examples/scenarios/login-and-search.yaml",
            scenario_renderer.source_digest(GOLDEN_SCENARIO),
        )
        self.assertIn("| # | Транзакция | Метод | Путь | Пауза | Проверки |", content)

    def test_integral_float_pause_renders_without_decimal(self) -> None:
        self.assertEqual(
            scenario_renderer.pause_summary({"pause_seconds": 1.0}), "1 с"
        )


class LoadDescriptionTest(unittest.TestCase):
    def test_stress_description(self) -> None:
        text = scenario_renderer.load_description(
            {"model": "closed", "profile": "stress", "users": 10, "levels": 5,
             "level_duration_seconds": 60}
        )
        self.assertIn("Ступенчатый рост", text)
        self.assertIn("5 уровней по 60 с", text)
        self.assertIn("до 10", text)

    def test_open_constant_description(self) -> None:
        text = scenario_renderer.load_description(
            {"model": "open", "profile": "constant", "users_per_second": 2.5,
             "duration_seconds": 120}
        )
        self.assertIn("2.5 запросов/с", text)
        self.assertIn("120 с", text)


class GraphqlRenderTest(unittest.TestCase):
    def test_graphql_step_renders_row_and_query_block(self) -> None:
        document = {
            "scenario": {
                "id": "demo",
                "title": "Demo",
                "source": {"type": "manual", "ref": "t"},
                "sut": {"base_url": "${BASE_URL}"},
                "steps": [
                    {
                        "name": "gql-search",
                        "title": "GraphQL search",
                        "transaction": "01 search.gql - GraphQL search",
                        "protocol": "graphql",
                        "graphql": {"query": "query{ x }", "variables": {}},
                        "checks": [{"status": 200}],
                    }
                ],
                "load": {"model": "closed", "profile": "constant", "users": 1,
                         "duration_seconds": 60},
                "assertions": [
                    {"name": "a", "metric": "global.responseTime.p95", "op": "<", "value": 1}
                ],
            }
        }
        content = scenario_renderer.render_markdown(document, "demo.yaml", "abc")
        self.assertIn("| POST | /graphql |", content)
        self.assertIn("### GraphQL-запросы", content)
        self.assertIn("query{ x }", content)


class PopulationsRenderTest(unittest.TestCase):
    def test_population_sections(self) -> None:
        document = {
            "scenario": {
                "id": "demo",
                "title": "Demo",
                "source": {"type": "manual", "ref": "t"},
                "sut": {"base_url": "${BASE_URL}"},
                "populations": [
                    {
                        "name": "main-flow",
                        "steps": [
                            {
                                "name": "open",
                                "title": "Open",
                                "transaction": "01 demo.open - Open",
                                "protocol": "http",
                                "request": {"method": "GET", "path": "/"},
                                "checks": [{"status": 200}],
                            }
                        ],
                        "load": {"model": "closed", "profile": "constant", "users": 1,
                                 "duration_seconds": 60},
                    },
                    {
                        "name": "background",
                        "steps": [
                            {
                                "name": "bg-open",
                                "title": "Bg open",
                                "transaction": "01 bg.open - Bg open",
                                "protocol": "http",
                                "request": {"method": "GET", "path": "/bg"},
                                "checks": [{"status": 200}],
                            }
                        ],
                        "load": {"model": "open", "profile": "constant",
                                 "users_per_second": 1, "duration_seconds": 60},
                    },
                ],
                "assertions": [
                    {"name": "a", "metric": "global.responseTime.p95", "op": "<", "value": 1}
                ],
            }
        }
        content = scenario_renderer.render_markdown(document, "demo.yaml", "abc")
        self.assertIn("## Популяция: `main-flow`", content)
        self.assertIn("## Популяция: `background`", content)
        self.assertIn("### Шаги", content)
        self.assertIn("### Профиль нагрузки", content)
        self.assertIn("01 bg.open - Bg open", content)

    def test_single_flow_keeps_flat_headings(self) -> None:
        document = scenario_renderer.load_yaml(GOLDEN_SCENARIO)
        content = scenario_renderer.render_markdown(
            document, "x.yaml", scenario_renderer.source_digest(GOLDEN_SCENARIO)
        )
        self.assertIn("\n## Шаги\n", content)
        self.assertNotIn("## Популяция:", content)


if __name__ == "__main__":
    sys.exit(unittest.main())

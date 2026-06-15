#!/usr/bin/env python3
"""Unit tests for the scenario Markdown renderer."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import scenario_renderer

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_SCENARIO = (
    REPO_ROOT / "examples" / "scenarios" / "SHOP" / "login-and-search-002" / "scenario.yaml"
)


def make_document(**overrides):
    """Build a minimal schema-valid single-flow scenario document.

    ``overrides`` are applied via ``scenario.update()``, so they replace
    top-level scenario fields (e.g. ``load``, ``steps``, ``populations``).
    When passing ``populations``, delete ``steps`` and ``load`` afterward —
    they are not valid alongside ``populations`` per the schema oneOf.
    """
    scenario = {
        "id": "demo-flow",
        "system": "DEMO",
        "number": 7,
        "title": "Demo flow",
        "source": {"type": "manual", "ref": "test"},
        "sut": {"base_url": "${BASE_URL}"},
        "steps": [
            {
                "name": "open-home",
                "title": "Open home",
                "transaction": "01 demo.open-home - Open home",
                "protocol": "http",
                "request": {"method": "GET", "path": "/"},
                "checks": [{"status": 200}],
            }
        ],
        "load": {
            "model": "closed",
            "profile": "ramp",
            "users": 5,
            "ramp_seconds": 10,
            "duration_seconds": 60,
        },
        "assertions": [
            {"name": "p95", "metric": "global.responseTime.p95", "op": "<", "value": 800}
        ],
    }
    scenario.update(overrides)
    return {"scenario": scenario}


class RendererTest(unittest.TestCase):
    def render(self) -> str:
        document = scenario_renderer.load_yaml(GOLDEN_SCENARIO)
        return scenario_renderer.render_markdown(
            document,
            "examples/scenarios/SHOP/login-and-search-002/scenario.yaml",
            scenario_renderer.source_digest(GOLDEN_SCENARIO),
        )

    def test_header_marks_generated_artifact(self) -> None:
        content = self.render()
        self.assertIn(
            "examples/scenarios/SHOP/login-and-search-002/scenario.yaml",
            content.splitlines()[2],
        )
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
            "examples/scenarios/SHOP/login-and-search-002/scenario.yaml",
            scenario_renderer.source_digest(GOLDEN_SCENARIO),
        )
        self.assertIn("| # | Транзакция | Метод | Путь | Пауза | Проверки | Теги |", content)

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


class ScriptRefLineTest(unittest.TestCase):
    def test_passport_shows_script_ref(self) -> None:
        document = {
            "scenario": {
                "id": "demo",
                "title": "Demo",
                "system": "SHOP",
                "number": 1,
                "source": {"type": "manual", "ref": "t"},
                "sut": {"base_url": "${BASE_URL}"},
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
                "assertions": [
                    {"name": "a", "metric": "global.responseTime.p95", "op": "<", "value": 1}
                ],
            }
        }
        content = scenario_renderer.render_markdown(document, "demo.yaml", "abc")
        self.assertIn("- **Скрипт:** `SHOP_Demo_001`", content)

    def test_missing_fields_render_question_mark(self) -> None:
        document = scenario_renderer.load_yaml(GOLDEN_SCENARIO)
        document["scenario"].pop("system", None)
        content = scenario_renderer.render_markdown(document, "x.yaml", "abc")
        self.assertIn("- **Скрипт:** `?`", content)


class DefaultOutputTest(unittest.TestCase):
    def test_default_writes_passport_next_to_scenario(self) -> None:
        import shutil
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            scenario = Path(tmp) / "scenario.yaml"
            shutil.copyfile(GOLDEN_SCENARIO, scenario)
            code = scenario_renderer.main([str(scenario)])
            self.assertEqual(code, 0)
            self.assertTrue((Path(tmp) / "passport.md").is_file())

    def test_stdout_flag_prints_instead_of_writing(self) -> None:
        import io
        import shutil
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            scenario = Path(tmp) / "scenario.yaml"
            shutil.copyfile(GOLDEN_SCENARIO, scenario)
            stdout = io.StringIO()
            with patch.object(sys, "stdout", stdout):
                code = scenario_renderer.main([str(scenario), "--stdout"])
            self.assertEqual(code, 0)
            self.assertIn("## Паспорт", stdout.getvalue())
            self.assertFalse((Path(tmp) / "passport.md").exists())


class TagsRenderTest(unittest.TestCase):
    def test_tags_column_rendered(self) -> None:
        document = make_document()
        document["scenario"]["steps"][0]["tags"] = ["kafka-via-proxy", "legacy"]
        content = scenario_renderer.render_markdown(document, "s.yaml", "0" * 12)
        self.assertIn("| Теги |", content)
        self.assertIn("kafka-via-proxy, legacy", content)

    def test_no_tags_renders_dash(self) -> None:
        document = make_document()
        content = scenario_renderer.render_markdown(document, "s.yaml", "0" * 12)
        # Anchor on the checks->tags cell boundary so an empty pause cell can't
        # satisfy this instead of the tags column.
        self.assertIn("| status 200 | — |", content)


class BodyFileRenderTest(unittest.TestCase):
    def test_body_files_section_lists_step_and_file(self) -> None:
        document = make_document()
        document["scenario"]["steps"][0]["request"]["body_file"] = "bodies/checkout.json"
        document["scenario"]["steps"][0]["request"].pop("body", None)
        content = scenario_renderer.render_markdown(document, "s.yaml", "0" * 12)
        self.assertIn("### Тела запросов", content)
        self.assertIn("`bodies/checkout.json`", content)


class StartAfterRenderTest(unittest.TestCase):
    def test_start_after_mentioned(self) -> None:
        base = make_document()["scenario"]
        document = make_document(
            populations=[
                {"name": "main-flow", "steps": base["steps"], "load": base["load"]},
                {
                    "name": "late-flow",
                    "steps": [
                        {
                            "name": "late-step",
                            "title": "Late",
                            "transaction": "02 demo.late - Late",
                            "protocol": "http",
                            "request": {"method": "GET", "path": "/late"},
                            "checks": [{"status": 200}],
                        }
                    ],
                    "load": base["load"],
                    "start_after_seconds": 1200,
                },
            ]
        )
        del document["scenario"]["steps"]
        del document["scenario"]["load"]
        content = scenario_renderer.render_markdown(document, "s.yaml", "0" * 12)
        self.assertIn("через **1200 с** после начала теста", content)


class HooksRenderTest(unittest.TestCase):
    def test_hooks_table_rendered(self) -> None:
        document = make_document()
        document["scenario"]["steps"][0]["hooks"] = {
            "after": [
                {
                    "ref": "migration/jsr223/audit.groovy",
                    "kind": "todo",
                    "summary": "writes audit row",
                    "writes": ["auditId"],
                }
            ]
        }
        content = scenario_renderer.render_markdown(document, "s.yaml", "0" * 12)
        self.assertIn("### JSR223-хуки", content)
        self.assertIn("| after | todo |", content)
        self.assertIn("writes audit row", content)


class StagesRenderTest(unittest.TestCase):
    def test_stages_description_lists_steps(self) -> None:
        document = make_document()
        document["scenario"]["load"] = {
            "model": "closed",
            "profile": "stages",
            "stages": [
                {"users": 10, "ramp_seconds": 60, "hold_seconds": 300},
                {"users": 20, "ramp_seconds": 0, "hold_seconds": 120},
            ],
        }
        content = scenario_renderer.render_markdown(document, "s.yaml", "0" * 12)
        self.assertIn("Ступени:", content)
        self.assertIn("разгон до 10 пользователей за 60 с", content)
        self.assertIn("скачок до 20 пользователей", content)


if __name__ == "__main__":
    sys.exit(unittest.main())

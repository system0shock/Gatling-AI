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
        # writes column lists the produced variable; reads is empty -> dash
        self.assertIn("| auditId |", content)
        self.assertIn("| — | auditId |", content)


class HintsRenderTest(unittest.TestCase):
    def test_hints_line_rendered(self) -> None:
        document = make_document()
        document["scenario"]["steps"][0]["hooks"] = {
            "after": [
                {
                    "ref": "migration/jsr223/audit.groovy",
                    "kind": "todo",
                    "summary": "writes audit row",
                    "writes": ["auditId"],
                    "hints": [
                        {"kind": "var_put", "var": "auditId", "expr": "uuid"},
                        {"kind": "log_call", "level": "info"},
                    ],
                }
            ]
        }
        content = scenario_renderer.render_markdown(document, "s.yaml", "0" * 12)
        self.assertIn("Намерения:", content)
        self.assertIn("var_put", content)
        self.assertIn("var=auditId", content)

    def test_no_hints_no_namerения_line(self) -> None:
        document = make_document()
        document["scenario"]["steps"][0]["hooks"] = {
            "after": [
                {
                    "ref": "migration/jsr223/audit.groovy",
                    "kind": "todo",
                    "summary": "writes audit row",
                }
            ]
        }
        content = scenario_renderer.render_markdown(document, "s.yaml", "0" * 12)
        self.assertNotIn("Намерения:", content)


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


class ProtocolStubRenderTest(unittest.TestCase):
    def test_kafka_and_jdbc_rows(self) -> None:
        document = make_document()
        document["scenario"]["steps"].append(
            {
                "name": "publish-event",
                "title": "Publish event",
                "transaction": "02 orders.publish - Publish order event",
                "protocol": "kafka",
                "kafka": {"topic": "orders", "payload": "{}"},
            }
        )
        content = scenario_renderer.render_markdown(document, "s.yaml", "0" * 12)
        self.assertIn("| KAFKA |", content)
        self.assertIn("topic `orders`", content)

    def test_jdbc_row_and_query_truncation(self) -> None:
        document = make_document()
        long_query = "SELECT " + ("col, " * 40) + "1 FROM big_table WHERE id = 7"
        document["scenario"]["steps"].append(
            {
                "name": "read-row",
                "title": "Read row",
                "transaction": "02 orders.read-row - Read a row",
                "protocol": "jdbc",
                "jdbc": {"query": long_query, "saveAs": "row"},
            }
        )
        content = scenario_renderer.render_markdown(document, "s.yaml", "0" * 12)
        self.assertIn("| JDBC |", content)
        self.assertIn("…", content)  # query truncated for the table

    def test_kafka_request_reply_row(self) -> None:
        document = make_document()
        document["scenario"]["steps"].append(
            {
                "name": "process-event",
                "title": "Process event",
                "transaction": "03 orders.process - Process order event",
                "protocol": "kafka",
                "kafka": {
                    "topic": "requests",
                    "reply_topic": "replies",
                    "request_reply": True,
                    "checks": [{"jsonPath": "$.status", "is": "ok"}],
                },
            }
        )
        content = scenario_renderer.render_markdown(document, "s.yaml", "0" * 12)
        self.assertIn("KAFKA RR", content)
        self.assertIn("reply `replies`", content)
        self.assertIn("kafka reply `$.status` = ok", content)

    def test_jdbc_insert_row(self) -> None:
        document = make_document()
        document["scenario"]["steps"].append(
            {
                "name": "insert-user",
                "title": "Insert user",
                "transaction": "04 users.insert - Insert a user",
                "protocol": "jdbc",
                "jdbc": {
                    "action": "insert",
                    "table": "users",
                    "columns": ["id", "name"],
                    "values": {"id": 1, "name": "${userName}"},
                },
            }
        )
        content = scenario_renderer.render_markdown(document, "s.yaml", "0" * 12)
        self.assertIn("JDBC INSERT", content)
        self.assertIn("`users`", content)
        self.assertIn("id, name", content)

    def test_jdbc_update_row(self) -> None:
        document = make_document()
        document["scenario"]["steps"].append(
            {
                "name": "update-status",
                "title": "Update status",
                "transaction": "05 orders.update - Update order status",
                "protocol": "jdbc",
                "jdbc": {
                    "action": "update",
                    "table": "orders",
                    "set": {"status": "completed"},
                    "where": "id = ${orderId}",
                },
            }
        )
        content = scenario_renderer.render_markdown(document, "s.yaml", "0" * 12)
        self.assertIn("JDBC UPDATE", content)
        self.assertIn("`orders`", content)
        self.assertIn("id = ${orderId}", content)

    def test_jdbc_raw_sql_row(self) -> None:
        document = make_document()
        document["scenario"]["steps"].append(
            {
                "name": "cleanup",
                "title": "Cleanup",
                "transaction": "06 sessions.cleanup - Cleanup sessions",
                "protocol": "jdbc",
                "jdbc": {"action": "raw_sql", "sql": "DELETE FROM sessions WHERE expired = true"},
            }
        )
        content = scenario_renderer.render_markdown(document, "s.yaml", "0" * 12)
        self.assertIn("JDBC SQL", content)
        self.assertIn("DELETE FROM sessions", content)

    def test_jdbc_call_row(self) -> None:
        document = make_document()
        document["scenario"]["steps"].append(
            {
                "name": "calc-balance",
                "title": "Calculate balance",
                "transaction": "07 billing.calc - Calculate balance",
                "protocol": "jdbc",
                "jdbc": {
                    "action": "call",
                    "procedure": "calculate_balance",
                    "params": {"accountId": "${accId}"},
                    "out_params": {"result": "DECIMAL"},
                    "saveAs": "balance",
                },
            }
        )
        content = scenario_renderer.render_markdown(document, "s.yaml", "0" * 12)
        self.assertIn("JDBC CALL", content)
        self.assertIn("`calculate_balance`", content)


class FeederOptionsRenderTest(unittest.TestCase):
    def test_feeder_non_default_options_columns(self) -> None:
        document = make_document(
            data={"feeders": [
                {"name": "users", "file": "users.csv", "strategy": "circular",
                 "delimiter": ";", "ignore_first_line": True},
            ]},
        )
        content = scenario_renderer.render_markdown(document, "s.yaml", "0" * 12)
        self.assertIn("Разделитель", content)
        self.assertIn("Без заголовка", content)
        self.assertIn(";", content)
        self.assertIn("да", content)

    def test_feeder_default_options_no_extra_columns(self) -> None:
        document = make_document(
            data={"feeders": [
                {"name": "users", "file": "users.csv", "strategy": "circular"},
            ]},
        )
        content = scenario_renderer.render_markdown(document, "s.yaml", "0" * 12)
        self.assertNotIn("Разделитель", content)
        self.assertNotIn("Без заголовка", content)


if __name__ == "__main__":
    sys.exit(unittest.main())

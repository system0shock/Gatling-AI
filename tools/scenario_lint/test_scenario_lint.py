#!/usr/bin/env python3
"""Unit tests for scenario lint."""

from __future__ import annotations

import json
import sys
import unittest
from datetime import date
from pathlib import Path

import scenario_lint

REPO_ROOT = Path(__file__).resolve().parents[2]


class SchemaContractTest(unittest.TestCase):
    def test_schema_requires_checks_per_step(self) -> None:
        schema = json.loads(
            (REPO_ROOT / "schemas" / "scenario.schema.json").read_text(encoding="utf-8")
        )
        # scenario is now oneOf; steps live in $defs
        step_schema = schema["$defs"]["steps"]["items"]
        for variant in step_schema["oneOf"]:
            self.assertIn("checks", variant["required"])

    def test_schema_requires_system_and_number(self) -> None:
        schema = json.loads(
            (REPO_ROOT / "schemas" / "scenario.schema.json").read_text(encoding="utf-8")
        )
        for variant in schema["properties"]["scenario"]["oneOf"]:
            self.assertIn("system", variant["required"])
            self.assertIn("number", variant["required"])
            self.assertEqual(
                variant["properties"]["system"]["pattern"], "^[A-Z][A-Z0-9]{1,9}$"
            )
            self.assertEqual(variant["properties"]["number"]["minimum"], 1)


class DeadCodeRemovedTest(unittest.TestCase):
    def test_columns_helper_is_gone(self) -> None:
        self.assertFalse(hasattr(scenario_lint, "feeder_columns_from_config"))


def waived_document():
    return {
        "scenario": {
            "id": "demo",
            "title": "Demo",
            "source": {"type": "manual", "ref": "t"},
            "sut": {"base_url": "${BASE_URL}"},
            "steps": [
                {
                    "name": "post-thing",
                    "title": "Post thing",
                    "transaction": "01 demo.post-thing - Post thing",
                    "protocol": "http",
                    "request": {"method": "POST", "path": "/thing"},
                    "checks": [{"extract": {"type": "css", "expr": "a", "saveAs": "x"}}],
                }
            ],
            "load": {
                "model": "closed",
                "profile": "ramp",
                "users": 1,
                "ramp_seconds": 1,
                "duration_seconds": 1,
            },
            "assertions": [
                {"name": "a", "metric": "global.responseTime.p95", "op": "<", "value": 1}
            ],
        },
        "lint_waivers": [
            {
                "rule": "check-lint.mutating-status-check",
                "reason": "endpoint returns only 200 with empty body",
                "owner": "perf-team",
                "expires": "2999-01-01",
            }
        ],
    }


class WaiverTest(unittest.TestCase):
    def test_waiver_downgrades_blocking_finding(self) -> None:
        result = scenario_lint.lint_with_waivers(waived_document(), None, today=date(2026, 6, 10))
        blocking_rules = [f.rule for f in result.blocking]
        self.assertNotIn("check-lint.mutating-status-check", blocking_rules)
        self.assertEqual(result.waivers[0]["rule"], "check-lint.mutating-status-check")

    def test_expired_waiver_does_not_apply_and_warns(self) -> None:
        document = waived_document()
        document["lint_waivers"][0]["expires"] = "2020-01-01"
        result = scenario_lint.lint_with_waivers(document, None, today=date(2026, 6, 10))
        self.assertIn("check-lint.mutating-status-check", [f.rule for f in result.blocking])
        self.assertIn("waiver-lint.expired", [f.rule for f in result.warnings])

    def test_unused_waiver_warns(self) -> None:
        document = waived_document()
        document["scenario"]["steps"][0]["checks"].append({"status": 200})
        result = scenario_lint.lint_with_waivers(document, None, today=date(2026, 6, 10))
        self.assertIn("waiver-lint.unused", [f.rule for f in result.warnings])


class ExtractTypeEnumTest(unittest.TestCase):
    def test_schema_restricts_extract_types(self) -> None:
        schema = json.loads(
            (REPO_ROOT / "schemas" / "scenario.schema.json").read_text(encoding="utf-8")
        )
        enum = schema["$defs"]["checks"]["items"]["oneOf"][1]["properties"]["extract"]["properties"]["type"]["enum"]
        self.assertEqual(set(enum), {"css", "jsonPath", "regex"})


class LoadProfileLintTest(unittest.TestCase):
    def lint(self, load):
        document = {
            "scenario": {
                "id": "demo",
                "title": "Demo",
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
                "load": load,
                "assertions": [
                    {"name": "a", "metric": "global.responseTime.p95", "op": "<", "value": 1}
                ],
            }
        }
        return [f.rule for f in scenario_lint.lint_document(document)]

    def test_stress_users_must_divide_by_levels(self) -> None:
        rules = self.lint(
            {"model": "closed", "profile": "stress", "users": 10, "levels": 3,
             "level_duration_seconds": 60}
        )
        self.assertIn("scenario-lint.stress-step-mismatch", rules)

    def test_spike_baseline_must_be_below_peak(self) -> None:
        rules = self.lint(
            {"model": "closed", "profile": "spike", "users": 5, "baseline_users": 5,
             "baseline_seconds": 60, "spike_rise_seconds": 5, "spike_hold_seconds": 10}
        )
        self.assertIn("scenario-lint.spike-baseline-not-below-peak", rules)

    def test_short_soak_warns(self) -> None:
        document_rules = self.lint(
            {"model": "closed", "profile": "soak", "users": 5, "duration_seconds": 600}
        )
        self.assertIn("scenario-lint.soak-too-short", document_rules)

    def test_valid_open_constant_has_no_load_findings(self) -> None:
        rules = self.lint(
            {"model": "open", "profile": "constant", "users_per_second": 2.5,
             "duration_seconds": 120}
        )
        self.assertEqual(rules, [])


def graphql_lint_step():
    return {
        "name": "gql-search",
        "title": "GraphQL search",
        "transaction": "02 search.gql-search - GraphQL search",
        "protocol": "graphql",
        "graphql": {"query": "query{ x }", "variables": {"q": "${term}"}},
        "checks": [{"status": 200}],
    }


class GraphqlLintTest(unittest.TestCase):
    def document_with(self, step):
        return {
            "scenario": {
                "id": "demo",
                "title": "Demo",
                "source": {"type": "manual", "ref": "t"},
                "sut": {"base_url": "${BASE_URL}"},
                "steps": [step],
                "load": {"model": "closed", "profile": "constant", "users": 1,
                         "duration_seconds": 60},
                "assertions": [
                    {"name": "a", "metric": "global.responseTime.p95", "op": "<", "value": 1}
                ],
            }
        }

    def test_graphql_step_is_supported(self) -> None:
        step = graphql_lint_step()
        step["graphql"]["variables"] = {}
        rules = [f.rule for f in scenario_lint.lint_document(self.document_with(step))]
        self.assertNotIn("scenario-lint.protocol-supported", rules)

    def test_graphql_requires_query(self) -> None:
        step = graphql_lint_step()
        step["graphql"]["query"] = "  "
        step["graphql"]["variables"] = {}
        rules = [f.rule for f in scenario_lint.lint_document(self.document_with(step))]
        self.assertIn("scenario-lint.graphql-query-required", rules)

    def test_graphql_requires_status_check(self) -> None:
        step = graphql_lint_step()
        step["graphql"]["variables"] = {}
        step["checks"] = [{"extract": {"type": "jsonPath", "expr": "$.x", "saveAs": "x"}}]
        rules = [f.rule for f in scenario_lint.lint_document(self.document_with(step))]
        self.assertIn("check-lint.mutating-status-check", rules)

    def test_graphql_variables_join_correlation(self) -> None:
        rules = [f.rule for f in scenario_lint.lint_document(self.document_with(graphql_lint_step()))]
        self.assertIn("feeder-lint.missing-feeder", rules)


def populations_document():
    return {
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
                    "load": {"model": "open", "profile": "constant", "users_per_second": 1,
                             "duration_seconds": 60},
                },
            ],
            "assertions": [
                {"name": "a", "metric": "global.responseTime.p95", "op": "<", "value": 1}
            ],
        }
    }


class PopulationsLintTest(unittest.TestCase):
    def rules(self, document):
        return [f.rule for f in scenario_lint.lint_document(document)]

    def test_valid_populations_pass(self) -> None:
        self.assertEqual(
            [r for r in self.rules(populations_document()) if r.startswith(("scenario-lint", "transaction-lint", "check-lint"))],
            [],
        )

    def test_population_name_must_be_kebab(self) -> None:
        document = populations_document()
        document["scenario"]["populations"][0]["name"] = "Main Flow"
        self.assertIn("scenario-lint.population-name", self.rules(document))

    def test_duplicate_population_names_blocked(self) -> None:
        document = populations_document()
        document["scenario"]["populations"][1]["name"] = "main-flow"
        self.assertIn("scenario-lint.unique-population-names", self.rules(document))

    def test_transactions_unique_across_populations(self) -> None:
        document = populations_document()
        document["scenario"]["populations"][1]["steps"][0]["transaction"] = (
            "01 demo.open - Open"
        )
        self.assertIn("transaction-lint.unique", self.rules(document))

    def test_step_names_unique_across_populations(self) -> None:
        document = populations_document()
        document["scenario"]["populations"][1]["steps"][0]["name"] = "open"
        self.assertIn("scenario-lint.unique-step-names", self.rules(document))

    def test_cross_population_variable_is_blocked(self) -> None:
        document = populations_document()
        document["scenario"]["populations"][0]["steps"][0]["checks"].append(
            {"extract": {"type": "css", "expr": "input", "saveAs": "token"}}
        )
        document["scenario"]["populations"][1]["steps"][0]["request"]["path"] = "/bg?t=${token}"
        self.assertIn("correlation-lint.cross-population-variable", self.rules(document))

    def test_same_population_variable_is_fine(self) -> None:
        document = populations_document()
        document["scenario"]["populations"][0]["steps"][0]["checks"].append(
            {"extract": {"type": "css", "expr": "input", "saveAs": "token"}}
        )
        document["scenario"]["populations"][0]["steps"].append(
            {
                "name": "use-token",
                "title": "Use token",
                "transaction": "02 demo.use-token - Use token",
                "protocol": "http",
                "request": {"method": "GET", "path": "/use?t=${token}"},
                "checks": [{"status": 200}],
            }
        )
        self.assertNotIn(
            "correlation-lint.cross-population-variable", self.rules(document)
        )
        self.assertNotIn("feeder-lint.missing-feeder", self.rules(document))

    def test_population_var_collision_is_blocked(self) -> None:
        document = populations_document()
        document["scenario"]["populations"][0]["name"] = "flow-1"
        document["scenario"]["populations"][1]["name"] = "flow1"
        self.assertIn("scenario-lint.population-name-collision", self.rules(document))


class InvalidFixturesTest(unittest.TestCase):
    """Every file under examples/scenarios/invalid/ must produce at least one blocking finding."""

    def test_all_invalid_fixtures_block(self) -> None:
        invalid_dir = REPO_ROOT / "examples" / "scenarios" / "invalid"
        yaml_files = list(invalid_dir.glob("*.yaml"))
        self.assertTrue(yaml_files, "no *.yaml fixtures found in examples/scenarios/invalid/")
        for path in yaml_files:
            with self.subTest(fixture=path.name):
                try:
                    document = scenario_lint.load_yaml(path)
                    result = scenario_lint.lint_with_waivers(document, path.parent)
                except Exception:
                    # load/schema failure is itself a blocking condition
                    continue
                self.assertTrue(
                    result.blocking,
                    f"{path.name} produced no blocking findings — it should be permanently blocking",
                )


def http_step(method: str) -> dict:
    return {
        "name": "step",
        "title": "Step",
        "transaction": "01 demo.step - Step",
        "protocol": "http",
        "request": {"method": method, "path": "/"},
        "checks": [{"status": 200}],
    }


def minimal_document(step: dict) -> dict:
    return {
        "scenario": {
            "id": "demo",
            "title": "Demo",
            "source": {"type": "manual", "ref": "t"},
            "sut": {"base_url": "${BASE_URL}"},
            "steps": [step],
            "load": {
                "model": "closed",
                "profile": "constant",
                "users": 1,
                "duration_seconds": 60,
            },
            "assertions": [
                {"name": "a", "metric": "global.responseTime.p95", "op": "<", "value": 1}
            ],
        }
    }


class UnsupportedMethodLintTest(unittest.TestCase):
    def rules(self, document: dict) -> list[str]:
        return [f.rule for f in scenario_lint.lint_document(document)]

    def test_put_is_blocked(self) -> None:
        rules = self.rules(minimal_document(http_step("PUT")))
        self.assertIn("scenario-lint.unsupported-method", rules)

    def test_patch_is_blocked(self) -> None:
        rules = self.rules(minimal_document(http_step("PATCH")))
        self.assertIn("scenario-lint.unsupported-method", rules)

    def test_delete_is_blocked(self) -> None:
        rules = self.rules(minimal_document(http_step("DELETE")))
        self.assertIn("scenario-lint.unsupported-method", rules)

    def test_get_is_not_blocked(self) -> None:
        rules = self.rules(minimal_document(http_step("GET")))
        self.assertNotIn("scenario-lint.unsupported-method", rules)

    def test_post_is_not_blocked(self) -> None:
        rules = self.rules(minimal_document(http_step("POST")))
        self.assertNotIn("scenario-lint.unsupported-method", rules)


if __name__ == "__main__":
    sys.exit(unittest.main())

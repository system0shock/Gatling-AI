#!/usr/bin/env python3
"""Unit tests for scenario lint."""

from __future__ import annotations

import json
import sys
import tempfile
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
        step_schema = schema["$defs"]["steps"]["items"]
        seen_protocols = set()
        for variant in step_schema["oneOf"]:
            protocol = variant["properties"]["protocol"]["const"]
            seen_protocols.add(protocol)
            if protocol in {"http", "graphql"}:
                self.assertIn("checks", variant["required"])
            else:
                self.assertNotIn("checks", variant.get("properties", {}))
        self.assertEqual(seen_protocols, {"http", "graphql", "kafka", "jdbc"})

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
            "system": "DEMO",
            "number": 1,
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
                "system": "DEMO",
                "number": 1,
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
                "system": "DEMO",
                "number": 1,
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
            "system": "DEMO",
            "number": 1,
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
                            "transaction": "03 bg.open - Bg open",
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

    def test_cross_population_hook_read_is_blocked(self) -> None:
        document = populations_document()
        document["scenario"]["populations"][0]["steps"][0]["checks"].append(
            {"extract": {"type": "css", "expr": "input", "saveAs": "token"}}
        )
        document["scenario"]["populations"][1]["steps"][0]["hooks"] = {
            "after": [
                {"ref": "x.groovy", "kind": "todo", "summary": "uses token", "reads": ["token"]}
            ]
        }
        rules = self.rules(document)
        self.assertIn("correlation-lint.cross-population-variable", rules)
        self.assertNotIn("correlation-lint.hook-read-undefined", rules)

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
            "system": "DEMO",
            "number": 1,
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


class SystemNumberLintTest(unittest.TestCase):
    def rules(self, document: dict) -> list[str]:
        return [f.rule for f in scenario_lint.lint_document(document)]

    def test_missing_system_blocks(self) -> None:
        document = minimal_document(http_step("GET"))
        del document["scenario"]["system"]
        self.assertIn("scenario-lint.system-format", self.rules(document))

    def test_lowercase_system_blocks(self) -> None:
        document = minimal_document(http_step("GET"))
        document["scenario"]["system"] = "shop"
        self.assertIn("scenario-lint.system-format", self.rules(document))

    def test_missing_number_blocks(self) -> None:
        document = minimal_document(http_step("GET"))
        del document["scenario"]["number"]
        self.assertIn("scenario-lint.number-format", self.rules(document))

    def test_zero_and_bool_number_block(self) -> None:
        for bad in (0, -1, True, "1"):
            document = minimal_document(http_step("GET"))
            document["scenario"]["number"] = bad
            self.assertIn("scenario-lint.number-format", self.rules(document), repr(bad))

    def test_valid_system_and_number_pass(self) -> None:
        document = minimal_document(http_step("GET"))
        rules = self.rules(document)
        self.assertNotIn("scenario-lint.system-format", rules)
        self.assertNotIn("scenario-lint.number-format", rules)


class FeederNamingLintTest(unittest.TestCase):
    def rules(self, feeder: dict) -> list[str]:
        document = minimal_document(http_step("GET"))
        document["scenario"]["data"] = {"feeders": [feeder]}
        return [f.rule for f in scenario_lint.lint_document(document)]

    def test_valid_feeder_passes(self) -> None:
        rules = self.rules({"name": "terms", "file": "terms.csv", "strategy": "circular"})
        self.assertNotIn("feeder-lint.name-format", rules)
        self.assertNotIn("feeder-lint.file-name", rules)

    def test_non_kebab_name_blocks(self) -> None:
        rules = self.rules({"name": "Terms", "file": "Terms.csv", "strategy": "circular"})
        self.assertIn("feeder-lint.name-format", rules)

    def test_file_must_match_feeder_name(self) -> None:
        rules = self.rules({"name": "terms", "file": "search-terms.csv", "strategy": "circular"})
        self.assertIn("feeder-lint.file-name", rules)


class TransactionNumberingLintTest(unittest.TestCase):
    def test_duplicate_number_across_populations_blocks(self) -> None:
        document = populations_document()
        document["scenario"]["populations"][1]["steps"][0]["transaction"] = (
            "01 bg.open - Bg open"
        )
        rules = [f.rule for f in scenario_lint.lint_document(document)]
        self.assertIn("transaction-lint.duplicate-number", rules)

    def test_through_numbering_passes(self) -> None:
        rules = [f.rule for f in scenario_lint.lint_document(populations_document())]
        self.assertNotIn("transaction-lint.duplicate-number", rules)


class LayoutLintTest(unittest.TestCase):
    def make_doc(self, system: str = "SHOP", number: int = 1, scenario_id: str = "demo") -> dict:
        document = minimal_document(http_step("GET"))
        document["scenario"]["id"] = scenario_id
        document["scenario"]["system"] = system
        document["scenario"]["number"] = number
        return document

    def write_scenario(self, root: Path, system_dir: str, folder: str, document: dict) -> Path:
        directory = root / system_dir / folder
        directory.mkdir(parents=True)
        path = directory / "scenario.yaml"
        path.write_text(json.dumps(document), encoding="utf-8")  # YAML is a JSON superset
        return path

    def rules(self, document: dict, path: Path) -> list[str]:
        return [f.rule for f in scenario_lint.lint_layout(document, path)]

    def test_canonical_layout_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_scenario(Path(tmp), "SHOP", "demo-001", self.make_doc())
            self.assertEqual(self.rules(self.make_doc(), path), [])

    def test_wrong_folder_name_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_scenario(Path(tmp), "SHOP", "demo-1", self.make_doc())
            self.assertIn("layout-lint.folder-name", self.rules(self.make_doc(), path))

    def test_wrong_system_dir_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_scenario(Path(tmp), "CRM", "demo-001", self.make_doc())
            self.assertIn("layout-lint.system-folder", self.rules(self.make_doc(), path))

    def test_duplicate_number_in_system_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.write_scenario(
                Path(tmp), "SHOP", "other-001", self.make_doc(scenario_id="other")
            )
            path = self.write_scenario(Path(tmp), "SHOP", "demo-001", self.make_doc())
            self.assertIn("layout-lint.duplicate-number", self.rules(self.make_doc(), path))

    def test_non_canonical_filename_skips_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "whatever.yaml"
            path.write_text(json.dumps(self.make_doc()), encoding="utf-8")
            self.assertEqual(self.rules(self.make_doc(), path), [])

    def test_malformed_sibling_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            broken_dir = Path(tmp) / "SHOP" / "broken-002"
            broken_dir.mkdir(parents=True)
            (broken_dir / "scenario.yaml").write_text('scenario: "oops"', encoding="utf-8")
            path = self.write_scenario(Path(tmp), "SHOP", "demo-001", self.make_doc())
            self.assertEqual(self.rules(self.make_doc(), path), [])


class FeederStrategyTest(unittest.TestCase):
    def test_schema_strategy_is_enum(self) -> None:
        schema = json.loads(
            (REPO_ROOT / "schemas" / "scenario.schema.json").read_text(encoding="utf-8")
        )
        feeder = schema["$defs"]["data"]["properties"]["feeders"]["items"]
        self.assertEqual(
            feeder["properties"]["strategy"]["enum"],
            ["circular", "queue", "random", "shuffle"],
        )

    def test_queue_feeder_with_too_few_rows_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "users.csv").write_text("username\nalice\nbob\n", encoding="utf-8")
            document = waived_document()
            del document["lint_waivers"]
            scenario = document["scenario"]
            scenario["data"] = {
                "feeders": [{"name": "users", "file": "users.csv", "strategy": "queue"}]
            }
            scenario["load"]["users"] = 10
            findings = scenario_lint.lint_document(document, base)
            rules = [f.rule for f in findings]
            self.assertIn("feeder-lint.queue-data-volume", rules)
            volume = next(f for f in findings if f.rule == "feeder-lint.queue-data-volume")
            self.assertEqual(volume.severity, "warning")

    def test_circular_feeder_with_few_rows_does_not_warn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "users.csv").write_text("username\nalice\n", encoding="utf-8")
            document = waived_document()
            del document["lint_waivers"]
            scenario = document["scenario"]
            scenario["data"] = {
                "feeders": [{"name": "users", "file": "users.csv", "strategy": "circular"}]
            }
            scenario["load"]["users"] = 10
            findings = scenario_lint.lint_document(document, base)
            self.assertNotIn("feeder-lint.queue-data-volume", [f.rule for f in findings])

    def test_queue_feeder_with_equal_rows_does_not_warn(self) -> None:
        # Boundary: warning uses strict peak_users > rows, so rows == peak must not warn.
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "users.csv").write_text(
                "username\n" + "".join(f"u{i}\n" for i in range(10)), encoding="utf-8"
            )
            document = waived_document()
            del document["lint_waivers"]
            scenario = document["scenario"]
            scenario["data"] = {
                "feeders": [{"name": "users", "file": "users.csv", "strategy": "queue"}]
            }
            scenario["load"]["users"] = 10  # rows == peak_users
            findings = scenario_lint.lint_document(document, base)
            self.assertNotIn("feeder-lint.queue-data-volume", [f.rule for f in findings])


def body_file_document(base: Path, body_name: str = "bodies/payload.json"):
    document = waived_document()
    del document["lint_waivers"]
    step = document["scenario"]["steps"][0]
    step["checks"] = [{"status": 200}]
    step["request"]["body_file"] = body_name
    return document


class BodyFileLintTest(unittest.TestCase):
    def test_missing_body_file_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            findings = scenario_lint.lint_document(body_file_document(Path(tmp)), Path(tmp))
            self.assertIn("scenario-lint.body-file-missing", [f.rule for f in findings])

    def test_existing_body_file_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "bodies").mkdir()
            (base / "bodies" / "payload.json").write_text("{}", encoding="utf-8")
            findings = scenario_lint.lint_document(body_file_document(base), base)
            self.assertNotIn("scenario-lint.body-file-missing", [f.rule for f in findings])

    def test_body_and_body_file_conflict_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "bodies").mkdir()
            (base / "bodies" / "payload.json").write_text("{}", encoding="utf-8")
            document = body_file_document(base)
            document["scenario"]["steps"][0]["request"]["body"] = "inline"
            findings = scenario_lint.lint_document(document, base)
            self.assertIn("scenario-lint.body-file-conflict", [f.rule for f in findings])


def hooks_document():
    document = waived_document()
    del document["lint_waivers"]
    step = document["scenario"]["steps"][0]
    step["checks"] = [{"status": 200}]
    step["hooks"] = {
        "before": [
            {
                "ref": "migration/jsr223/sign-request.groovy",
                "kind": "translated",
                "snippet": "snippets/SignRequest.java",
                "summary": "signs the body",
                "reads": [],
                "writes": ["signature"],
            }
        ]
    }
    step["request"]["body"] = "sig=${signature}"
    return document


class HooksLintTest(unittest.TestCase):
    def test_missing_snippet_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            findings = scenario_lint.lint_document(hooks_document(), Path(tmp))
            self.assertIn("scenario-lint.snippet-missing", [f.rule for f in findings])

    def test_existing_snippet_passes_and_ref_missing_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "snippets").mkdir()
            (base / "snippets" / "SignRequest.java").write_text("class X {}", encoding="utf-8")
            findings = scenario_lint.lint_document(hooks_document(), base)
            rules = [f.rule for f in findings]
            self.assertNotIn("scenario-lint.snippet-missing", rules)
            self.assertIn("scenario-lint.hook-ref-missing", rules)

    def test_hook_write_satisfies_variable_use(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "snippets").mkdir()
            (base / "snippets" / "SignRequest.java").write_text("class X {}", encoding="utf-8")
            findings = scenario_lint.lint_document(hooks_document(), base)
            missing = [
                f for f in findings
                if f.rule == "feeder-lint.missing-feeder" and "signature" in f.message
            ]
            self.assertEqual(missing, [])

    def test_undefined_hook_read_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "snippets").mkdir()
            (base / "snippets" / "SignRequest.java").write_text("class X {}", encoding="utf-8")
            document = hooks_document()
            document["scenario"]["steps"][0]["hooks"]["before"][0]["reads"] = ["nosuchvar"]
            findings = scenario_lint.lint_document(document, base)
            self.assertIn(
                "correlation-lint.hook-read-undefined", [f.rule for f in findings]
            )


class StagesLintTest(unittest.TestCase):
    def _document(self, stages, model="closed"):
        document = waived_document()
        del document["lint_waivers"]
        document["scenario"]["steps"][0]["checks"] = [{"status": 200}]
        document["scenario"]["load"] = {
            "model": model,
            "profile": "stages",
            "stages": stages,
        }
        return document

    def test_valid_stages_pass(self) -> None:
        findings = scenario_lint.lint_document(
            self._document([{"users": 5, "ramp_seconds": 10, "hold_seconds": 20}]), None
        )
        self.assertNotIn(
            "scenario-lint.stage-no-duration", [f.rule for f in findings]
        )

    def test_zero_duration_stage_blocks(self) -> None:
        findings = scenario_lint.lint_document(
            self._document([{"users": 5, "ramp_seconds": 0, "hold_seconds": 0}]), None
        )
        self.assertIn("scenario-lint.stage-no-duration", [f.rule for f in findings])

    def test_non_positive_stage_users_blocks(self) -> None:
        findings = scenario_lint.lint_document(
            self._document([{"users": 0, "ramp_seconds": 10, "hold_seconds": 0}]), None
        )
        self.assertIn("scenario-lint.stage-values", [f.rule for f in findings])

    def test_non_positive_stage_rate_blocks_open_model(self) -> None:
        findings = scenario_lint.lint_document(
            self._document(
                [{"users_per_second": 0, "ramp_seconds": 10, "hold_seconds": 0}],
                model="open",
            ),
            None,
        )
        self.assertIn("scenario-lint.stage-values", [f.rule for f in findings])

    def test_zero_duration_stage_blocks_open_model(self) -> None:
        findings = scenario_lint.lint_document(
            self._document(
                [{"users_per_second": 5, "ramp_seconds": 0, "hold_seconds": 0}],
                model="open",
            ),
            None,
        )
        self.assertIn("scenario-lint.stage-no-duration", [f.rule for f in findings])


def kafka_jdbc_document():
    document = waived_document()
    del document["lint_waivers"]
    document["scenario"]["steps"][0]["checks"] = [{"status": 200}]
    document["scenario"]["steps"].extend(
        [
            {
                "name": "publish-event",
                "title": "Publish event",
                "transaction": "02 orders.publish - Publish order event",
                "protocol": "kafka",
                "kafka": {"topic": "orders", "key": "${orderId}", "payload": '{"id":"${orderId}"}'},
                "tags": ["kafka-via-proxy"],
            },
            {
                "name": "check-balance",
                "title": "Check balance",
                "transaction": "03 orders.check-balance - Check balance",
                "protocol": "jdbc",
                "jdbc": {"query": "SELECT 1", "saveAs": "balance"},
            },
            {
                "name": "use-balance",
                "title": "Use balance",
                "transaction": "04 orders.use-balance - Use balance",
                "protocol": "http",
                "request": {"method": "GET", "path": "/b/${balance}"},
                "checks": [{"status": 200}],
            },
        ]
    )
    return document


class ProtocolStubLintTest(unittest.TestCase):
    def test_kafka_and_jdbc_warn_not_block(self) -> None:
        document = kafka_jdbc_document()
        # orderId is undefined on purpose elsewhere; define it via extraction:
        document["scenario"]["steps"][0]["checks"].append(
            {"extract": {"type": "jsonPath", "expr": "$.id", "saveAs": "orderId"}}
        )
        findings = scenario_lint.lint_document(document, None)
        stub = [f for f in findings if f.rule == "scenario-lint.protocol-stub"]
        self.assertEqual(len(stub), 2)
        self.assertTrue(all(f.severity == "warning" for f in stub))
        self.assertNotIn(
            "scenario-lint.protocol-supported", [f.rule for f in findings]
        )
        self.assertNotIn("check-lint.missing-checks", [f.rule for f in findings])

    def test_jdbc_save_as_satisfies_downstream_use(self) -> None:
        document = kafka_jdbc_document()
        document["scenario"]["steps"][0]["checks"].append(
            {"extract": {"type": "jsonPath", "expr": "$.id", "saveAs": "orderId"}}
        )
        findings = scenario_lint.lint_document(document, None)
        balance_findings = [
            f for f in findings
            if f.rule == "feeder-lint.missing-feeder" and "balance" in f.message
        ]
        self.assertEqual(balance_findings, [])

    def test_unknown_protocol_still_blocks(self) -> None:
        document = kafka_jdbc_document()
        document["scenario"]["steps"][1]["protocol"] = "grpc"
        findings = scenario_lint.lint_document(document, None)
        self.assertIn("scenario-lint.protocol-supported", [f.rule for f in findings])


if __name__ == "__main__":
    sys.exit(unittest.main())

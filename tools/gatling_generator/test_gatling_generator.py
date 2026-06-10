#!/usr/bin/env python3
"""Unit tests for the Gatling generator."""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import gatling_generator


def minimal_scenario(**overrides):
    scenario = {
        "id": "demo-flow",
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
            {"name": "p95-under-800ms", "metric": "global.responseTime.p95", "op": "<", "value": 800},
            {"name": "ok-rate", "metric": "global.successfulRequests.percent", "op": ">", "value": 99},
        ],
    }
    scenario.update(overrides)
    return {"scenario": scenario}


class RenderAssertionsTest(unittest.TestCase):
    def test_simulation_contains_assertions(self) -> None:
        _, content = gatling_generator.render_simulation(minimal_scenario())
        self.assertIn(".assertions(", content)
        self.assertIn("global().responseTime().percentile(95.0).lt(800)", content)
        self.assertIn("global().successfulRequests().percent().gt(99.0)", content)

    def test_percent_assertion_integer_value_renders_as_double(self) -> None:
        assertion = {"metric": "global.successfulRequests.percent", "op": ">", "value": 99}
        result = gatling_generator.render_assertion(assertion)
        self.assertEqual(result, "global().successfulRequests().percent().gt(99.0)")

    def test_percent_assertion_float_value_renders_as_double(self) -> None:
        assertion = {"metric": "global.failedRequests.percent", "op": "<", "value": 99.5}
        result = gatling_generator.render_assertion(assertion)
        self.assertEqual(result, "global().failedRequests().percent().lt(99.5)")

    def test_non_finite_percent_assertion_rejected(self) -> None:
        for bad in (float("inf"), float("-inf"), float("nan")):
            with self.subTest(value=bad):
                assertion = {"metric": "global.successfulRequests.percent", "op": ">", "value": bad}
                with self.assertRaisesRegex(ValueError, "must be finite"):
                    gatling_generator.render_assertion(assertion)

    def test_non_finite_response_time_assertion_rejected(self) -> None:
        for bad in (float("inf"), float("-inf"), float("nan")):
            with self.subTest(value=bad):
                assertion = {"metric": "global.responseTime.p95", "op": "<", "value": bad}
                with self.assertRaisesRegex(ValueError, "must be finite"):
                    gatling_generator.render_assertion(assertion)

    def test_unknown_metric_is_rejected(self) -> None:
        document = minimal_scenario(
            assertions=[{"name": "x", "metric": "global.unknown.p95", "op": "<", "value": 1}]
        )
        with self.assertRaises(ValueError):
            gatling_generator.render_simulation(document)

    def test_unknown_op_is_rejected(self) -> None:
        document = minimal_scenario(
            assertions=[
                {"name": "x", "metric": "global.responseTime.p95", "op": "~", "value": 1}
            ]
        )
        with self.assertRaises(ValueError):
            gatling_generator.render_simulation(document)

    def test_missing_assertions_is_rejected(self) -> None:
        document = minimal_scenario()
        del document["scenario"]["assertions"]
        with self.assertRaises(ValueError):
            gatling_generator.render_simulation(document)


class FeederContainmentTest(unittest.TestCase):
    def test_feeder_resolving_outside_scenario_dir_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scenario_dir = root / "scenarios"
            scenario_dir.mkdir()
            outside = root / "outside.csv"
            outside.write_text("username\nalice\n", encoding="utf-8")
            link = scenario_dir / "users.csv"
            try:
                link.symlink_to(outside)
            except OSError:
                self.skipTest("symlinks unavailable without privileges")
            scenario_path = scenario_dir / "demo.yaml"
            scenario_path.write_text("placeholder", encoding="utf-8")
            document = minimal_scenario(
                data={"feeders": [{"name": "users", "file": "users.csv", "strategy": "circular"}]}
            )
            with self.assertRaises(ValueError):
                gatling_generator.copy_feeder_resources(document, scenario_path, root / "out")


class JsonOutputTest(unittest.TestCase):
    def test_failure_emits_findings_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scenario = Path(tmp) / "bad.yaml"
            scenario.write_text("scenario:\n  id: Bad_Id\n", encoding="utf-8")
            stdout = io.StringIO()
            with patch.object(sys, "stdout", stdout):
                code = gatling_generator.main(
                    [str(scenario), str(Path(tmp) / "out"), "--format", "json"]
                )
            self.assertEqual(code, 1)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["blocking"][0]["rule"], "generator.invalid-scenario")
            self.assertIn("message", payload["blocking"][0])


class ExtractorTest(unittest.TestCase):
    def test_regex_extractor_renders(self) -> None:
        document = minimal_scenario()
        document["scenario"]["steps"][0]["checks"].append(
            {"extract": {"type": "regex", "expr": "token=(\\w+)", "saveAs": "token"}}
        )
        _, content = gatling_generator.render_simulation(document)
        self.assertIn('regex("token=(\\\\w+)").saveAs("token")', content)

    def test_jsonpath_extractor_renders(self) -> None:
        document = minimal_scenario()
        document["scenario"]["steps"][0]["checks"].append(
            {"extract": {"type": "jsonPath", "expr": "$.token", "saveAs": "token"}}
        )
        _, content = gatling_generator.render_simulation(document)
        self.assertIn('jsonPath("$.token").saveAs("token")', content)

    def test_unknown_extract_type_is_rejected(self) -> None:
        document = minimal_scenario()
        document["scenario"]["steps"][0]["checks"].append(
            {"extract": {"type": "xpath", "expr": "//a", "saveAs": "x"}}
        )
        with self.assertRaises(ValueError):
            gatling_generator.render_simulation(document)


class PauseTest(unittest.TestCase):
    def test_integer_pause_renders_seconds(self) -> None:
        document = minimal_scenario()
        document["scenario"]["steps"][0]["pause_seconds"] = 3
        _, content = gatling_generator.render_simulation(document)
        self.assertIn(").pause(Duration.ofSeconds(3))", content)

    def test_fractional_pause_renders_millis(self) -> None:
        document = minimal_scenario()
        document["scenario"]["steps"][0]["pause_seconds"] = 0.5
        _, content = gatling_generator.render_simulation(document)
        self.assertIn(").pause(Duration.ofMillis(500))", content)

    def test_non_positive_pause_is_rejected(self) -> None:
        document = minimal_scenario()
        document["scenario"]["steps"][0]["pause_seconds"] = 0
        with self.assertRaises(ValueError):
            gatling_generator.render_simulation(document)

    def test_float_integer_pause_renders_seconds(self) -> None:
        document = minimal_scenario()
        document["scenario"]["steps"][0]["pause_seconds"] = 2.0
        _, content = gatling_generator.render_simulation(document)
        self.assertIn(").pause(Duration.ofSeconds(2))", content)

    def test_submillisecond_pause_is_rejected(self) -> None:
        document = minimal_scenario()
        document["scenario"]["steps"][0]["pause_seconds"] = 0.0001
        with self.assertRaises(ValueError):
            gatling_generator.render_simulation(document)

    def test_non_finite_pause_is_rejected(self) -> None:
        document = minimal_scenario()
        document["scenario"]["steps"][0]["pause_seconds"] = float("nan")
        with self.assertRaises(ValueError):
            gatling_generator.render_simulation(document)


class LoadProfileTest(unittest.TestCase):
    def render_with_load(self, load):
        document = minimal_scenario(load=load)
        _, content = gatling_generator.render_simulation(document)
        return content

    def test_closed_constant(self) -> None:
        content = self.render_with_load(
            {"model": "closed", "profile": "constant", "users": 7, "duration_seconds": 90}
        )
        self.assertIn("injectClosed(", content)
        self.assertIn("constantConcurrentUsers(7).during(Duration.ofSeconds(90))", content)

    def test_open_ramp(self) -> None:
        content = self.render_with_load(
            {
                "model": "open",
                "profile": "ramp",
                "users_per_second": 2.5,
                "ramp_seconds": 30,
                "duration_seconds": 120,
            }
        )
        self.assertIn("injectOpen(", content)
        self.assertIn("rampUsersPerSec(0).to(2.5).during(Duration.ofSeconds(30))", content)
        self.assertIn("constantUsersPerSec(2.5).during(Duration.ofSeconds(120))", content)

    def test_closed_stress_levels(self) -> None:
        content = self.render_with_load(
            {
                "model": "closed",
                "profile": "stress",
                "users": 10,
                "levels": 5,
                "level_duration_seconds": 60,
            }
        )
        self.assertIn(
            "incrementConcurrentUsers(2).times(5)"
            ".eachLevelLasting(Duration.ofSeconds(60)).startingFrom(2)",
            content,
        )

    def test_closed_stress_requires_divisible_users(self) -> None:
        with self.assertRaises(ValueError):
            self.render_with_load(
                {
                    "model": "closed",
                    "profile": "stress",
                    "users": 10,
                    "levels": 3,
                    "level_duration_seconds": 60,
                }
            )

    def test_closed_spike_timeline(self) -> None:
        content = self.render_with_load(
            {
                "model": "closed",
                "profile": "spike",
                "users": 50,
                "baseline_users": 5,
                "baseline_seconds": 60,
                "spike_rise_seconds": 10,
                "spike_hold_seconds": 30,
            }
        )
        self.assertIn("constantConcurrentUsers(5).during(Duration.ofSeconds(60))", content)
        self.assertIn("rampConcurrentUsers(5).to(50).during(Duration.ofSeconds(10))", content)
        self.assertIn("constantConcurrentUsers(50).during(Duration.ofSeconds(30))", content)
        self.assertIn("rampConcurrentUsers(50).to(5).during(Duration.ofSeconds(10))", content)

    def test_unknown_profile_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.render_with_load(
                {"model": "closed", "profile": "burst", "users": 1, "duration_seconds": 1}
            )

    def test_open_stress_levels(self) -> None:
        content = self.render_with_load(
            {
                "model": "open",
                "profile": "stress",
                "users_per_second": 6,
                "levels": 3,
                "level_duration_seconds": 30,
            }
        )
        self.assertIn(
            "incrementUsersPerSec(2).times(3)"
            ".eachLevelLasting(Duration.ofSeconds(30)).startingFrom(2)",
            content,
        )

    def test_open_stress_missing_rate_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.render_with_load(
                {"model": "open", "profile": "stress", "levels": 2,
                 "level_duration_seconds": 30}
            )

    def test_open_spike_timeline(self) -> None:
        content = self.render_with_load(
            {
                "model": "open",
                "profile": "spike",
                "users_per_second": 10,
                "baseline_users_per_second": 1,
                "baseline_seconds": 30,
                "spike_rise_seconds": 5,
                "spike_hold_seconds": 15,
            }
        )
        self.assertIn("constantUsersPerSec(1).during(Duration.ofSeconds(30))", content)
        self.assertIn("rampUsersPerSec(1).to(10).during(Duration.ofSeconds(5))", content)
        self.assertIn("constantUsersPerSec(10).during(Duration.ofSeconds(15))", content)
        self.assertIn("rampUsersPerSec(10).to(1).during(Duration.ofSeconds(5))", content)

    def test_unknown_model_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.render_with_load(
                {"model": "mixed", "profile": "ramp", "users": 1,
                 "ramp_seconds": 1, "duration_seconds": 1}
            )


def graphql_step(**overrides):
    step = {
        "name": "gql-search",
        "title": "GraphQL search",
        "transaction": "02 search.gql-search - GraphQL search",
        "protocol": "graphql",
        "graphql": {
            "query": "query($q:String){ search(q:$q){ id } }",
            "variables": {"q": "${term}"},
        },
        "checks": [{"status": 200}],
    }
    step.update(overrides)
    return step


class GraphqlTest(unittest.TestCase):
    def test_graphql_renders_post_with_json_body(self) -> None:
        document = minimal_scenario()
        document["scenario"]["steps"].append(graphql_step())
        _, content = gatling_generator.render_simulation(document)
        self.assertIn('.post("/graphql")', content)
        self.assertIn('.header("Content-Type", "application/json")', content)
        self.assertIn('\\"query\\":\\"query($q:String){ search(q:$q){ id } }\\"', content)
        self.assertIn('\\"q\\":\\"#{term}\\"', content)

    def test_graphql_custom_path(self) -> None:
        document = minimal_scenario()
        step = graphql_step()
        step["graphql"]["path"] = "/api/graphql"
        document["scenario"]["steps"].append(step)
        _, content = gatling_generator.render_simulation(document)
        self.assertIn('.post("/api/graphql")', content)

    def test_graphql_requires_query(self) -> None:
        document = minimal_scenario()
        step = graphql_step()
        del step["graphql"]["query"]
        document["scenario"]["steps"].append(step)
        with self.assertRaises(ValueError):
            gatling_generator.render_simulation(document)

    def test_graphql_without_variables_omits_variables_key(self) -> None:
        document = minimal_scenario()
        step = graphql_step()
        del step["graphql"]["variables"]
        document["scenario"]["steps"].append(step)
        _, content = gatling_generator.render_simulation(document)
        self.assertNotIn("variables", content.split("class", 1)[1])

    def test_graphql_redirect_check_disables_follow(self) -> None:
        document = minimal_scenario()
        step = graphql_step()
        step["checks"] = [{"status": 302}]
        document["scenario"]["steps"].append(step)
        _, content = gatling_generator.render_simulation(document)
        self.assertIn(".disableFollowRedirect()", content.split("gql-search", 1)[1])


def populations_scenario():
    base = minimal_scenario()["scenario"]
    step_a = dict(base["steps"][0])
    step_b = dict(base["steps"][0])
    step_b["name"] = "bg-open"
    step_b["transaction"] = "01 bg.open - Background open"
    return {
        "scenario": {
            "id": base["id"],
            "title": base["title"],
            "source": base["source"],
            "sut": base["sut"],
            "populations": [
                {"name": "main-flow", "steps": [step_a], "load": base["load"]},
                {
                    "name": "background-search",
                    "steps": [step_b],
                    "load": {
                        "model": "open",
                        "profile": "constant",
                        "users_per_second": 2,
                        "duration_seconds": 60,
                    },
                },
            ],
            "assertions": base["assertions"],
        }
    }


class PopulationsTest(unittest.TestCase):
    def test_two_builders_and_combined_setup(self) -> None:
        _, content = gatling_generator.render_simulation(populations_scenario())
        self.assertIn('private final ScenarioBuilder mainFlow = scenario("main-flow")', content)
        self.assertIn(
            'private final ScenarioBuilder backgroundSearch = scenario("background-search")',
            content,
        )
        self.assertIn("mainFlow.injectClosed(", content)
        self.assertIn("backgroundSearch.injectOpen(", content)
        self.assertIn("constantUsersPerSec(2).during(Duration.ofSeconds(60))", content)

    def test_duplicate_population_names_rejected(self) -> None:
        document = populations_scenario()
        document["scenario"]["populations"][1]["name"] = "main-flow"
        with self.assertRaises(ValueError):
            gatling_generator.render_simulation(document)

    def test_single_flow_form_keeps_scenario_variable(self) -> None:
        _, content = gatling_generator.render_simulation(minimal_scenario())
        self.assertIn("private final ScenarioBuilder scenario = scenario(", content)

    def test_var_collision_message_names_both_populations(self) -> None:
        document = populations_scenario()
        document["scenario"]["populations"][0]["name"] = "flow-1"
        document["scenario"]["populations"][1]["name"] = "flow1"
        with self.assertRaises(ValueError) as raised:
            gatling_generator.render_simulation(document)
        self.assertIn("flow-1", str(raised.exception))
        self.assertIn("flow1", str(raised.exception))


class BootstrapTest(unittest.TestCase):
    def test_bootstrap_creates_pom_and_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "fresh"
            bootstrapped = gatling_generator.bootstrap_project(output_dir)
            self.assertTrue(bootstrapped)
            pom_text = (output_dir / "pom.xml").read_text(encoding="utf-8")
            self.assertIn("<gatling.version>3.12.0</gatling.version>", pom_text)
            self.assertIn(
                "<gatling.maven.plugin.version>4.21.7</gatling.maven.plugin.version>", pom_text
            )
            self.assertTrue((output_dir / "src" / "test" / "java").is_dir())
            self.assertTrue((output_dir / "src" / "test" / "resources").is_dir())

    def test_existing_pom_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            (output_dir / "pom.xml").write_text("<project/>", encoding="utf-8")
            self.assertFalse(gatling_generator.bootstrap_project(output_dir))
            self.assertEqual(
                (output_dir / "pom.xml").read_text(encoding="utf-8"), "<project/>"
            )

    def test_template_pom_matches_golden_pom(self) -> None:
        template = (
            Path(gatling_generator.__file__).resolve().parent / "templates" / "pom.xml"
        ).read_bytes()
        golden = (
            Path(gatling_generator.__file__).resolve().parents[2]
            / "examples" / "generated" / "java" / "pom.xml"
        ).read_bytes()
        self.assertEqual(template, golden, "template pom drifted from golden pom")
        checkout_golden = (
            Path(gatling_generator.__file__).resolve().parents[2]
            / "examples" / "generated" / "checkout-java" / "pom.xml"
        ).read_bytes()
        self.assertEqual(template, checkout_golden, "checkout-java pom drifted from template pom")


if __name__ == "__main__":
    sys.exit(unittest.main())

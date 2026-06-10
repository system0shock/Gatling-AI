#!/usr/bin/env python3
"""Unit tests for shared helpers."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

import common


class CamelCaseTest(unittest.TestCase):
    def test_kebab_to_camel(self) -> None:
        self.assertEqual(common.camel_case("main-checkout"), "mainCheckout")
        self.assertEqual(common.camel_case("login"), "login")

    def test_underscores_are_not_split(self) -> None:
        # scenario ids are kebab-case by contract; underscores pass through as-is
        self.assertEqual(common.camel_case("login_search"), "login_search")


class ScenarioPopulationsTest(unittest.TestCase):
    def test_single_flow_normalizes_to_one_population(self) -> None:
        scenario = {"id": "demo", "steps": [{"name": "s"}], "load": {"model": "closed"}}
        populations = common.scenario_populations(scenario)
        self.assertEqual(len(populations), 1)
        self.assertEqual(populations[0]["name"], "demo")
        self.assertEqual(populations[0]["steps"], [{"name": "s"}])
        self.assertEqual(populations[0]["load"], {"model": "closed"})

    def test_explicit_populations_pass_through(self) -> None:
        scenario = {
            "id": "demo",
            "populations": [
                {"name": "a", "steps": [], "load": {}},
                {"name": "b", "steps": [], "load": {}},
            ],
        }
        populations = common.scenario_populations(scenario)
        self.assertEqual([p["name"] for p in populations], ["a", "b"])

    def test_garbage_populations_fall_back_to_single_flow(self) -> None:
        scenario = {"id": "demo", "steps": [], "load": {}, "populations": ["junk", 42]}
        populations = common.scenario_populations(scenario)
        self.assertEqual(len(populations), 1)
        self.assertEqual(populations[0]["name"], "demo")


class RunCommandEnvTest(unittest.TestCase):
    def test_custom_env_is_passed_to_subprocess(self) -> None:
        result = common.run_command(
            [sys.executable, "-c",
             "import os; print(os.environ.get('GATLING_AI_TEST', 'missing'))"],
            cwd=Path(__file__).parent,
            env={**os.environ, "GATLING_AI_TEST": "hello"},
        )
        self.assertEqual(result.stdout.strip(), "hello")


if __name__ == "__main__":
    sys.exit(unittest.main())

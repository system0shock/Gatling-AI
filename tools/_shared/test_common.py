#!/usr/bin/env python3
"""Unit tests for shared helpers."""

from __future__ import annotations

import sys
import unittest

import common


class CamelCaseTest(unittest.TestCase):
    def test_kebab_to_camel(self) -> None:
        self.assertEqual(common.camel_case("main-checkout"), "mainCheckout")
        self.assertEqual(common.camel_case("login"), "login")


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


if __name__ == "__main__":
    sys.exit(unittest.main())

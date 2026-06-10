#!/usr/bin/env python3
"""Unit tests for scenario lint."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import scenario_lint

REPO_ROOT = Path(__file__).resolve().parents[2]


class SchemaContractTest(unittest.TestCase):
    def test_schema_requires_checks_per_step(self) -> None:
        schema = json.loads(
            (REPO_ROOT / "schemas" / "scenario.schema.json").read_text(encoding="utf-8")
        )
        step_schema = schema["properties"]["scenario"]["properties"]["steps"]["items"]
        self.assertIn("checks", step_schema["required"])


class DeadCodeRemovedTest(unittest.TestCase):
    def test_columns_helper_is_gone(self) -> None:
        self.assertFalse(hasattr(scenario_lint, "feeder_columns_from_config"))


if __name__ == "__main__":
    sys.exit(unittest.main())

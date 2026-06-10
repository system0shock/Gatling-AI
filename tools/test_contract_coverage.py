#!/usr/bin/env python3
"""Every schema field must be consumed or explicitly ignored by each consumer."""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO_ROOT = TOOLS.parent


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(path.parent))
    return module


def schema_paths(schema: dict, prefix: str = "") -> set[str]:
    paths: set[str] = set()
    for name, sub in schema.get("properties", {}).items():
        path = f"{prefix}.{name}" if prefix else name
        paths.add(path)
        paths.update(schema_paths(sub, path))
    items = schema.get("items")
    if isinstance(items, dict):
        paths.update(schema_paths(items, f"{prefix}[]"))
    for variant in schema.get("oneOf", []):
        paths.update(schema_paths(variant, prefix))
    return paths


class ContractCoverageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        schema = json.loads(
            (REPO_ROOT / "schemas" / "scenario.schema.json").read_text(encoding="utf-8")
        )
        cls.paths = schema_paths(schema)
        cls.generator = load_module(
            "gen_cc", TOOLS / "gatling_generator" / "gatling_generator.py"
        )
        cls.renderer = load_module(
            "ren_cc", TOOLS / "scenario_renderer" / "scenario_renderer.py"
        )

    def assert_covered(self, module) -> None:
        declared = module.CONSUMED_FIELDS | module.IGNORED_FIELDS
        missing = self.paths - declared
        stale = declared - self.paths
        self.assertEqual(missing, set(), f"schema fields not declared by {module.__name__}")
        self.assertEqual(stale, set(), f"declared fields missing from schema in {module.__name__}")

    def test_generator_covers_schema(self) -> None:
        self.assert_covered(self.generator)

    def test_renderer_covers_schema(self) -> None:
        self.assert_covered(self.renderer)


if __name__ == "__main__":
    sys.exit(unittest.main())

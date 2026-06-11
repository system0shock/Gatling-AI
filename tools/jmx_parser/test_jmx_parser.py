#!/usr/bin/env python3
"""Unit tests for the JMX parser."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import fixtures
import jmx_parser


class ParserCase(unittest.TestCase):
    """Shared setup: write a fixture document, parse it into a temp out dir."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.out_dir = self.tmp / "out"

    def parse(self, document: str, **kwargs):
        jmx_path = self.tmp / "plan.jmx"
        jmx_path.write_text(document, encoding="utf-8")
        return jmx_parser.parse_jmx(jmx_path, self.out_dir, **kwargs)


class WalkerTest(ParserCase):
    def test_minimal_plan(self) -> None:
        ir = self.parse(fixtures.jmx())
        self.assertEqual(ir["version"], 1)
        self.assertEqual(ir["test_plan"]["name"], "Test Plan")
        self.assertEqual(ir["test_plan"]["comments"], "fixture plan")
        self.assertEqual(ir["children"], [])
        self.assertEqual(ir["unsupported"], [])
        self.assertEqual(ir["source"]["file"], "plan.jmx")
        self.assertEqual(len(ir["source"]["sha256"]), 64)
        self.assertGreater(ir["source"]["size_bytes"], 0)

    def test_unknown_element_is_recorded_not_dropped(self) -> None:
        ir = self.parse(fixtures.jmx(fixtures.element("com.example.WeirdSampler", "weird")))
        node = ir["children"][0]
        self.assertEqual(node["kind"], "unknown")
        self.assertEqual(node["type"], "com.example.WeirdSampler")
        self.assertEqual(node["name"], "weird")
        self.assertEqual(ir["unsupported"][0]["id"], node["id"])
        self.assertEqual(ir["unsupported"][0]["path"], ["Test Plan"])

    def test_ids_follow_document_order(self) -> None:
        ir = self.parse(
            fixtures.jmx(
                fixtures.element("com.example.A", "a"),
                fixtures.element("com.example.B", "b"),
            )
        )
        self.assertEqual([node["id"] for node in ir["children"]], ["e-0001", "e-0002"])

    def test_nesting_follows_hash_trees(self) -> None:
        ir = self.parse(
            fixtures.jmx(
                fixtures.element(
                    "com.example.Outer", "outer",
                    children=fixtures.element("com.example.Inner", "inner"),
                )
            )
        )
        outer = ir["children"][0]
        self.assertEqual(outer["children"][0]["name"], "inner")
        self.assertEqual(outer["children"][0]["path"], ["Test Plan", "outer"])
        self.assertEqual(outer["children"][0]["id"], "e-0002")

    def test_disabled_element_keeps_enabled_false(self) -> None:
        ir = self.parse(fixtures.jmx(fixtures.element("com.example.A", "a", enabled=False)))
        self.assertFalse(ir["children"][0]["enabled"])


if __name__ == "__main__":
    sys.exit(unittest.main())

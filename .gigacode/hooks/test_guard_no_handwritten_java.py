#!/usr/bin/env python3
"""Unit tests for the guard_no_handwritten_java PreToolUse hook."""
from __future__ import annotations

import unittest

import guard_no_handwritten_java as g


class IsGeneratedJavaTest(unittest.TestCase):
    def test_matches_unix_path(self) -> None:
        self.assertTrue(g.is_generated_java("build/p/src/test/java/SHOP_X_003.java"))

    def test_matches_windows_path(self) -> None:
        self.assertTrue(g.is_generated_java(r"build\p\src\test\java\SHOP_X_003.java"))

    def test_matches_nested_package(self) -> None:
        self.assertTrue(g.is_generated_java("src/test/java/com/acme/Sim.java"))

    def test_rejects_resources_csv(self) -> None:
        self.assertFalse(g.is_generated_java("src/test/resources/terms.csv"))

    def test_rejects_java_outside_test_tree(self) -> None:
        self.assertFalse(g.is_generated_java("src/main/java/App.java"))

    def test_rejects_scenario_yaml(self) -> None:
        self.assertFalse(g.is_generated_java("scenarios/SHOP/x-003/scenario.yaml"))


class JavaTargetsFromPayloadTest(unittest.TestCase):
    def test_extracts_from_tool_input(self) -> None:
        payload = {"tool_input": {"file_path": "p/src/test/java/A.java"}}
        self.assertEqual(g.java_targets_from_payload(payload), ["p/src/test/java/A.java"])

    def test_ignores_non_java(self) -> None:
        payload = {"tool_input": {"file_path": "README.md"}}
        self.assertEqual(g.java_targets_from_payload(payload), [])

    def test_walks_nested_payload(self) -> None:
        payload = {"a": {"b": ["x/src/test/java/B.java"]}}
        self.assertEqual(g.java_targets_from_payload(payload), ["x/src/test/java/B.java"])


class EnforcingTest(unittest.TestCase):
    def test_default_off(self) -> None:
        self.assertFalse(g.enforcing({}))

    def test_on_when_flag_set(self) -> None:
        self.assertTrue(g.enforcing({"GIGACODE_ENFORCE": "1"}))

    def test_truthy_words(self) -> None:
        self.assertTrue(g.enforcing({"GIGACODE_ENFORCE": "true"}))
        self.assertTrue(g.enforcing({"GIGACODE_ENFORCE": "ON"}))

    def test_off_when_flag_zero(self) -> None:
        self.assertFalse(g.enforcing({"GIGACODE_ENFORCE": "0"}))


if __name__ == "__main__":
    unittest.main()

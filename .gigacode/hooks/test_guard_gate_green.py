#!/usr/bin/env python3
"""Unit tests for the guard_gate_green Stop hook."""
from __future__ import annotations

import unittest

import guard_gate_green as g


class PassingTest(unittest.TestCase):
    def test_passed_is_green(self) -> None:
        self.assertTrue(g.passing("passed"))

    def test_passed_with_warnings_is_green(self) -> None:
        self.assertTrue(g.passing("passed_with_warnings"))

    def test_blocked_is_not_green(self) -> None:
        self.assertFalse(g.passing("blocked"))

    def test_none_is_not_green(self) -> None:
        self.assertFalse(g.passing(None))


class ShouldBlockTest(unittest.TestCase):
    def test_no_scenarios_never_blocks(self) -> None:
        self.assertFalse(g.should_block([], None, None))
        self.assertFalse(g.should_block([], 100.0, "passed"))

    def test_missing_report_blocks(self) -> None:
        self.assertTrue(g.should_block([100.0], None, None))

    def test_stale_report_blocks(self) -> None:
        self.assertTrue(g.should_block([200.0, 50.0], 100.0, "passed"))

    def test_fresh_passed_does_not_block(self) -> None:
        self.assertFalse(g.should_block([100.0], 200.0, "passed"))

    def test_fresh_passed_with_warnings_does_not_block(self) -> None:
        self.assertFalse(g.should_block([100.0], 200.0, "passed_with_warnings"))

    def test_fresh_blocked_blocks(self) -> None:
        self.assertTrue(g.should_block([100.0], 200.0, "blocked"))

    def test_fresh_unknown_status_blocks(self) -> None:
        self.assertTrue(g.should_block([100.0], 200.0, None))

    def test_equal_mtime_passed_does_not_block(self) -> None:
        self.assertFalse(g.should_block([100.0], 100.0, "passed"))


class DecideTest(unittest.TestCase):
    def test_allow_when_not_blocking(self) -> None:
        self.assertEqual(g.decide(False, 0, 3), "allow")

    def test_block_under_limit(self) -> None:
        self.assertEqual(g.decide(True, 0, 3), "block")
        self.assertEqual(g.decide(True, 2, 3), "block")

    def test_advisory_at_limit(self) -> None:
        self.assertEqual(g.decide(True, 3, 3), "advisory")

    def test_advisory_over_limit(self) -> None:
        self.assertEqual(g.decide(True, 5, 3), "advisory")


class EnforcingAndLimitTest(unittest.TestCase):
    def test_enforcing_default_off(self) -> None:
        self.assertFalse(g.enforcing({}))

    def test_enforcing_on(self) -> None:
        self.assertTrue(g.enforcing({"GIGACODE_ENFORCE": "1"}))

    def test_limit_default(self) -> None:
        self.assertEqual(g.block_limit({}), 3)

    def test_limit_from_env(self) -> None:
        self.assertEqual(g.block_limit({"GIGACODE_ENFORCE_MAX": "5"}), 5)

    def test_limit_invalid_falls_back(self) -> None:
        self.assertEqual(g.block_limit({"GIGACODE_ENFORCE_MAX": "nope"}), 3)


if __name__ == "__main__":
    unittest.main()

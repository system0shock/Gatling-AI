#!/usr/bin/env python3
"""Unit tests for the gate_reminder Stop hook."""
from __future__ import annotations

import unittest

import gate_reminder


class NeedsReminderTest(unittest.TestCase):
    def test_no_scenarios_never_reminds(self) -> None:
        self.assertFalse(gate_reminder.needs_reminder([], None))
        self.assertFalse(gate_reminder.needs_reminder([], 100.0))

    def test_missing_report_reminds(self) -> None:
        self.assertTrue(gate_reminder.needs_reminder([100.0], None))

    def test_stale_report_reminds(self) -> None:
        self.assertTrue(gate_reminder.needs_reminder([200.0, 50.0], 100.0))

    def test_fresh_report_does_not_remind(self) -> None:
        self.assertFalse(gate_reminder.needs_reminder([100.0], 200.0))

    def test_equal_mtime_does_not_remind(self) -> None:
        self.assertFalse(gate_reminder.needs_reminder([100.0], 100.0))


if __name__ == "__main__":
    unittest.main()

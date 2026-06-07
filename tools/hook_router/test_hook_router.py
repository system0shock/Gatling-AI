#!/usr/bin/env python3
"""Unit tests for the hook router MVP."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import hook_router


class HookRouterTest(unittest.TestCase):
    FIXTURES = Path(__file__).parent / "test_configs"

    def test_dry_run_matches_yaml_post_tool_use(self) -> None:
        config = self.FIXTURES / "dry_run_hooks.json"
        event = {
            "event_name": "PostToolUse",
            "changed_files": ["examples/scenarios/login-and-search.yaml"],
        }

        summary = hook_router.route_event(event, config, dry_run=True)

        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["matched_rules"], ["scenario-lint"])
        self.assertEqual(len(summary["commands"]), 1)
        self.assertIn("login-and-search.yaml", " ".join(summary["commands"][0]["argv"]))
        self.assertTrue(summary["commands"][0]["dry_run"])

    def test_dry_run_matches_general_java_post_tool_use(self) -> None:
        config = Path(__file__).parent / "hooks.json"
        event = {
            "event_name": "PostToolUse",
            "changed_files": ["src/Foo.java"],
        }

        summary = hook_router.route_event(event, config, dry_run=True)

        self.assertEqual(summary["status"], "passed")
        self.assertIn("quality-gate-code-post-tool-use", summary["matched_rules"])

    def test_dry_run_matches_root_build_files_post_tool_use(self) -> None:
        config = Path(__file__).parent / "hooks.json"

        for build_file in ("pom.xml", "build.gradle", "build.gradle.kts"):
            with self.subTest(build_file=build_file):
                event = {
                    "event_name": "PostToolUse",
                    "changed_files": [build_file],
                }

                summary = hook_router.route_event(event, config, dry_run=True)

                self.assertEqual(summary["status"], "passed")
                self.assertIn("quality-gate-code-post-tool-use", summary["matched_rules"])

    def test_prompt_regex_runs_quality_gate_command(self) -> None:
        config = self.FIXTURES / "prompt_hooks.json"

        summary = hook_router.route_event({"message": "готово"}, config)

        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["commands"][0]["returncode"], 0)

    def test_blocking_command_failure_blocks(self) -> None:
        config = self.FIXTURES / "blocking_hooks.json"

        summary = hook_router.route_event({"hook_event": "Stop"}, config)

        self.assertEqual(summary["status"], "blocked")
        self.assertEqual(summary["commands"][0]["returncode"], 3)


if __name__ == "__main__":
    sys.exit(unittest.main())

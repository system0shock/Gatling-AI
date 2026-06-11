#!/usr/bin/env python3
"""Unit tests for the hook router MVP."""

from __future__ import annotations

import json
import sys
import unittest
from contextlib import chdir
from pathlib import Path
from unittest.mock import patch

import hook_router


class HookRouterTest(unittest.TestCase):
    FIXTURES = Path(__file__).parent / "test_configs"

    def test_dry_run_matches_yaml_post_tool_use(self) -> None:
        config = self.FIXTURES / "dry_run_hooks.json"
        event = {
            "event_name": "PostToolUse",
            "changed_files": ["examples/scenarios/SHOP/login-and-search-002/scenario.yaml"],
        }

        summary = hook_router.route_event(event, config, dry_run=True)

        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["matched_rules"], ["scenario-lint"])
        self.assertEqual(len(summary["commands"]), 1)
        self.assertIn(
            "examples/scenarios/SHOP/login-and-search-002/scenario.yaml",
            " ".join(summary["commands"][0]["argv"]),
        )
        self.assertTrue(summary["commands"][0]["dry_run"])

    def test_cwd_relative_changed_file_matches_yaml_post_tool_use(self) -> None:
        config = self.FIXTURES / "dry_run_hooks.json"
        event = {
            "event_name": "PostToolUse",
            "cwd": "examples/scenarios/SHOP/login-and-search-002",
            "changed_files": ["scenario.yaml"],
        }

        summary = hook_router.route_event(event, config, dry_run=True)

        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["matched_rules"], ["scenario-lint"])
        self.assertEqual(
            summary["event"]["files"],
            ["examples/scenarios/SHOP/login-and-search-002/scenario.yaml"],
        )

    def test_missing_cwd_defaults_to_repo_root_from_non_root_process_cwd(self) -> None:
        config = self.FIXTURES / "dry_run_hooks.json"
        event = {
            "event_name": "PostToolUse",
            "changed_files": ["examples/scenarios/SHOP/login-and-search-002/scenario.yaml"],
        }

        with chdir(Path(__file__).parent):
            summary = hook_router.route_event(event, config, dry_run=True)

        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["matched_rules"], ["scenario-lint"])
        self.assertEqual(
            summary["event"]["files"],
            ["examples/scenarios/SHOP/login-and-search-002/scenario.yaml"],
        )

    def test_canonicalized_parent_path_outside_scenario_dir_does_not_match_yaml_route(self) -> None:
        config = self.FIXTURES / "dry_run_hooks.json"
        event = {
            "event_name": "PostToolUse",
            "changed_files": ["examples/scenarios/../outside.yaml"],
        }

        summary = hook_router.route_event(event, config, dry_run=True)

        self.assertEqual(summary["status"], "no_match")
        self.assertEqual(summary["matched_rules"], [])
        self.assertEqual(summary["event"]["files"], ["examples/outside.yaml"])

    def test_conflicting_event_aliases_resolve_valid_event_name(self) -> None:
        config = self.FIXTURES / "dry_run_hooks.json"
        event = {
            "event": {"type": "PostToolUse"},
            "event_name": "PostToolUse",
            "changed_files": ["examples/scenarios/SHOP/login-and-search-002/scenario.yaml"],
        }

        original_field_event = hook_router.FIELD_EVENT
        try:
            hook_router.FIELD_EVENT = ["event", "event_name", "hook_event"]  # type: ignore[assignment]
            summary = hook_router.route_event(event, config, dry_run=True)
        finally:
            hook_router.FIELD_EVENT = original_field_event

        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["event"]["event"], "PostToolUse")
        self.assertEqual(summary["matched_rules"], ["scenario-lint"])

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

    def test_unknown_placeholder_blocks_before_command_execution_in_dry_run(self) -> None:
        config = self.FIXTURES / "unknown_placeholder_hooks.json"

        summary = hook_router.route_event({"hook_event": "Stop"}, config, dry_run=True)

        self.assertEqual(summary["status"], "blocked")
        self.assertEqual(summary["matched_rules"], ["unknown-placeholder"])
        self.assertEqual(len(summary["commands"]), 1)
        self.assertEqual(summary["commands"][0]["returncode"], 127)
        self.assertIn("unknown placeholder {missing}", summary["commands"][0]["stderr"])
        self.assertNotIn("argv", summary["commands"][0])

    def test_collect_paths_keeps_all_path_like_keys(self) -> None:
        value = {"path": "a.yaml", "file": "b.yaml"}
        self.assertEqual(sorted(hook_router.collect_paths(value)), ["a.yaml", "b.yaml"])

    def test_missing_scenario_placeholder_blocks_with_config_error(self) -> None:
        config = self.FIXTURES / "missing_scenario_hooks.json"

        summary = hook_router.route_event({"hook_event": "Stop"}, config, dry_run=True)

        self.assertEqual(summary["status"], "blocked")
        self.assertIn("placeholder {scenario} has no value", summary["commands"][0]["stderr"])

    def test_literal_scenario_text_does_not_trigger_path_iteration(self) -> None:
        action = {"commands": [["echo", "text {scenario} text"]], "scenario": "fixed.yaml"}
        scenarios = hook_router.command_scenarios(action, {}, ["a.yaml", "b.yaml"])
        self.assertEqual(scenarios, ["fixed.yaml"])

    def test_placeholder_in_args_with_matched_paths_iterates(self) -> None:
        action = {"commands": [["lint", "{scenario}"]]}
        scenarios = hook_router.command_scenarios(action, {}, ["a.yaml", "b.yaml"])
        self.assertEqual(scenarios, ["a.yaml", "b.yaml"])

    def test_event_json_file_with_utf8_bom_parses(self) -> None:
        event = {
            "event_name": "PostToolUse",
            "changed_files": ["examples/scenarios/SHOP/login-and-search-002/scenario.yaml"],
        }
        encoded = json.dumps(event)

        def read_text(_path: Path, encoding: str) -> str:
            if encoding == "utf-8-sig":
                return encoded
            return f"\ufeff{encoded}"

        args = hook_router.parse_args(["--event-json", "event.json"])
        with patch.object(Path, "read_text", read_text):
            loaded = hook_router.load_event(args)

        self.assertEqual(loaded, event)


if __name__ == "__main__":
    sys.exit(unittest.main())

#!/usr/bin/env python3
"""Unit tests for the scenario Markdown renderer."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import scenario_renderer

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_SCENARIO = REPO_ROOT / "examples" / "scenarios" / "login-and-search.yaml"


class RendererTest(unittest.TestCase):
    def render(self) -> str:
        document = scenario_renderer.load_yaml(GOLDEN_SCENARIO)
        return scenario_renderer.render_markdown(
            document,
            "examples/scenarios/login-and-search.yaml",
            scenario_renderer.source_digest(GOLDEN_SCENARIO),
        )

    def test_header_marks_generated_artifact(self) -> None:
        content = self.render()
        self.assertIn("login-and-search.yaml", content.splitlines()[2])
        self.assertIn("Не редактировать вручную", content)

    def test_steps_table_lists_transactions(self) -> None:
        content = self.render()
        self.assertIn("01 auth.open-login - Open login page", content)
        self.assertIn("| POST | /login |", content)

    def test_correlations_table_tracks_csrf(self) -> None:
        content = self.render()
        self.assertIn("csrf", content)
        self.assertIn("извлекается в шаге `open-login`", content)

    def test_sla_section_lists_assertions(self) -> None:
        content = self.render()
        self.assertIn("global.responseTime.p95", content)
        self.assertIn("< 800", content)

    def test_render_is_deterministic(self) -> None:
        self.assertEqual(self.render(), self.render())


if __name__ == "__main__":
    sys.exit(unittest.main())

#!/usr/bin/env python3
"""Structural guard tests for the .gigacode package."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

GIGACODE = Path(__file__).resolve().parent
REPO_ROOT = GIGACODE.parent

FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


def frontmatter(text: str) -> str | None:
    m = FRONTMATTER.match(text)
    return m.group(1) if m else None


class SkillFrontmatterTest(unittest.TestCase):
    def test_all_skills_have_name_and_description(self) -> None:
        skill_files = sorted((GIGACODE / "skills").glob("*/SKILL.md"))
        self.assertEqual(len(skill_files), 5, "expected exactly 5 skills")
        for path in skill_files:
            fm = frontmatter(path.read_text(encoding="utf-8"))
            self.assertIsNotNone(fm, f"{path} is missing YAML frontmatter")
            self.assertRegex(fm, r"(?m)^name:\s*\S+", f"{path} missing name")
            self.assertRegex(fm, r"(?m)^description:\s*\S+", f"{path} missing description")


class SettingsTest(unittest.TestCase):
    def test_settings_valid_and_hooks_wired(self) -> None:
        import json
        data = json.loads((GIGACODE / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(data["context"]["fileName"], ["GIGACODE.md"])
        for event_groups in data["hooks"].values():
            for group in event_groups:
                for hook in group["hooks"]:
                    self.assertEqual(hook["type"], "command")
                    script = hook["command"].split()[-1]
                    self.assertTrue((REPO_ROOT / script).exists(), f"missing hook script {script}")


class AgentFrontmatterTest(unittest.TestCase):
    def test_validator_subagent_frontmatter(self) -> None:
        fm = frontmatter((GIGACODE / "agents" / "validator-subagent.md").read_text(encoding="utf-8"))
        self.assertIsNotNone(fm, "validator-subagent.md missing frontmatter")
        self.assertRegex(fm, r"(?m)^name:\s*validator-subagent")
        self.assertRegex(fm, r"(?m)^description:\s*\S+")


if __name__ == "__main__":
    unittest.main()

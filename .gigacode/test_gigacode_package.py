#!/usr/bin/env python3
"""Structural guard tests for the .gigacode package."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

GIGACODE = Path(__file__).resolve().parent
REPO_ROOT = GIGACODE.parent

FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
REQUIRED_SKILLS = {
    "convert-from-jmeter",
    "document-legacy-jmeter",
    "quality-gate",
    "scenario-from-docs",
    "scenario-to-gatling",
}
REQUIRED_AGENTS = {
    "validator-subagent",
    "mnt-module-inspector",
    "mnt-confluence-researcher",
    "mnt-evidence-reconciler",
}


def frontmatter(text: str) -> str | None:
    m = FRONTMATTER.match(text)
    return m.group(1) if m else None


def skill_names() -> set[str]:
    names = set()
    for path in (GIGACODE / "skills").glob("*/SKILL.md"):
        fm = frontmatter(path.read_text(encoding="utf-8")) or ""
        match = re.search(r"(?m)^name:\s*(\S+)", fm)
        if match:
            names.add(match.group(1))
    return names


def agent_names() -> set[str]:
    names = set()
    for path in (GIGACODE / "agents").glob("*.md"):
        fm = frontmatter(path.read_text(encoding="utf-8")) or ""
        match = re.search(r"(?m)^name:\s*(\S+)", fm)
        if match:
            names.add(match.group(1))
    return names


class SkillFrontmatterTest(unittest.TestCase):
    def test_all_skills_have_name_and_description(self) -> None:
        skill_files = sorted((GIGACODE / "skills").glob("*/SKILL.md"))
        for path in skill_files:
            fm = frontmatter(path.read_text(encoding="utf-8"))
            self.assertIsNotNone(fm, f"{path} is missing YAML frontmatter")
            self.assertRegex(fm, r"(?m)^name:\s*\S+", f"{path} missing name")
            self.assertRegex(fm, r"(?m)^description:\s*\S+", f"{path} missing description")

    def test_required_skills_exist(self) -> None:
        self.assertTrue(REQUIRED_SKILLS <= skill_names())


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
    def test_required_agents_exist(self) -> None:
        self.assertFalse(REQUIRED_AGENTS - agent_names(), f"missing required agents: {sorted(REQUIRED_AGENTS - agent_names())}")

    def test_collectors_disallow_write_and_edit_tools(self) -> None:
        for path in (GIGACODE / "agents").glob("mnt-*.md"):
            fm = frontmatter(path.read_text(encoding="utf-8")) or ""
            name = re.search(r"(?m)^name:\s*(\S+)", fm)
            if name and re.fullmatch(r"mnt-.*(?:researcher|inspector)", name.group(1)):
                self.assertRegex(fm, r"(?m)^\s*-\s*write_file\s*$", f"{path} must disallow write_file")
                self.assertRegex(fm, r"(?m)^\s*-\s*edit\s*$", f"{path} must disallow edit")


class CommandFrontmatterTest(unittest.TestCase):
    def test_quality_gate_command_frontmatter(self) -> None:
        fm = frontmatter((GIGACODE / "commands" / "quality-gate.md").read_text(encoding="utf-8"))
        self.assertIsNotNone(fm, "quality-gate.md missing frontmatter")
        self.assertRegex(fm, r"(?m)^description:\s*\S+")


class ContextFileTest(unittest.TestCase):
    def test_context_file_exists(self) -> None:
        self.assertTrue((REPO_ROOT / "GIGACODE.md").exists(), "GIGACODE.md missing at repo root")


if __name__ == "__main__":
    unittest.main()

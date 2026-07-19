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
    "mnt-author",
}
REQUIRED_METHODOLOGY_HEADINGS = (
    "Паспорт документа",
    "Назначение и область тестирования",
    "Описание системы и функциональности",
    "Архитектура",
    "Реестр интеграций",
    "Реестр тестируемых интерфейсов",
    "Пользовательские и технические потоки",
    "Модель нагрузки",
    "Виды тестов",
    "SLA, SLO и критерии приемки",
    "Тестовый стенд",
    "Требования к тестовым данным",
    "Наблюдаемость и диагностика",
    "Порядок проведения тестов",
    "Риски, ограничения и допущения",
    "Артефакты и отчетность",
    "Актуализация методики",
)
STANDARD_COLLECTOR_TOOLS = {
    "read_file",
    "read_many_files",
    "glob",
    "grep_search",
    "run_shell_command",
}


def frontmatter(text: str) -> str | None:
    m = FRONTMATTER.match(text)
    return m.group(1) if m else None


def frontmatter_list(frontmatter_text: str, key: str) -> list[str]:
    """Read one YAML-style scalar list without matching neighboring sections."""
    lines = frontmatter_text.splitlines()
    for index, line in enumerate(lines):
        if line == f"{key}:":
            values = []
            for item in lines[index + 1:]:
                if item and not item[0].isspace():
                    break
                match = re.fullmatch(r"\s*-\s*(\S+)\s*", item)
                if match:
                    values.append(match.group(1))
            return values
    return []


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

    def test_manage_methodology_has_ordered_approval_gates(self) -> None:
        skill = (GIGACODE / "skills" / "manage-methodology" / "SKILL.md").read_text(encoding="utf-8")
        lower = skill.lower()
        workflow = lower[lower.index('## ordered workflow'):]
        markers = (
            "workspace preview approval", "workspace.candidate.yaml", "show exact workspace diff",
            "record-approval", "apply", "workspace-snapshot.json", "fresh subagents",
            "aggregate and reconcile", "gap approval", "six artifact paths", "quality gate",
            "mnt-validator", "show exact diff", "methodology-patch", "post-apply quality gate",
            "confluence remains unchanged",
        )
        for marker in markers:
            self.assertIn(marker, workflow)
        ordered = (
            "workspace preview approval", "workspace.candidate.yaml", "show exact workspace diff",
            "workspace-manifest approval", "workspace-snapshot.json", "fresh subagents",
            "aggregate and reconcile", "gap approval", "six artifact paths", "quality gate",
            "mnt-validator", "show exact mnt diff", "second explicit methodology approval",
            "record-approval methodology-patch", "apply methodology-patch", "post-apply quality gate",
        )
        positions = [workflow.index(marker) for marker in ordered]
        self.assertEqual(positions, sorted(positions), "workflow gates must be ordered")

    def test_manage_methodology_requires_independent_snapshot_and_envelope_handoffs(self) -> None:
        skill = (GIGACODE / "skills" / "manage-methodology" / "SKILL.md").read_text(encoding="utf-8").lower()
        self.assertIn("independently validated workspace snapshot", skill)
        self.assertIn("only compact json envelopes", skill)
        self.assertIn("unless a blocker requires artifact detail", skill)
        self.assertIn("confluence researcher and per-module inspectors in parallel", skill)
        self.assertIn("no concrete confluence mcp tool names", skill)


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
    def test_all_agents_have_name_and_description(self) -> None:
        for path in sorted((GIGACODE / "agents").glob("*.md")):
            fm = frontmatter(path.read_text(encoding="utf-8"))
            self.assertIsNotNone(fm, f"{path} is missing YAML frontmatter")
            self.assertRegex(fm, r"(?m)^name:\s*\S+", f"{path} missing name")
            self.assertRegex(fm, r"(?m)^description:\s*\S+", f"{path} missing description")

    def test_required_agents_exist(self) -> None:
        self.assertFalse(REQUIRED_AGENTS - agent_names(), f"missing required agents: {sorted(REQUIRED_AGENTS - agent_names())}")

    def test_collectors_disallow_write_and_edit_tools(self) -> None:
        for path in (GIGACODE / "agents").glob("mnt-*.md"):
            fm = frontmatter(path.read_text(encoding="utf-8")) or ""
            name = re.search(r"(?m)^name:\s*(\S+)", fm)
            if name and re.fullmatch(r"mnt-.*(?:researcher|inspector)", name.group(1)):
                disallowed = frontmatter_list(fm, "disallowedTools")
                self.assertIn("write_file", disallowed, f"{path} must disallow write_file")
                self.assertIn("edit", disallowed, f"{path} must disallow edit")

    def test_mnt_author_disallows_general_write_and_edit_tools(self) -> None:
        path = GIGACODE / "agents" / "mnt-author.md"
        text = path.read_text(encoding="utf-8")
        fm = frontmatter(text) or ""
        disallowed = frontmatter_list(fm, "disallowedTools")
        self.assertIn("write_file", disallowed, f"{path} must disallow write_file")
        self.assertIn("edit", disallowed, f"{path} must disallow edit")
        self.assertIn("explicitly scoped run-directory mechanism", text)
        self.assertIn("only under the supplied run directory", text)
        self.assertIn("six supplied input artifacts", text)
        self.assertIn("workspace-snapshot.json", text)
        self.assertIn("snapshot_id", text)

    def test_mnt_validator_is_read_only_and_independently_cross_checks_inputs(self) -> None:
        path = GIGACODE / "agents" / "mnt-validator.md"
        text = path.read_text(encoding="utf-8")
        fm = frontmatter(text) or ""
        disallowed = frontmatter_list(fm, "disallowedTools")
        self.assertIn("write_file", disallowed)
        self.assertIn("edit", disallowed)
        self.assertNotIn("write_file", frontmatter_list(fm, "tools"))
        self.assertNotIn("edit", frontmatter_list(fm, "tools"))
        for input_name in (
            "methodology.candidate.md", "methodology-quality-report.json", "methodology-gaps.md",
            "methodology-source-map.json", "patch descriptor", "resolved-evidence.json",
            "workspace-snapshot.json",
        ):
            self.assertIn(input_name, text)
        self.assertIn("accept|blocked", text)
        self.assertIn("missing or non-green", text)
        self.assertIn("claims absent from evidence", text)
        self.assertIn("never apply", text.lower())

    def test_phase_3c_plan_requires_all_six_author_inputs_and_snapshot_map_identity(self) -> None:
        plan = (REPO_ROOT / "docs" / "superpowers" / "plans" / "2026-07-19-methodology-3c-authoring-approval.md").read_text(encoding="utf-8")
        self.assertIn("exactly six supplied artifact paths", plan)
        self.assertIn("`workspace-snapshot.json`", plan)
        self.assertIn('"workspace_snapshot"', plan)
        self.assertIn('"snapshot_id": "<64 lowercase hex from workspace-snapshot.json>"', plan)
        self.assertIn('"fresh": true', plan)
    def test_module_inspector_consumes_selected_inline_snapshot_job(self) -> None:
        text = (GIGACODE / "agents" / "mnt-module-inspector.md").read_text(encoding="utf-8")
        self.assertIn("selected inline `inspector_jobs[]` object", text)
        self.assertIn("snapshot path/context", text)
        self.assertNotIn("job file", text)

    def test_confluence_researcher_uses_standard_shell_artifact_handoff(self) -> None:
        path = GIGACODE / "agents" / "mnt-confluence-researcher.md"
        text = path.read_text(encoding="utf-8")
        fm = frontmatter(text) or ""
        self.assertEqual(set(frontmatter_list(fm, "tools")), STANDARD_COLLECTOR_TOOLS)
        self.assertIn("only new `confluence-snapshot.json`", text)
        self.assertIn("UTF-8", text)
        self.assertNotIn("confluence_search", fm)
        self.assertNotIn("confluence_get_page", fm)


class CommandFrontmatterTest(unittest.TestCase):
    def test_manage_methodology_command_delegates_without_approval_bypass(self) -> None:
        path = GIGACODE / "commands" / "manage-methodology.md"
        text = path.read_text(encoding="utf-8")
        fm = frontmatter(text) or ""
        self.assertEqual(
            re.search(r"(?m)^description:\s*(.+)$", fm).group(1),
            "Создать или обновить системную МНТ через обнаружение рабочего пространства, сверку доказательств, проверку качества, точный diff и явное локальное подтверждение.",
        )
        self.assertIn("manage-methodology", text)
        self.assertIn("never skips approval", text.lower())

    def test_quality_gate_command_frontmatter(self) -> None:
        fm = frontmatter((GIGACODE / "commands" / "quality-gate.md").read_text(encoding="utf-8"))
        self.assertIsNotNone(fm, "quality-gate.md missing frontmatter")
        self.assertRegex(fm, r"(?m)^description:\s*\S+")


class MethodologyTemplateTest(unittest.TestCase):
    def test_methodology_template_has_all_headings(self) -> None:
        template = (
            GIGACODE
            / "skills"
            / "manage-methodology"
            / "templates"
            / "methodology-template.md"
        ).read_text(encoding="utf-8")
        for heading in REQUIRED_METHODOLOGY_HEADINGS:
            self.assertIn(f"## {heading}", template)


class ContextFileTest(unittest.TestCase):
    def test_context_file_exists(self) -> None:
        self.assertTrue((REPO_ROOT / "GIGACODE.md").exists(), "GIGACODE.md missing at repo root")

    def test_confluence_host_overlay_is_documented(self) -> None:
        for path in (GIGACODE / "README.md", REPO_ROOT / "GIGACODE.md"):
            text = path.read_text(encoding="utf-8")
            self.assertIn("host overlay", text, f"{path} must document the host overlay")
            self.assertIn("blocked", text, f"{path} must describe unavailable read capability")


    def test_docs_describe_two_distinct_local_approvals_and_no_publish(self) -> None:
        for path in (GIGACODE / "README.md", REPO_ROOT / "GIGACODE.md", REPO_ROOT / "docs" / "METHODOLOGY.md"):
            text = path.read_text(encoding="utf-8").lower()
            self.assertIn("workspace-manifest", text, f"{path} must document manifest approval")
            self.assertIn("methodology-patch", text, f"{path} must document methodology approval")
            self.assertIn("confluence", text, f"{path} must retain the no-publish boundary")
            if path == GIGACODE / 'README.md':
                self.assertNotIn('`n', text, f"{path} must not contain a literal newline escape")
    def test_windows_authoring_fixture_residue_is_narrowly_ignored(self) -> None:
        ignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("Windows-local authoring test residue", ignore)
        self.assertIn("tools/methodology_authoring/.test-fixtures/", ignore)
        self.assertIn("Windows-local methodology quality-gate test residue", ignore)
        self.assertIn("tools/methodology_quality_gate/.test-fixtures/", ignore)
if __name__ == "__main__":
    unittest.main()

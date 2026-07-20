#!/usr/bin/env python3
"""Structural guard tests for the .gigacode package."""
from __future__ import annotations

from argparse import Namespace
import re
import shlex
import sys
import unittest
from pathlib import Path

GIGACODE = Path(__file__).resolve().parent
REPO_ROOT = GIGACODE.parent
sys.path.insert(0, str(REPO_ROOT / "tools" / "methodology_authoring"))
import methodology_authoring as authoring

FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
REQUIRED_SKILLS = {
    "convert-from-jmeter",
    "document-legacy-jmeter",
    "quality-gate",
    "scenario-from-docs",
    "scenario-to-gatling",
    "manage-methodology",
}
REQUIRED_AGENTS = {
    "validator-subagent",
    "mnt-module-inspector",
    "mnt-confluence-researcher",
    "mnt-confluence-publisher",
    "mnt-evidence-reconciler",
    "mnt-author",
    "mnt-validator",
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


LIFECYCLE_COMMANDS = {
    "workspace-prepare": "prepare",
    "workspace-record": "record-approval",
    "workspace-apply": "apply",
    "methodology-prepare": "prepare",
    "methodology-record": "record-approval",
    "methodology-apply": "apply",
}
CLI_COMMAND_PREFIX = ["python", "tools/methodology_authoring/methodology_authoring.py"]


def parse_labelled_lifecycle_invocations(skill: str) -> dict[str, Namespace]:
    """Parse each labelled documented CLI command into its argparse namespace."""
    parser = authoring.build_parser()
    parsed = {}
    for label, command in LIFECYCLE_COMMANDS.items():
        match = re.search(rf"<!-- cli: {label} -->\n`([^`]+)`", skill)
        if match is None:
            raise AssertionError(f"missing documented {label} invocation")
        tokens = shlex.split(match.group(1))
        if tokens[:2] != CLI_COMMAND_PREFIX:
            raise AssertionError(f"{label} must invoke the methodology authoring CLI")
        invocation = parser.parse_args(tokens[2:])
        if invocation.command != command:
            raise AssertionError(f"{label} must invoke {command}")
        parsed[label] = invocation
    return parsed

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

    def test_manage_methodology_enforces_transaction_scoped_order(self) -> None:
        skill = (GIGACODE / "skills" / "manage-methodology" / "SKILL.md").read_text(encoding="utf-8")
        workspace = re.sub(r"\s+", " ", skill[skill.index("### 1. Workspace preview approval"):skill.index("### 5. Collect evidence in parallel")].lower())
        workspace_gates = (
            "workspace preview approval",
            "prepare --kind workspace-manifest",
            "show exact workspace diff",
            "wait for explicit workspace-manifest approval",
            "cli: workspace-record",
            "cli: workspace-apply",
            "workspace-snapshot.json",
        )
        self.assertEqual([workspace.index(gate) for gate in workspace_gates], sorted(workspace.index(gate) for gate in workspace_gates))

        methodology = re.sub(r"\s+", " ", skill[skill.index("### 8. Bounded candidate authoring"):skill.index("### 16. Close the local run")].lower())
        methodology_gates = (
            "mnt-author",
            "cli: methodology-prepare",
            "quality gate",
            "mnt-validator",
            "change-summary.md",
            "warnings",
            "show exact mnt diff",
            "wait for explicit methodology-patch approval",
            "cli: methodology-record",
            "cli: methodology-apply",
            "post-apply quality gate",
        )
        self.assertEqual([methodology.index(gate) for gate in methodology_gates], sorted(methodology.index(gate) for gate in methodology_gates))
        self.assertEqual(skill.count("<!-- cli: methodology-prepare -->"), 1)
        self.assertIn("same unchanged patch and descriptor", methodology)
        for forbidden in ("skip approval", "bypass approval", "continue on blocked"):
            self.assertNotIn(forbidden, skill.lower())

    def test_manage_methodology_passes_exact_author_inputs_and_envelope_boundaries(self) -> None:
        skill = (GIGACODE / "skills" / "manage-methodology" / "SKILL.md").read_text(encoding="utf-8").lower()
        authoring = skill[skill.index("### 8. bounded candidate authoring"):skill.index("### 9. prepare the exact methodology patch and descriptor")]
        for input_name in (
            "template", "current methodology", "resolved-evidence.json",
            "manual-confirmations.json", "section-coverage.json", "workspace-snapshot.json",
        ):
            self.assertIn(input_name, authoring)
        self.assertIn("six artifact paths", authoring)
        self.assertIn("independently validated workspace snapshot", authoring)
        self.assertIn("only compact json envelopes", skill)
        self.assertIn("unless a blocker requires artifact detail", skill)
        self.assertIn("confluence researcher and per-module inspectors in parallel", skill)
        self.assertIn("no concrete confluence mcp tool names", skill)
    def test_manage_methodology_examples_parse_with_authoring_cli(self) -> None:
        skill = (GIGACODE / "skills" / "manage-methodology" / "SKILL.md").read_text(encoding="utf-8")
        parsed = parse_labelled_lifecycle_invocations(skill)
        self.assertEqual(parsed["workspace-prepare"].kind, "workspace-manifest")
        self.assertEqual(parsed["methodology-prepare"].kind, "methodology-patch")
        for label in ("workspace-record", "workspace-apply", "methodology-record", "methodology-apply"):
            self.assertFalse(hasattr(parsed[label], "kind"), f"{label} must derive kind from its descriptor or approval")
        self.assertIn("descriptor carries the approved kind", re.sub(r"\s+", " ", skill.lower()))

    def test_methodology_lifecycle_reuses_exact_parsed_operands(self) -> None:
        skill = (GIGACODE / "skills" / "manage-methodology" / "SKILL.md").read_text(encoding="utf-8")
        parsed = parse_labelled_lifecycle_invocations(skill)
        prepare = parsed["methodology-prepare"]
        record = parsed["methodology-record"]
        apply = parsed["methodology-apply"]

        self.assertEqual(prepare.out, record.descriptor)
        self.assertEqual(prepare.base, apply.base)
        self.assertEqual(prepare.candidate, apply.candidate)
        self.assertEqual(prepare.patch, apply.patch)
        self.assertEqual(record.out, apply.approval)
        self.assertEqual(prepare.load_test_root, record.load_test_root)
        self.assertEqual(record.load_test_root, apply.load_test_root)

        self.assertEqual(prepare.load_test_root, Path("<load-test-root>"))
        self.assertEqual(prepare.base, Path("<load-test-root>/methodology.md"))
        self.assertEqual(prepare.candidate, Path("<run-dir>/methodology.candidate.md"))
        self.assertEqual(prepare.patch, Path("<run-dir>/methodology.patch"))
        self.assertEqual(prepare.out, Path("<run-dir>/methodology-descriptor.json"))
        self.assertEqual(record.out, Path("<run-dir>/methodology-approval.json"))

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

    def test_mnt_validator_is_minimally_read_only_and_defers_byte_checks_to_apply(self) -> None:
        path = GIGACODE / "agents" / "mnt-validator.md"
        text = path.read_text(encoding="utf-8")
        fm = frontmatter(text) or ""
        self.assertEqual(frontmatter_list(fm, "tools"), ["read_file"])
        disallowed = frontmatter_list(fm, "disallowedTools")
        for forbidden in ("write_file", "edit", "run_shell_command"):
            self.assertIn(forbidden, disallowed)
            self.assertNotIn(forbidden, frontmatter_list(fm, "tools"))
        for input_name in (
            "methodology.candidate.md", "methodology-quality-report.json", "methodology-gaps.md",
            "methodology-source-map.json", "patch descriptor", "resolved-evidence.json",
            "workspace-snapshot.json",
        ):
            self.assertIn(input_name, text)
        self.assertIn("accept|blocked", text)
        self.assertIn("missing or non-green", re.sub(r"\s+", " ", text))
        self.assertIn("claims absent from evidence", text)
        self.assertIn("do not independently recompute hashes", re.sub(r"\s+", " ", text))
        self.assertIn("apply engine", text)
        self.assertNotIn("report_path", text)
        self.assertNotIn("mnt-validator-report", text)
        self.assertIn("pre-existing", text.lower())

    def test_mnt_publisher_is_the_only_confluence_writer(self) -> None:
        path = GIGACODE / "agents" / "mnt-confluence-publisher.md"
        self.assertTrue(path.is_file())
        text = path.read_text(encoding="utf-8").lower()
        normalized = re.sub(r"\s+", " ", text)
        for marker in (
            "read final local methodology",
            "fetch the same confirmed page id",
            "validate_publish",
            "stop without update",
            "host-supplied page-update capability",
            "return inline",
        ):
            self.assertIn(marker, text)
        self.assertIn("no concrete confluence mcp tool names", text)

        for marker in (
            "never search for",
            "never change a title, parent, label, permission",
            "never write repository files",
            "never retry after an ambiguous page-update result",
            "if either host-supplied capability is unavailable, return inline `blocked`",
            "a missing approval, changed local mnt, or changed confluence page version must",
            "stop without update",
        ):
            self.assertIn(marker, normalized)

        validation_command = (
            "python tools/methodology_publish/methodology_publish.py validate "
            "--methodology <load-test-root>/methodology.md "
            "--fresh-page-id <fresh-page-id> "
            "--fresh-page-version <fresh-page-version> "
            "--approval <run-dir>/publish-approval.json"
        )
        self.assertIn(validation_command, normalized)
        for marker in (
            "after host page-read",
            "before page-update",
            "require exit 0",
            "stop without update on nonzero",
            "must not use shell to write artifacts or publish",
        ):
            self.assertIn(marker, normalized)
    def test_only_publisher_requests_host_page_update_capability(self) -> None:
        for path in (GIGACODE / "agents").glob("*.md"):
            if path.name == "mnt-confluence-publisher.md":
                continue
            text = path.read_text(encoding="utf-8").lower()
            self.assertNotIn(
                "host-supplied page-update capability",
                text,
                f"{path} must not request the publisher capability",
            )


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
        for field in (
            "page_id",
            "version",
            "body_markdown",
            "fetched_at",
            "source_type",
            "reference",
        ):
            self.assertIn(field, text)
        self.assertIn("never returned in the chat envelope", text)
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


    def test_manage_methodology_publish_order_is_explicit(self) -> None:
        text = (GIGACODE / "skills" / "manage-methodology" / "SKILL.md").read_text(
            encoding="utf-8"
        ).lower()
        publish = text[text.index("## publish") :]
        markers = (
            "canonical methodology is green",
            "confirmed page snapshot",
            "prepare publish",
            "show confluence.patch",
            "wait for explicit publish approval",
            "record publish approval",
            "dispatch mnt-confluence-publisher",
        )
        positions = [publish.index(marker) for marker in markers]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn("selective refresh", publish)
        publish_flat = re.sub(r"\s+", " ", publish)

        for marker in (
            "confirmed page snapshot",
            "separate user action",
            "wait for explicit publish approval",
            "do not dispatch mnt-confluence-publisher without recorded publish approval",
            "stop before dispatching mnt-confluence-publisher",
        ):
            self.assertIn(marker, publish_flat)

    def test_local_close_is_scoped_before_publish_without_no_publish_contradiction(self) -> None:
        text = (GIGACODE / "skills" / "manage-methodology" / "SKILL.md").read_text(
            encoding="utf-8"
        ).lower()
        local_close = text[
            text.index("### 16. close the local run") : text.index("## publish")
        ]
        self.assertIn("create and update-local", local_close)
        self.assertIn("confluence remains unchanged", local_close)
        self.assertIn("no confluence write, comment, move, or publish operation", local_close)
        publish = text[text.index("## publish") :]
        self.assertNotIn("confluence remains unchanged", publish)
        self.assertNotIn("no confluence write, comment, move, or publish operation", publish)

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


    def test_docs_describe_complete_mnt_inventory_and_two_approvals(self) -> None:
        readme = (GIGACODE / "README.md").read_text(encoding="utf-8")
        context = (REPO_ROOT / "GIGACODE.md").read_text(encoding="utf-8")
        for text in (readme, context):
            for name in ("manage-methodology", "mnt-author", "mnt-validator", "/manage-methodology"):
                self.assertIn(name, text)
            self.assertIn("workspace-manifest", text)
            self.assertIn("methodology-patch", text)
            self.assertIn("confluence", text.lower())
        self.assertNotIn("the 5 agent skills", readme)
        self.assertNotIn("(` /quality-gate`)", context)
    def test_windows_authoring_fixture_residue_is_narrowly_ignored(self) -> None:
        ignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("Windows-local authoring test residue", ignore)
        self.assertIn("tools/methodology_authoring/.test-fixtures/", ignore)
        self.assertIn("Windows-local methodology quality-gate test residue", ignore)
        self.assertIn("tools/methodology_quality_gate/.test-fixtures/", ignore)
if __name__ == "__main__":
    unittest.main()

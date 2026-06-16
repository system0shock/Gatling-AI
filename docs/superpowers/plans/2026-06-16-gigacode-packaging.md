# Gigacode Packaging (`.gigacode/`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Assemble all agent-facing artifacts into a committed `.gigacode/` config package that follows Qwen Code conventions (Gigacode = renamed Qwen), and close the compliance gaps found in review.

**Architecture:** Move the 5 skills into `.gigacode/skills/` as the single source of truth; add a Qwen-schema `settings.json`, two schema-agnostic Python hook scripts (advisory lint + gate reminder), a read-only `validator-subagent`, a `/quality-gate` command, and a `GIGACODE.md` context file. Tools/schemas/examples stay in the repo root and are invoked by relative path. Static artifacts are guarded by a structural test; hook scripts are built TDD.

**Tech Stack:** Python 3.10+ (`unittest`, co-located `test_*.py`), JSON (Qwen settings), Markdown+YAML frontmatter (skills/agents/commands), Git.

**Spec:** `docs/superpowers/specs/2026-06-16-gigacode-packaging-design.md`

---

### Task 1: Commit the design spec

**Files:**
- Commit (untracked): `docs/superpowers/specs/2026-06-16-gigacode-packaging-design.md`

- [ ] **Step 1: Confirm the spec is the only thing staged**

Run: `git status --short docs/superpowers/specs/2026-06-16-gigacode-packaging-design.md`
Expected: shows `?? docs/superpowers/specs/2026-06-16-gigacode-packaging-design.md`

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/specs/2026-06-16-gigacode-packaging-design.md
git commit -m "docs: gigacode packaging design spec" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Move skills into `.gigacode/skills/` (single-source)

**Files:**
- Move: `skills/` → `.gigacode/skills/` (5 skill dirs)

- [ ] **Step 1: Verify no code/test references the old `skills/` path**

Run: `git grep -n "skills/" -- "*.py"`
Expected: only `tools/gatling_generator/gatling_generator.py` line ~96 — a comment string (`"migration markers for skills/reports"`), NOT a path dependency. If any real import/path appears, stop and reconcile before moving.

- [ ] **Step 2: Move the skills tree with git**

Run: `git mv skills .gigacode/skills`

- [ ] **Step 3: Verify the new layout**

Run: `git status --short` then `ls .gigacode/skills`
Expected: 5 renames (`R  skills/... -> .gigacode/skills/...`); directory lists `convert-from-jmeter document-legacy-jmeter quality-gate scenario-from-docs scenario-to-gatling`.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: move skills into .gigacode/ (single-source)" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Skills frontmatter guard test + fix `quality-gate`

**Files:**
- Create: `.gigacode/test_gigacode_package.py`
- Modify: `.gigacode/skills/quality-gate/SKILL.md` (prepend frontmatter)

- [ ] **Step 1: Write the failing test**

Create `.gigacode/test_gigacode_package.py`:

```python
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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python .gigacode/test_gigacode_package.py -v`
Expected: FAIL — `.gigacode/skills/quality-gate/SKILL.md is missing YAML frontmatter`.

- [ ] **Step 3: Add the frontmatter to the quality-gate skill**

Prepend to `.gigacode/skills/quality-gate/SKILL.md` (before the existing `# Quality Gate` line):

```markdown
---
name: quality-gate
description: Use before handing back any Gatling-AI scenario or generated Java change. Runs the local quality gate (schema, lint, generator, passport sync, Maven compile, optional smoke) and interprets the report status — never report work done without a passed/passed_with_warnings gate.
---

```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python .gigacode/test_gigacode_package.py -v`
Expected: PASS (`test_all_skills_have_name_and_description`).

- [ ] **Step 5: Commit**

```bash
git add .gigacode/test_gigacode_package.py .gigacode/skills/quality-gate/SKILL.md
git commit -m "fix: add Qwen frontmatter to quality-gate skill + guard test" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: PostToolUse hook — `lint_scenario.py` (TDD)

**Files:**
- Create: `.gigacode/hooks/lint_scenario.py`
- Test: `.gigacode/hooks/test_lint_scenario.py`

- [ ] **Step 1: Write the failing test**

Create `.gigacode/hooks/test_lint_scenario.py`:

```python
#!/usr/bin/env python3
"""Unit tests for the lint_scenario PostToolUse hook."""
from __future__ import annotations

import unittest
from pathlib import Path

import lint_scenario

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_REL = "examples/scenarios/SHOP/checkout-mix-001/scenario.yaml"


class ScenarioPathExtractionTest(unittest.TestCase):
    def test_extracts_scenario_yaml_from_tool_input(self) -> None:
        existing = (REPO_ROOT / FIXTURE_REL).resolve()
        self.assertTrue(existing.exists(), "fixture scenario must exist")
        payload = {"cwd": str(REPO_ROOT), "tool_input": {"file_path": FIXTURE_REL}}
        self.assertEqual(lint_scenario.scenario_paths_from_payload(payload, REPO_ROOT), [existing])

    def test_ignores_non_scenario_files(self) -> None:
        payload = {"cwd": str(REPO_ROOT), "tool_input": {"file_path": "README.md"}}
        self.assertEqual(lint_scenario.scenario_paths_from_payload(payload, REPO_ROOT), [])

    def test_ignores_missing_scenario_files(self) -> None:
        payload = {"cwd": str(REPO_ROOT), "tool_input": {"file_path": "scenarios/NOPE/x-001/scenario.yaml"}}
        self.assertEqual(lint_scenario.scenario_paths_from_payload(payload, REPO_ROOT), [])

    def test_deduplicates_repeated_paths(self) -> None:
        payload = {"cwd": str(REPO_ROOT), "tool_input": {"a": FIXTURE_REL, "b": FIXTURE_REL}}
        self.assertEqual(len(lint_scenario.scenario_paths_from_payload(payload, REPO_ROOT)), 1)

    def test_handles_payload_without_cwd(self) -> None:
        payload = {"tool_input": {"file_path": FIXTURE_REL}}
        self.assertEqual(lint_scenario.scenario_paths_from_payload(payload, REPO_ROOT),
                         [(REPO_ROOT / FIXTURE_REL).resolve()])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python .gigacode/hooks/test_lint_scenario.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lint_scenario'`.

- [ ] **Step 3: Write the implementation**

Create `.gigacode/hooks/lint_scenario.py`:

```python
#!/usr/bin/env python3
"""PostToolUse hook: auto-lint an edited scenario.yaml.

Gigacode/Qwen passes the event payload as JSON on stdin after a tool runs. We
scan the payload for any file path whose basename is ``scenario.yaml`` and run
the repository linter on each one that exists, returning findings to the model
via ``hookSpecificOutput.additionalContext`` so it can fix them.

Advisory: always exits 0, never blocks the edit. Schema-agnostic by design —
instead of depending on exact Qwen field names (which may differ in Gigacode),
we walk the whole payload collecting strings.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LINTER = REPO_ROOT / "tools" / "scenario_lint" / "scenario_lint.py"
SCENARIO_NAME = "scenario.yaml"


def iter_strings(value):
    """Yield every string contained in a nested JSON value."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from iter_strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from iter_strings(v)


def scenario_paths_from_payload(payload, repo_root: Path) -> list[Path]:
    """Return existing scenario.yaml paths referenced anywhere in the payload."""
    cwd = repo_root
    if isinstance(payload, dict) and payload.get("cwd"):
        cwd = Path(payload["cwd"])
    found: list[Path] = []
    seen: set[Path] = set()
    for s in iter_strings(payload):
        if Path(s).name != SCENARIO_NAME:
            continue
        candidate = Path(s)
        if not candidate.is_absolute():
            candidate = cwd / candidate
        candidate = candidate.resolve()
        if candidate.exists() and candidate not in seen:
            seen.add(candidate)
            found.append(candidate)
    return found


def run_lint(path: Path) -> tuple[int, str]:
    """Run the scenario linter; return (exit_code, combined_output)."""
    proc = subprocess.run(
        [sys.executable, str(LINTER), str(path), "--format", "text"],
        capture_output=True,
        text=True,
    )
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return 0

    paths = scenario_paths_from_payload(payload, REPO_ROOT)
    if not paths or not LINTER.exists():
        return 0

    blocking = []
    for path in paths:
        code, output = run_lint(path)
        if code != 0:
            blocking.append(output)

    if blocking:
        context = "scenario-lint found blocking issues after your edit:\n\n" + "\n\n".join(blocking)
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": context,
            }
        }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python .gigacode/hooks/test_lint_scenario.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Smoke the end-to-end path on a clean scenario**

Run: `echo '{"cwd": "'"$(pwd)"'", "tool_input": {"file_path": "examples/scenarios/SHOP/checkout-mix-001/scenario.yaml"}}' | python .gigacode/hooks/lint_scenario.py; echo "exit=$?"`
Expected: `exit=0` and (for a lint-clean fixture) no stdout JSON. If the fixture has blockers, a JSON object with `additionalContext` is printed — still `exit=0`.

- [ ] **Step 6: Commit**

```bash
git add .gigacode/hooks/lint_scenario.py .gigacode/hooks/test_lint_scenario.py
git commit -m "feat: PostToolUse scenario-lint hook for .gigacode" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Stop hook — `gate_reminder.py` (TDD)

**Files:**
- Create: `.gigacode/hooks/gate_reminder.py`
- Test: `.gigacode/hooks/test_gate_reminder.py`

- [ ] **Step 1: Write the failing test**

Create `.gigacode/hooks/test_gate_reminder.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python .gigacode/hooks/test_gate_reminder.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gate_reminder'`.

- [ ] **Step 3: Write the implementation**

Create `.gigacode/hooks/gate_reminder.py`:

```python
#!/usr/bin/env python3
"""Stop hook: remind to run the quality gate when the report is stale.

Advisory only. Compares the mtime of quality-gate-report.json against the
newest scenario.yaml under scenarios/ and examples/scenarios/. If the report is
missing or older than the newest scenario, emit a user-visible reminder.
Always exits 0; never blocks the Stop event.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT = REPO_ROOT / "quality-gate-report.json"
SCENARIO_ROOTS = (REPO_ROOT / "scenarios", REPO_ROOT / "examples" / "scenarios")


def needs_reminder(scenario_mtimes: list[float], report_mtime: float | None) -> bool:
    if not scenario_mtimes:
        return False
    if report_mtime is None:
        return True
    return max(scenario_mtimes) > report_mtime


def scenario_mtimes() -> list[float]:
    mtimes: list[float] = []
    for root in SCENARIO_ROOTS:
        if root.exists():
            for path in root.glob("**/scenario.yaml"):
                mtimes.append(path.stat().st_mtime)
    return mtimes


def main() -> int:
    try:
        sys.stdin.read()  # drain the payload; we rely on the filesystem
        report_mtime = REPORT.stat().st_mtime if REPORT.exists() else None
        if needs_reminder(scenario_mtimes(), report_mtime):
            print(json.dumps({
                "systemMessage": (
                    "Reminder: a scenario.yaml is newer than quality-gate-report.json "
                    "(or no report exists). Run the quality-gate skill before reporting done."
                )
            }))
    except Exception:
        return 0  # never block Stop on hook failure
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python .gigacode/hooks/test_gate_reminder.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add .gigacode/hooks/gate_reminder.py .gigacode/hooks/test_gate_reminder.py
git commit -m "feat: Stop gate-reminder hook for .gigacode" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: `settings.json` (Qwen schema) + guard test

**Files:**
- Create: `.gigacode/settings.json`
- Modify: `.gigacode/test_gigacode_package.py` (add `SettingsTest`)

- [ ] **Step 1: Add the failing test**

Append to `.gigacode/test_gigacode_package.py` (before the `if __name__` block):

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python .gigacode/test_gigacode_package.py SettingsTest -v`
Expected: FAIL — `FileNotFoundError: .gigacode/settings.json`.

- [ ] **Step 3: Create `.gigacode/settings.json`**

```json
{
  "context": {
    "fileName": ["GIGACODE.md"]
  },
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python .gigacode/hooks/lint_scenario.py",
            "name": "lint-scenario",
            "timeout": 30000
          }
        ]
      }
    ],
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python .gigacode/hooks/gate_reminder.py",
            "name": "gate-reminder",
            "timeout": 15000
          }
        ]
      }
    ]
  }
}
```

Notes: empty `matcher` matches all events — the hook scripts self-filter, which keeps the wiring robust to Gigacode tool-name differences. `permissions` and `mcpServers` are intentionally omitted here (documented in `.gigacode/README.md` as confirm-items; JSON has no comments).

- [ ] **Step 4: Run the test to verify it passes**

Run: `python .gigacode/test_gigacode_package.py SettingsTest -v`
Expected: PASS.

- [ ] **Step 5: Validate JSON independently**

Run: `python -c "import json; json.load(open('.gigacode/settings.json', encoding='utf-8')); print('valid')"`
Expected: `valid`

- [ ] **Step 6: Commit**

```bash
git add .gigacode/settings.json .gigacode/test_gigacode_package.py
git commit -m "feat: .gigacode/settings.json with layered hooks + context wiring" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: `validator-subagent.md` (read-only reviewer) + guard test

**Files:**
- Create: `.gigacode/agents/validator-subagent.md`
- Modify: `.gigacode/test_gigacode_package.py` (add `AgentFrontmatterTest`)

- [ ] **Step 1: Add the failing test**

Append to `.gigacode/test_gigacode_package.py` (before the `if __name__` block):

```python
class AgentFrontmatterTest(unittest.TestCase):
    def test_validator_subagent_frontmatter(self) -> None:
        fm = frontmatter((GIGACODE / "agents" / "validator-subagent.md").read_text(encoding="utf-8"))
        self.assertIsNotNone(fm, "validator-subagent.md missing frontmatter")
        self.assertRegex(fm, r"(?m)^name:\s*validator-subagent")
        self.assertRegex(fm, r"(?m)^description:\s*\S+")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python .gigacode/test_gigacode_package.py AgentFrontmatterTest -v`
Expected: FAIL — `FileNotFoundError: .gigacode/agents/validator-subagent.md`.

- [ ] **Step 3: Create `.gigacode/agents/validator-subagent.md`**

```markdown
---
name: validator-subagent
description: Read-only reviewer that verifies Gatling-AI artifacts before final handoff. Use to confirm lint is clean, the quality gate passed, and the rendered passport is in sync — it never edits files, only reports accept/blocked with evidence.
model: inherit
approvalMode: default
tools:
  - read_file
  - read_many_files
  - glob
  - search_file_content
  - run_shell_command
disallowedTools:
  - write_file
  - edit
---

You are a strict, read-only quality reviewer for the Gatling-AI workflow. You
NEVER modify files. You read artifacts and reports, then return a verdict.

## What you check

1. **Lint is clean.** Run
   `python tools/scenario_lint/scenario_lint.py <scenario.yaml> --format text`
   for the scenario under review. Any blocking finding ⇒ `blocked`.
2. **Quality gate passed.** Read `quality-gate-report.json`. It must exist and
   its status must be `passed` or `passed_with_warnings`. `blocked` or a missing
   report ⇒ `blocked`.
3. **Passport in sync.** The committed `passport.md` next to the scenario must
   match a fresh render. If the gate's `passport-sync` check is not green ⇒
   `blocked`.
4. **Honest disposition (migrations).** For converted JMeter scenarios, confirm
   `conversion-report.md` reconciles 100% (no silent drops); remaining `todo`
   JSR223 hooks justify only `passed_with_warnings`, never a clean `passed`.

## Output

Return one verdict:

- `accept` — every check above is satisfied. State the report path and status.
- `blocked` — at least one check failed. List each failing check with the exact
  finding and the file/report path. Do not soften or work around it.

Cite evidence (command output, report fields) for every claim. If you cannot
run a check, say so explicitly and treat it as `blocked`, never as passing.
```

Note: the `tools`/`disallowedTools` names follow Qwen's tool vocabulary; the exact set is a confirm-item in `.gigacode/README.md`. The read-only intent (no `write_file`/`edit`) is the contract regardless of naming.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python .gigacode/test_gigacode_package.py AgentFrontmatterTest -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add .gigacode/agents/validator-subagent.md .gigacode/test_gigacode_package.py
git commit -m "feat: read-only validator-subagent for .gigacode" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 8: `/quality-gate` command + guard test

**Files:**
- Create: `.gigacode/commands/quality-gate.md`
- Modify: `.gigacode/test_gigacode_package.py` (add `CommandFrontmatterTest`)

- [ ] **Step 1: Add the failing test**

Append to `.gigacode/test_gigacode_package.py` (before the `if __name__` block):

```python
class CommandFrontmatterTest(unittest.TestCase):
    def test_quality_gate_command_frontmatter(self) -> None:
        fm = frontmatter((GIGACODE / "commands" / "quality-gate.md").read_text(encoding="utf-8"))
        self.assertIsNotNone(fm, "quality-gate.md missing frontmatter")
        self.assertRegex(fm, r"(?m)^description:\s*\S+")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python .gigacode/test_gigacode_package.py CommandFrontmatterTest -v`
Expected: FAIL — `FileNotFoundError: .gigacode/commands/quality-gate.md`.

- [ ] **Step 3: Create `.gigacode/commands/quality-gate.md`**

```markdown
---
description: Run the local quality gate on the current scenario + generated project and report the status honestly.
---

Invoke the `quality-gate` skill for the scenario and generated Maven project
currently under review.

If a scenario path and/or project path are provided in {{args}}, use them.
Otherwise ask the user which `scenario.yaml` and which generated project
directory to gate (do not guess).

Run the gate, then report the resulting status (`passed`,
`passed_with_warnings`, or `blocked`) together with the path to
`quality-gate-report.md`. Never claim the work is done unless the status is
`passed` or `passed_with_warnings`.
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python .gigacode/test_gigacode_package.py CommandFrontmatterTest -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add .gigacode/commands/quality-gate.md .gigacode/test_gigacode_package.py
git commit -m "feat: /quality-gate command for .gigacode" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 9: `GIGACODE.md` context file + guard test

**Files:**
- Create: `GIGACODE.md` (repo root)
- Modify: `.gigacode/test_gigacode_package.py` (add context-file assertion)

- [ ] **Step 1: Add the failing test**

Append to `.gigacode/test_gigacode_package.py` (before the `if __name__` block):

```python
class ContextFileTest(unittest.TestCase):
    def test_context_file_exists(self) -> None:
        self.assertTrue((REPO_ROOT / "GIGACODE.md").exists(), "GIGACODE.md missing at repo root")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python .gigacode/test_gigacode_package.py ContextFileTest -v`
Expected: FAIL — `GIGACODE.md missing at repo root`.

- [ ] **Step 3: Create `GIGACODE.md`**

```markdown
# Gatling-AI — Agent Context

Compact always-on context for Gigacode. The full rules live in `docs/`; this
file is the map and the non-negotiables.

## Working rules

- Gatling **OSS** only (never Enterprise).
- Generate **Java** simulations only.
- **Maven** first (Gatling 3.12, gatling-maven-plugin 4.21.7).
- `scenario.yaml` is the single source of truth — fix problems by editing the
  scenario and regenerating, never by hand-editing generated Java.
- Never invent `system` / `id` / `number`. Ask the user.
- **Never report work done without a quality gate** whose status is `passed` or
  `passed_with_warnings`. `blocked` means not ready — say so with the report path.

## Layout

- `.gigacode/skills/` — agent workflows (model-invoked / `/skills <name>`).
- `.gigacode/agents/` — subagents (read-only `validator-subagent`).
- `.gigacode/commands/` — slash commands (`/quality-gate`).
- `.gigacode/hooks/` — advisory hooks (auto-lint, gate reminder).
- `tools/` — executable checks/generators, invoked as `python tools/<tool>/<tool>.py …`.
- `schemas/` — JSON Schemas (`scenario.schema.json`, `jmx-ir.schema.json`).
- `scenarios/`, `examples/scenarios/` — scenario artifacts.

## Key docs

- `docs/PRD.md`, `docs/ARCHITECTURE.md`, `docs/GETTING_STARTED.md`
- `docs/SCENARIO_FORMAT.md`, `docs/QUALITY_GATE.md`
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python .gigacode/test_gigacode_package.py ContextFileTest -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add GIGACODE.md .gigacode/test_gigacode_package.py
git commit -m "feat: GIGACODE.md agent context file" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 10: `.gigacode/README.md` + documentation updates

**Files:**
- Create: `.gigacode/README.md`
- Modify: `docs/GETTING_STARTED.md` (§6 install paths)
- Modify: `docs/ARCHITECTURE.md` (repo structure + `.gigacode/` note)
- Modify: `README.md` (mention `.gigacode/`)

- [ ] **Step 1: Create `.gigacode/README.md`**

```markdown
# `.gigacode/` — Gigacode configuration package

Canonical, version-controlled config for the Gatling-AI workflow on Gigacode
(the corporate Qwen Code fork). Layout follows Qwen Code conventions.

## Contents

- `settings.json` — context wiring + layered hooks.
- `skills/` — the 5 agent skills (single source of truth).
- `agents/validator-subagent.md` — read-only reviewer.
- `commands/quality-gate.md` — `/quality-gate` slash command.
- `hooks/` — advisory `lint_scenario.py` (PostToolUse) and `gate_reminder.py` (Stop).

## Install

- **Project (recommended):** this `.gigacode/` is already in the repo root, next
  to `tools/`. Skills invoke tools by relative path, so they only work when run
  from a project that contains `tools/`.
- **Personal (all projects):** copy individual skills to `~/.gigacode/skills/`.
  Note: tools are NOT bundled in skills, so personal-installed skills still
  require a project that contains `tools/`.

## Confirm-items (verify against a live Gigacode)

1. The config directory name is `.gigacode/` and `settings.json` uses the Qwen
   schema verbatim.
2. The context file name (`context.fileName: ["GIGACODE.md"]`) is honored.
3. The project-dir env var used by hooks (`$QWEN_PROJECT_DIR` in Qwen) — our
   hooks avoid it by resolving paths relative to their own location.
4. Hooks are supported. If not, `/quality-gate` and the `quality-gate` skill
   still work without them.
5. Subagent tool names (`read_file`, `write_file`, …) match Gigacode's vocabulary.
6. `permissions` / `mcpServers` are intentionally omitted from `settings.json`;
   add them once their Gigacode syntax is confirmed. Example Atlassian MCP block:

   ```json
   "mcpServers": {
     "atlassian": { "command": "npx", "args": ["-y", "mcp-atlassian"] }
   }
   ```
```

- [ ] **Step 2: Update `docs/GETTING_STARTED.md` §6 install instructions**

Replace the two install bullets (currently referencing `.qwen/skills/`) with:

```markdown
- **Project-level:** skills already live in `.gigacode/skills/<name>` inside this
  repository.
- **Personal (all projects):** copy `.gigacode/skills/<name>` to
  `~/.gigacode/skills/<name>`.
```

Keep the existing paragraph that tools stay in the repo and are invoked by
relative path.

- [ ] **Step 3: Update `docs/ARCHITECTURE.md`**

In the repo-structure block, add a `.gigacode/` entry (the config package) next
to the existing `skills/`/`tools/` lines, and update the line that begins "The
structure may change once the real Gigacode skill packaging requirements are
verified." to point readers at `.gigacode/README.md` for the confirm-items.
Append a short subsection:

```markdown
### `.gigacode/` — agent configuration package

Mirrors Qwen Code layout: `settings.json`, `skills/` (single source of truth),
`agents/` (read-only `validator-subagent`), `commands/` (`/quality-gate`), and
`hooks/` (advisory auto-lint + gate reminder). `GIGACODE.md` at the repo root is
the always-on agent context. See `.gigacode/README.md` for install and the
Gigacode confirm-items.
```

- [ ] **Step 4: Update root `README.md`**

In the opening description, note that the workflow ships as a `.gigacode/`
package. Add to the Documentation Map:

```markdown
- [.gigacode/](.gigacode/README.md) - Gigacode configuration package (skills, settings, hooks, agents, commands).
```

- [ ] **Step 5: Commit**

```bash
git add .gigacode/README.md docs/GETTING_STARTED.md docs/ARCHITECTURE.md README.md
git commit -m "docs: document .gigacode package and update install paths" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 11: Final verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full package guard test**

Run: `python .gigacode/test_gigacode_package.py -v`
Expected: PASS — all of `SkillFrontmatterTest`, `SettingsTest`, `AgentFrontmatterTest`, `CommandFrontmatterTest`, `ContextFileTest`.

- [ ] **Step 2: Run both hook test suites**

Run: `python .gigacode/hooks/test_lint_scenario.py -v` then `python .gigacode/hooks/test_gate_reminder.py -v`
Expected: PASS (5 + 5).

- [ ] **Step 3: Run the existing tool tests to confirm no regression from the move**

Run: `python tools/scenario_lint/test_scenario_lint.py -v`
Expected: PASS (unchanged).

- [ ] **Step 4: Confirm the existing quality gate is still green on a golden scenario**

```bash
python tools/quality_gate/quality_gate.py --scenario examples/scenarios/SHOP/login-and-search-002/scenario.yaml --project examples/generated/java --profile mvp
```
Expected: report status `passed` (or `passed_with_warnings`).

- [ ] **Step 5: Confirm no stray references to the old `skills/` path remain in live docs**

Run: `git grep -n "skills/" -- docs/GETTING_STARTED.md docs/ARCHITECTURE.md README.md`
Expected: every remaining match reads `.gigacode/skills/…`; no bare top-level `skills/` install path. (Historical `docs/superpowers/plans|specs` are left as-is by design and not checked here.)

- [ ] **Step 6: Confirm the final tree**

Run: `git ls-files .gigacode GIGACODE.md`
Expected: lists `GIGACODE.md`, `.gigacode/settings.json`, `.gigacode/README.md`, `.gigacode/test_gigacode_package.py`, the 5 `skills/*/SKILL.md`, `agents/validator-subagent.md`, `commands/quality-gate.md`, `hooks/lint_scenario.py`, `hooks/gate_reminder.py`, and the two hook test files.

---

## Notes for the implementer

- **Commit policy:** the user commits on request. These per-task commits are part
  of executing this plan; proceed with them during execution unless told otherwise.
- **Windows:** commands above use POSIX shell (`$(pwd)`, single-quoted JSON). In
  PowerShell, adapt the Task 4 Step 5 smoke command (it's optional). Python and
  git commands are identical.
- **No new dependencies:** everything uses the standard library (`json`,
  `subprocess`, `pathlib`, `re`, `unittest`).
```


# Phase 0 Hardening + Human-Readable Renderer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the confirmed review findings (lost assertions, hook router contract holes, schema/lint/generator mismatch), extract a shared tools module, add waivers end-to-end, and add a deterministic human-readable Markdown renderer wired into the quality gate.

**Architecture:** scenario.yaml stays the single contract; Java generator and the new Markdown renderer become symmetric consumers, both checked for determinism and drift by the quality gate. Cross-cutting helpers move to `tools/_shared/` (imported via `sys.path` insert of the `tools/` dir, since tools run as plain scripts). A contract-coverage test keeps schema fields and consumers in sync.

**Tech Stack:** Python 3.11+ stdlib + PyYAML + jsonschema; unittest (tests live next to each tool, runnable directly, matching `tools/hook_router/test_hook_router.py`); Java Gatling 3.12 examples; Maven.

**Verification commands** (run from repo root `F:\Coding\Gatling-AI`):

```powershell
python tools/hook_router/test_hook_router.py
python tools/gatling_generator/test_gatling_generator.py
python tools/scenario_lint/test_scenario_lint.py
python tools/scenario_renderer/test_scenario_renderer.py
python tools/quality_gate/test_quality_gate.py
python tools/quality_gate/quality_gate.py --scenario examples/scenarios/login-and-search.yaml --project examples/generated/java
```

---

### Task 1: Generator renders assertions (critical bug)

The schema requires `assertions` (minItems 1) but `render_simulation()` never reads them — SLA silently dropped from generated Java.

**Files:**
- Create: `tools/gatling_generator/test_gatling_generator.py`
- Modify: `tools/gatling_generator/gatling_generator.py` (render_load ~185-203, render_simulation ~206-254)
- Modify: `examples/generated/java/src/test/java/LoginAndSearchSimulation.java` (setUp block, lines 42-49)

- [ ] **Step 1.1: Write the failing test**

Create `tools/gatling_generator/test_gatling_generator.py`:

```python
#!/usr/bin/env python3
"""Unit tests for the Gatling generator."""

from __future__ import annotations

import sys
import unittest

import gatling_generator


def minimal_scenario(**overrides):
    scenario = {
        "id": "demo-flow",
        "title": "Demo flow",
        "source": {"type": "manual", "ref": "test"},
        "sut": {"base_url": "${BASE_URL}"},
        "steps": [
            {
                "name": "open-home",
                "title": "Open home",
                "transaction": "01 demo.open-home - Open home",
                "protocol": "http",
                "request": {"method": "GET", "path": "/"},
                "checks": [{"status": 200}],
            }
        ],
        "load": {
            "model": "closed",
            "profile": "ramp",
            "users": 5,
            "ramp_seconds": 10,
            "duration_seconds": 60,
        },
        "assertions": [
            {"name": "p95-under-800ms", "metric": "global.responseTime.p95", "op": "<", "value": 800},
            {"name": "ok-rate", "metric": "global.successfulRequests.percent", "op": ">", "value": 99},
        ],
    }
    scenario.update(overrides)
    return {"scenario": scenario}


class RenderAssertionsTest(unittest.TestCase):
    def test_simulation_contains_assertions(self) -> None:
        _, content = gatling_generator.render_simulation(minimal_scenario())
        self.assertIn(".assertions(", content)
        self.assertIn("global().responseTime().percentile(95.0).lt(800)", content)
        self.assertIn("global().successfulRequests().percent().gt(99)", content)

    def test_unknown_metric_is_rejected(self) -> None:
        document = minimal_scenario(
            assertions=[{"name": "x", "metric": "global.unknown.p95", "op": "<", "value": 1}]
        )
        with self.assertRaises(ValueError):
            gatling_generator.render_simulation(document)

    def test_unknown_op_is_rejected(self) -> None:
        document = minimal_scenario(
            assertions=[
                {"name": "x", "metric": "global.responseTime.p95", "op": "~", "value": 1}
            ]
        )
        with self.assertRaises(ValueError):
            gatling_generator.render_simulation(document)

    def test_missing_assertions_is_rejected(self) -> None:
        document = minimal_scenario()
        del document["scenario"]["assertions"]
        with self.assertRaises(ValueError):
            gatling_generator.render_simulation(document)


if __name__ == "__main__":
    sys.exit(unittest.main())
```

- [ ] **Step 1.2: Run test to verify it fails**

Run: `python tools/gatling_generator/test_gatling_generator.py`
Expected: FAIL — `.assertions(` not found; missing-assertions test fails because generator currently ignores the field.

- [ ] **Step 1.3: Implement assertion rendering**

In `tools/gatling_generator/gatling_generator.py` add after `feeder_expression`:

```python
ASSERTION_OPS = {"<": "lt", "<=": "lte", ">": "gt", ">=": "gte", "==": "is", "=": "is"}
PERCENTILE_RE = re.compile(r"^p(\d{1,2})$")


def format_number(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"assertion value must be a number: {value!r}")
    if isinstance(value, int) or value == int(value):
        return str(int(value))
    return repr(float(value))


def render_assertion(assertion: dict[str, Any]) -> str:
    metric = str(assertion["metric"])
    op = str(assertion["op"])
    parts = metric.split(".")
    if len(parts) != 3 or parts[0] != "global":
        raise ValueError(f"unsupported assertion metric: {metric}")
    _, target, stat = parts
    if target == "responseTime":
        percentile = PERCENTILE_RE.fullmatch(stat)
        if percentile:
            base = f"global().responseTime().percentile({float(percentile.group(1))})"
        elif stat in {"mean", "max", "min"}:
            base = f"global().responseTime().{stat}()"
        else:
            raise ValueError(f"unsupported assertion metric: {metric}")
    elif target in {"successfulRequests", "failedRequests"} and stat == "percent":
        base = f"global().{target}().percent()"
    else:
        raise ValueError(f"unsupported assertion metric: {metric}")
    method = ASSERTION_OPS.get(op)
    if method is None:
        raise ValueError(f"unsupported assertion op: {op}")
    return f"{base}.{method}({format_number(assertion['value'])})"
```

Replace `render_load` so the setUp block carries assertions:

```python
def render_load(load: dict[str, Any], assertions: list[Any]) -> list[str]:
    model = str(load.get("model", "")).lower()
    profile = str(load.get("profile", "")).lower()
    if model != "closed" or profile != "ramp":
        raise ValueError("only closed ramp load profiles are supported")

    users = int(load["users"])
    ramp_seconds = int(load["ramp_seconds"])
    duration_seconds = int(load["duration_seconds"])
    rendered_assertions = [
        render_assertion(require_mapping(assertion, "assertion")) for assertion in assertions
    ]
    lines = [
        "  {",
        "    setUp(",
        "      scenario.injectClosed(",
        f"        rampConcurrentUsers(0).to({users}).during(Duration.ofSeconds({ramp_seconds})),",
        f"        constantConcurrentUsers({users}).during(Duration.ofSeconds({duration_seconds}))",
        "      )",
        "    ).protocols(httpProtocol)",
        "      .assertions(",
    ]
    for index, rendered in enumerate(rendered_assertions):
        suffix = "," if index < len(rendered_assertions) - 1 else ""
        lines.append(f"        {rendered}{suffix}")
    lines.extend(["      );", "  }"])
    return lines
```

In `render_simulation`, after `load = require_mapping(...)` add and pass through:

```python
    load = require_mapping(scenario.get("load"), "scenario.load")
    assertions = require_list(scenario.get("assertions"), "scenario.assertions")
    if not assertions:
        raise ValueError("scenario.assertions must contain at least one assertion")
```

and change `lines.extend(render_load(load))` → `lines.extend(render_load(load, assertions))`.

- [ ] **Step 1.4: Run tests to verify they pass**

Run: `python tools/gatling_generator/test_gatling_generator.py`
Expected: PASS (4 tests).

- [ ] **Step 1.5: Regenerate the golden Java example**

Run: `python tools/gatling_generator/gatling_generator.py examples/scenarios/login-and-search.yaml examples/generated/java`
Then verify the committed file now ends with:

```java
  {
    setUp(
      scenario.injectClosed(
        rampConcurrentUsers(0).to(10).during(Duration.ofSeconds(30)),
        constantConcurrentUsers(10).during(Duration.ofSeconds(120))
      )
    ).protocols(httpProtocol)
      .assertions(
        global().responseTime().percentile(95.0).lt(800)
      );
  }
```

- [ ] **Step 1.6: Verify Maven still compiles (if mvn available)**

Run: `python tools/quality_gate/quality_gate.py --scenario examples/scenarios/login-and-search.yaml --project examples/generated/java`
Expected: status `passed` (or `maven.compile-command-failed` only if Maven is absent on the machine — note it, don't ignore other failures).

- [ ] **Step 1.7: Commit**

```powershell
git add tools/gatling_generator examples/generated/java
git commit -m "fix: render scenario assertions into generated simulation"
```

---

### Task 2: Generator cleanups — dead conditional, feeder path containment

**Files:**
- Modify: `tools/gatling_generator/gatling_generator.py` (render_step ~164-182, copy_feeder_resources ~257-278)
- Test: `tools/gatling_generator/test_gatling_generator.py`

- [ ] **Step 2.1: Write the failing test**

Append to `test_gatling_generator.py`:

```python
import tempfile
from pathlib import Path


class FeederContainmentTest(unittest.TestCase):
    def test_feeder_resolving_outside_scenario_dir_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scenario_dir = root / "scenarios"
            scenario_dir.mkdir()
            outside = root / "outside.csv"
            outside.write_text("username\nalice\n", encoding="utf-8")
            link = scenario_dir / "users.csv"
            try:
                link.symlink_to(outside)
            except OSError:
                self.skipTest("symlinks unavailable without privileges")
            scenario_path = scenario_dir / "demo.yaml"
            scenario_path.write_text("placeholder", encoding="utf-8")
            document = minimal_scenario(
                data={"feeders": [{"name": "users", "file": "users.csv", "strategy": "circular"}]}
            )
            with self.assertRaises(ValueError):
                gatling_generator.copy_feeder_resources(document, scenario_path, root / "out")
```

- [ ] **Step 2.2: Run test to verify it fails**

Run: `python tools/gatling_generator/test_gatling_generator.py`
Expected: FAIL (no containment check) or SKIP on hosts without symlink rights — if it skips, still apply Step 2.3 (the check is cheap and the dead-code fix is independent).

- [ ] **Step 2.3: Implement**

In `render_step`, replace the dead loop:

```python
    request_lines = request_chain(step)
    for index, line in enumerate(request_lines):
        if index == len(request_lines) - 1:
            lines.append(line)
        else:
            lines.append(line)
```

with:

```python
    lines.extend(request_chain(step))
```

In `copy_feeder_resources`, after `source = (scenario_dir / feeder_file).resolve()` add:

```python
        if not source.is_relative_to(scenario_dir):
            raise ValueError(
                f"feeder file resolves outside the scenario directory: {feeder_file}"
            )
```

- [ ] **Step 2.4: Run tests**

Run: `python tools/gatling_generator/test_gatling_generator.py`
Expected: PASS (or containment test skipped on restricted hosts).

- [ ] **Step 2.5: Commit**

```powershell
git add tools/gatling_generator
git commit -m "fix: remove dead branch and contain feeder paths in generator"
```

---

### Task 3: Contract alignment — schema requires checks, lint drops dead `columns` code

Schema is the single structural truth: `checks` becomes required per step (lint already blocks on it; SCENARIO_FORMAT.md lists it as a blocking rule). The lint's `feeder.get("columns")` branch is dead because the schema sets `additionalProperties: false` on feeders.

**Files:**
- Modify: `schemas/scenario.schema.json` (steps[].required, line 90)
- Modify: `tools/scenario_lint/scenario_lint.py` (remove feeder_columns_from_config ~115-119, its call site ~141)
- Create: `tools/scenario_lint/test_scenario_lint.py`

- [ ] **Step 3.1: Write the failing test**

Create `tools/scenario_lint/test_scenario_lint.py`:

```python
#!/usr/bin/env python3
"""Unit tests for scenario lint."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import scenario_lint

REPO_ROOT = Path(__file__).resolve().parents[2]


class SchemaContractTest(unittest.TestCase):
    def test_schema_requires_checks_per_step(self) -> None:
        schema = json.loads(
            (REPO_ROOT / "schemas" / "scenario.schema.json").read_text(encoding="utf-8")
        )
        step_schema = schema["properties"]["scenario"]["properties"]["steps"]["items"]
        self.assertIn("checks", step_schema["required"])


class DeadCodeRemovedTest(unittest.TestCase):
    def test_columns_helper_is_gone(self) -> None:
        self.assertFalse(hasattr(scenario_lint, "feeder_columns_from_config"))


if __name__ == "__main__":
    sys.exit(unittest.main())
```

- [ ] **Step 3.2: Run test to verify it fails**

Run: `python tools/scenario_lint/test_scenario_lint.py`
Expected: FAIL on both tests.

- [ ] **Step 3.3: Implement**

In `schemas/scenario.schema.json` change the step required list:

```json
            "required": ["name", "title", "transaction", "protocol", "request", "checks"],
```

In `scenario_lint.py` delete the `feeder_columns_from_config` function and change `resolve_feeders`:

```python
        name = feeder["name"]
        columns: set[str] = set()
```

(the `columns = feeder_columns_from_config(feeder)` line is replaced by an empty set; CSV columns continue to come from `read_csv_columns`).

- [ ] **Step 3.4: Run tests + full fixture check**

Run: `python tools/scenario_lint/test_scenario_lint.py` — PASS.
Run: `python tools/scenario_lint/scenario_lint.py examples/scenarios/login-and-search.yaml --format text` — Expected: `examples/scenarios/login-and-search.yaml: passed`.
Run: `python tools/quality_gate/quality_gate.py --scenario examples/scenarios/invalid/missing-check.yaml --project examples/generated/java` — Expected: status `blocked` (now both schema and lint flag the missing check).

- [ ] **Step 3.5: Commit**

```powershell
git add schemas tools/scenario_lint
git commit -m "fix: require step checks in schema and drop dead feeder columns code"
```

---

### Task 4: Hook router — collect all path keys, strict placeholders, real placeholder parsing

Three confirmed bugs: (a) `collect_paths` returns after the first of `path|file|name` keys, dropping siblings; (b) `{scenario}`/`{project}` expand to `""` silently when unset; (c) `"{scenario}" in json.dumps(...)` is substring matching over serialized JSON.

**Files:**
- Modify: `tools/hook_router/hook_router.py` (collect_paths ~90-104, context_value ~216-231, expand_arg ~234-244, command_scenarios ~247-252)
- Modify: `tools/hook_router/README.md` (document `foreach`)
- Test: `tools/hook_router/test_hook_router.py`

- [ ] **Step 4.1: Write the failing tests**

Append to `test_hook_router.py` (inside `HookRouterTest`):

```python
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
```

Create fixture `tools/hook_router/test_configs/missing_scenario_hooks.json`:

```json
{
  "rules": [
    {
      "id": "missing-scenario",
      "blocking": true,
      "when": { "events": ["Stop"] },
      "action": {
        "commands": [["echo", "{scenario}"]]
      }
    }
  ]
}
```

- [ ] **Step 4.2: Run tests to verify they fail**

Run: `python tools/hook_router/test_hook_router.py`
Expected: the four new tests FAIL (collect_paths returns one path; empty-string expansion instead of ConfigError; substring detection misfires).

- [ ] **Step 4.3: Implement**

Replace `collect_paths` dict branch:

```python
    elif isinstance(value, dict):
        path_keys = [key for key in ("path", "file", "name") if key in value]
        if path_keys:
            for key in path_keys:
                paths.extend(collect_paths(value[key]))
            return paths
        for child in value.values():
            paths.extend(collect_paths(child))
```

Replace `context_value` scenario/project branches (fail closed):

```python
    if name == "scenario":
        value = scenario or str(action.get("scenario") or defaults.get("scenario") or "")
        if not value:
            raise ConfigError("placeholder {scenario} has no value: set action.scenario or defaults.scenario")
        return value
    if name == "project":
        value = str(action.get("project") or defaults.get("project") or "")
        if not value:
            raise ConfigError("placeholder {project} has no value: set action.project or defaults.project")
        return value
```

Add a module-level constant next to the other regexes and reuse it in `expand_arg`:

```python
PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
```

```python
    return PLACEHOLDER_RE.sub(replace, value)
```

Replace `command_scenarios` detection with real placeholder parsing:

```python
def command_placeholders(commands: Any) -> set[str]:
    names: set[str] = set()
    if isinstance(commands, list):
        for command in commands:
            if isinstance(command, list):
                for arg in command:
                    if isinstance(arg, str):
                        names.update(PLACEHOLDER_RE.findall(arg))
    return names


def command_scenarios(
    action: dict[str, Any], defaults: dict[str, Any], matched_paths: list[str]
) -> list[str | None]:
    if action.get("foreach") == "matched_paths":
        return matched_paths or [None]
    configured = action.get("scenario") or defaults.get("scenario")
    if (
        "scenario" in command_placeholders(action.get("commands", []))
        and matched_paths
        and not configured
    ):
        return matched_paths
    return [str(configured)] if configured else [None]
```

Note: `route_event` already converts `ConfigError` from `build_commands` into a blocked result with `returncode: 127` — the new ConfigError paths reuse that machinery; no change needed there.

- [ ] **Step 4.4: Run tests**

Run: `python tools/hook_router/test_hook_router.py`
Expected: ALL tests pass, including the pre-existing ones (the default `hooks.json` provides `defaults.scenario`/`defaults.project`, so existing routes keep working).

Caveat: inspect `tools/hook_router/test_configs/*.json` first. If `blocking_hooks.json` or `prompt_hooks.json` use `{scenario}`/`{project}` in commands without providing `defaults.scenario`/`defaults.project`, the new fail-closed behavior changes their result — add the missing default to the fixture (the fixtures test blocking/prompt mechanics, not placeholder strictness; `missing_scenario_hooks.json` now covers strictness).

- [ ] **Step 4.5: Document `foreach` in the router README**

In `tools/hook_router/README.md`, in the section describing action fields, add:

```markdown
### Action fields

- `commands` — list of argv lists; each argument may use `{repo_root}`, `{scenario}`, `{project}`, `{python}` placeholders.
- `scenario` / `project` — per-action overrides for the matching placeholders.
- `foreach: "matched_paths"` — run the action's commands once per matched path,
  binding `{scenario}` to each path in turn. Without `foreach`, `{scenario}` in a
  command and an absent `scenario` default also iterates matched paths; `foreach`
  makes that behavior explicit and unconditional.

`{scenario}` and `{project}` placeholders fail the route with a config error when
no value is available from the action, defaults, or matched paths.
```

(Adapt placement to the README's existing structure; keep the table of placeholders.)

- [ ] **Step 4.6: Commit**

```powershell
git add tools/hook_router
git commit -m "fix: harden hook router path collection and placeholder expansion"
```

---

### Task 5: Extract `tools/_shared` (load_yaml, repo root, Finding, run_command, variables)

Confirmed duplication: `load_yaml` ×3, `find_repo_root` ×3, `Finding` ×2 (different shapes — unify into one with optional fields), `run_command` ×2, plus `VARIABLE_RE`/`variables_in` needed by the upcoming renderer.

**Files:**
- Create: `tools/_shared/__init__.py` (empty)
- Create: `tools/_shared/common.py`
- Modify: `tools/scenario_lint/scenario_lint.py`, `tools/gatling_generator/gatling_generator.py`, `tools/quality_gate/quality_gate.py`, `tools/hook_router/hook_router.py`
- Test: existing test files (regression only — refactor task, no new behavior)

- [ ] **Step 5.1: Create the shared module**

`tools/_shared/__init__.py`: empty file.

`tools/_shared/common.py`:

```python
#!/usr/bin/env python3
"""Shared helpers for Gatling-AI Phase 0 tools."""

from __future__ import annotations

import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only on hosts without PyYAML.
    yaml = None


VARIABLE_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_.-]*)\}")

BLOCKING = "blocking"
WARNING = "warning"
WAIVED = "waived"


@dataclass(frozen=True)
class Finding:
    rule: str
    message: str
    severity: str | None = None
    path: str | None = None
    artifact: str | None = None
    check: str | None = None
    command: str | None = None
    output: str | None = None


def finding_to_dict(finding: Finding) -> dict[str, Any]:
    return {key: value for key, value in asdict(finding).items() if value is not None}


def load_yaml(path: Path) -> Any:
    if yaml is None:
        raise RuntimeError("PyYAML is unavailable; install PyYAML to run Gatling-AI tools.")
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def find_repo_root(*starts: Path) -> Path | None:
    candidates = [*starts, Path(__file__)]
    for start in candidates:
        try:
            current = start.resolve()
        except OSError:
            current = start.absolute()
        if current.is_file():
            current = current.parent
        for directory in (current, *current.parents):
            if (directory / ".git").exists():
                return directory
    return None


def rel_path(path: Path, repo_root: Path | None) -> str:
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path.absolute()
    if repo_root is not None:
        try:
            return resolved.relative_to(repo_root.resolve()).as_posix()
        except (OSError, ValueError):
            pass
    return resolved.as_posix()


def run_command(
    args: list[str], cwd: Path, timeout: int | None = 120
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        shell=False,
    )


def variables_in(value: Any) -> set[str]:
    if isinstance(value, str):
        return set(VARIABLE_RE.findall(value))
    found: set[str] = set()
    if isinstance(value, dict):
        for child in value.values():
            found.update(variables_in(child))
    elif isinstance(value, list):
        for child in value:
            found.update(variables_in(child))
    return found
```

- [ ] **Step 5.2: Migrate each tool**

At the top of each of the four tool scripts (after stdlib imports, before module constants) add:

```python
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _shared.common import (  # noqa: E402
    BLOCKING,
    WARNING,
    Finding,
    finding_to_dict,
    find_repo_root,
    load_yaml,
    rel_path,
    run_command,
    variables_in,
    VARIABLE_RE,
)
```

(import only the names each tool actually uses — see below — and delete the local duplicates):

- `scenario_lint.py`: use shared `BLOCKING`, `WARNING`, `Finding`, `finding_to_dict`, `load_yaml`, `VARIABLE_RE`, `variables_in`; delete local `Finding`, `load_yaml`, `variables_in`, `VARIABLE_RE`, `BLOCKING`, `WARNING`. Local `find_repo_root` is replaced by shared (`find_repo_root(args.scenario)` keeps `Path | None` semantics). `normalize_artifact_path` is replaced by shared `rel_path` (same resolve-with-fallback + relative_to behavior); update the two call sites in `main`. In `main`, replace `asdict(f)` with `finding_to_dict(f)` (output keys stay `rule/severity/path/message` because the other fields are `None`). The `add(...)` helper now must pass `severity=` keyword: update its body to `findings.append(Finding(rule=rule, message=message, severity=severity, path=path))`.
- `gatling_generator.py`: use shared `load_yaml`; delete local copy and the local `yaml` import block.
- `quality_gate.py`: use shared `Finding`, `finding_to_dict`, `find_repo_root`, `rel_path`, `load_yaml`, `run_command`; delete the local versions. `find_repo_root(...)` callers append `or Path.cwd().resolve()`: `repo_root = find_repo_root(Path(__file__), Path.cwd(), args.scenario, args.project) or Path.cwd().resolve()`. Keep field order differences in mind: shared `Finding` puts `message` second — all quality_gate constructions already use keyword arguments, so they keep working.
- `hook_router.py`: use shared `find_repo_root`; keep its local `run_command` wrapper (different return shape — a dict with error capture) but have it call shared `run_command` internally:

```python
def run_command_summary(argv: list[str], cwd: Path) -> dict[str, Any]:
    try:
        result = run_command(argv, cwd, timeout=None)
        return {
            "argv": argv,
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    except Exception as exc:
        return {"argv": argv, "returncode": 127, "stdout": "", "stderr": str(exc)}
```

(rename the local function and its single call site in `route_event`). `find_repo_root(start)` callers append `or Path.cwd().resolve()`.

- [ ] **Step 5.3: Run all tests and the gate**

```powershell
python tools/hook_router/test_hook_router.py
python tools/gatling_generator/test_gatling_generator.py
python tools/scenario_lint/test_scenario_lint.py
python tools/scenario_lint/scenario_lint.py examples/scenarios/login-and-search.yaml --format json
python tools/quality_gate/quality_gate.py --scenario examples/scenarios/login-and-search.yaml --project examples/generated/java
```

Expected: all PASS; lint JSON keys unchanged; gate status unchanged from Task 1 baseline.

- [ ] **Step 5.4: Commit**

```powershell
git add tools
git commit -m "refactor: extract shared helpers into tools/_shared"
```

---### Task 6: Generator emits structured findings (`--format json`)

Unified taxonomy: tool failures should be machine-consumable rules, not raw tracebacks, so the agent loop can fix by rule.

**Files:**
- Modify: `tools/gatling_generator/gatling_generator.py` (main ~293-306)
- Modify: `tools/quality_gate/quality_gate.py` (run_generator_once ~313-316, generator failure finding ~346-359)
- Test: `tools/gatling_generator/test_gatling_generator.py`

- [ ] **Step 6.1: Write the failing test**

Append to `test_gatling_generator.py`:

```python
import io
import json
from unittest.mock import patch


class JsonOutputTest(unittest.TestCase):
    def test_failure_emits_findings_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scenario = Path(tmp) / "bad.yaml"
            scenario.write_text("scenario:\n  id: Bad_Id\n", encoding="utf-8")
            stdout = io.StringIO()
            with patch.object(sys, "stdout", stdout):
                code = gatling_generator.main([str(scenario), str(Path(tmp) / "out"), "--format", "json"])
            self.assertEqual(code, 1)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["blocking"][0]["rule"], "generator.invalid-scenario")
            self.assertIn("message", payload["blocking"][0])
```

- [ ] **Step 6.2: Run test to verify it fails**

Run: `python tools/gatling_generator/test_gatling_generator.py`
Expected: FAIL — argparse rejects `--format`.

- [ ] **Step 6.3: Implement**

Replace `main` in `gatling_generator.py`:

```python
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate Java Gatling simulations")
    parser.add_argument("scenario", type=Path, help="scenario YAML file")
    parser.add_argument("output_dir", type=Path, help="Maven project root for generated Java")
    parser.add_argument(
        "--format",
        choices=("json", "text"),
        default="text",
        help="output format (default: text)",
    )
    args = parser.parse_args(argv)

    try:
        output_path = write_simulation(args.scenario, args.output_dir)
    except Exception as exc:
        if args.format == "json":
            finding = Finding(
                rule="generator.invalid-scenario",
                severity=BLOCKING,
                path="$",
                message=str(exc),
            )
            print(json.dumps({"blocking": [finding_to_dict(finding)]}, indent=2, sort_keys=True))
        else:
            print(f"BLOCKED: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps({"blocking": [], "output": output_path.as_posix()}, indent=2, sort_keys=True))
    else:
        print(output_path.as_posix())
    return 0
```

Add `import json` to the imports and `Finding`, `finding_to_dict`, `BLOCKING` to the `_shared.common` import list.

In `quality_gate.py`, `run_generator_once` passes the flag:

```python
    args = [sys.executable, str(script), str(ctx.scenario), str(output_dir), "--format", "json"]
```

and in `run_generator_check`'s failure branch, surface the structured rule when present:

```python
        for label, result in (("first", result_a), ("second", result_b)):
            if result.returncode != 0:
                rule = "generator.failed"
                message = f"generator {label} run exited {result.returncode}."
                try:
                    payload = json.loads(result.stdout)
                    item = payload["blocking"][0]
                    rule = str(item.get("rule", rule))
                    message = f"{message} {item.get('message', '')}".strip()
                except (json.JSONDecodeError, LookupError, TypeError):
                    pass
                ctx.blocking.append(
                    Finding(
                        check="generator",
                        rule=rule,
                        artifact=rel_path(ctx.scenario, ctx.repo_root),
                        command=command,
                        output=output_excerpt(result.stdout, result.stderr),
                        message=message,
                    )
                )
                ctx.checks.append(CheckResult("generator", BLOCKED, artifacts, command))
                return
```

- [ ] **Step 6.4: Run tests**

```powershell
python tools/gatling_generator/test_gatling_generator.py
python tools/quality_gate/quality_gate.py --scenario examples/scenarios/login-and-search.yaml --project examples/generated/java
```

Expected: PASS; gate output unchanged for the happy path.

- [ ] **Step 6.5: Commit**

```powershell
git add tools/gatling_generator tools/quality_gate
git commit -m "feat: emit structured generator findings and consume them in the gate"
```

---

### Task 7: Waivers end-to-end (schema → lint → gate report)

`lint_waivers` are specified in SCENARIO_FORMAT.md and the report shape, but nothing implements them. Match by exact rule, honor `expires` (UTC date), report applied/expired/unused.

**Files:**
- Modify: `schemas/scenario.schema.json` (root properties)
- Modify: `tools/scenario_lint/scenario_lint.py` (lint pipeline + main JSON output)
- Modify: `tools/quality_gate/quality_gate.py` (run_lint_check consumes waivers)
- Test: `tools/scenario_lint/test_scenario_lint.py`

- [ ] **Step 7.1: Write the failing tests**

Append to `test_scenario_lint.py`:

```python
from datetime import date


def waived_document():
    return {
        "scenario": {
            "id": "demo",
            "title": "Demo",
            "source": {"type": "manual", "ref": "t"},
            "sut": {"base_url": "${BASE_URL}"},
            "steps": [
                {
                    "name": "post-thing",
                    "title": "Post thing",
                    "transaction": "01 demo.post-thing - Post thing",
                    "protocol": "http",
                    "request": {"method": "POST", "path": "/thing"},
                    "checks": [{"extract": {"type": "css", "expr": "a", "saveAs": "x"}}],
                }
            ],
            "load": {"model": "closed", "profile": "ramp", "users": 1, "ramp_seconds": 1, "duration_seconds": 1},
            "assertions": [{"name": "a", "metric": "global.responseTime.p95", "op": "<", "value": 1}],
        },
        "lint_waivers": [
            {
                "rule": "check-lint.mutating-status-check",
                "reason": "endpoint returns only 200 with empty body",
                "owner": "perf-team",
                "expires": "2999-01-01",
            }
        ],
    }


class WaiverTest(unittest.TestCase):
    def test_waiver_downgrades_blocking_finding(self) -> None:
        result = scenario_lint.lint_with_waivers(waived_document(), None, today=date(2026, 6, 10))
        blocking_rules = [f.rule for f in result.blocking]
        self.assertNotIn("check-lint.mutating-status-check", blocking_rules)
        self.assertEqual(result.waivers[0]["rule"], "check-lint.mutating-status-check")

    def test_expired_waiver_does_not_apply_and_warns(self) -> None:
        document = waived_document()
        document["lint_waivers"][0]["expires"] = "2020-01-01"
        result = scenario_lint.lint_with_waivers(document, None, today=date(2026, 6, 10))
        self.assertIn("check-lint.mutating-status-check", [f.rule for f in result.blocking])
        self.assertIn("waiver-lint.expired", [f.rule for f in result.warnings])

    def test_unused_waiver_warns(self) -> None:
        document = waived_document()
        document["scenario"]["steps"][0]["checks"].append({"status": 200})
        result = scenario_lint.lint_with_waivers(document, None, today=date(2026, 6, 10))
        self.assertIn("waiver-lint.unused", [f.rule for f in result.warnings])
```

- [ ] **Step 7.2: Run tests to verify they fail**

Run: `python tools/scenario_lint/test_scenario_lint.py`
Expected: FAIL — `lint_with_waivers` does not exist.

- [ ] **Step 7.3: Implement in scenario_lint.py**

Add imports `from datetime import date, datetime` and a result type + waiver application after `lint_document`:

```python
@dataclass
class LintResult:
    blocking: list[Finding]
    warnings: list[Finding]
    waived: list[Finding]
    waivers: list[dict[str, Any]]


def parse_expires(raw: Any) -> date | None:
    try:
        return datetime.strptime(str(raw), "%Y-%m-%d").date()
    except ValueError:
        return None


def lint_with_waivers(
    document: Any, base_dir: Path | None = None, today: date | None = None
) -> LintResult:
    today = today or datetime.now(UTC).date()
    findings = lint_document(document, base_dir)
    raw_waivers = document.get("lint_waivers") if isinstance(document, dict) else None
    waivers = [w for w in raw_waivers if isinstance(w, dict)] if isinstance(raw_waivers, list) else []

    blocking = [f for f in findings if f.severity == BLOCKING]
    warnings = [f for f in findings if f.severity == WARNING]
    waived: list[Finding] = []
    applied: list[dict[str, Any]] = []

    for waiver in waivers:
        rule = str(waiver.get("rule", ""))
        expires = parse_expires(waiver.get("expires"))
        matched = [f for f in blocking if f.rule == rule]
        if expires is None or expires < today:
            if matched:
                warnings.append(
                    Finding(
                        rule="waiver-lint.expired",
                        severity=WARNING,
                        path="$.lint_waivers",
                        message=f"waiver for '{rule}' is expired or has an invalid date; finding stays blocking",
                    )
                )
            continue
        if not matched:
            warnings.append(
                Finding(
                    rule="waiver-lint.unused",
                    severity=WARNING,
                    path="$.lint_waivers",
                    message=f"waiver for '{rule}' matched no blocking finding",
                )
            )
            continue
        for finding in matched:
            blocking.remove(finding)
            waived.append(
                Finding(rule=finding.rule, severity=WAIVED, path=finding.path, message=finding.message)
            )
        applied.append(
            {
                "rule": rule,
                "reason": str(waiver.get("reason", "")),
                "owner": str(waiver.get("owner", "")),
                "expires": str(waiver.get("expires", "")),
            }
        )

    return LintResult(blocking=blocking, warnings=warnings, waived=waived, waivers=applied)
```

Add `WAIVED` and `UTC` to imports (`from datetime import UTC, date, datetime`; `WAIVED` from `_shared.common`). Rewrite `main`'s lint section to use it:

```python
    try:
        document = load_yaml(args.scenario)
        result = lint_with_waivers(document, args.scenario.parent)
    except Exception as exc:
        failure = Finding(
            rule="scenario-lint.load-failed", severity=BLOCKING, path="$", message=str(exc)
        )
        result = LintResult(blocking=[failure], warnings=[], waived=[], waivers=[])

    if args.format == "json":
        print(
            json.dumps(
                {
                    "artifact": artifact_path,
                    "blocking": [finding_to_dict(f) for f in result.blocking],
                    "warnings": [finding_to_dict(f) for f in result.warnings],
                    "waived": [finding_to_dict(f) for f in result.waived],
                    "waivers": result.waivers,
                    "findings": [
                        finding_to_dict(f)
                        for f in (*result.blocking, *result.warnings, *result.waived)
                    ],
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(render_text(artifact_path, [*result.blocking, *result.warnings, *result.waived]))

    return 1 if result.blocking else 0
```

- [ ] **Step 7.4: Schema — allow `lint_waivers` at the document root**

In `schemas/scenario.schema.json`, add to the root `properties` (next to `"scenario"`):

```json
    "lint_waivers": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["rule", "reason", "owner", "expires"],
        "properties": {
          "rule": { "type": "string", "minLength": 1 },
          "reason": { "type": "string", "minLength": 1 },
          "owner": { "type": "string", "minLength": 1 },
          "expires": { "type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$" }
        }
      }
    }
```

- [ ] **Step 7.5: Gate consumes waivers**

In `quality_gate.py` `run_lint_check`, after the warnings loop add:

```python
    for waiver in payload.get("waivers", []):
        if isinstance(waiver, dict):
            ctx.waivers.append(waiver)
```

(`final_status` already returns `passed_with_warnings` when `ctx.waivers` is non-empty; the Markdown renderer already prints them.)

- [ ] **Step 7.6: Run tests**

```powershell
python tools/scenario_lint/test_scenario_lint.py
python tools/quality_gate/quality_gate.py --scenario examples/scenarios/login-and-search.yaml --project examples/generated/java
```

Expected: PASS; gate status unchanged (no waivers in the golden scenario).

- [ ] **Step 7.7: Commit**

```powershell
git add schemas tools/scenario_lint tools/quality_gate
git commit -m "feat: implement lint waivers end-to-end"
```

---

### Task 8: Human-readable renderer (`tools/scenario_renderer`)

New symmetric consumer of the scenario contract: deterministic Markdown for reviewers (FR3.2/FR3.3, M4). One-way artifact with a "generated from" header including the source SHA-256.

**Files:**
- Create: `tools/scenario_renderer/scenario_renderer.py`
- Create: `tools/scenario_renderer/test_scenario_renderer.py`
- Create: `tools/scenario_renderer/README.md`
- Create: `examples/generated/docs/login-and-search.md` (rendered output, committed)

- [ ] **Step 8.1: Write the failing tests**

Create `tools/scenario_renderer/test_scenario_renderer.py`:

```python
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
            document, "examples/scenarios/login-and-search.yaml",
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
```

- [ ] **Step 8.2: Run tests to verify they fail**

Run: `python tools/scenario_renderer/test_scenario_renderer.py`
Expected: FAIL — module does not exist.

- [ ] **Step 8.3: Implement the renderer**

Create `tools/scenario_renderer/scenario_renderer.py`:

```python
#!/usr/bin/env python3
"""Render Gatling-AI scenario YAML into reviewer-friendly Markdown."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _shared.common import find_repo_root, load_yaml, rel_path, variables_in  # noqa: E402


def source_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def md_escape(value: Any) -> str:
    return str(value).replace("|", "\\|")


def checks_summary(step: dict[str, Any]) -> str:
    parts: list[str] = []
    for check in step.get("checks", []) or []:
        if not isinstance(check, dict):
            continue
        if "status" in check:
            parts.append(f"status {check['status']}")
        elif isinstance(check.get("extract"), dict):
            extract = check["extract"]
            parts.append(f"extract `{extract.get('saveAs', '?')}` ({extract.get('type', '?')})")
    return ", ".join(parts) or "—"


def step_variables(step: dict[str, Any]) -> set[str]:
    request = step.get("request") if isinstance(step.get("request"), dict) else {}
    return variables_in(
        {"path": request.get("path"), "headers": request.get("headers"), "body": request.get("body")}
    )


def variable_sources(scenario: dict[str, Any]) -> dict[str, str]:
    sources: dict[str, str] = {}
    data = scenario.get("data") if isinstance(scenario.get("data"), dict) else {}
    feeders = data.get("feeders") if isinstance(data.get("feeders"), list) else []
    for feeder in feeders:
        if isinstance(feeder, dict) and feeder.get("name"):
            sources[str(feeder["name"])] = f"фидер `{feeder.get('file', '?')}`"
    for step in scenario.get("steps", []) or []:
        if not isinstance(step, dict):
            continue
        for check in step.get("checks", []) or []:
            if isinstance(check, dict) and isinstance(check.get("extract"), dict):
                save_as = check["extract"].get("saveAs")
                if isinstance(save_as, str):
                    sources[save_as] = f"извлекается в шаге `{step.get('name', '?')}`"
    return sources


def correlation_rows(scenario: dict[str, Any]) -> list[tuple[str, str, str]]:
    sources = variable_sources(scenario)
    usage: dict[str, list[str]] = {}
    feeder_names = {
        str(feeder.get("name"))
        for feeder in (scenario.get("data") or {}).get("feeders", [])
        if isinstance(feeder, dict)
    } if isinstance(scenario.get("data"), dict) else set()
    for step in scenario.get("steps", []) or []:
        if not isinstance(step, dict):
            continue
        for variable in step_variables(step):
            usage.setdefault(variable, []).append(str(step.get("name", "?")))
    rows: list[tuple[str, str, str]] = []
    for variable in sorted(usage):
        base = variable.split(".", 1)[0]
        if base in feeder_names:
            source = f"{sources[base]} (колонка `{variable.split('.', 1)[1]}`)" if "." in variable else sources[base]
        elif variable in sources:
            source = sources[variable]
        else:
            source = "переменная окружения / feeder-колонка"
        rows.append((variable, source, ", ".join(f"`{name}`" for name in sorted(set(usage[variable])))))
    return rows


def render_markdown(document: dict[str, Any], source_name: str, digest: str) -> str:
    scenario = document["scenario"]
    steps = scenario.get("steps", []) or []
    load = scenario.get("load", {}) or {}
    data = scenario.get("data") if isinstance(scenario.get("data"), dict) else {}
    feeders = data.get("feeders") if isinstance(data.get("feeders"), list) else []
    assertions = scenario.get("assertions", []) or []
    source = scenario.get("source", {}) or {}

    lines = [
        f"# Сценарий: {scenario.get('title', scenario.get('id', '?'))}",
        "",
        f"> Сгенерировано из `{source_name}` (sha256 `{digest}`). Не редактировать вручную.",
        "",
        "## Паспорт",
        "",
        f"- **ID:** `{scenario.get('id', '?')}`",
        f"- **Источник требований:** {source.get('type', '?')} / `{source.get('ref', '?')}`",
        f"- **Базовый URL:** `{scenario.get('sut', {}).get('base_url', '?')}`",
        "",
        "## Шаги",
        "",
        "| # | Транзакция | Метод | Путь | Проверки |",
        "|---|---|---|---|---|",
    ]
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            continue
        request = step.get("request") if isinstance(step.get("request"), dict) else {}
        lines.append(
            f"| {index} | {md_escape(step.get('transaction', step.get('name', '?')))} "
            f"| {md_escape(str(request.get('method', '?')).upper())} "
            f"| {md_escape(request.get('path', '?'))} "
            f"| {md_escape(checks_summary(step))} |"
        )

    lines.extend(["", "## Тестовые данные", ""])
    if feeders:
        lines.extend(["| Фидер | Файл | Стратегия |", "|---|---|---|"])
        for feeder in feeders:
            if isinstance(feeder, dict):
                lines.append(
                    f"| {md_escape(feeder.get('name', '?'))} | `{feeder.get('file', '?')}` "
                    f"| {md_escape(feeder.get('strategy', '?'))} |"
                )
    else:
        lines.append("Фидеры не используются.")

    lines.extend(
        [
            "",
            "## Профиль нагрузки",
            "",
            f"Модель: **{load.get('model', '?')}**, профиль: **{load.get('profile', '?')}**. "
            f"Разгон до **{load.get('users', '?')}** пользователей за **{load.get('ramp_seconds', '?')} с**, "
            f"полка **{load.get('duration_seconds', '?')} с**.",
            "",
            "## Корреляции и переменные",
            "",
        ]
    )
    rows = correlation_rows(scenario)
    if rows:
        lines.extend(["| Переменная | Источник | Используется в шагах |", "|---|---|---|"])
        lines.extend(f"| `{name}` | {source} | {used} |" for name, source, used in rows)
    else:
        lines.append("Сессионные переменные не используются.")

    lines.extend(["", "## SLA (assertions)", ""])
    if assertions:
        lines.extend(["| Имя | Метрика | Условие |", "|---|---|---|"])
        for assertion in assertions:
            if isinstance(assertion, dict):
                lines.append(
                    f"| {md_escape(assertion.get('name', '?'))} | `{assertion.get('metric', '?')}` "
                    f"| {md_escape(assertion.get('op', '?'))} {md_escape(assertion.get('value', '?'))} |"
                )
    else:
        lines.append("SLA не заданы.")

    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render scenario YAML to reviewer Markdown")
    parser.add_argument("scenario", type=Path, help="scenario YAML file")
    parser.add_argument("--output", type=Path, help="output .md path; stdout when omitted")
    args = parser.parse_args(argv)

    repo_root = find_repo_root(args.scenario)
    try:
        document = load_yaml(args.scenario)
        if not isinstance(document, dict) or not isinstance(document.get("scenario"), dict):
            raise ValueError("scenario root is required")
        content = render_markdown(
            document, rel_path(args.scenario, repo_root), source_digest(args.scenario)
        )
    except Exception as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 1

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8", newline="\n")
        print(args.output.as_posix())
    else:
        print(content, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 8.4: Run tests**

Run: `python tools/scenario_renderer/test_scenario_renderer.py`
Expected: PASS (5 tests).

- [ ] **Step 8.5: Generate and commit the golden rendered doc**

Run: `python tools/scenario_renderer/scenario_renderer.py examples/scenarios/login-and-search.yaml --output examples/generated/docs/login-and-search.md`

Create `tools/scenario_renderer/README.md`:

```markdown
# scenario_renderer

Renders a Gatling-AI scenario YAML into reviewer-friendly Markdown (паспорт,
шаги, тестовые данные, профиль нагрузки, корреляции, SLA).

The output is a **generated, one-way artifact**: the header records the source
file and its SHA-256; never edit the .md by hand — edit the scenario YAML and
re-render. The quality gate re-renders the golden scenario and blocks when the
committed document drifts.

## Usage

    python tools/scenario_renderer/scenario_renderer.py examples/scenarios/login-and-search.yaml \
        --output examples/generated/docs/login-and-search.md

Without `--output` the Markdown is printed to stdout. Exit code 1 with a
`BLOCKED:` stderr line when the scenario cannot be rendered.
```

- [ ] **Step 8.6: Commit**

```powershell
git add tools/scenario_renderer examples/generated/docs
git commit -m "feat: add human-readable scenario renderer"
```

---

### Task 9: Quality gate renders docs and blocks on drift

**Files:**
- Modify: `tools/quality_gate/quality_gate.py` (new check between generator and maven; new `--docs-dir` arg)
- Create: `tools/quality_gate/test_quality_gate.py`
- Modify: `skills/quality-gate/SKILL.md`, `docs/QUALITY_GATE.md` (add renderer check to MVP profile list)

- [ ] **Step 9.1: Write the failing test**

Create `tools/quality_gate/test_quality_gate.py`:

```python
#!/usr/bin/env python3
"""Unit tests for quality gate checks."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import quality_gate

REPO_ROOT = Path(__file__).resolve().parents[2]


def make_ctx(tmp: Path, docs_dir: Path) -> quality_gate.GateContext:
    return quality_gate.GateContext(
        repo_root=REPO_ROOT,
        scenario=REPO_ROOT / "examples" / "scenarios" / "login-and-search.yaml",
        project=REPO_ROOT / "examples" / "generated" / "java",
        schema=REPO_ROOT / "schemas" / "scenario.schema.json",
        profile="mvp",
        json_report=tmp / "report.json",
        md_report=tmp / "report.md",
        docs_dir=docs_dir,
    )


class RendererCheckTest(unittest.TestCase):
    def test_fresh_docs_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctx = make_ctx(Path(tmp), REPO_ROOT / "examples" / "generated" / "docs")
            quality_gate.run_renderer_check(ctx)
            self.assertEqual(ctx.checks[-1].name, "renderer")
            self.assertEqual(ctx.checks[-1].status, quality_gate.PASSED)
            self.assertEqual(ctx.blocking, [])

    def test_stale_docs_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stale_docs = Path(tmp) / "docs"
            stale_docs.mkdir()
            (stale_docs / "login-and-search.md").write_text("outdated\n", encoding="utf-8")
            ctx = make_ctx(Path(tmp), stale_docs)
            quality_gate.run_renderer_check(ctx)
            self.assertEqual(ctx.checks[-1].status, quality_gate.BLOCKED)
            self.assertEqual(ctx.blocking[-1].rule, "renderer.docs-stale")


if __name__ == "__main__":
    sys.exit(unittest.main())
```

- [ ] **Step 9.2: Run test to verify it fails**

Run: `python tools/quality_gate/test_quality_gate.py`
Expected: FAIL — `GateContext` has no `docs_dir`, `run_renderer_check` missing.

- [ ] **Step 9.3: Implement**

In `quality_gate.py`:

Add field to `GateContext` (after `md_report`):

```python
    docs_dir: Path = Path("examples/generated/docs")
```

Add the check after `run_generator_check`:

```python
def run_renderer_check(ctx: GateContext) -> None:
    script = ctx.repo_root / "tools" / "scenario_renderer" / "scenario_renderer.py"
    scenario_id = ctx.scenario.stem
    committed = ctx.docs_dir / f"{scenario_id}.md"
    artifacts = add_artifacts(ctx, ctx.scenario, script, committed)
    command = command_text(
        [sys.executable, "tools/scenario_renderer/scenario_renderer.py", rel_path(ctx.scenario, ctx.repo_root)]
    )

    args = [sys.executable, str(script), str(ctx.scenario)]
    try:
        result_a = run_command(args, ctx.repo_root)
        result_b = run_command(args, ctx.repo_root)
    except Exception as exc:
        ctx.blocking.append(
            Finding(
                check="renderer",
                rule="renderer.command-failed",
                artifact=rel_path(ctx.scenario, ctx.repo_root),
                command=command,
                message=str(exc),
            )
        )
        ctx.checks.append(CheckResult("renderer", BLOCKED, artifacts, command))
        return

    for label, result in (("first", result_a), ("second", result_b)):
        if result.returncode != 0:
            ctx.blocking.append(
                Finding(
                    check="renderer",
                    rule="renderer.failed",
                    artifact=rel_path(ctx.scenario, ctx.repo_root),
                    command=command,
                    output=output_excerpt(result.stdout, result.stderr),
                    message=f"renderer {label} run exited {result.returncode}.",
                )
            )
            ctx.checks.append(CheckResult("renderer", BLOCKED, artifacts, command))
            return

    if result_a.stdout != result_b.stdout:
        ctx.blocking.append(
            Finding(
                check="renderer",
                rule="renderer.non-deterministic-output",
                artifact=rel_path(ctx.scenario, ctx.repo_root),
                command=command,
                message="renderer produced different Markdown across two runs.",
            )
        )
        ctx.checks.append(CheckResult("renderer", BLOCKED, artifacts, command))
        return

    committed_text = committed.read_text(encoding="utf-8") if committed.is_file() else None
    if committed_text != result_a.stdout:
        ctx.blocking.append(
            Finding(
                check="renderer",
                rule="renderer.docs-stale",
                artifact=rel_path(committed, ctx.repo_root),
                command=command,
                message=(
                    "committed scenario doc does not match a fresh render; re-run "
                    f"scenario_renderer with --output {rel_path(committed, ctx.repo_root)}."
                ),
            )
        )
        ctx.checks.append(CheckResult("renderer", BLOCKED, artifacts, command))
        return

    ctx.checks.append(CheckResult("renderer", PASSED, artifacts, command))
```

In `parse_args` add:

```python
    parser.add_argument(
        "--docs-dir",
        default=Path("examples/generated/docs"),
        type=Path,
        help="directory with committed rendered scenario docs",
    )
```

In `main`: `docs_dir = resolve_arg_path(args.docs_dir, repo_root)`, pass `docs_dir=docs_dir` into `GateContext`, and insert `run_renderer_check(ctx)` between `run_generator_check(ctx)` and `run_maven_compile_check(ctx)`. In `skip_late_checks`, add a skipped entry:

```python
    ctx.checks.append(CheckResult("renderer", SKIPPED, [rel_path(ctx.scenario, ctx.repo_root)]))
```

and extend its message to "generator, renderer, and Maven compile skipped …".

- [ ] **Step 9.4: Run tests + the full gate**

```powershell
python tools/quality_gate/test_quality_gate.py
python tools/quality_gate/quality_gate.py --scenario examples/scenarios/login-and-search.yaml --project examples/generated/java
```

Expected: PASS; gate includes `renderer: passed`.

- [ ] **Step 9.5: Update docs**

`docs/QUALITY_GATE.md` MVP Profile list — add after the Java compile bullet:

```markdown
- Scenario Markdown render (deterministic, committed docs must match).
```

`skills/quality-gate/SKILL.md` — add the renderer check to the listed checks in the same wording.

- [ ] **Step 9.6: Commit**

```powershell
git add tools/quality_gate skills/quality-gate docs/QUALITY_GATE.md
git commit -m "feat: add renderer drift check to quality gate"
```

---

### Task 10: Restore the hard Stop-gate promise in docs

The router already blocks (Stop route is `blocking: true`, router exits 1 on failure) — the docs were downgraded to soft language. State the mechanism explicitly.

**Files:**
- Modify: `docs/QUALITY_GATE.md` (Hook Model table)
- Modify: `docs/HOOK_SPIKE.md` (MVP Routes table)

- [ ] **Step 10.1: Update QUALITY_GATE.md**

Replace the row:

```markdown
| `SubagentStop` / `Stop` | Router runs the MVP quality gate. |
```

with:

```markdown
| `SubagentStop` / `Stop` | Router runs the MVP quality gate and **exits non-zero when the gate is blocked** — the host must treat a non-zero router exit as "do not hand off". |
```

- [ ] **Step 10.2: Update HOOK_SPIKE.md**

After the MVP Routes table sentence "It exits non-zero when a matched blocking command fails." add:

```markdown
The `Stop`/`SubagentStop` route is the hard gate from FR5.7.5: a blocked quality
gate makes the router exit non-zero, and the host hook integration must block the
final "ready" response on that exit code. If the host cannot block on hook exit
codes, the explicit `quality-gate` command remains the fallback and the agent
must not report readiness without a `passed`/`passed_with_warnings` report.
```

- [ ] **Step 10.3: Verify the mechanism with the existing test**

Run: `python tools/hook_router/test_hook_router.py`
Expected: PASS — `test_blocking_command_failure_blocks` covers the exit path.

- [ ] **Step 10.4: Commit**

```powershell
git add docs/QUALITY_GATE.md docs/HOOK_SPIKE.md
git commit -m "docs: state the hard Stop-gate contract explicitly"
```

---

### Task 11: Contract coverage test (schema ↔ consumers)

Mechanism that would have caught the lost assertions: every schema field path must be either consumed or explicitly ignored by each consumer (generator, renderer).

**Files:**
- Modify: `tools/gatling_generator/gatling_generator.py` (declare field sets)
- Modify: `tools/scenario_renderer/scenario_renderer.py` (declare field sets)
- Create: `tools/test_contract_coverage.py`

- [ ] **Step 11.1: Write the failing test**

Create `tools/test_contract_coverage.py`:

```python
#!/usr/bin/env python3
"""Every schema field must be consumed or explicitly ignored by each consumer."""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO_ROOT = TOOLS.parent


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(path.parent))
    return module


def schema_paths(schema: dict, prefix: str = "") -> set[str]:
    paths: set[str] = set()
    for name, sub in schema.get("properties", {}).items():
        path = f"{prefix}.{name}" if prefix else name
        paths.add(path)
        paths.update(schema_paths(sub, path))
    items = schema.get("items")
    if isinstance(items, dict):
        paths.update(schema_paths(items, f"{prefix}[]"))
    for variant in schema.get("oneOf", []):
        paths.update(schema_paths(variant, prefix))
    return paths


class ContractCoverageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        schema = json.loads(
            (REPO_ROOT / "schemas" / "scenario.schema.json").read_text(encoding="utf-8")
        )
        cls.paths = schema_paths(schema)
        cls.generator = load_module(
            "gen_cc", TOOLS / "gatling_generator" / "gatling_generator.py"
        )
        cls.renderer = load_module(
            "ren_cc", TOOLS / "scenario_renderer" / "scenario_renderer.py"
        )

    def assert_covered(self, module) -> None:
        declared = module.CONSUMED_FIELDS | module.IGNORED_FIELDS
        missing = self.paths - declared
        stale = declared - self.paths
        self.assertEqual(missing, set(), f"schema fields not declared by {module.__name__}")
        self.assertEqual(stale, set(), f"declared fields missing from schema in {module.__name__}")

    def test_generator_covers_schema(self) -> None:
        self.assert_covered(self.generator)

    def test_renderer_covers_schema(self) -> None:
        self.assert_covered(self.renderer)


if __name__ == "__main__":
    sys.exit(unittest.main())
```

- [ ] **Step 11.2: Run test to verify it fails**

Run: `python tools/test_contract_coverage.py`
Expected: FAIL — `CONSUMED_FIELDS` not defined.

- [ ] **Step 11.3: Declare field sets in the generator**

Add to `gatling_generator.py` (module level, after the regex constants). Adjust to the exact failure output of Step 11.2 — the test names every missing path:

```python
# Contract coverage declarations: every schema field path is either consumed by
# this generator or explicitly ignored with a reason. Checked by
# tools/test_contract_coverage.py.
CONSUMED_FIELDS = {
    "scenario",
    "scenario.id",
    "scenario.title",
    "scenario.sut",
    "scenario.sut.base_url",
    "scenario.data",
    "scenario.data.feeders",
    "scenario.data.feeders[].file",
    "scenario.data.feeders[].strategy",
    "scenario.steps",
    "scenario.steps[].name",
    "scenario.steps[].transaction",
    "scenario.steps[].request",
    "scenario.steps[].request.method",
    "scenario.steps[].request.path",
    "scenario.steps[].request.headers",
    "scenario.steps[].request.body",
    "scenario.steps[].checks",
    "scenario.steps[].checks[].status",
    "scenario.steps[].checks[].extract",
    "scenario.steps[].checks[].extract.type",
    "scenario.steps[].checks[].extract.expr",
    "scenario.steps[].checks[].extract.saveAs",
    "scenario.load",
    "scenario.load.model",
    "scenario.load.profile",
    "scenario.load.users",
    "scenario.load.ramp_seconds",
    "scenario.load.duration_seconds",
    "scenario.assertions",
    "scenario.assertions[].metric",
    "scenario.assertions[].op",
    "scenario.assertions[].value",
}
IGNORED_FIELDS = {
    "scenario.source",        # requirements provenance; documented by the renderer
    "scenario.source.type",
    "scenario.source.ref",
    "scenario.steps[].title",      # human label; transaction is the display name
    "scenario.steps[].protocol",   # validated by schema enum + lint
    "scenario.data.feeders[].name",  # used by lint/renderer correlation, not codegen
    "scenario.assertions[].name",    # report label only
    "lint_waivers",                  # lint concern
    "lint_waivers[].rule",
    "lint_waivers[].reason",
    "lint_waivers[].owner",
    "lint_waivers[].expires",
}
```

- [ ] **Step 11.4: Declare field sets in the renderer**

Add to `scenario_renderer.py` (module level), same shape. Note: `request.headers` and `request.body` count as **consumed** because `step_variables` reads them for the correlations table. Declare:

```python
CONSUMED_FIELDS = {
    "scenario",
    "scenario.id",
    "scenario.title",
    "scenario.source",
    "scenario.source.type",
    "scenario.source.ref",
    "scenario.sut",
    "scenario.sut.base_url",
    "scenario.data",
    "scenario.data.feeders",
    "scenario.data.feeders[].name",
    "scenario.data.feeders[].file",
    "scenario.data.feeders[].strategy",
    "scenario.steps",
    "scenario.steps[].name",
    "scenario.steps[].transaction",
    "scenario.steps[].request",
    "scenario.steps[].request.method",
    "scenario.steps[].request.path",
    "scenario.steps[].request.headers",
    "scenario.steps[].request.body",
    "scenario.steps[].checks",
    "scenario.steps[].checks[].status",
    "scenario.steps[].checks[].extract",
    "scenario.steps[].checks[].extract.type",
    "scenario.steps[].checks[].extract.expr",
    "scenario.steps[].checks[].extract.saveAs",
    "scenario.load",
    "scenario.load.model",
    "scenario.load.profile",
    "scenario.load.users",
    "scenario.load.ramp_seconds",
    "scenario.load.duration_seconds",
    "scenario.assertions",
    "scenario.assertions[].name",
    "scenario.assertions[].metric",
    "scenario.assertions[].op",
    "scenario.assertions[].value",
}
IGNORED_FIELDS = {
    "scenario.steps[].title",     # transaction is the reviewer-facing label
    "scenario.steps[].protocol",  # MVP is http-only; schema enum guarantees it
    "lint_waivers",               # rendered by the quality gate report, not the doc
    "lint_waivers[].rule",
    "lint_waivers[].reason",
    "lint_waivers[].owner",
    "lint_waivers[].expires",
}
```

- [ ] **Step 11.5: Run the test**

Run: `python tools/test_contract_coverage.py`
Expected: PASS. If path spellings differ from the schema walker's output, fix the declarations to match the test's reported sets — the walker is the source of truth.

- [ ] **Step 11.6: Commit**

```powershell
git add tools/test_contract_coverage.py tools/gatling_generator tools/scenario_renderer
git commit -m "test: enforce schema contract coverage for generator and renderer"
```

---

### Task 12: Opt-in smoke run (`--smoke`)

FR5.7.8 includes a smoke run in MVP; the gate stops at compile. Add `mvn gatling:test` behind an explicit flag (FR5.7.7: never load the SUT without permission).

**Files:**
- Modify: `tools/quality_gate/quality_gate.py`
- Test: `tools/quality_gate/test_quality_gate.py`
- Modify: `docs/QUALITY_GATE.md`, `tools/quality_gate/README.md`

- [ ] **Step 12.1: Write the failing test**

Append to `test_quality_gate.py`:

```python
import subprocess
from unittest.mock import patch


class SmokeCheckTest(unittest.TestCase):
    def test_smoke_runs_simulation_class(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctx = make_ctx(Path(tmp), REPO_ROOT / "examples" / "generated" / "docs")
            completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            with patch.object(quality_gate, "resolve_maven_executable", return_value="mvn"), patch.object(
                quality_gate, "run_command", return_value=completed
            ) as run:
                quality_gate.run_smoke_check(ctx)
            argv = run.call_args.args[0]
            self.assertIn("gatling:test", argv)
            self.assertIn("-Dgatling.simulationClass=LoginAndSearchSimulation", argv)
            self.assertEqual(ctx.checks[-1].status, quality_gate.PASSED)

    def test_smoke_failure_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctx = make_ctx(Path(tmp), REPO_ROOT / "examples" / "generated" / "docs")
            completed = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="boom")
            with patch.object(quality_gate, "resolve_maven_executable", return_value="mvn"), patch.object(
                quality_gate, "run_command", return_value=completed
            ):
                quality_gate.run_smoke_check(ctx)
            self.assertEqual(ctx.blocking[-1].rule, "smoke.run-failed")
```

- [ ] **Step 12.2: Run test to verify it fails**

Run: `python tools/quality_gate/test_quality_gate.py`
Expected: FAIL — `run_smoke_check` missing.

- [ ] **Step 12.3: Implement**

The smoke check needs `pascal_case`, which currently lives in the generator. Move it to the shared module first. In `tools/_shared/common.py` add:

```python
def pascal_case(identifier: str) -> str:
    parts = [part for part in identifier.split("-") if part]
    return "".join(part[:1].upper() + part[1:] for part in parts)
```

Update `gatling_generator.py` to import `pascal_case` from `_shared.common` and delete its local copy.

In `quality_gate.py` add after `run_maven_compile_check` (import `pascal_case` from `_shared.common`):

```python
def run_smoke_check(ctx: GateContext) -> None:
    pom = ctx.project / "pom.xml"
    artifacts = add_artifacts(ctx, pom, ctx.scenario)
    try:
        document = load_yaml(ctx.scenario)
        scenario_id = str(document["scenario"]["id"])
    except Exception as exc:
        ctx.blocking.append(
            Finding(
                check="smoke",
                rule="smoke.scenario-unreadable",
                artifact=rel_path(ctx.scenario, ctx.repo_root),
                message=str(exc),
            )
        )
        ctx.checks.append(CheckResult("smoke", BLOCKED, artifacts))
        return

    simulation_class = f"{pascal_case(scenario_id)}Simulation"
    command = f"mvn -q gatling:test -Dgatling.simulationClass={simulation_class}"
    executable = resolve_maven_executable()
    if executable is None:
        ctx.blocking.append(
            Finding(
                check="smoke",
                rule="smoke.command-failed",
                artifact=rel_path(pom, ctx.repo_root),
                command=command,
                message="Maven executable was not found on PATH.",
            )
        )
        ctx.checks.append(CheckResult("smoke", BLOCKED, artifacts, command))
        return

    args = [executable, "-q", "gatling:test", f"-Dgatling.simulationClass={simulation_class}"]
    try:
        result = run_command(args, ctx.project, timeout=600)
    except Exception as exc:
        ctx.blocking.append(
            Finding(
                check="smoke",
                rule="smoke.command-failed",
                artifact=rel_path(pom, ctx.repo_root),
                command=command,
                message=str(exc),
            )
        )
        ctx.checks.append(CheckResult("smoke", BLOCKED, artifacts, command))
        return

    if result.returncode != 0:
        ctx.blocking.append(
            Finding(
                check="smoke",
                rule="smoke.run-failed",
                artifact=rel_path(pom, ctx.repo_root),
                command=command,
                output=output_excerpt(result.stdout, result.stderr),
                message=f"smoke run exited {result.returncode}.",
            )
        )
        ctx.checks.append(CheckResult("smoke", BLOCKED, artifacts, command))
        return

    ctx.checks.append(CheckResult("smoke", PASSED, artifacts, command))
```

In `parse_args`:

```python
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="run the simulation once via mvn gatling:test (loads the SUT; opt-in only)",
    )
```

In `main`, after `run_maven_compile_check(ctx)`:

```python
        if args.smoke:
            run_smoke_check(ctx)
```

- [ ] **Step 12.4: Run tests**

Run: `python tools/quality_gate/test_quality_gate.py` and `python tools/gatling_generator/test_gatling_generator.py` and `python tools/test_contract_coverage.py`
Expected: PASS.

- [ ] **Step 12.5: Update docs**

`docs/QUALITY_GATE.md` MVP Profile — add:

```markdown
- Smoke run via `--smoke` (opt-in: it loads the SUT, so it never runs by default).
```

`tools/quality_gate/README.md` — document the `--smoke` and `--docs-dir` flags with one example each.

- [ ] **Step 12.6: Commit**

```powershell
git add tools/_shared tools/gatling_generator tools/quality_gate docs/QUALITY_GATE.md
git commit -m "feat: add opt-in smoke run to quality gate"
```

---

### Task 13: Final verification sweep

- [ ] **Step 13.1: Run everything**

```powershell
python tools/hook_router/test_hook_router.py
python tools/gatling_generator/test_gatling_generator.py
python tools/scenario_lint/test_scenario_lint.py
python tools/scenario_renderer/test_scenario_renderer.py
python tools/quality_gate/test_quality_gate.py
python tools/test_contract_coverage.py
python tools/quality_gate/quality_gate.py --scenario examples/scenarios/login-and-search.yaml --project examples/generated/java
python tools/quality_gate/quality_gate.py --scenario examples/scenarios/invalid/missing-check.yaml --project examples/generated/java
```

Expected: all test files PASS; golden gate `passed` (or with a noted Maven-absence finding only); invalid fixture `blocked`.

- [ ] **Step 13.2: Update ARCHITECTURE.md**

Add the renderer to the Components table:

```markdown
| `scenario_renderer` | Render scenario YAML into reviewer-facing Markdown (one-way generated artifact, drift-checked by the quality gate). |
```

and add `scenario_renderer/` to the Planned Repository Structure tools listing.

- [ ] **Step 13.3: Commit**

```powershell
git add docs/ARCHITECTURE.md
git commit -m "docs: register scenario renderer in architecture"
```

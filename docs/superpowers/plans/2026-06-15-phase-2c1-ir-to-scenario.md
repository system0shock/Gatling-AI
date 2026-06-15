# Phase 2c-1: `ir_to_scenario` Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `tools/ir_to_scenario/` — a deterministic tool that converts a parsed JMeter IR (`ir.json` from `jmx_parser`) into a Phase-2b `scenario.yaml` plus a `conversion-report.md` whose element disposition reconciles 1:1 with the parser's `inventory.md`.

**Architecture:** Pure Python stdlib (+ PyYAML, already used). The tool reads the full `ir.json` (agents never do — they read the report); it walks the IR tree, maps each element to the Phase-2b scenario contract, and records a disposition (`converted | partial | todo | skipped-disabled`) for **every** element so nothing is silently dropped. JSR223 is never transpiled here — every JSR223 element becomes a `kind: todo` hook for the agent to translate later (Phase 2 spec decision: "the agent always translates JSR223"). Mapping rules for HTTP functions, extractors, redirects, and CSV `shareMode` are adapted (with attribution) from Gatling's Apache-2.0 `gatling-convert-from-jmeter` skill.

**Tech Stack:** Python 3.11+ stdlib, PyYAML, `tools/_shared/common.py` helpers (`Finding`, `load_yaml`, `pascal_case`, etc.); `unittest` run directly; inputs validated against `schemas/jmx-ir.schema.json`; output validated against `schemas/scenario.schema.json`.

**Verification commands** (from repo root `F:\Coding\Gatling-AI`):

```powershell
python tools/ir_to_scenario/test_ir_to_scenario.py
python tools/scenario_lint/scenario_lint.py <generated scenario.yaml>   # generated output must lint clean where expected
```

## Source-of-truth references (read before starting)

- **IR shape:** `schemas/jmx-ir.schema.json` (base element: `id, kind, type, name, enabled, path, children`; kind-specific fields are free-form `additionalProperties`). The exact per-kind fields are produced by `tools/jmx_parser/jmx_parser.py` detail builders — the relevant ones are quoted inline in each task below.
- **Target shape:** `schemas/scenario.schema.json` (Phase-2b contract: `scenario` with single-flow `steps`+`load` OR `populations`; step variants http/graphql/kafka/jdbc; `load` with `profile: stages` etc.).
- **Inventory counts:** `jmx_parser` emits `stats.by_kind` and `stats.elements_total/elements_disabled` in `ir.json`, and an `inventory.md`. Reconciliation targets `stats`.
- **Gatling mapping reference (Apache-2.0):** `github.com/gatling/gatling-ai-extensions` → `plugins/gatling/skills/gatling-convert-from-jmeter/SKILL.md`. Cite it in a module docstring.

## File structure (final state)

```text
tools/ir_to_scenario/
  __init__.py                 # empty (package marker, matches other tools)
  ir_to_scenario.py           # the tool: IR walk -> scenario dict + report; CLI main()
  test_ir_to_scenario.py      # unittest suite
  fixtures.py                 # IR-builder helpers for tests (mirrors jmx_parser/fixtures.py style)
docs/MIGRATION.md             # MODIFIED/created: documents the tool + disposition statuses + Gatling attribution
```

The tool is one focused module. If `ir_to_scenario.py` grows past ~600 lines during implementation, split the mapping helpers into `tools/ir_to_scenario/mappers.py` and report the split as DONE_WITH_CONCERNS — do not split pre-emptively.

**Conventions for every task:** TDD — failing test first, run it, implement, run again; append test classes to `test_ir_to_scenario.py`; each task ends with a commit. Disposition statuses are the literals `"converted"`, `"partial"`, `"todo"`, `"skipped-disabled"`. End every commit message with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

### Task 1: Scaffolding — IR load/validate, Disposition ledger, conversion skeleton

**Files:**
- Create: `tools/ir_to_scenario/__init__.py` (empty)
- Create: `tools/ir_to_scenario/ir_to_scenario.py`
- Create: `tools/ir_to_scenario/fixtures.py`
- Create: `tools/ir_to_scenario/test_ir_to_scenario.py`

- [ ] **Step 1.1: Write `fixtures.py` (test IR builders)**

```python
"""Builders for minimal valid JMX-IR dicts used by the ir_to_scenario tests."""
from __future__ import annotations
from typing import Any

_COUNTER = {"n": 0}


def eid() -> str:
    _COUNTER["n"] += 1
    return f"e-{_COUNTER['n']:04d}"


def element(kind: str, name: str = "", **detail: Any) -> dict[str, Any]:
    node = {
        "id": eid(), "kind": kind, "type": kind, "name": name,
        "enabled": detail.pop("enabled", True), "path": [], "children": detail.pop("children", []),
    }
    node.update(detail)
    return node


def http_sampler(name: str, method: str = "GET", path: str = "/", **extra: Any) -> dict[str, Any]:
    detail = {
        "method": method,
        "url": {"protocol": "", "domain": "", "port": "", "path": path},
        "follow_redirects": True,
    }
    detail.update(extra)
    return element("http_sampler", name, **detail)


def thread_group(name: str, children: list[dict], normalized: dict | None, note: str | None = None) -> dict[str, Any]:
    return element(
        "thread_group", name,
        flavor="standard", raw={}, load={"normalized": normalized, "note": note},
        children=children,
    )


def ir(children: list[dict], **over: Any) -> dict[str, Any]:
    by_kind: dict[str, int] = {}

    def walk(node: dict) -> None:
        by_kind[node["kind"]] = by_kind.get(node["kind"], 0) + 1
        for child in node.get("children", []):
            walk(child)

    for child in children:
        walk(child)
    total = sum(by_kind.values())
    doc = {
        "version": 1,
        "source": {"file": "test.jmx", "sha256": "0" * 64, "size_bytes": 0},
        "test_plan": {"name": "Test", "comments": ""},
        "children": children,
        "unsupported": [],
        "variables": {"index": {}, "functions": [], "props": {}, "findings": {"consumed_not_produced": [], "produced_not_consumed": []}},
        "complexity_flags": [],
        "stats": {
            "elements_total": total, "elements_disabled": 0, "by_kind": by_kind,
            "bodies_externalized": 0, "jsr223": {"typical": 0, "complex": 0},
        },
    }
    doc.update(over)
    return doc
```

- [ ] **Step 1.2: Write the failing test**

```python
#!/usr/bin/env python3
from __future__ import annotations
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ir_to_scenario
import fixtures


class SkeletonTest(unittest.TestCase):
    def test_emits_scenario_meta_from_args(self) -> None:
        doc = fixtures.ir([
            fixtures.thread_group(
                "Main", [fixtures.http_sampler("home", path="/")],
                {"model": "closed", "stages": [{"users": 5, "ramp_seconds": 10, "hold_seconds": 60}], "start_after_seconds": 0},
            )
        ])
        result = ir_to_scenario.convert(doc, system="SHOP", scenario_id="checkout-mix", number=1)
        scenario = result.scenario["scenario"]
        self.assertEqual(scenario["system"], "SHOP")
        self.assertEqual(scenario["id"], "checkout-mix")
        self.assertEqual(scenario["number"], 1)
        self.assertEqual(scenario["source"], {"type": "jmeter", "ref": "test.jmx"})

    def test_every_element_has_a_disposition(self) -> None:
        doc = fixtures.ir([
            fixtures.thread_group(
                "Main", [fixtures.http_sampler("home", path="/")],
                {"model": "closed", "stages": [{"users": 5, "ramp_seconds": 10, "hold_seconds": 60}], "start_after_seconds": 0},
            )
        ])
        result = ir_to_scenario.convert(doc, system="SHOP", scenario_id="demo", number=1)
        # thread_group + http_sampler = 2 elements, each accounted exactly once
        self.assertEqual(sum(result.disposition_counts().values()), doc["stats"]["elements_total"])


if __name__ == "__main__":
    sys.exit(unittest.main())
```

- [ ] **Step 1.3: Run test to verify it fails**

Run: `python tools/ir_to_scenario/test_ir_to_scenario.py` → FAIL (`module 'ir_to_scenario' has no attribute 'convert'`).

- [ ] **Step 1.4: Implement the skeleton**

Create `tools/ir_to_scenario/ir_to_scenario.py`:

```python
#!/usr/bin/env python3
"""Convert a JMeter IR (jmx_parser output) into a Phase-2b scenario.yaml + report.

Element-mapping rules for HTTP functions, extractors, redirects, and CSV
shareMode are adapted from Gatling's Apache-2.0 `gatling-convert-from-jmeter`
skill (github.com/gatling/gatling-ai-extensions). The contract-first pipeline
(IR -> scenario.yaml -> generator) and the disposition reconciliation are ours.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _shared.common import Finding  # noqa: E402

CONVERTED = "converted"
PARTIAL = "partial"
TODO = "todo"
SKIPPED = "skipped-disabled"

# IR kinds that carry no codegen meaning on their own (handled via their effect
# on samplers/steps) and are recorded as converted when their effect is applied,
# or skipped when disabled. Controllers handled in Task 3.
@dataclass
class Conversion:
    scenario: dict[str, Any]
    report_rows: list[dict[str, str]] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    def record(self, element: dict[str, Any], status: str, note: str = "") -> None:
        self.report_rows.append(
            {"id": element.get("id", "?"), "kind": element.get("kind", "?"),
             "name": element.get("name", ""), "status": status, "note": note}
        )

    def disposition_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self.report_rows:
            counts[row["status"]] = counts.get(row["status"], 0) + 1
        return counts


def convert(ir: dict[str, Any], *, system: str, scenario_id: str, number: int) -> Conversion:
    scenario: dict[str, Any] = {
        "id": scenario_id,
        "system": system,
        "number": number,
        "title": ir.get("test_plan", {}).get("name") or scenario_id,
        "source": {"type": "jmeter", "ref": ir.get("source", {}).get("file", "")},
        "sut": {"base_url": "${BASE_URL}"},
    }
    conv = Conversion(scenario={"scenario": scenario})
    walk_children(ir.get("children", []), conv)
    return conv


def walk_children(children: list[Any], conv: Conversion) -> None:
    """Record a disposition for every element so counts reconcile. Replaced with
    real mapping in later tasks; for now every element is recorded as todo."""
    for node in children:
        if not isinstance(node, dict):
            continue
        if not node.get("enabled", True):
            conv.record(node, SKIPPED)
        else:
            conv.record(node, TODO, "not yet mapped")
        walk_children(node.get("children", []), conv)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Convert JMeter IR to a scenario.yaml")
    parser.add_argument("ir_json")
    parser.add_argument("--system", required=True)
    parser.add_argument("--id", required=True, dest="scenario_id")
    parser.add_argument("--number", required=True, type=int)
    args = parser.parse_args(argv)
    ir = json.loads(Path(args.ir_json).read_text(encoding="utf-8"))
    conv = convert(ir, system=args.system, scenario_id=args.scenario_id, number=args.number)
    print(json.dumps(conv.disposition_counts()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Create `tools/ir_to_scenario/__init__.py` as an empty file.

- [ ] **Step 1.5: Run test to verify it passes**

Run: `python tools/ir_to_scenario/test_ir_to_scenario.py` → PASS (2 tests).

- [ ] **Step 1.6: Commit**

```powershell
git add tools/ir_to_scenario
git commit -m "feat: ir_to_scenario scaffolding with disposition ledger"
```

---

### Task 2: Load mapping (`thread_group.load.normalized` → scenario load)

The parser already normalizes every TG flavor to `{"model", "stages":[{users|users_per_second, ramp_seconds, hold_seconds}], "start_after_seconds"}` or `None` + a `note`. One TG → single-flow `steps`+`load`; ≥2 TG → `populations`.

**Files:** Modify `tools/ir_to_scenario/ir_to_scenario.py`; Test in `test_ir_to_scenario.py`.

- [ ] **Step 2.1: Write the failing tests**

```python
class LoadMappingTest(unittest.TestCase):
    def _convert(self, groups):
        return ir_to_scenario.convert(fixtures.ir(groups), system="SHOP", scenario_id="demo", number=1)

    def test_single_thread_group_is_single_flow(self) -> None:
        conv = self._convert([
            fixtures.thread_group("Main", [fixtures.http_sampler("home")],
                {"model": "closed", "stages": [{"users": 5, "ramp_seconds": 10, "hold_seconds": 60}], "start_after_seconds": 0})
        ])
        scenario = conv.scenario["scenario"]
        self.assertNotIn("populations", scenario)
        self.assertEqual(scenario["load"], {"model": "closed", "profile": "stages",
            "stages": [{"users": 5, "ramp_seconds": 10, "hold_seconds": 60}]})

    def test_two_thread_groups_become_populations(self) -> None:
        conv = self._convert([
            fixtures.thread_group("Main flow", [fixtures.http_sampler("home")],
                {"model": "closed", "stages": [{"users": 5, "ramp_seconds": 10, "hold_seconds": 60}], "start_after_seconds": 0}),
            fixtures.thread_group("Background", [fixtures.http_sampler("bg", path="/bg")],
                {"model": "open", "stages": [{"users_per_second": 2, "ramp_seconds": 5, "hold_seconds": 30}], "start_after_seconds": 120}),
        ])
        scenario = conv.scenario["scenario"]
        self.assertNotIn("load", scenario)
        names = [p["name"] for p in scenario["populations"]]
        self.assertEqual(names, ["main-flow", "background"])
        self.assertEqual(scenario["populations"][1]["start_after_seconds"], 120)

    def test_unnormalizable_load_blocks(self) -> None:
        conv = self._convert([
            fixtures.thread_group("Main", [fixtures.http_sampler("home")], None, note="parameterized thread count")
        ])
        rules = [f.rule for f in conv.findings]
        self.assertIn("convert.load-not-normalized", rules)
```

- [ ] **Step 2.2: Run tests to verify they fail**

Run: `python tools/ir_to_scenario/test_ir_to_scenario.py` → FAIL (no `load`/`populations` emitted).

- [ ] **Step 2.3: Implement**

Add helpers and rework `convert` so that, after building `scenario` meta, it collects enabled `thread_group` nodes and maps load:

```python
def kebab(name: str) -> str:
    import re
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "flow"


def load_from_normalized(normalized: dict[str, Any]) -> dict[str, Any]:
    model = normalized["model"]
    return {"model": model, "profile": "stages", "stages": normalized["stages"]}


def thread_groups(children: list[Any]) -> list[dict[str, Any]]:
    return [n for n in children if isinstance(n, dict) and n.get("kind") == "thread_group" and n.get("enabled", True)]


def add_finding(conv: Conversion, rule: str, message: str, element_id: str) -> None:
    conv.findings.append(Finding(rule=rule, message=message, severity="blocking", path=element_id))
```

In `convert`, after meta:

```python
    groups = thread_groups(ir.get("children", []))
    populations: list[dict[str, Any]] = []
    for tg in groups:
        normalized = (tg.get("load") or {}).get("normalized")
        if normalized is None:
            note = (tg.get("load") or {}).get("note") or "load could not be normalized"
            add_finding(conv, "convert.load-not-normalized", f"thread group '{tg.get('name')}' load not normalized: {note}", tg["id"])
            conv.record(tg, PARTIAL, note)
            load = {"model": "closed", "profile": "stages", "stages": [{"users": 1, "ramp_seconds": 0, "hold_seconds": 1}]}
        else:
            conv.record(tg, CONVERTED)
            load = load_from_normalized(normalized)
        population = {"name": kebab(tg.get("name", "flow")), "load": load, "steps": []}
        start_after = (normalized or {}).get("start_after_seconds") or 0
        if start_after > 0:
            population["start_after_seconds"] = start_after
        populations.append((tg, population))  # pair tg with its population for Task 3

    if len(populations) == 1:
        _, only = populations[0]
        scenario["steps"] = only["steps"]
        scenario["load"] = only["load"]
        if "start_after_seconds" in only:
            # single-flow has no population to delay; record as a finding for review
            add_finding(conv, "convert.single-flow-start-after-dropped",
                        "single thread group has an initial delay; not representable in single-flow form", groups[0]["id"])
    else:
        scenario["populations"] = [p for _tg, p in populations]
    conv._populations = populations  # stash for Task 3 step walk
```

Add `_populations: list = field(default_factory=list)` to `Conversion`. Remove the blanket `walk_children` todo-recording of thread groups (Task 3 will record their descendants); keep recording any top-level non-thread-group children as `todo`/`skipped` for now. Note: `_convert` test counts will be re-checked in Task 3 once descendants are walked.

- [ ] **Step 2.4: Run tests to verify they pass**

Run: `python tools/ir_to_scenario/test_ir_to_scenario.py` → PASS. (The Task-1 reconciliation test may need the Task-3 walk to balance; if it fails now because descendants under the TG aren't yet recorded, mark it `@unittest.expectedFailure` with a comment "balances after Task 3" and remove the marker in Task 3. Prefer to keep it green by recording TG descendants as `todo` in this task's walk.)

- [ ] **Step 2.5: Commit**

```powershell
git add tools/ir_to_scenario
git commit -m "feat: ir_to_scenario maps thread-group load to scenario load"
```

---

### Task 3: Structure walk — samplers → steps, controllers → disposition, transaction naming

Walk each thread group's subtree in document order. `http_sampler`/`jdbc_sampler`/`jsr223_sampler` become steps (filled in by Tasks 4/8). Container controllers (`transaction`, `simple`, `if`, `loop`, `once_only`, `throughput`, `fragment`, `module`) do not themselves become steps: `transaction`/`simple`/`fragment` are transparent groupings (recorded `converted`); `if`/`loop`/`once_only`/`throughput`/`module` are not representable in the flat 2b contract and are recorded `partial`/`todo` with a note (their sampler children still convert). Transaction-controller names seed the `NN domain.action - Title` transaction mask; the agent refines later.

**Files:** Modify `ir_to_scenario.py`; Test in `test_ir_to_scenario.py`.

- [ ] **Step 3.1: Write the failing tests**

```python
class StructureWalkTest(unittest.TestCase):
    def _steps(self, conv):
        s = conv.scenario["scenario"]
        return s.get("steps") or s["populations"][0]["steps"]

    def test_samplers_become_steps_in_order(self) -> None:
        tg = fixtures.thread_group("Main",
            [fixtures.http_sampler("open-home", path="/"), fixtures.http_sampler("submit", method="POST", path="/submit")],
            {"model": "closed", "stages": [{"users": 1, "ramp_seconds": 0, "hold_seconds": 10}], "start_after_seconds": 0})
        conv = ir_to_scenario.convert(fixtures.ir([tg]), system="SHOP", scenario_id="demo", number=1)
        steps = self._steps(conv)
        self.assertEqual([s["name"] for s in steps], ["open-home", "submit"])
        self.assertEqual(steps[0]["transaction"], "01 demo.open-home - open-home")

    def test_transaction_controller_seeds_step_names(self) -> None:
        txn = fixtures.element("transaction", "Checkout",
            children=[fixtures.http_sampler("submit", method="POST", path="/checkout")])
        tg = fixtures.thread_group("Main", [txn],
            {"model": "closed", "stages": [{"users": 1, "ramp_seconds": 0, "hold_seconds": 10}], "start_after_seconds": 0})
        conv = ir_to_scenario.convert(fixtures.ir([tg]), system="SHOP", scenario_id="demo", number=1)
        steps = self._steps(conv)
        self.assertEqual(steps[0]["transaction"], "01 demo.checkout - submit")

    def test_if_controller_recorded_partial_but_child_converts(self) -> None:
        cond = fixtures.element("if", "only-prod", condition="${env}=='prod'",
            children=[fixtures.http_sampler("guarded", path="/g")])
        tg = fixtures.thread_group("Main", [cond],
            {"model": "closed", "stages": [{"users": 1, "ramp_seconds": 0, "hold_seconds": 10}], "start_after_seconds": 0})
        conv = ir_to_scenario.convert(fixtures.ir([tg]), system="SHOP", scenario_id="demo", number=1)
        statuses = {r["kind"]: r["status"] for r in conv.report_rows}
        self.assertEqual(statuses["if"], "partial")
        self.assertEqual(statuses["http_sampler"], "converted")
        self.assertEqual(len(self._steps(conv)), 1)
```

- [ ] **Step 3.2: Run tests to verify they fail**

Run: `python tools/ir_to_scenario/test_ir_to_scenario.py` → FAIL (no steps populated / names wrong).

- [ ] **Step 3.3: Implement**

```python
SAMPLER_KINDS = {"http_sampler", "jdbc_sampler", "jsr223_sampler"}
TRANSPARENT = {"transaction", "simple", "fragment"}
UNREPRESENTABLE = {"if", "loop", "once_only", "throughput", "module"}


def kebab_seg(name: str) -> str:
    seg = kebab(name)
    return seg or "step"


def walk_steps(nodes: list[Any], conv: Conversion, steps: list[dict[str, Any]],
               domain: str, counter: list[int]) -> None:
    for node in nodes:
        if not isinstance(node, dict):
            continue
        kind = node.get("kind")
        if not node.get("enabled", True):
            conv.record(node, SKIPPED)
            continue
        if kind in SAMPLER_KINDS:
            counter[0] += 1
            step = build_step(node, conv, domain, counter[0])  # Tasks 4/8 fill protocol detail
            if step is not None:
                steps.append(step)
            continue
        if kind in TRANSPARENT:
            conv.record(node, CONVERTED)
            child_domain = kebab_seg(node.get("name", "")) if kind == "transaction" else domain
            walk_steps(node.get("children", []), conv, steps, child_domain, counter)
            continue
        if kind in UNREPRESENTABLE:
            conv.record(node, PARTIAL, f"{kind} controller flattened; semantics not represented in the flat contract")
            walk_steps(node.get("children", []), conv, steps, domain, counter)
            continue
        # config/extractor/assertion/timer/jsr223-processor elements: handled by
        # the owning sampler (Tasks 4/5/8) — record here so counts reconcile.
        record_non_step_element(node, conv, steps)


def build_step(node: dict[str, Any], conv: Conversion, domain: str, index: int) -> dict[str, Any] | None:
    name = kebab_seg(node.get("name", f"step-{index}"))
    transaction = f"{index:02d} {domain}.{name} - {node.get('name', name)}"
    step = {"name": name, "title": node.get("name", name), "transaction": transaction}
    fill_protocol(node, step, conv)   # defined in Tasks 4 (http), 8 (jdbc/jsr223)
    conv.record(node, CONVERTED)
    return step


def record_non_step_element(node: dict[str, Any], conv: Conversion, steps: list[dict[str, Any]]) -> None:
    # Placeholder until Tasks 5-8 attach these to steps. For now record todo so
    # nothing is dropped; later tasks change the status when they consume it.
    conv.record(node, TODO, "pending attach to step")


def fill_protocol(node: dict[str, Any], step: dict[str, Any], conv: Conversion) -> None:
    # http handled in Task 4; default stub keeps Task 3 self-contained.
    step["protocol"] = "http"
    step["request"] = {"method": node.get("method", "GET"), "path": node.get("url", {}).get("path") or "/"}
    step["checks"] = [{"status": 200}]
```

In `convert`, replace the stashed-walk with: for each `(tg, population)` pair, call `walk_steps(tg["children"], conv, population["steps"], kebab_seg(tg.get("name","")), counter=[0])`. Use a single shared `counter` across populations only if transaction numbering should be global — here use a per-population counter (reset per TG) so numbering restarts per population. Record the thread_group itself as already done in Task 2.

NOTE on `domain`: the transaction mask is `NN domain.action - Title`. `domain` defaults to the kebab of the enclosing transaction controller name (or thread-group name at top level). `action` is the kebab of the sampler name. The agent refines these in the passport; the tool only needs deterministic, lint-valid seeds. Verify the seed matches `tools/scenario_lint`'s `TRANSACTION_RE` (`^\d{2} [a-z][a-z0-9-]*\.[a-z][a-z0-9-]* - .+$`) — both `domain` and `action` must be kebab starting with a letter. If a name kebabs to empty or starts with a digit, fall back to `step`/`txn`.

- [ ] **Step 3.4: Run tests to verify they pass**

Run: `python tools/ir_to_scenario/test_ir_to_scenario.py` → PASS. Re-enable the Task-1 reconciliation test (remove any `expectedFailure`); confirm counts balance.

- [ ] **Step 3.5: Commit**

```powershell
git add tools/ir_to_scenario
git commit -m "feat: ir_to_scenario walks structure into steps with transaction seeds"
```

---

### Task 4: HTTP request mapping (method, URL, headers, body/body_file, params)

IR `http_sampler` fields: `method`, `url:{protocol,domain,port,path}`, `follow_redirects`, and one of `body:{variables,inline}` / `body:{variables,ref}` (raw post body) or `params:[{name,value,...}]` (form args) or `file_uploads`. Header values come from in-scope `header_manager` siblings; domain/port from a `http_defaults` element when the sampler leaves them blank. JMeter `${var}` stay as-is (the generator converts `${}`→`#{}`).

**Files:** Modify `ir_to_scenario.py`; Test in `test_ir_to_scenario.py`.

- [ ] **Step 4.1: Write the failing tests**

```python
class HttpStepTest(unittest.TestCase):
    def _one_step(self, sampler, extra_children=None):
        children = [sampler] + (extra_children or [])
        tg = fixtures.thread_group("Main", children,
            {"model": "closed", "stages": [{"users": 1, "ramp_seconds": 0, "hold_seconds": 10}], "start_after_seconds": 0})
        conv = ir_to_scenario.convert(fixtures.ir([tg]), system="SHOP", scenario_id="demo", number=1)
        s = conv.scenario["scenario"]
        return (s.get("steps") or s["populations"][0]["steps"])[0], conv

    def test_method_and_path(self) -> None:
        step, _ = self._one_step(fixtures.http_sampler("home", method="GET", path="/home"))
        self.assertEqual(step["request"]["method"], "GET")
        self.assertEqual(step["request"]["path"], "/home")

    def test_inline_body(self) -> None:
        sampler = fixtures.http_sampler("post", method="POST", path="/p",
            body={"variables": ["id"], "inline": '{"id":"${id}"}'})
        step, _ = self._one_step(sampler)
        self.assertEqual(step["request"]["body"], '{"id":"${id}"}')

    def test_external_body_becomes_body_file(self) -> None:
        sampler = fixtures.http_sampler("post", method="POST", path="/p",
            body={"variables": [], "ref": "bodies/abc123.json"})
        step, _ = self._one_step(sampler)
        self.assertEqual(step["request"]["body_file"], "bodies/abc123.json")
        self.assertNotIn("body", step["request"])

    def test_headers_from_sibling_manager(self) -> None:
        hm = fixtures.element("header_manager", "hdrs", headers={"Accept": "application/json"})
        step, _ = self._one_step(fixtures.http_sampler("home", path="/"), [hm])
        self.assertEqual(step["request"]["headers"], {"Accept": "application/json"})

    def test_form_params_recorded_partial(self) -> None:
        sampler = fixtures.http_sampler("form", method="POST", path="/f",
            params=[{"name": "a", "value": "1"}])
        step, conv = self._one_step(sampler)
        statuses = [r for r in conv.report_rows if r["id"] == sampler["id"]]
        self.assertEqual(statuses[0]["status"], "partial")
        self.assertIn("form params", statuses[0]["note"])
```

- [ ] **Step 4.2: Run tests to verify they fail**

Run: `python tools/ir_to_scenario/test_ir_to_scenario.py` → FAIL.

- [ ] **Step 4.3: Implement**

Replace `fill_protocol` with a real HTTP mapper, and propagate header/defaults context. Add to `walk_steps` a `context` dict carrying the active `header_manager` headers and `http_defaults` url (collected from sibling config elements before walking samplers in the same container):

```python
def collect_context(nodes: list[Any], parent: dict[str, Any]) -> dict[str, Any]:
    ctx = {"headers": dict(parent.get("headers", {})), "defaults": dict(parent.get("defaults", {}))}
    for node in nodes:
        if not isinstance(node, dict) or not node.get("enabled", True):
            continue
        if node.get("kind") == "header_manager":
            ctx["headers"].update(node.get("headers", {}))
        elif node.get("kind") == "http_defaults":
            ctx["defaults"] = node.get("url", {})
    return ctx
```

`walk_steps` computes `ctx = collect_context(nodes, parent_ctx)` at entry and passes it down. `fill_protocol` for http:

```python
def fill_http(node: dict[str, Any], step: dict[str, Any], conv: Conversion, ctx: dict[str, Any]) -> None:
    url = node.get("url", {})
    path = url.get("path") or "/"
    request: dict[str, Any] = {"method": (node.get("method") or "GET").upper(), "path": path}
    headers = ctx.get("headers") or {}
    if headers:
        request["headers"] = dict(headers)
    body = node.get("body")
    partial_note = ""
    if isinstance(body, dict) and "inline" in body:
        request["body"] = body["inline"]
    elif isinstance(body, dict) and "ref" in body:
        request["body_file"] = body["ref"]
    elif node.get("params"):
        partial_note = "form params not representable in the http contract; emitted as TODO body"
    if not node.get("follow_redirects", True):
        partial_note = (partial_note + "; " if partial_note else "") + "follow_redirects=false (disableFollowRedirect) not in contract"
    step["protocol"] = "http"
    step["request"] = request
    step["checks"] = []   # filled by Task 5; lint requires >=1 — Task 5 guarantees a status check fallback
    conv.record(node, PARTIAL if partial_note else CONVERTED, partial_note)
```

Update `build_step` so `fill_protocol` dispatches on kind: `http_sampler` → `fill_http`; others stubbed until Task 8. Remove the `conv.record(node, CONVERTED)` from `build_step` (the protocol filler now records, since it knows partial vs converted). Domain/port from `ctx["defaults"]` are not needed in `path` (base_url handles host) — if the sampler has an absolute `url.domain`, record a note (host pinned) but keep `path`.

NOTE: lint requires every http/graphql step to have ≥1 check. Task 5 adds checks; until then `checks: []` will fail lint but unit tests here assert on `request` only. Do not run lint on Task-4 output.

- [ ] **Step 4.4: Run tests to verify they pass**

Run: `python tools/ir_to_scenario/test_ir_to_scenario.py` → PASS.

- [ ] **Step 4.5: Commit**

```powershell
git add tools/ir_to_scenario
git commit -m "feat: ir_to_scenario maps http samplers to steps with headers and bodies"
```

---

### Task 5: Checks — response/json assertions + regex/jsonpath/boundary extractors

Extractor and assertion elements are children of their sampler. After building an http step, scan the sampler's `children` for: `response_assertion` (`field`, `test_type`, `patterns`) → status or substring check; `json_assertion` → substring/json check; `regex_extractor`/`jsonpath_extractor`/`boundary_extractor` → `checks[].extract`. A step with no status assertion gets a default `{status: 200}` so it lints.

**Files:** Modify `ir_to_scenario.py`; Test in `test_ir_to_scenario.py`.

- [ ] **Step 5.1: Write the failing tests**

```python
class ChecksTest(unittest.TestCase):
    def _step(self, sampler_children):
        sampler = fixtures.http_sampler("home", path="/")
        sampler["children"] = sampler_children
        tg = fixtures.thread_group("Main", [sampler],
            {"model": "closed", "stages": [{"users": 1, "ramp_seconds": 0, "hold_seconds": 10}], "start_after_seconds": 0})
        conv = ir_to_scenario.convert(fixtures.ir([tg]), system="SHOP", scenario_id="demo", number=1)
        s = conv.scenario["scenario"]
        return (s.get("steps") or s["populations"][0]["steps"])[0], conv

    def test_default_status_check_when_no_assertion(self) -> None:
        step, _ = self._step([])
        self.assertIn({"status": 200}, step["checks"])

    def test_regex_extractor_becomes_extract_check(self) -> None:
        ex = fixtures.element("regex_extractor", "csrf", variable="csrf",
            regex="name=csrf value=(.+?)", template="$1$", match_number="1", default="NF")
        step, conv = self._step([ex])
        extracts = [c for c in step["checks"] if "extract" in c]
        self.assertEqual(extracts[0]["extract"], {"type": "regex", "expr": "name=csrf value=(.+?)", "saveAs": "csrf"})

    def test_jsonpath_extractor_multi(self) -> None:
        ex = fixtures.element("jsonpath_extractor", "ids",
            extracts=[{"variable": "orderId", "expr": "$.id", "match_number": "1", "default": ""}])
        step, _ = self._step([ex])
        extracts = [c["extract"] for c in step["checks"] if "extract" in c]
        self.assertIn({"type": "jsonPath", "expr": "$.id", "saveAs": "orderId"}, extracts)

    def test_response_assertion_status(self) -> None:
        a = fixtures.element("response_assertion", "code", field="Assertion.response_code",
            test_type=8, patterns=["200"])
        step, _ = self._step([a])
        self.assertIn({"status": 200}, step["checks"])
```

- [ ] **Step 5.2: Run tests to verify they fail**

Run: `python tools/ir_to_scenario/test_ir_to_scenario.py` → FAIL.

- [ ] **Step 5.3: Implement**

```python
EXTRACT_TYPE = {"regex_extractor": "regex", "boundary_extractor": "boundary", "jsonpath_extractor": "jsonPath"}


def checks_from_children(sampler: dict[str, Any], conv: Conversion) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    has_status = False
    for child in sampler.get("children", []):
        if not isinstance(child, dict) or not child.get("enabled", True):
            if isinstance(child, dict) and not child.get("enabled", True):
                conv.record(child, SKIPPED)
            continue
        kind = child.get("kind")
        if kind == "regex_extractor":
            checks.append({"extract": {"type": "regex", "expr": child.get("regex", ""), "saveAs": child.get("variable", "")}})
            conv.record(child, CONVERTED)
        elif kind == "boundary_extractor":
            # boundary not a scenario extract type -> partial todo (no direct contract type)
            conv.record(child, PARTIAL, "boundary extractor has no direct contract type; translate manually")
        elif kind == "jsonpath_extractor":
            for ex in child.get("extracts", []):
                checks.append({"extract": {"type": "jsonPath", "expr": ex.get("expr", ""), "saveAs": ex.get("variable", "")}})
            conv.record(child, CONVERTED)
        elif kind == "response_assertion":
            if child.get("field") == "Assertion.response_code":
                for pat in child.get("patterns", []):
                    if pat.strip().isdigit():
                        checks.append({"status": int(pat.strip())})
                        has_status = True
                conv.record(child, CONVERTED)
            else:
                conv.record(child, PARTIAL, "non-status assertion; translate as a body check manually")
        elif kind == "json_assertion":
            conv.record(child, PARTIAL, "json assertion; translate manually")
    if not has_status:
        checks.insert(0, {"status": 200})
    return checks
```

In `fill_http`, set `step["checks"] = checks_from_children(node, conv)` instead of `[]`. Boundary extractor maps to `partial` because the scenario `extract.type` enum is `{css, jsonPath, regex}` (no boundary) — verify against `schemas/scenario.schema.json`; if a future contract adds boundary, revisit. The default `{status:200}` guarantees lint passes.

NOTE: extractor/assertion children are consumed here, so `record_non_step_element` must NOT also record them. Ensure `walk_steps` does not descend into sampler children (samplers are leaves for the step walk; their children are consumed by `checks_from_children`). Confirm `build_step`/`walk_steps` treats sampler nodes as leaves.

- [ ] **Step 5.4: Run tests to verify they pass**

Run: `python tools/ir_to_scenario/test_ir_to_scenario.py` → PASS.

- [ ] **Step 5.5: Commit**

```powershell
git add tools/ir_to_scenario
git commit -m "feat: ir_to_scenario maps assertions and extractors to checks"
```

---

### Task 6: Feeders (CSVDataSet) + environment (UDV → base_url/env)

`csv_data_set` fields: `file`, `variable_names` (list or `None`), `delimiter`, `recycle`, `stop_thread`, `share_mode`. Map to a `data.feeders[]` entry: `name` (kebab of element name or file stem), `file`, `strategy` (`recycle=true`→`circular`; `stop_thread=true`→`queue`; else `circular`). `user_defined_variables.values` map to env: a UDV named `BASE_URL`/`baseUrl`/host-like → `sut.base_url`; the rest are recorded as env-backed (no scenario field — documented in report).

**Files:** Modify `ir_to_scenario.py`; Test in `test_ir_to_scenario.py`.

- [ ] **Step 6.1: Write the failing tests**

```python
class FeederEnvTest(unittest.TestCase):
    def _convert(self, children):
        tg = fixtures.thread_group("Main", [fixtures.http_sampler("home", path="/")] ,
            {"model": "closed", "stages": [{"users": 1, "ramp_seconds": 0, "hold_seconds": 10}], "start_after_seconds": 0})
        tg["children"] = children + tg["children"]
        return ir_to_scenario.convert(fixtures.ir([tg]), system="SHOP", scenario_id="demo", number=1)

    def test_csv_becomes_feeder(self) -> None:
        csv = fixtures.element("csv_data_set", "users",
            file="users.csv", variable_names=["username", "password"], delimiter=",", recycle=True, stop_thread=False, share_mode="all")
        conv = self._convert([csv])
        feeders = conv.scenario["scenario"]["data"]["feeders"]
        self.assertEqual(feeders[0]["file"], "users.csv")
        self.assertEqual(feeders[0]["strategy"], "circular")

    def test_csv_stop_thread_is_queue(self) -> None:
        csv = fixtures.element("csv_data_set", "ids",
            file="ids.csv", variable_names=["id"], delimiter=",", recycle=False, stop_thread=True, share_mode="all")
        conv = self._convert([csv])
        self.assertEqual(conv.scenario["scenario"]["data"]["feeders"][0]["strategy"], "queue")

    def test_base_url_from_udv(self) -> None:
        udv = fixtures.element("user_defined_variables", "globals", values={"BASE_URL": "https://sut.example.com", "tenant": "acme"})
        conv = self._convert([udv])
        self.assertEqual(conv.scenario["scenario"]["sut"]["base_url"], "${BASE_URL}")
        rows = [r for r in conv.report_rows if r["id"] == udv["id"]]
        self.assertEqual(rows[0]["status"], "converted")
```

- [ ] **Step 6.2: Run tests to verify they fail**

Run: `python tools/ir_to_scenario/test_ir_to_scenario.py` → FAIL.

- [ ] **Step 6.3: Implement**

Collect CSV and UDV elements anywhere in the tree (they apply test-plan-wide in JMeter). Add a pre-pass over all elements:

```python
def iter_all(nodes: list[Any]):
    for node in nodes:
        if isinstance(node, dict):
            yield node
            yield from iter_all(node.get("children", []))


def feeder_strategy(csv: dict[str, Any]) -> str:
    if csv.get("stop_thread"):
        return "queue"
    return "circular"  # recycle true/false both loop in Gatling circular; queue only for stop_thread


def build_data_and_env(ir: dict[str, Any], scenario: dict[str, Any], conv: Conversion) -> None:
    feeders: list[dict[str, Any]] = []
    for node in iter_all(ir.get("children", [])):
        if not node.get("enabled", True):
            continue
        if node.get("kind") == "csv_data_set":
            stem = (node.get("file") or "feeder").rsplit("/", 1)[-1].rsplit(".", 1)[0]
            feeders.append({"name": kebab_seg(node.get("name") or stem), "file": node.get("file", ""), "strategy": feeder_strategy(node)})
            conv.record(node, CONVERTED if node.get("variable_names") else PARTIAL,
                        "" if node.get("variable_names") else "variableNames blank; columns inferred from CSV header at runtime")
        elif node.get("kind") == "user_defined_variables":
            values = node.get("values", {})
            if any(k in values for k in ("BASE_URL", "baseUrl", "base_url")):
                scenario["sut"]["base_url"] = "${BASE_URL}"
            conv.record(node, CONVERTED, "UDV mapped to env/base_url (values are env-backed; never inlined per NFR5)")
    if feeders:
        scenario["data"] = {"feeders": feeders}
```

Call `build_data_and_env(ir, scenario, conv)` in `convert` after the step walk. NOTE: CSV/UDV elements are nested under thread groups in the IR but apply test-wide; the `iter_all` pre-pass records them here, so `walk_steps`/`record_non_step_element` must SKIP `csv_data_set`/`user_defined_variables`/`http_defaults`/`header_manager`/`cookie_manager` (config elements) to avoid double-recording. Add those kinds to a `CONFIG_KINDS` set that `walk_steps` ignores (they are consumed by `collect_context` or `build_data_and_env`). Ensure each element is recorded exactly once — the reconciliation test in Task 9 enforces this.

- [ ] **Step 6.4: Run tests to verify they pass**

Run: `python tools/ir_to_scenario/test_ir_to_scenario.py` → PASS.

- [ ] **Step 6.5: Commit**

```powershell
git add tools/ir_to_scenario
git commit -m "feat: ir_to_scenario maps CSV feeders and UDV environment"
```

---

### Task 7: Timers → pauses; counters/random variables → partial; JMeter functions note

`constant_timer.delay_ms` and random timers (`offset_ms`/`range_ms`) become a `pause_seconds` on the **preceding** step (JMeter timers delay the next sampler; approximating to the prior step's pause is the documented behavior). `counter`/`random_variable` config elements produce session variables not representable in the flat contract → `partial` with a note. JMeter functions inside strings (`${__UUID}`, `${__P(x)}`, etc.) are left as-is in values but flagged in the report when unsupported (the agent/generator handles translation; `${__P(x)}`→env).

**Files:** Modify `ir_to_scenario.py`; Test in `test_ir_to_scenario.py`.

- [ ] **Step 7.1: Write the failing tests**

```python
class TimersCountersTest(unittest.TestCase):
    def _convert(self, tg_children):
        tg = fixtures.thread_group("Main", tg_children,
            {"model": "closed", "stages": [{"users": 1, "ramp_seconds": 0, "hold_seconds": 10}], "start_after_seconds": 0})
        return ir_to_scenario.convert(fixtures.ir([tg]), system="SHOP", scenario_id="demo", number=1)

    def test_constant_timer_becomes_pause_on_prior_step(self) -> None:
        conv = self._convert([
            fixtures.http_sampler("home", path="/"),
            fixtures.element("constant_timer", "wait", delay_ms="2000"),
            fixtures.http_sampler("next", path="/n"),
        ])
        s = conv.scenario["scenario"]
        steps = s.get("steps") or s["populations"][0]["steps"]
        self.assertEqual(steps[0]["pause_seconds"], 2)

    def test_counter_recorded_partial(self) -> None:
        conv = self._convert([fixtures.element("counter", "c", variable="n", start="1", increment="1", per_user=True),
                              fixtures.http_sampler("home", path="/")])
        rows = {r["kind"]: r["status"] for r in conv.report_rows}
        self.assertEqual(rows["counter"], "partial")
```

- [ ] **Step 7.2: Run tests to verify they fail**

Run: `python tools/ir_to_scenario/test_ir_to_scenario.py` → FAIL.

- [ ] **Step 7.3: Implement**

In `walk_steps`, handle timer and counter kinds. Track the last appended step so a timer can attach a pause to it:

```python
TIMER_KINDS = {"constant_timer", "uniform_random_timer", "gaussian_random_timer", "constant_throughput_timer"}


def timer_seconds(node: dict[str, Any]) -> float | None:
    raw = node.get("delay_ms") or node.get("offset_ms")
    try:
        ms = int(str(raw))
    except (TypeError, ValueError):
        return None
    return round(ms / 1000, 3) if ms > 0 else None
```

Within `walk_steps`, when `kind in TIMER_KINDS`: compute `secs = timer_seconds(node)`; if `steps` non-empty and `secs`, set `steps[-1]["pause_seconds"] = secs` and record `CONVERTED`; else record `PARTIAL` ("timer with no preceding step / non-numeric delay"). When `kind in {"counter","random_variable"}`: record `PARTIAL` ("counter/random variable not representable in the flat contract; translate via feeder or hook"). Add these kinds to the dispatch so they are NOT caught by `record_non_step_element`.

NOTE: `pause_seconds` must be a positive number per `schemas/scenario.schema.json`; `timer_seconds` returns `None` for 0/negative so no zero pause is emitted. Integral seconds emit as `int` (2 not 2.0) — `round(ms/1000,3)` gives `2.0`; coerce: `int(x) if x == int(x) else x`.

- [ ] **Step 7.4: Run tests to verify they pass**

Run: `python tools/ir_to_scenario/test_ir_to_scenario.py` → PASS.

- [ ] **Step 7.5: Commit**

```powershell
git add tools/ir_to_scenario
git commit -m "feat: ir_to_scenario maps timers to pauses; counters partial"
```

---

### Task 8: JSR223 → todo hooks; JDBC sampler → jdbc stub step

JSR223 elements (`jsr223_sampler` as a step; `jsr223_pre`/`jsr223_post` as a sampler child) are **never transpiled here** (Phase 2 decision: the agent translates JSR223). Each becomes a `hooks` entry with `kind: todo`, carrying `ref` (the IR `script_ref`), `summary` (from `name`/`script_preview`), `reads`, `writes`. `jsr223_pre`→`hooks.before`, `jsr223_post`→`hooks.after` on the owning step; a standalone `jsr223_sampler` becomes its own step whose only content is the todo hook (a no-op http step is wrong — instead emit a `protocol: jdbc`? no). For a standalone `jsr223_sampler` with no HTTP, emit a step with `protocol: jdbc` is incorrect; instead record it `todo` (cannot become a contract step on its own) and surface a finding. `jdbc_sampler` → `protocol: jdbc` stub step (`jdbc: {query, saveAs?}`) per Phase 2b.

**Files:** Modify `ir_to_scenario.py`; Test in `test_ir_to_scenario.py`.

- [ ] **Step 8.1: Write the failing tests**

```python
class JsrJdbcTest(unittest.TestCase):
    def _convert(self, tg_children):
        tg = fixtures.thread_group("Main", tg_children,
            {"model": "closed", "stages": [{"users": 1, "ramp_seconds": 0, "hold_seconds": 10}], "start_after_seconds": 0})
        return ir_to_scenario.convert(fixtures.ir([tg]), system="SHOP", scenario_id="demo", number=1)

    def test_jsr223_post_becomes_after_todo_hook(self) -> None:
        sampler = fixtures.http_sampler("home", path="/")
        sampler["children"] = [fixtures.element("jsr223_post", "sign", language="groovy",
            reads=["user"], writes=["sig"], props_reads=[], props_writes=[],
            classification="complex", classification_reasons=["uses props"], script_ref="jsr223/abc.groovy", script_preview="...")]
        conv = self._convert([sampler])
        s = conv.scenario["scenario"]
        step = (s.get("steps") or s["populations"][0]["steps"])[0]
        hook = step["hooks"]["after"][0]
        self.assertEqual(hook["kind"], "todo")
        self.assertEqual(hook["ref"], "jsr223/abc.groovy")
        self.assertEqual(hook["writes"], ["sig"])

    def test_jdbc_sampler_becomes_jdbc_stub(self) -> None:
        conv = self._convert([fixtures.element("jdbc_sampler", "lookup", query="SELECT 1", query_type="Select Statement", data_source="ds")])
        s = conv.scenario["scenario"]
        step = (s.get("steps") or s["populations"][0]["steps"])[0]
        self.assertEqual(step["protocol"], "jdbc")
        self.assertEqual(step["jdbc"]["query"], "SELECT 1")
```

- [ ] **Step 8.2: Run tests to verify they fail**

Run: `python tools/ir_to_scenario/test_ir_to_scenario.py` → FAIL.

- [ ] **Step 8.3: Implement**

```python
def todo_hook(node: dict[str, Any]) -> dict[str, Any]:
    summary = node.get("name") or (node.get("script_preview", "")[:60]) or "JSR223 script"
    hook = {"ref": node.get("script_ref") or node.get("script_file") or "jsr223/unknown.groovy",
            "kind": "todo", "summary": summary}
    if node.get("reads"):
        hook["reads"] = list(node["reads"])
    if node.get("writes"):
        hook["writes"] = list(node["writes"])
    return hook
```

In `checks_from_children`/step-children handling, when a sampler child is `jsr223_pre`/`jsr223_post`: append `todo_hook(child)` to `step.setdefault("hooks", {}).setdefault("before"/"after", [])` and record `CONVERTED` (the hook captures it; agent translates later). In `fill_protocol` dispatch: `jdbc_sampler` → `fill_jdbc` setting `step["protocol"]="jdbc"`, `step["jdbc"]={"query": node.get("query","")}` (+ `saveAs` only if a known output var — omit otherwise), no `checks`; record `PARTIAL` ("jdbc stub until protocol spike"). Standalone `jsr223_sampler` step → do not emit an http step; instead `conv.record(node, TODO, "standalone JSR223 sampler; no contract step")` and return `None` from `build_step` so it is skipped from `steps` (it is still counted). Ensure `build_step` returning `None` is handled in `walk_steps` (already: `if step is not None`).

Attribution note: the EL-side-effect rule and function handling come from Gatling's skill but apply in the *skill* (translation), not here.

- [ ] **Step 8.4: Run tests to verify they pass**

Run: `python tools/ir_to_scenario/test_ir_to_scenario.py` → PASS.

- [ ] **Step 8.5: Commit**

```powershell
git add tools/ir_to_scenario
git commit -m "feat: ir_to_scenario emits jsr223 todo hooks and jdbc stubs"
```

---

### Task 9: conversion-report.md + disposition reconciliation + CLI + idempotency + integration

Emit `scenario.yaml` and `conversion-report.md` to disk; the report lists every element with its disposition and totals; a reconciliation check asserts `sum(disposition_counts) == ir.stats.elements_total` and surfaces a blocking finding if not. Add CLI writing both files (idempotent: refuse to overwrite an existing `scenario.yaml` without `--force`, mirroring NFR6). Add a small end-to-end test that converts a realistic multi-element IR and lints the produced YAML.

**Files:** Modify `ir_to_scenario.py`; create `docs/MIGRATION.md`; Test in `test_ir_to_scenario.py`.

- [ ] **Step 9.1: Write the failing tests**

```python
class ReportReconcileTest(unittest.TestCase):
    def test_disposition_reconciles_with_stats(self) -> None:
        sampler = fixtures.http_sampler("home", path="/")
        sampler["children"] = [fixtures.element("regex_extractor", "csrf", variable="csrf", regex="(.+)", template="$1$", match_number="1", default="")]
        tg = fixtures.thread_group("Main", [sampler],
            {"model": "closed", "stages": [{"users": 1, "ramp_seconds": 0, "hold_seconds": 10}], "start_after_seconds": 0})
        doc = fixtures.ir([tg])
        conv = ir_to_scenario.convert(doc, system="SHOP", scenario_id="demo", number=1)
        self.assertEqual(sum(conv.disposition_counts().values()), doc["stats"]["elements_total"])
        self.assertNotIn("convert.disposition-mismatch", [f.rule for f in conv.findings])

    def test_report_markdown_has_table_and_totals(self) -> None:
        tg = fixtures.thread_group("Main", [fixtures.http_sampler("home", path="/")],
            {"model": "closed", "stages": [{"users": 1, "ramp_seconds": 0, "hold_seconds": 10}], "start_after_seconds": 0})
        conv = ir_to_scenario.convert(fixtures.ir([tg]), system="SHOP", scenario_id="demo", number=1)
        md = ir_to_scenario.render_report(conv, fixtures.ir([tg]))
        self.assertIn("| ID | Тип | Имя | Статус | Примечание |", md)
        self.assertIn("converted", md)

    def test_end_to_end_yaml_lints(self) -> None:
        # build a representative scenario, write it, and lint it
        import tempfile, subprocess
        sampler = fixtures.http_sampler("open-home", path="/")
        sampler["children"] = [fixtures.element("response_assertion", "code", field="Assertion.response_code", test_type=8, patterns=["200"])]
        tg = fixtures.thread_group("Main", [sampler],
            {"model": "closed", "stages": [{"users": 5, "ramp_seconds": 10, "hold_seconds": 60}], "start_after_seconds": 0})
        conv = ir_to_scenario.convert(fixtures.ir([tg]), system="SHOP", scenario_id="login-flow", number=2)
        import yaml as _yaml
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scenario.yaml"
            path.write_text(_yaml.safe_dump(conv.scenario, allow_unicode=True), encoding="utf-8")
            proc = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / "scenario_lint" / "scenario_lint.py"), str(path)],
                                  capture_output=True, text=True)
        # lint exits 0 (clean) or 1 (findings); the YAML must at least be schema-valid (no crash)
        self.assertIn(proc.returncode, (0, 1))
        self.assertNotIn("Traceback", proc.stderr)
```

- [ ] **Step 9.2: Run tests to verify they fail**

Run: `python tools/ir_to_scenario/test_ir_to_scenario.py` → FAIL (`render_report` missing; reconciliation finding logic missing).

- [ ] **Step 9.3: Implement**

Add reconciliation at the end of `convert`:

```python
    total = ir.get("stats", {}).get("elements_total", 0)
    counted = sum(conv.disposition_counts().values())
    if counted != total:
        add_finding(conv, "convert.disposition-mismatch",
                    f"recorded {counted} dispositions but IR has {total} elements (silent drop/double-count)", "stats")
```

Add `render_report`:

```python
def render_report(conv: Conversion, ir: dict[str, Any]) -> str:
    counts = conv.disposition_counts()
    lines = ["# Отчёт о конвертации", "",
             f"Элементов в IR: **{ir.get('stats', {}).get('elements_total', 0)}**.",
             "Сводка диспозиции: " + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())) + ".",
             "", "| ID | Тип | Имя | Статус | Примечание |", "|---|---|---|---|---|"]
    for row in conv.report_rows:
        note = row["note"].replace("|", "\\|")
        lines.append(f"| {row['id']} | {row['kind']} | {row['name']} | {row['status']} | {note} |")
    if conv.findings:
        lines += ["", "## Блокеры", ""] + [f"- `{f.rule}` — {f.message}" for f in conv.findings]
    return "\n".join(lines) + "\n"
```

Extend `main` to write outputs:

```python
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--force", action="store_true")
    ...
    out_dir = Path(args.out_dir)
    scenario_path = out_dir / "scenario.yaml"
    if scenario_path.exists() and not args.force:
        print(f"refusing to overwrite {scenario_path} (use --force)", file=sys.stderr)
        return 2
    import yaml
    out_dir.mkdir(parents=True, exist_ok=True)
    scenario_path.write_text(yaml.safe_dump(conv.scenario, allow_unicode=True, sort_keys=False), encoding="utf-8", newline="\n")
    (out_dir / "conversion-report.md").write_text(render_report(conv, ir), encoding="utf-8", newline="\n")
    blocking = [f for f in conv.findings if f.severity == "blocking"]
    return 1 if blocking else 0
```

Create `docs/MIGRATION.md` documenting: the tool's role in the pipeline, the four disposition statuses and what each means, the reconciliation guarantee, and the Apache-2.0 attribution to Gatling's `gatling-convert-from-jmeter` skill for the element-mapping rules.

- [ ] **Step 9.4: Run tests to verify they pass**

Run: `python tools/ir_to_scenario/test_ir_to_scenario.py` → PASS (all classes). Confirm the end-to-end test produces lint-valid YAML (no traceback).

- [ ] **Step 9.5: Commit**

```powershell
git add tools/ir_to_scenario docs/MIGRATION.md
git commit -m "feat: ir_to_scenario report, disposition reconciliation, and CLI"
```

---

## Self-review notes

- **Spec coverage (2c spec §4/§5/§6):** load (Task 2), steps/structure (Task 3), http request incl. body_file (Task 4), checks/extractors (Task 5), feeders+env (Task 6), timers/counters (Task 7), JSR223 todo hooks + jdbc stub (Task 8), conversion-report + reconciliation + CLI + idempotency (Task 9). Passport, Confluence, golden `.jmx` e2e, and the JSR223 *translation* belong to plan 2c-2 (skills) — out of scope here.
- **Deliberately deferred:** transaction-name refinement and kafka-via-proxy tagging are agent/skill concerns (2c-2): the tool only seeds lint-valid transaction names and emits plain HTTP steps; the skill applies the `kafka-via-proxy` tag and refines names. Boundary extractor and form params are recorded `partial` (no contract type) rather than invented.
- **Reconciliation invariant:** every element is recorded exactly once. Config kinds (`csv_data_set`, `user_defined_variables`, `http_defaults`, `header_manager`, `cookie_manager`) are consumed by `collect_context`/`build_data_and_env` and skipped by `walk_steps`; extractor/assertion/jsr223-processor children are consumed by `checks_from_children`; samplers/controllers/timers/counters by `walk_steps`. Task 9's reconciliation test is the backstop.
- **Type consistency:** `Conversion.record(element, status, note="")`, statuses are the four literals, `convert(...)` returns `Conversion`, `render_report(conv, ir)` — used consistently across tasks. `kebab`/`kebab_seg` produce lint-valid kebab-case for population and step names.
- **Naming for the generator:** step names must kebab-case to valid Java identifiers (Phase 2b `validate_step_name`); `kebab_seg` guarantees this. Population names likewise via `kebab`.

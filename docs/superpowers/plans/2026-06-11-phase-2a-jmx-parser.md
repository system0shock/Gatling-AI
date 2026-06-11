# Phase 2a: JMX Parser + IR Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deterministic streaming parser `tools/jmx_parser/` that turns a JMeter `.jmx` (up to ~200 MB) into a compact IR (`ir.json`), externalized request bodies, extracted+classified JSR223 scripts, a variable cross-reference, and a reviewer-facing `inventory.md` — the foundation both Phase 2 skills build on.

**Architecture:** Single-module tool in the repo's established style (stdlib only, tests next to the tool, runnable directly). XML is consumed via `xml.etree.ElementTree.iterparse` with aggressive `clear()` so memory is bounded by the largest single element, not file size. The agent never reads `.jmx` or the full `ir.json` — the CLI offers `summary`/`element` slices. Spec: `docs/superpowers/specs/2026-06-11-phase-2-migration-design.md` (sections 2, 7, 8). This is plan 1 of 3 for Phase 2 (2b: contract extensions, 2c: skills + golden e2e, plus the Kafka/JDBC spike).

**Tech Stack:** Python 3.11+ stdlib (PyYAML/jsonschema only where the repo already uses them); unittest run directly; no new dependencies.

**Verification commands** (run from repo root `F:\Coding\Gatling-AI`):

```powershell
python tools/jmx_parser/test_jmx_parser.py
python tools/_shared/test_common.py
python tools/scenario_lint/test_scenario_lint.py
python tools/test_contract_coverage.py
# perf check (opt-in, ~minutes):
$env:GATLING_AI_PERF = "1"; python tools/jmx_parser/test_jmx_parser_perf.py; Remove-Item Env:GATLING_AI_PERF
```

## File structure (final state)

```text
schemas/jmx-ir.schema.json              # NEW: versioned IR contract (Task 12)
tools/jmx_parser/jmx_parser.py          # NEW: walker, element builders, JSR223, index, inventory, CLI
tools/jmx_parser/fixtures.py            # NEW: test-only builders for small JMX documents
tools/jmx_parser/test_jmx_parser.py     # NEW: unit tests for everything above
tools/jmx_parser/test_jmx_parser_perf.py# NEW: env-gated ~150MB streaming budget test
tools/jmx_parser/README.md              # NEW: usage, IR overview, guarantees and limits
docs/ARCHITECTURE.md                    # updated: jmx_parser component row + structure
```

Parser output layout (all under `--out-dir`, normally `scenarios/<SYSTEM>/<id>-<NNN>/migration/`):

```text
<out-dir>/ir.json            # the IR; deterministic byte-for-byte across runs
<out-dir>/inventory.md       # Gate 1 review document
<out-dir>/bodies/<sha12>.json|.txt   # externalized big bodies, deduplicated by content hash
<out-dir>/jsr223/<sha12>.groovy      # extracted scripts, deduplicated by content hash
```

Note (small deviation from the spec layout sketch): extracted bodies live in `migration/bodies/`, not a root-level `bodies/` — one parser output root keeps re-runs and cleanup trivial, and `body_file` in plan 2c can reference `migration/bodies/...` (relative paths inside the scenario folder are exactly what the generator already supports for feeders).

Conventions for every task: tests are `unittest` classes in `tools/jmx_parser/test_jmx_parser.py`, run via `python tools/jmx_parser/test_jmx_parser.py`; each task ends with a commit. IR ordering rules everywhere: element ids `e-NNNN` in document order, every list either document-ordered or `sorted()`, `json.dumps(..., indent=2, sort_keys=True)` — two runs over the same file must produce identical bytes.

---

### Task 1: Walker skeleton — element/hashTree pairing, ids, unknown elements

**Files:**
- Create: `tools/jmx_parser/jmx_parser.py`
- Create: `tools/jmx_parser/fixtures.py`
- Create: `tools/jmx_parser/test_jmx_parser.py`

A `.jmx` is XML where each test element is followed by a sibling `<hashTree>` holding its children. The walker pairs them with a scope stack, assigns deterministic ids, and constructively guarantees "no silent drop": every element either maps to a known kind or lands in `unsupported`.

- [ ] **Step 1.1: Write the test fixtures module**

Create `tools/jmx_parser/fixtures.py`:

```python
#!/usr/bin/env python3
"""Builders for small JMX documents used by jmx_parser tests."""

from __future__ import annotations

from xml.sax.saxutils import escape


def jmx(*plan_children: str) -> str:
    """Wrap element snippets (already paired with their <hashTree/>) into a plan."""
    inner = "\n".join(plan_children)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<jmeterTestPlan version="1.2" properties="5.0" jmeter="5.6.3">\n'
        "  <hashTree>\n"
        '    <TestPlan guiclass="TestPlanGui" testclass="TestPlan" testname="Test Plan" enabled="true">\n'
        '      <stringProp name="TestPlan.comments">fixture plan</stringProp>\n'
        "    </TestPlan>\n"
        "    <hashTree>\n"
        f"{inner}\n"
        "    </hashTree>\n"
        "  </hashTree>\n"
        "</jmeterTestPlan>\n"
    )


def element(
    testclass: str,
    name: str,
    *,
    guiclass: str = "",
    enabled: bool = True,
    props: str = "",
    children: str = "",
) -> str:
    """A test element paired with its container hashTree (children go inside)."""
    gui = f' guiclass="{guiclass}"' if guiclass else ""
    flag = "true" if enabled else "false"
    return (
        f'<{testclass}{gui} testclass="{testclass}" testname="{escape(name)}" enabled="{flag}">\n'
        f"{props}\n"
        f"</{testclass}>\n"
        f"<hashTree>\n{children}\n</hashTree>"
    )


def string_prop(name: str, value: str) -> str:
    return f'  <stringProp name="{name}">{escape(value)}</stringProp>'


def bool_prop(name: str, value: bool) -> str:
    return f'  <boolProp name="{name}">{"true" if value else "false"}</boolProp>'


def thread_group(
    name: str = "TG",
    *,
    threads: int = 1,
    ramp: int = 0,
    duration: int = 0,
    delay: int = 0,
    enabled: bool = True,
    children: str = "",
) -> str:
    props = "\n".join(
        [
            string_prop("ThreadGroup.num_threads", str(threads)),
            string_prop("ThreadGroup.ramp_time", str(ramp)),
            string_prop("ThreadGroup.duration", str(duration)),
            string_prop("ThreadGroup.delay", str(delay)),
            bool_prop("ThreadGroup.scheduler", duration > 0 or delay > 0),
        ]
    )
    return element(
        "ThreadGroup", name, guiclass="ThreadGroupGui", enabled=enabled,
        props=props, children=children,
    )


def http_sampler(
    name: str = "request",
    *,
    method: str = "GET",
    path: str = "/",
    body: str | None = None,
    params: dict[str, str] | None = None,
    children: str = "",
) -> str:
    props = [
        string_prop("HTTPSampler.method", method),
        string_prop("HTTPSampler.path", path),
    ]
    if body is not None:
        props.append(bool_prop("HTTPSampler.postBodyRaw", True))
        props.append(
            '  <elementProp name="HTTPsampler.Arguments" elementType="Arguments">\n'
            '    <collectionProp name="Arguments.arguments">\n'
            '      <elementProp name="" elementType="HTTPArgument">\n'
            f'        <stringProp name="Argument.value">{escape(body)}</stringProp>\n'
            "      </elementProp>\n"
            "    </collectionProp>\n"
            "  </elementProp>"
        )
    elif params:
        rows = "\n".join(
            '      <elementProp name="" elementType="HTTPArgument">\n'
            f'        <stringProp name="Argument.name">{escape(key)}</stringProp>\n'
            f'        <stringProp name="Argument.value">{escape(value)}</stringProp>\n'
            "      </elementProp>"
            for key, value in params.items()
        )
        props.append(
            '  <elementProp name="HTTPsampler.Arguments" elementType="Arguments">\n'
            '    <collectionProp name="Arguments.arguments">\n'
            f"{rows}\n"
            "    </collectionProp>\n"
            "  </elementProp>"
        )
    return element(
        "HTTPSamplerProxy", name, guiclass="HttpTestSampleGui",
        props="\n".join(props), children=children,
    )
```

- [ ] **Step 1.2: Write the failing tests**

Create `tools/jmx_parser/test_jmx_parser.py`:

```python
#!/usr/bin/env python3
"""Unit tests for the JMX parser."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import fixtures
import jmx_parser


class ParserCase(unittest.TestCase):
    """Shared setup: write a fixture document, parse it into a temp out dir."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.out_dir = self.tmp / "out"

    def parse(self, document: str, **kwargs):
        jmx_path = self.tmp / "plan.jmx"
        jmx_path.write_text(document, encoding="utf-8")
        return jmx_parser.parse_jmx(jmx_path, self.out_dir, **kwargs)


class WalkerTest(ParserCase):
    def test_minimal_plan(self) -> None:
        ir = self.parse(fixtures.jmx())
        self.assertEqual(ir["version"], 1)
        self.assertEqual(ir["test_plan"]["name"], "Test Plan")
        self.assertEqual(ir["test_plan"]["comments"], "fixture plan")
        self.assertEqual(ir["children"], [])
        self.assertEqual(ir["unsupported"], [])
        self.assertEqual(ir["source"]["file"], "plan.jmx")
        self.assertEqual(len(ir["source"]["sha256"]), 64)
        self.assertGreater(ir["source"]["size_bytes"], 0)

    def test_unknown_element_is_recorded_not_dropped(self) -> None:
        ir = self.parse(fixtures.jmx(fixtures.element("com.example.WeirdSampler", "weird")))
        node = ir["children"][0]
        self.assertEqual(node["kind"], "unknown")
        self.assertEqual(node["type"], "com.example.WeirdSampler")
        self.assertEqual(node["name"], "weird")
        self.assertEqual(ir["unsupported"][0]["id"], node["id"])
        self.assertEqual(ir["unsupported"][0]["path"], ["Test Plan"])

    def test_ids_follow_document_order(self) -> None:
        ir = self.parse(
            fixtures.jmx(
                fixtures.element("com.example.A", "a"),
                fixtures.element("com.example.B", "b"),
            )
        )
        self.assertEqual([node["id"] for node in ir["children"]], ["e-0001", "e-0002"])

    def test_nesting_follows_hash_trees(self) -> None:
        ir = self.parse(
            fixtures.jmx(
                fixtures.element(
                    "com.example.Outer", "outer",
                    children=fixtures.element("com.example.Inner", "inner"),
                )
            )
        )
        outer = ir["children"][0]
        self.assertEqual(outer["children"][0]["name"], "inner")
        self.assertEqual(outer["children"][0]["path"], ["Test Plan", "outer"])

    def test_disabled_element_keeps_enabled_false(self) -> None:
        ir = self.parse(fixtures.jmx(fixtures.element("com.example.A", "a", enabled=False)))
        self.assertFalse(ir["children"][0]["enabled"])


if __name__ == "__main__":
    sys.exit(unittest.main())
```

- [ ] **Step 1.3: Run tests to verify they fail**

Run: `python tools/jmx_parser/test_jmx_parser.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'jmx_parser'`.

- [ ] **Step 1.4: Implement the walker**

Create `tools/jmx_parser/jmx_parser.py`:

```python
#!/usr/bin/env python3
"""Parse JMeter .jmx plans into a compact, deterministic IR for migration tooling.

Streaming contract: the document is consumed with iterparse and processed
elements are cleared immediately, so peak memory is bounded by the largest
single test element (in practice: the largest request body), not by file size.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

IR_VERSION = 1
DEFAULT_MAX_INLINE_BODY_BYTES = 1024
PREVIEW_CHARS = 200


@dataclass
class ParseState:
    out_dir: Path
    max_inline_body: int = DEFAULT_MAX_INLINE_BODY_BYTES
    counter: int = 0
    bodies: dict[str, str] = field(default_factory=dict)  # sha256 -> relative ref
    scripts: dict[str, str] = field(default_factory=dict)  # sha256 -> relative ref
    unsupported: list[dict[str, Any]] = field(default_factory=list)

    def next_id(self) -> str:
        self.counter += 1
        return f"e-{self.counter:04d}"


def string_prop(elem: ElementTree.Element, name: str, default: str = "") -> str:
    for child in elem.findall("stringProp"):
        if child.get("name") == name:
            return child.text or ""
    return default


def bool_prop(elem: ElementTree.Element, name: str, default: bool = False) -> bool:
    for child in elem.findall("boolProp"):
        if child.get("name") == name:
            return (child.text or "").strip().lower() == "true"
    return default


def int_prop(elem: ElementTree.Element, name: str, default: int | None = None) -> int | None:
    for child in elem.findall("intProp"):
        if child.get("name") == name:
            try:
                return int((child.text or "").strip())
            except ValueError:
                return default
    return default


KIND_BY_TESTCLASS: dict[str, str] = {}

DetailBuilder = Callable[[ElementTree.Element, "ParseState"], dict[str, Any]]
DETAIL_BUILDERS: dict[str, DetailBuilder] = {}


def resolve_kind(testclass: str, guiclass: str) -> str:
    return KIND_BY_TESTCLASS.get(testclass, "unknown")


def build_node(
    elem: ElementTree.Element, state: ParseState, path: list[str]
) -> dict[str, Any]:
    testclass = elem.get("testclass") or elem.tag
    kind = resolve_kind(testclass, elem.get("guiclass", ""))
    node: dict[str, Any] = {
        "id": state.next_id(),
        "kind": kind,
        "type": testclass,
        "name": elem.get("testname", ""),
        "enabled": elem.get("enabled", "true") != "false",
        "path": path,
        "children": [],
    }
    builder = DETAIL_BUILDERS.get(kind)
    if builder is not None:
        node.update(builder(elem, state))
    if kind == "unknown":
        state.unsupported.append(
            {"id": node["id"], "type": testclass, "name": node["name"], "path": path}
        )
    return node


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_jmx(
    jmx_path: Path,
    out_dir: Path,
    max_inline_body: int = DEFAULT_MAX_INLINE_BODY_BYTES,
) -> dict[str, Any]:
    state = ParseState(out_dir=out_dir, max_inline_body=max_inline_body)
    out_dir.mkdir(parents=True, exist_ok=True)
    test_plan: dict[str, Any] = {"name": "", "comments": ""}
    root_children: list[dict[str, Any]] = []
    scope_stack: list[list[dict[str, Any]]] = []
    name_stack: list[str] = []
    pending_children: list[dict[str, Any]] | None = None
    pending_name: str | None = None
    inner_depth = 0

    for event, elem in ElementTree.iterparse(str(jmx_path), events=("start", "end")):
        tag = elem.tag
        if tag == "jmeterTestPlan":
            if event == "end":
                elem.clear()
            continue
        if tag == "hashTree":
            if inner_depth:
                raise ValueError("malformed jmx: hashTree nested inside a test element")
            if event == "start":
                scope_stack.append(
                    pending_children if pending_children is not None else root_children
                )
                name_stack.append(pending_name or "")
                pending_children, pending_name = None, None
            else:
                scope_stack.pop()
                name_stack.pop()
                elem.clear()
            continue
        if event == "start":
            inner_depth += 1
            continue
        inner_depth -= 1
        if inner_depth:
            continue  # a prop inside a test element; handled by the element builder
        if tag == "TestPlan":
            test_plan = {
                "name": elem.get("testname", ""),
                "comments": string_prop(elem, "TestPlan.comments"),
            }
            pending_children, pending_name = root_children, elem.get("testname", "")
            elem.clear()
            continue
        breadcrumb = [part for part in name_stack if part]
        node = build_node(elem, state, breadcrumb)
        (scope_stack[-1] if scope_stack else root_children).append(node)
        pending_children, pending_name = node["children"], node["name"]
        elem.clear()

    return {
        "version": IR_VERSION,
        "source": {
            "file": jmx_path.name,
            "sha256": file_sha256(jmx_path),
            "size_bytes": jmx_path.stat().st_size,
        },
        "test_plan": test_plan,
        "children": root_children,
        "unsupported": state.unsupported,
    }
```

- [ ] **Step 1.5: Run tests to verify they pass**

Run: `python tools/jmx_parser/test_jmx_parser.py`
Expected: PASS, 0 failures.

- [ ] **Step 1.6: Commit**

```bash
git add tools/jmx_parser
git commit -m "feat: jmx_parser walker skeleton with deterministic ids and no-silent-drop"
```

---

### Task 2: Standard ThreadGroup and HTTP sampler details

**Files:**
- Modify: `tools/jmx_parser/jmx_parser.py`
- Modify: `tools/jmx_parser/test_jmx_parser.py`

- [ ] **Step 2.1: Write the failing tests**

Append to `tools/jmx_parser/test_jmx_parser.py` (before the `__main__` block):

```python
class ThreadGroupTest(ParserCase):
    def test_standard_thread_group_raw_load(self) -> None:
        ir = self.parse(fixtures.jmx(fixtures.thread_group("Main", threads=10, ramp=30)))
        node = ir["children"][0]
        self.assertEqual(node["kind"], "thread_group")
        self.assertEqual(node["flavor"], "standard")
        self.assertEqual(node["load"]["raw"]["num_threads"], "10")
        self.assertEqual(node["load"]["raw"]["ramp_time"], "30")


class HttpSamplerTest(ParserCase):
    def test_http_sampler_method_path_and_inline_body(self) -> None:
        ir = self.parse(
            fixtures.jmx(
                fixtures.thread_group(
                    "Main",
                    children=fixtures.http_sampler(
                        "checkout", method="POST", path="/checkout", body='{"a":1}'
                    ),
                )
            )
        )
        sampler = ir["children"][0]["children"][0]
        self.assertEqual(sampler["kind"], "http_sampler")
        self.assertEqual(sampler["method"], "POST")
        self.assertEqual(sampler["url"]["path"], "/checkout")
        self.assertEqual(sampler["body"], {"inline": '{"a":1}'})

    def test_http_sampler_query_params(self) -> None:
        ir = self.parse(
            fixtures.jmx(
                fixtures.thread_group(
                    "Main",
                    children=fixtures.http_sampler(
                        "search", path="/search", params={"q": "${term}"}
                    ),
                )
            )
        )
        sampler = ir["children"][0]["children"][0]
        self.assertNotIn("body", sampler)
        self.assertEqual(sampler["params"], [{"name": "q", "value": "${term}"}])
```

- [ ] **Step 2.2: Run tests to verify they fail**

Run: `python tools/jmx_parser/test_jmx_parser.py`
Expected: FAIL — `KeyError: 'flavor'` / kind is `unknown` for the new assertions; Task 1 tests still PASS.

- [ ] **Step 2.3: Implement**

In `tools/jmx_parser/jmx_parser.py` replace `KIND_BY_TESTCLASS: dict[str, str] = {}` with:

```python
THREAD_GROUP_FLAVORS: dict[str, str] = {
    "ThreadGroup": "standard",
    "kg.apc.jmeter.threads.UltimateThreadGroup": "ultimate",
    "kg.apc.jmeter.threads.SteppingThreadGroup": "stepping",
    "com.blazemeter.jmeter.threads.concurrency.ConcurrencyThreadGroup": "concurrency",
    "com.blazemeter.jmeter.threads.arrivals.ArrivalsThreadGroup": "arrivals",
}

KIND_BY_TESTCLASS: dict[str, str] = {
    **{testclass: "thread_group" for testclass in THREAD_GROUP_FLAVORS},
    "HTTPSamplerProxy": "http_sampler",
}
```

After `int_prop` add the detail builders and registration (the plugin flavors fill their raw fields in Task 8; until then they parse as standard-style raw with empty values, which is harmless because `normalized` does not exist yet):

```python
def thread_group_details(elem: ElementTree.Element, state: ParseState) -> dict[str, Any]:
    flavor = THREAD_GROUP_FLAVORS.get(elem.get("testclass") or elem.tag, "standard")
    raw = {
        "num_threads": string_prop(elem, "ThreadGroup.num_threads"),
        "ramp_time": string_prop(elem, "ThreadGroup.ramp_time"),
        "duration": string_prop(elem, "ThreadGroup.duration"),
        "delay": string_prop(elem, "ThreadGroup.delay"),
        "scheduler": bool_prop(elem, "ThreadGroup.scheduler"),
    }
    return {"flavor": flavor, "load": {"raw": raw}}


def store_body(text: str, state: ParseState) -> dict[str, Any]:
    return {"inline": text}


def raw_body_text(elem: ElementTree.Element) -> str | None:
    if not bool_prop(elem, "HTTPSampler.postBodyRaw"):
        return None
    for element_prop in elem.findall("elementProp"):
        if element_prop.get("name") != "HTTPsampler.Arguments":
            continue
        collection = element_prop.find("collectionProp")
        if collection is None:
            return ""
        for argument in collection.findall("elementProp"):
            value = string_prop(argument, "Argument.value", default="")
            return value
    return None


def http_arguments(elem: ElementTree.Element) -> list[dict[str, str]]:
    arguments: list[dict[str, str]] = []
    for element_prop in elem.findall("elementProp"):
        if element_prop.get("name") != "HTTPsampler.Arguments":
            continue
        collection = element_prop.find("collectionProp")
        if collection is None:
            continue
        for argument in collection.findall("elementProp"):
            arguments.append(
                {
                    "name": string_prop(argument, "Argument.name")
                    or (argument.get("name") or ""),
                    "value": string_prop(argument, "Argument.value"),
                }
            )
    return arguments


def http_sampler_details(elem: ElementTree.Element, state: ParseState) -> dict[str, Any]:
    details: dict[str, Any] = {
        "method": string_prop(elem, "HTTPSampler.method"),
        "url": {
            "protocol": string_prop(elem, "HTTPSampler.protocol"),
            "domain": string_prop(elem, "HTTPSampler.domain"),
            "port": string_prop(elem, "HTTPSampler.port"),
            "path": string_prop(elem, "HTTPSampler.path"),
        },
        "follow_redirects": bool_prop(elem, "HTTPSampler.follow_redirects", True),
    }
    body = raw_body_text(elem)
    if body is not None:
        details["body"] = store_body(body, state)
    else:
        params = http_arguments(elem)
        if params:
            details["params"] = params
    return details


DETAIL_BUILDERS.update(
    {
        "thread_group": thread_group_details,
        "http_sampler": http_sampler_details,
    }
)
```

- [ ] **Step 2.4: Run tests to verify they pass**

Run: `python tools/jmx_parser/test_jmx_parser.py`
Expected: PASS, 0 failures.

- [ ] **Step 2.5: Commit**

```bash
git add tools/jmx_parser
git commit -m "feat: jmx_parser reads standard thread groups and HTTP samplers"
```

---
### Task 3: Body externalization with dedup and variable scan

**Files:**
- Modify: `tools/jmx_parser/jmx_parser.py`
- Modify: `tools/jmx_parser/test_jmx_parser.py`

Bodies above the inline threshold go to `bodies/<sha12>.json|.txt`, deduplicated by content hash. Both inline and externalized records list the JMeter `${variables}` and `${__functions}` they reference, because the variable index (Task 9) must not re-read body files.

- [ ] **Step 3.1: Write the failing tests**

Append to `tools/jmx_parser/test_jmx_parser.py`:

```python
class BodyStoreTest(ParserCase):
    def sampler_with_body(self, body: str, name: str = "req") -> str:
        return fixtures.jmx(
            fixtures.thread_group(
                "Main",
                children=fixtures.http_sampler(name, method="POST", path="/x", body=body),
            )
        )

    def two_samplers_with_body(self, body: str) -> str:
        return fixtures.jmx(
            fixtures.thread_group(
                "Main",
                children="\n".join(
                    [
                        fixtures.http_sampler("a", method="POST", path="/x", body=body),
                        fixtures.http_sampler("b", method="POST", path="/y", body=body),
                    ]
                ),
            )
        )

    def test_small_body_stays_inline_with_variables(self) -> None:
        ir = self.parse(self.sampler_with_body('{"id":"${productId}","t":"${__time()}"}'))
        body = ir["children"][0]["children"][0]["body"]
        self.assertEqual(body["variables"], ["productId"])
        self.assertEqual(body["functions"], ["time"])
        self.assertIn("inline", body)

    def test_large_body_is_externalized(self) -> None:
        payload = '{"data":"' + "x" * 5000 + '","user":"${user}"}'
        ir = self.parse(self.sampler_with_body(payload))
        body = ir["children"][0]["children"][0]["body"]
        self.assertNotIn("inline", body)
        self.assertTrue(body["ref"].startswith("bodies/"))
        self.assertTrue(body["ref"].endswith(".json"))
        self.assertEqual(body["bytes"], len(payload.encode("utf-8")))
        self.assertEqual(body["variables"], ["user"])
        self.assertEqual(body["preview"], payload[:200])
        stored = (self.out_dir / body["ref"]).read_text(encoding="utf-8")
        self.assertEqual(stored, payload)

    def test_identical_bodies_are_deduplicated(self) -> None:
        payload = "y" * 5000
        ir = self.parse(self.two_samplers_with_body(payload))
        steps = ir["children"][0]["children"]
        self.assertEqual(steps[0]["body"]["ref"], steps[1]["body"]["ref"])
        self.assertTrue(steps[0]["body"]["ref"].endswith(".txt"))
        self.assertEqual(len(list((self.out_dir / "bodies").iterdir())), 1)

    def test_threshold_is_configurable(self) -> None:
        ir = self.parse(self.sampler_with_body("z" * 100), max_inline_body=10)
        self.assertIn("ref", ir["children"][0]["children"][0]["body"])
```

- [ ] **Step 3.2: Run tests to verify they fail**

Run: `python tools/jmx_parser/test_jmx_parser.py`
Expected: FAIL — `KeyError: 'variables'` and `'ref'` (everything is inline today).

- [ ] **Step 3.3: Implement**

In `tools/jmx_parser/jmx_parser.py` add after `PREVIEW_CHARS`:

```python
# ${var} but not ${__function(...)}; dots allow feeder-style names.
JMETER_VARIABLE_RE = re.compile(r"\$\{(?!__)([A-Za-z_][A-Za-z0-9_.-]*)\}")
JMETER_FUNCTION_RE = re.compile(r"\$\{__([A-Za-z]+)")


def jmeter_variables(text: str) -> list[str]:
    return sorted(set(JMETER_VARIABLE_RE.findall(text)))


def jmeter_functions(text: str) -> list[str]:
    return sorted(set(JMETER_FUNCTION_RE.findall(text)))


def body_extension(text: str) -> str:
    return ".json" if text.lstrip().startswith(("{", "[")) else ".txt"
```

Replace the Task 2 `store_body` stub with:

```python
def store_body(text: str, state: ParseState) -> dict[str, Any]:
    record: dict[str, Any] = {
        "variables": jmeter_variables(text),
        "functions": jmeter_functions(text),
    }
    encoded = text.encode("utf-8")
    if len(encoded) <= state.max_inline_body:
        record["inline"] = text
        return record
    sha = hashlib.sha256(encoded).hexdigest()
    ref = state.bodies.get(sha)
    if ref is None:
        bodies_dir = state.out_dir / "bodies"
        bodies_dir.mkdir(parents=True, exist_ok=True)
        ref = f"bodies/{sha[:12]}{body_extension(text)}"
        (state.out_dir / ref).write_text(text, encoding="utf-8", newline="\n")
        state.bodies[sha] = ref
    record.update(
        {"ref": ref, "bytes": len(encoded), "sha256": sha, "preview": text[:PREVIEW_CHARS]}
    )
    return record
```

- [ ] **Step 3.4: Run tests to verify they pass**

Run: `python tools/jmx_parser/test_jmx_parser.py`
Expected: PASS, 0 failures.

- [ ] **Step 3.5: Commit**

```bash
git add tools/jmx_parser
git commit -m "feat: jmx_parser externalizes large bodies with dedup and variable scan"
```

---

### Task 4: Controllers and Module Controller resolution

**Files:**
- Modify: `tools/jmx_parser/jmx_parser.py`
- Modify: `tools/jmx_parser/test_jmx_parser.py`

- [ ] **Step 4.1: Write the failing tests**

Append to `tools/jmx_parser/test_jmx_parser.py`:

```python
def module_controller(name: str, target_path: list[str]) -> str:
    rows = "\n".join(
        f'    <stringProp name="node_{index}">{value}</stringProp>'
        for index, value in enumerate(target_path)
    )
    props = (
        '  <collectionProp name="ModuleController.node_path">\n'
        f"{rows}\n"
        "  </collectionProp>"
    )
    return fixtures.element(
        "ModuleController", name, guiclass="ModuleControllerGui", props=props
    )


class ControllerTest(ParserCase):
    def test_transaction_and_simple_controllers(self) -> None:
        ir = self.parse(
            fixtures.jmx(
                fixtures.thread_group(
                    "Main",
                    children="\n".join(
                        [
                            fixtures.element(
                                "TransactionController", "Login",
                                props=fixtures.bool_prop("TransactionController.parent", True),
                                children=fixtures.http_sampler("post-login"),
                            ),
                            fixtures.element(
                                "IfController", "maybe",
                                props=fixtures.string_prop(
                                    "IfController.condition", '"${flag}" == "1"'
                                ),
                            ),
                            fixtures.element(
                                "LoopController", "thrice",
                                props=fixtures.string_prop("LoopController.loops", "3"),
                            ),
                            fixtures.element("OnceOnlyController", "setup"),
                            fixtures.element(
                                "ThroughputController", "half",
                                props=fixtures.string_prop(
                                    "ThroughputController.percentThroughput", "50.0"
                                ),
                            ),
                        ]
                    ),
                )
            )
        )
        children = ir["children"][0]["children"]
        kinds = [node["kind"] for node in children]
        self.assertEqual(kinds, ["transaction", "if", "loop", "once_only", "throughput"])
        self.assertTrue(children[0]["generate_parent_sample"])
        self.assertEqual(children[0]["children"][0]["kind"], "http_sampler")
        self.assertEqual(children[1]["condition"], '"${flag}" == "1"')
        self.assertEqual(children[2]["loops"], "3")
        self.assertEqual(children[4]["percent"], "50.0")
        self.assertEqual(ir["unsupported"], [])

    def test_module_controller_resolves_fragment(self) -> None:
        ir = self.parse(
            fixtures.jmx(
                fixtures.element(
                    "TestFragmentController", "Shared steps",
                    children=fixtures.http_sampler("shared-call"),
                ),
                fixtures.thread_group(
                    "Main",
                    children=module_controller("use shared", ["Test Plan", "Shared steps"]),
                ),
            )
        )
        fragment = ir["children"][0]
        module = ir["children"][1]["children"][0]
        self.assertEqual(fragment["kind"], "fragment")
        self.assertEqual(module["kind"], "module")
        self.assertEqual(module["target_path"], ["Test Plan", "Shared steps"])
        self.assertEqual(module["target_id"], fragment["id"])
        self.assertFalse(module["unresolved"])

    def test_module_controller_unresolved_target(self) -> None:
        ir = self.parse(
            fixtures.jmx(
                fixtures.thread_group(
                    "Main",
                    children=module_controller("dangling", ["Test Plan", "missing"]),
                )
            )
        )
        module = ir["children"][0]["children"][0]
        self.assertIsNone(module["target_id"])
        self.assertTrue(module["unresolved"])
```

- [ ] **Step 4.2: Run tests to verify they fail**

Run: `python tools/jmx_parser/test_jmx_parser.py`
Expected: FAIL — controller kinds resolve to `unknown`.

- [ ] **Step 4.3: Implement**

In `jmx_parser.py` extend `KIND_BY_TESTCLASS` (inside the existing literal, after the `HTTPSamplerProxy` entry):

```python
    "TransactionController": "transaction",
    "GenericController": "simple",
    "IfController": "if",
    "LoopController": "loop",
    "OnceOnlyController": "once_only",
    "ThroughputController": "throughput",
    "TestFragmentController": "fragment",
    "ModuleController": "module",
```

Add detail builders and the post-pass after `http_sampler_details`:

```python
def transaction_details(elem: ElementTree.Element, state: ParseState) -> dict[str, Any]:
    return {"generate_parent_sample": bool_prop(elem, "TransactionController.parent")}


def if_details(elem: ElementTree.Element, state: ParseState) -> dict[str, Any]:
    return {"condition": string_prop(elem, "IfController.condition")}


def loop_details(elem: ElementTree.Element, state: ParseState) -> dict[str, Any]:
    return {"loops": string_prop(elem, "LoopController.loops")}


def throughput_details(elem: ElementTree.Element, state: ParseState) -> dict[str, Any]:
    return {
        "style": int_prop(elem, "ThroughputController.style", 0),
        "percent": string_prop(elem, "ThroughputController.percentThroughput"),
        "max_executions": string_prop(elem, "ThroughputController.maxThroughput"),
    }


def module_details(elem: ElementTree.Element, state: ParseState) -> dict[str, Any]:
    target: list[str] = []
    for collection in elem.findall("collectionProp"):
        if collection.get("name") == "ModuleController.node_path":
            target = [(prop.text or "") for prop in collection.findall("stringProp")]
    return {"target_path": target, "target_id": None, "unresolved": True}


def resolve_modules(ir: dict[str, Any]) -> None:
    """Second phase: link module controllers to their targets by name path."""
    by_path: dict[tuple[str, ...], str] = {}
    plan_name = ir["test_plan"]["name"]

    def register(node: dict[str, Any], ancestors: list[str]) -> None:
        key = tuple([*ancestors, node["name"]])
        by_path.setdefault(key, node["id"])
        for child in node["children"]:
            register(child, [*ancestors, node["name"]])

    for child in ir["children"]:
        register(child, [plan_name])

    def visit(node: dict[str, Any]) -> None:
        if node["kind"] == "module":
            node["target_id"] = by_path.get(tuple(node["target_path"]))
            node["unresolved"] = node["target_id"] is None
        for child in node["children"]:
            visit(child)

    for child in ir["children"]:
        visit(child)


DETAIL_BUILDERS.update(
    {
        "transaction": transaction_details,
        "if": if_details,
        "loop": loop_details,
        "throughput": throughput_details,
        "module": module_details,
    }
)
```

In `parse_jmx`, build the result in a local variable and resolve modules before returning — replace `return {` ... `}` with:

```python
    ir = {
        "version": IR_VERSION,
        "source": {
            "file": jmx_path.name,
            "sha256": file_sha256(jmx_path),
            "size_bytes": jmx_path.stat().st_size,
        },
        "test_plan": test_plan,
        "children": root_children,
        "unsupported": state.unsupported,
    }
    resolve_modules(ir)
    return ir
```

- [ ] **Step 4.4: Run tests to verify they pass**

Run: `python tools/jmx_parser/test_jmx_parser.py`
Expected: PASS, 0 failures.

- [ ] **Step 4.5: Commit**

```bash
git add tools/jmx_parser
git commit -m "feat: jmx_parser controllers with module target resolution"
```

---
### Task 5: Config elements — CSV, UDV, HTTP defaults, headers, cookies, counters

**Files:**
- Modify: `tools/jmx_parser/jmx_parser.py`
- Modify: `tools/jmx_parser/test_jmx_parser.py`

- [ ] **Step 5.1: Write the failing tests**

Append to `tools/jmx_parser/test_jmx_parser.py`:

```python
def arguments_props(values: dict[str, str]) -> str:
    rows = "\n".join(
        '    <elementProp name="" elementType="Argument">\n'
        f'      <stringProp name="Argument.name">{key}</stringProp>\n'
        f'      <stringProp name="Argument.value">{value}</stringProp>\n'
        "    </elementProp>"
        for key, value in values.items()
    )
    return f'  <collectionProp name="Arguments.arguments">\n{rows}\n  </collectionProp>'


class ConfigElementTest(ParserCase):
    def test_csv_data_set(self) -> None:
        props = "\n".join(
            [
                fixtures.string_prop("filename", "users.csv"),
                fixtures.string_prop("variableNames", "login, password"),
                fixtures.string_prop("delimiter", ","),
                fixtures.bool_prop("recycle", True),
                fixtures.string_prop("shareMode", "shareMode.all"),
            ]
        )
        ir = self.parse(
            fixtures.jmx(fixtures.element("CSVDataSet", "users", props=props))
        )
        node = ir["children"][0]
        self.assertEqual(node["kind"], "csv_data_set")
        self.assertEqual(node["file"], "users.csv")
        self.assertEqual(node["variable_names"], ["login", "password"])
        self.assertTrue(node["recycle"])

    def test_user_defined_variables(self) -> None:
        ir = self.parse(
            fixtures.jmx(
                fixtures.element(
                    "Arguments", "Env", guiclass="ArgumentsPanel",
                    props=arguments_props({"host": "shop.local", "port": "8080"}),
                )
            )
        )
        node = ir["children"][0]
        self.assertEqual(node["kind"], "user_defined_variables")
        self.assertEqual(node["values"], {"host": "shop.local", "port": "8080"})

    def test_http_defaults_and_managers(self) -> None:
        defaults_props = "\n".join(
            [
                fixtures.string_prop("HTTPSampler.domain", "${host}"),
                fixtures.string_prop("HTTPSampler.port", "${port}"),
                fixtures.string_prop("HTTPSampler.protocol", "https"),
            ]
        )
        header_props = (
            '  <collectionProp name="HeaderManager.headers">\n'
            '    <elementProp name="" elementType="Header">\n'
            '      <stringProp name="Header.name">Content-Type</stringProp>\n'
            '      <stringProp name="Header.value">application/json</stringProp>\n'
            "    </elementProp>\n"
            "  </collectionProp>"
        )
        ir = self.parse(
            fixtures.jmx(
                fixtures.element(
                    "ConfigTestElement", "Defaults", guiclass="HttpDefaultsGui",
                    props=defaults_props,
                ),
                fixtures.element("HeaderManager", "Headers", props=header_props),
                fixtures.element("CookieManager", "Cookies"),
            )
        )
        defaults, headers, cookies = ir["children"]
        self.assertEqual(defaults["kind"], "http_defaults")
        self.assertEqual(defaults["url"]["domain"], "${host}")
        self.assertEqual(headers["kind"], "header_manager")
        self.assertEqual(headers["headers"], {"Content-Type": "application/json"})
        self.assertEqual(cookies["kind"], "cookie_manager")

    def test_counter_and_random_variable(self) -> None:
        counter_props = "\n".join(
            [
                fixtures.string_prop("CounterConfig.name", "orderNo"),
                fixtures.string_prop("CounterConfig.start", "1"),
                fixtures.string_prop("CounterConfig.incr", "1"),
            ]
        )
        random_props = "\n".join(
            [
                fixtures.string_prop("variableName", "rndUser"),
                fixtures.string_prop("minimumValue", "1"),
                fixtures.string_prop("maximumValue", "100"),
            ]
        )
        ir = self.parse(
            fixtures.jmx(
                fixtures.element("CounterConfig", "Counter", props=counter_props),
                fixtures.element("RandomVariableConfig", "Random", props=random_props),
            )
        )
        counter, random_var = ir["children"]
        self.assertEqual(counter["kind"], "counter")
        self.assertEqual(counter["variable"], "orderNo")
        self.assertEqual(random_var["kind"], "random_variable")
        self.assertEqual(random_var["variable"], "rndUser")
```

- [ ] **Step 5.2: Run tests to verify they fail**

Run: `python tools/jmx_parser/test_jmx_parser.py`
Expected: FAIL — all four new tests see kind `unknown`.

- [ ] **Step 5.3: Implement**

`Arguments` (UDV) and `ConfigTestElement` (HTTP defaults) need guiclass-aware resolution. Replace `resolve_kind` with:

```python
def resolve_kind(testclass: str, guiclass: str) -> str:
    if testclass == "ConfigTestElement":
        return "http_defaults" if guiclass == "HttpDefaultsGui" else "unknown"
    if testclass == "Arguments":
        return "user_defined_variables"
    return KIND_BY_TESTCLASS.get(testclass, "unknown")
```

Extend `KIND_BY_TESTCLASS` with:

```python
    "CSVDataSet": "csv_data_set",
    "HeaderManager": "header_manager",
    "CookieManager": "cookie_manager",
    "CounterConfig": "counter",
    "RandomVariableConfig": "random_variable",
```

Add detail builders (after `module_details`) and register them:

```python
def csv_details(elem: ElementTree.Element, state: ParseState) -> dict[str, Any]:
    names = string_prop(elem, "variableNames")
    return {
        "file": string_prop(elem, "filename"),
        "variable_names": [part.strip() for part in names.split(",") if part.strip()],
        "delimiter": string_prop(elem, "delimiter", ","),
        "recycle": bool_prop(elem, "recycle", True),
        "stop_thread": bool_prop(elem, "stopThread"),
        "share_mode": string_prop(elem, "shareMode"),
    }


def arguments_entries(elem: ElementTree.Element) -> dict[str, str]:
    entries: dict[str, str] = {}
    for collection in elem.findall("collectionProp"):
        if collection.get("name") != "Arguments.arguments":
            continue
        for argument in collection.findall("elementProp"):
            name = string_prop(argument, "Argument.name") or (argument.get("name") or "")
            if name:
                entries[name] = string_prop(argument, "Argument.value")
    return entries


def udv_details(elem: ElementTree.Element, state: ParseState) -> dict[str, Any]:
    return {"values": arguments_entries(elem)}


def http_defaults_details(elem: ElementTree.Element, state: ParseState) -> dict[str, Any]:
    return {
        "url": {
            "protocol": string_prop(elem, "HTTPSampler.protocol"),
            "domain": string_prop(elem, "HTTPSampler.domain"),
            "port": string_prop(elem, "HTTPSampler.port"),
            "path": string_prop(elem, "HTTPSampler.path"),
        }
    }


def header_manager_details(elem: ElementTree.Element, state: ParseState) -> dict[str, Any]:
    headers: dict[str, str] = {}
    for collection in elem.findall("collectionProp"):
        if collection.get("name") != "HeaderManager.headers":
            continue
        for header in collection.findall("elementProp"):
            name = string_prop(header, "Header.name")
            if name:
                headers[name] = string_prop(header, "Header.value")
    return {"headers": headers}


def cookie_manager_details(elem: ElementTree.Element, state: ParseState) -> dict[str, Any]:
    return {"clear_each_iteration": bool_prop(elem, "CookieManager.clearEachIteration")}


def counter_details(elem: ElementTree.Element, state: ParseState) -> dict[str, Any]:
    return {
        "variable": string_prop(elem, "CounterConfig.name"),
        "start": string_prop(elem, "CounterConfig.start"),
        "increment": string_prop(elem, "CounterConfig.incr"),
        "per_user": bool_prop(elem, "CounterConfig.per_user"),
    }


def random_variable_details(elem: ElementTree.Element, state: ParseState) -> dict[str, Any]:
    return {
        "variable": string_prop(elem, "variableName"),
        "minimum": string_prop(elem, "minimumValue"),
        "maximum": string_prop(elem, "maximumValue"),
        "per_thread": bool_prop(elem, "perThread"),
    }


DETAIL_BUILDERS.update(
    {
        "csv_data_set": csv_details,
        "user_defined_variables": udv_details,
        "http_defaults": http_defaults_details,
        "header_manager": header_manager_details,
        "cookie_manager": cookie_manager_details,
        "counter": counter_details,
        "random_variable": random_variable_details,
    }
)
```

- [ ] **Step 5.4: Run tests to verify they pass**

Run: `python tools/jmx_parser/test_jmx_parser.py`
Expected: PASS, 0 failures.

- [ ] **Step 5.5: Commit**

```bash
git add tools/jmx_parser
git commit -m "feat: jmx_parser config elements (csv, udv, defaults, headers, counters)"
```

---

### Task 6: Extractors, assertions, timers

**Files:**
- Modify: `tools/jmx_parser/jmx_parser.py`
- Modify: `tools/jmx_parser/test_jmx_parser.py`

- [ ] **Step 6.1: Write the failing tests**

Append to `tools/jmx_parser/test_jmx_parser.py`:

```python
class PostProcessorTest(ParserCase):
    def parse_sampler_children(self, children: str) -> list[dict]:
        ir = self.parse(
            fixtures.jmx(
                fixtures.thread_group(
                    "Main", children=fixtures.http_sampler("req", children=children)
                )
            )
        )
        return ir["children"][0]["children"][0]["children"]

    def test_regex_and_boundary_extractors(self) -> None:
        regex_props = "\n".join(
            [
                fixtures.string_prop("RegexExtractor.refname", "csrf"),
                fixtures.string_prop("RegexExtractor.regex", 'name="csrf" value="(.+?)"'),
                fixtures.string_prop("RegexExtractor.template", "$1$"),
                fixtures.string_prop("RegexExtractor.match_number", "1"),
                fixtures.string_prop("RegexExtractor.default", "NOT_FOUND"),
            ]
        )
        boundary_props = "\n".join(
            [
                fixtures.string_prop("BoundaryExtractor.refname", "token"),
                fixtures.string_prop("BoundaryExtractor.lboundary", "token="),
                fixtures.string_prop("BoundaryExtractor.rboundary", ";"),
            ]
        )
        nodes = self.parse_sampler_children(
            "\n".join(
                [
                    fixtures.element("RegexExtractor", "get csrf", props=regex_props),
                    fixtures.element("BoundaryExtractor", "get token", props=boundary_props),
                ]
            )
        )
        regex, boundary = nodes
        self.assertEqual(regex["kind"], "regex_extractor")
        self.assertEqual(regex["variable"], "csrf")
        self.assertEqual(regex["default"], "NOT_FOUND")
        self.assertEqual(boundary["kind"], "boundary_extractor")
        self.assertEqual(boundary["variable"], "token")

    def test_jsonpath_extractor_with_multiple_refs(self) -> None:
        props = "\n".join(
            [
                fixtures.string_prop("JSONPostProcessor.referenceNames", "id;price"),
                fixtures.string_prop(
                    "JSONPostProcessor.jsonPathExprs", "$.items[0].id;$.items[0].price"
                ),
                fixtures.string_prop("JSONPostProcessor.match_numbers", "1;1"),
                fixtures.string_prop("JSONPostProcessor.defaultValues", "MISSING;0"),
            ]
        )
        nodes = self.parse_sampler_children(
            fixtures.element("JSONPostProcessor", "ids", props=props)
        )
        node = nodes[0]
        self.assertEqual(node["kind"], "jsonpath_extractor")
        self.assertEqual(
            node["extracts"],
            [
                {"variable": "id", "expr": "$.items[0].id", "match_number": "1", "default": "MISSING"},
                {"variable": "price", "expr": "$.items[0].price", "match_number": "1", "default": "0"},
            ],
        )

    def test_assertions(self) -> None:
        response_props = (
            '  <collectionProp name="Asserion.test_strings">\n'
            '    <stringProp name="s0">200</stringProp>\n'
            "  </collectionProp>\n"
            + fixtures.string_prop("Assertion.test_field", "Assertion.response_code")
            + "\n"
            + '  <intProp name="Assertion.test_type">8</intProp>'
        )
        json_props = "\n".join(
            [
                fixtures.string_prop("JSON_PATH", "$.status"),
                fixtures.string_prop("EXPECTED_VALUE", "OK"),
                fixtures.bool_prop("JSONVALIDATION", True),
            ]
        )
        duration_props = fixtures.string_prop("DurationAssertion.duration", "2000")
        nodes = self.parse_sampler_children(
            "\n".join(
                [
                    fixtures.element("ResponseAssertion", "status 200", props=response_props),
                    fixtures.element("JSONPathAssertion", "status ok", props=json_props),
                    fixtures.element("DurationAssertion", "fast", props=duration_props),
                ]
            )
        )
        response, json_assert, duration = nodes
        self.assertEqual(response["kind"], "response_assertion")
        self.assertEqual(response["field"], "Assertion.response_code")
        self.assertEqual(response["patterns"], ["200"])
        self.assertEqual(response["test_type"], 8)
        self.assertEqual(json_assert["kind"], "json_assertion")
        self.assertEqual(json_assert["json_path"], "$.status")
        self.assertEqual(duration["kind"], "duration_assertion")
        self.assertEqual(duration["duration_ms"], "2000")

    def test_timers(self) -> None:
        constant = fixtures.element(
            "ConstantTimer", "wait",
            props=fixtures.string_prop("ConstantTimer.delay", "1000"),
        )
        uniform = fixtures.element(
            "UniformRandomTimer", "jitter",
            props="\n".join(
                [
                    fixtures.string_prop("ConstantTimer.delay", "500"),
                    fixtures.string_prop("RandomTimer.range", "1000"),
                ]
            ),
        )
        throughput = fixtures.element(
            "ConstantThroughputTimer", "pace",
            props=(
                "  <doubleProp>\n"
                "    <name>throughput</name>\n"
                "    <value>120.0</value>\n"
                "  </doubleProp>\n"
                '  <intProp name="calcMode">0</intProp>'
            ),
        )
        nodes = self.parse_sampler_children("\n".join([constant, uniform, throughput]))
        self.assertEqual(
            [node["kind"] for node in nodes],
            ["constant_timer", "uniform_random_timer", "constant_throughput_timer"],
        )
        self.assertEqual(nodes[0]["delay_ms"], "1000")
        self.assertEqual(nodes[1]["range_ms"], "1000")
        self.assertEqual(nodes[2]["throughput_per_min"], "120.0")
```

- [ ] **Step 6.2: Run tests to verify they fail**

Run: `python tools/jmx_parser/test_jmx_parser.py`
Expected: FAIL — new kinds resolve to `unknown`.

- [ ] **Step 6.3: Implement**

Extend `KIND_BY_TESTCLASS` with:

```python
    "RegexExtractor": "regex_extractor",
    "JSONPostProcessor": "jsonpath_extractor",
    "BoundaryExtractor": "boundary_extractor",
    "ResponseAssertion": "response_assertion",
    "JSONPathAssertion": "json_assertion",
    "DurationAssertion": "duration_assertion",
    "ConstantTimer": "constant_timer",
    "UniformRandomTimer": "uniform_random_timer",
    "GaussianRandomTimer": "gaussian_random_timer",
    "ConstantThroughputTimer": "constant_throughput_timer",
```

Add the `doubleProp` helper next to `int_prop` (JMeter stores it with child tags, not attributes):

```python
def double_prop(elem: ElementTree.Element, name: str, default: str = "") -> str:
    for child in elem.findall("doubleProp"):
        name_node = child.find("name")
        if name_node is not None and (name_node.text or "") == name:
            value_node = child.find("value")
            return (value_node.text or "") if value_node is not None else default
    return default
```

Add detail builders and register them:

```python
def split_list(value: str) -> list[str]:
    return value.split(";") if value else []


def regex_extractor_details(elem: ElementTree.Element, state: ParseState) -> dict[str, Any]:
    return {
        "variable": string_prop(elem, "RegexExtractor.refname"),
        "regex": string_prop(elem, "RegexExtractor.regex"),
        "template": string_prop(elem, "RegexExtractor.template"),
        "match_number": string_prop(elem, "RegexExtractor.match_number"),
        "default": string_prop(elem, "RegexExtractor.default"),
    }


def jsonpath_extractor_details(elem: ElementTree.Element, state: ParseState) -> dict[str, Any]:
    names = split_list(string_prop(elem, "JSONPostProcessor.referenceNames"))
    exprs = split_list(string_prop(elem, "JSONPostProcessor.jsonPathExprs"))
    matches = split_list(string_prop(elem, "JSONPostProcessor.match_numbers"))
    defaults = split_list(string_prop(elem, "JSONPostProcessor.defaultValues"))
    extracts = [
        {
            "variable": name.strip(),
            "expr": exprs[index].strip() if index < len(exprs) else "",
            "match_number": matches[index].strip() if index < len(matches) else "",
            "default": defaults[index].strip() if index < len(defaults) else "",
        }
        for index, name in enumerate(names)
        if name.strip()
    ]
    return {"extracts": extracts}


def boundary_extractor_details(elem: ElementTree.Element, state: ParseState) -> dict[str, Any]:
    return {
        "variable": string_prop(elem, "BoundaryExtractor.refname"),
        "left": string_prop(elem, "BoundaryExtractor.lboundary"),
        "right": string_prop(elem, "BoundaryExtractor.rboundary"),
        "match_number": string_prop(elem, "BoundaryExtractor.match_number"),
        "default": string_prop(elem, "BoundaryExtractor.default"),
    }


def response_assertion_details(elem: ElementTree.Element, state: ParseState) -> dict[str, Any]:
    patterns: list[str] = []
    for collection in elem.findall("collectionProp"):
        if collection.get("name") == "Asserion.test_strings":  # sic: JMeter's own typo
            patterns = [(prop.text or "") for prop in collection.findall("stringProp")]
    return {
        "field": string_prop(elem, "Assertion.test_field"),
        "test_type": int_prop(elem, "Assertion.test_type", 0),
        "patterns": patterns,
    }


def json_assertion_details(elem: ElementTree.Element, state: ParseState) -> dict[str, Any]:
    return {
        "json_path": string_prop(elem, "JSON_PATH"),
        "expected": string_prop(elem, "EXPECTED_VALUE"),
        "validate": bool_prop(elem, "JSONVALIDATION"),
    }


def duration_assertion_details(elem: ElementTree.Element, state: ParseState) -> dict[str, Any]:
    return {"duration_ms": string_prop(elem, "DurationAssertion.duration")}


def constant_timer_details(elem: ElementTree.Element, state: ParseState) -> dict[str, Any]:
    return {"delay_ms": string_prop(elem, "ConstantTimer.delay")}


def random_timer_details(elem: ElementTree.Element, state: ParseState) -> dict[str, Any]:
    return {
        "offset_ms": string_prop(elem, "ConstantTimer.delay"),
        "range_ms": string_prop(elem, "RandomTimer.range"),
    }


def constant_throughput_timer_details(
    elem: ElementTree.Element, state: ParseState
) -> dict[str, Any]:
    return {
        "throughput_per_min": double_prop(elem, "throughput"),
        "calc_mode": int_prop(elem, "calcMode", 0),
    }


DETAIL_BUILDERS.update(
    {
        "regex_extractor": regex_extractor_details,
        "jsonpath_extractor": jsonpath_extractor_details,
        "boundary_extractor": boundary_extractor_details,
        "response_assertion": response_assertion_details,
        "json_assertion": json_assertion_details,
        "duration_assertion": duration_assertion_details,
        "constant_timer": constant_timer_details,
        "uniform_random_timer": random_timer_details,
        "gaussian_random_timer": random_timer_details,
        "constant_throughput_timer": constant_throughput_timer_details,
    }
)
```

- [ ] **Step 6.4: Run tests to verify they pass**

Run: `python tools/jmx_parser/test_jmx_parser.py`
Expected: PASS, 0 failures.

- [ ] **Step 6.5: Commit**

```bash
git add tools/jmx_parser
git commit -m "feat: jmx_parser extractors, assertions and timers"
```

---
### Task 7: JSR223 extraction and classification

**Files:**
- Modify: `tools/jmx_parser/jmx_parser.py`
- Modify: `tools/jmx_parser/test_jmx_parser.py`

Every JSR223 script is written to `jsr223/<sha12>.groovy` (deduplicated by hash, like bodies). The classifier is deliberately conservative: a script is `typical` only when every identifier is on the allowlist or locally declared — misclassifying toward `complex` just costs one extra review, misclassifying toward `typical` could silently lose business logic. `props` usage always means `complex` (inter-thread state). BeanShell elements stay `unknown`/unsupported by design (the park uses JSR223; revisit only if real runs disagree).

- [ ] **Step 7.1: Write the failing tests**

Append to `tools/jmx_parser/test_jmx_parser.py`:

```python
def jsr223(testclass: str, name: str, script: str, language: str = "groovy") -> str:
    props = "\n".join(
        [
            fixtures.string_prop("script", script),
            fixtures.string_prop("scriptLanguage", language),
        ]
    )
    return fixtures.element(testclass, name, props=props)


class Jsr223Test(ParserCase):
    def parse_pre(self, script: str) -> dict:
        ir = self.parse(
            fixtures.jmx(
                fixtures.thread_group(
                    "Main",
                    children=fixtures.http_sampler(
                        "req", children=jsr223("JSR223PreProcessor", "prep", script)
                    ),
                )
            )
        )
        return ir["children"][0]["children"][0]["children"][0]

    def test_typical_uuid_script(self) -> None:
        node = self.parse_pre(
            'def rid = UUID.randomUUID().toString()\nvars.put("requestId", rid)'
        )
        self.assertEqual(node["kind"], "jsr223_pre")
        self.assertEqual(node["classification"], "typical")
        self.assertEqual(node["classification_reasons"], [])
        self.assertEqual(node["writes"], ["requestId"])
        self.assertEqual(node["reads"], [])
        self.assertTrue(node["script_ref"].startswith("jsr223/"))
        stored = (self.out_dir / node["script_ref"]).read_text(encoding="utf-8")
        self.assertIn("randomUUID", stored)

    def test_props_usage_is_complex(self) -> None:
        node = self.parse_pre('props.put("sharedToken", vars.get("token"))')
        self.assertEqual(node["classification"], "complex")
        self.assertIn("uses props (inter-thread state)", node["classification_reasons"])
        self.assertEqual(node["props_writes"], ["sharedToken"])
        self.assertEqual(node["reads"], ["token"])

    def test_unknown_api_is_complex_with_reason(self) -> None:
        node = self.parse_pre(
            'def signed = SignerUtil.hmac(vars.get("body"))\nvars.put("sig", signed)'
        )
        self.assertEqual(node["classification"], "complex")
        self.assertTrue(
            any("SignerUtil" in reason for reason in node["classification_reasons"])
        )

    def test_external_script_file_is_complex(self) -> None:
        ir = self.parse(
            fixtures.jmx(
                fixtures.thread_group(
                    "Main",
                    children=fixtures.element(
                        "JSR223Sampler", "ext",
                        props=fixtures.string_prop("filename", "scripts/do_stuff.groovy"),
                    ),
                )
            )
        )
        node = ir["children"][0]["children"][0]
        self.assertEqual(node["kind"], "jsr223_sampler")
        self.assertEqual(node["script_file"], "scripts/do_stuff.groovy")
        self.assertEqual(node["classification"], "complex")
        self.assertEqual(node["classification_reasons"], ["external script file"])

    def test_identical_scripts_share_one_file(self) -> None:
        script = 'vars.put("ts", String.valueOf(System.currentTimeMillis()))'
        ir = self.parse(
            fixtures.jmx(
                fixtures.thread_group(
                    "Main",
                    children="\n".join(
                        [
                            fixtures.http_sampler(
                                "a", children=jsr223("JSR223PreProcessor", "p1", script)
                            ),
                            fixtures.http_sampler(
                                "b", children=jsr223("JSR223PreProcessor", "p2", script)
                            ),
                        ]
                    ),
                )
            )
        )
        steps = ir["children"][0]["children"]
        ref_a = steps[0]["children"][0]["script_ref"]
        ref_b = steps[1]["children"][0]["script_ref"]
        self.assertEqual(ref_a, ref_b)
        self.assertEqual(len(list((self.out_dir / "jsr223").iterdir())), 1)

    def test_jdbc_sampler_is_recognized_for_stub_conversion(self) -> None:
        ir = self.parse(
            fixtures.jmx(
                fixtures.thread_group(
                    "Main",
                    children=fixtures.element(
                        "JDBCSampler", "check balance",
                        props=fixtures.string_prop("query", "SELECT 1"),
                    ),
                )
            )
        )
        node = ir["children"][0]["children"][0]
        self.assertEqual(node["kind"], "jdbc_sampler")
        self.assertEqual(node["query"], "SELECT 1")
        self.assertEqual(ir["unsupported"], [])
```

- [ ] **Step 7.2: Run tests to verify they fail**

Run: `python tools/jmx_parser/test_jmx_parser.py`
Expected: FAIL — JSR223 kinds resolve to `unknown`.

- [ ] **Step 7.3: Implement**

Extend `KIND_BY_TESTCLASS` with:

```python
    "JSR223Sampler": "jsr223_sampler",
    "JSR223PreProcessor": "jsr223_pre",
    "JSR223PostProcessor": "jsr223_post",
    "JDBCSampler": "jdbc_sampler",
```

(`jdbc_sampler` rides along here: it is "recognized, converts to a TODO stub" per the spec — recognition is just the kind mapping plus a query field.)

Add after the timer builders:

```python
VARS_CALL_RE = re.compile(
    r"vars\.(get|put|getObject|putObject)\s*\(\s*[\"']([^\"']+)[\"']"
)
PROPS_CALL_RE = re.compile(r"props\.(get|put)\s*\(\s*[\"']([^\"']+)[\"']")
GROOVY_COMMENT_RE = re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL)
GROOVY_STRING_RE = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"")
IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
DECLARED_RE = re.compile(
    r"\bdef\s+([A-Za-z_][A-Za-z0-9_]*)|\b([A-Za-z_][A-Za-z0-9_]*)\s*=(?!=)"
)

# Identifiers a "typical" (mechanically translatable) script may use. Anything
# else marks the script complex; conservative misclassification only costs an
# extra review in the conversion pass.
TYPICAL_TOKENS = frozenset(
    {
        # groovy/java keywords and literals
        "def", "if", "else", "return", "true", "false", "null", "new",
        "int", "long", "boolean", "String", "void",
        # JMeter session variables
        "vars", "get", "put",
        # safe value generation
        "UUID", "randomUUID", "toString", "System", "currentTimeMillis", "nanoTime",
        "Math", "abs", "max", "min", "random", "Random", "nextInt",
        "Integer", "Long", "parseInt", "parseLong", "valueOf",
        # simple string/JSON assembly
        "concat", "trim", "replace", "substring", "length", "split", "contains",
        "equals", "isEmpty", "format", "groovy", "json", "JsonOutput", "toJson",
    }
)


def classify_script(script: str) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if PROPS_CALL_RE.search(script):
        reasons.append("uses props (inter-thread state)")
    stripped = GROOVY_COMMENT_RE.sub(" ", script)
    stripped = GROOVY_STRING_RE.sub(" ", stripped)
    declared = {
        match.group(1) or match.group(2) for match in DECLARED_RE.finditer(stripped)
    }
    foreign = sorted(
        {
            token
            for token in IDENTIFIER_RE.findall(stripped)
            if token not in TYPICAL_TOKENS and token not in declared and token != "props"
        }
    )
    if foreign:
        reasons.append("unrecognized tokens: " + ", ".join(foreign[:8]))
    return ("complex" if reasons else "typical", reasons)


def write_script(script: str, state: ParseState) -> str:
    encoded = script.encode("utf-8")
    sha = hashlib.sha256(encoded).hexdigest()
    ref = state.scripts.get(sha)
    if ref is None:
        scripts_dir = state.out_dir / "jsr223"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        ref = f"jsr223/{sha[:12]}.groovy"
        (state.out_dir / ref).write_text(script, encoding="utf-8", newline="\n")
        state.scripts[sha] = ref
    return ref


def jsr223_details(elem: ElementTree.Element, state: ParseState) -> dict[str, Any]:
    script = string_prop(elem, "script")
    details: dict[str, Any] = {
        "language": string_prop(elem, "scriptLanguage", "groovy") or "groovy",
        "reads": sorted(
            {name for verb, name in VARS_CALL_RE.findall(script) if verb.startswith("get")}
        ),
        "writes": sorted(
            {name for verb, name in VARS_CALL_RE.findall(script) if verb.startswith("put")}
        ),
        "props_reads": sorted(
            {name for verb, name in PROPS_CALL_RE.findall(script) if verb == "get"}
        ),
        "props_writes": sorted(
            {name for verb, name in PROPS_CALL_RE.findall(script) if verb == "put"}
        ),
    }
    file_ref = string_prop(elem, "filename")
    if file_ref:
        details["script_file"] = file_ref
        details["classification"] = "complex"
        details["classification_reasons"] = ["external script file"]
        return details
    classification, reasons = classify_script(script)
    details["classification"] = classification
    details["classification_reasons"] = reasons
    details["script_ref"] = write_script(script, state)
    details["script_preview"] = script[:PREVIEW_CHARS]
    return details


def jdbc_sampler_details(elem: ElementTree.Element, state: ParseState) -> dict[str, Any]:
    return {
        "query": string_prop(elem, "query"),
        "query_type": string_prop(elem, "queryType"),
        "data_source": string_prop(elem, "dataSource"),
    }


DETAIL_BUILDERS.update(
    {
        "jsr223_sampler": jsr223_details,
        "jsr223_pre": jsr223_details,
        "jsr223_post": jsr223_details,
        "jdbc_sampler": jdbc_sampler_details,
    }
)
```

- [ ] **Step 7.4: Run tests to verify they pass**

Run: `python tools/jmx_parser/test_jmx_parser.py`
Expected: PASS, 0 failures.

- [ ] **Step 7.5: Commit**

```bash
git add tools/jmx_parser
git commit -m "feat: jmx_parser extracts and classifies JSR223 scripts"
```

---

### Task 8: Load normalization — plugin thread groups to stages

**Files:**
- Modify: `tools/jmx_parser/jmx_parser.py`
- Modify: `tools/jmx_parser/test_jmx_parser.py`

Every thread group gets `load.raw` (always, traceability) plus `load.normalized` — either `{model, stages[], start_after_seconds}` or `null` with `load.normalization_note` explaining why (parameterized `${...}` values, multi-row Ultimate schedules). Honest `null` beats a lossy guess: the conversion pass surfaces it as a review item.

- [ ] **Step 8.1: Write the failing tests**

Append to `tools/jmx_parser/test_jmx_parser.py`:

```python
def plugin_thread_group(testclass: str, guiclass: str, props: str, name: str = "TG") -> str:
    return fixtures.element(testclass, name, guiclass=guiclass, props=props)


class LoadNormalizationTest(ParserCase):
    def load_of_first(self, document: str) -> dict:
        return self.parse(document)["children"][0]["load"]

    def test_standard_with_scheduler(self) -> None:
        load = self.load_of_first(
            fixtures.jmx(fixtures.thread_group("Main", threads=10, ramp=30, duration=330, delay=60))
        )
        self.assertEqual(
            load["normalized"],
            {
                "model": "closed",
                "stages": [{"users": 10, "ramp_seconds": 30, "hold_seconds": 300}],
                "start_after_seconds": 60,
            },
        )

    def test_standard_parameterized_is_not_normalized(self) -> None:
        document = fixtures.jmx(
            plugin_thread_group(
                "ThreadGroup", "ThreadGroupGui",
                fixtures.string_prop("ThreadGroup.num_threads", "${THREADS}"),
            )
        )
        load = self.load_of_first(document)
        self.assertIsNone(load["normalized"])
        self.assertIn("parameterized", load["normalization_note"])

    def test_stepping_builds_staircase(self) -> None:
        props = "\n".join(
            [
                fixtures.string_prop("ThreadGroup.num_threads", "30"),
                fixtures.string_prop("Start users count", "10"),
                fixtures.string_prop("Start users period", "60"),
                fixtures.string_prop("rampUp", "5"),
                fixtures.string_prop("flighttime", "300"),
                fixtures.string_prop("Threads initial delay", "0"),
            ]
        )
        load = self.load_of_first(
            fixtures.jmx(
                plugin_thread_group(
                    "kg.apc.jmeter.threads.SteppingThreadGroup", "SteppingThreadGroupGui", props
                )
            )
        )
        self.assertEqual(
            load["normalized"]["stages"],
            [
                {"users": 10, "ramp_seconds": 5, "hold_seconds": 60},
                {"users": 20, "ramp_seconds": 5, "hold_seconds": 60},
                {"users": 30, "ramp_seconds": 5, "hold_seconds": 300},
            ],
        )

    def test_ultimate_single_row(self) -> None:
        props = (
            '  <collectionProp name="ultimatethreadgroupdata">\n'
            '    <collectionProp name="row">\n'
            '      <stringProp name="c0">50</stringProp>\n'
            '      <stringProp name="c1">10</stringProp>\n'
            '      <stringProp name="c2">120</stringProp>\n'
            '      <stringProp name="c3">600</stringProp>\n'
            '      <stringProp name="c4">60</stringProp>\n'
            "    </collectionProp>\n"
            "  </collectionProp>"
        )
        load = self.load_of_first(
            fixtures.jmx(
                plugin_thread_group(
                    "kg.apc.jmeter.threads.UltimateThreadGroup", "UltimateThreadGroupGui", props
                )
            )
        )
        self.assertEqual(
            load["normalized"],
            {
                "model": "closed",
                "stages": [{"users": 50, "ramp_seconds": 120, "hold_seconds": 600}],
                "start_after_seconds": 10,
            },
        )

    def test_ultimate_multi_row_left_for_review(self) -> None:
        row = (
            '    <collectionProp name="r">\n'
            '      <stringProp name="c0">10</stringProp>\n'
            '      <stringProp name="c1">0</stringProp>\n'
            '      <stringProp name="c2">60</stringProp>\n'
            '      <stringProp name="c3">300</stringProp>\n'
            '      <stringProp name="c4">30</stringProp>\n'
            "    </collectionProp>\n"
        )
        props = (
            '  <collectionProp name="ultimatethreadgroupdata">\n' + row + row +
            "  </collectionProp>"
        )
        load = self.load_of_first(
            fixtures.jmx(
                plugin_thread_group(
                    "kg.apc.jmeter.threads.UltimateThreadGroup", "UltimateThreadGroupGui", props
                )
            )
        )
        self.assertIsNone(load["normalized"])
        self.assertIn("2 schedule rows", load["normalization_note"])
        self.assertEqual(len(load["raw"]["rows"]), 2)

    def test_concurrency_with_steps(self) -> None:
        props = "\n".join(
            [
                fixtures.string_prop("TargetLevel", "20"),
                fixtures.string_prop("RampUp", "4"),
                fixtures.string_prop("Steps", "2"),
                fixtures.string_prop("Hold", "10"),
                fixtures.string_prop("Unit", "M"),
            ]
        )
        load = self.load_of_first(
            fixtures.jmx(
                plugin_thread_group(
                    "com.blazemeter.jmeter.threads.concurrency.ConcurrencyThreadGroup",
                    "ConcurrencyThreadGroupGui", props,
                )
            )
        )
        self.assertEqual(load["normalized"]["model"], "closed")
        self.assertEqual(
            load["normalized"]["stages"],
            [
                {"users": 10, "ramp_seconds": 120, "hold_seconds": 300},
                {"users": 20, "ramp_seconds": 120, "hold_seconds": 300},
            ],
        )

    def test_arrivals_is_open_model(self) -> None:
        props = "\n".join(
            [
                fixtures.string_prop("TargetLevel", "120"),
                fixtures.string_prop("RampUp", "1"),
                fixtures.string_prop("Steps", "0"),
                fixtures.string_prop("Hold", "5"),
                fixtures.string_prop("Unit", "M"),
            ]
        )
        load = self.load_of_first(
            fixtures.jmx(
                plugin_thread_group(
                    "com.blazemeter.jmeter.threads.arrivals.ArrivalsThreadGroup",
                    "ArrivalsThreadGroupGui", props,
                )
            )
        )
        self.assertEqual(load["normalized"]["model"], "open")
        self.assertEqual(
            load["normalized"]["stages"],
            [{"users_per_second": 2.0, "ramp_seconds": 60, "hold_seconds": 300}],
        )
```

- [ ] **Step 8.2: Run tests to verify they fail**

Run: `python tools/jmx_parser/test_jmx_parser.py`
Expected: FAIL — `KeyError: 'normalized'`.

- [ ] **Step 8.3: Implement**

Replace `thread_group_details` with the flavor-aware version (and add the helpers right above it):

```python
def to_int(value: str) -> int | None:
    try:
        return int(value.strip())
    except (ValueError, AttributeError):
        return None


def normalize_standard(raw: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    users = to_int(raw["num_threads"])
    if users is None:
        return None, "parameterized thread count"
    ramp = to_int(raw["ramp_time"]) or 0
    hold = None
    start_after = 0
    if raw["scheduler"]:
        duration = to_int(raw["duration"])
        if duration is None:
            return None, "parameterized duration"
        hold = max(duration - ramp, 0)
        start_after = to_int(raw["delay"]) or 0
    stage = {"users": users, "ramp_seconds": ramp, "hold_seconds": hold}
    return {"model": "closed", "stages": [stage], "start_after_seconds": start_after}, None


def normalize_stepping(raw: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    total = to_int(raw["num_threads"])
    step = to_int(raw["start_users_count"])
    if not total or not step:
        return None, "parameterized stepping parameters"
    period = to_int(raw["start_users_period"]) or 0
    ramp = to_int(raw["ramp_up"]) or 0
    hold = to_int(raw["flight_time"])
    stages: list[dict[str, Any]] = []
    current = 0
    while current < total:
        current = min(current + step, total)
        stages.append({"users": current, "ramp_seconds": ramp, "hold_seconds": period})
    if hold is not None and stages:
        stages[-1]["hold_seconds"] = hold
    start_after = to_int(raw["initial_delay"]) or 0
    return {"model": "closed", "stages": stages, "start_after_seconds": start_after}, None


def normalize_ultimate(rows: list[list[str]]) -> tuple[dict[str, Any] | None, str | None]:
    if len(rows) != 1:
        return None, f"{len(rows)} schedule rows; overlapping ramps need manual review"
    values = [to_int(value) for value in rows[0][:4]]
    if any(value is None for value in values):
        return None, "parameterized schedule row"
    users, delay, startup, hold = values
    return (
        {
            "model": "closed",
            "stages": [{"users": users, "ramp_seconds": startup, "hold_seconds": hold}],
            "start_after_seconds": delay,
        },
        None,
    )


def normalize_concurrency(
    raw: dict[str, Any], open_model: bool
) -> tuple[dict[str, Any] | None, str | None]:
    target = to_int(raw["target_level"])
    if target is None:
        return None, "parameterized target level"
    unit = 60 if raw["unit"] == "M" else 1
    ramp = (to_int(raw["ramp_up"]) or 0) * unit
    hold = (to_int(raw["hold"]) or 0) * unit
    steps = to_int(raw["steps"]) or 0
    model = "open" if open_model else "closed"
    if open_model:
        # arrivals: TargetLevel is a rate per Unit; normalize to per-second.
        rate = round(target / unit, 3)
        stages = [{"users_per_second": rate, "ramp_seconds": ramp, "hold_seconds": hold}]
        return {"model": model, "stages": stages, "start_after_seconds": 0}, None
    if steps > 1:
        stages = []
        for index in range(1, steps + 1):
            stages.append(
                {
                    "users": target * index // steps,
                    "ramp_seconds": ramp // steps,
                    "hold_seconds": hold // steps,
                }
            )
        stages[-1]["users"] = target
    else:
        stages = [{"users": target, "ramp_seconds": ramp, "hold_seconds": hold}]
    return {"model": model, "stages": stages, "start_after_seconds": 0}, None


def ultimate_rows(elem: ElementTree.Element) -> list[list[str]]:
    rows: list[list[str]] = []
    for collection in elem.findall("collectionProp"):
        if collection.get("name") != "ultimatethreadgroupdata":
            continue
        for row in collection.findall("collectionProp"):
            rows.append([(prop.text or "") for prop in row.findall("stringProp")])
    return rows


def thread_group_details(elem: ElementTree.Element, state: ParseState) -> dict[str, Any]:
    flavor = THREAD_GROUP_FLAVORS.get(elem.get("testclass") or elem.tag, "standard")
    raw: dict[str, Any]
    if flavor == "standard":
        raw = {
            "num_threads": string_prop(elem, "ThreadGroup.num_threads"),
            "ramp_time": string_prop(elem, "ThreadGroup.ramp_time"),
            "duration": string_prop(elem, "ThreadGroup.duration"),
            "delay": string_prop(elem, "ThreadGroup.delay"),
            "scheduler": bool_prop(elem, "ThreadGroup.scheduler"),
        }
        normalized, note = normalize_standard(raw)
    elif flavor == "stepping":
        raw = {
            "num_threads": string_prop(elem, "ThreadGroup.num_threads"),
            "start_users_count": string_prop(elem, "Start users count"),
            "start_users_period": string_prop(elem, "Start users period"),
            "ramp_up": string_prop(elem, "rampUp"),
            "flight_time": string_prop(elem, "flighttime"),
            "initial_delay": string_prop(elem, "Threads initial delay"),
        }
        normalized, note = normalize_stepping(raw)
    elif flavor == "ultimate":
        rows = ultimate_rows(elem)
        raw = {"rows": rows}
        normalized, note = normalize_ultimate(rows)
    else:  # concurrency / arrivals share the BlazeMeter property set
        raw = {
            "target_level": string_prop(elem, "TargetLevel"),
            "ramp_up": string_prop(elem, "RampUp"),
            "steps": string_prop(elem, "Steps"),
            "hold": string_prop(elem, "Hold"),
            "unit": string_prop(elem, "Unit"),
        }
        normalized, note = normalize_concurrency(raw, open_model=flavor == "arrivals")
    load: dict[str, Any] = {"raw": raw, "normalized": normalized}
    if note is not None:
        load["normalization_note"] = note
    return {"flavor": flavor, "load": load}
```

- [ ] **Step 8.4: Run tests to verify they pass**

Run: `python tools/jmx_parser/test_jmx_parser.py`
Expected: PASS, 0 failures. The Task 2 raw-load test keeps passing (standard raw keys unchanged).

- [ ] **Step 8.5: Commit**

```bash
git add tools/jmx_parser
git commit -m "feat: jmx_parser normalizes plugin thread groups into load stages"
```

---
### Task 9: Variable cross-reference, props links, complexity flags

**Files:**
- Modify: `tools/jmx_parser/jmx_parser.py`
- Modify: `tools/jmx_parser/test_jmx_parser.py`

A post-pass over the finished tree. Consumed variables come from a generic scan of every scalar string in a node (plus the precomputed `body.variables` and JSR223 `reads`); produced variables come from a per-kind dispatch. Disabled elements do not contribute. Only enabled elements feed findings and flags.

- [ ] **Step 9.1: Write the failing tests**

Append to `tools/jmx_parser/test_jmx_parser.py`:

```python
class VariableIndexTest(ParserCase):
    def test_extractor_to_consumer_link(self) -> None:
        regex_props = "\n".join(
            [
                fixtures.string_prop("RegexExtractor.refname", "csrf"),
                fixtures.string_prop("RegexExtractor.regex", "v=(.+?);"),
            ]
        )
        ir = self.parse(
            fixtures.jmx(
                fixtures.thread_group(
                    "Main",
                    children="\n".join(
                        [
                            fixtures.http_sampler(
                                "login",
                                children=fixtures.element(
                                    "RegexExtractor", "get csrf", props=regex_props
                                ),
                            ),
                            fixtures.http_sampler("submit", path="/submit?c=${csrf}"),
                        ]
                    ),
                )
            )
        )
        entry = ir["variables"]["index"]["csrf"]
        self.assertEqual(len(entry["producers"]), 1)
        self.assertEqual(len(entry["consumers"]), 1)
        findings = ir["variables"]["findings"]
        self.assertEqual(findings["consumed_not_produced"], [])
        self.assertEqual(findings["produced_not_consumed"], [])

    def test_orphan_and_dead_variables(self) -> None:
        regex_props = fixtures.string_prop("RegexExtractor.refname", "unusedVar")
        ir = self.parse(
            fixtures.jmx(
                fixtures.thread_group(
                    "Main",
                    children="\n".join(
                        [
                            fixtures.http_sampler(
                                "a", path="/x?g=${ghost}",
                                children=fixtures.element(
                                    "RegexExtractor", "dead", props=regex_props
                                ),
                            ),
                        ]
                    ),
                )
            )
        )
        findings = ir["variables"]["findings"]
        self.assertEqual(findings["consumed_not_produced"][0]["variable"], "ghost")
        self.assertEqual(findings["produced_not_consumed"][0]["variable"], "unusedVar")

    def test_functions_are_not_variables(self) -> None:
        ir = self.parse(
            fixtures.jmx(
                fixtures.thread_group(
                    "Main",
                    children=fixtures.http_sampler("a", path="/x?t=${__time()}"),
                )
            )
        )
        self.assertIn("time", ir["variables"]["functions"])
        self.assertNotIn("__time", ir["variables"]["index"])

    def test_externalized_body_variables_are_indexed(self) -> None:
        body = '{"pad":"' + "x" * 5000 + '","user":"${login}"}'
        ir = self.parse(
            fixtures.jmx(
                fixtures.thread_group(
                    "Main",
                    children=fixtures.http_sampler("a", method="POST", path="/x", body=body),
                )
            )
        )
        self.assertIn("login", ir["variables"]["index"])
        self.assertEqual(
            ir["variables"]["findings"]["consumed_not_produced"][0]["variable"], "login"
        )

    def test_disabled_elements_do_not_contribute(self) -> None:
        ir = self.parse(
            fixtures.jmx(
                fixtures.thread_group(
                    "Main",
                    children=fixtures.http_sampler("off", path="/x?g=${ghost}"),
                    enabled=False,
                )
            )
        )
        self.assertEqual(ir["variables"]["findings"]["consumed_not_produced"], [])


class ComplexityFlagTest(ParserCase):
    def test_props_across_thread_groups(self) -> None:
        ir = self.parse(
            fixtures.jmx(
                fixtures.thread_group(
                    "Writer", delay=0,
                    children=fixtures.http_sampler(
                        "w",
                        children=jsr223(
                            "JSR223PostProcessor", "share",
                            'props.put("shared", vars.get("x"))',
                        ),
                    ),
                ),
                fixtures.thread_group(
                    "Reader", delay=1200, duration=600,
                    children=fixtures.http_sampler(
                        "r",
                        children=jsr223(
                            "JSR223PreProcessor", "take",
                            'vars.put("y", props.get("shared"))',
                        ),
                    ),
                ),
            )
        )
        flags = {flag["flag"] for flag in ir["complexity_flags"]}
        self.assertIn("props-usage", flags)
        self.assertIn("inter-thread-props", flags)
        self.assertIn("staged-thread-groups", flags)
        props = ir["variables"]["props"]["shared"]
        self.assertEqual(len(props["writers"]), 1)
        self.assertEqual(len(props["readers"]), 1)

    def test_unknown_and_unresolved_flags(self) -> None:
        ir = self.parse(
            fixtures.jmx(
                fixtures.thread_group(
                    "Main",
                    children="\n".join(
                        [
                            fixtures.element("com.example.Strange", "odd"),
                            module_controller("dangling", ["Test Plan", "nope"]),
                        ]
                    ),
                )
            )
        )
        flags = {flag["flag"] for flag in ir["complexity_flags"]}
        self.assertIn("unknown-elements", flags)
        self.assertIn("unresolved-module", flags)

    def test_stats(self) -> None:
        ir = self.parse(
            fixtures.jmx(
                fixtures.thread_group(
                    "Main",
                    children="\n".join(
                        [
                            fixtures.http_sampler("a"),
                            fixtures.http_sampler("b"),
                        ]
                    ),
                )
            )
        )
        self.assertEqual(ir["stats"]["by_kind"]["http_sampler"], 2)
        self.assertEqual(ir["stats"]["elements_total"], 3)
        self.assertEqual(ir["stats"]["elements_disabled"], 0)
```

- [ ] **Step 9.2: Run tests to verify they fail**

Run: `python tools/jmx_parser/test_jmx_parser.py`
Expected: FAIL — `KeyError: 'variables'`.

- [ ] **Step 9.3: Implement**

Add after `resolve_modules`:

```python
NODE_SCAN_SKIP_KEYS = frozenset(
    {"id", "kind", "type", "path", "children", "script_preview", "preview", "sha256"}
)


def node_strings(node: dict[str, Any]) -> list[str]:
    """All scalar strings of one node (not its children) for the consumer scan."""
    collected: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, str):
            collected.append(value)
        elif isinstance(value, dict):
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    for key, value in node.items():
        if key not in NODE_SCAN_SKIP_KEYS:
            visit(value)
    return collected


def node_produced(node: dict[str, Any]) -> list[str]:
    kind = node["kind"]
    if kind == "csv_data_set":
        return list(node.get("variable_names", []))
    if kind in {"regex_extractor", "boundary_extractor"}:
        return [node["variable"]] if node.get("variable") else []
    if kind == "jsonpath_extractor":
        return [extract["variable"] for extract in node.get("extracts", []) if extract["variable"]]
    if kind in {"counter", "random_variable"}:
        return [node["variable"]] if node.get("variable") else []
    if kind == "user_defined_variables":
        return list(node.get("values", {}))
    if kind in {"jsr223_sampler", "jsr223_pre", "jsr223_post"}:
        return list(node.get("writes", []))
    return []


def analyze_variables(ir: dict[str, Any], state: ParseState) -> None:
    index: dict[str, dict[str, set[str]]] = {}
    props_index: dict[str, dict[str, set[str]]] = {}
    functions: set[str] = set()
    flags: list[dict[str, str]] = []
    by_kind: dict[str, int] = {}
    totals = {"all": 0, "disabled": 0}
    jsr223_counts = {"typical": 0, "complex": 0}
    unresolved_modules: list[str] = []
    thread_groups: list[dict[str, Any]] = []
    jsr223_sampler_present = False

    def entry(var: str) -> dict[str, set[str]]:
        return index.setdefault(var, {"producers": set(), "consumers": set()})

    def prop_entry(name: str) -> dict[str, set[str]]:
        return props_index.setdefault(
            name, {"writers": set(), "readers": set(), "thread_groups": set()}
        )

    def visit(node: dict[str, Any], tg_name: str | None, enabled: bool) -> None:
        nonlocal jsr223_sampler_present
        totals["all"] += 1
        by_kind[node["kind"]] = by_kind.get(node["kind"], 0) + 1
        active = enabled and node["enabled"]
        if not node["enabled"]:
            totals["disabled"] += 1
        if active:
            if node["kind"] == "thread_group":
                thread_groups.append(node)
                tg_name = node["name"]
            if node["kind"] == "module" and node.get("unresolved"):
                unresolved_modules.append(node["name"])
            if node["kind"] == "jsr223_sampler":
                jsr223_sampler_present = True
            if node["kind"].startswith("jsr223"):
                jsr223_counts[node.get("classification", "complex")] += 1
            for text in node_strings(node):
                for variable in JMETER_VARIABLE_RE.findall(text):
                    entry(variable)["consumers"].add(node["id"])
                functions.update(JMETER_FUNCTION_RE.findall(text))
            # Externalized bodies keep only a preview in the node; their full
            # variable/function lists were precomputed by store_body.
            body = node.get("body")
            if isinstance(body, dict):
                for variable in body.get("variables", []):
                    entry(variable)["consumers"].add(node["id"])
                functions.update(body.get("functions", []))
            for variable in node.get("reads", []):
                entry(variable)["consumers"].add(node["id"])
            for variable in node_produced(node):
                entry(variable)["producers"].add(node["id"])
            for prop in node.get("props_writes", []):
                record = prop_entry(prop)
                record["writers"].add(node["id"])
                record["thread_groups"].add(tg_name or "")
            for prop in node.get("props_reads", []):
                record = prop_entry(prop)
                record["readers"].add(node["id"])
                record["thread_groups"].add(tg_name or "")
        for child in node["children"]:
            visit(child, tg_name, active)

    for child in ir["children"]:
        visit(child, None, True)

    consumed_not_produced = [
        {"variable": var, "elements": sorted(data["consumers"])}
        for var, data in sorted(index.items())
        if data["consumers"] and not data["producers"]
    ]
    produced_not_consumed = [
        {"variable": var, "elements": sorted(data["producers"])}
        for var, data in sorted(index.items())
        if data["producers"] and not data["consumers"]
    ]

    if props_index:
        flags.append(
            {"flag": "props-usage", "details": "props: " + ", ".join(sorted(props_index))}
        )
        cross = sorted(
            name
            for name, record in props_index.items()
            if len(record["thread_groups"]) > 1
        )
        if cross:
            flags.append(
                {"flag": "inter-thread-props", "details": "props: " + ", ".join(cross)}
            )
    starts = [
        (node["load"].get("normalized") or {}).get("start_after_seconds", 0)
        for node in thread_groups
    ]
    if len(thread_groups) >= 2 and any(start > 0 for start in starts):
        flags.append(
            {
                "flag": "staged-thread-groups",
                "details": f"{len(thread_groups)} thread groups with time offsets",
            }
        )
    unnormalized = sorted(
        node["name"] for node in thread_groups if node["load"].get("normalized") is None
    )
    if unnormalized:
        flags.append(
            {"flag": "unnormalized-load", "details": "thread groups: " + ", ".join(unnormalized)}
        )
    if unresolved_modules:
        flags.append(
            {
                "flag": "unresolved-module",
                "details": "controllers: " + ", ".join(sorted(unresolved_modules)),
            }
        )
    if ir["unsupported"]:
        types = sorted({item["type"] for item in ir["unsupported"]})
        flags.append(
            {
                "flag": "unknown-elements",
                "details": f"{len(ir['unsupported'])} element(s): " + ", ".join(types[:8]),
            }
        )
    if jsr223_sampler_present:
        flags.append({"flag": "jsr223-sampler", "details": "standalone JSR223 sampler present"})

    ir["variables"] = {
        "index": {
            var: {
                "producers": sorted(data["producers"]),
                "consumers": sorted(data["consumers"]),
            }
            for var, data in sorted(index.items())
        },
        "functions": sorted(functions),
        "props": {
            name: {
                "writers": sorted(record["writers"]),
                "readers": sorted(record["readers"]),
            }
            for name, record in sorted(props_index.items())
        },
        "findings": {
            "consumed_not_produced": consumed_not_produced,
            "produced_not_consumed": produced_not_consumed,
        },
    }
    ir["complexity_flags"] = sorted(flags, key=lambda flag: flag["flag"])
    ir["stats"] = {
        "elements_total": totals["all"],
        "elements_disabled": totals["disabled"],
        "by_kind": dict(sorted(by_kind.items())),
        "bodies_externalized": len(state.bodies),
        "jsr223": jsr223_counts,
    }
```

In `parse_jmx`, after `resolve_modules(ir)` add:

```python
    analyze_variables(ir, state)
```

- [ ] **Step 9.4: Run tests to verify they pass**

Run: `python tools/jmx_parser/test_jmx_parser.py`
Expected: PASS, 0 failures.

- [ ] **Step 9.5: Commit**

```bash
git add tools/jmx_parser
git commit -m "feat: jmx_parser variable cross-reference and complexity flags"
```

---

### Task 10: inventory.md renderer

**Files:**
- Modify: `tools/jmx_parser/jmx_parser.py`
- Modify: `tools/jmx_parser/test_jmx_parser.py`

The Gate 1 document. Curated findings only — the full index stays in `ir.json` (agent-context protection per the spec). Deterministic output, English like every other tool artifact.

- [ ] **Step 10.1: Write the failing tests**

Append to `tools/jmx_parser/test_jmx_parser.py`:

```python
class InventoryTest(ParserCase):
    def test_inventory_sections(self) -> None:
        ir = self.parse(
            fixtures.jmx(
                fixtures.thread_group(
                    "Main", threads=5, ramp=10,
                    children="\n".join(
                        [
                            fixtures.http_sampler("a", path="/x?g=${ghost}"),
                            fixtures.element("com.example.Strange", "odd"),
                        ]
                    ),
                )
            )
        )
        text = jmx_parser.render_inventory(ir)
        self.assertIn("# JMX Inventory — plan.jmx", text)
        self.assertIn("## Elements", text)
        self.assertIn("| http_sampler | 1 |", text)
        self.assertIn("## Unsupported elements", text)
        self.assertIn("com.example.Strange", text)
        self.assertIn("## Thread groups", text)
        self.assertIn("| Main | standard | closed |", text)
        self.assertIn("## Data flow findings", text)
        self.assertIn("ghost", text)
        self.assertIn("## Complexity flags", text)
        self.assertIn("unknown-elements", text)

    def test_inventory_is_deterministic(self) -> None:
        document = fixtures.jmx(
            fixtures.thread_group("Main", children=fixtures.http_sampler("a"))
        )
        first = jmx_parser.render_inventory(self.parse(document))
        out_dir_2 = self.tmp / "out2"
        jmx_path = self.tmp / "plan.jmx"
        second = jmx_parser.render_inventory(jmx_parser.parse_jmx(jmx_path, out_dir_2))
        self.assertEqual(first, second)
```

- [ ] **Step 10.2: Run tests to verify they fail**

Run: `python tools/jmx_parser/test_jmx_parser.py`
Expected: FAIL — `AttributeError: module 'jmx_parser' has no attribute 'render_inventory'`.

- [ ] **Step 10.3: Implement**

Add after `analyze_variables`:

```python
def render_stage(stage: dict[str, Any]) -> str:
    target = stage.get("users", stage.get("users_per_second"))
    unit = "u" if "users" in stage else "u/s"
    hold = stage.get("hold_seconds")
    hold_text = f"{hold}s" if hold is not None else "-"
    return f"{target}{unit} ramp {stage.get('ramp_seconds', 0)}s hold {hold_text}"


def render_inventory(ir: dict[str, Any]) -> str:
    source = ir["source"]
    stats = ir["stats"]
    lines = [
        f"# JMX Inventory — {source['file']}",
        "",
        f"- Size: {source['size_bytes']} bytes (sha256 `{source['sha256'][:12]}`)",
        f"- Test plan: {ir['test_plan']['name']}",
        f"- Elements: {stats['elements_total']} total, {stats['elements_disabled']} disabled",
        f"- Bodies externalized: {stats['bodies_externalized']}",
        f"- JSR223: {stats['jsr223']['typical']} typical, {stats['jsr223']['complex']} complex",
        "",
        "## Elements",
        "",
        "| Kind | Count |",
        "|---|---|",
    ]
    lines.extend(f"| {kind} | {count} |" for kind, count in stats["by_kind"].items())

    lines.extend(["", "## Unsupported elements", ""])
    if ir["unsupported"]:
        lines.extend(
            f"- `{item['type']}` — {item['name']} (id {item['id']}, at {'/'.join(item['path'])})"
            for item in ir["unsupported"]
        )
    else:
        lines.append("- None")

    lines.extend(
        ["", "## Thread groups", "", "| Name | Flavor | Model | Stages | Start after | Note |", "|---|---|---|---|---|---|"]
    )

    def thread_group_rows(node: dict[str, Any]) -> None:
        if node["kind"] == "thread_group":
            normalized = node["load"].get("normalized")
            if normalized:
                model = normalized["model"]
                stages = "; ".join(render_stage(stage) for stage in normalized["stages"])
                start = f"{normalized['start_after_seconds']}s"
                note = ""
            else:
                model, stages, start = "?", "needs review", "?"
                note = node["load"].get("normalization_note", "")
            suffix = "" if node["enabled"] else " (disabled)"
            lines.append(
                f"| {node['name']}{suffix} | {node['flavor']} | {model} | {stages} | {start} | {note} |"
            )
        for child in node["children"]:
            thread_group_rows(child)

    for child in ir["children"]:
        thread_group_rows(child)

    findings = ir["variables"]["findings"]
    lines.extend(["", "## Data flow findings", ""])
    body = False
    for item in findings["consumed_not_produced"]:
        lines.append(
            f"- `${{{item['variable']}}}` is consumed but never produced "
            f"(elements: {', '.join(item['elements'])}) — props, external file or hidden logic?"
        )
        body = True
    for item in findings["produced_not_consumed"]:
        lines.append(
            f"- `${{{item['variable']}}}` is produced but never consumed "
            f"(elements: {', '.join(item['elements'])}) — dead correlation?"
        )
        body = True
    for name, record in ir["variables"]["props"].items():
        lines.append(
            f"- prop `{name}`: writers {', '.join(record['writers']) or '-'}; "
            f"readers {', '.join(record['readers']) or '-'}"
        )
        body = True
    if not body:
        lines.append("- None")

    lines.extend(["", "## Complexity flags", ""])
    if ir["complexity_flags"]:
        lines.extend(
            f"- **{flag['flag']}**: {flag['details']}" for flag in ir["complexity_flags"]
        )
    else:
        lines.append("- None")

    return "\n".join(lines) + "\n"
```

- [ ] **Step 10.4: Run tests to verify they pass**

Run: `python tools/jmx_parser/test_jmx_parser.py`
Expected: PASS, 0 failures.

- [ ] **Step 10.5: Commit**

```bash
git add tools/jmx_parser
git commit -m "feat: jmx_parser renders the Gate 1 inventory document"
```

---

### Task 11: CLI — parse / summary / element, deterministic outputs

**Files:**
- Modify: `tools/jmx_parser/jmx_parser.py`
- Modify: `tools/jmx_parser/test_jmx_parser.py`

`parse` writes `ir.json` + `inventory.md` and prints a machine-readable result; `summary` and `element` are the agent-facing slices so the agent never loads the whole IR. Same `--format json|text` and exit-code conventions as the other tools.

- [ ] **Step 11.1: Write the failing tests**

Append to `tools/jmx_parser/test_jmx_parser.py`:

```python
import io
import json
from contextlib import redirect_stdout


class CliTest(ParserCase):
    def write_plan(self) -> Path:
        jmx_path = self.tmp / "plan.jmx"
        jmx_path.write_text(
            fixtures.jmx(
                fixtures.thread_group("Main", children=fixtures.http_sampler("a"))
            ),
            encoding="utf-8",
        )
        return jmx_path

    def run_cli(self, *argv: str) -> tuple[int, str]:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = jmx_parser.main(list(argv))
        return code, buffer.getvalue()

    def test_parse_writes_artifacts(self) -> None:
        jmx_path = self.write_plan()
        code, output = self.run_cli(
            "parse", str(jmx_path), "--out-dir", str(self.out_dir), "--format", "json"
        )
        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertTrue((self.out_dir / "ir.json").is_file())
        self.assertTrue((self.out_dir / "inventory.md").is_file())
        self.assertEqual(payload["complexity_flags"], [])
        ir = json.loads((self.out_dir / "ir.json").read_text(encoding="utf-8"))
        self.assertEqual(ir["version"], 1)

    def test_parse_is_deterministic_byte_for_byte(self) -> None:
        jmx_path = self.write_plan()
        out_a, out_b = self.tmp / "a", self.tmp / "b"
        self.run_cli("parse", str(jmx_path), "--out-dir", str(out_a))
        self.run_cli("parse", str(jmx_path), "--out-dir", str(out_b))
        self.assertEqual(
            (out_a / "ir.json").read_bytes(), (out_b / "ir.json").read_bytes()
        )
        self.assertEqual(
            (out_a / "inventory.md").read_bytes(), (out_b / "inventory.md").read_bytes()
        )

    def test_parse_failure_is_blocking(self) -> None:
        broken = self.tmp / "broken.jmx"
        broken.write_text("<jmeterTestPlan><hashTree>", encoding="utf-8")
        code, output = self.run_cli(
            "parse", str(broken), "--out-dir", str(self.out_dir), "--format", "json"
        )
        self.assertEqual(code, 1)
        payload = json.loads(output)
        self.assertEqual(payload["blocking"][0]["rule"], "jmx-parser.parse-failed")

    def test_summary_and_element(self) -> None:
        jmx_path = self.write_plan()
        self.run_cli("parse", str(jmx_path), "--out-dir", str(self.out_dir))
        code, output = self.run_cli("summary", str(self.out_dir / "ir.json"))
        self.assertEqual(code, 0)
        self.assertIn("Main", output)
        code, output = self.run_cli("element", str(self.out_dir / "ir.json"), "e-0002")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["kind"], "http_sampler")
        code, _ = self.run_cli("element", str(self.out_dir / "ir.json"), "e-9999")
        self.assertEqual(code, 1)
```

- [ ] **Step 11.2: Run tests to verify they fail**

Run: `python tools/jmx_parser/test_jmx_parser.py`
Expected: FAIL — `AttributeError: module 'jmx_parser' has no attribute 'main'`.

- [ ] **Step 11.3: Implement**

Add at the top of `jmx_parser.py` (with the other imports): `import argparse`. Add at the end of the module:

```python
def write_outputs(ir: dict[str, Any], out_dir: Path) -> tuple[Path, Path]:
    ir_path = out_dir / "ir.json"
    inventory_path = out_dir / "inventory.md"
    ir_path.write_text(
        json.dumps(ir, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    inventory_path.write_text(render_inventory(ir), encoding="utf-8", newline="\n")
    return ir_path, inventory_path


def find_element(ir: dict[str, Any], element_id: str) -> dict[str, Any] | None:
    stack = list(ir["children"])
    while stack:
        node = stack.pop()
        if node["id"] == element_id:
            return node
        stack.extend(node["children"])
    return None


def render_summary(ir: dict[str, Any]) -> str:
    lines = [
        f"plan: {ir['test_plan']['name']} ({ir['source']['file']}, "
        f"{ir['source']['size_bytes']} bytes)",
        f"elements: {ir['stats']['elements_total']} "
        f"({ir['stats']['elements_disabled']} disabled), "
        f"unsupported: {len(ir['unsupported'])}",
    ]

    def visit(node: dict[str, Any]) -> None:
        if node["kind"] == "thread_group":
            normalized = node["load"].get("normalized")
            detail = (
                f"{normalized['model']}, {len(normalized['stages'])} stage(s)"
                if normalized
                else "load needs review"
            )
            lines.append(f"thread group {node['id']} '{node['name']}': {detail}")
        for child in node["children"]:
            visit(child)

    for child in ir["children"]:
        visit(child)
    for flag in ir["complexity_flags"]:
        lines.append(f"flag {flag['flag']}: {flag['details']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Parse JMeter .jmx into migration IR")
    sub = parser.add_subparsers(dest="command", required=True)

    parse_cmd = sub.add_parser("parse", help="parse a .jmx into ir.json + inventory.md")
    parse_cmd.add_argument("jmx", type=Path, help=".jmx file")
    parse_cmd.add_argument("--out-dir", type=Path, required=True, help="output directory")
    parse_cmd.add_argument(
        "--max-inline-body-bytes", type=int, default=DEFAULT_MAX_INLINE_BODY_BYTES
    )
    parse_cmd.add_argument("--format", choices=("json", "text"), default="json")

    summary_cmd = sub.add_parser("summary", help="print a short overview of an ir.json")
    summary_cmd.add_argument("ir", type=Path)

    element_cmd = sub.add_parser("element", help="print one element of an ir.json by id")
    element_cmd.add_argument("ir", type=Path)
    element_cmd.add_argument("element_id")

    args = parser.parse_args(argv)

    if args.command == "parse":
        try:
            ir = parse_jmx(args.jmx, args.out_dir, max_inline_body=args.max_inline_body_bytes)
            ir_path, inventory_path = write_outputs(ir, args.out_dir)
        except Exception as exc:
            finding = {
                "rule": "jmx-parser.parse-failed",
                "severity": "blocking",
                "message": str(exc),
            }
            if args.format == "json":
                print(json.dumps({"blocking": [finding]}, indent=2, sort_keys=True))
            else:
                print(f"BLOCKED: {exc}", file=sys.stderr)
            return 1
        if args.format == "json":
            print(
                json.dumps(
                    {
                        "blocking": [],
                        "ir": ir_path.as_posix(),
                        "inventory": inventory_path.as_posix(),
                        "complexity_flags": [flag["flag"] for flag in ir["complexity_flags"]],
                        "stats": ir["stats"],
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            print(inventory_path.as_posix())
        return 0

    ir = json.loads(args.ir.read_text(encoding="utf-8"))
    if args.command == "summary":
        print(render_summary(ir))
        return 0
    node = find_element(ir, args.element_id)
    if node is None:
        print(f"element not found: {args.element_id}", file=sys.stderr)
        return 1
    print(json.dumps(node, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 11.4: Run tests to verify they pass**

Run: `python tools/jmx_parser/test_jmx_parser.py`
Expected: PASS, 0 failures.

- [ ] **Step 11.5: Commit**

```bash
git add tools/jmx_parser
git commit -m "feat: jmx_parser CLI with parse/summary/element commands"
```

---
### Task 12: IR contract — `schemas/jmx-ir.schema.json` + self-validation

**Files:**
- Create: `schemas/jmx-ir.schema.json`
- Modify: `tools/jmx_parser/jmx_parser.py`
- Modify: `tools/jmx_parser/test_jmx_parser.py`

The IR is a contract between the parser and the Phase 2 skills, so it gets a versioned schema like `scenario.yaml`. Element detail fields vary by kind and stay open (`additionalProperties` not restricted); the schema pins the envelope: ids, kinds, tree shape, the analysis blocks.

- [ ] **Step 12.1: Write the failing tests**

Append to `tools/jmx_parser/test_jmx_parser.py`:

```python
try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover
    Draft202012Validator = None

REPO_ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(Draft202012Validator is not None, "jsonschema unavailable")
class IrSchemaTest(ParserCase):
    def validator(self) -> "Draft202012Validator":
        schema = json.loads(
            (REPO_ROOT / "schemas" / "jmx-ir.schema.json").read_text(encoding="utf-8")
        )
        return Draft202012Validator(schema)

    def test_fixture_ir_validates(self) -> None:
        ir = self.parse(
            fixtures.jmx(
                fixtures.thread_group(
                    "Main",
                    children="\n".join(
                        [
                            fixtures.http_sampler("a", method="POST", path="/x", body="b" * 5000),
                            fixtures.element("com.example.Strange", "odd"),
                        ]
                    ),
                )
            )
        )
        self.assertEqual(list(self.validator().iter_errors(ir)), [])

    def test_schema_rejects_element_without_id(self) -> None:
        ir = self.parse(fixtures.jmx(fixtures.thread_group("Main")))
        del ir["children"][0]["id"]
        self.assertTrue(list(self.validator().iter_errors(ir)))
```

- [ ] **Step 12.2: Run tests to verify they fail**

Run: `python tools/jmx_parser/test_jmx_parser.py`
Expected: FAIL — `FileNotFoundError: ... schemas/jmx-ir.schema.json`.

- [ ] **Step 12.3: Create the schema**

Create `schemas/jmx-ir.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://gatling-ai.local/schemas/jmx-ir.schema.json",
  "title": "Gatling-AI JMX IR",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "version", "source", "test_plan", "children",
    "unsupported", "variables", "complexity_flags", "stats"
  ],
  "$defs": {
    "element": {
      "type": "object",
      "required": ["id", "kind", "type", "name", "enabled", "path", "children"],
      "properties": {
        "id": { "type": "string", "pattern": "^e-\\d{4,}$" },
        "kind": {
          "enum": [
            "thread_group", "http_sampler", "jsr223_sampler", "jdbc_sampler",
            "transaction", "simple", "if", "loop", "once_only", "throughput",
            "fragment", "module",
            "csv_data_set", "user_defined_variables", "http_defaults",
            "header_manager", "cookie_manager", "counter", "random_variable",
            "regex_extractor", "jsonpath_extractor", "boundary_extractor",
            "response_assertion", "json_assertion", "duration_assertion",
            "constant_timer", "uniform_random_timer", "gaussian_random_timer",
            "constant_throughput_timer", "unknown"
          ]
        },
        "type": { "type": "string", "minLength": 1 },
        "name": { "type": "string" },
        "enabled": { "type": "boolean" },
        "path": { "type": "array", "items": { "type": "string" } },
        "children": { "type": "array", "items": { "$ref": "#/$defs/element" } }
      }
    },
    "idList": { "type": "array", "items": { "type": "string" } },
    "variableFinding": {
      "type": "object",
      "additionalProperties": false,
      "required": ["variable", "elements"],
      "properties": {
        "variable": { "type": "string" },
        "elements": { "$ref": "#/$defs/idList" }
      }
    }
  },
  "properties": {
    "version": { "const": 1 },
    "source": {
      "type": "object",
      "additionalProperties": false,
      "required": ["file", "sha256", "size_bytes"],
      "properties": {
        "file": { "type": "string", "minLength": 1 },
        "sha256": { "type": "string", "pattern": "^[0-9a-f]{64}$" },
        "size_bytes": { "type": "integer", "minimum": 0 }
      }
    },
    "test_plan": {
      "type": "object",
      "additionalProperties": false,
      "required": ["name", "comments"],
      "properties": {
        "name": { "type": "string" },
        "comments": { "type": "string" }
      }
    },
    "children": { "type": "array", "items": { "$ref": "#/$defs/element" } },
    "unsupported": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["id", "type", "name", "path"],
        "properties": {
          "id": { "type": "string" },
          "type": { "type": "string" },
          "name": { "type": "string" },
          "path": { "type": "array", "items": { "type": "string" } }
        }
      }
    },
    "variables": {
      "type": "object",
      "additionalProperties": false,
      "required": ["index", "functions", "props", "findings"],
      "properties": {
        "index": {
          "type": "object",
          "additionalProperties": {
            "type": "object",
            "additionalProperties": false,
            "required": ["producers", "consumers"],
            "properties": {
              "producers": { "$ref": "#/$defs/idList" },
              "consumers": { "$ref": "#/$defs/idList" }
            }
          }
        },
        "functions": { "type": "array", "items": { "type": "string" } },
        "props": {
          "type": "object",
          "additionalProperties": {
            "type": "object",
            "additionalProperties": false,
            "required": ["writers", "readers"],
            "properties": {
              "writers": { "$ref": "#/$defs/idList" },
              "readers": { "$ref": "#/$defs/idList" }
            }
          }
        },
        "findings": {
          "type": "object",
          "additionalProperties": false,
          "required": ["consumed_not_produced", "produced_not_consumed"],
          "properties": {
            "consumed_not_produced": {
              "type": "array", "items": { "$ref": "#/$defs/variableFinding" }
            },
            "produced_not_consumed": {
              "type": "array", "items": { "$ref": "#/$defs/variableFinding" }
            }
          }
        }
      }
    },
    "complexity_flags": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["flag", "details"],
        "properties": {
          "flag": { "type": "string" },
          "details": { "type": "string" }
        }
      }
    },
    "stats": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "elements_total", "elements_disabled", "by_kind",
        "bodies_externalized", "jsr223"
      ],
      "properties": {
        "elements_total": { "type": "integer", "minimum": 0 },
        "elements_disabled": { "type": "integer", "minimum": 0 },
        "by_kind": {
          "type": "object",
          "additionalProperties": { "type": "integer", "minimum": 0 }
        },
        "bodies_externalized": { "type": "integer", "minimum": 0 },
        "jsr223": {
          "type": "object",
          "additionalProperties": false,
          "required": ["typical", "complex"],
          "properties": {
            "typical": { "type": "integer", "minimum": 0 },
            "complex": { "type": "integer", "minimum": 0 }
          }
        }
      }
    }
  }
}
```

- [ ] **Step 12.4: Wire self-validation into the CLI**

In `jmx_parser.py` add after the stdlib imports:

```python
try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover - validation is skipped without jsonschema.
    Draft202012Validator = None

IR_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "jmx-ir.schema.json"


def validate_ir(ir: dict[str, Any]) -> None:
    """Blocking self-check: written IR must satisfy the published contract."""
    if Draft202012Validator is None:
        return
    schema = json.loads(IR_SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema).iter_errors(ir),
        key=lambda error: (list(error.absolute_path), error.message),
    )
    if errors:
        first = errors[0]
        raise ValueError(f"generated IR violates jmx-ir.schema.json: {first.message}")
```

In `main`, inside the `parse` branch, call `validate_ir(ir)` between `parse_jmx(...)` and `write_outputs(...)` (inside the same `try`).

- [ ] **Step 12.5: Run tests to verify they pass**

Run: `python tools/jmx_parser/test_jmx_parser.py`
Expected: PASS, 0 failures.

- [ ] **Step 12.6: Commit**

```bash
git add schemas/jmx-ir.schema.json tools/jmx_parser
git commit -m "feat: versioned IR schema with parser self-validation"
```

---

### Task 13: Streaming budget test (~150 MB, env-gated)

**Files:**
- Create: `tools/jmx_parser/test_jmx_parser_perf.py`

Validates the spec's core constraint: memory bounded by the largest element, wall time in minutes for a 150 MB plan. Gated behind `GATLING_AI_PERF=1` so the normal suite stays fast.

- [ ] **Step 13.1: Write the test**

Create `tools/jmx_parser/test_jmx_parser_perf.py`:

```python
#!/usr/bin/env python3
"""Env-gated streaming budget test for jmx_parser (~150MB synthetic plan).

Run from repo root:
    $env:GATLING_AI_PERF = "1"; python tools/jmx_parser/test_jmx_parser_perf.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import tracemalloc
import unittest
from pathlib import Path

import fixtures
import jmx_parser

SAMPLERS = 30
BODY_BYTES = 5 * 1024 * 1024
TIME_BUDGET_SECONDS = 240  # generous: includes tracemalloc overhead
MEMORY_BUDGET_BYTES = 400 * 1024 * 1024


@unittest.skipUnless(
    os.environ.get("GATLING_AI_PERF") == "1", "set GATLING_AI_PERF=1 to run"
)
class StreamingBudgetTest(unittest.TestCase):
    def test_large_plan_parses_within_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            jmx_path = tmp_path / "big.jmx"
            samplers = []
            for index in range(SAMPLERS):
                body = (
                    f'{{"sampler":{index},"data":"' + "x" * BODY_BYTES + '"}'
                )
                samplers.append(
                    fixtures.http_sampler(
                        f"req-{index}", method="POST", path=f"/x/{index}", body=body
                    )
                )
            document = fixtures.jmx(
                fixtures.thread_group("Main", children="\n".join(samplers))
            )
            jmx_path.write_text(document, encoding="utf-8")
            del document, samplers
            self.assertGreater(jmx_path.stat().st_size, 140 * 1024 * 1024)

            tracemalloc.start()
            started = time.monotonic()
            ir = jmx_parser.parse_jmx(jmx_path, tmp_path / "out")
            elapsed = time.monotonic() - started
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()

            self.assertEqual(ir["stats"]["bodies_externalized"], SAMPLERS)
            self.assertLess(elapsed, TIME_BUDGET_SECONDS)
            self.assertLess(peak, MEMORY_BUDGET_BYTES)


if __name__ == "__main__":
    sys.exit(unittest.main())
```

- [ ] **Step 13.2: Run it once for real**

Run: `$env:GATLING_AI_PERF = "1"; python tools/jmx_parser/test_jmx_parser_perf.py; Remove-Item Env:GATLING_AI_PERF`
Expected: PASS (1 test, takes minutes). If the memory assertion fails, the walker is keeping subtrees alive — verify every branch in `parse_jmx` calls `elem.clear()` and that `scope_stack` holds only IR lists, never XML elements.

- [ ] **Step 13.3: Verify it is skipped by default**

Run: `python tools/jmx_parser/test_jmx_parser_perf.py`
Expected: `OK (skipped=1)`.

- [ ] **Step 13.4: Commit**

```bash
git add tools/jmx_parser/test_jmx_parser_perf.py
git commit -m "test: env-gated 150MB streaming budget for jmx_parser"
```

---

### Task 14: README, ARCHITECTURE, full verification

**Files:**
- Create: `tools/jmx_parser/README.md`
- Modify: `docs/ARCHITECTURE.md`

- [ ] **Step 14.1: Write the tool README**

Create `tools/jmx_parser/README.md`:

```markdown
# jmx_parser

Deterministic streaming parser: JMeter `.jmx` → compact IR for the migration
pipeline (Phase 2). The only component in the repo that reads JMX XML; agents
work with its outputs, never with the raw file.

## Usage

```powershell
# parse (out-dir is usually scenarios/<SYSTEM>/<id>-<NNN>/migration/)
python tools/jmx_parser/jmx_parser.py parse path\to\plan.jmx --out-dir <dir> --format json

# agent-facing slices (avoid loading the whole ir.json into context)
python tools/jmx_parser/jmx_parser.py summary <dir>/ir.json
python tools/jmx_parser/jmx_parser.py element <dir>/ir.json e-0042
```

## Outputs

| Artifact | Purpose |
|---|---|
| `ir.json` | Element tree (ids `e-NNNN` in document order), loads, variable index, complexity flags, stats; validated against `schemas/jmx-ir.schema.json` |
| `inventory.md` | Gate 1 review document: counts, unsupported elements, thread groups, curated data-flow findings, complexity flags |
| `bodies/<sha12>.json\|.txt` | Request bodies above `--max-inline-body-bytes` (default 1024), deduplicated by content hash |
| `jsr223/<sha12>.groovy` | Extracted JSR223 scripts, deduplicated, classified `typical`/`complex` |

## Guarantees

- **No silent drop:** every XML test element lands in the IR; unrecognized
  types get `kind: unknown` and an `unsupported` entry.
- **Determinism:** identical input produces byte-identical `ir.json` and
  `inventory.md` (no timestamps, sorted keys, hash-named artifacts).
- **Bounded memory:** iterparse + clear; peak is the largest single element
  (in practice the largest request body), not file size. Budget-tested at
  ~150 MB via `test_jmx_parser_perf.py` (`GATLING_AI_PERF=1`).

## Known limits (by design, surfaced in inventory)

- BeanShell elements are `unknown` (the target park uses JSR223).
- Multi-row Ultimate Thread Group schedules are not normalized
  (`load.normalized: null` + note) — overlapping ramps need human review.
- Extractor/timer scope is recorded positionally (where the element sits in
  the tree); JMeter "applies to" subtleties are the conversion skill's job.
- JSR223 classification is conservative: anything outside a small allowlist
  of tokens is `complex`. `props` usage is always `complex` (inter-thread).
```

- [ ] **Step 14.2: Update ARCHITECTURE.md**

In `docs/ARCHITECTURE.md`, in the Components table, add after the `mock_sut` row:

```markdown
| `jmx_parser` | Stream-parse legacy `.jmx` into `ir.json`, `inventory.md`, externalized bodies and classified JSR223 scripts; the only component that reads JMX XML (Phase 2). |
```

In the "Planned Repository Structure" code block: under `schemas/` add `  jmx-ir.schema.json`, and under `tools/` add `  jmx_parser/` (keep alphabetical placement with the existing entries).

- [ ] **Step 14.3: Run the full verification list**

```powershell
python tools/jmx_parser/test_jmx_parser.py
python tools/jmx_parser/test_jmx_parser_perf.py   # expect OK (skipped=1)
python tools/_shared/test_common.py
python tools/hook_router/test_hook_router.py
python tools/gatling_generator/test_gatling_generator.py
python tools/scenario_lint/test_scenario_lint.py
python tools/scenario_renderer/test_scenario_renderer.py
python tools/mock_sut/test_mock_sut.py
python tools/quality_gate/test_quality_gate.py
python tools/test_contract_coverage.py
```

Expected: all suites PASS. (`test_contract_coverage.py` is untouched by this plan — the IR schema is a separate contract with its own validation; the scenario-schema coverage harness gains jmx-related consumers in plan 2b.)

- [ ] **Step 14.4: Commit**

```bash
git add tools/jmx_parser/README.md docs/ARCHITECTURE.md
git commit -m "docs: jmx_parser README and architecture entry"
```

---

## Out of scope for this plan (next plans of Phase 2)

- **Plan 2b — contract extensions:** `body_file`, `profile: stages`,
  `start_after_seconds`, `hooks.before/after`, `protocol: kafka|jdbc` stubs and
  `tags` across schema → lint → generator → renderer (+ contract-coverage
  declarations), quality-gate `todo`-hook accounting, disposition convergence
  check (`ir.json` vs `conversion-report.json`).
- **Plan 2c — skills + golden:** `skills/document-legacy-jmeter`,
  `skills/convert-from-jmeter`, two golden `.jmx` examples in `examples/jmx/`,
  end-to-end runs to `gate passed` / `passed_with_warnings`, SCENARIO_FORMAT
  and GETTING_STARTED updates.
- **Spike — Kafka/JDBC:** galax-io plugin on 3.12 + Java DSL; JDBC custom
  action prototype; spike report in `docs/`.


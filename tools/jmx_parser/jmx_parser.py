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

# ${var} but not ${__function(...)}; dots allow feeder-style names.
JMETER_VARIABLE_RE = re.compile(r"\$\{(?!__)([A-Za-z_][A-Za-z0-9_.-]*)\}")
JMETER_FUNCTION_RE = re.compile(r"\$\{__([A-Za-z]+)")  # JMeter built-in function names are alpha-only


def jmeter_variables(text: str) -> list[str]:
    return sorted(set(JMETER_VARIABLE_RE.findall(text)))


def jmeter_functions(text: str) -> list[str]:
    return sorted(set(JMETER_FUNCTION_RE.findall(text)))


def body_extension(text: str) -> str:
    return ".json" if text.lstrip().startswith(("{", "[")) else ".txt"


@dataclass
class ParseState:
    """Mutable accumulator threaded through parse_jmx and all detail builders."""
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

DetailBuilder = Callable[[ElementTree.Element, "ParseState"], dict[str, Any]]
DETAIL_BUILDERS: dict[str, DetailBuilder] = {}


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
        # NOTE: sha12 prefix collision ~2e-7 at 10k unique bodies; accepted for migration tooling.
        ref = f"bodies/{sha[:12]}{body_extension(text)}"
        (state.out_dir / ref).write_text(text, encoding="utf-8", newline="\n")
        state.bodies[sha] = ref
    record.update(
        {"ref": ref, "bytes": len(encoded), "sha256": sha, "preview": text[:PREVIEW_CHARS]}
    )
    return record


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
            return string_prop(argument, "Argument.value", default="")
        return ""  # collection present but empty: raw body, just blank
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
                if not scope_stack:  # defensive; expat rejects unbalanced XML first
                    raise ValueError("malformed jmx: unexpected hashTree close")
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

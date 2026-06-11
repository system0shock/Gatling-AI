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


def double_prop(elem: ElementTree.Element, name: str, default: str = "") -> str:
    for child in elem.findall("doubleProp"):
        name_node = child.find("name")
        if name_node is not None and (name_node.text or "") == name:
            value_node = child.find("value")
            return (value_node.text or "") if value_node is not None else default
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
    "TransactionController": "transaction",
    "GenericController": "simple",
    "IfController": "if",
    "LoopController": "loop",
    "OnceOnlyController": "once_only",
    "ThroughputController": "throughput",
    "TestFragmentController": "fragment",
    "ModuleController": "module",
    "CSVDataSet": "csv_data_set",
    "HeaderManager": "header_manager",
    "CookieManager": "cookie_manager",
    "CounterConfig": "counter",
    "RandomVariableConfig": "random_variable",
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


def csv_details(elem: ElementTree.Element, state: ParseState) -> dict[str, Any]:
    raw_names = string_prop(elem, "variableNames")
    names = [part.strip() for part in raw_names.split(",") if part.strip()]
    return {
        "file": string_prop(elem, "filename"),
        # None means variableNames was blank: JMeter reads the file's first row
        # as headers, so the produced variables are unknown statically.
        "variable_names": names if names else None,
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
                # last writer wins on duplicate names (JMeter GUI allows duplicates)
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


def split_list(value: str) -> list[str]:
    """Split a JMeter semicolon-delimited multi-value property string."""
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


def resolve_modules(ir: dict[str, Any]) -> None:
    """Second phase: link module controllers to their targets by name path.

    When two nodes share a path, the first in document order wins - consistent
    with JMeter's own GUI-tree resolution.
    """
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
        "thread_group": thread_group_details,
        "http_sampler": http_sampler_details,
        "transaction": transaction_details,
        "if": if_details,
        "loop": loop_details,
        "throughput": throughput_details,
        "module": module_details,
    }
)


def resolve_kind(testclass: str, guiclass: str) -> str:
    if testclass == "ConfigTestElement":
        return "http_defaults" if guiclass == "HttpDefaultsGui" else "unknown"
    if testclass == "Arguments":
        return "user_defined_variables"
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

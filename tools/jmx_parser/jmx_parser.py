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
    "JSR223Sampler": "jsr223_sampler",
    "JSR223PreProcessor": "jsr223_pre",
    "JSR223PostProcessor": "jsr223_post",
    "JDBCSampler": "jdbc_sampler",
}

DetailBuilder = Callable[[ElementTree.Element, "ParseState"], dict[str, Any]]
DETAIL_BUILDERS: dict[str, DetailBuilder] = {}


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
        return None, "zero or parameterized stepping parameters"
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
    if not rows:
        return None, "empty schedule (no rows)"
    if len(rows) > 1:
        return None, f"{len(rows)} schedule rows; overlapping ramps need manual review"
    cells = [to_int(value) for value in rows[0][:4]]
    if any(value is None for value in cells):
        return None, "parameterized schedule row"
    users, delay, startup, hold = cells
    shutdown = to_int(rows[0][4]) if len(rows[0]) > 4 else None
    note = (
        "shutdown ramp-down not representable in stages; ignored"
        if shutdown
        else None
    )
    return (
        {
            "model": "closed",
            "stages": [{"users": users, "ramp_seconds": startup, "hold_seconds": hold}],
            "start_after_seconds": delay,
        },
        note,
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
        if steps > 1:
            stages = [
                {
                    "users_per_second": round(target * index / steps / unit, 3),
                    "ramp_seconds": ramp // steps,
                    "hold_seconds": hold // steps,
                }
                for index in range(1, steps + 1)
            ]
            stages[-1]["users_per_second"] = rate
        else:
            stages = [{"users_per_second": rate, "ramp_seconds": ramp, "hold_seconds": hold}]
        return {"model": model, "stages": stages, "start_after_seconds": 0}, None
    if steps > 1:
        # integer division: the last stage may run up to steps-1 seconds short
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
    """Conservatively classify a JSR223 script as mechanically translatable or not.

    "typical" means every identifier is allowlisted or locally declared, and the
    script never touches props. Misclassification toward "complex" only costs an
    extra review; toward "typical" it could silently lose business logic.
    Note: the literal-key props check runs on the RAW script, so even a
    commented-out props call yields "complex" - accepted conservatism.
    """
    reasons: list[str] = []
    if PROPS_CALL_RE.search(script):
        reasons.append("uses props (inter-thread state)")
    stripped = GROOVY_COMMENT_RE.sub(" ", script)
    stripped = GROOVY_STRING_RE.sub(" ", stripped)
    tokens = set(IDENTIFIER_RE.findall(stripped))
    if not reasons and "props" in tokens:
        # dynamic keys (props.get(k)) and bare references never match the
        # literal-key regex above, but are still inter-thread state
        reasons.append("uses props (inter-thread state)")
    declared = {
        match.group(1) or match.group(2) for match in DECLARED_RE.finditer(stripped)
    }
    foreign = sorted(
        {
            token
            for token in tokens
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

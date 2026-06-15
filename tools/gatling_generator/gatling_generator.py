#!/usr/bin/env python3
"""Generate Java Gatling simulations from Gatling-AI scenario YAML."""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _shared.common import (  # noqa: E402
    BLOCKING,
    SYSTEM_RE,
    Finding,
    camel_case,
    finding_to_dict,
    load_yaml,
    script_ref,
    scenario_populations,
)

# Contract coverage declarations: every schema field path is either consumed by
# this generator or explicitly ignored with a reason. Checked by
# tools/test_contract_coverage.py.
STEP_LOAD_CONSUMED = {
    "steps",
    "steps[].name",
    "steps[].transaction",
    "steps[].protocol",
    "steps[].pause_seconds",
    "steps[].request",
    "steps[].request.method",
    "steps[].request.path",
    "steps[].request.headers",
    "steps[].request.body",
    "steps[].request.body_file",
    "steps[].graphql",
    "steps[].graphql.path",
    "steps[].graphql.query",
    "steps[].graphql.variables",
    "steps[].kafka",
    "steps[].kafka.topic",
    "steps[].kafka.key",
    "steps[].kafka.payload",
    "steps[].jdbc",
    "steps[].jdbc.query",
    "steps[].jdbc.saveAs",
    "steps[].hooks",
    "steps[].hooks.before",
    "steps[].hooks.before[].ref",
    "steps[].hooks.before[].kind",
    "steps[].hooks.before[].snippet",
    "steps[].hooks.before[].summary",
    "steps[].hooks.before[].reads",
    "steps[].hooks.before[].writes",
    "steps[].hooks.after",
    "steps[].hooks.after[].ref",
    "steps[].hooks.after[].kind",
    "steps[].hooks.after[].snippet",
    "steps[].hooks.after[].summary",
    "steps[].hooks.after[].reads",
    "steps[].hooks.after[].writes",
    "steps[].checks",
    "steps[].checks[].status",
    "steps[].checks[].extract",
    "steps[].checks[].extract.type",
    "steps[].checks[].extract.expr",
    "steps[].checks[].extract.saveAs",
    "load",
    "load.model",
    "load.profile",
    "load.users",
    "load.users_per_second",
    "load.ramp_seconds",
    "load.duration_seconds",
    "load.levels",
    "load.level_duration_seconds",
    "load.baseline_users",
    "load.baseline_users_per_second",
    "load.baseline_seconds",
    "load.spike_rise_seconds",
    "load.spike_hold_seconds",
    "load.stages",
    "load.stages[].users",
    "load.stages[].users_per_second",
    "load.stages[].ramp_seconds",
    "load.stages[].hold_seconds",
}
STEP_LOAD_IGNORED = {
    "steps[].title",  # human label; transaction is the display name
    "steps[].tags",  # migration markers for skills/reports; no codegen impact
}

# Body-file extensions that Gatling treats as EL templates (${var} -> #{var});
# any other extension is copied verbatim via RawFileBody.
EL_BODY_SUFFIXES = {".json", ".txt", ".xml"}


def _expand(prefix: str, fields: set[str]) -> set[str]:
    return {f"{prefix}{field}" for field in fields}


CONSUMED_FIELDS = (
    {
        "scenario",
        "scenario.id",
        "scenario.title",
        "scenario.system",
        "scenario.number",
        "scenario.sut",
        "scenario.sut.base_url",
        "scenario.data",
        "scenario.data.feeders",
        "scenario.data.feeders[].file",
        "scenario.data.feeders[].strategy",
        "scenario.populations",
        "scenario.populations[].name",
        "scenario.populations[].start_after_seconds",
        "scenario.assertions",
        "scenario.assertions[].metric",
        "scenario.assertions[].op",
        "scenario.assertions[].value",
    }
    | _expand("scenario.", STEP_LOAD_CONSUMED)
    | _expand("scenario.populations[].", STEP_LOAD_CONSUMED)
)
IGNORED_FIELDS = (
    {
        "scenario.source",  # requirements provenance; documented by the renderer
        "scenario.source.type",
        "scenario.source.ref",
        "scenario.data.feeders[].name",  # used by lint/renderer correlation, not codegen
        "scenario.assertions[].name",  # report label only
        "lint_waivers",  # lint concern
        "lint_waivers[].rule",
        "lint_waivers[].reason",
        "lint_waivers[].owner",
        "lint_waivers[].expires",
    }
    | _expand("scenario.", STEP_LOAD_IGNORED)
    | _expand("scenario.populations[].", STEP_LOAD_IGNORED)
)

SNIPPET_CLASS_RE = re.compile(r"^[A-Z][A-Za-z0-9]*$")
VARIABLE_ONLY_RE = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")
SCENARIO_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
SCENARIO_PLACEHOLDER_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_.-]*)\}")

JAVA_KEYWORDS = {
    "abstract", "assert", "boolean", "break", "byte", "case", "catch", "char",
    "class", "const", "continue", "default", "do", "double", "else", "enum",
    "extends", "final", "finally", "float", "for", "goto", "if", "implements",
    "import", "instanceof", "int", "interface", "long", "native", "new",
    "package", "private", "protected", "public", "return", "short", "static",
    "strictfp", "super", "switch", "synchronized", "this", "throw", "throws",
    "transient", "try", "void", "volatile", "while",
    # reserved literals (JLS 3.10): not keywords, but equally forbidden as identifiers
    "true", "false", "null",
}


def builder_variable(name: str, kind: str, seen_vars: dict[str, str]) -> str:
    var = camel_case(name)
    if var in JAVA_KEYWORDS:
        raise ValueError(f"{kind} name {name!r} maps to a Java keyword variable {var!r}")
    if var in seen_vars:
        raise ValueError(
            f"{kind} name {name!r} and {seen_vars[var]!r} collide on builder variable {var!r}"
        )
    seen_vars[var] = name
    return var


def java_string(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", "\\r")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def validate_scenario_id(scenario_id: str) -> None:
    if not SCENARIO_ID_RE.fullmatch(scenario_id):
        raise ValueError(
            "scenario.id must be kebab-case: start with a lowercase letter and "
            "use lowercase letters/digits separated by single hyphens"
        )


def validate_population_name(name: str) -> None:
    if not SCENARIO_ID_RE.fullmatch(name):
        raise ValueError(
            f"population name must be kebab-case: {name!r}"
        )


def validate_step_name(name: str) -> None:
    # Step names become ChainBuilder variables, so they must camel-case to a
    # valid Java identifier; kebab-case (e.g. "open-products") guarantees that.
    if not SCENARIO_ID_RE.fullmatch(name):
        raise ValueError(
            f"step name must be kebab-case: {name!r}"
        )


def validate_system(system: Any) -> str:
    if not isinstance(system, str) or not SYSTEM_RE.fullmatch(system):
        raise ValueError("scenario.system must match ^[A-Z][A-Z0-9]{1,9}$ (e.g. SHOP)")
    return system


def validate_number(number: Any) -> int:
    if isinstance(number, bool) or not isinstance(number, int) or number < 1:
        raise ValueError("scenario.number must be a positive integer")
    return number


def gatling_el_string(value: str) -> str:
    return SCENARIO_PLACEHOLDER_RE.sub(r"#{\1}", value)


def pause_call(pause_seconds: Any) -> str:
    if isinstance(pause_seconds, bool) or not isinstance(pause_seconds, (int, float)):
        raise ValueError(f"pause_seconds must be a number: {pause_seconds!r}")
    if not math.isfinite(pause_seconds):
        raise ValueError(f"pause_seconds must be finite: {pause_seconds!r}")
    if pause_seconds <= 0:
        raise ValueError("pause_seconds must be positive")
    if float(pause_seconds) == int(pause_seconds):
        return f"pause(Duration.ofSeconds({int(pause_seconds)}))"
    millis = round(float(pause_seconds) * 1000)
    if millis <= 0:
        raise ValueError(
            f"pause_seconds {pause_seconds!r} rounds to 0 ms; minimum expressible value is 0.001"
        )
    return f"pause(Duration.ofMillis({millis}))"


def require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a mapping")
    return value


def require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    return value


def load_base_url_expression(base_url: str) -> tuple[str, list[str]]:
    match = VARIABLE_ONLY_RE.match(base_url)
    if not match:
        return java_string(base_url), []

    env_name = match.group(1)
    helper = [
        "",
        "  private static String requiredEnv(String name) {",
        "    String value = System.getenv(name);",
        "    if (value == null || value.isBlank()) {",
        '      throw new IllegalStateException("Missing required environment variable: " + name);',
        "    }",
        "    return value;",
        "  }",
    ]
    return f"requiredEnv({java_string(env_name)})", helper


def feeder_expression(feeder: dict[str, Any]) -> str:
    file_name = str(feeder["file"])
    strategy = str(feeder.get("strategy", "queue")).lower()
    strategy_method = {
        "circular": "circular",
        "random": "random",
        "queue": "queue",
        "shuffle": "shuffle",
    }.get(strategy)
    if strategy_method is None:
        raise ValueError(f"unsupported feeder strategy: {strategy}")
    return f"csv({java_string(file_name)}).{strategy_method}()"


ASSERTION_OPS = {"<": "lt", "<=": "lte", ">": "gt", ">=": "gte", "==": "is", "=": "is"}
PERCENTILE_RE = re.compile(r"^p(\d{1,2})$")


def format_number(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"assertion value must be a number: {value!r}")
    if not math.isfinite(float(value)):
        raise ValueError(f"assertion value must be finite: {value!r}")
    if isinstance(value, int) or value == int(value):
        return str(int(value))
    return repr(float(value))


def format_double(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"assertion value must be a number: {value!r}")
    if not math.isfinite(float(value)):
        raise ValueError(f"assertion value must be finite: {value!r}")
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
        method = ASSERTION_OPS.get(op)
        if method is None:
            raise ValueError(f"unsupported assertion op: {op}")
        return f"{base}.{method}({format_double(assertion['value'])})"
    else:
        raise ValueError(f"unsupported assertion metric: {metric}")
    method = ASSERTION_OPS.get(op)
    if method is None:
        raise ValueError(f"unsupported assertion op: {op}")
    return f"{base}.{method}({format_number(assertion['value'])})"


def render_check(check: dict[str, Any]) -> str:
    if "status" in check:
        return f"status().is({int(check['status'])})"

    extract = check.get("extract")
    if not isinstance(extract, dict):
        raise ValueError(f"unsupported check: {check}")

    extract_type = str(extract.get("type", ""))
    expr = str(extract["expr"])
    save_as = str(extract["saveAs"])
    extractor = {"css": "css", "jsonPath": "jsonPath", "regex": "regex"}.get(extract_type)
    if extractor is None:
        raise ValueError(f"unsupported extract check type: {extract_type}")
    return f"{extractor}({java_string(expr)}).saveAs({java_string(save_as)})"


def has_redirect_status_check(checks: list[Any]) -> bool:
    for check in checks:
        check_mapping = require_mapping(check, "check")
        if "status" in check_mapping:
            status = int(check_mapping["status"])
            if 300 <= status <= 399:
                return True
    return False


def request_chain(step: dict[str, Any]) -> list[str]:
    request = require_mapping(step.get("request"), "step.request")
    method = str(request.get("method", "")).upper()
    if method not in {"GET", "POST"}:
        raise ValueError(f"unsupported HTTP method: {method}")

    display_name = str(step.get("transaction") or step.get("name"))
    lines = [f"          http({java_string(display_name)})"]
    method_call = "get" if method == "GET" else "post"
    path = java_string(gatling_el_string(str(request["path"])))
    lines.append(f"            .{method_call}({path})")

    checks = require_list(step.get("checks"), "step.checks")
    if has_redirect_status_check(checks):
        lines.append("            .disableFollowRedirect()")

    headers = request.get("headers")
    if isinstance(headers, dict):
        for key in sorted(headers):
            value = java_string(gatling_el_string(str(headers[key])))
            lines.append(
                f"            .header({java_string(str(key))}, {value})"
            )

    if "body" in request and "body_file" in request:
        raise ValueError("request must use either body or body_file, not both")
    if "body" in request:
        body = java_string(gatling_el_string(str(request["body"])))
        lines.append(f"            .body(StringBody({body}))")
    elif "body_file" in request:
        rel = Path(str(request["body_file"]))
        body_call = "ElFileBody" if rel.suffix.lower() in EL_BODY_SUFFIXES else "RawFileBody"
        lines.append(f"            .body({body_call}({java_string(rel.as_posix())}))")

    lines.extend(check_chain_lines(checks))
    return lines


def check_chain_lines(checks: list[Any]) -> list[str]:
    return [
        f"            .check({render_check(require_mapping(check, 'check'))})" for check in checks
    ]


def graphql_chain(step: dict[str, Any]) -> list[str]:
    graphql = require_mapping(step.get("graphql"), "step.graphql")
    if not str(graphql.get("query", "")).strip():
        raise ValueError("graphql steps require a non-empty query")
    path = str(graphql.get("path", "/graphql"))
    payload: dict[str, Any] = {"query": str(graphql["query"])}
    if "variables" in graphql:
        payload["variables"] = require_mapping(graphql["variables"], "step.graphql.variables")
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    checks = require_list(step.get("checks"), "step.checks")
    display_name = str(step.get("transaction") or step.get("name"))
    lines = [
        f"          http({java_string(display_name)})",
        f"            .post({java_string(gatling_el_string(path))})",
        '            .header("Content-Type", "application/json")',
        f"            .body(StringBody({java_string(gatling_el_string(body))}))",
    ]
    if has_redirect_status_check(checks):
        lines.append("            .disableFollowRedirect()")
    lines.extend(check_chain_lines(checks))
    return lines


def step_chain(step: dict[str, Any]) -> list[str]:
    protocol = str(step.get("protocol", "http"))
    if protocol == "http":
        return request_chain(step)
    if protocol == "graphql":
        return graphql_chain(step)
    raise ValueError(f"unsupported step protocol: {protocol}")


def hook_pairs(step: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    hooks = step.get("hooks") if isinstance(step.get("hooks"), dict) else {}
    pairs: list[tuple[str, dict[str, Any]]] = []
    for when in ("before", "after"):
        entries = hooks.get(when) if isinstance(hooks.get(when), list) else []
        pairs.extend((when, entry) for entry in entries if isinstance(entry, dict))
    return pairs


def snippet_class(snippet_path: str) -> str:
    stem = Path(snippet_path).stem
    if not SNIPPET_CLASS_RE.fullmatch(stem):
        raise ValueError(
            f"snippet file stem must be a PascalCase Java class name: {snippet_path!r}"
        )
    return stem


def one_line(text: Any) -> str:
    return " ".join(str(text).split())


def todo_hook_comments(step: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for when, hook in hook_pairs(step):
        if hook.get("kind") != "todo":
            continue
        extras: list[str] = []
        for field in ("reads", "writes"):
            values = hook.get(field)
            if isinstance(values, list) and values:
                extras.append(f"{field}: " + ", ".join(str(value) for value in values))
        suffix = f" ({'; '.join(extras)})" if extras else ""
        lines.append(
            f"  // TODO(jsr223 {when}): {one_line(hook['summary'])} — "
            f"original: {hook['ref']}{suffix}"
        )
    return lines


def translated_snippets(step: dict[str, Any], when: str) -> list[str]:
    return [
        snippet_class(str(hook["snippet"]))
        for hook_when, hook in hook_pairs(step)
        if hook_when == when and hook.get("kind") == "translated"
    ]


def comment_preview(text: str, limit: int = 80) -> str:
    flat = one_line(gatling_el_string(text))
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def kafka_stub_chain(step: dict[str, Any]) -> list[str]:
    kafka = require_mapping(step.get("kafka"), "step.kafka")
    topic = comment_preview(str(kafka.get("topic", "")))
    header = f"      // topic: {topic}"
    if kafka.get("key") is not None:
        header += f" | key: {comment_preview(str(kafka['key']))}"
    return [
        "exec(session -> {",
        "      // TODO(kafka-stub): replace with a real Kafka action after the protocol spike (FR5.6.3).",
        header,
        f"      // payload: {comment_preview(str(kafka.get('payload', '')))}",
        "      return session;",
        "    })",
    ]


def jdbc_stub_chain(step: dict[str, Any]) -> list[str]:
    jdbc = require_mapping(step.get("jdbc"), "step.jdbc")
    lines = [
        "exec(session -> {",
        "      // TODO(jdbc-stub): replace with a real JDBC action after the protocol spike (FR5.6.3).",
        f"      // query: {comment_preview(str(jdbc.get('query', '')))}",
    ]
    save_as = jdbc.get("saveAs")
    if isinstance(save_as, str) and save_as:
        lines.append(f"      return session.set({java_string(save_as)}, \"jdbc-stub\");")
    else:
        lines.append("      return session;")
    lines.append("    })")
    return lines


def render_chain_field(var: str, step: dict[str, Any]) -> list[str]:
    lines = [""]
    lines.extend(todo_hook_comments(step))
    lines.append(f"  private final ChainBuilder {var} =")
    segments: list[list[str]] = []
    for cls in translated_snippets(step, "before"):
        segments.append([f"exec({cls}::apply)"])
    protocol = str(step.get("protocol", "http"))
    if protocol == "kafka":
        core = kafka_stub_chain(step)
    elif protocol == "jdbc":
        core = jdbc_stub_chain(step)
    else:
        core = ["exec(", *step_chain(step), "    )"]
    segments.append(core)
    for cls in translated_snippets(step, "after"):
        segments.append([f"exec({cls}::apply)"])
    for index, segment in enumerate(segments):
        head = "    " if index == 0 else "    ."
        lines.append(head + segment[0])
        lines.extend(segment[1:])
    lines[-1] += ";"
    return lines


def render_group_line(step: dict[str, Any], var: str, is_last: bool) -> str:
    display_name = str(step.get("transaction") or step.get("name"))
    line = f"    .group({java_string(display_name)}).on({var})"
    if "pause_seconds" in step:
        line += f".{pause_call(step['pause_seconds'])}"
    return line + (";" if is_last else "")


def format_rate(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"rate must be a positive number: {value!r}")
    if float(value) == int(value):
        return str(int(value))
    return repr(float(value))


def positive_int(load: dict[str, Any], field: str) -> int:
    value = load.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"load.{field} must be a positive integer")
    return value


def duration(seconds: int) -> str:
    return f"Duration.ofSeconds({seconds})"


def stage_duration_field(stage: dict[str, Any], field: str) -> int:
    value = stage.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"stage {field} must be a non-negative integer")
    return value


def stages_injection_steps(model: str, load: dict[str, Any]) -> list[str]:
    stages = require_list(load.get("stages"), "load.stages")
    if not stages:
        raise ValueError("load.stages must not be empty")
    steps: list[str] = []
    previous = "0"
    for stage in stages:
        stage_map = require_mapping(stage, "stage")
        ramp = stage_duration_field(stage_map, "ramp_seconds")
        hold = stage_duration_field(stage_map, "hold_seconds")
        if ramp == 0 and hold == 0:
            raise ValueError("stage must have ramp_seconds or hold_seconds greater than zero")
        if model == "closed":
            users = stage_map.get("users")
            if isinstance(users, bool) or not isinstance(users, int) or users <= 0:
                raise ValueError("stage users must be a positive integer")
            target = str(users)
            ramp_call, hold_call = "rampConcurrentUsers", "constantConcurrentUsers"
        else:
            target = format_rate(stage_map.get("users_per_second"))
            ramp_call, hold_call = "rampUsersPerSec", "constantUsersPerSec"
        if ramp > 0:
            steps.append(f"{ramp_call}({previous}).to({target}).during({duration(ramp)})")
        if hold > 0:
            steps.append(f"{hold_call}({target}).during({duration(hold)})")
        previous = target
    return steps


def closed_injection_steps(profile: str, load: dict[str, Any]) -> list[str]:
    if profile == "stages":
        return stages_injection_steps("closed", load)
    if profile == "ramp":
        users = positive_int(load, "users")
        return [
            f"rampConcurrentUsers(0).to({users}).during({duration(positive_int(load, 'ramp_seconds'))})",
            f"constantConcurrentUsers({users}).during({duration(positive_int(load, 'duration_seconds'))})",
        ]
    if profile in {"constant", "soak"}:
        users = positive_int(load, "users")
        return [
            f"constantConcurrentUsers({users}).during({duration(positive_int(load, 'duration_seconds'))})"
        ]
    if profile == "stress":
        users = positive_int(load, "users")
        levels = positive_int(load, "levels")
        if levels < 2:
            raise ValueError(f"closed stress requires levels >= 2, got {levels}")
        if users % levels != 0:
            raise ValueError(
                f"closed stress requires users ({users}) divisible by levels ({levels})"
            )
        step = users // levels
        level_duration = positive_int(load, "level_duration_seconds")
        return [
            f"incrementConcurrentUsers({step}).times({levels})"
            f".eachLevelLasting({duration(level_duration)}).startingFrom({step})"
        ]
    if profile == "spike":
        peak = positive_int(load, "users")
        baseline = positive_int(load, "baseline_users")
        if baseline >= peak:
            raise ValueError("spike baseline_users must be below users (the peak)")
        baseline_d = duration(positive_int(load, "baseline_seconds"))
        rise_d = duration(positive_int(load, "spike_rise_seconds"))
        hold_d = duration(positive_int(load, "spike_hold_seconds"))
        return [
            f"constantConcurrentUsers({baseline}).during({baseline_d})",
            f"rampConcurrentUsers({baseline}).to({peak}).during({rise_d})",
            f"constantConcurrentUsers({peak}).during({hold_d})",
            f"rampConcurrentUsers({peak}).to({baseline}).during({rise_d})",
            f"constantConcurrentUsers({baseline}).during({baseline_d})",
        ]
    raise ValueError(f"unsupported load profile: {profile}")


def open_injection_steps(profile: str, load: dict[str, Any]) -> list[str]:
    if profile == "stages":
        return stages_injection_steps("open", load)
    if profile == "ramp":
        rate = format_rate(load.get("users_per_second"))
        return [
            f"rampUsersPerSec(0).to({rate}).during({duration(positive_int(load, 'ramp_seconds'))})",
            f"constantUsersPerSec({rate}).during({duration(positive_int(load, 'duration_seconds'))})",
        ]
    if profile in {"constant", "soak"}:
        rate = format_rate(load.get("users_per_second"))
        return [
            f"constantUsersPerSec({rate}).during({duration(positive_int(load, 'duration_seconds'))})"
        ]
    if profile == "stress":
        raw_rate = load.get("users_per_second")
        format_rate(raw_rate)
        levels = positive_int(load, "levels")
        if levels < 2:
            raise ValueError(f"stress requires levels >= 2, got {levels}")
        step = format_rate(float(raw_rate) / levels)
        level_duration = positive_int(load, "level_duration_seconds")
        return [
            f"incrementUsersPerSec({step}).times({levels})"
            f".eachLevelLasting({duration(level_duration)}).startingFrom({step})"
        ]
    if profile == "spike":
        peak = format_rate(load.get("users_per_second"))
        baseline = format_rate(load.get("baseline_users_per_second"))
        if float(load["baseline_users_per_second"]) >= float(load["users_per_second"]):
            raise ValueError("spike baseline_users_per_second must be below users_per_second")
        baseline_d = duration(positive_int(load, "baseline_seconds"))
        rise_d = duration(positive_int(load, "spike_rise_seconds"))
        hold_d = duration(positive_int(load, "spike_hold_seconds"))
        return [
            f"constantUsersPerSec({baseline}).during({baseline_d})",
            f"rampUsersPerSec({baseline}).to({peak}).during({rise_d})",
            f"constantUsersPerSec({peak}).during({hold_d})",
            f"rampUsersPerSec({peak}).to({baseline}).during({rise_d})",
            f"constantUsersPerSec({baseline}).during({baseline_d})",
        ]
    raise ValueError(f"unsupported load profile: {profile}")


def render_injection(load: dict[str, Any]) -> tuple[str, list[str]]:
    model = str(load.get("model", ""))
    profile = str(load.get("profile", ""))
    if model == "closed":
        return "injectClosed", closed_injection_steps(profile, load)
    if model == "open":
        return "injectOpen", open_injection_steps(profile, load)
    raise ValueError(f"unsupported load model: {model}")


def render_setup(
    builders: list[tuple[str, dict[str, Any]]], assertions: list[Any]
) -> list[str]:
    lines = ["  {", "    setUp("]
    for builder_index, (var, population) in enumerate(builders):
        load = require_mapping(population.get("load"), "population.load")
        method, injection_steps = render_injection(load)
        start_after = population.get("start_after_seconds")
        if start_after is not None:
            if isinstance(start_after, bool) or not isinstance(start_after, int) or start_after <= 0:
                raise ValueError("population start_after_seconds must be a positive integer")
            injection_steps = [f"nothingFor({duration(start_after)})"] + injection_steps
        lines.append(f"      {var}.{method}(")
        for index, injection in enumerate(injection_steps):
            suffix = "," if index < len(injection_steps) - 1 else ""
            lines.append(f"        {injection}{suffix}")
        lines.append("      )," if builder_index < len(builders) - 1 else "      )")
    lines.extend(["    ).protocols(httpProtocol)", "      .assertions("])
    rendered_assertions = [
        render_assertion(require_mapping(assertion, "assertion")) for assertion in assertions
    ]
    for index, rendered in enumerate(rendered_assertions):
        suffix = "," if index < len(rendered_assertions) - 1 else ""
        lines.append(f"        {rendered}{suffix}")
    lines.extend(["      );", "  }"])
    return lines


def render_population_builder(
    var: str, display: str, population: dict[str, Any], feeders: list[Any], step_vars: list[str]
) -> list[str]:
    lines = [
        "",
        f"  private final ScenarioBuilder {var} = scenario({java_string(display)})",
    ]
    for feeder in feeders:
        lines.append(f"    .feed({feeder_expression(require_mapping(feeder, 'feeder'))})")
    steps = require_list(population.get("steps"), "population.steps")
    if not steps:
        raise ValueError("population steps must not be empty")
    for index, step in enumerate(steps):
        lines.append(
            render_group_line(require_mapping(step, "step"), step_vars[index], index == len(steps) - 1)
        )
    return lines


def render_simulation(document: dict[str, Any]) -> tuple[str, str]:
    scenario = require_mapping(document.get("scenario"), "scenario")
    scenario_id = str(scenario["id"])
    validate_scenario_id(scenario_id)
    class_name = script_ref(
        validate_system(scenario.get("system")),
        scenario_id,
        validate_number(scenario.get("number")),
    )
    title = str(scenario["title"])
    sut = require_mapping(scenario.get("sut"), "scenario.sut")
    base_url_expression, helper_lines = load_base_url_expression(str(sut["base_url"]))

    data = scenario.get("data") if isinstance(scenario.get("data"), dict) else {}
    feeders = data.get("feeders") if isinstance(data.get("feeders"), list) else []

    assertions = require_list(scenario.get("assertions"), "scenario.assertions")
    if not assertions:
        raise ValueError("scenario.assertions must contain at least one assertion")

    explicit = isinstance(scenario.get("populations"), list)
    populations = scenario_populations(scenario)

    seen_vars: dict[str, str] = {"httpProtocol": "<reserved field>"}
    builders: list[tuple[str, str, dict[str, Any], list[str]]] = []
    chain_lines: list[str] = []
    for population in populations:
        if explicit:
            name = str(population.get("name", ""))
            validate_population_name(name)
            var, display = builder_variable(name, "population", seen_vars), name
        else:
            var, display = "scenario", title
            seen_vars["scenario"] = "<single-flow scenario>"
        steps = require_list(population.get("steps"), "population.steps")
        step_vars: list[str] = []
        for step in steps:
            step_mapping = require_mapping(step, "step")
            step_name = str(step_mapping.get("name", ""))
            validate_step_name(step_name)
            step_var = builder_variable(step_name, "step", seen_vars)
            step_vars.append(step_var)
            chain_lines.extend(render_chain_field(step_var, step_mapping))
        builders.append((var, display, population, step_vars))

    lines = [
        "import io.gatling.javaapi.core.ChainBuilder;",
        "import io.gatling.javaapi.core.ScenarioBuilder;",
        "import io.gatling.javaapi.core.Simulation;",
        "import io.gatling.javaapi.http.HttpProtocolBuilder;",
        "import java.time.Duration;",
        "",
        "import static io.gatling.javaapi.core.CoreDsl.*;",
        "import static io.gatling.javaapi.http.HttpDsl.*;",
        "",
        f"public class {class_name} extends Simulation {{",
    ]
    lines.extend(helper_lines)
    lines.extend(
        [
            "",
            f"  private final HttpProtocolBuilder httpProtocol = http.baseUrl({base_url_expression});",
        ]
    )
    lines.extend(chain_lines)
    for var, display, population, step_vars in builders:
        lines.extend(render_population_builder(var, display, population, feeders, step_vars))

    lines.append("")
    lines.extend(render_setup([(var, population) for var, _display, population, _sv in builders], assertions))
    lines.append("}")
    return class_name, "\n".join(lines) + "\n"


TEMPLATE_POM = Path(__file__).resolve().parent / "templates" / "pom.xml"


def bootstrap_project(output_dir: Path) -> bool:
    """Create a pinned Maven Gatling project when output_dir has no pom.xml."""
    pom = output_dir / "pom.xml"
    if pom.exists():
        return False
    (output_dir / "src" / "test" / "java").mkdir(parents=True, exist_ok=True)
    (output_dir / "src" / "test" / "resources").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(TEMPLATE_POM, pom)
    return True


def copy_feeder_resources(document: dict[str, Any], scenario_path: Path, output_dir: Path) -> None:
    scenario = require_mapping(document.get("scenario"), "scenario")
    data = scenario.get("data") if isinstance(scenario.get("data"), dict) else {}
    feeders = data.get("feeders") if isinstance(data.get("feeders"), list) else []
    if not feeders:
        return

    resources_dir = output_dir / "src" / "test" / "resources"
    scenario_dir = scenario_path.parent.resolve()
    for feeder in feeders:
        feeder_mapping = require_mapping(feeder, "feeder")
        feeder_file = Path(str(feeder_mapping["file"]))
        if feeder_file.is_absolute() or ".." in feeder_file.parts:
            raise ValueError(f"feeder file must be relative to the scenario directory: {feeder_file}")

        source = (scenario_dir / feeder_file).resolve()
        if not source.is_relative_to(scenario_dir):
            raise ValueError(
                f"feeder file resolves outside the scenario directory: {feeder_file}"
            )
        if not source.is_file():
            raise ValueError(f"feeder file does not exist: {source}")

        destination = resources_dir / feeder_file
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)


def iter_steps(document: dict[str, Any]) -> list[dict[str, Any]]:
    scenario = require_mapping(document.get("scenario"), "scenario")
    steps: list[dict[str, Any]] = []
    for population in scenario_populations(scenario):
        for step in population.get("steps") or []:
            if isinstance(step, dict):
                steps.append(step)
    return steps


def copy_hook_snippets(document: dict[str, Any], scenario_path: Path, output_dir: Path) -> None:
    scenario_dir = scenario_path.parent.resolve()
    copied: dict[str, Path] = {}
    for step in iter_steps(document):
        for _when, hook in hook_pairs(step):
            if hook.get("kind") != "translated":
                continue
            snippet_value = str(hook["snippet"])
            cls = snippet_class(snippet_value)
            rel = Path(snippet_value)
            if rel.is_absolute() or ".." in rel.parts:
                raise ValueError(f"snippet must be relative to the scenario directory: {rel}")
            source = (scenario_dir / rel).resolve()
            if not source.is_relative_to(scenario_dir):
                raise ValueError(f"snippet resolves outside the scenario directory: {rel}")
            if not source.is_file():
                raise ValueError(f"snippet does not exist: {source}")
            if cls in copied and copied[cls] != source:
                raise ValueError(f"snippet class name collision across files: {cls}")
            copied[cls] = source
    if not copied:
        return
    java_dir = output_dir / "src" / "test" / "java"
    java_dir.mkdir(parents=True, exist_ok=True)
    for cls, source in sorted(copied.items()):
        shutil.copyfile(source, java_dir / f"{cls}.java")


def copy_body_files(document: dict[str, Any], scenario_path: Path, output_dir: Path) -> None:
    resources_dir = output_dir / "src" / "test" / "resources"
    scenario_dir = scenario_path.parent.resolve()
    for step in iter_steps(document):
        request = step.get("request") if isinstance(step.get("request"), dict) else {}
        body_file = request.get("body_file")
        if not isinstance(body_file, str) or not body_file:
            continue
        rel = Path(body_file)
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError(f"body file must be relative to the scenario directory: {rel}")
        source = (scenario_dir / rel).resolve()
        if not source.is_relative_to(scenario_dir):
            raise ValueError(f"body file resolves outside the scenario directory: {rel}")
        if not source.is_file():
            raise ValueError(f"body file does not exist: {source}")
        destination = resources_dir / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        if rel.suffix.lower() in EL_BODY_SUFFIXES:
            destination.write_text(
                gatling_el_string(source.read_text(encoding="utf-8")),
                encoding="utf-8",
                newline="\n",
            )
        else:
            shutil.copyfile(source, destination)


def write_simulation(scenario_path: Path, output_dir: Path) -> tuple[Path, bool]:
    document = load_yaml(scenario_path)
    document_mapping = require_mapping(document, "document")
    class_name, content = render_simulation(document_mapping)
    bootstrapped = bootstrap_project(output_dir)
    java_dir = output_dir / "src" / "test" / "java"
    java_dir.mkdir(parents=True, exist_ok=True)
    output_path = java_dir / f"{class_name}.java"
    output_path.write_text(content, encoding="utf-8", newline="\n")
    copy_feeder_resources(document_mapping, scenario_path, output_dir)
    copy_body_files(document_mapping, scenario_path, output_dir)
    copy_hook_snippets(document_mapping, scenario_path, output_dir)
    return output_path, bootstrapped


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
        output_path, bootstrapped = write_simulation(args.scenario, args.output_dir)
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
        print(
            json.dumps(
                {
                    "blocking": [],
                    "bootstrapped": bootstrapped,
                    "output": output_path.as_posix(),
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(output_path.as_posix())
    return 0


if __name__ == "__main__":
    sys.exit(main())

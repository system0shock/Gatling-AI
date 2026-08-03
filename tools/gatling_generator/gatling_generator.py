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
    "steps[].kafka.request_reply",
    "steps[].kafka.reply_topic",
    "steps[].kafka.checks",
    "steps[].kafka.checks[].jsonPath",
    "steps[].kafka.checks[].is",
    "steps[].jdbc",
    "steps[].jdbc.query",
    "steps[].jdbc.saveAs",
    "steps[].jdbc.action",
    "steps[].jdbc.table",
    "steps[].jdbc.columns",
    "steps[].jdbc.values",
    "steps[].jdbc.set",
    "steps[].jdbc.where",
    "steps[].jdbc.sql",
    "steps[].jdbc.procedure",
    "steps[].jdbc.params",
    "steps[].jdbc.out_params",
    "steps[].hooks",
    "steps[].hooks.before",
    "steps[].hooks.before[].ref",
    "steps[].hooks.before[].kind",
    "steps[].hooks.before[].snippet",
    "steps[].hooks.before[].summary",
    "steps[].hooks.before[].reads",
    "steps[].hooks.before[].writes",
    "steps[].hooks.before[].hints",
    "steps[].hooks.before[].hints[].kind",
    "steps[].hooks.after",
    "steps[].hooks.after[].ref",
    "steps[].hooks.after[].kind",
    "steps[].hooks.after[].snippet",
    "steps[].hooks.after[].summary",
    "steps[].hooks.after[].reads",
    "steps[].hooks.after[].writes",
    "steps[].hooks.after[].hints",
    "steps[].hooks.after[].hints[].kind",
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
        "scenario.lifecycle",
        "scenario.sut",
        "scenario.sut.base_url",
        "scenario.data",
        "scenario.data.feeders",
        "scenario.data.feeders[].file",
        "scenario.data.feeders[].strategy",
        "scenario.data.feeders[].delimiter",
        "scenario.data.feeders[].ignore_first_line",
        "scenario.data.feeders[].quoted_text",
        "scenario.data.feeders[].share_mode",
        "scenario.data.feeders[].recycle",
        "scenario.data.feeders[].random_order",
        "scenario.populations",
        "scenario.populations[].name",
        "scenario.populations[].start_after_seconds",
        "scenario.assertions",
        "scenario.assertions[].metric",
        "scenario.assertions[].op",
        "scenario.assertions[].value",
        "scenario.protocols",
        "scenario.protocols.kafka",
        "scenario.protocols.kafka.bootstrap_servers",
        "scenario.protocols.kafka.properties",
        "scenario.protocols.kafka.timeout_seconds",
        "scenario.protocols.kafka.match_by",
        "scenario.protocols.jdbc",
        "scenario.protocols.jdbc.url",
        "scenario.protocols.jdbc.username",
        "scenario.protocols.jdbc.password",
        "scenario.protocols.jdbc.maximum_pool_size",
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

CUSTOM_ZONE_RE = re.compile(
    r"(  // @custom:(\w+)[^\n]*\n)(.*?)(  // @custom-end)",
    re.DOTALL,
)

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


REQUIRED_ENV_HELPER: list[str] = [
    "",
    "  private static String requiredEnv(String name) {",
    "    String value = System.getenv(name);",
    "    if (value == null || value.isBlank()) {",
    '      throw new IllegalStateException("Missing required environment variable: " + name);',
    "    }",
    "    return value;",
    "  }",
]


def env_var_expression(value: str) -> str:
    match = VARIABLE_ONLY_RE.match(value)
    if not match:
        return java_string(value)
    return f"requiredEnv({java_string(match.group(1))})"


def load_base_url_expression(base_url: str) -> tuple[str, list[str]]:
    match = VARIABLE_ONLY_RE.match(base_url)
    if not match:
        return java_string(base_url), []

    env_name = match.group(1)
    return f"requiredEnv({java_string(env_name)})", list(REQUIRED_ENV_HELPER)


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
    base = f"csv({java_string(file_name)})"
    delimiter = feeder.get("delimiter")
    if delimiter and delimiter != ",":
        base += f".separator({java_string(delimiter)})"
    if feeder.get("ignore_first_line"):
        base += ".skipHeaderRow()"
    if feeder.get("quoted_text"):
        base += ".quoted()"
    base += f".{strategy_method}()"
    todos: list[str] = []
    share_mode = feeder.get("share_mode")
    if share_mode:
        todos.append(f"share_mode={share_mode}")
    if feeder.get("recycle") is False:
        todos.append("recycle=false")
    if feeder.get("random_order"):
        todos.append("random_order=true")
    if todos:
        base += f" // TODO: {', '.join(todos)} — no Gatling equivalent; review"
    return base


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
    _METHOD_CALL = {
        "GET": "get", "POST": "post", "PUT": "put", "PATCH": "patch",
        "DELETE": "delete", "HEAD": "head", "OPTIONS": "options",
    }
    if method not in _METHOD_CALL:
        raise ValueError(f"unsupported HTTP method: {method}")

    display_name = str(step.get("transaction") or step.get("name"))
    lines = [f"          http({java_string(display_name)})"]
    method_call = _METHOD_CALL[method]
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


def kafka_action_chain(step: dict[str, Any]) -> list[str]:
    kafka = require_mapping(step.get("kafka"), "step.kafka")
    display_name = str(step.get("transaction") or step.get("name"))
    key = kafka.get("key")
    payload = java_string(gatling_el_string(str(kafka.get("payload", ""))))
    if kafka.get("request_reply"):
        reply_topic = kafka.get("reply_topic")
        if not isinstance(reply_topic, str) or not reply_topic:
            raise ValueError("kafka request_reply steps require a reply_topic")
        topic = java_string(str(kafka.get("topic", "")))
        lines = [
            f"          kafka({java_string(display_name)})",
            "            .requestReply()",
            f"            .requestTopic({topic})",
            f"            .replyTopic({java_string(reply_topic)})",
        ]
        if key is not None:
            key_str = java_string(gatling_el_string(str(key)))
            lines.append(f"            .send({key_str}, {payload})")
        else:
            lines.append(f"            .send({payload})")
        for check in kafka.get("checks") or []:
            check_map = require_mapping(check, "kafka check")
            expr = java_string(str(check_map["jsonPath"]))
            expected = java_string(str(check_map["is"]))
            lines.append(f"            .check(jsonPath({expr}).is({expected}))")
        return lines
    topic = java_string(str(kafka.get("topic", "")))
    lines = [
        f"          kafka({java_string(display_name)})",
        f"            .topic({topic})",
    ]
    if key is not None:
        key_str = java_string(gatling_el_string(str(key)))
        lines.append(f"            .send({key_str}, {payload})")
    else:
        lines.append(f"            .send({payload})")
    return lines


_JDBC_TYPE_MAP = {
    "INTEGER": "java.sql.Types.INTEGER",
    "VARCHAR": "java.sql.Types.VARCHAR",
    "DECIMAL": "java.sql.Types.DECIMAL",
    "BOOLEAN": "java.sql.Types.BOOLEAN",
    "TIMESTAMP": "java.sql.Types.TIMESTAMP",
    "BIGINT": "java.sql.Types.BIGINT",
}


def jdbc_action_chain(step: dict[str, Any]) -> list[str]:
    jdbc = require_mapping(step.get("jdbc"), "step.jdbc")
    display_name = str(step.get("transaction") or step.get("name"))
    action = str(jdbc.get("action", ""))
    query = jdbc.get("query")
    if action and isinstance(query, str) and query:
        raise ValueError("jdbc step cannot specify both query and action")

    if not action:
        return _jdbc_query_chain(jdbc, display_name)
    elif action == "insert":
        return _jdbc_insert_chain(jdbc, display_name)
    elif action == "update":
        return _jdbc_update_chain(jdbc, display_name)
    elif action == "raw_sql":
        return _jdbc_raw_sql_chain(jdbc, display_name)
    elif action == "call":
        return _jdbc_call_chain(jdbc, display_name)
    else:
        raise ValueError(f"unsupported jdbc action: {action}")


def _jdbc_query_chain(jdbc: dict[str, Any], display_name: str) -> list[str]:
    query = java_string(gatling_el_string(str(jdbc.get("query", ""))))
    lines = [
        f"          jdbc({java_string(display_name)})",
        f"            .query({query})",
    ]
    save_as = jdbc.get("saveAs")
    if isinstance(save_as, str) and save_as:
        lines.append("            .check(")
        lines.append("                simpleCheck(simpleCheckType.NonEmpty),")
        lines.append(f"                allResults().saveAs({java_string(save_as)})")
        lines.append("            )")
    return lines


def _jdbc_insert_chain(jdbc: dict[str, Any], display_name: str) -> list[str]:
    table = java_string(str(jdbc["table"]))
    columns = jdbc.get("columns")
    if not isinstance(columns, list) or not columns:
        raise ValueError("jdbc insert requires columns")
    values = jdbc.get("values")
    if not isinstance(values, dict) or not values:
        raise ValueError("jdbc insert requires values")

    cols_str = ", ".join(java_string(str(c)) for c in columns)
    lines = [
        f"          jdbc({java_string(display_name)})",
        f"            .insertInto({table}, {cols_str})",
    ]
    entries = []
    for col in columns:
        val = values.get(str(col), "")
        val_str = java_string(gatling_el_string(str(val)))
        entries.append(f"{java_string(str(col))}, {val_str}")
    map_str = "Map.of(" + ", ".join(entries) + ")"
    lines.append(f"            .values({map_str})")
    return lines


def _jdbc_update_chain(jdbc: dict[str, Any], display_name: str) -> list[str]:
    table = java_string(str(jdbc["table"]))
    set_fields = jdbc.get("set")
    if not isinstance(set_fields, dict) or not set_fields:
        raise ValueError("jdbc update requires set fields")
    where = str(jdbc.get("where", ""))

    lines = [
        f"          jdbc({java_string(display_name)})",
        f"            .update({table})",
    ]
    for field, value in set_fields.items():
        lines.append(
            f"            .set({java_string(str(field))}, {java_string(gatling_el_string(str(value)))})"
        )
    if where:
        lines.append(f"            .where({java_string(gatling_el_string(where))})")
    return lines


def _jdbc_raw_sql_chain(jdbc: dict[str, Any], display_name: str) -> list[str]:
    sql = jdbc.get("sql")
    if not isinstance(sql, str) or not sql:
        raise ValueError("jdbc raw_sql requires sql field")
    return [
        f"          jdbc({java_string(display_name)})",
        f"            .rawSql({java_string(gatling_el_string(sql))})",
    ]


def _jdbc_call_chain(jdbc: dict[str, Any], display_name: str) -> list[str]:
    procedure = jdbc.get("procedure")
    if not isinstance(procedure, str) or not procedure:
        raise ValueError("jdbc call requires procedure field")
    params = jdbc.get("params")
    out_params = jdbc.get("out_params")
    save_as = jdbc.get("saveAs")

    lines = [
        f"          jdbc({java_string(display_name)})",
        f"            .call({java_string(str(procedure))})",
    ]
    if isinstance(params, dict) and params:
        entries = []
        for key, val in params.items():
            entries.append(
                f"{java_string(str(key))}, {java_string(gatling_el_string(str(val)))}"
            )
        lines.append(f"            .params(Map.of({', '.join(entries)}))")
    if isinstance(out_params, dict) and out_params:
        entries = []
        for key, type_name in out_params.items():
            java_type = _JDBC_TYPE_MAP.get(str(type_name).upper(), "java.sql.Types.VARCHAR")
            entries.append(f"{java_string(str(key))}, {java_type}")
        lines.append(f"            .outParams(Map.of({', '.join(entries)}))")
    return lines


def render_kafka_protocol(
    kafka_config: dict[str, Any], request_reply: bool = False
) -> list[str]:
    bootstrap = env_var_expression(str(kafka_config["bootstrap_servers"]))
    if request_reply:
        timeout_seconds = kafka_config.get("timeout_seconds", 5)
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, int)
            or timeout_seconds <= 0
        ):
            raise ValueError(
                "scenario.protocols.kafka.timeout_seconds must be a positive integer"
            )
        match_by = kafka_config.get("match_by", "key")
        if match_by not in ("key", "value"):
            raise ValueError("scenario.protocols.kafka.match_by must be 'key' or 'value'")
        lines = [
            "  private final KafkaProtocolBuilder kafkaProtocol = kafka()",
            "      .producerSettings(Map.of(",
            f'          "bootstrap.servers", {bootstrap},',
            '          "acks", "1"',
            "      ))",
            "      .consumeSettings(Map.of(",
            f'          "bootstrap.servers", {bootstrap}',
            "      ))",
            f"      .timeout(Duration.ofSeconds({timeout_seconds}))",
        ]
        if match_by == "value":
            lines[-1] += ".matchByValue()"
        lines[-1] += ";"
        return lines
    extra = kafka_config.get("properties")
    has_extra = isinstance(extra, dict) and bool(extra)
    if has_extra:
        lines = [
            "  private final KafkaProtocolBuilder kafkaProtocol = kafka()",
            "      .properties(new HashMap<String, Object>() {{",
            f'          put("bootstrap.servers", {bootstrap});',
        ]
        for key in sorted(extra):
            lines.append(
                f"          put({java_string(str(key))}, {java_string(str(extra[key]))});"
            )
        lines.append("      }});")
        return lines
    return [
        "  private final KafkaProtocolBuilder kafkaProtocol = kafka()",
        f'      .properties(Map.of("bootstrap.servers", {bootstrap}));',
    ]


def render_jdbc_protocol(jdbc_config: dict[str, Any]) -> list[str]:
    url_expr = env_var_expression(str(jdbc_config["url"]))
    username_expr = env_var_expression(str(jdbc_config["username"]))
    password_expr = env_var_expression(str(jdbc_config["password"]))
    pool_size = jdbc_config.get("maximum_pool_size", 10)
    return [
        "  private final JdbcProtocolBuilder jdbcProtocol = DB()",
        f"      .url({url_expr})",
        f"      .username({username_expr})",
        f"      .password({password_expr})",
        f"      .maximumPoolSize({pool_size})",
        "      .protocolBuilder();",
    ]


def has_kafka_steps(document: dict[str, Any]) -> bool:
    return any(step.get("protocol") == "kafka" for step in iter_steps(document))


def has_kafka_request_reply(document: dict[str, Any]) -> bool:
    for step in iter_steps(document):
        if step.get("protocol") != "kafka":
            continue
        kafka = step.get("kafka")
        if isinstance(kafka, dict) and kafka.get("request_reply"):
            return True
    return False


def has_jdbc_steps(document: dict[str, Any]) -> bool:
    return any(step.get("protocol") == "jdbc" for step in iter_steps(document))


def render_chain_field(var: str, step: dict[str, Any]) -> list[str]:
    lines = [""]
    lines.extend(todo_hook_comments(step))
    lines.append(f"  private final ChainBuilder {var} =")
    segments: list[list[str]] = []
    for cls in translated_snippets(step, "before"):
        segments.append([f"exec({cls}::apply)"])
    protocol = str(step.get("protocol", "http"))
    if protocol == "kafka":
        core = ["exec(", *kafka_action_chain(step), "    )"]
    elif protocol == "jdbc":
        core = ["exec(", *jdbc_action_chain(step), "    )"]
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
    builders: list[tuple[str, dict[str, Any]]],
    assertions: list[Any],
    protocol_vars: list[str],
) -> list[str]:
    lines = ["  {", "    setUp("]
    for builder_index, (var, population) in enumerate(builders):
        load = require_mapping(population.get("load"), "population.load")
        method, injection_steps = render_injection(load)
        start_after = population.get("start_after_seconds")
        if start_after is not None:
            if isinstance(start_after, bool) or not isinstance(start_after, int) or start_after <= 0:
                raise ValueError("population start_after_seconds must be a positive integer")
            # nothingFor is an OpenInjectionStep and cannot enter injectClosed(...).
            # A closed population idles by holding zero concurrent users for the delay.
            if method == "injectClosed":
                idle = f"constantConcurrentUsers(0).during({duration(start_after)})"
            else:
                idle = f"nothingFor({duration(start_after)})"
            injection_steps = [idle] + injection_steps
        lines.append(f"      {var}.{method}(")
        for index, injection in enumerate(injection_steps):
            suffix = "," if index < len(injection_steps) - 1 else ""
            lines.append(f"        {injection}{suffix}")
        lines.append("      )," if builder_index < len(builders) - 1 else "      )")
    lines.extend([f"    ).protocols({', '.join(protocol_vars)})", "      .assertions("])
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

    protocols_config = scenario.get("protocols") if isinstance(scenario.get("protocols"), dict) else {}
    has_kafka = has_kafka_steps(document)
    has_jdbc = has_jdbc_steps(document)
    kafka_request_reply = has_kafka and has_kafka_request_reply(document)
    kafka_cfg: dict[str, Any] = {}
    jdbc_cfg: dict[str, Any] = {}
    if has_kafka:
        kafka_cfg = protocols_config.get("kafka")
        if not isinstance(kafka_cfg, dict) or not kafka_cfg.get("bootstrap_servers"):
            raise ValueError("scenario.protocols.kafka is required when kafka steps exist")
    if has_jdbc:
        jdbc_cfg = protocols_config.get("jdbc")
        if not isinstance(jdbc_cfg, dict) or not jdbc_cfg.get("url"):
            raise ValueError("scenario.protocols.jdbc is required when jdbc steps exist")

    kafka_protocol_lines: list[str] = (
        render_kafka_protocol(kafka_cfg, request_reply=kafka_request_reply)
        if has_kafka
        else []
    )
    jdbc_protocol_lines: list[str] = render_jdbc_protocol(jdbc_cfg) if has_jdbc else []

    needs_env_helper = bool(helper_lines)
    for proto_lines in (kafka_protocol_lines, jdbc_protocol_lines):
        if any("requiredEnv(" in line for line in proto_lines):
            needs_env_helper = True
    if needs_env_helper and not helper_lines:
        helper_lines = list(REQUIRED_ENV_HELPER)

    kafka_has_extra = (
        has_kafka
        and not kafka_request_reply
        and isinstance(kafka_cfg.get("properties"), dict)
        and bool(kafka_cfg.get("properties"))
    )

    regular_imports = [
        "import io.gatling.javaapi.core.ChainBuilder;",
        "import io.gatling.javaapi.core.ScenarioBuilder;",
        "import io.gatling.javaapi.core.Simulation;",
        "import io.gatling.javaapi.http.HttpProtocolBuilder;",
    ]
    if has_kafka:
        regular_imports.append(
            "import org.galaxio.gatling.kafka.javaapi.protocol.KafkaProtocolBuilder;"
        )
    if has_jdbc:
        regular_imports.append(
            "import org.galaxio.gatling.javaapi.protocol.JdbcProtocolBuilder;"
        )
    regular_imports.append("import java.time.Duration;")
    if kafka_has_extra:
        regular_imports.append("import java.util.HashMap;")
    elif has_kafka:
        regular_imports.append("import java.util.Map;")

    static_imports = [
        "import static io.gatling.javaapi.core.CoreDsl.*;",
        "import static io.gatling.javaapi.http.HttpDsl.*;",
    ]
    if has_kafka:
        static_imports.append("import static org.galaxio.gatling.kafka.javaapi.KafkaDsl.*;")
    if has_jdbc:
        static_imports.append("import static org.galaxio.gatling.javaapi.JdbcDsl.*;")

    seen_vars: dict[str, str] = {"httpProtocol": "<reserved field>"}
    if has_kafka:
        seen_vars["kafkaProtocol"] = "<reserved field>"
    if has_jdbc:
        seen_vars["jdbcProtocol"] = "<reserved field>"
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
        "// @generated",
        *regular_imports,
        "",
        *static_imports,
        "// @generated-end",
        "",
        f"public class {class_name} extends Simulation {{",
        "  // @generated",
    ]
    lines.extend(helper_lines)
    lines.extend(
        [
            "",
            f"  private final HttpProtocolBuilder httpProtocol = http.baseUrl({base_url_expression});",
        ]
    )
    lines.extend(kafka_protocol_lines)
    lines.extend(jdbc_protocol_lines)
    lines.extend(
        [
            "  // @generated-end",
            "",
            "  // @custom:protocols — add custom protocol builders here",
            "  // @custom-end",
            "",
            "  // @generated",
        ]
    )
    lines.extend(chain_lines)
    lines.extend(
        [
            "  // @generated-end",
            "",
            "  // @custom:steps — add custom chain builders here",
            "  // @custom-end",
            "",
            "  // @generated",
        ]
    )
    for var, display, population, step_vars in builders:
        lines.extend(render_population_builder(var, display, population, feeders, step_vars))

    protocol_vars = ["httpProtocol"]
    if has_kafka:
        protocol_vars.append("kafkaProtocol")
    if has_jdbc:
        protocol_vars.append("jdbcProtocol")

    lines.append("")
    lines.extend(
        render_setup(
            [(var, population) for var, _display, population, _sv in builders],
            assertions,
            protocol_vars,
        )
    )
    lines.extend(["  // @generated-end", "}"])
    return class_name, "\n".join(lines) + "\n"


TEMPLATE_POM = Path(__file__).resolve().parent / "templates" / "pom.xml"


KAFKA_PLUGIN_DEP = """    <dependency>
      <groupId>org.galaxio</groupId>
      <artifactId>gatling-kafka-plugin_2.13</artifactId>
      <version>1.0.6</version>
      <scope>test</scope>
    </dependency>
"""

JDBC_PLUGIN_DEP = """    <dependency>
      <groupId>org.galaxio</groupId>
      <artifactId>gatling-jdbc-plugin_2.13</artifactId>
      <version>1.3.1</version>
      <scope>test</scope>
    </dependency>
"""

POSTGRES_DEP = """    <dependency>
      <groupId>org.postgresql</groupId>
      <artifactId>postgresql</artifactId>
      <version>42.7.11</version>
      <scope>test</scope>
    </dependency>
"""


def inject_plugin_deps(pom_content: str, has_kafka: bool, has_jdbc: bool) -> str:
    """Inject galax-io plugin dependencies into pom.xml when needed."""
    deps_to_add = []
    if has_kafka:
        deps_to_add.append(KAFKA_PLUGIN_DEP)
    if has_jdbc:
        deps_to_add.append(JDBC_PLUGIN_DEP)
        deps_to_add.append(POSTGRES_DEP)
    if not deps_to_add:
        return pom_content
    injection = "\n".join(deps_to_add)
    return pom_content.replace("  </dependencies>", injection + "  </dependencies>")


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


def merge_custom_blocks(old_content: str, new_content: str) -> str:
    """Preserve @custom zone content from old file when regenerating."""
    old_zones: dict[str, str] = {}
    for match in CUSTOM_ZONE_RE.finditer(old_content):
        zone_name = match.group(2)
        zone_body = match.group(3)
        if zone_body.strip():
            old_zones[zone_name] = zone_body

    if not old_zones:
        return new_content

    def replace_zone(match: re.Match) -> str:
        zone_name = match.group(2)
        if zone_name in old_zones:
            return match.group(1) + old_zones[zone_name] + match.group(4)
        return match.group(0)

    return CUSTOM_ZONE_RE.sub(replace_zone, new_content)


def write_simulation_from_document(document: Any, output_dir: Path) -> tuple[Path, bool]:
    document_mapping = require_mapping(document, "document")
    class_name, content = render_simulation(document_mapping)
    scenario = require_mapping(document_mapping.get("scenario"), "scenario")
    lifecycle = str(scenario.get("lifecycle", "managed"))
    bootstrapped = bootstrap_project(output_dir)
    if bootstrapped:
        has_kafka = has_kafka_steps(document_mapping)
        has_jdbc = has_jdbc_steps(document_mapping)
        if has_kafka or has_jdbc:
            pom_path = output_dir / "pom.xml"
            pom_content = pom_path.read_text(encoding="utf-8")
            pom_content = inject_plugin_deps(pom_content, has_kafka, has_jdbc)
            pom_path.write_text(pom_content, encoding="utf-8")
    java_dir = output_dir / "src" / "test" / "java"
    java_dir.mkdir(parents=True, exist_ok=True)
    output_path = java_dir / f"{class_name}.java"
    if lifecycle == "detached" and output_path.exists():
        pass
    else:
        if output_path.exists():
            old_content = output_path.read_text(encoding="utf-8")
            content = merge_custom_blocks(old_content, content)
        output_path.write_text(content, encoding="utf-8", newline="\n")
    return output_path, bootstrapped


def write_simulation(scenario_path: Path, output_dir: Path) -> tuple[Path, bool]:
    document = load_yaml(scenario_path)
    document_mapping = require_mapping(document, "document")
    output_path, bootstrapped = write_simulation_from_document(document_mapping, output_dir)
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

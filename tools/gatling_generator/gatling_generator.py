#!/usr/bin/env python3
"""Generate Java Gatling simulations from Gatling-AI scenario YAML."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _shared.common import (  # noqa: E402
    BLOCKING,
    Finding,
    finding_to_dict,
    load_yaml,
    pascal_case,
)

VARIABLE_ONLY_RE = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")
SCENARIO_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
SCENARIO_PLACEHOLDER_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_.-]*)\}")


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


def gatling_el_string(value: str) -> str:
    return SCENARIO_PLACEHOLDER_RE.sub(r"#{\1}", value)


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
    }.get(strategy)
    if strategy_method is None:
        raise ValueError(f"unsupported feeder strategy: {strategy}")
    return f"csv({java_string(file_name)}).{strategy_method}()"


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


def render_check(check: dict[str, Any]) -> str:
    if "status" in check:
        return f"status().is({int(check['status'])})"

    extract = check.get("extract")
    if not isinstance(extract, dict):
        raise ValueError(f"unsupported check: {check}")

    extract_type = str(extract.get("type", "")).lower()
    expr = str(extract["expr"])
    save_as = str(extract["saveAs"])
    if extract_type == "css":
        return f"css({java_string(expr)}).saveAs({java_string(save_as)})"
    if extract_type in {"jsonpath", "json_path", "json-path"}:
        return f"jsonPath({java_string(expr)}).saveAs({java_string(save_as)})"
    raise ValueError(f"unsupported extract check type: {extract_type}")


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

    if "body" in request:
        body = java_string(gatling_el_string(str(request["body"])))
        lines.append(f"            .body(StringBody({body}))")

    for check in checks:
        lines.append(f"            .check({render_check(require_mapping(check, 'check'))})")
    return lines


def render_step(step: dict[str, Any], is_last: bool) -> list[str]:
    display_name = str(step.get("transaction") or step.get("name"))
    lines = [
        f"    .group({java_string(display_name)}).on(",
        "      exec(",
    ]
    lines.extend(request_chain(step))
    lines.extend(
        [
            "      )",
            f"    ){';' if is_last else ''}",
        ]
    )
    return lines


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


def render_simulation(document: dict[str, Any]) -> tuple[str, str]:
    scenario = require_mapping(document.get("scenario"), "scenario")
    scenario_id = str(scenario["id"])
    validate_scenario_id(scenario_id)
    class_name = f"{pascal_case(scenario_id)}Simulation"
    title = str(scenario["title"])
    sut = require_mapping(scenario.get("sut"), "scenario.sut")
    base_url_expression, helper_lines = load_base_url_expression(str(sut["base_url"]))

    data = scenario.get("data") if isinstance(scenario.get("data"), dict) else {}
    feeders = data.get("feeders") if isinstance(data.get("feeders"), list) else []
    steps = require_list(scenario.get("steps"), "scenario.steps")
    load = require_mapping(scenario.get("load"), "scenario.load")
    assertions = require_list(scenario.get("assertions"), "scenario.assertions")
    if not assertions:
        raise ValueError("scenario.assertions must contain at least one assertion")

    lines = [
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

    lines.extend(
        [
            "",
            f"  private final ScenarioBuilder scenario = scenario({java_string(title)})",
        ]
    )
    for feeder in feeders:
        lines.append(f"    .feed({feeder_expression(require_mapping(feeder, 'feeder'))})")

    for index, step in enumerate(steps):
        lines.extend(render_step(require_mapping(step, "step"), index == len(steps) - 1))

    lines.append("")
    lines.extend(render_load(load, assertions))
    lines.append("}")
    return class_name, "\n".join(lines) + "\n"


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


def write_simulation(scenario_path: Path, output_dir: Path) -> Path:
    document = load_yaml(scenario_path)
    document_mapping = require_mapping(document, "document")
    class_name, content = render_simulation(document_mapping)
    java_dir = output_dir / "src" / "test" / "java"
    java_dir.mkdir(parents=True, exist_ok=True)
    output_path = java_dir / f"{class_name}.java"
    output_path.write_text(content, encoding="utf-8", newline="\n")
    copy_feeder_resources(document_mapping, scenario_path, output_dir)
    return output_path


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
        print(
            json.dumps(
                {"blocking": [], "output": output_path.as_posix()}, indent=2, sort_keys=True
            )
        )
    else:
        print(output_path.as_posix())
    return 0


if __name__ == "__main__":
    sys.exit(main())

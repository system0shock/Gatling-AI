#!/usr/bin/env python3
"""Semantic lint for Gatling-AI scenario YAML files."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _shared.common import (  # noqa: E402
    BLOCKING,
    SYSTEM_RE,
    VARIABLE_RE,
    WAIVED,
    WARNING,
    Finding,
    camel_case,
    find_repo_root,
    finding_to_dict,
    load_yaml,
    rel_path,
    script_number,
    variables_in,
)

TRANSACTION_RE = re.compile(
    r"^\d{2} [a-z][a-z0-9-]*\.[a-z][a-z0-9-]* - .+$"
)
ENV_NAME_RE = re.compile(r"\b(?:dev|stage|prod)\b", re.IGNORECASE)
SECRET_VALUE_RE = re.compile(
    r"(?ix)"
    r"(?:bearer\s+[A-Za-z0-9._~+/=-]{12,})|"
    r"(?:\b(?:api[_-]?key|token|secret|password|passwd|pwd)\b\s*[:=]\s*"
    r"(?!\$\{)[^\s&;,\"']{6,})|"
    r"(?:jdbc:[^\s\"']*://[^\s\"']*:[^\s\"']+@[^\s\"']+)"
)
PROD_URL_RE = re.compile(
    r"(?i)https?://[^\s\"']*(?:\bprod\b|production)[^\s\"']*"
)
KNOWN_ENV_VARIABLES = {"BASE_URL", "env"}


def add(
    findings: list[Finding], rule: str, severity: str, path: str, message: str
) -> None:
    findings.append(Finding(rule=rule, message=message, severity=severity, path=path))


def iter_strings(value: Any, path: str = "$") -> Iterable[tuple[str, str]]:
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from iter_strings(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from iter_strings(child, f"{path}[{index}]")


def has_status_check(step: dict[str, Any]) -> bool:
    return any(isinstance(check, dict) and "status" in check for check in step.get("checks", []))


def correlation_values(step: dict[str, Any]) -> dict[str, Any]:
    request = step.get("request") if isinstance(step.get("request"), dict) else {}
    graphql = step.get("graphql") if isinstance(step.get("graphql"), dict) else {}
    return {
        "path": request.get("path"),
        "headers": request.get("headers"),
        "body": request.get("body"),
        "graphql_path": graphql.get("path"),
        "graphql_query": graphql.get("query"),
        "graphql_variables": graphql.get("variables"),
    }


def hook_pairs(step: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    hooks = step.get("hooks") if isinstance(step.get("hooks"), dict) else {}
    pairs: list[tuple[str, dict[str, Any]]] = []
    for when in ("before", "after"):
        entries = hooks.get(when) if isinstance(hooks.get(when), list) else []
        pairs.extend((when, entry) for entry in entries if isinstance(entry, dict))
    return pairs


def hook_variables(step: dict[str, Any], field: str) -> set[str]:
    names: set[str] = set()
    for _when, hook in hook_pairs(step):
        values = hook.get(field)
        if isinstance(values, list):
            names.update(value for value in values if isinstance(value, str))
    return names


def extracted_variables(step: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for check in step.get("checks", []) or []:
        if not isinstance(check, dict):
            continue
        extract = check.get("extract")
        if isinstance(extract, dict) and isinstance(extract.get("saveAs"), str):
            names.add(extract["saveAs"])
    return names


def read_csv_info(path: Path) -> tuple[set[str], int]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            return set(), 0
        rows = sum(1 for row in reader if any(cell.strip() for cell in row))
    return {column.strip() for column in header if column.strip()}, rows


def resolve_feeders(
    feeders: list[Any], base_dir: Path | None, findings: list[Finding]
) -> tuple[dict[str, set[str]], dict[str, int | None], dict[str, str]]:
    feeder_columns: dict[str, set[str]] = {}
    feeder_rows: dict[str, int | None] = {}
    feeder_strategy: dict[str, str] = {}
    root = base_dir or Path.cwd()
    for index, feeder in enumerate(feeders):
        if not isinstance(feeder, dict) or not isinstance(feeder.get("name"), str):
            continue
        name = feeder["name"]
        feeder_strategy[name] = str(feeder.get("strategy", ""))
        columns: set[str] = set()
        rows: int | None = None
        file_value = feeder.get("file")
        if isinstance(file_value, str) and file_value:
            feeder_path = Path(file_value)
            if not feeder_path.is_absolute():
                feeder_path = root / feeder_path
            if feeder_path.exists():
                columns, rows = read_csv_info(feeder_path)
            else:
                add(
                    findings,
                    "feeder-lint.missing-feeder-file",
                    WARNING,
                    f"$.scenario.data.feeders[{index}].file",
                    f"feeder file '{file_value}' is referenced but not present",
                )
        feeder_columns[name] = columns
        feeder_rows[name] = rows
    return feeder_columns, feeder_rows, feeder_strategy


POPULATION_NAME_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")


def scenario_step_paths(scenario: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Return (json_path, step) pairs for both contract forms."""
    pairs: list[tuple[str, dict[str, Any]]] = []
    populations = scenario.get("populations")
    if isinstance(populations, list):
        for population_index, population in enumerate(populations):
            if not isinstance(population, dict):
                continue
            steps = population.get("steps") if isinstance(population.get("steps"), list) else []
            for step_index, step in enumerate(steps):
                if isinstance(step, dict):
                    pairs.append(
                        (
                            f"$.scenario.populations[{population_index}].steps[{step_index}]",
                            step,
                        )
                    )
        return pairs
    steps = scenario.get("steps") if isinstance(scenario.get("steps"), list) else []
    for step_index, step in enumerate(steps):
        if isinstance(step, dict):
            pairs.append((f"$.scenario.steps[{step_index}]", step))
    return pairs


def scenario_population_step_groups(
    scenario: dict[str, Any]
) -> list[list[tuple[str, dict[str, Any]]]]:
    """Step (path, step) pairs grouped per population (single-flow = one group)."""
    populations = scenario.get("populations")
    if not isinstance(populations, list):
        return [scenario_step_paths(scenario)]
    groups: list[list[tuple[str, dict[str, Any]]]] = []
    for population_index, population in enumerate(populations):
        if not isinstance(population, dict):
            continue
        steps = population.get("steps") if isinstance(population.get("steps"), list) else []
        groups.append(
            [
                (f"$.scenario.populations[{population_index}].steps[{step_index}]", step)
                for step_index, step in enumerate(steps)
                if isinstance(step, dict)
            ]
        )
    return groups


def scenario_load_paths(scenario: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    populations = scenario.get("populations")
    if isinstance(populations, list):
        return [
            (f"$.scenario.populations[{index}].load", population["load"])
            for index, population in enumerate(populations)
            if isinstance(population, dict) and isinstance(population.get("load"), dict)
        ]
    load = scenario.get("load")
    return [("$.scenario.load", load)] if isinstance(load, dict) else []


def lint_populations(scenario: dict[str, Any], findings: list[Finding]) -> None:
    populations = scenario.get("populations")
    if not isinstance(populations, list):
        return
    seen: dict[str, int] = {}
    seen_vars: dict[str, str] = {}
    for index, population in enumerate(populations):
        if not isinstance(population, dict):
            continue
        path = f"$.scenario.populations[{index}].name"
        name = population.get("name")
        if not isinstance(name, str) or not POPULATION_NAME_RE.fullmatch(name):
            add(
                findings,
                "scenario-lint.population-name",
                BLOCKING,
                path,
                "population name must be stable kebab-case ASCII",
            )
            continue
        if name in seen:
            add(
                findings,
                "scenario-lint.unique-population-names",
                BLOCKING,
                path,
                f"population name '{name}' is duplicated; "
                f"first seen at $.scenario.populations[{seen[name]}].name",
            )
        else:
            seen[name] = index
            var = camel_case(name)
            if var in seen_vars and seen_vars[var] != name:
                add(
                    findings,
                    "scenario-lint.population-name-collision",
                    BLOCKING,
                    path,
                    f"population names '{seen_vars[var]}' and '{name}' collide on "
                    f"generated builder variable '{var}'",
                )
            else:
                seen_vars[var] = name


LOAD_INT_FIELDS = (
    "users",
    "ramp_seconds",
    "duration_seconds",
    "levels",
    "level_duration_seconds",
    "baseline_users",
    "baseline_seconds",
    "spike_rise_seconds",
    "spike_hold_seconds",
)
LOAD_RATE_FIELDS = ("users_per_second", "baseline_users_per_second")
SOAK_MIN_DURATION_SECONDS = 1800


def lint_load(load: dict[str, Any], path: str, findings: list[Finding]) -> None:
    for field in LOAD_INT_FIELDS:
        if field in load:
            value = load[field]
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                add(
                    findings,
                    "scenario-lint.positive-load-values",
                    BLOCKING,
                    f"{path}.{field}",
                    f"load.{field} must be a positive integer",
                )
    for field in LOAD_RATE_FIELDS:
        if field in load:
            value = load[field]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
                add(
                    findings,
                    "scenario-lint.positive-load-values",
                    BLOCKING,
                    f"{path}.{field}",
                    f"load.{field} must be a positive number",
                )

    profile = load.get("profile")
    model = load.get("model")
    if profile == "stress" and model == "closed":
        users = load.get("users")
        levels = load.get("levels")
        if isinstance(users, int) and isinstance(levels, int) and levels > 0 and users % levels != 0:
            add(
                findings,
                "scenario-lint.stress-step-mismatch",
                BLOCKING,
                f"{path}.users",
                f"closed stress requires users ({users}) divisible by levels ({levels})",
            )
    if profile == "spike":
        peak = load.get("users") if model == "closed" else load.get("users_per_second")
        baseline = (
            load.get("baseline_users") if model == "closed" else load.get("baseline_users_per_second")
        )
        if (
            isinstance(peak, (int, float))
            and isinstance(baseline, (int, float))
            and baseline >= peak
        ):
            add(
                findings,
                "scenario-lint.spike-baseline-not-below-peak",
                BLOCKING,
                path,
                f"spike baseline ({baseline}) must be below the peak ({peak})",
            )
    if profile == "soak":
        duration_seconds = load.get("duration_seconds")
        if isinstance(duration_seconds, int) and duration_seconds < SOAK_MIN_DURATION_SECONDS:
            add(
                findings,
                "scenario-lint.soak-too-short",
                WARNING,
                f"{path}.duration_seconds",
                f"soak shorter than {SOAK_MIN_DURATION_SECONDS}s is effectively constant; "
                "use profile: constant or extend the duration",
            )
    if profile == "stages":
        stages = load.get("stages") if isinstance(load.get("stages"), list) else []
        rate_field = "users" if model == "closed" else "users_per_second"
        for index, stage in enumerate(stages):
            if not isinstance(stage, dict):
                continue
            stage_path = f"{path}.stages[{index}]"
            target = stage.get(rate_field)
            if isinstance(target, bool) or not isinstance(target, (int, float)) or target <= 0:
                add(
                    findings,
                    "scenario-lint.stage-values",
                    BLOCKING,
                    f"{stage_path}.{rate_field}",
                    f"stage {rate_field} must be a positive number",
                )
            ramp = stage.get("ramp_seconds")
            hold = stage.get("hold_seconds")
            for field_name, value in (("ramp_seconds", ramp), ("hold_seconds", hold)):
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    add(
                        findings,
                        "scenario-lint.stage-values",
                        BLOCKING,
                        f"{stage_path}.{field_name}",
                        f"stage {field_name} must be a non-negative integer",
                    )
            if not ramp and not hold:
                # None/0 both mean "no duration"; the stage-values rule above
                # separately reports a missing/negative field.
                add(
                    findings,
                    "scenario-lint.stage-no-duration",
                    BLOCKING,
                    stage_path,
                    "stage must have ramp_seconds or hold_seconds greater than zero",
                )


def lint_scenario(document: Any, base_dir: Path | None = None) -> list[Finding]:
    findings: list[Finding] = []
    if not isinstance(document, dict) or not isinstance(document.get("scenario"), dict):
        add(findings, "scenario-lint.missing-root", BLOCKING, "$", "scenario root is required")
        return findings

    scenario = document["scenario"]
    system = scenario.get("system")
    if not isinstance(system, str) or not SYSTEM_RE.fullmatch(system):
        add(
            findings,
            "scenario-lint.system-format",
            BLOCKING,
            "$.scenario.system",
            "scenario.system is required and must match ^[A-Z][A-Z0-9]{1,9}$ (e.g. SHOP)",
        )
    number = scenario.get("number")
    if isinstance(number, bool) or not isinstance(number, int) or number < 1:
        add(
            findings,
            "scenario-lint.number-format",
            BLOCKING,
            "$.scenario.number",
            "scenario.number is required and must be a positive integer (unique within the system)",
        )
    data = scenario.get("data") if isinstance(scenario.get("data"), dict) else {}
    feeders = data.get("feeders") if isinstance(data.get("feeders"), list) else []

    for index, feeder in enumerate(feeders):
        if not isinstance(feeder, dict):
            continue
        feeder_name = feeder.get("name")
        feeder_path = f"$.scenario.data.feeders[{index}]"
        if not isinstance(feeder_name, str) or not POPULATION_NAME_RE.fullmatch(feeder_name):
            add(
                findings,
                "feeder-lint.name-format",
                BLOCKING,
                f"{feeder_path}.name",
                "feeder name must be kebab-case (a short plural noun, e.g. users, terms)",
            )
        elif feeder.get("file") != f"{feeder_name}.csv":
            add(
                findings,
                "feeder-lint.file-name",
                BLOCKING,
                f"{feeder_path}.file",
                f"feeder file must be named '{feeder_name}.csv' and live next to the scenario",
            )

    feeder_columns, feeder_rows, feeder_strategy = resolve_feeders(feeders, base_dir, findings)
    feeder_names = set(feeder_columns)

    peak_users = 0
    for _load_path, load in scenario_load_paths(scenario):
        users = load.get("users")
        if not isinstance(users, bool) and isinstance(users, int):
            peak_users = max(peak_users, users)
        stages = load.get("stages")
        if isinstance(stages, list):
            for stage in stages:
                if isinstance(stage, dict):
                    stage_users = stage.get("users")
                    if not isinstance(stage_users, bool) and isinstance(stage_users, int):
                        peak_users = max(peak_users, stage_users)
    for index, feeder in enumerate(feeders):
        if not isinstance(feeder, dict) or not isinstance(feeder.get("name"), str):
            continue
        name = feeder["name"]
        rows = feeder_rows.get(name)
        if (
            feeder_strategy.get(name) == "queue"
            and rows is not None
            and peak_users > rows
        ):
            add(
                findings,
                "feeder-lint.queue-data-volume",
                WARNING,
                f"$.scenario.data.feeders[{index}]",
                f"queue feeder '{name}' has {rows} data row(s) but the scenario ramps to "
                f"{peak_users} concurrent users; a queue feeder stops the run when data is exhausted",
            )

    lint_populations(scenario, findings)
    step_pairs = scenario_step_paths(scenario)

    seen_steps: dict[str, str] = {}
    for step_path, step in step_pairs:
        name = step.get("name")
        if isinstance(name, str):
            if name in seen_steps:
                add(
                    findings,
                    "scenario-lint.unique-step-names",
                    BLOCKING,
                    f"{step_path}.name",
                    f"step name '{name}' is duplicated; first seen at {seen_steps[name]}",
                )
            else:
                seen_steps[name] = f"{step_path}.name"

        protocol = step.get("protocol")
        request = step.get("request")
        checks = step.get("checks")
        if not checks:
            add(
                findings,
                "check-lint.missing-checks",
                BLOCKING,
                f"{step_path}.checks",
                "steps require at least one check",
            )

        for when, hook in hook_pairs(step):
            hook_path = f"{step_path}.hooks.{when}"
            root = base_dir or Path.cwd()
            snippet = hook.get("snippet")
            if hook.get("kind") == "translated" and isinstance(snippet, str):
                if not (root / snippet).is_file():
                    add(
                        findings,
                        "scenario-lint.snippet-missing",
                        BLOCKING,
                        hook_path,
                        f"translated hook snippet '{snippet}' is referenced but not present",
                    )
            ref = hook.get("ref")
            if isinstance(ref, str) and not (root / ref).is_file():
                add(
                    findings,
                    "scenario-lint.hook-ref-missing",
                    WARNING,
                    hook_path,
                    f"hook original '{ref}' is referenced but not present (traceability)",
                )

        if protocol == "graphql":
            graphql = step.get("graphql")
            if not isinstance(graphql, dict) or not str(graphql.get("query", "")).strip():
                add(
                    findings,
                    "scenario-lint.graphql-query-required",
                    BLOCKING,
                    f"{step_path}.graphql",
                    "graphql steps require a non-empty query",
                )
            if checks and not has_status_check(step):
                add(
                    findings,
                    "check-lint.mutating-status-check",
                    BLOCKING,
                    f"{step_path}.checks",
                    "graphql steps are POST requests and require an explicit status check",
                )
            continue

        if protocol != "http":
            add(
                findings,
                "scenario-lint.protocol-supported",
                BLOCKING,
                f"{step_path}.protocol",
                "only http and graphql protocols are supported in the MVP linter",
            )
            continue

        if not isinstance(request, dict):
            add(
                findings,
                "scenario-lint.http-request-required",
                BLOCKING,
                f"{step_path}.request",
                "http steps require a request block",
            )
            continue

        for field in ("method", "path"):
            if not request.get(field):
                add(
                    findings,
                    "scenario-lint.http-request-required",
                    BLOCKING,
                    f"{step_path}.request.{field}",
                    f"http request requires {field}",
                )

        method = str(request.get("method", "")).upper()
        _SUPPORTED_METHODS = {"GET", "POST"}
        if method and method not in _SUPPORTED_METHODS:
            add(
                findings,
                "scenario-lint.unsupported-method",
                BLOCKING,
                f"{step_path}.request.method",
                f"unsupported HTTP method {method!r}; supported: {sorted(_SUPPORTED_METHODS)}",
            )
        if (
            checks
            and method in {"POST", "PUT", "PATCH", "DELETE"}
            and not has_status_check(step)
        ):
            add(
                findings,
                "check-lint.mutating-status-check",
                BLOCKING,
                f"{step_path}.checks",
                f"{method} steps require an explicit status check",
            )

        body_file = request.get("body_file")
        if body_file is not None and request.get("body") is not None:
            add(
                findings,
                "scenario-lint.body-file-conflict",
                BLOCKING,
                f"{step_path}.request",
                "request must use either body or body_file, not both",
            )
        if isinstance(body_file, str) and body_file:
            candidate = Path(body_file)
            if not candidate.is_absolute():
                candidate = (base_dir or Path.cwd()) / candidate
            if not candidate.is_file():
                add(
                    findings,
                    "scenario-lint.body-file-missing",
                    BLOCKING,
                    f"{step_path}.request.body_file",
                    f"body file '{body_file}' is referenced but not present",
                )

    for load_path, load in scenario_load_paths(scenario):
        lint_load(load, load_path, findings)
    if not scenario_load_paths(scenario):
        add(
            findings,
            "scenario-lint.load-required",
            BLOCKING,
            "$.scenario.load",
            "scenario requires a load block (or per-population load blocks)",
        )

    population_groups = scenario_population_step_groups(scenario)
    all_extracted: set[str] = set()
    for group in population_groups:
        for _path, step in group:
            all_extracted.update(extracted_variables(step) | hook_variables(step, "writes"))

    for group in population_groups:
        local_extracted: set[str] = set()
        for _path, step in group:
            local_extracted.update(extracted_variables(step) | hook_variables(step, "writes"))

        for step_path, step in group:
            request_values = correlation_values(step)
            for variable in sorted(variables_in(request_values)):
                if "." in variable:
                    feeder_name, column = variable.split(".", 1)
                    if feeder_name not in feeder_names:
                        add(
                            findings,
                            "feeder-lint.missing-feeder",
                            BLOCKING,
                            step_path,
                            f"variable '${{{variable}}}' references missing feeder '{feeder_name}'",
                        )
                    elif column not in feeder_columns[feeder_name]:
                        add(
                            findings,
                            "feeder-lint.missing-feeder",
                            BLOCKING,
                            step_path,
                            f"variable '${{{variable}}}' references missing feeder column '{column}'",
                        )
                elif variable in local_extracted or variable in KNOWN_ENV_VARIABLES:
                    continue
                elif variable in all_extracted:
                    add(
                        findings,
                        "correlation-lint.cross-population-variable",
                        BLOCKING,
                        step_path,
                        f"variable '${{{variable}}}' is extracted in another population; "
                        "Gatling session variables do not cross populations",
                    )
                elif not any(variable in columns for columns in feeder_columns.values()):
                    add(
                        findings,
                        "feeder-lint.missing-feeder",
                        BLOCKING,
                        step_path,
                        f"variable '${{{variable}}}' is not extracted, environment-backed, "
                        "or backed by a feeder column",
                    )

            for variable in sorted(hook_variables(step, "reads")):
                if variable in local_extracted or variable in KNOWN_ENV_VARIABLES:
                    continue
                if any(variable in columns for columns in feeder_columns.values()):
                    continue
                if variable in all_extracted:
                    add(
                        findings,
                        "correlation-lint.cross-population-variable",
                        BLOCKING,
                        step_path,
                        f"hook reads '{variable}' which is extracted in another population; "
                        "Gatling session variables do not cross populations",
                    )
                    continue
                add(
                    findings,
                    "correlation-lint.hook-read-undefined",
                    BLOCKING,
                    step_path,
                    f"hook reads '{variable}' which is not extracted, environment-backed, "
                    "or backed by a feeder column",
                )

    return findings


def lint_transactions(document: Any) -> list[Finding]:
    findings: list[Finding] = []
    scenario = document.get("scenario", {}) if isinstance(document, dict) else {}
    pairs = scenario_step_paths(scenario) if isinstance(scenario, dict) else []
    seen: dict[str, str] = {}
    seen_numbers: dict[str, str] = {}
    for step_path, step in pairs:
        path = f"{step_path}.transaction"
        transaction = step.get("transaction")
        if not isinstance(transaction, str):
            add(
                findings,
                "transaction-lint.required",
                BLOCKING,
                path,
                "transaction display name is required",
            )
            continue
        if transaction in seen:
            add(
                findings,
                "transaction-lint.unique",
                BLOCKING,
                path,
                f"transaction '{transaction}' is duplicated; first seen at {seen[transaction]}",
            )
        else:
            seen[transaction] = path
        if not TRANSACTION_RE.match(transaction):
            add(
                findings,
                "transaction-lint.format",
                BLOCKING,
                path,
                "transaction must use '<NN> <domain>.<action> - <human title>'",
            )
        number_prefix = transaction[:2]
        if number_prefix.isdigit():
            if number_prefix in seen_numbers:
                add(
                    findings,
                    "transaction-lint.duplicate-number",
                    BLOCKING,
                    path,
                    f"transaction number '{number_prefix}' is reused (first seen at "
                    f"{seen_numbers[number_prefix]}); numbering is through the whole simulation",
                )
            else:
                seen_numbers[number_prefix] = path
        if len(transaction) > 80:
            add(
                findings,
                "transaction-lint.max-length",
                BLOCKING,
                path,
                "transaction display name must be 80 characters or fewer",
            )
        scrubbed = VARIABLE_RE.sub("${var}", transaction)
        if SECRET_VALUE_RE.search(scrubbed):
            add(
                findings,
                "transaction-lint.no-secrets",
                BLOCKING,
                path,
                "transaction display name contains a secret-looking value",
            )
        if ENV_NAME_RE.search(transaction):
            add(
                findings,
                "transaction-lint.no-env-names",
                BLOCKING,
                path,
                "transaction display name must not include dev, stage, or prod",
            )
    return findings


def lint_secrets(document: Any) -> list[Finding]:
    findings: list[Finding] = []
    for path, value in iter_strings(document):
        scrubbed = VARIABLE_RE.sub("${var}", value)
        if SECRET_VALUE_RE.search(scrubbed):
            add(
                findings,
                "secret-scan.secret-looking-value",
                BLOCKING,
                path,
                "secret-looking token, password, bearer token, or JDBC credential found",
            )
        if PROD_URL_RE.search(scrubbed):
            add(
                findings,
                "secret-scan.hardcoded-production-url",
                BLOCKING,
                path,
                "hardcoded production URL found",
            )
    return findings


def lint_layout(document: Any, scenario_path: Path) -> list[Finding]:
    """Layout rules for canonical scenario.yaml files: folder names and number uniqueness."""
    findings: list[Finding] = []
    if scenario_path.name != "scenario.yaml":
        return findings
    scenario = document.get("scenario", {}) if isinstance(document, dict) else {}
    scenario_id = scenario.get("id")
    system = scenario.get("system")
    number = scenario.get("number")
    if (
        not isinstance(scenario_id, str)
        or not isinstance(system, str)
        or isinstance(number, bool)
        or not isinstance(number, int)
        or number < 1
    ):
        return findings  # field-level problems are reported by lint_scenario
    resolved_self = scenario_path.resolve()
    folder = resolved_self.parent
    expected_folder = f"{scenario_id}-{script_number(number)}"
    if folder.name != expected_folder:
        add(
            findings,
            "layout-lint.folder-name",
            BLOCKING,
            "$.scenario",
            f"scenario folder must be named '{expected_folder}', found '{folder.name}'",
        )
    system_dir = folder.parent
    if system_dir.name != system:
        add(
            findings,
            "layout-lint.system-folder",
            BLOCKING,
            "$.scenario.system",
            f"scenario must live under a '{system}' system folder, found '{system_dir.name}'",
        )
        return findings
    scenarios_root = system_dir.parent
    for other in sorted(scenarios_root.glob("*/*/scenario.yaml")):
        if other.resolve() == resolved_self:
            continue
        try:
            other_document = load_yaml(other)
        except Exception:
            continue  # unreadable siblings are their own lint problem
        other_scenario = (
            other_document.get("scenario") if isinstance(other_document, dict) else None
        )
        if not isinstance(other_scenario, dict):
            continue
        if other_scenario.get("system") == system and other_scenario.get("number") == number:
            add(
                findings,
                "layout-lint.duplicate-number",
                BLOCKING,
                "$.scenario.number",
                f"script number {number} in system '{system}' is already used by "
                f"{other.as_posix()}",
            )
    return findings


def lint_document(document: Any, base_dir: Path | None = None) -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(lint_scenario(document, base_dir))
    findings.extend(lint_transactions(document))
    findings.extend(lint_secrets(document))
    return findings


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
    document: Any,
    base_dir: Path | None = None,
    today: date | None = None,
    scenario_path: Path | None = None,
) -> LintResult:
    today = today or datetime.now(UTC).date()
    findings = lint_document(document, base_dir)
    if scenario_path is not None:
        findings.extend(lint_layout(document, scenario_path))
    raw_waivers = document.get("lint_waivers") if isinstance(document, dict) else None
    waivers = (
        [waiver for waiver in raw_waivers if isinstance(waiver, dict)]
        if isinstance(raw_waivers, list)
        else []
    )

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
                        message=(
                            f"waiver for '{rule}' is expired or has an invalid date; "
                            "finding stays blocking"
                        ),
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
                Finding(
                    rule=finding.rule,
                    severity=WAIVED,
                    path=finding.path,
                    message=finding.message,
                )
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


def render_text(path: str, findings: list[Finding]) -> str:
    if not findings:
        return f"{path}: passed"
    lines = [f"{path}: {len(findings)} finding(s)"]
    for finding in findings:
        lines.append(
            f"{finding.severity.upper()} {finding.rule} {finding.path}: {finding.message}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lint Gatling-AI scenario YAML")
    parser.add_argument("scenario", type=Path, help="scenario YAML file to lint")
    parser.add_argument(
        "--format",
        choices=("json", "text"),
        default="json",
        help="output format (default: json)",
    )
    args = parser.parse_args(argv)
    repo_root = find_repo_root(args.scenario)
    artifact_path = rel_path(args.scenario, repo_root)

    try:
        document = load_yaml(args.scenario)
        result = lint_with_waivers(document, args.scenario.parent, scenario_path=args.scenario)
    except Exception as exc:
        failure = Finding(
            rule="scenario-lint.load-failed",
            severity=BLOCKING,
            path="$",
            message=str(exc),
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
        print(
            render_text(
                artifact_path, [*result.blocking, *result.warnings, *result.waived]
            )
        )

    return 1 if result.blocking else 0


if __name__ == "__main__":
    sys.exit(main())

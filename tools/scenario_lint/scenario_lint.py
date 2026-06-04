#!/usr/bin/env python3
"""Semantic lint for Gatling-AI scenario YAML files."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only on hosts without PyYAML.
    yaml = None


BLOCKING = "blocking"
WARNING = "warning"

VARIABLE_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_.-]*)\}")
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


@dataclass(frozen=True)
class Finding:
    rule: str
    severity: str
    path: str
    message: str


def add(
    findings: list[Finding], rule: str, severity: str, path: str, message: str
) -> None:
    findings.append(Finding(rule=rule, severity=severity, path=path, message=message))


def load_yaml(path: Path) -> Any:
    if yaml is None:
        raise RuntimeError(
            "PyYAML is not installed. Install PyYAML or run in the Phase 0 verification environment."
        )
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def variables_in(value: Any) -> set[str]:
    if isinstance(value, str):
        return set(VARIABLE_RE.findall(value))
    if isinstance(value, dict):
        found: set[str] = set()
        for child in value.values():
            found.update(variables_in(child))
        return found
    if isinstance(value, list):
        found = set()
        for child in value:
            found.update(variables_in(child))
        return found
    return set()


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


def extracted_variables(step: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for check in step.get("checks", []) or []:
        if not isinstance(check, dict):
            continue
        extract = check.get("extract")
        if isinstance(extract, dict) and isinstance(extract.get("saveAs"), str):
            names.add(extract["saveAs"])
    return names


def is_env_variable(name: str) -> bool:
    return re.fullmatch(r"[A-Z][A-Z0-9_]*", name) is not None


def lint_scenario(document: Any) -> list[Finding]:
    findings: list[Finding] = []
    if not isinstance(document, dict) or not isinstance(document.get("scenario"), dict):
        add(findings, "scenario-lint.missing-root", BLOCKING, "$", "scenario root is required")
        return findings

    scenario = document["scenario"]
    steps = scenario.get("steps") if isinstance(scenario.get("steps"), list) else []
    load = scenario.get("load") if isinstance(scenario.get("load"), dict) else {}
    data = scenario.get("data") if isinstance(scenario.get("data"), dict) else {}
    feeders = data.get("feeders") if isinstance(data.get("feeders"), list) else []
    feeder_names = {
        feeder.get("name")
        for feeder in feeders
        if isinstance(feeder, dict) and isinstance(feeder.get("name"), str)
    }

    seen_steps: dict[str, int] = {}
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        step_path = f"$.scenario.steps[{index}]"
        name = step.get("name")
        if isinstance(name, str):
            if name in seen_steps:
                add(
                    findings,
                    "scenario-lint.unique-step-names",
                    BLOCKING,
                    f"{step_path}.name",
                    f"step name '{name}' is duplicated; first seen at $.scenario.steps[{seen_steps[name]}].name",
                )
            else:
                seen_steps[name] = index

        protocol = step.get("protocol")
        request = step.get("request")
        if protocol != "http":
            add(
                findings,
                "scenario-lint.protocol-supported",
                BLOCKING,
                f"{step_path}.protocol",
                "only http protocol is supported in the MVP linter",
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

        if not step.get("checks"):
            add(
                findings,
                "check-lint.missing-checks",
                BLOCKING,
                f"{step_path}.checks",
                "http steps require at least one check",
            )

        method = str(request.get("method", "")).upper()
        if method in {"POST", "PUT", "PATCH", "DELETE"} and not has_status_check(step):
            add(
                findings,
                "check-lint.mutating-status-check",
                BLOCKING,
                f"{step_path}.checks",
                f"{method} steps require an explicit status check",
            )

    for field in ("users", "ramp_seconds", "duration_seconds"):
        value = load.get(field)
        if not isinstance(value, int) or value <= 0:
            add(
                findings,
                "scenario-lint.positive-load-values",
                BLOCKING,
                f"$.scenario.load.{field}",
                f"load.{field} must be a positive integer",
            )

    known_session_vars: set[str] = set()
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        request = step.get("request")
        if isinstance(request, dict):
            request_values = {
                "path": request.get("path"),
                "headers": request.get("headers"),
                "body": request.get("body"),
            }
            for variable in sorted(variables_in(request_values)):
                if "." in variable:
                    feeder_name = variable.split(".", 1)[0]
                    if feeder_name not in feeder_names:
                        add(
                            findings,
                            "feeder-lint.missing-feeder",
                            BLOCKING,
                            f"$.scenario.steps[{index}].request",
                            f"variable '${{{variable}}}' references missing feeder '{feeder_name}'",
                        )
                elif (
                    variable not in known_session_vars
                    and not is_env_variable(variable)
                    and not feeder_names
                ):
                    add(
                        findings,
                        "feeder-lint.missing-feeder",
                        BLOCKING,
                        f"$.scenario.steps[{index}].request",
                        f"variable '${{{variable}}}' is not extracted, env-style, or backed by a configured feeder",
                    )
        known_session_vars.update(extracted_variables(step))

    return findings


def lint_transactions(document: Any) -> list[Finding]:
    findings: list[Finding] = []
    scenario = document.get("scenario", {}) if isinstance(document, dict) else {}
    steps = scenario.get("steps", []) if isinstance(scenario, dict) else []
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        path = f"$.scenario.steps[{index}].transaction"
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
        if not TRANSACTION_RE.match(transaction):
            add(
                findings,
                "transaction-lint.format",
                BLOCKING,
                path,
                "transaction must use '<NN> <domain>.<action> - <human title>'",
            )
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


def lint_document(document: Any) -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(lint_scenario(document))
    findings.extend(lint_transactions(document))
    findings.extend(lint_secrets(document))
    return findings


def render_text(path: Path, findings: list[Finding]) -> str:
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

    try:
        document = load_yaml(args.scenario)
        findings = lint_document(document)
    except Exception as exc:
        findings = [
            Finding(
                rule="scenario-lint.load-failed",
                severity=BLOCKING,
                path="$",
                message=str(exc),
            )
        ]

    if args.format == "json":
        print(
            json.dumps(
                {
                    "artifact": str(args.scenario),
                    "blocking": [asdict(f) for f in findings if f.severity == BLOCKING],
                    "warnings": [asdict(f) for f in findings if f.severity == WARNING],
                    "findings": [asdict(f) for f in findings],
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(render_text(args.scenario, findings))

    return 1 if any(f.severity == BLOCKING for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())

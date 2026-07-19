#!/usr/bin/env python3
"""Run deterministic, evidence-bound quality checks for an MNT candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from methodology_evidence.reconcile import Finding, REQUIRED_MNT_SECTIONS


REPORT_VERSION = 1
NO_DATA = "Нет подтвержденных данных."
REQUIRED_HEADINGS = tuple(heading for heading, _ in REQUIRED_MNT_SECTIONS)
SECRET_PATTERNS = (
    re.compile(r"(?i)authorization:\s*bearer\s+\S+"),
    re.compile(r"(?i)(password|client_secret|api[_-]?key)\s*[:=]\s*\S+"),
)
CHECKS = (
    "required-section",
    "placeholder-scan",
    "source-map-schema",
    "sla-source",
    "endpoint-source",
    "integration-source",
    "blocking-conflicts",
    "module-coverage",
    "secret-detection",
    "artifact-boundary",
    "patch-scope",
    "snapshot-freshness",
)


@dataclass(frozen=True)
class GateReport:
    """The stable result of all quality checks."""

    status: str
    findings: tuple[Finding, ...]
    checks: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class GateContext:
    """All immutable candidate inputs consumed by pure checks."""

    candidate_path: Path
    candidate_text: str
    resolved_evidence: dict[str, Any]
    coverage: dict[str, Any]
    source_map: dict[str, Any]
    patch_text: str
    base_path: Path
    base_text: str


def finding(rule: str, message: str, severity: str = "blocking") -> tuple[Finding, ...]:
    """Create a safe finding without adding candidate content to its message."""
    return (Finding(rule=rule, message=message, severity=severity),)


def markdown_sections(text: str) -> dict[str, str]:
    """Return second-level Markdown sections and their trimmed bodies."""
    matches = list(re.finditer(r"(?m)^##\s+(.+?)\s*$", text))
    return {
        match.group(1): text[
            match.end() : matches[index + 1].start() if index + 1 < len(matches) else len(text)
        ].strip()
        for index, match in enumerate(matches)
    }


def check_required_sections(ctx: GateContext) -> tuple[Finding, ...]:
    actual = markdown_sections(ctx.candidate_text)
    coverage_sections = ctx.coverage.get("sections")
    if not isinstance(coverage_sections, dict):
        return finding("required-section", "coverage contract must contain sections")
    missing = sorted(set(REQUIRED_HEADINGS) - set(actual))
    return finding("required-section", f"missing sections: {', '.join(missing)}") if missing else ()


def check_placeholders(ctx: GateContext) -> tuple[Finding, ...]:
    forbidden = re.compile(r"(?i)\b(TBD|TODO|FIXME)\b|\?\?\?|\|\s*\|")
    return finding("placeholder-scan", "candidate contains placeholder content") if forbidden.search(ctx.candidate_text) else ()


def check_source_map_schema(ctx: GateContext) -> tuple[Finding, ...]:
    valid = ctx.source_map.get("version") == 1 and isinstance(ctx.source_map.get("sections"), dict)
    return () if valid else finding("source-map-schema", "source map must contain version 1 and sections")


def check_section_sources(ctx: GateContext, heading_fragment: str, rule: str) -> tuple[Finding, ...]:
    sections = markdown_sections(ctx.candidate_text)
    heading = next((name for name in sections if heading_fragment.casefold() in name.casefold()), None)
    if heading is None:
        return ()
    body = sections[heading]
    has_claim = bool(body and body != NO_DATA)
    mapped = ctx.source_map.get("sections", {}).get(heading, [])
    return finding(rule, f"{heading} contains claims without evidence IDs") if has_claim and not mapped else ()


def check_sla_sources(ctx: GateContext) -> tuple[Finding, ...]:
    return check_section_sources(ctx, "SLA", "sla-source")


def check_endpoint_sources(ctx: GateContext) -> tuple[Finding, ...]:
    return check_section_sources(ctx, "интерфейсов", "endpoint-source")


def check_integration_sources(ctx: GateContext) -> tuple[Finding, ...]:
    return check_section_sources(ctx, "интеграций", "integration-source")


def check_blocking_conflicts(ctx: GateContext) -> tuple[Finding, ...]:
    gaps = ctx.resolved_evidence.get("blocking_gaps", [])
    return finding("blocking-conflicts", f"{len(gaps)} blocking evidence gaps") if gaps else ()


def check_module_coverage(ctx: GateContext) -> tuple[Finding, ...]:
    sections = ctx.coverage.get("sections", {})
    if not isinstance(sections, dict):
        return finding("module-coverage", "coverage contract must contain sections")
    incomplete = sorted(name for name, status in sections.items() if status in {"missing", "partial"})
    return finding("module-coverage", f"incomplete sections: {', '.join(incomplete)}") if incomplete else ()


def check_secrets(ctx: GateContext) -> tuple[Finding, ...]:
    return tuple(
        Finding("secret-detection", f"secret-like value at line {line_number}", "blocking")
        for line_number, line in enumerate(ctx.candidate_text.splitlines(), start=1)
        if any(pattern.search(line) for pattern in SECRET_PATTERNS)
    )


def check_artifact_boundaries(ctx: GateContext) -> tuple[Finding, ...]:
    concrete_data = re.search(
        r"(?im)^\s*(users\.csv:|run[_ -]?id\s*[:=]|protocol[_ -]?id\s*[:=])",
        ctx.candidate_text,
    )
    return finding(
        "artifact-boundary", "scenario data or run protocol content belongs in a separate artifact"
    ) if concrete_data else ()


def check_patch_scope(ctx: GateContext) -> tuple[Finding, ...]:
    headers = [line[4:] for line in ctx.patch_text.splitlines() if line.startswith(("--- ", "+++ "))]
    allowed = {str(ctx.base_path), str(ctx.candidate_path), "/dev/null"}
    invalid = [header for header in headers if header.split("\t", 1)[0] not in allowed]
    return finding("patch-scope", "patch contains a path outside base/candidate") if invalid else ()


def check_snapshot_freshness(ctx: GateContext) -> tuple[Finding, ...]:
    snapshot = ctx.source_map.get("workspace_snapshot", {})
    return finding("snapshot-freshness", "workspace snapshot is stale") if snapshot.get("stale") is True else ()


CHECK_FUNCTIONS: dict[str, Callable[[GateContext], tuple[Finding, ...]]] = {
    "required-section": check_required_sections,
    "placeholder-scan": check_placeholders,
    "source-map-schema": check_source_map_schema,
    "sla-source": check_sla_sources,
    "endpoint-source": check_endpoint_sources,
    "integration-source": check_integration_sources,
    "blocking-conflicts": check_blocking_conflicts,
    "module-coverage": check_module_coverage,
    "secret-detection": check_secrets,
    "artifact-boundary": check_artifact_boundaries,
    "patch-scope": check_patch_scope,
    "snapshot-freshness": check_snapshot_freshness,
}


def _load_object(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def load_gate_context(
    candidate: Path, resolved_evidence: Path, coverage: Path, source_map: Path, patch: Path, base: Path
) -> GateContext:
    """Load UTF-8 artifacts once before evaluating checks."""
    return GateContext(
        candidate_path=candidate,
        candidate_text=candidate.read_text(encoding="utf-8"),
        resolved_evidence=_load_object(resolved_evidence, "resolved evidence"),
        coverage=_load_object(coverage, "coverage"),
        source_map=_load_object(source_map, "source map"),
        patch_text=patch.read_text(encoding="utf-8"),
        base_path=base,
        base_text=base.read_text(encoding="utf-8") if base.exists() else "",
    )


def run_gate(
    *, candidate: Path, resolved_evidence: Path, coverage: Path, source_map: Path, patch: Path, base: Path
) -> GateReport:
    """Run the fixed ordered set of deterministic checks."""
    context = load_gate_context(candidate, resolved_evidence, coverage, source_map, patch, base)
    findings: list[Finding] = []
    checks: list[dict[str, Any]] = []
    for check_id in CHECKS:
        check_findings = CHECK_FUNCTIONS[check_id](context)
        findings.extend(check_findings)
        checks.append({"id": check_id, "status": "passed" if not check_findings else "failed", "finding_count": len(check_findings)})
    status = "blocked" if any(item.severity == "blocking" for item in findings) else (
        "passed_with_warnings" if findings else "passed"
    )
    return GateReport(status, tuple(findings), tuple(checks))


def exit_code_for(report: GateReport) -> int:
    """Map a report status to the public CLI contract."""
    return {"passed": 0, "passed_with_warnings": 1, "blocked": 2}[report.status]


def _report_finding(item: Finding) -> dict[str, Any]:
    """Serialize only stable, already-redacted finding fields."""
    return asdict(item)


def _generated_at() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def render_markdown(report: GateReport, payload: dict[str, Any]) -> str:
    """Render a redacted, compact human report."""
    counts = {severity: sum(item.severity == severity for item in report.findings) for severity in ("blocking", "warning")}
    lines = [
        "# Methodology Quality Report",
        "",
        f"- Status: `{report.status}`",
        f"- Candidate: `{payload['candidate']}`",
        f"- Checks: {len(report.checks)}",
        f"- Blocking findings: {counts['blocking']}",
        f"- Warnings: {counts['warning']}",
        "",
        "## Findings",
    ]
    if report.findings:
        lines.extend(f"- [{item.severity}] `{item.rule}`: {item.message}" for item in report.findings)
    else:
        lines.append("- None")
    return "\n".join(lines) + "\n"


def write_reports(report: GateReport, candidate: Path, out_dir: Path) -> dict[str, Path]:
    """Write the JSON and Markdown reports beside the candidate run artifacts."""
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": REPORT_VERSION,
        "status": report.status,
        "candidate": str(candidate),
        "candidate_sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
        "checks": list(report.checks),
        "findings": [_report_finding(item) for item in report.findings],
        "generated_at": _generated_at(),
    }
    outputs = {
        "json": out_dir / "methodology-quality-report.json",
        "markdown": out_dir / "methodology-quality-report.md",
    }
    outputs["json"].write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    outputs["markdown"].write_text(render_markdown(report, payload), encoding="utf-8")
    return outputs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the deterministic methodology quality gate.")
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--resolved-evidence", type=Path, required=True)
    parser.add_argument("--coverage", type=Path, required=True)
    parser.add_argument("--source-map", type=Path, required=True)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--patch", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Write reports and return 0/1/2; a blocked result stops approval flow."""
    args = build_parser().parse_args(argv)
    try:
        report = run_gate(
            candidate=args.candidate,
            resolved_evidence=args.resolved_evidence,
            coverage=args.coverage,
            source_map=args.source_map,
            patch=args.patch,
            base=args.base,
        )
        outputs = write_reports(report, args.candidate, args.out_dir)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps({"status": report.status, "json_report": str(outputs["json"]), "md_report": str(outputs["markdown"])}, ensure_ascii=False, sort_keys=True))
    return exit_code_for(report)


if __name__ == "__main__":
    raise SystemExit(main())

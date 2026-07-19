#!/usr/bin/env python3
"""Run deterministic, evidence-bound quality checks for an MNT candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from methodology_evidence.reconcile import Finding, NO_DATA, REQUIRED_MNT_SECTIONS


REPORT_VERSION = 1
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
    workspace_snapshot: dict[str, Any]
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


def _valid_resolved_evidence(ctx: GateContext) -> bool:
    document = ctx.resolved_evidence
    if set(document) != {"version", "entities", "blocking_gaps"} or document.get("version") != 1 or isinstance(document.get("version"), bool) or not isinstance(document.get("entities"), list) or not isinstance(document.get("blocking_gaps"), list):
        return False
    for entity in document["entities"]:
        if not isinstance(entity, dict) or not {"entity_type", "entity_id", "status", "fields"} <= set(entity) or not isinstance(entity["entity_type"], str) or not entity["entity_type"] or not isinstance(entity["entity_id"], str) or not entity["entity_id"] or entity["status"] not in {"confirmed", "repo_only", "docs_only", "conflict", "inferred", "unknown", "not_applicable"} or not isinstance(entity["fields"], dict):
            return False
        for field, records in entity["fields"].items():
            if not isinstance(field, str) or not field or not isinstance(records, list) or not records:
                return False
            for record in records:
                source = record.get("source") if isinstance(record, dict) else None
                if not isinstance(record, dict) or record.get("entity_type") != entity["entity_type"] or record.get("entity_id") != entity["entity_id"] or record.get("field") != field or not isinstance(record.get("statement"), str) or not record["statement"] or not isinstance(source, dict) or not isinstance(source.get("source_type"), str) or not source["source_type"] or not isinstance(source.get("ref"), str) or not source["ref"] or not isinstance(record.get("confidence"), str) or not isinstance(record.get("freshness"), str):
                    return False
    return True
def _valid_evidence_ids(resolved_evidence: dict[str, Any]) -> set[str]:
    entities = resolved_evidence.get("entities")
    if not isinstance(entities, list):
        return set()
    result: set[str] = set()
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        entity_type = entity.get("entity_type")
        entity_id = entity.get("entity_id")
        fields = entity.get("fields")
        if isinstance(entity_type, str) and entity_type and isinstance(entity_id, str) and entity_id and isinstance(fields, dict):
            result.update(f"{entity_type}.{entity_id}.{field}" for field in fields if isinstance(field, str) and field)
    return result


def _is_id_list(value: Any, known_ids: set[str]) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and item and item in known_ids for item in value)
        and len(value) == len(set(value))
    )


def check_source_map_schema(ctx: GateContext) -> tuple[Finding, ...]:
    source_map = ctx.source_map
    known_ids = _valid_evidence_ids(ctx.resolved_evidence)
    if not _valid_resolved_evidence(ctx):
        return finding("source-map-schema", "resolved evidence envelope is malformed")
    sections = source_map.get("sections")
    snapshot = source_map.get("workspace_snapshot")
    valid_snapshot = (
        isinstance(snapshot, dict)
        and set(snapshot) == {"version", "snapshot_id", "fresh"}
        and snapshot.get("version") == 1
        and not isinstance(snapshot.get("version"), bool)
        and isinstance(snapshot.get("snapshot_id"), str)
        and re.fullmatch(r"[0-9a-f]{64}", snapshot["snapshot_id"]) is not None
        and isinstance(snapshot.get("fresh"), bool)
    )
    valid = (
        set(source_map) == {"version", "sections", "workspace_snapshot"}
        and source_map.get("version") == 1
        and not isinstance(source_map.get("version"), bool)
        and isinstance(sections, dict)
        and set(sections) == set(REQUIRED_HEADINGS)
        and bool(known_ids)
        and all(_is_id_list(ids, known_ids) for ids in sections.values())
        and valid_snapshot
    )
    return () if valid else finding("source-map-schema", "source map must map every canonical section to unique resolved evidence IDs and a snapshot identity")
def check_section_sources(ctx: GateContext, heading_fragment: str, rule: str) -> tuple[Finding, ...]:
    sections = markdown_sections(ctx.candidate_text)
    heading = next((name for name in sections if heading_fragment.casefold() in name.casefold()), None)
    if heading is None:
        return ()
    body = sections[heading]
    has_claim = bool(body and body != NO_DATA)
    section_map = ctx.source_map.get("sections", {})
    mapped = section_map.get(heading, []) if isinstance(section_map, dict) else []
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
    coverage = ctx.coverage
    sections = coverage.get("sections")
    evidence_ids = coverage.get("evidence_ids")
    valid = (
        set(coverage) == {"version", "sections", "evidence_ids"}
        and coverage.get("version") == 1
        and not isinstance(coverage.get("version"), bool)
        and isinstance(sections, dict)
        and isinstance(evidence_ids, dict)
        and set(sections) == set(REQUIRED_HEADINGS)
        and set(evidence_ids) == set(REQUIRED_HEADINGS)
        and all(status in {"covered", "partial", "missing"} for status in sections.values())
        and all(isinstance(ids, list) and all(isinstance(item, str) and item for item in ids) and len(ids) == len(set(ids)) for ids in evidence_ids.values())
    )
    if not valid:
        return finding("module-coverage", "coverage must be version 1 with exactly the canonical sections and evidence IDs")
    incomplete = sorted(name for name, status in sections.items() if status in {"missing", "partial"})
    return finding("module-coverage", f"incomplete sections: {', '.join(incomplete)}") if incomplete else ()
def check_secrets(ctx: GateContext) -> tuple[Finding, ...]:
    return tuple(
        Finding("secret-detection", f"secret-like value at line {line_number}", "blocking")
        for line_number, line in enumerate(ctx.candidate_text.splitlines(), start=1)
        if any(pattern.search(line) for pattern in SECRET_PATTERNS)
    )


def check_artifact_boundaries(ctx: GateContext) -> tuple[Finding, ...]:
    text = ctx.candidate_text
    patterns = (
        r"(?im)^\s*(users|accounts|customers|orders|products)[\w-]*\.(csv|json|ya?ml)\s*:\s*.+$",
        r"(?im)^\s*\|[^\n]*\b[\w.-]+\.(csv|json|ya?ml)\b[^\n]*\b(login|password|email)\b[^\n]*\|",
        r"(?is)```(?:ya?ml|json)?\s*\n(?:(?!```).)*(scenario(?:_id)?|users\.csv|run_id|protocol_id)\s*[:=]",
        r"(?im)\b(?:dataset|data file)\s*:\s*[\w.-]+\.(csv|json|ya?ml)\s*\([^)]*\b(login|password|email)\b",
        r"(?is)\brun[- ]?id\s*[:#]?\s*\S+.*\b(result|status)\s*[:=]",
        r"(?im)^\s*(protocol|scenario)[_ -]?id\s*[:=]\s*\S+",
    )
    return finding("artifact-boundary", "concrete scenarios, datasets, run protocols, and results belong in separate artifacts") if any(re.search(pattern, text) for pattern in patterns) else ()


def _diff_path(header: str) -> str:
    return header.split("\t", 1)[0]


def _unsafe_diff_path(path: str) -> bool:
    return path != "/dev/null" and (not path or ".." in Path(path).parts)
def _apply_unified_diff(base_text: str, patch_text: str, expected_base: str, expected_candidate: str) -> str | None:
    lines = patch_text.splitlines(keepends=True)
    if not lines:
        return base_text
    clean = [line.rstrip("\r\n") for line in lines]
    if len(clean) < 3 or not clean[0].startswith("--- ") or not clean[1].startswith("+++ "):
        return None
    if _diff_path(clean[0][4:]) != expected_base or _diff_path(clean[1][4:]) != expected_candidate or _unsafe_diff_path(_diff_path(clean[0][4:])) or _unsafe_diff_path(_diff_path(clean[1][4:])):
        return None
    header = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: .*)?$")
    hunks: list[tuple[int, int, int, int, list[tuple[str, str]]]] = []
    index = 2
    while index < len(lines):
        match = header.fullmatch(clean[index])
        if match is None:
            return None
        old_start, old_count, new_start, new_count = (int(match.group(1)), int(match.group(2) or 1), int(match.group(3)), int(match.group(4) or 1))
        if (old_start == 0 and old_count != 0) or (new_start == 0 and new_count != 0):
            return None
        index += 1; body: list[tuple[str, str]] = []
        while index < len(lines) and not clean[index].startswith("@@ "):
            line = clean[index]
            if line == "\\ No newline at end of file":
                if not body or not body[-1][1].endswith(("\n", "\r")):
                    return None
                body[-1] = (body[-1][0], body[-1][1].rstrip("\r\n")); index += 1; continue
            if not line or line[0] not in {" ", "+", "-"}:
                return None
            body.append((line[0], lines[index][1:])); index += 1
        if sum(kind in {" ", "-"} for kind, _ in body) != old_count or sum(kind in {" ", "+"} for kind, _ in body) != new_count:
            return None
        hunks.append((old_start, old_count, new_start, new_count, body))
    if not hunks:
        return None
    base = base_text.splitlines(keepends=True); result: list[str] = []; cursor = 0; previous_new = 0
    for old_start, old_count, new_start, new_count, body in hunks:
        target = old_start if old_count == 0 else old_start - 1
        if target < cursor or target > len(base) or new_start < previous_new:
            return None
        result.extend(base[cursor:target]); cursor = target
        expected_new_start = len(result) + (1 if new_count else 0)
        if new_start != expected_new_start:
            return None
        for kind, content in body:
            if kind in {" ", "-"}:
                if cursor >= len(base) or base[cursor] != content:
                    return None
                cursor += 1
            if kind in {" ", "+"}:
                result.append(content)
        if cursor != target + old_count:
            return None
        previous_new = new_start + new_count
    result.extend(base[cursor:]); return "".join(result)


def check_patch_scope(ctx: GateContext) -> tuple[Finding, ...]:
    applied = _apply_unified_diff(ctx.base_text, ctx.patch_text, str(ctx.base_path), str(ctx.candidate_path))
    return () if applied == ctx.candidate_text else finding("patch-scope", "patch is not an exact unified diff from base to candidate")
def _valid_workspace_snapshot(snapshot: dict[str, Any]) -> bool:
    valid_envelope = (
        isinstance(snapshot, dict) and snapshot.get("version") == 1 and not isinstance(snapshot.get("version"), bool)
        and isinstance(snapshot.get("snapshot_id"), str) and re.fullmatch(r"[0-9a-f]{64}", snapshot["snapshot_id"]) is not None
        and isinstance(snapshot.get("workspace_root"), str) and snapshot["workspace_root"]
        and isinstance(snapshot.get("modules"), dict)
        and all(isinstance(module_id, str) and module_id and isinstance(state, dict) and isinstance(state.get("commit"), str) and state["commit"] and isinstance(state.get("path"), str) and state["path"] and isinstance(state.get("kind"), str) and state["kind"] and isinstance(state.get("dirty"), bool) and state.get("dirty_policy") in {"clean", "HEAD", "working-tree"} for module_id, state in snapshot["modules"].items())
    )
    canonical = json.dumps(snapshot["modules"], sort_keys=True, separators=(",", ":")).encode("utf-8") if valid_envelope else b""
    return valid_envelope and hashlib.sha256(canonical).hexdigest() == snapshot["snapshot_id"]

def check_snapshot_freshness(ctx: GateContext) -> tuple[Finding, ...]:
    mapped = ctx.source_map.get("workspace_snapshot")
    actual = ctx.workspace_snapshot
    valid_map = isinstance(mapped, dict) and mapped.get("fresh") is True and mapped.get("snapshot_id") == actual.get("snapshot_id")
    return () if _valid_workspace_snapshot(actual) and valid_map else finding("snapshot-freshness", "workspace snapshot is missing, malformed, stale, or mismatched")
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
    candidate: Path, resolved_evidence: Path, coverage: Path, source_map: Path, workspace_snapshot: Path, patch: Path, base: Path
) -> GateContext:
    """Load UTF-8 artifacts once before evaluating checks."""
    return GateContext(
        candidate_path=candidate,
        candidate_text=candidate.read_text(encoding="utf-8"),
        resolved_evidence=_load_object(resolved_evidence, "resolved evidence"),
        coverage=_load_object(coverage, "coverage"),
        source_map=_load_object(source_map, "source map"),
        workspace_snapshot=_load_object(workspace_snapshot, "workspace snapshot"),
        patch_text=patch.read_text(encoding="utf-8"),
        base_path=base,
        base_text=base.read_text(encoding="utf-8") if base.exists() else "",
    )


def run_gate(
    *, candidate: Path, resolved_evidence: Path, coverage: Path, source_map: Path, workspace_snapshot: Path, patch: Path, base: Path
) -> GateReport:
    """Run the fixed ordered set of deterministic checks."""
    context = load_gate_context(candidate, resolved_evidence, coverage, source_map, workspace_snapshot, patch, base)
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


def validate_report_payload(payload: dict[str, Any]) -> None:
    required = {"version", "status", "candidate", "candidate_sha256", "checks", "findings", "generated_at"}
    if set(payload) != required or payload["version"] != REPORT_VERSION or isinstance(payload["version"], bool) or payload["status"] not in {"passed", "passed_with_warnings", "blocked"}:
        raise ValueError("quality report payload does not match schema")
    if not isinstance(payload["candidate"], str) or not payload["candidate"] or not isinstance(payload["candidate_sha256"], str) or re.fullmatch(r"[0-9a-f]{64}", payload["candidate_sha256"]) is None:
        raise ValueError("quality report payload does not match schema")
    if not isinstance(payload["checks"], list) or not isinstance(payload["findings"], list) or not isinstance(payload["generated_at"], str):
        raise ValueError("quality report payload does not match schema")
    for check in payload["checks"]:
        if not isinstance(check, dict) or set(check) != {"id", "status", "finding_count"} or not isinstance(check["id"], str) or check["status"] not in {"passed", "failed"} or not isinstance(check["finding_count"], int) or isinstance(check["finding_count"], bool) or check["finding_count"] < 0:
            raise ValueError("quality report payload does not match schema")
    for item in payload["findings"]:
        if not isinstance(item, dict) or set(item) != {"rule", "message", "severity", "entity_type", "entity_id"} or not isinstance(item["rule"], str) or not item["rule"] or not isinstance(item["message"], str) or not item["message"] or item["severity"] not in {"blocking", "warning"} or not all(value is None or isinstance(value, str) for value in (item["entity_type"], item["entity_id"])):
            raise ValueError("quality report payload does not match schema")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", payload["generated_at"]) is None:
        raise ValueError("quality report payload does not match schema")


def _stage_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(text.encode("utf-8"))
    return Path(temporary_name)


def _atomic_write_reports(outputs: dict[str, Path], json_text: str, markdown_text: str) -> None:
    staged = {"json": _stage_text(outputs["json"], json_text), "markdown": _stage_text(outputs["markdown"], markdown_text)}
    original = {name: path.read_bytes() if path.exists() else None for name, path in outputs.items()}
    replaced: list[str] = []
    try:
        for name in ("json", "markdown"):
            os.replace(staged[name], outputs[name])
            replaced.append(name)
    except BaseException:
        for name in reversed(replaced):
            previous = original[name]
            if previous is None:
                outputs[name].unlink(missing_ok=True)
            else:
                restore = _stage_text(outputs[name], previous.decode("utf-8"))
                os.replace(restore, outputs[name])
        raise
    finally:
        for temporary in staged.values():
            temporary.unlink(missing_ok=True)


def write_reports(report: GateReport, candidate: Path, out_dir: Path) -> dict[str, Path]:
    """Validate then atomically replace both UTF-8 report artifacts as a pair."""
    outputs = {"json": out_dir / "methodology-quality-report.json", "markdown": out_dir / "methodology-quality-report.md"}
    payload = {
        "version": REPORT_VERSION,
        "status": report.status,
        "candidate": str(candidate),
        "candidate_sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
        "checks": list(report.checks),
        "findings": [_report_finding(item) for item in report.findings],
        "generated_at": _generated_at(),
    }
    validate_report_payload(payload)
    _atomic_write_reports(outputs, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", render_markdown(report, payload))
    return outputs
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the deterministic methodology quality gate.")
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--resolved-evidence", type=Path, required=True)
    parser.add_argument("--coverage", type=Path, required=True)
    parser.add_argument("--source-map", type=Path, required=True)
    parser.add_argument("--workspace-snapshot", type=Path, required=True)
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
            workspace_snapshot=args.workspace_snapshot,
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

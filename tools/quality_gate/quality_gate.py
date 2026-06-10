#!/usr/bin/env python3
"""Aggregate Phase 0 Gatling-AI quality checks and write reports."""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from contextlib import contextmanager
import json
import shutil
import sys
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _shared.common import (  # noqa: E402
    Finding,
    find_repo_root,
    finding_to_dict,
    load_yaml,
    rel_path,
    run_command,
)

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover - environment issue is reported at runtime.
    Draft202012Validator = None


PASSED = "passed"
PASSED_WITH_WARNINGS = "passed_with_warnings"
BLOCKED = "blocked"
SKIPPED = "skipped"
GENERATED_COMPARE_DIRS = (Path("src/test/java"), Path("src/test/resources"))


@dataclass
class CheckResult:
    name: str
    status: str
    artifacts: list[str] = field(default_factory=list)
    command: str | None = None


@dataclass
class GateContext:
    repo_root: Path
    scenario: Path
    project: Path
    schema: Path
    profile: str
    json_report: Path
    md_report: Path
    artifacts: set[str] = field(default_factory=set)
    blocking: list[Finding] = field(default_factory=list)
    warnings: list[Finding] = field(default_factory=list)
    waivers: list[dict[str, Any]] = field(default_factory=list)
    checks: list[CheckResult] = field(default_factory=list)


def json_path(parts: Any) -> str:
    rendered = "$"
    for part in parts:
        if isinstance(part, int):
            rendered += f"[{part}]"
        else:
            rendered += f".{part}"
    return rendered


def command_text(args: list[str]) -> str:
    display = ["python" if arg == sys.executable else arg for arg in args]
    return " ".join(display)


def output_excerpt(stdout: str, stderr: str, limit: int = 4000) -> str:
    combined = "\n".join(part for part in (stdout.strip(), stderr.strip()) if part)
    if len(combined) <= limit:
        return combined
    return combined[-limit:]


def add_artifacts(ctx: GateContext, *paths: Path) -> list[str]:
    artifacts = [rel_path(path, ctx.repo_root) for path in paths]
    ctx.artifacts.update(artifacts)
    return artifacts


def run_schema_check(ctx: GateContext) -> None:
    artifacts = add_artifacts(ctx, ctx.scenario, ctx.schema)
    if Draft202012Validator is None:
        ctx.blocking.append(
            Finding(
                check="schema",
                rule="schema.validation-unavailable",
                artifact=rel_path(ctx.scenario, ctx.repo_root),
                message="jsonschema is unavailable; schema validation cannot run.",
            )
        )
        ctx.checks.append(CheckResult("schema", BLOCKED, artifacts))
        return

    try:
        document = load_yaml(ctx.scenario)
        schema = json.loads(ctx.schema.read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema)
        errors = sorted(
            validator.iter_errors(document),
            key=lambda error: (list(error.absolute_path), error.message),
        )
    except Exception as exc:
        ctx.blocking.append(
            Finding(
                check="schema",
                rule="schema.load-failed",
                artifact=rel_path(ctx.scenario, ctx.repo_root),
                message=str(exc),
            )
        )
        ctx.checks.append(CheckResult("schema", BLOCKED, artifacts))
        return

    for error in errors:
        ctx.blocking.append(
            Finding(
                check="schema",
                rule="schema.validation",
                artifact=rel_path(ctx.scenario, ctx.repo_root),
                path=json_path(error.absolute_path),
                message=error.message,
            )
        )
    ctx.checks.append(CheckResult("schema", BLOCKED if errors else PASSED, artifacts))


def run_lint_check(ctx: GateContext) -> None:
    script = ctx.repo_root / "tools" / "scenario_lint" / "scenario_lint.py"
    artifacts = add_artifacts(ctx, ctx.scenario, script)
    args = [sys.executable, str(script), str(ctx.scenario), "--format", "json"]
    command = command_text([sys.executable, "tools/scenario_lint/scenario_lint.py", rel_path(ctx.scenario, ctx.repo_root), "--format", "json"])

    try:
        result = run_command(args, ctx.repo_root)
    except Exception as exc:
        ctx.blocking.append(
            Finding(
                check="scenario-lint",
                rule="scenario-lint.command-failed",
                artifact=rel_path(ctx.scenario, ctx.repo_root),
                command=command,
                message=str(exc),
            )
        )
        ctx.checks.append(CheckResult("scenario-lint", BLOCKED, artifacts, command))
        return

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        ctx.blocking.append(
            Finding(
                check="scenario-lint",
                rule="scenario-lint.invalid-output",
                artifact=rel_path(ctx.scenario, ctx.repo_root),
                command=command,
                output=output_excerpt(result.stdout, result.stderr),
                message="scenario lint did not emit valid JSON.",
            )
        )
        ctx.checks.append(CheckResult("scenario-lint", BLOCKED, artifacts, command))
        return

    for item in payload.get("blocking", []):
        ctx.blocking.append(
            Finding(
                check="scenario-lint",
                rule=str(item.get("rule", "scenario-lint.finding")),
                artifact=str(item.get("artifact", payload.get("artifact", rel_path(ctx.scenario, ctx.repo_root)))),
                path=item.get("path"),
                message=str(item.get("message", "")),
            )
        )
    for item in payload.get("warnings", []):
        ctx.warnings.append(
            Finding(
                check="scenario-lint",
                rule=str(item.get("rule", "scenario-lint.warning")),
                artifact=str(item.get("artifact", payload.get("artifact", rel_path(ctx.scenario, ctx.repo_root)))),
                path=item.get("path"),
                message=str(item.get("message", "")),
            )
        )

    status = BLOCKED if payload.get("blocking") else PASSED_WITH_WARNINGS if payload.get("warnings") else PASSED
    if result.returncode != 0 and not payload.get("blocking"):
        ctx.blocking.append(
            Finding(
                check="scenario-lint",
                rule="scenario-lint.unexpected-exit",
                artifact=rel_path(ctx.scenario, ctx.repo_root),
                command=command,
                output=output_excerpt(result.stdout, result.stderr),
                message=f"scenario lint exited {result.returncode} without blocking findings.",
            )
        )
        status = BLOCKED
    ctx.checks.append(CheckResult("scenario-lint", status, artifacts, command))


def generated_files(root: Path, relative_dirs: tuple[Path, ...] | None = None) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    search_roots = tuple(root / relative_dir for relative_dir in relative_dirs) if relative_dirs else (root,)
    for search_root in search_roots:
        if not search_root.exists():
            continue
        for path in sorted(search_root.rglob("*")):
            if path.is_file():
                files[path.relative_to(root).as_posix()] = path.read_bytes()
    return files


def summarize_generated_diff(expected: dict[str, bytes], actual: dict[str, bytes]) -> str:
    expected_paths = set(expected)
    actual_paths = set(actual)
    missing = sorted(expected_paths - actual_paths)
    extra = sorted(actual_paths - expected_paths)
    changed = sorted(path for path in expected_paths & actual_paths if expected[path] != actual[path])
    parts: list[str] = []
    if changed:
        parts.append(f"changed: {', '.join(changed[:10])}")
    if missing:
        parts.append(f"missing: {', '.join(missing[:10])}")
    if extra:
        parts.append(f"extra: {', '.join(extra[:10])}")
    if len(changed) + len(missing) + len(extra) > 10:
        parts.append("additional differences omitted")
    return "; ".join(parts)


@contextmanager
def quality_gate_temp_dir(ctx: GateContext) -> Iterator[Path]:
    fallback_parent = ctx.repo_root / "tools" / "quality_gate" / "tmp"
    candidates = (Path(tempfile.gettempdir()), fallback_parent)
    for parent in candidates:
        temp_parent = parent / f"gatling-ai-quality-gate-{uuid.uuid4().hex}"
        try:
            parent.mkdir(parents=True, exist_ok=True)
            temp_parent.mkdir()
            probe = temp_parent / ".probe"
            probe.mkdir()
            probe.rmdir()
        except OSError:
            shutil.rmtree(temp_parent, ignore_errors=True)
            continue
        try:
            yield temp_parent
            return
        finally:
            shutil.rmtree(temp_parent, ignore_errors=True)

    raise OSError("could not create a writable temporary directory for generator comparison")


def run_generator_once(ctx: GateContext, output_dir: Path) -> subprocess.CompletedProcess[str]:
    script = ctx.repo_root / "tools" / "gatling_generator" / "gatling_generator.py"
    args = [sys.executable, str(script), str(ctx.scenario), str(output_dir), "--format", "json"]
    return run_command(args, ctx.repo_root)


def run_generator_check(ctx: GateContext) -> None:
    script = ctx.repo_root / "tools" / "gatling_generator" / "gatling_generator.py"
    project_compare_paths = [ctx.project / relative_dir for relative_dir in GENERATED_COMPARE_DIRS]
    artifacts = add_artifacts(ctx, ctx.scenario, script, *project_compare_paths)
    command = command_text([sys.executable, "tools/gatling_generator/gatling_generator.py", rel_path(ctx.scenario, ctx.repo_root), "<temp-project>"])

    with quality_gate_temp_dir(ctx) as temp_parent:
        run_a = temp_parent / "run-a"
        run_b = temp_parent / "run-b"
        for output_dir in (run_a, run_b):
            output_dir.mkdir(parents=True, exist_ok=True)
        try:
            result_a = run_generator_once(ctx, run_a)
            result_b = run_generator_once(ctx, run_b)
        except Exception as exc:
            ctx.blocking.append(
                Finding(
                    check="generator",
                    rule="generator.command-failed",
                    artifact=rel_path(ctx.scenario, ctx.repo_root),
                    command=command,
                    message=str(exc),
                )
            )
            ctx.checks.append(CheckResult("generator", BLOCKED, artifacts, command))
            return

        for label, result in (("first", result_a), ("second", result_b)):
            if result.returncode != 0:
                rule = "generator.failed"
                message = f"generator {label} run exited {result.returncode}."
                try:
                    payload = json.loads(result.stdout)
                    item = payload["blocking"][0]
                    rule = str(item.get("rule", rule))
                    message = f"{message} {item.get('message', '')}".strip()
                except (json.JSONDecodeError, LookupError, TypeError):
                    pass
                ctx.blocking.append(
                    Finding(
                        check="generator",
                        rule=rule,
                        artifact=rel_path(ctx.scenario, ctx.repo_root),
                        command=command,
                        output=output_excerpt(result.stdout, result.stderr),
                        message=message,
                    )
                )
                ctx.checks.append(CheckResult("generator", BLOCKED, artifacts, command))
                return

        files_a = generated_files(run_a)
        files_b = generated_files(run_b)
        if files_a != files_b:
            ctx.blocking.append(
                Finding(
                    check="generator",
                    rule="generator.non-deterministic-output",
                    artifact=rel_path(ctx.scenario, ctx.repo_root),
                    command=command,
                    message="generator produced different files across two temporary runs.",
                )
            )
            ctx.checks.append(CheckResult("generator", BLOCKED, artifacts, command))
            return

        generated_relevant = generated_files(run_a, GENERATED_COMPARE_DIRS)
        project_relevant = generated_files(ctx.project, GENERATED_COMPARE_DIRS)
        if generated_relevant != project_relevant:
            ctx.blocking.append(
                Finding(
                    check="generator",
                    rule="generator.project-output-stale",
                    artifact=rel_path(ctx.project, ctx.repo_root),
                    command=command,
                    message=(
                        "generated project files do not match a fresh generator run "
                        f"for {', '.join(path.as_posix() for path in GENERATED_COMPARE_DIRS)} "
                        f"({summarize_generated_diff(generated_relevant, project_relevant)})."
                    ),
                )
            )
            ctx.checks.append(CheckResult("generator", BLOCKED, artifacts, command))
            return

        ctx.checks.append(CheckResult("generator", PASSED, artifacts, command))


def resolve_maven_executable() -> str | None:
    for candidate in ("mvn.cmd", "mvn.bat", "mvn"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None


def run_maven_compile_check(ctx: GateContext) -> None:
    pom = ctx.project / "pom.xml"
    artifacts = add_artifacts(ctx, pom)
    java_dir = ctx.project / "src" / "test" / "java"
    resource_dir = ctx.project / "src" / "test" / "resources"
    if java_dir.exists():
        artifacts.extend(add_artifacts(ctx, *sorted(path for path in java_dir.rglob("*.java"))))
    if resource_dir.exists():
        artifacts.extend(add_artifacts(ctx, *sorted(path for path in resource_dir.rglob("*") if path.is_file())))

    command = "mvn -q compile"
    executable = resolve_maven_executable()
    if executable is None:
        ctx.blocking.append(
            Finding(
                check="maven-compile",
                rule="maven.compile-command-failed",
                artifact=rel_path(pom, ctx.repo_root),
                command=command,
                message="Maven executable was not found on PATH.",
            )
        )
        ctx.checks.append(CheckResult("maven-compile", BLOCKED, artifacts, command))
        return

    args = [executable, "-q", "compile"]
    try:
        result = run_command(args, ctx.project, timeout=180)
    except Exception as exc:
        ctx.blocking.append(
            Finding(
                check="maven-compile",
                rule="maven.compile-command-failed",
                artifact=rel_path(pom, ctx.repo_root),
                command=command,
                message=str(exc),
            )
        )
        ctx.checks.append(CheckResult("maven-compile", BLOCKED, artifacts, command))
        return

    if result.returncode != 0:
        ctx.blocking.append(
            Finding(
                check="maven-compile",
                rule="maven.compile-failed",
                artifact=rel_path(pom, ctx.repo_root),
                command=command,
                output=output_excerpt(result.stdout, result.stderr),
                message=f"Maven compile exited {result.returncode}.",
            )
        )
        ctx.checks.append(CheckResult("maven-compile", BLOCKED, artifacts, command))
        return

    ctx.checks.append(CheckResult("maven-compile", PASSED, artifacts, command))


def skip_late_checks(ctx: GateContext) -> None:
    message = "generator and Maven compile skipped because schema or scenario lint has blocking findings."
    ctx.warnings.append(
        Finding(
            check="quality-gate",
            rule="quality-gate.skipped-late-checks",
            artifact=rel_path(ctx.scenario, ctx.repo_root),
            message=message,
        )
    )
    ctx.checks.append(CheckResult("generator", SKIPPED, [rel_path(ctx.scenario, ctx.repo_root)]))
    ctx.checks.append(CheckResult("maven-compile", SKIPPED, [rel_path(ctx.project / "pom.xml", ctx.repo_root)]))


def final_status(ctx: GateContext) -> str:
    if ctx.blocking:
        return BLOCKED
    if ctx.warnings or ctx.waivers:
        return PASSED_WITH_WARNINGS
    return PASSED


def report_payload(ctx: GateContext, checked_at: str) -> dict[str, Any]:
    return {
        "status": final_status(ctx),
        "profile": ctx.profile,
        "checked_at": checked_at,
        "artifacts": sorted(ctx.artifacts),
        "blocking": [finding_to_dict(finding) for finding in ctx.blocking],
        "warnings": [finding_to_dict(finding) for finding in ctx.warnings],
        "waivers": ctx.waivers,
        "checks": [asdict(check) for check in ctx.checks],
    }


def render_finding(finding: Finding) -> str:
    parts = [finding.rule]
    if finding.artifact:
        parts.append(finding.artifact)
    if finding.path:
        parts.append(finding.path)
    prefix = " - ".join(parts)
    return f"- {prefix}: {finding.message}"


def render_markdown(payload: dict[str, Any], ctx: GateContext) -> str:
    lines = [
        "# Quality Gate Report",
        "",
        f"- Status: `{payload['status']}`",
        f"- Profile: `{payload['profile']}`",
        f"- Checked at: `{payload['checked_at']}`",
        "",
        "## Checked Artifacts",
    ]
    if payload["artifacts"]:
        lines.extend(f"- `{artifact}`" for artifact in payload["artifacts"])
    else:
        lines.append("- None")

    lines.extend(["", "## Checks"])
    for check in ctx.checks:
        command = f" (`{check.command}`)" if check.command else ""
        lines.append(f"- `{check.name}`: `{check.status}`{command}")

    lines.extend(["", "## Blocking Findings"])
    if ctx.blocking:
        lines.extend(render_finding(finding) for finding in ctx.blocking)
    else:
        lines.append("- None")

    lines.extend(["", "## Warnings"])
    if ctx.warnings:
        lines.extend(render_finding(finding) for finding in ctx.warnings)
    else:
        lines.append("- None")

    lines.extend(["", "## Accepted Waivers"])
    if ctx.waivers:
        for waiver in ctx.waivers:
            lines.append(f"- `{waiver.get('rule', 'waiver')}`: {waiver.get('reason', '')}")
    else:
        lines.append("- None")

    return "\n".join(lines) + "\n"


def write_reports(ctx: GateContext) -> dict[str, Any]:
    checked_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    payload = report_payload(ctx, checked_at)
    ctx.json_report.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    ctx.md_report.write_text(render_markdown(payload, ctx), encoding="utf-8", newline="\n")
    return payload


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Gatling-AI Phase 0 quality gate.")
    parser.add_argument("--scenario", required=True, type=Path, help="scenario YAML to validate")
    parser.add_argument(
        "--project",
        required=True,
        type=Path,
        help="Maven project root for the generated Java golden path",
    )
    parser.add_argument("--profile", default="mvp", choices=("mvp",), help="quality gate profile")
    parser.add_argument(
        "--schema",
        default=Path("schemas/scenario.schema.json"),
        type=Path,
        help="JSON Schema path",
    )
    parser.add_argument(
        "--json-report",
        default=Path("quality-gate-report.json"),
        type=Path,
        help="JSON report output path",
    )
    parser.add_argument(
        "--md-report",
        default=Path("quality-gate-report.md"),
        type=Path,
        help="Markdown report output path",
    )
    return parser.parse_args(argv)


def resolve_arg_path(path: Path, repo_root: Path) -> Path:
    return path if path.is_absolute() else repo_root / path


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = find_repo_root(Path(__file__), Path.cwd(), args.scenario, args.project) or Path.cwd().resolve()
    scenario = resolve_arg_path(args.scenario, repo_root)
    project = resolve_arg_path(args.project, repo_root)
    schema = resolve_arg_path(args.schema, repo_root)
    json_report = resolve_arg_path(args.json_report, repo_root)
    md_report = resolve_arg_path(args.md_report, repo_root)

    ctx = GateContext(
        repo_root=repo_root,
        scenario=scenario,
        project=project,
        schema=schema,
        profile=args.profile,
        json_report=json_report,
        md_report=md_report,
    )

    run_schema_check(ctx)
    run_lint_check(ctx)
    if ctx.blocking:
        skip_late_checks(ctx)
    else:
        run_generator_check(ctx)
        run_maven_compile_check(ctx)

    payload = write_reports(ctx)
    print(json.dumps({"status": payload["status"], "json_report": rel_path(json_report, repo_root), "md_report": rel_path(md_report, repo_root)}, sort_keys=True))
    return 1 if payload["status"] == BLOCKED else 0


if __name__ == "__main__":
    sys.exit(main())

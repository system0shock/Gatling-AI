"""Build and check deterministic methodology-first run artifacts."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
import sys
import tempfile
from typing import Any

if __package__:
    from . import (
        assembler,
        conformance,
        contracts,
        managed_blocks,
        profiles,
        questionnaire,
        readiness,
        renderer,
    )
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from tools.methodology_pipeline import (
        assembler,
        conformance,
        contracts,
        managed_blocks,
        profiles,
        questionnaire,
        readiness,
        renderer,
    )


MANAGE_METHODOLOGY_ROOT = (
    Path(__file__).resolve().parents[2]
    / ".gigacode"
    / "skills"
    / "manage-methodology"
)
EMPTY_GENERATION_STATE: dict[str, Any] = {"version": 1, "blocks": {}}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build or independently check methodology-first artifacts."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build", help="build a candidate and reports")
    build.add_argument("--workspace-snapshot", type=Path, required=True)
    build.add_argument("--surface-review", type=Path, required=True)
    build.add_argument("--profile", type=Path, required=True)
    build.add_argument("--questions", type=Path, required=True)
    build.add_argument("--answers", type=Path, required=True)
    build.add_argument("--template", type=Path, required=True)
    build.add_argument("--template-contract", type=Path, required=True)
    build.add_argument("--current", type=Path, required=True)
    build.add_argument("--previous-generation-state", type=Path)
    build.add_argument("--drift-decisions", type=Path)
    build.add_argument("--out-dir", type=Path, required=True)
    build.add_argument("--load-test-root", type=Path, required=True)

    check = commands.add_parser("check", help="regenerate reports from run artifacts")
    check.add_argument("--candidate", type=Path, required=True)
    check.add_argument("--methodology-input", type=Path, required=True)
    check.add_argument("--generation-state", type=Path, required=True)
    check.add_argument("--template-contract", type=Path, required=True)
    check.add_argument("--out-dir", type=Path, required=True)
    check.add_argument("--load-test-root", type=Path, required=True)
    return parser


def _resolve_root(path: Path, label: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"{label} is unavailable: {path}: {exc}") from exc
    if not resolved.is_dir():
        raise ValueError(f"{label} is not a directory: {path}")
    return resolved


def _contained_path(
    path: Path,
    root: Path,
    boundary_name: str,
    *,
    must_exist: bool,
) -> Path:
    try:
        resolved = path.resolve(strict=must_exist)
    except OSError as exc:
        raise ValueError(f"path is unavailable: {path}: {exc}") from exc
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"path is outside {boundary_name}: {path}") from exc
    return resolved


def _runtime_path(path: Path, root: Path, *, must_exist: bool) -> Path:
    return _contained_path(
        path, root, "load-test root", must_exist=must_exist
    )


def _asset_path(path: Path, asset_root: Path) -> Path:
    return _contained_path(
        path,
        asset_root,
        "manage-methodology root",
        must_exist=True,
    )


def _load_json_mapping(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label}: expected a mapping")
    return value


def _read_text(path: Path, label: str) -> str:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return handle.read()
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"{label}: {path}: {exc}") from exc


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _write_reports(
    out_dir: Path,
    readiness_value: Mapping[str, Any],
    template_value: Mapping[str, Any],
) -> None:
    contracts.write_json_atomic(
        out_dir / "methodology-readiness-report.json", readiness_value
    )
    _write_text_atomic(
        out_dir / "methodology-readiness-report.md",
        conformance.render_readiness_markdown(readiness_value),
    )
    contracts.write_json_atomic(
        out_dir / "methodology-template-report.json", template_value
    )
    _write_text_atomic(
        out_dir / "methodology-template-report.md",
        conformance.render_template_markdown(template_value),
    )


def _generation_state_conflict(
    candidate: str,
    methodology_input: Mapping[str, Any],
    generation_state: Mapping[str, Any],
) -> str | None:
    views = managed_blocks.parse_managed_sections(candidate)
    rendered = renderer.render_generated_sections(methodology_input)
    canonical_ids = tuple(rendered)
    candidate_ids = {
        section_id
        for section_id, view in views.items()
        if view.generated is not None
    }
    if candidate_ids != set(canonical_ids):
        return "candidate generated blocks do not match canonical sections"
    state_blocks = generation_state["blocks"]
    if set(state_blocks) != set(canonical_ids):
        return "generation state blocks do not match canonical sections"
    for section_id in canonical_ids:
        actual = views[section_id].generated
        if actual is None:
            return "candidate generated blocks do not match canonical sections"
        state = state_blocks[section_id]
        if managed_blocks.sha256_text(actual) != state["sha256"]:
            return f"candidate generated hash mismatch: {section_id}"
        if (
            managed_blocks.sha256_text(rendered[section_id])
            != state["rendered_sha256"]
        ):
            return f"deterministic rendered hash mismatch: {section_id}"
    return None


def _build(arguments: argparse.Namespace) -> int:
    load_root = _resolve_root(arguments.load_test_root, "load-test root")
    asset_root = _resolve_root(MANAGE_METHODOLOGY_ROOT, "manage-methodology root")

    workspace_snapshot_path = _runtime_path(
        arguments.workspace_snapshot, load_root, must_exist=True
    )
    surface_review_path = _runtime_path(
        arguments.surface_review, load_root, must_exist=True
    )
    answers_path = _runtime_path(arguments.answers, load_root, must_exist=True)
    current_path = _runtime_path(arguments.current, load_root, must_exist=False)
    out_dir = _runtime_path(arguments.out_dir, load_root, must_exist=False)
    previous_state_path = (
        _runtime_path(
            arguments.previous_generation_state, load_root, must_exist=True
        )
        if arguments.previous_generation_state is not None
        else None
    )
    drift_decisions_path = (
        _runtime_path(arguments.drift_decisions, load_root, must_exist=True)
        if arguments.drift_decisions is not None
        else None
    )

    profile_path = _asset_path(arguments.profile, asset_root)
    questions_path = _asset_path(arguments.questions, asset_root)
    template_path = _asset_path(arguments.template, asset_root)
    template_contract_path = _asset_path(arguments.template_contract, asset_root)

    snapshot_value = _load_json_mapping(
        workspace_snapshot_path, "workspace snapshot"
    )
    surface_value = _load_json_mapping(surface_review_path, "surface review")
    profile_value = contracts.load_yaml_mapping(
        profile_path, "methodology-profile.schema.json"
    )
    catalog_value = contracts.load_yaml_mapping(
        questions_path, "methodology-questions.schema.json"
    )
    answers_value = contracts.load_yaml_mapping(
        answers_path, "methodology-answers.schema.json"
    )
    template_contract_value = contracts.load_yaml_mapping(
        template_contract_path, "methodology-template-contract.schema.json"
    )
    template_text = _read_text(template_path, "methodology template")
    current_text = (
        _read_text(current_path, "current methodology")
        if current_path.exists()
        else template_text
    )
    previous_state = (
        _load_json_mapping(previous_state_path, "previous generation state")
        if previous_state_path is not None
        else dict(EMPTY_GENERATION_STATE)
    )
    contracts.validate_artifact(
        previous_state, "methodology-generation-state.schema.json"
    )
    drift_decisions = (
        contracts.load_yaml_mapping(
            drift_decisions_path, "methodology-drift-decisions.schema.json"
        )
        if drift_decisions_path is not None
        else None
    )

    resolved_profile = profiles.resolve_profile(profile_value, answers_value)
    methodology_input = assembler.build_input(
        snapshot_value,
        surface_value,
        resolved_profile,
        catalog_value,
        answers_value,
    )
    capabilities = assembler.capabilities_from_surface(surface_value)
    pending_questions = questionnaire.unresolved_questions(
        methodology_input, catalog_value, capabilities
    )
    readiness_value = readiness.readiness_report(
        methodology_input, pending_questions
    )
    render_result = renderer.render_candidate(
        current_text,
        methodology_input,
        previous_state,
        drift_decisions,
    )
    template_value = conformance.template_report(
        render_result.markdown, template_contract_value, methodology_input
    )

    contracts.write_yaml_atomic(
        out_dir / "resolved-profile.yaml", resolved_profile
    )
    contracts.write_yaml_atomic(
        out_dir / "methodology-input.yaml", methodology_input
    )
    contracts.write_json_atomic(
        out_dir / "generation-state.json", render_result.generation_state
    )
    _write_text_atomic(
        out_dir / "methodology.candidate.md", render_result.markdown
    )
    _write_reports(out_dir, readiness_value, template_value)

    if not readiness_value["ready_for_test"] or render_result.conflicts:
        for conflict in render_result.conflicts:
            print(f"error: {conflict['message']}", file=sys.stderr)
        return 2
    if not template_value["template_complete"] or render_result.warnings:
        return 1
    return 0


def _check(arguments: argparse.Namespace) -> int:
    load_root = _resolve_root(arguments.load_test_root, "load-test root")
    asset_root = _resolve_root(MANAGE_METHODOLOGY_ROOT, "manage-methodology root")
    candidate_path = _runtime_path(arguments.candidate, load_root, must_exist=True)
    input_path = _runtime_path(
        arguments.methodology_input, load_root, must_exist=True
    )
    state_path = _runtime_path(
        arguments.generation_state, load_root, must_exist=True
    )
    out_dir = _runtime_path(arguments.out_dir, load_root, must_exist=False)
    template_contract_path = _asset_path(arguments.template_contract, asset_root)

    candidate = _read_text(candidate_path, "methodology candidate")
    methodology_input = contracts.load_yaml_mapping(
        input_path, "methodology-input.schema.json"
    )
    generation_state = _load_json_mapping(state_path, "generation state")
    contracts.validate_artifact(
        generation_state, "methodology-generation-state.schema.json"
    )
    template_contract = contracts.load_yaml_mapping(
        template_contract_path, "methodology-template-contract.schema.json"
    )

    readiness_value = readiness.readiness_report(methodology_input, [])
    template_value = conformance.template_report(
        candidate, template_contract, methodology_input
    )
    state_conflict = _generation_state_conflict(
        candidate, methodology_input, generation_state
    )
    _write_reports(out_dir, readiness_value, template_value)

    if state_conflict is not None:
        print(f"error: check state conflict: {state_conflict}", file=sys.stderr)
        return 2
    if not readiness_value["ready_for_test"]:
        return 2
    if (
        not template_value["template_complete"]
        or any(
            block["resolution"] == "keep"
            for block in generation_state["blocks"].values()
        )
    ):
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "build":
            return _build(arguments)
        return _check(arguments)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Thin scan-and-confirm CLI for bounded multi-repository discovery."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
import sys
from typing import Any, Callable

import yaml

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.methodology_discovery import (  # noqa: E402
    asyncapi,
    contracts,
    deployment,
    graphql_sdl,
    locator,
    merge,
    openapi,
    source_views,
    surface_review,
)
from tools.workspace_discovery.models import (  # noqa: E402
    ModuleConfig,
    load_manifest,
    resolve_workspace_root,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build and confirm a bounded surface candidate")
    commands = parser.add_subparsers(dest="command", required=True)
    scan = commands.add_parser("scan")
    scan.add_argument("--manifest", type=Path, required=True)
    scan.add_argument("--workspace-snapshot", type=Path, required=True)
    scan.add_argument("--run-dir", type=Path, required=True)
    scan.add_argument("--load-test-root", type=Path, required=True)
    confirm = commands.add_parser("confirm")
    confirm.add_argument("--candidate", type=Path, required=True)
    confirm.add_argument("--decisions", type=Path, required=True)
    confirm.add_argument("--out", type=Path, required=True)
    confirm.add_argument("--load-test-root", type=Path, required=True)
    return parser


def _inside(
    root: Path, path: Path, *, must_exist: bool, boundary: str = "load-test root"
) -> Path:
    resolved = path.resolve(strict=must_exist)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"path is outside {boundary}: {path}") from exc
    return resolved


def _mapping(path: Path, label: str, *, yaml_input: bool = False) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
        value = yaml.safe_load(text) if yaml_input else json.loads(text)
    except (OSError, UnicodeError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"{label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a mapping")
    return value


def _snapshot_repositories(snapshot: Mapping[str, Any]) -> Mapping[str, Any]:
    key = "repositories" if snapshot.get("version") == 2 else "modules"
    value = snapshot.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"workspace snapshot has no {key} mapping")
    return value


def _validate_snapshot(snapshot: Mapping[str, Any], manifest: Any, workspace_root: Path) -> Mapping[str, Any]:
    states = _snapshot_repositories(snapshot)
    repositories = {repository.module_id: repository for repository in manifest.repositories}
    if snapshot.get("version") != manifest.version or set(states) != set(repositories):
        raise ValueError("workspace snapshot does not match manifest repositories")
    if Path(str(snapshot.get("workspace_root", ""))).resolve() != workspace_root:
        raise ValueError("workspace snapshot does not match workspace root")
    encoded = json.dumps(states, sort_keys=True, separators=(",", ":")).encode()
    if snapshot.get("snapshot_id") != hashlib.sha256(encoded).hexdigest():
        raise ValueError("workspace snapshot identity is invalid")
    for repo_id, repository in repositories.items():
        state = states[repo_id]
        if not isinstance(state, Mapping) or state.get("path") != repository.path:
            raise ValueError(f"workspace snapshot does not match repository {repo_id}")
    return states


def _context(repository: ModuleConfig, index: Mapping[str, Any], record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "repo_id": repository.module_id,
        "snapshot_identity": index["snapshot_identity"],
        "service_id": repository.service_id,
        "source": {
            key: record[key]
            for key in ("repo_id", "revision", "path", "pointer", "selection_reason", "sha256")
        },
    }


def _extract(view: source_views.SourceView, repository: ModuleConfig, index: Mapping[str, Any]) -> list[dict[str, Any]]:
    extractors: dict[str, Callable[[str, Mapping[str, Any]], Any]] = {
        "openapi-signature": openapi.extract_openapi,
        "asyncapi-signature": asyncapi.extract_asyncapi,
        "graphql-sdl-signature": graphql_sdl.extract_graphql_sdl,
        "kubernetes-signature": deployment.extract_deployment,
        "docker-compose-signature": deployment.extract_deployment,
    }
    results: list[dict[str, Any]] = []
    for record in index["selected_files"]:
        reason = record["selection_reason"]
        if reason not in extractors and reason not in {
            "helm-chart-signature", "maven-build-signature", "gradle-build-signature",
            "spring-configuration-signature",
        }:
            continue
        text = view.read_text(record["path"], locator.DEFAULT_BUDGET.structured_file_bytes)
        context = _context(repository, index, record)
        result = (
            deployment.extract_build_metadata(text, record["path"], context)
            if reason not in extractors
            else extractors[reason](text, context)
        )
        results.append(result.to_dict())
    return results


def _scan(arguments: argparse.Namespace) -> int:
    load_root = arguments.load_test_root.resolve(strict=True)
    if not load_root.is_dir():
        raise ValueError("load-test root must be a directory")
    manifest_path = _inside(load_root, arguments.manifest, must_exist=True)
    snapshot_path = _inside(load_root, arguments.workspace_snapshot, must_exist=True)
    run_dir = _inside(load_root, arguments.run_dir, must_exist=False)
    manifest = load_manifest(manifest_path)
    workspace_root = resolve_workspace_root(manifest_path, manifest.workspace_root)
    configured_load_root = _inside(
        workspace_root,
        workspace_root / manifest.load_test_module,
        must_exist=True,
        boundary="workspace",
    )
    if configured_load_root != load_root:
        raise ValueError("manifest does not select the supplied load-test root")
    snapshot = _mapping(snapshot_path, "workspace snapshot")
    states = _validate_snapshot(snapshot, manifest, workspace_root)

    results: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for repository in manifest.repositories:
        state = states[repository.module_id]
        if state.get("available") is False:
            if repository.required:
                raise ValueError(f"required repository is unavailable: {repository.module_id}")
            diagnostics.append({"repo_id": repository.module_id, "diagnostics": [{
                "code": "repository-unavailable", "message": "Optional repository was unavailable."
            }]})
            continue
        repository_root = _inside(
            workspace_root,
            workspace_root / repository.path,
            must_exist=True,
            boundary="workspace",
        )
        if repository_root == load_root:
            continue
        view = source_views.source_view(repository_root, state, run_dir.name)
        index = locator.locate_sources(
            view, repository, locator.DEFAULT_BUDGET, source_markers_enabled=False
        )
        contracts.write_json_atomic(
            run_dir / "discovery" / repository.module_id / "discovery-index.json", index
        )
        diagnostics.append({"repo_id": repository.module_id, "diagnostics": index["warnings"]})
        results.extend(_extract(view, repository, index))

    candidate = merge.merge_results(snapshot["snapshot_id"], results, diagnostics)
    contracts.write_json_atomic(run_dir / "surface-candidate.json", candidate)
    print(f"surface-candidate.json: {len(candidate['entities'])} entities; confirmation required")
    return 0


def _confirm(arguments: argparse.Namespace) -> int:
    load_root = arguments.load_test_root.resolve(strict=True)
    candidate = _mapping(_inside(load_root, arguments.candidate, must_exist=True), "surface candidate")
    decisions = _mapping(
        _inside(load_root, arguments.decisions, must_exist=True), "surface decisions", yaml_input=True
    )
    review = surface_review.apply_surface_decisions(candidate, decisions)
    output = _inside(load_root, arguments.out, must_exist=False)
    contracts.write_json_atomic(output, review)
    print(f"{output.name}: {len(review['included']) + len(review['added'])} included")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        return _scan(arguments) if arguments.command == "scan" else _confirm(arguments)
    except (OSError, UnicodeError, ValueError, source_views.DiscoveryError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Safe, bounded preview discovery for sibling workspace modules."""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Collection
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _shared.common import run_command  # noqa: E402
from models import WorkspaceManifest


MARKERS = {
    "api-spec": ("openapi.yaml", "openapi.yml", "swagger.json"),
    "infrastructure": ("Chart.yaml", "terraform.tf", "kustomization.yaml"),
    "frontend": ("package.json",),
    "backend": ("pom.xml", "build.gradle", "build.gradle.kts"),
}


def ensure_inside(root: Path, candidate: Path) -> Path:
    """Resolve *candidate* and reject paths (including symlinks) outside *root*."""
    resolved_root = root.resolve(strict=True)
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"path resolves outside workspace: {candidate}") from exc
    return resolved


def _frontend_marker_applies(package_json: Path) -> bool:
    """Return whether the fixed package marker contains frontend build evidence."""
    try:
        contents = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return False
    if not isinstance(contents, dict):
        return False
    scripts = contents.get("scripts")
    if isinstance(scripts, dict) and "build" in scripts:
        return True
    for section in ("dependencies", "devDependencies", "peerDependencies"):
        dependencies = contents.get(section)
        if isinstance(dependencies, dict) and any(
            dependency in dependencies for dependency in ("react", "vue", "@angular/core")
        ):
            return True
    return False


def classification_evidence(root: Path, module: Path) -> list[str]:
    """Return only present fixed markers that support an advisory classification."""
    evidence: list[str] = []
    for kind, markers in MARKERS.items():
        for marker in markers:
            marker_path = ensure_inside(root, module / marker)
            if marker_path.is_file() and (
                kind != "frontend" or _frontend_marker_applies(marker_path)
            ):
                evidence.append(marker)
    return evidence


def classify_module(evidence: Collection[str]) -> str:
    """Classify a module from its fixed, advisory marker set."""
    evidence = set(evidence)
    for kind, markers in MARKERS.items():
        if any(marker in evidence for marker in markers):
            return kind
    return "other"


def discover_preview(root: Path, manifest: WorkspaceManifest, max_depth: int = 1) -> dict[str, Any]:
    """List depth-one Git siblings without changing the committed manifest."""
    if max_depth != 1:
        raise ValueError("MVP discovery depth is exactly 1")
    resolved_root = root.resolve(strict=True)
    confirmed = {module.path for module in manifest.modules}
    candidates: list[dict[str, Any]] = []
    for child in sorted(resolved_root.iterdir(), key=lambda path: path.name.lower()):
        if not child.is_dir() or not (child / ".git").exists():
            continue
        safe = ensure_inside(resolved_root, child)
        relative_path = safe.relative_to(resolved_root).as_posix()
        evidence = classification_evidence(resolved_root, safe)
        candidates.append({
            "path": relative_path,
            "suggested_kind": classify_module(evidence),
            "confirmation": "confirmed" if relative_path in confirmed else "required",
            "classification_evidence": evidence,
        })
    return {"version": 1, "candidates": candidates}

def git_state(path: Path) -> dict[str, Any]:
    """Return commit, branch, working-tree state, and origin for one module repository."""
    commands = {
        "commit": ["git", "rev-parse", "HEAD"],
        "branch": ["git", "branch", "--show-current"],
        "status": ["git", "status", "--porcelain"],
        "remote": ["git", "remote", "get-url", "origin"],
    }
    values: dict[str, str | None] = {}
    for key, args in commands.items():
        result = run_command(args, cwd=path, timeout=15)
        if result.returncode != 0 and key != "remote":
            raise ValueError(f"cannot read git {key} for {path}: {result.stderr.strip()}")
        values[key] = result.stdout.strip() if result.returncode == 0 else None
    return {
        "commit": values["commit"],
        "branch": values["branch"] or None,
        "dirty": bool(values["status"]),
        "remote": values["remote"],
    }


def require_dirty_policy(module_id: str, dirty: bool, policies: dict[str, str]) -> str:
    """Return the selected revision policy, requiring an explicit dirty choice."""
    if not dirty:
        return "clean"
    policy = policies.get(module_id)
    if policy not in {"working-tree", "HEAD"}:
        raise ValueError(f"dirty policy required for {module_id}")
    return policy


def build_snapshot(
    root: Path, manifest: WorkspaceManifest, dirty_policy: dict[str, str]
) -> dict[str, Any]:
    """Capture independent Git state for each confirmed manifest module."""
    modules: dict[str, dict[str, Any]] = {}
    for module in manifest.modules:
        path = ensure_inside(root, root / module.path)
        state = git_state(path)
        modules[module.module_id] = {
            **state,
            "path": module.path,
            "kind": module.kind,
            "dirty_policy": require_dirty_policy(module.module_id, state["dirty"], dirty_policy),
        }
    canonical = json.dumps(modules, sort_keys=True, separators=(",", ":")).encode()
    return {
        "version": 1,
        "snapshot_id": hashlib.sha256(canonical).hexdigest(),
        "workspace_root": str(root.resolve()),
        "modules": modules,
    }


def build_inspector_jobs(
    snapshot: dict[str, Any], manifest: WorkspaceManifest, run_dir: Path
) -> list[dict[str, Any]]:
    """Build content-free inspector envelopes for confirmed SUT modules only."""
    jobs: list[dict[str, Any]] = []
    by_id = {module.module_id: module for module in manifest.modules}
    root = Path(snapshot["workspace_root"])
    for module_id, state in sorted(snapshot["modules"].items()):
        module = by_id[module_id]
        if module.kind == "load-tests":
            continue
        module_path = ensure_inside(root, root / module.path)
        jobs.append({
            "module_id": module_id,
            "module_path": str(module_path),
            "kind": module.kind,
            "revision": state["commit"],
            "dirty_policy": state["dirty_policy"],
            "inspect": list(module.inspect),
            "exclude": list(module.exclude),
            "output": str(run_dir / "modules" / f"{module_id}-evidence.json"),
        })
    return jobs

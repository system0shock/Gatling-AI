"""Safe, bounded preview discovery for sibling workspace modules."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections.abc import Collection, Mapping, Sequence
from pathlib import Path, PurePosixPath
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


def _run_git_bytes(repo_root: Path, args: list[str]) -> bytes:
    """Run one Git command without a shell and return its unmodified stdout."""
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        timeout=15,
        check=False,
        shell=False,
    )
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"cannot fingerprint working tree for {repo_root}: {message}")
    return result.stdout


def _is_excluded(path: str, exclusions: Sequence[str]) -> bool:
    """Return whether a normalized relative path matches a manifest exclusion."""
    relative = PurePosixPath(path)
    for exclusion in exclusions:
        normalized = exclusion.replace("\\", "/").strip("/")
        if not normalized:
            continue
        if path == normalized or path.startswith(f"{normalized}/") or relative.match(normalized):
            return True
    return False


def working_tree_fingerprint(
    repo_root: Path, commit: str, exclusions: Sequence[str]
) -> str:
    """Hash raw tracked changes and excluded-filtered untracked file identities."""
    digest = hashlib.sha256()
    digest.update(_run_git_bytes(
        repo_root, ["diff", "--binary", "--no-ext-diff", commit, "--", "."]
    ))
    untracked_output = _run_git_bytes(
        repo_root, ["ls-files", "--others", "--exclude-standard", "-z"]
    )
    paths = sorted(
        path.decode("utf-8", errors="surrogateescape")
        for path in untracked_output.split(b"\0")
        if path
    )
    for relative in paths:
        normalized = PurePosixPath(relative).as_posix()
        if _is_excluded(normalized, exclusions):
            continue
        candidate = ensure_inside(repo_root, repo_root / Path(*PurePosixPath(normalized).parts))
        if not candidate.is_file():
            continue
        digest.update(b"\0path\0")
        digest.update(normalized.encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0sha256\0")
        digest.update(hashlib.sha256(candidate.read_bytes()).digest())
    return digest.hexdigest()


def snapshot_repositories(snapshot: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return the version-independent repository-state mapping."""
    key = "repositories" if snapshot.get("version") == 2 else "modules"
    value = snapshot.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"workspace snapshot has no {key} mapping")
    return value


def _unavailable_repository(module: Any) -> dict[str, Any]:
    """Build the normalized v2 record for one unavailable repository."""
    return {
        "available": False,
        "path": module.path,
        "roles": list(module.effective_roles),
        "service_id": module.service_id,
        "required": module.required,
        "inspect": list(module.inspect),
        "exclude": list(module.exclude),
        "error": "repository-unavailable",
        "severity": "blocking" if module.required else "warning",
    }


def build_snapshot(
    root: Path, manifest: WorkspaceManifest, dirty_policy: dict[str, str]
) -> dict[str, Any]:
    """Capture independent Git state for each confirmed manifest module."""
    modules: dict[str, dict[str, Any]] = {}
    for module in manifest.modules:
        path = ensure_inside(root, root / module.path)
        if manifest.version == 2 and not path.is_dir():
            modules[module.module_id] = _unavailable_repository(module)
            continue
        try:
            state = git_state(path)
        except (OSError, ValueError):
            if manifest.version != 2:
                raise
            modules[module.module_id] = _unavailable_repository(module)
            continue
        policy = require_dirty_policy(module.module_id, state["dirty"], dirty_policy)
        if manifest.version == 1:
            modules[module.module_id] = {
                **state,
                "path": module.path,
                "kind": module.kind,
                "dirty_policy": policy,
            }
            continue
        record = {
            "available": True,
            "path": module.path,
            "roles": list(module.effective_roles),
            "service_id": module.service_id,
            "required": module.required,
            "inspect": list(module.inspect),
            "exclude": list(module.exclude),
            **state,
            "dirty_policy": policy,
        }
        if policy == "working-tree":
            record["working_tree_fingerprint"] = working_tree_fingerprint(
                path, str(state["commit"]), module.exclude
            )
        modules[module.module_id] = record
    canonical = json.dumps(modules, sort_keys=True, separators=(",", ":")).encode()
    snapshot = {
        "version": 1,
        "snapshot_id": hashlib.sha256(canonical).hexdigest(),
        "workspace_root": str(root.resolve()),
        "modules": modules,
    }
    if manifest.version == 1:
        return snapshot
    return {
        "version": 2,
        "snapshot_id": snapshot["snapshot_id"],
        "workspace_root": snapshot["workspace_root"],
        "status": (
            "blocked"
            if any(not state["available"] and state["required"] for state in modules.values())
            else "complete"
        ),
        "repositories": modules,
    }


def build_inspector_jobs(
    snapshot: dict[str, Any], manifest: WorkspaceManifest, run_dir: Path
) -> list[dict[str, Any]]:
    """Build content-free inspector envelopes for confirmed SUT modules only."""
    jobs: list[dict[str, Any]] = []
    by_id = {module.module_id: module for module in manifest.modules}
    root = Path(snapshot["workspace_root"])
    for module_id, state in sorted(snapshot_repositories(snapshot).items()):
        module = by_id[module_id]
        if state.get("available") is False or module.primary_role == "load-tests":
            continue
        module_path = ensure_inside(root, root / module.path)
        jobs.append({
            "module_id": module_id,
            "module_path": str(module_path),
            "kind": module.primary_role,
            "revision": state["commit"],
            "dirty_policy": state["dirty_policy"],
            "inspect": list(module.inspect),
            "exclude": list(module.exclude),
            "output": str(run_dir / "modules" / f"{module_id}-evidence.json"),
        })
    return jobs

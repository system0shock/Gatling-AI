"""Safe, bounded preview discovery for sibling workspace modules."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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
    resolved = candidate.resolve(strict=True)
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


def classification_evidence(module: Path) -> list[str]:
    """Return only present fixed markers that support an advisory classification."""
    evidence: list[str] = []
    for kind, markers in MARKERS.items():
        for marker in markers:
            marker_path = module / marker
            if marker_path.is_file() and (kind != "frontend" or _frontend_marker_applies(marker_path)):
                evidence.append(marker)
    return evidence


def classify_module(module: Path) -> str:
    """Classify a module from its fixed, advisory marker set."""
    evidence = set(classification_evidence(module))
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
        evidence = classification_evidence(safe)
        candidates.append({
            "path": relative_path,
            "suggested_kind": classify_module(safe),
            "confirmation": "confirmed" if relative_path in confirmed else "required",
            "classification_evidence": evidence,
        })
    return {"version": 1, "candidates": candidates}

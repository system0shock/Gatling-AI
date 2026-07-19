#!/usr/bin/env python3
"""Command-line entry points for methodology workspace discovery."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

try:
    from .discovery import build_inspector_jobs, build_snapshot, discover_preview, ensure_inside
    from .models import load_manifest, resolve_workspace_root
except ImportError:
    from discovery import build_inspector_jobs, build_snapshot, discover_preview, ensure_inside
    from models import load_manifest, resolve_workspace_root


def build_parser() -> argparse.ArgumentParser:
    """Build the workspace discovery command-line parser."""
    parser = argparse.ArgumentParser(description="Discover methodology workspace modules")
    sub = parser.add_subparsers(dest="command", required=True)

    preview = sub.add_parser("preview")
    preview.add_argument("--manifest", required=True, type=Path)
    preview.add_argument("--out", required=True, type=Path)

    snapshot = sub.add_parser("snapshot")
    snapshot.add_argument("--manifest", required=True, type=Path)
    snapshot.add_argument("--run-dir", required=True, type=Path)
    snapshot.add_argument(
        "--dirty-policy",
        action="append",
        default=[],
        metavar="MODULE=working-tree|HEAD",
    )
    return parser


def parse_dirty_policies(values: list[str]) -> dict[str, str]:
    """Parse one explicit revision policy per dirty module."""
    policies: dict[str, str] = {}
    for value in values:
        module_id, separator, policy = value.partition("=")
        if not separator or not module_id or policy not in {"working-tree", "HEAD"}:
            raise ValueError(f"invalid dirty policy: {value!r}")
        if module_id in policies:
            raise ValueError(f"duplicate dirty policy for {module_id}")
        policies[module_id] = policy
    return policies


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Write stable UTF-8 JSON by replacing a temporary sibling file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    """Run preview or snapshot, returning 2 only for expected domain errors."""
    args = build_parser().parse_args(argv)
    try:
        manifest = load_manifest(args.manifest)
        root = resolve_workspace_root(args.manifest, manifest.workspace_root)
        if args.command == "preview":
            write_json_atomic(ensure_inside(root, args.out), discover_preview(root, manifest))
            return 0

        policies = parse_dirty_policies(args.dirty_policy)
        snapshot = build_snapshot(root, manifest, policies)
        run_dir = ensure_inside(root, args.run_dir)
        snapshot["inspector_jobs"] = build_inspector_jobs(snapshot, manifest, run_dir)
        write_json_atomic(run_dir / "workspace-snapshot.json", snapshot)
        return 0
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

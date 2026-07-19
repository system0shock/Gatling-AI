#!/usr/bin/env python3
"""Create and atomically apply approval-bound methodology patches."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


APPROVAL_VERSION = 1
APPROVAL_KINDS = frozenset({"workspace-manifest", "methodology-patch"})
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
HASH_FIELDS = ("base_sha256", "candidate_sha256", "patch_sha256")
TARGET_NAMES = {"workspace-manifest": "workspace.yaml", "methodology-patch": "methodology.md"}


@dataclass(frozen=True)
class PatchDescriptor:
    """Immutable hashes binding one candidate and patch to one base file."""

    kind: str
    base_path: str
    candidate_path: str
    base_sha256: str
    candidate_sha256: str
    patch_sha256: str


def sha256_path(path: Path, *, allow_missing: bool = False) -> str:
    """Return a file hash; only an explicitly allowed absent base is empty."""
    if not path.exists():
        if allow_missing:
            return EMPTY_SHA256
        raise FileNotFoundError(path)
    if not path.is_file():
        raise ValueError(f"expected a file: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_kind(kind: str) -> None:
    if kind not in APPROVAL_KINDS:
        choices = ", ".join(sorted(APPROVAL_KINDS))
        raise ValueError(f"unsupported approval kind {kind!r}; expected one of: {choices}")


def _require_target_name(kind: str, base: Path) -> None:
    expected = TARGET_NAMES[kind]
    if base.name != expected:
        raise ValueError(f"{kind} approvals require base target {expected}")


def _absolute_path(path: Path) -> Path:
    """Make an absolute lexical path without resolving links."""
    return Path(os.path.abspath(os.fspath(path)))


def _is_link_or_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    attributes = getattr(path.stat(), "st_file_attributes", 0)
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _assert_safe_containment(load_test_root: Path, path: Path) -> Path:
    """Confine a lexical path and reject all existing link/reparse components."""
    root = _absolute_path(load_test_root)
    target = _absolute_path(path)
    if not root.exists() or not root.is_dir():
        raise ValueError(f"configured load-test root must be an existing directory: {root}")
    try:
        relative = target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"path is outside the configured load-test root: {path}") from exc
    current = root
    if _is_link_or_reparse(current):
        raise ValueError(f"path contains a symlink or reparse point: {current}")
    for component in relative.parts:
        current = current / component
        if current.exists() and _is_link_or_reparse(current):
            raise ValueError(f"path contains a symlink or reparse point: {current}")
    return target


def _root_for(load_test_root: Path | None, base: Path) -> Path:
    return _absolute_path(load_test_root if load_test_root is not None else base.parent)


def _normalise_paths(load_test_root: Path | None, base: Path, *paths: Path) -> tuple[Path, ...]:
    root = _root_for(load_test_root, base)
    return (root, *(_assert_safe_containment(root, path) for path in (base, *paths)))


def _normalised_text(content: bytes) -> list[str]:
    return content.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n").splitlines(keepends=True)


def _patch_text(base: Path, candidate: Path) -> str:
    before = base.read_text(encoding="utf-8").splitlines(keepends=True) if base.exists() else []
    after = candidate.read_text(encoding="utf-8").splitlines(keepends=True)
    return "".join(difflib.unified_diff(before, after, fromfile=str(base), tofile=str(candidate)))


def _patch_text_from_bytes(base: Path, base_bytes: bytes, candidate: Path, candidate_bytes: bytes) -> str:
    return "".join(
        difflib.unified_diff(
            _normalised_text(base_bytes), _normalised_text(candidate_bytes),
            fromfile=str(base), tofile=str(candidate),
        )
    )


def _atomic_write_contained(load_test_root: Path, path: Path, content: bytes) -> None:
    """Replace a contained target after link/reparse checks immediately around replace.

    Portable Python cannot hold a directory descriptor for atomic replacement on every
    supported platform. Existing link/reparse components are rejected and checked again
    immediately before ``os.replace``; a hostile filesystem actor can still race after
    that final check, so the tool must run in a trusted load-test workspace.
    """
    target = _assert_safe_containment(load_test_root, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    _assert_safe_containment(load_test_root, target.parent)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
        _assert_safe_containment(load_test_root, target)
        os.replace(temporary_name, target)
    except BaseException:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
        raise


def atomic_write_text(path: Path, text: str) -> None:
    """Atomically replace a file with UTF-8 text without containment policy."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(text.encode("utf-8"))
        os.replace(temporary_name, path)
    except BaseException:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
        raise


def prepare(
    kind: str, base: Path, candidate: Path, patch: Path, *, load_test_root: Path | None = None
) -> PatchDescriptor:
    """Write a deterministic, root-contained patch and return its content binding."""
    _require_kind(kind)
    root, base_path, candidate_path, patch_path = _normalise_paths(load_test_root, base, candidate, patch)
    _require_target_name(kind, base_path)
    diff = _patch_text(base_path, candidate_path)
    _atomic_write_contained(root, patch_path, diff.encode("utf-8"))
    return PatchDescriptor(
        kind=kind,
        base_path=str(base_path),
        candidate_path=str(candidate_path),
        base_sha256=sha256_path(base_path, allow_missing=True),
        candidate_sha256=sha256_path(candidate_path),
        patch_sha256=sha256_path(patch_path),
    )


def descriptor_to_dict(descriptor: PatchDescriptor) -> dict[str, str]:
    """Serialize a descriptor with stable field names for the CLI."""
    return asdict(descriptor)


def descriptor_from_dict(value: Mapping[str, Any]) -> PatchDescriptor:
    """Deserialize a CLI descriptor after validating its exact shape."""
    expected = {"kind", "base_path", "candidate_path", *HASH_FIELDS}
    if set(value) != expected:
        raise ValueError("descriptor fields are invalid")
    if not all(isinstance(value[name], str) and value[name] for name in expected):
        raise ValueError("descriptor values must be non-empty strings")
    _require_kind(value["kind"])
    return PatchDescriptor(**dict(value))


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def record_approval(
    descriptor: PatchDescriptor, approved_by: str, out: Path, *, load_test_root: Path | None = None
) -> dict[str, Any]:
    """Record an explicit, root-contained approval for one prepared descriptor."""
    descriptor = descriptor_from_dict(descriptor_to_dict(descriptor))
    root, base_path, candidate_path, out_path = _normalise_paths(
        load_test_root, Path(descriptor.base_path), Path(descriptor.candidate_path), out
    )
    _require_target_name(descriptor.kind, base_path)
    if not isinstance(approved_by, str) or not approved_by.strip():
        raise ValueError("approved_by must be a non-empty string")
    approval: dict[str, Any] = {
        "version": APPROVAL_VERSION,
        "kind": descriptor.kind,
        "base_sha256": descriptor.base_sha256,
        "candidate_sha256": descriptor.candidate_sha256,
        "patch_sha256": descriptor.patch_sha256,
        "approved_by": approved_by,
        "approved_at": _utc_now(),
    }
    _validate_approval_shape(approval)
    _atomic_write_contained(root, out_path, (json.dumps(approval, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return approval


def _validate_approval_shape(approval: Mapping[str, Any]) -> None:
    expected = {"version", "kind", *HASH_FIELDS, "approved_by", "approved_at"}
    if set(approval) != expected:
        raise ValueError("approval fields are invalid")
    if approval["version"] != APPROVAL_VERSION or isinstance(approval["version"], bool):
        raise ValueError("approval version is invalid")
    _require_kind(approval["kind"])
    for field in HASH_FIELDS:
        value = approval[field]
        if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError(f"{field} is invalid")
    if not isinstance(approval["approved_by"], str) or not approval["approved_by"].strip():
        raise ValueError("approved_by is invalid")
    timestamp = approval["approved_at"]
    if not isinstance(timestamp, str) or re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z", timestamp
    ) is None:
        raise ValueError("approved_at must be an RFC3339 UTC datetime")
    try:
        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("approved_at must be an RFC3339 UTC datetime") from exc


def validate_approval(base: Path, candidate: Path, patch: Path, approval: Mapping[str, Any]) -> None:
    """Reject approvals not bound to the current base, candidate, and patch."""
    _validate_approval_shape(approval)
    base_path, candidate_path, patch_path = map(_absolute_path, (base, candidate, patch))
    _require_target_name(approval["kind"], base_path)
    actual = {
        "base_sha256": sha256_path(base_path, allow_missing=True),
        "candidate_sha256": sha256_path(candidate_path),
        "patch_sha256": sha256_path(patch_path),
    }
    for field in HASH_FIELDS:
        if actual[field] != approval[field]:
            raise ValueError(f"{field} does not match the approved content")
    fresh_hash = hashlib.sha256(_patch_text(base_path, candidate_path).encode("utf-8")).hexdigest()
    if fresh_hash != approval["patch_sha256"]:
        raise ValueError("patch_sha256 does not match a fresh base-to-candidate diff")


def _load_approval(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("approval must be a JSON object")
    return value


def _current_hashes(base: Path, candidate: Path, patch: Path) -> tuple[dict[str, str], bytes, bytes]:
    base_bytes = base.read_bytes() if base.exists() else b""
    candidate_bytes = candidate.read_bytes()
    patch_bytes = patch.read_bytes()
    return (
        {
            "base_sha256": hashlib.sha256(base_bytes).hexdigest(),
            "candidate_sha256": hashlib.sha256(candidate_bytes).hexdigest(),
            "patch_sha256": hashlib.sha256(patch_bytes).hexdigest(),
        },
        base_bytes,
        candidate_bytes,
    )


def apply_approved_candidate(
    base: Path,
    candidate: Path,
    patch: Path,
    approval_path: Path,
    *,
    load_test_root: Path | None = None,
    before_replace: Callable[[], None] | None = None,
) -> None:
    """Atomically install only a currently approved, root-contained candidate.

    ``before_replace`` is a deterministic test hook used to prove the final
    revalidation window; production callers must leave it unset.
    """
    root, base_path, candidate_path, patch_path, approval_file = _normalise_paths(
        load_test_root, base, candidate, patch, approval_path
    )
    approval = _load_approval(approval_file)
    validate_approval(base_path, candidate_path, patch_path, approval)
    if before_replace is not None:
        before_replace()

    # Revalidate containment and every approved input immediately before writing.
    root, base_path, candidate_path, patch_path, approval_file = _normalise_paths(
        root, base_path, candidate_path, patch_path, approval_file
    )
    _require_target_name(approval["kind"], base_path)
    current, base_bytes, candidate_bytes = _current_hashes(base_path, candidate_path, patch_path)
    for field in HASH_FIELDS:
        if current[field] != approval[field]:
            raise ValueError(f"{field} changed before atomic apply")
    fresh_hash = hashlib.sha256(
        _patch_text_from_bytes(base_path, base_bytes, candidate_path, candidate_bytes).encode("utf-8")
    ).hexdigest()
    if fresh_hash != approval["patch_sha256"]:
        raise ValueError("patch_sha256 changed before atomic apply")
    _atomic_write_contained(root, base_path, candidate_bytes)


def _print_json(value: Mapping[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for the approval lifecycle."""
    parser = argparse.ArgumentParser(description="Prepare and apply approval-bound methodology patches")
    subcommands = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subcommands.add_parser("prepare")
    prepare_parser.add_argument("--kind", choices=sorted(APPROVAL_KINDS), required=True)
    prepare_parser.add_argument("--base", type=Path, required=True)
    prepare_parser.add_argument("--candidate", type=Path, required=True)
    prepare_parser.add_argument("--patch", type=Path, required=True)
    prepare_parser.add_argument("--out", type=Path, required=True, help="descriptor JSON output")
    prepare_parser.add_argument("--load-test-root", type=Path, required=True)

    record_parser = subcommands.add_parser("record-approval")
    record_parser.add_argument("--descriptor", type=Path, required=True)
    record_parser.add_argument("--approved-by", required=True)
    record_parser.add_argument("--out", type=Path, required=True)
    record_parser.add_argument("--load-test-root", type=Path, required=True)

    apply_parser = subcommands.add_parser("apply")
    apply_parser.add_argument("--base", type=Path, required=True)
    apply_parser.add_argument("--candidate", type=Path, required=True)
    apply_parser.add_argument("--patch", type=Path, required=True)
    apply_parser.add_argument("--approval", type=Path, required=True)
    apply_parser.add_argument("--load-test-root", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run a lifecycle command, returning 2 for expected domain errors."""
    args = build_parser().parse_args(argv)
    try:
        if args.command == "prepare":
            descriptor = prepare(args.kind, args.base, args.candidate, args.patch, load_test_root=args.load_test_root)
            payload = descriptor_to_dict(descriptor)
            root, _, out_path = _normalise_paths(args.load_test_root, args.base, args.out)
            _atomic_write_contained(root, out_path, (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
            _print_json(payload)
            return 0
        if args.command == "record-approval":
            descriptor = descriptor_from_dict(json.loads(args.descriptor.read_text(encoding="utf-8")))
            _print_json(record_approval(descriptor, args.approved_by, args.out, load_test_root=args.load_test_root))
            return 0
        apply_approved_candidate(
            args.base, args.candidate, args.patch, args.approval, load_test_root=args.load_test_root
        )
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

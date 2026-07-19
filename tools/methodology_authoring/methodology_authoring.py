#!/usr/bin/env python3
"""Create and atomically apply approval-bound methodology patches."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


APPROVAL_VERSION = 1
APPROVAL_KINDS = frozenset({"workspace-manifest", "methodology-patch"})
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
HASH_FIELDS = ("base_sha256", "candidate_sha256", "patch_sha256")


@dataclass(frozen=True)
class PatchDescriptor:
    """Immutable hashes binding one candidate and patch to one base file."""

    kind: str
    base_path: str
    candidate_path: str
    base_sha256: str
    candidate_sha256: str
    patch_sha256: str


def sha256_path(path: Path) -> str:
    """Return a file hash, treating an absent base file as empty bytes."""
    if not path.exists():
        return EMPTY_SHA256
    if not path.is_file():
        raise ValueError(f"expected a file: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_write_text(path: Path, text: str) -> None:
    """Atomically replace *path* with UTF-8 text."""
    atomic_write_bytes(path, text.encode("utf-8"))


def atomic_write_bytes(path: Path, content: bytes) -> None:
    """Atomically replace *path* with exact bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
        os.replace(temporary_name, path)
    except BaseException:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
        raise


def _require_kind(kind: str) -> None:
    if kind not in APPROVAL_KINDS:
        choices = ", ".join(sorted(APPROVAL_KINDS))
        raise ValueError(f"unsupported approval kind {kind!r}; expected one of: {choices}")


def _patch_text(base: Path, candidate: Path) -> str:
    before = base.read_text(encoding="utf-8").splitlines(keepends=True) if base.exists() else []
    after = candidate.read_text(encoding="utf-8").splitlines(keepends=True)
    return "".join(difflib.unified_diff(before, after, fromfile=str(base), tofile=str(candidate)))


def _patch_text_from_bytes(base: Path, base_bytes: bytes, candidate: Path, candidate_bytes: bytes) -> str:
    return "".join(
        difflib.unified_diff(
            base_bytes.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n").splitlines(keepends=True),
            candidate_bytes.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n").splitlines(keepends=True),
            fromfile=str(base),
            tofile=str(candidate),
        )
    )


def prepare(kind: str, base: Path, candidate: Path, patch: Path) -> PatchDescriptor:
    """Write a deterministic unified patch and return its content binding."""
    _require_kind(kind)
    diff = _patch_text(base, candidate)
    atomic_write_text(patch, diff)
    return PatchDescriptor(
        kind=kind,
        base_path=str(base),
        candidate_path=str(candidate),
        base_sha256=sha256_path(base),
        candidate_sha256=sha256_path(candidate),
        patch_sha256=sha256_path(patch),
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


def record_approval(descriptor: PatchDescriptor, approved_by: str, out: Path) -> dict[str, Any]:
    """Record an explicit approval for exactly one prepared descriptor."""
    _require_kind(descriptor.kind)
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
    atomic_write_text(out, json.dumps(approval, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
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
    if not isinstance(timestamp, str) or not timestamp.endswith("Z"):
        raise ValueError("approved_at must be UTC")
    try:
        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("approved_at is invalid") from exc


def validate_approval(base: Path, candidate: Path, patch: Path, approval: Mapping[str, Any]) -> None:
    """Reject approvals not bound to the current base, candidate, and patch."""
    _validate_approval_shape(approval)
    actual = {
        "base_sha256": sha256_path(base),
        "candidate_sha256": sha256_path(candidate),
        "patch_sha256": sha256_path(patch),
    }
    for field in HASH_FIELDS:
        if actual[field] != approval[field]:
            raise ValueError(f"{field} does not match the approved content")
    fresh_hash = hashlib.sha256(_patch_text(base, candidate).encode("utf-8")).hexdigest()
    if fresh_hash != approval["patch_sha256"]:
        raise ValueError("patch_sha256 does not match a fresh base-to-candidate diff")


def _ensure_inside(load_test_root: Path, path: Path) -> Path:
    root = load_test_root.resolve()
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"path is outside the configured load-test root: {path}") from exc
    return resolved


def _load_approval(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("approval must be a JSON object")
    return value


def apply_approved_candidate(
    base: Path,
    candidate: Path,
    patch: Path,
    approval_path: Path,
    *,
    load_test_root: Path | None = None,
) -> None:
    """Atomically install only the candidate described by the current approval."""
    root = load_test_root if load_test_root is not None else base.parent
    _ensure_inside(root, base)
    _ensure_inside(root, candidate)
    approval = _load_approval(approval_path)
    validate_approval(base, candidate, patch, approval)

    base_bytes = base.read_bytes() if base.exists() else b""
    candidate_bytes = candidate.read_bytes()
    current = {
        "base_sha256": hashlib.sha256(base_bytes).hexdigest(),
        "candidate_sha256": hashlib.sha256(candidate_bytes).hexdigest(),
        "patch_sha256": hashlib.sha256(
            _patch_text_from_bytes(base, base_bytes, candidate, candidate_bytes).encode("utf-8")
        ).hexdigest(),
    }
    for field in HASH_FIELDS:
        if current[field] != approval[field]:
            raise ValueError(f"{field} changed before atomic apply")
    atomic_write_bytes(base, candidate_bytes)


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

    record_parser = subcommands.add_parser("record-approval")
    record_parser.add_argument("--descriptor", type=Path, required=True)
    record_parser.add_argument("--approved-by", required=True)
    record_parser.add_argument("--out", type=Path, required=True)

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
            descriptor = prepare(args.kind, args.base, args.candidate, args.patch)
            payload = descriptor_to_dict(descriptor)
            atomic_write_text(args.out, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            _print_json(payload)
            return 0
        if args.command == "record-approval":
            descriptor = descriptor_from_dict(json.loads(args.descriptor.read_text(encoding="utf-8")))
            _print_json(record_approval(descriptor, args.approved_by, args.out))
            return 0
        apply_approved_candidate(
            args.base, args.candidate, args.patch, args.approval, load_test_root=args.load_test_root
        )
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=os.sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


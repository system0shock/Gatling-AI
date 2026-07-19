import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import difflib
import hashlib
import json
from pathlib import Path
import sys


@dataclass(frozen=True)
class PublishDescriptor:
    page_id: str
    expected_page_version: int
    methodology_sha256: str
    patch_sha256: str


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_string(mapping: dict, key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value


def require_int(mapping: dict, key: str) -> int:
    value = mapping.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{key} must be a positive integer")
    return value


def write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def descriptor_from_mapping(mapping: dict) -> PublishDescriptor:
    return PublishDescriptor(
        page_id=require_string(mapping, "page_id"),
        expected_page_version=require_int(mapping, "expected_page_version"),
        methodology_sha256=require_string(mapping, "methodology_sha256"),
        patch_sha256=require_string(mapping, "patch_sha256"),
    )


def prepare_publish(methodology: Path, page_snapshot: dict, out_dir: Path) -> PublishDescriptor:
    page_id = require_string(page_snapshot, "page_id")
    version = require_int(page_snapshot, "version")
    before = require_string(page_snapshot, "body_markdown")
    after = methodology.read_text(encoding="utf-8")
    patch_text = "".join(difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"confluence:{page_id}@{version}",
        tofile=str(methodology),
    ))
    out_dir.mkdir(parents=True, exist_ok=True)
    patch_path = out_dir / "confluence.patch"
    patch_path.write_text(patch_text, encoding="utf-8")
    descriptor = PublishDescriptor(
        page_id=page_id,
        expected_page_version=version,
        methodology_sha256=sha256_path(methodology),
        patch_sha256=sha256_path(patch_path),
    )
    write_json(out_dir / "publish-descriptor.json", asdict(descriptor))
    return descriptor


def record_publish_approval(
    descriptor: PublishDescriptor, approved_by: str, out: Path
) -> dict:
    if not approved_by.strip():
        raise ValueError("approved_by must be non-empty")
    approval = {
        **asdict(descriptor),
        "approved_by": approved_by,
        "approved_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    write_json(out, approval)
    return approval


def validate_publish(
    methodology: Path, fresh_page_snapshot: dict, approval_path: Path
) -> PublishDescriptor:
    approval = json.loads(approval_path.read_text(encoding="utf-8"))
    descriptor = descriptor_from_mapping(approval)
    if sha256_path(methodology) != descriptor.methodology_sha256:
        raise ValueError("local methodology changed after approval")
    if require_string(fresh_page_snapshot, "page_id") != descriptor.page_id:
        raise ValueError("target page changed")
    if require_int(fresh_page_snapshot, "version") != descriptor.expected_page_version:
        raise ValueError("page version changed after approval")
    return descriptor


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare and validate MNT publication")
    commands = parser.add_subparsers(dest="command", required=True)

    prepare = commands.add_parser("prepare")
    prepare.add_argument("--methodology", required=True)
    prepare.add_argument("--page-snapshot", required=True)
    prepare.add_argument("--out-dir", required=True)

    approve = commands.add_parser("approve")
    approve.add_argument("--descriptor", required=True)
    approve.add_argument("--approved-by", required=True)
    approve.add_argument("--out", required=True)

    validate = commands.add_parser("validate")
    validate.add_argument("--methodology", required=True)
    validate.add_argument("--page-snapshot", required=True)
    validate.add_argument("--approval", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "prepare":
            prepare_publish(Path(args.methodology), read_json(Path(args.page_snapshot)), Path(args.out_dir))
        elif args.command == "approve":
            descriptor = descriptor_from_mapping(read_json(Path(args.descriptor)))
            record_publish_approval(descriptor, args.approved_by, Path(args.out))
        else:
            validate_publish(
                Path(args.methodology),
                read_json(Path(args.page_snapshot)),
                Path(args.approval),
            )
    except (FileNotFoundError, ValueError, json.JSONDecodeError):
        print("error: publish guard failed", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

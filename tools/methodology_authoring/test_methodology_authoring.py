"""Behavior tests for approval-bound methodology patches."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import methodology_authoring as authoring


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "methodology_authoring" / "methodology_authoring.py"


class ApprovalTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / ".tmp")
        root = Path(self.temp.name)
        self.base = root / "methodology.md"
        self.candidate = root / "methodology.candidate.md"
        self.patch = root / "methodology.patch"
        self.approval = root / "approval.json"
        self.missing = root / "missing-approval.json"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_patch_is_stable_and_bound_to_base_and_candidate(self) -> None:
        self.base.write_text("# MNT\nold\n", encoding="utf-8")
        self.candidate.write_text("# MNT\nnew\n", encoding="utf-8")
        descriptor = authoring.prepare("methodology-patch", self.base, self.candidate, self.patch)
        self.assertEqual(descriptor.patch_sha256, authoring.sha256_path(self.patch))
        self.assertIn("-old", self.patch.read_text(encoding="utf-8"))
        self.assertIn("+new", self.patch.read_text(encoding="utf-8"))

    def test_missing_base_uses_empty_byte_hash(self) -> None:
        self.candidate.write_text("# MNT\n", encoding="utf-8")
        descriptor = authoring.prepare("methodology-patch", self.base, self.candidate, self.patch)
        self.assertEqual(descriptor.base_sha256, hashlib.sha256(b"").hexdigest())

    def test_changed_base_invalidates_approval(self) -> None:
        self.base.write_text("# MNT\nold\n", encoding="utf-8")
        self.candidate.write_text("# MNT\nnew\n", encoding="utf-8")
        descriptor = authoring.prepare("methodology-patch", self.base, self.candidate, self.patch)
        approval = authoring.record_approval(descriptor, "v.salnikov", self.approval)
        self.base.write_text("concurrent edit", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "base_sha256"):
            authoring.validate_approval(self.base, self.candidate, self.patch, approval)

    def test_changed_candidate_invalidates_approval(self) -> None:
        self.base.write_text("old\n", encoding="utf-8")
        self.candidate.write_text("new\n", encoding="utf-8")
        approval = authoring.record_approval(
            authoring.prepare("methodology-patch", self.base, self.candidate, self.patch),
            "v.salnikov", self.approval,
        )
        self.candidate.write_text("different\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "candidate_sha256"):
            authoring.validate_approval(self.base, self.candidate, self.patch, approval)

    def test_changed_patch_invalidates_approval(self) -> None:
        self.base.write_text("old\n", encoding="utf-8")
        self.candidate.write_text("new\n", encoding="utf-8")
        approval = authoring.record_approval(
            authoring.prepare("methodology-patch", self.base, self.candidate, self.patch),
            "v.salnikov", self.approval,
        )
        self.patch.write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "patch_sha256"):
            authoring.validate_approval(self.base, self.candidate, self.patch, approval)

    def test_apply_without_approval_does_not_change_base(self) -> None:
        self.base.write_bytes(b"old\n")
        self.candidate.write_bytes(b"new\n")
        before = self.base.read_bytes()
        with self.assertRaises(FileNotFoundError):
            authoring.apply_approved_candidate(self.base, self.candidate, self.patch, self.missing)
        self.assertEqual(self.base.read_bytes(), before)

    def test_workspace_manifest_uses_a_distinct_approval_kind(self) -> None:
        self.base.write_text("modules: []\n", encoding="utf-8")
        self.candidate.write_text("modules:\n  - id: orders\n", encoding="utf-8")
        descriptor = authoring.prepare("workspace-manifest", self.base, self.candidate, self.patch)
        approval = authoring.record_approval(descriptor, "v.salnikov", self.approval)
        self.assertEqual(approval["kind"], "workspace-manifest")
        authoring.apply_approved_candidate(self.base, self.candidate, self.patch, self.approval)
        self.assertEqual(self.base.read_bytes(), self.candidate.read_bytes())

    def test_apply_rejects_candidate_outside_configured_load_test_root(self) -> None:
        root = self.base.parent / "load-tests"
        root.mkdir()
        base = root / "methodology.md"
        base.write_text("old\n", encoding="utf-8")
        self.candidate.write_text("new\n", encoding="utf-8")
        descriptor = authoring.prepare("methodology-patch", base, self.candidate, self.patch)
        authoring.record_approval(descriptor, "v.salnikov", self.approval)
        with self.assertRaisesRegex(ValueError, "load-test root"):
            authoring.apply_approved_candidate(
                base, self.candidate, self.patch, self.approval, load_test_root=root
            )
        self.assertEqual(base.read_text(encoding="utf-8"), "old\n")

    def test_cli_prepare_record_approval_and_apply(self) -> None:
        self.base.write_text("old\n", encoding="utf-8")
        self.candidate.write_text("new\n", encoding="utf-8")
        descriptor = self.base.parent / "descriptor.json"
        prepare = self._cli(
            "prepare", "--kind", "methodology-patch", "--base", str(self.base),
            "--candidate", str(self.candidate), "--patch", str(self.patch), "--out", str(descriptor),
        )
        self.assertEqual(prepare.returncode, 0, prepare.stderr)
        record = self._cli(
            "record-approval", "--descriptor", str(descriptor), "--approved-by", "v.salnikov",
            "--out", str(self.approval),
        )
        self.assertEqual(record.returncode, 0, record.stderr)
        apply = self._cli(
            "apply", "--base", str(self.base), "--candidate", str(self.candidate),
            "--patch", str(self.patch), "--approval", str(self.approval),
            "--load-test-root", str(self.base.parent),
        )
        self.assertEqual(apply.returncode, 0, apply.stderr)
        self.assertEqual(self.base.read_text(encoding="utf-8"), "new\n")

    def test_cli_apply_reports_domain_errors_with_exit_two(self) -> None:
        self.base.write_text("old\n", encoding="utf-8")
        self.candidate.write_text("new\n", encoding="utf-8")
        completed = self._cli(
            "apply", "--base", str(self.base), "--candidate", str(self.candidate),
            "--patch", str(self.patch), "--approval", str(self.missing),
            "--load-test-root", str(self.base.parent),
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("missing-approval.json", completed.stderr)
        self.assertEqual(self.base.read_text(encoding="utf-8"), "old\n")

    def _cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args], cwd=ROOT, text=True,
            capture_output=True, check=False,
        )


if __name__ == "__main__":
    unittest.main()


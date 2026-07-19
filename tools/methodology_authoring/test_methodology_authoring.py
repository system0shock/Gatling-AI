"""Behavior tests for approval-bound methodology patches."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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
        base = self.base.parent / "workspace.yaml"
        candidate = self.base.parent / "workspace.candidate.yaml"
        base.write_text("modules: []\n", encoding="utf-8")
        candidate.write_text("modules:\n  - id: orders\n", encoding="utf-8")
        descriptor = authoring.prepare("workspace-manifest", base, candidate, self.patch)
        approval = authoring.record_approval(descriptor, "v.salnikov", self.approval)
        self.assertEqual(approval["kind"], "workspace-manifest")
        authoring.apply_approved_candidate(base, candidate, self.patch, self.approval)
        self.assertEqual(base.read_bytes(), candidate.read_bytes())
    def test_apply_rejects_candidate_outside_configured_load_test_root(self) -> None:
        root = self.base.parent / "load-tests"
        root.mkdir()
        base = root / "methodology.md"
        base.write_text("old\n", encoding="utf-8")
        self.candidate.write_text("new\n", encoding="utf-8")
        descriptor = authoring.prepare("methodology-patch", base, self.candidate, self.patch, load_test_root=self.base.parent)
        authoring.record_approval(descriptor, "v.salnikov", self.approval, load_test_root=self.base.parent)
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
            "--load-test-root", str(self.base.parent),
        )
        self.assertEqual(prepare.returncode, 0, prepare.stderr)
        record = self._cli(
            "record-approval", "--descriptor", str(descriptor), "--approved-by", "v.salnikov",
            "--out", str(self.approval), "--load-test-root", str(self.base.parent),
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



class ApprovalHardeningTest(ApprovalTest):
    def test_missing_candidate_and_patch_are_not_empty_hashes(self) -> None:
        self.base.write_text("old\n", encoding="utf-8")
        with self.assertRaises(FileNotFoundError):
            authoring.sha256_path(self.candidate)
        self.candidate.write_text("new\n", encoding="utf-8")
        approval = authoring.record_approval(
            authoring.prepare("methodology-patch", self.base, self.candidate, self.patch),
            "v.salnikov", self.approval,
        )
        self.patch.unlink()
        with self.assertRaises(FileNotFoundError):
            authoring.validate_approval(self.base, self.candidate, self.patch, approval)

    def test_kind_is_bound_to_its_base_filename(self) -> None:
        self.base.write_text("old\n", encoding="utf-8")
        self.candidate.write_text("new\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "workspace.yaml"):
            authoring.prepare("workspace-manifest", self.base, self.candidate, self.patch)
        workspace = self.base.parent / "workspace.yaml"
        workspace_candidate = self.base.parent / "workspace.candidate.yaml"
        workspace.write_text("old\n", encoding="utf-8")
        workspace_candidate.write_text("new\n", encoding="utf-8")
        descriptor = authoring.prepare("workspace-manifest", workspace, workspace_candidate, self.patch)
        approval = authoring.record_approval(descriptor, "v.salnikov", self.approval)
        approval["kind"] = "methodology-patch"
        with self.assertRaisesRegex(ValueError, "methodology.md"):
            authoring.validate_approval(workspace, workspace_candidate, self.patch, approval)

    def test_prepare_and_record_reject_writes_outside_load_test_root(self) -> None:
        root = self.base.parent / "load-tests"
        root.mkdir()
        base = root / "methodology.md"
        candidate = root / "methodology.candidate.md"
        base.write_text("old\n", encoding="utf-8")
        candidate.write_text("new\n", encoding="utf-8")
        outside_patch = self.base.parent / "outside.patch"
        with self.assertRaisesRegex(ValueError, "load-test root"):
            authoring.prepare("methodology-patch", base, candidate, outside_patch, load_test_root=root)
        descriptor = authoring.prepare("methodology-patch", base, candidate, root / "methodology.patch", load_test_root=root)
        with self.assertRaisesRegex(ValueError, "load-test root"):
            authoring.record_approval(descriptor, "v.salnikov", self.approval, load_test_root=root)

    def test_approval_timestamp_requires_rfc3339_utc_datetime(self) -> None:
        self.base.write_text("old\n", encoding="utf-8")
        self.candidate.write_text("new\n", encoding="utf-8")
        approval = authoring.record_approval(
            authoring.prepare("methodology-patch", self.base, self.candidate, self.patch),
            "v.salnikov", self.approval,
        )
        approval["approved_at"] = "2026-07-19 12:00:00Z"
        with self.assertRaisesRegex(ValueError, "approved_at"):
            authoring.validate_approval(self.base, self.candidate, self.patch, approval)

    def test_approval_timestamp_allows_rfc3339_utc_fractional_seconds(self) -> None:
        self.base.write_text("old\n", encoding="utf-8")
        self.candidate.write_text("new\n", encoding="utf-8")
        approval = authoring.record_approval(
            authoring.prepare("methodology-patch", self.base, self.candidate, self.patch),
            "v.salnikov", self.approval,
        )
        approval["approved_at"] = "2026-07-19T12:00:00.123Z"
        authoring.validate_approval(self.base, self.candidate, self.patch, approval)
    def test_pre_replace_base_edit_is_detected_before_overwrite(self) -> None:
        self.base.write_text("old\n", encoding="utf-8")
        self.candidate.write_text("approved\n", encoding="utf-8")
        descriptor = authoring.prepare("methodology-patch", self.base, self.candidate, self.patch)
        authoring.record_approval(descriptor, "v.salnikov", self.approval)

        def concurrent_edit() -> None:
            self.base.write_text("concurrent\n", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "base_sha256"):
            authoring.apply_approved_candidate(
                self.base, self.candidate, self.patch, self.approval,
                before_replace=concurrent_edit,
            )
        self.assertEqual(self.base.read_text(encoding="utf-8"), "concurrent\n")

    def test_pre_replace_revalidates_containment_after_attack_hook(self) -> None:
        self.base.write_text("old\n", encoding="utf-8")
        self.candidate.write_text("approved\n", encoding="utf-8")
        descriptor = authoring.prepare("methodology-patch", self.base, self.candidate, self.patch)
        authoring.record_approval(descriptor, "v.salnikov", self.approval)
        attacked = False
        original_guard = authoring._assert_safe_containment

        def attack() -> None:
            nonlocal attacked
            attacked = True

        def guard(root: Path, path: Path) -> Path:
            if attacked and path == self.base:
                raise ValueError("path contains a symlink or reparse point")
            return original_guard(root, path)

        with mock.patch.object(authoring, "_assert_safe_containment", side_effect=guard):
            with self.assertRaisesRegex(ValueError, "symlink or reparse"):
                authoring.apply_approved_candidate(
                    self.base, self.candidate, self.patch, self.approval,
                    before_replace=attack,
                )
        self.assertEqual(self.base.read_text(encoding="utf-8"), "old\n")

class ApprovalTransactionTest(ApprovalTest):
    def test_transaction_does_not_overwrite_concurrent_recreation(self) -> None:
        self.base.write_text("old\n", encoding="utf-8")
        self.candidate.write_text("approved\n", encoding="utf-8")
        approval = authoring.record_approval(
            authoring.prepare("methodology-patch", self.base, self.candidate, self.patch),
            "v.salnikov", self.approval,
        )

        def race(phase: str) -> None:
            if phase == "base-captured":
                self.base.write_text("concurrent\n", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "target was recreated"):
            authoring.apply_approved_candidate(
                self.base, self.candidate, self.patch, self.approval, transaction_hook=race
            )
        self.assertEqual(self.base.read_text(encoding="utf-8"), "concurrent\n")

    def test_transaction_applies_snapshotted_candidate_when_inputs_mutate(self) -> None:
        self.base.write_text("old\n", encoding="utf-8")
        self.candidate.write_bytes(b"approved\\r\\n")
        approval = authoring.record_approval(
            authoring.prepare("methodology-patch", self.base, self.candidate, self.patch),
            "v.salnikov", self.approval,
        )

        def mutate(phase: str) -> None:
            if phase == "inputs-snapshotted":
                self.candidate.write_bytes(b"mutated\\n")
                self.patch.write_text("mutated patch", encoding="utf-8")

        authoring.apply_approved_candidate(
            self.base, self.candidate, self.patch, self.approval, transaction_hook=mutate
        )
        self.assertEqual(self.base.read_bytes(), b"approved\\r\\n")


class ApprovalContainmentFilesystemTest(ApprovalTest):
    def test_prepare_rejects_real_symlink_component_when_platform_permits(self) -> None:
        root = self.base.parent / "load-tests"
        outside = self.base.parent / "outside"
        root.mkdir(); outside.mkdir()
        link = root / "linked"
        try:
            os.symlink(outside, link, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"symlink creation unavailable: {exc}")
        base = link / "methodology.md"
        candidate = root / "methodology.candidate.md"
        (outside / "methodology.md").write_text("old\n", encoding="utf-8")
        candidate.write_text("new\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "symlink or reparse"):
            authoring.prepare("methodology-patch", base, candidate, root / "methodology.patch", load_test_root=root)

if __name__ == "__main__":
    unittest.main()

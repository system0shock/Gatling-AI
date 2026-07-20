import json
from pathlib import Path
import shutil
import unittest

if __package__:
    from . import methodology_publish as publish
else:
    import methodology_publish as publish


class PublishGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).parent / ".test-fixtures" / self._testMethodName
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)
        self.methodology = self.root / "methodology.md"
        self.methodology.write_text("# MNT\n", encoding="utf-8")

    def snapshot(self, version: int = 7) -> dict:
        return {
            "page_id": "123",
            "version": version,
            "body_markdown": "# Existing MNT\n",
        }

    def researcher_snapshot(self, version: int = 7) -> dict:
        return {
            **self.snapshot(version),
            "fetched_at": "2026-07-20T10:00:00Z",
            "source_type": "confluence",
            "reference": "https://confluence.example.test/pages/123",
        }

    def approve(self) -> Path:
        descriptor = publish.prepare_publish(self.methodology, self.snapshot(), self.root)
        approval = self.root / "publish-approval.json"
        publish.record_publish_approval(descriptor, "v.salnikov", approval)
        return approval

    def test_happy_path_validates_fixed_page_and_local_hash(self) -> None:
        approval = self.approve()
        descriptor = publish.validate_publish(self.methodology, self.snapshot(), approval)
        self.assertEqual(descriptor.page_id, "123")
        self.assertTrue((self.root / "confluence.patch").is_file())

    def test_missing_approval_blocks(self) -> None:
        with self.assertRaises(FileNotFoundError):
            publish.validate_publish(self.methodology, self.snapshot(), self.root / "missing.json")

    def test_changed_local_methodology_blocks(self) -> None:
        approval = self.approve()
        self.methodology.write_text("# Changed MNT\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "local methodology changed"):
            publish.validate_publish(self.methodology, self.snapshot(), approval)

    def test_changed_page_version_blocks(self) -> None:
        approval = self.approve()
        with self.assertRaisesRegex(ValueError, "page version changed"):
            publish.validate_publish(self.methodology, self.snapshot(version=8), approval)

    def test_descriptor_is_not_a_publish_approval(self) -> None:
        publish.prepare_publish(self.methodology, self.snapshot(), self.root)
        with self.assertRaisesRegex(ValueError, "approved_by must be a non-empty string"):
            publish.validate_publish(
                self.methodology,
                self.snapshot(),
                self.root / "publish-descriptor.json",
            )

    def test_cli_prepare_approve_validate_happy_path(self) -> None:
        page_path = self.root / "page.json"
        page_path.write_text(json.dumps(self.snapshot()), encoding="utf-8")
        self.assertEqual(publish.main([
            "prepare", "--methodology", str(self.methodology),
            "--page-snapshot", str(page_path),
            "--out-dir", str(self.root),
        ]), 0)
        self.assertEqual(publish.main([
            "approve", "--descriptor", str(self.root / "publish-descriptor.json"),
            "--approved-by", "v.salnikov",
            "--out", str(self.root / "publish-approval.json"),
        ]), 0)
        self.assertEqual(publish.main([
            "validate", "--methodology", str(self.methodology),
            "--page-snapshot", str(page_path),
            "--approval", str(self.root / "publish-approval.json"),
        ]), 0)


    def test_cli_prepares_researcher_snapshot_and_validates_fresh_identity(self) -> None:
        page_path = self.root / "confluence-snapshot.json"
        page_path.write_text(json.dumps(self.researcher_snapshot()), encoding="utf-8")
        self.assertEqual(publish.main([
            "prepare", "--methodology", str(self.methodology),
            "--page-snapshot", str(page_path),
            "--out-dir", str(self.root),
        ]), 0)
        self.assertEqual(publish.main([
            "approve", "--descriptor", str(self.root / "publish-descriptor.json"),
            "--approved-by", "v.salnikov",
            "--out", str(self.root / "publish-approval.json"),
        ]), 0)
        self.assertEqual(publish.main([
            "validate", "--methodology", str(self.methodology),
            "--fresh-page-id", "123", "--fresh-page-version", "7",
            "--approval", str(self.root / "publish-approval.json"),
        ]), 0)

    def test_cli_rejects_missing_or_partial_fresh_identity(self) -> None:
        command = [
            "validate", "--methodology", str(self.methodology),
            "--approval", str(self.root / "publish-approval.json"),
        ]
        for fresh_args in ((), ("--fresh-page-id", "123"), ("--fresh-page-version", "7")):
            with self.subTest(fresh_args=fresh_args):
                self.assertEqual(publish.main(command + list(fresh_args)), 2)

    def test_cli_rejects_mixed_snapshot_and_fresh_identity(self) -> None:
        page_path = self.root / "page.json"
        page_path.write_text(json.dumps(self.snapshot()), encoding="utf-8")
        self.assertEqual(publish.main([
            "validate", "--methodology", str(self.methodology),
            "--page-snapshot", str(page_path),
            "--fresh-page-id", "123", "--fresh-page-version", "7",
            "--approval", str(self.root / "publish-approval.json"),
        ]), 2)

    def test_cli_rejects_missing_or_malformed_snapshot(self) -> None:
        page_path = self.root / "page.json"
        command = [
            "validate", "--methodology", str(self.methodology),
            "--page-snapshot", str(page_path),
            "--approval", str(self.root / "publish-approval.json"),
        ]
        self.assertEqual(publish.main(command), 2)
        page_path.write_text("not JSON", encoding="utf-8")
        self.assertEqual(publish.main(command), 2)


    def test_cli_rejects_array_snapshot_with_controlled_error(self) -> None:
        page_path = self.root / "page.json"
        page_path.write_text("[]", encoding="utf-8")
        self.assertEqual(publish.main([
            "prepare", "--methodology", str(self.methodology),
            "--page-snapshot", str(page_path),
            "--out-dir", str(self.root),
        ]), 2)


if __name__ == "__main__":
    unittest.main()

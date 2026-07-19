import json
from pathlib import Path
import shutil
import unittest

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


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Focused tests for the workspace manifest contract."""

from __future__ import annotations

from unittest.mock import patch
import tempfile
import unittest
from pathlib import Path

import models
import discovery
from fixtures import completed_git_outputs, manifest_object, module


class ManifestLoadTest(unittest.TestCase):
    def test_loads_relative_workspace_and_modules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            load_repo = root / "load-tests"
            system_dir = load_repo / "systems" / "SHOP"
            system_dir.mkdir(parents=True)
            manifest = system_dir / "workspace.yaml"
            manifest.write_text(
                """version: 1
system: SHOP
workspace_root: ../../..
load_test_module: load-tests
modules:
  - id: orders
    path: orders-backend
    kind: backend
    required: true
    inspect: [api, integrations]
write_policy:
  allowed_modules: [load-tests]
  sut_modules: read-only
""",
                encoding="utf-8",
            )
            loaded = models.load_manifest(manifest)
            self.assertEqual(loaded.system, "SHOP")
            self.assertEqual(loaded.modules[0].module_id, "orders")
            self.assertEqual(models.resolve_workspace_root(manifest, loaded.workspace_root), root)

    def test_rejects_absolute_module_path(self) -> None:
        doc = {
            "version": 1,
            "system": "SHOP",
            "workspace_root": ".",
            "load_test_module": "load-tests",
            "modules": [
                {
                    "id": "orders",
                    "path": str(Path.cwd().anchor + "outside"),
                    "kind": "backend",
                }
            ],
            "write_policy": {"allowed_modules": ["load-tests"], "sut_modules": "read-only"},
        }
        with self.assertRaisesRegex(ValueError, "relative"):
            models.parse_manifest(doc)

    def test_rejects_write_policy_that_allows_a_sut_module(self) -> None:
        doc = {
            "version": 1,
            "system": "SHOP",
            "workspace_root": ".",
            "load_test_module": "load-tests",
            "modules": [{"id": "orders", "path": "orders", "kind": "backend"}],
            "write_policy": {"allowed_modules": ["orders"], "sut_modules": "read-only"},
        }
        with self.assertRaisesRegex(ValueError, "load-test module"):
            models.parse_manifest(doc)

    def test_rejects_windows_non_relative_module_paths(self) -> None:
        for path in ("C:outside", r"\outside", r"C:\outside", r"\\server\share\outside"):
            with self.subTest(path=path):
                doc = {
                    "version": 1,
                    "system": "SHOP",
                    "workspace_root": ".",
                    "load_test_module": "load-tests",
                    "modules": [{"id": "orders", "path": path, "kind": "backend"}],
                    "write_policy": {"allowed_modules": ["load-tests"], "sut_modules": "read-only"},
                }
                with self.assertRaisesRegex(ValueError, "relative"):
                    models.parse_manifest(doc)

    def test_rejects_windows_non_relative_workspace_roots(self) -> None:
        for path in ("C:outside", r"\outside", r"C:\outside", r"\\server\share\outside"):
            with self.subTest(path=path):
                doc = {
                    "version": 1,
                    "system": "SHOP",
                    "workspace_root": path,
                    "load_test_module": "load-tests",
                    "modules": [{"id": "orders", "path": "orders", "kind": "backend"}],
                    "write_policy": {"allowed_modules": ["load-tests"], "sut_modules": "read-only"},
                }
                with self.assertRaisesRegex(ValueError, "relative"):

                    models.parse_manifest(doc)
class DiscoveryTest(unittest.TestCase):
    def test_preview_marks_unconfirmed_sibling_without_analyzing_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "load-tests" / ".git").mkdir(parents=True)
            (root / "orders" / ".git").mkdir(parents=True)
            (root / "orders" / "pom.xml").write_text("<project/>", encoding="utf-8")
            manifest = manifest_object(modules=[])

            preview = discovery.discover_preview(root, manifest)

            orders = next(item for item in preview["candidates"] if item["path"] == "orders")
            self.assertEqual(orders["confirmation"], "required")
            self.assertEqual(orders["suggested_kind"], "backend")

    def test_symlink_escape_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            link = Path(tmp) / "escape"
            try:
                link.symlink_to(Path(outside), target_is_directory=True)
            except OSError:
                self.skipTest("symlinks unavailable")

            with self.assertRaisesRegex(ValueError, "outside workspace"):
                discovery.ensure_inside(Path(tmp), link)

    def test_marker_paths_are_checked_against_workspace_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            module_path = root / "orders"
            module_path.mkdir()
            (module_path / "package.json").write_text('{"scripts": {"build": "vite build"}}', encoding="utf-8")

            with patch.object(discovery, "ensure_inside", side_effect=ValueError("outside workspace")):
                with self.assertRaisesRegex(ValueError, "outside workspace"):
                    discovery.classification_evidence(root, module_path)

    def test_preview_rejects_marker_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            module_path = root / "orders"
            (module_path / ".git").mkdir(parents=True)
            outside_marker = Path(outside) / "package.json"
            outside_marker.write_text('{"scripts": {"build": "vite build"}}', encoding="utf-8")
            try:
                (module_path / "package.json").symlink_to(outside_marker)
            except OSError:
                self.skipTest("symlinks unavailable")

            with self.assertRaisesRegex(ValueError, "outside workspace"):
                discovery.discover_preview(root, manifest_object(modules=[]))


class SnapshotTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "orders" / ".git").mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    @patch.object(discovery, "run_command")
    def test_snapshot_records_each_repo_independently(self, run) -> None:
        run.side_effect = completed_git_outputs(
            head="abc123\n", branch="main\n", status=" M app.py\n", remote="ssh://git/orders\n"
        )
        manifest = manifest_object(modules=[module("orders", "orders", "backend")])

        snapshot = discovery.build_snapshot(self.root, manifest, {"orders": "working-tree"})

        state = snapshot["modules"]["orders"]
        self.assertEqual(state["commit"], "abc123")
        self.assertTrue(state["dirty"])
        self.assertEqual(state["dirty_policy"], "working-tree")
        self.assertEqual(run.call_args_list[0].args[0], ["git", "rev-parse", "HEAD"])

    def test_dirty_module_without_policy_blocks(self) -> None:
        with self.assertRaisesRegex(ValueError, "dirty policy required"):
            discovery.require_dirty_policy("orders", True, {})

    def test_inspector_jobs_skip_load_tests_and_contain_only_envelope_fields(self) -> None:
        manifest = manifest_object(modules=[
            models.ModuleConfig(
                module_id="orders",
                path="orders",
                kind="backend",
                inspect=("api",),
                exclude=("generated",),
            ),
            module("load-tests", "load-tests", "load-tests"),
        ])
        snapshot = {
            "workspace_root": str(self.root),
            "modules": {
                "load-tests": {"commit": "test", "dirty_policy": "clean"},
                "orders": {"commit": "abc123", "dirty_policy": "HEAD"},
            },
        }

        jobs = discovery.build_inspector_jobs(snapshot, manifest, self.root / "run")

        self.assertEqual(jobs, [{
            "module_id": "orders",
            "module_path": str(self.root / "orders"),
            "kind": "backend",
            "revision": "abc123",
            "dirty_policy": "HEAD",
            "inspect": ["api"],
            "exclude": ["generated"],
            "output": str(self.root / "run" / "modules" / "orders-evidence.json"),
        }])

if __name__ == "__main__":
    unittest.main()

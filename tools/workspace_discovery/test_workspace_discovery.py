#!/usr/bin/env python3
"""Focused tests for the workspace manifest contract."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import models
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

if __name__ == "__main__":
    unittest.main()

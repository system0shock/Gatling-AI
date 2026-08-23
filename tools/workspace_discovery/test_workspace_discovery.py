#!/usr/bin/env python3
"""Focused tests for the workspace manifest contract."""

from __future__ import annotations

import hashlib
import json
import subprocess
from unittest.mock import patch
import sys
import tempfile
import unittest
from pathlib import Path

if __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

    from . import discovery, models
    from .fixtures import (
        completed_git_outputs,
        manifest_object,
        manifest_v1_document,
        manifest_v2_document,
        module,
    )
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

    import discovery
    import models
    from fixtures import (
        completed_git_outputs,
        manifest_object,
        manifest_v1_document,
        manifest_v2_document,
        module,
    )


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

    def test_v2_roles_are_open_and_required_defaults_true(self) -> None:
        manifest = models.parse_manifest(manifest_v2_document([{
            "id": "orders-contracts",
            "path": "orders-contracts",
            "roles": ["contracts", "team-specific-role"],
            "service_id": "orders",
        }]))

        repository = manifest.repositories[0]

        self.assertEqual(repository.roles, ("contracts", "team-specific-role"))
        self.assertEqual(repository.effective_roles, ("contracts", "team-specific-role"))
        self.assertEqual(repository.primary_role, "contracts")
        self.assertEqual(repository.service_id, "orders")
        self.assertTrue(repository.required)

    def test_v2_repository_without_roles_has_other_primary_role(self) -> None:
        manifest = models.parse_manifest(manifest_v2_document([{
            "id": "orders-data",
            "path": "orders-data",
        }]))

        repository = manifest.repositories[0]

        self.assertEqual(repository.roles, ())
        self.assertEqual(repository.effective_roles, ())
        self.assertEqual(repository.primary_role, "other")

    def test_v1_kind_maps_to_one_role_and_keeps_optional_default(self) -> None:
        manifest = models.parse_manifest(manifest_v1_document())

        repository = manifest.repositories[0]

        self.assertEqual(manifest.version, 1)
        self.assertIs(manifest.repositories, manifest.modules)
        self.assertEqual(repository.roles, ("backend",))
        self.assertEqual(repository.primary_role, "backend")
        self.assertFalse(repository.required)

    def test_module_config_keeps_existing_positional_arguments(self) -> None:
        repository = models.ModuleConfig("orders", "orders", "backend")

        self.assertEqual(repository.module_id, "orders")
        self.assertEqual(repository.path, "orders")
        self.assertEqual(repository.kind, "backend")

    def test_v2_rejects_duplicate_roles_and_duplicate_repository_ids(self) -> None:
        with self.assertRaises(ValueError):
            models.parse_manifest(manifest_v2_document([{
                "id": "orders-contracts",
                "path": "orders-contracts",
                "roles": ["contracts", "contracts"],
            }]))
        with self.assertRaisesRegex(ValueError, "repository id"):
            models.parse_manifest(manifest_v2_document([
                {"id": "orders", "path": "orders-api"},
                {"id": "orders", "path": "orders-backend"},
            ]))

    def test_v1_rejects_duplicate_module_ids(self) -> None:
        document = manifest_v1_document()
        document["modules"].append({"id": "orders", "path": "orders-copy", "kind": "backend"})

        with self.assertRaisesRegex(ValueError, "module id"):
            models.parse_manifest(document)

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

    @patch.object(discovery, "run_command")
    def test_v1_snapshot_shape_remains_unchanged(self, run) -> None:
        run.side_effect = completed_git_outputs(
            head="abc123\n", branch="main\n", status="\n", remote="ssh://git/orders\n"
        )
        manifest = manifest_object(modules=[module("orders", "orders", "backend")])

        snapshot = discovery.build_snapshot(self.root, manifest, {})

        modules = {
            "orders": {
                "branch": "main",
                "commit": "abc123",
                "dirty": False,
                "dirty_policy": "clean",
                "kind": "backend",
                "path": "orders",
                "remote": "ssh://git/orders",
            }
        }
        expected_id = hashlib.sha256(
            json.dumps(modules, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        self.assertEqual(snapshot, {
            "version": 1,
            "snapshot_id": expected_id,
            "workspace_root": str(self.root.resolve()),
            "modules": modules,
        })

    def test_v2_snapshot_records_unavailable_repositories_by_requiredness(self) -> None:
        manifest = models.parse_manifest(manifest_v2_document([
            {"id": "required-docs", "path": "required-docs", "roles": ["documentation"]},
            {
                "id": "optional-ui",
                "path": "optional-ui",
                "roles": ["frontend"],
                "required": False,
            },
        ]))

        snapshot = discovery.build_snapshot(self.root, manifest, {})

        expected_repositories = {
            "optional-ui": {
                "available": False,
                "error": "repository-unavailable",
                "exclude": [],
                "inspect": [],
                "path": "optional-ui",
                "required": False,
                "roles": ["frontend"],
                "service_id": None,
                "severity": "warning",
            },
            "required-docs": {
                "available": False,
                "error": "repository-unavailable",
                "exclude": [],
                "inspect": [],
                "path": "required-docs",
                "required": True,
                "roles": ["documentation"],
                "service_id": None,
                "severity": "blocking",
            },
        }
        expected_id = hashlib.sha256(
            json.dumps(expected_repositories, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        self.assertEqual(snapshot["status"], "blocked")
        self.assertEqual(snapshot["repositories"], expected_repositories)
        self.assertEqual(snapshot["snapshot_id"], expected_id)

    @patch.object(discovery, "run_command")
    def test_v2_available_snapshot_contains_normalized_repository_metadata(self, run) -> None:
        run.side_effect = completed_git_outputs(
            head="abc123\n", branch="main\n", status="\n", remote="ssh://git/orders\n"
        )
        manifest = models.parse_manifest(manifest_v2_document([{
            "id": "orders-contracts",
            "path": "orders",
            "roles": ["contracts", "custom-role"],
            "service_id": "orders",
            "inspect": ["api"],
            "exclude": ["generated"],
        }]))

        snapshot = discovery.build_snapshot(self.root, manifest, {})

        self.assertEqual(snapshot["version"], 2)
        self.assertEqual(snapshot["status"], "complete")
        self.assertEqual(snapshot["repositories"]["orders-contracts"], {
            "available": True,
            "branch": "main",
            "commit": "abc123",
            "dirty": False,
            "dirty_policy": "clean",
            "exclude": ["generated"],
            "inspect": ["api"],
            "path": "orders",
            "remote": "ssh://git/orders",
            "required": True,
            "roles": ["contracts", "custom-role"],
            "service_id": "orders",
        })

    def test_snapshot_repositories_accepts_both_versions_and_rejects_bad_shape(self) -> None:
        v1_modules = {"orders": {"commit": "abc"}}
        v2_repositories = {"orders": {"commit": "def"}}

        self.assertIs(
            discovery.snapshot_repositories({"version": 1, "modules": v1_modules}),
            v1_modules,
        )
        self.assertIs(
            discovery.snapshot_repositories({"version": 2, "repositories": v2_repositories}),
            v2_repositories,
        )
        with self.assertRaisesRegex(ValueError, "no repositories mapping"):
            discovery.snapshot_repositories({"version": 2, "repositories": []})

    def test_working_tree_fingerprint_tracks_binary_diff_and_untracked_content(self) -> None:
        repo = self.root / "fingerprint-repo"
        repo.mkdir()
        self._git(repo, "init")
        self._git(repo, "config", "user.email", "test@example.com")
        self._git(repo, "config", "user.name", "Workspace Test")
        tracked = repo / "tracked.bin"
        tracked.write_bytes(b"before\x00content")
        self._git(repo, "add", "tracked.bin")
        self._git(repo, "commit", "-m", "initial")
        commit = self._git(repo, "rev-parse", "HEAD").stdout.strip()

        initial = discovery.working_tree_fingerprint(repo, commit, ())
        tracked.write_bytes(b"after\x00content")
        tracked_change = discovery.working_tree_fingerprint(repo, commit, ())
        untracked = repo / "new.bin"
        untracked.write_bytes(b"one\x00")
        untracked_one = discovery.working_tree_fingerprint(repo, commit, ())
        untracked.write_bytes(b"two\x00")
        untracked_two = discovery.working_tree_fingerprint(repo, commit, ())

        self.assertNotEqual(initial, tracked_change)
        self.assertNotEqual(tracked_change, untracked_one)
        self.assertNotEqual(untracked_one, untracked_two)

    def test_working_tree_fingerprint_sorts_untracked_paths_and_applies_exclusions(self) -> None:
        repo = self.root / "excluded-repo"
        repo.mkdir()
        self._git(repo, "init")
        self._git(repo, "config", "user.email", "test@example.com")
        self._git(repo, "config", "user.name", "Workspace Test")
        (repo / "tracked.txt").write_text("tracked", encoding="utf-8")
        self._git(repo, "add", "tracked.txt")
        self._git(repo, "commit", "-m", "initial")
        commit = self._git(repo, "rev-parse", "HEAD").stdout.strip()
        excluded = repo / "generated" / "ignored.txt"
        excluded.parent.mkdir()
        excluded.write_text("first", encoding="utf-8")

        before = discovery.working_tree_fingerprint(repo, commit, ("generated",))
        excluded.write_text("second", encoding="utf-8")
        after = discovery.working_tree_fingerprint(repo, commit, ("generated",))

        self.assertEqual(before, after)

    @patch.object(discovery, "run_command")
    @patch.object(discovery, "working_tree_fingerprint", return_value="f" * 64)
    def test_v2_working_tree_snapshot_stores_only_run_guard_fingerprint(
        self, fingerprint, run
    ) -> None:
        run.side_effect = completed_git_outputs(
            head="abc123\n", branch="main\n", status=" M app.py\n", remote="ssh://git/orders\n"
        )
        manifest = models.parse_manifest(manifest_v2_document([{
            "id": "orders",
            "path": "orders",
            "roles": ["backend"],
            "exclude": ["generated"],
        }]))

        snapshot = discovery.build_snapshot(self.root, manifest, {"orders": "working-tree"})

        state = snapshot["repositories"]["orders"]
        self.assertEqual(state["working_tree_fingerprint"], "f" * 64)
        self.assertNotIn("diff", state)
        fingerprint.assert_called_once_with(self.root / "orders", "abc123", ("generated",))

    @staticmethod
    def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
            shell=False,
        )

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

class CliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.load_tests = self.root / "load-tests"
        self.load_tests.mkdir()
        self.sut = self.root / "orders"
        self.sut.mkdir()
        self.manifest = self.root / "workspace.yaml"
        self.manifest.write_text(
            "version: 1\nsystem: SHOP\nworkspace_root: .\n"
            "load_test_module: load-tests\nmodules: []\n"
            "write_policy:\n  allowed_modules: [load-tests]\n  sut_modules: read-only\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def main(self, *args: str) -> tuple[int, str]:
        from io import StringIO
        from contextlib import redirect_stderr
        if __package__:
            from . import workspace_discovery
        else:
            from workspace_discovery import workspace_discovery

        stderr = StringIO()
        with redirect_stderr(stderr):
            code = workspace_discovery.main(list(args))
        return code, stderr.getvalue()

    def test_preview_writes_json_without_mutating_manifest(self) -> None:
        before = self.manifest.read_bytes()
        output = self.load_tests / "run" / "workspace-discovery.json"
        code, stderr = self.main("preview", "--manifest", str(self.manifest), "--out", str(output))
        self.assertEqual(code, 0, stderr)
        self.assertEqual(self.manifest.read_bytes(), before)
        self.assertTrue(output.is_file())

    def test_preview_rejects_output_in_sut_sibling(self) -> None:
        code, stderr = self.main(
            "preview", "--manifest", str(self.manifest),
            "--out", str(self.sut / "workspace-discovery.json"),
        )
        self.assertEqual(code, 2)
        self.assertIn("outside workspace", stderr)
        self.assertNotIn("Traceback", stderr)

    def test_snapshot_rejects_run_dir_in_sut_sibling(self) -> None:
        code, stderr = self.main(
            "snapshot", "--manifest", str(self.manifest), "--run-dir", str(self.sut / "run"),
        )
        self.assertEqual(code, 2)
        self.assertIn("outside workspace", stderr)
        self.assertNotIn("Traceback", stderr)

    def test_snapshot_writes_json_under_load_test_module(self) -> None:
        run_dir = self.load_tests / "run"
        code, stderr = self.main("snapshot", "--manifest", str(self.manifest), "--run-dir", str(run_dir))
        self.assertEqual(code, 0, stderr)
        self.assertTrue((run_dir / "workspace-snapshot.json").is_file())

    def test_invalid_output_shapes_return_domain_error(self) -> None:
        output_dir = self.load_tests / "directory-output"
        output_dir.mkdir()
        run_file = self.load_tests / "run-file"
        run_file.write_text("not a directory", encoding="utf-8")

        cases = [
            ("preview", "--out", output_dir),
            ("snapshot", "--run-dir", run_file),
        ]
        for command, option, path in cases:
            with self.subTest(command=command):
                code, stderr = self.main(
                    command, "--manifest", str(self.manifest), option, str(path),
                )
                self.assertEqual(code, 2)
                self.assertNotIn("Traceback", stderr)
if __name__ == "__main__":
    unittest.main()

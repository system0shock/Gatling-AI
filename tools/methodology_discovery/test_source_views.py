#!/usr/bin/env python3
"""Revision and filesystem boundary tests for bounded source views."""

from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

if __package__:
    from . import source_views
else:
    import source_views

working_tree_fingerprint = source_views.working_tree_fingerprint


MIB = 1024 * 1024


class FakeDirEntry:
    """Small deterministic scandir entry for symlink boundary tests."""

    def __init__(
        self,
        name: str,
        path: Path,
        *,
        target_is_directory: bool,
    ) -> None:
        self.name = name
        self.path = str(path)
        self.target_is_directory = target_is_directory
        self.dir_follow_calls: list[bool] = []
        self.file_follow_calls: list[bool] = []

    def is_dir(self, *, follow_symlinks: bool = True) -> bool:
        self.dir_follow_calls.append(follow_symlinks)
        return self.target_is_directory if follow_symlinks else False

    def is_file(self, *, follow_symlinks: bool = True) -> bool:
        self.file_follow_calls.append(follow_symlinks)
        return (not self.target_is_directory) if follow_symlinks else False

    def is_symlink(self) -> bool:
        return True


class SourceViewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name) / "repo"
        self.repo.mkdir()
        self._git("init")
        self._git("config", "user.email", "test@example.com")
        self._git("config", "user.name", "Discovery Test")
        (self.repo / "openapi.yaml").write_text(
            "openapi: 3.0.0\npaths:\n  /committed: {}\n", encoding="utf-8"
        )
        self._git("add", "openapi.yaml")
        self._git("commit", "-m", "initial")
        self.commit = self._git("rev-parse", "HEAD").stdout.strip()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_head_policy_reads_committed_blob_not_dirty_bytes(self) -> None:
        """Replacing a working file must not change a HEAD-policy read."""
        (self.repo / "openapi.yaml").write_text(
            "openapi: 3.0.0\npaths:\n  /dirty: {}\n", encoding="utf-8"
        )

        view = source_views.source_view(
            self.repo,
            {"commit": self.commit, "dirty_policy": "HEAD"},
            run_id="RUN-001",
        )

        self.assertEqual(view.source_mode, "git-object")
        self.assertEqual(view.snapshot_identity, f"commit:{self.commit}")
        self.assertIn("openapi.yaml", view.list_paths())
        content = view.read_bytes("openapi.yaml", 5 * MIB)
        self.assertIn(b"/committed", content)
        self.assertNotIn(b"/dirty", content)

    def test_working_tree_policy_reads_hash_guarded_dirty_bytes(self) -> None:
        """A confirmed dirty snapshot must expose the accepted working bytes."""
        dirty = b"openapi: 3.0.0\npaths:\n  /dirty: {}\n"
        (self.repo / "openapi.yaml").write_bytes(dirty)
        fingerprint = working_tree_fingerprint(self.repo, self.commit, ())

        view = source_views.source_view(
            self.repo,
            {
                "commit": self.commit,
                "dirty_policy": "working-tree",
                "working_tree_fingerprint": fingerprint,
                "exclude": [],
            },
            run_id="RUN-001",
        )

        self.assertEqual(view.source_mode, "working-tree")
        self.assertEqual(
            view.snapshot_identity, f"working-tree:RUN-001:{fingerprint}"
        )
        self.assertEqual(view.read_bytes("openapi.yaml", 5 * MIB), dirty)
        view.verify_run_guard()

    def test_exact_byte_cap_is_allowed_and_one_byte_more_is_rejected(self) -> None:
        """Changing a <= comparison to < must fail at the exact hard cap."""
        payload = subprocess.run(
            ["git", "cat-file", "blob", f"{self.commit}:openapi.yaml"],
            cwd=self.repo,
            capture_output=True,
            check=True,
            shell=False,
        ).stdout
        view = source_views.source_view(
            self.repo,
            {"commit": self.commit, "dirty_policy": "clean"},
            run_id="RUN-001",
        )

        self.assertEqual(view.read_bytes("openapi.yaml", len(payload)), payload)
        with self.assertRaisesRegex(source_views.DiscoveryError, "source-file-too-large"):
            view.read_bytes("openapi.yaml", len(payload) - 1)

    def test_paths_are_normalized_before_reaching_git_or_filesystem(self) -> None:
        """Traversal, NUL, absolute, and backslash paths must never be read."""
        view = source_views.source_view(
            self.repo,
            {"commit": self.commit, "dirty_policy": "clean"},
            run_id="RUN-001",
        )

        for path in (
            "../openapi.yaml",
            "api/../openapi.yaml",
            "/openapi.yaml",
            "C:/openapi.yaml",
            "api\\openapi.yaml",
            "openapi\x00.yaml",
            "./openapi.yaml",
            "",
        ):
            with self.subTest(path=path):
                with self.assertRaisesRegex(
                    source_views.DiscoveryError, "invalid-source-path"
                ):
                    view.read_bytes(path, MIB)

    def test_working_tree_change_between_index_and_read_is_rejected(self) -> None:
        """A stale size/mtime/hash tuple must not produce a source record."""
        fingerprint = working_tree_fingerprint(self.repo, self.commit, ())
        view = source_views.source_view(
            self.repo,
            {
                "commit": self.commit,
                "dirty_policy": "working-tree",
                "working_tree_fingerprint": fingerprint,
                "exclude": [],
            },
            run_id="RUN-001",
        )
        original = self.repo / "openapi.yaml"
        stat = original.stat()
        changed = original.read_bytes().replace(b"committed", b"different")
        original.write_bytes(changed)
        # Preserve indexed size and mtime so the post-read hash check is essential.
        self.assertEqual(len(changed), stat.st_size)
        import os

        os.utime(original, ns=(stat.st_atime_ns, stat.st_mtime_ns))

        with self.assertRaisesRegex(
            source_views.DiscoveryError, "source-changed-during-scan"
        ):
            view.read_bytes("openapi.yaml", MIB)

    def test_opened_object_identity_is_checked_during_indexing(self) -> None:
        """Indexing must reject a handle redirected away from the resolved target."""
        fingerprint = working_tree_fingerprint(self.repo, self.commit, ())
        outside = Path(self.temp.name) / "outside-indexed.txt"
        outside.write_bytes(b"outside")
        real_os_open = os.open

        with patch.object(
            source_views.os,
            "open",
            side_effect=lambda _path, flags: real_os_open(outside, flags),
        ):
            with self.assertRaisesRegex(
                source_views.DiscoveryError, "source-changed-during-scan"
            ):
                source_views.source_view(
                    self.repo,
                    {
                        "commit": self.commit,
                        "dirty_policy": "working-tree",
                        "working_tree_fingerprint": fingerprint,
                        "exclude": [],
                    },
                    run_id="RUN-001",
                )

    def test_opened_object_identity_is_checked_before_later_read(self) -> None:
        """A later read must consume only a handle for the exact indexed object."""
        view = self._working_view()
        outside = Path(self.temp.name) / "outside-read.txt"
        outside.write_bytes((self.repo / "openapi.yaml").read_bytes())
        real_os_open = os.open

        with patch.object(
            source_views.os,
            "open",
            side_effect=lambda _path, flags: real_os_open(outside, flags),
        ):
            with self.assertRaisesRegex(
                source_views.DiscoveryError, "source-changed-during-scan"
            ):
                view.read_bytes("openapi.yaml", MIB)

    def test_deleted_indexed_file_is_snapshot_drift(self) -> None:
        """A vanished selected path is drift, not an outside-repository source."""
        view = self._working_view()
        (self.repo / "openapi.yaml").unlink()

        with self.assertRaisesRegex(
            source_views.DiscoveryError, "source-changed-during-scan"
        ):
            view.read_bytes("openapi.yaml", MIB)

    def test_moved_indexed_file_is_snapshot_drift(self) -> None:
        """Moving an indexed object away from its selected path must fail closed."""
        view = self._working_view()
        (self.repo / "openapi.yaml").rename(self.repo / "moved.yaml")

        with self.assertRaisesRegex(
            source_views.DiscoveryError, "source-changed-during-scan"
        ):
            view.read_bytes("openapi.yaml", MIB)

    def test_recreated_working_view_rejects_stale_snapshot_run_guard(self) -> None:
        """Sequential layers must not silently combine two dirty repository states."""
        tracked = self.repo / "openapi.yaml"
        tracked.write_text("openapi: 3.0.0\npaths: {}\n", encoding="utf-8")
        fingerprint = working_tree_fingerprint(self.repo, self.commit, ())
        snapshot = {
            "commit": self.commit,
            "dirty_policy": "working-tree",
            "working_tree_fingerprint": fingerprint,
            "exclude": [],
        }
        source_views.source_view(self.repo, snapshot, run_id="RUN-001")
        tracked.write_text("openapi: 3.0.0\npaths: {changed: {}}\n", encoding="utf-8")

        with self.assertRaisesRegex(
            source_views.DiscoveryError, "working-tree-snapshot-drift"
        ):
            source_views.source_view(self.repo, snapshot, run_id="RUN-001")

    def test_directory_symlinks_are_not_followed_and_file_escapes_are_rejected(self) -> None:
        """No symlink may turn repository-relative discovery into an outside read."""
        outside_root = Path(self.temp.name) / "outside"
        outside_root.mkdir()
        (outside_root / "secret.txt").write_text("secret", encoding="utf-8")
        fingerprint = working_tree_fingerprint(self.repo, self.commit, ())
        directory_link = self.repo / "linked-dir"
        file_link = self.repo / "linked-file.txt"
        try:
            directory_link.symlink_to(outside_root, target_is_directory=True)
            file_link.symlink_to(outside_root / "secret.txt")
        except OSError:
            self.skipTest("symlinks unavailable")

        with self.assertRaisesRegex(
            source_views.DiscoveryError, "source-outside-repository"
        ):
            source_views.source_view(
                self.repo,
                {
                    "commit": self.commit,
                    "dirty_policy": "working-tree",
                    "working_tree_fingerprint": fingerprint,
                    "exclude": [],
                },
                run_id="RUN-001",
            )

    def test_directory_symlink_is_not_followed_without_host_privilege(self) -> None:
        """Directory symlink classification must stop before containment or file reads."""
        fake = FakeDirEntry(
            "linked-dir",
            self.repo / "privilege-independent-directory-link",
            target_is_directory=True,
        )
        with (
            patch.object(source_views, "working_tree_fingerprint", return_value="f" * 64),
            patch.object(source_views.os, "scandir", return_value=[fake]),
        ):
            view = source_views.WorkingTreeSourceView(
                self.repo, self.commit, "f" * 64, (), "RUN-001"
            )

        self.assertEqual(view.list_paths(), ())
        self.assertEqual(fake.dir_follow_calls, [False, True])
        self.assertEqual(fake.file_follow_calls, [])

    def test_file_symlink_escape_is_rejected_without_host_privilege(self) -> None:
        """A file entry whose followed target is outside the root must be rejected."""
        outside = Path(self.temp.name) / "outside-file.txt"
        outside.write_text("secret", encoding="utf-8")
        fake = FakeDirEntry(
            "linked-file.txt", outside, target_is_directory=False
        )
        with (
            patch.object(source_views, "working_tree_fingerprint", return_value="f" * 64),
            patch.object(source_views.os, "scandir", return_value=[fake]),
        ):
            with self.assertRaisesRegex(
                source_views.DiscoveryError, "source-outside-repository"
            ):
                source_views.WorkingTreeSourceView(
                    self.repo, self.commit, "f" * 64, (), "RUN-001"
                )
        self.assertEqual(fake.dir_follow_calls, [False, True])
        self.assertEqual(fake.file_follow_calls, [True])

    def test_working_tree_index_hash_is_stable_for_unchanged_file(self) -> None:
        """The indexed hash must describe the bytes later returned to a locator."""
        fingerprint = working_tree_fingerprint(self.repo, self.commit, ())
        view = source_views.source_view(
            self.repo,
            {
                "commit": self.commit,
                "dirty_policy": "working-tree",
                "working_tree_fingerprint": fingerprint,
                "exclude": [],
            },
            run_id="RUN-001",
        )
        content = view.read_bytes("openapi.yaml", MIB)

        self.assertEqual(view.sha256("openapi.yaml"), hashlib.sha256(content).hexdigest())

    def _working_view(self) -> source_views.WorkingTreeSourceView:
        fingerprint = working_tree_fingerprint(self.repo, self.commit, ())
        view = source_views.source_view(
            self.repo,
            {
                "commit": self.commit,
                "dirty_policy": "working-tree",
                "working_tree_fingerprint": fingerprint,
                "exclude": [],
            },
            run_id="RUN-001",
        )
        self.assertIsInstance(view, source_views.WorkingTreeSourceView)
        return view

    def _git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=self.repo,
            capture_output=True,
            text=True,
            check=True,
            shell=False,
        )


if __name__ == "__main__":
    unittest.main()

"""Exact, bounded reads from confirmed Git or working-tree snapshots."""

from __future__ import annotations

import hashlib
import importlib.util
import os
import stat
import subprocess
import sys
from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Mapping, Sequence


def _load_working_tree_fingerprint() -> Any:
    """Load Task 1's exact guard without leaking its legacy bare imports."""
    workspace_dir = Path(__file__).resolve().parents[1] / "workspace_discovery"
    module_path = workspace_dir / "discovery.py"
    spec = importlib.util.spec_from_file_location(
        "_methodology_workspace_discovery", module_path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load workspace discovery API from {module_path}")
    module = importlib.util.module_from_spec(spec)
    previous_models = sys.modules.pop("models", None)
    sys.path.insert(0, str(workspace_dir))
    try:
        spec.loader.exec_module(module)
    finally:
        try:
            sys.path.remove(str(workspace_dir))
        except ValueError:
            pass
        sys.modules.pop("models", None)
        if previous_models is not None:
            sys.modules["models"] = previous_models
    return module.working_tree_fingerprint


working_tree_fingerprint = _load_working_tree_fingerprint()


class DiscoveryError(RuntimeError):
    """A safe, user-facing bounded-discovery failure."""

    def __init__(self, code: str, message: str, *, path: str | None = None) -> None:
        self.code = code
        self.path = path
        detail = f" [{path}]" if path is not None else ""
        super().__init__(f"{code}{detail}: {message}")


def normalize_source_path(value: str) -> str:
    """Return one normalized repository-relative POSIX path or raise."""
    if not isinstance(value, str):
        raise DiscoveryError("invalid-source-path", "path must be a string")
    path = PurePosixPath(value)
    if (
        not value
        or "\x00" in value
        or "\\" in value
        or value.startswith("/")
        or ":" in value.split("/", 1)[0]
        or "//" in value
        or any(part in {".", ".."} for part in path.parts)
        or path.as_posix() != value
    ):
        raise DiscoveryError(
            "invalid-source-path",
            "path must be a normalized relative POSIX path",
            path=value,
        )
    return value


def _byte_limit(value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise DiscoveryError("invalid-byte-limit", "max_bytes must be a non-negative integer")
    return value


def _inside(
    root: Path,
    candidate: Path,
    relative: str,
    *,
    missing_code: str = "source-outside-repository",
) -> Path:
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise DiscoveryError(
            missing_code,
            "source no longer resolves to the indexed object",
            path=relative,
        ) from exc
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise DiscoveryError(
            "source-outside-repository",
            "source resolves outside the confirmed repository",
            path=relative,
        ) from exc
    return resolved


def _file_identity(info: os.stat_result, relative: str) -> tuple[int, int]:
    device = getattr(info, "st_dev", None)
    inode = getattr(info, "st_ino", None)
    if (
        not isinstance(device, int)
        or not isinstance(inode, int)
        or device < 0
        or inode <= 0
    ):
        raise DiscoveryError(
            "source-identity-unavailable",
            "platform did not provide a stable opened-file identity",
            path=relative,
        )
    return (device, inode)


def _verify_current_target(
    root: Path,
    candidate: Path,
    relative: str,
    *,
    expected_resolved: Path | None = None,
    expected_identity: tuple[int, int] | None = None,
) -> tuple[Path, os.stat_result, tuple[int, int]]:
    resolved = _inside(
        root,
        candidate,
        relative,
        missing_code="source-changed-during-scan",
    )
    try:
        current = resolved.stat()
    except OSError as exc:
        raise DiscoveryError(
            "source-changed-during-scan",
            "source target changed during validation",
            path=relative,
        ) from exc
    if not stat.S_ISREG(current.st_mode):
        raise DiscoveryError(
            "source-changed-during-scan",
            "source target is no longer a regular file",
            path=relative,
        )
    identity = _file_identity(current, relative)
    if expected_resolved is not None and resolved != expected_resolved:
        raise DiscoveryError(
            "source-changed-during-scan",
            "source target changed after indexing",
            path=relative,
        )
    if expected_identity is not None and identity != expected_identity:
        raise DiscoveryError(
            "source-changed-during-scan",
            "source identity changed after indexing",
            path=relative,
        )
    return resolved, current, identity


@contextmanager
def _opened_source(
    root: Path,
    candidate: Path,
    relative: str,
    *,
    expected_resolved: Path | None = None,
    expected_identity: tuple[int, int] | None = None,
) -> Iterator[tuple[BinaryIO, os.stat_result, Path, tuple[int, int]]]:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(candidate, flags)
    except OSError as exc:
        raise DiscoveryError(
            "source-changed-during-scan",
            "source could not be opened as the indexed object",
            path=relative,
        ) from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise DiscoveryError(
                "source-changed-during-scan",
                "opened source is not a regular file",
                path=relative,
            )
        opened_identity = _file_identity(opened, relative)
        resolved, _current, current_identity = _verify_current_target(
            root,
            candidate,
            relative,
            expected_resolved=expected_resolved,
            expected_identity=expected_identity,
        )
        if opened_identity != current_identity:
            raise DiscoveryError(
                "source-changed-during-scan",
                "opened source does not match the current in-root target",
                path=relative,
            )
        handle = os.fdopen(descriptor, "rb", closefd=True)
        descriptor = -1
        with handle:
            yield handle, opened, resolved, opened_identity
    finally:
        if descriptor >= 0:
            os.close(descriptor)


class SourceView(ABC):
    """Common interface for immutable Git-object and guarded filesystem reads."""

    source_mode: str
    snapshot_identity: str
    revision: str

    @abstractmethod
    def list_paths(self) -> tuple[str, ...]:
        """List normalized repository-relative file paths."""

    @abstractmethod
    def read_bytes(self, path: str, max_bytes: int) -> bytes:
        """Read one file without crossing the hard byte limit."""

    def read_text(self, path: str, max_bytes: int) -> str:
        """Read strict UTF-8 text through the same hard byte boundary."""
        normalized = normalize_source_path(path)
        content = self.read_bytes(normalized, max_bytes)
        if b"\x00" in content:
            raise DiscoveryError(
                "source-not-utf8-text", "NUL byte is not allowed in text input", path=normalized
            )
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DiscoveryError(
                "source-not-utf8-text", "source is not valid UTF-8 text", path=normalized
            ) from exc

    def sha256(self, path: str) -> str:
        """Return the SHA-256 of the exact bytes exposed by this view."""
        return hashlib.sha256(self.read_bytes(path, (1 << 63) - 1)).hexdigest()

    def verify_run_guard(self) -> None:
        """Verify that a layer still represents the accepted snapshot."""


class GitTreeSourceView(SourceView):
    """Read committed bytes directly from a Git tree, never from the worktree."""

    def __init__(self, repo_root: Path, commit: str) -> None:
        try:
            self.repo_root = repo_root.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise DiscoveryError("repository-unavailable", str(exc)) from exc
        if not self.repo_root.is_dir() or not commit or "\x00" in commit:
            raise DiscoveryError("invalid-snapshot-state", "Git commit and repository are required")
        self.revision = commit
        self.source_mode = "git-object"
        self.snapshot_identity = f"commit:{commit}"
        self._paths: tuple[str, ...] | None = None

    def _git(self, args: Sequence[str], code: str) -> bytes:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=self.repo_root,
                capture_output=True,
                timeout=30,
                check=False,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DiscoveryError(code, f"Git command failed: {exc}") from exc
        if result.returncode != 0:
            message = result.stderr.decode("utf-8", errors="replace").strip()
            raise DiscoveryError(code, message or "Git command returned a failure")
        return result.stdout

    def list_paths(self) -> tuple[str, ...]:
        if self._paths is None:
            output = self._git(
                ["ls-tree", "-rz", "--name-only", self.revision], "source-list-failed"
            )
            paths: list[str] = []
            for raw in output.split(b"\x00"):
                if not raw:
                    continue
                try:
                    decoded = raw.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise DiscoveryError(
                        "invalid-source-path", "Git tree path is not UTF-8"
                    ) from exc
                paths.append(normalize_source_path(decoded))
            self._paths = tuple(sorted(paths))
        return self._paths

    def read_bytes(self, path: str, max_bytes: int) -> bytes:
        normalized = normalize_source_path(path)
        limit = _byte_limit(max_bytes)
        object_name = f"{self.revision}:{normalized}"
        raw_size = self._git(["cat-file", "-s", object_name], "source-read-failed")
        try:
            size = int(raw_size.strip())
        except ValueError as exc:
            raise DiscoveryError(
                "source-read-failed", "Git returned an invalid blob size", path=normalized
            ) from exc
        if size > limit:
            raise DiscoveryError(
                "source-file-too-large",
                f"source is {size} bytes; hard limit is {limit}",
                path=normalized,
            )
        content = self._git(["cat-file", "blob", object_name], "source-read-failed")
        if len(content) != size:
            raise DiscoveryError(
                "source-read-failed", "Git blob size changed during read", path=normalized
            )
        return content


@dataclass(frozen=True)
class _IndexedFile:
    resolved: Path
    identity: tuple[int, int]
    size: int
    mtime_ns: int
    sha256: str


class WorkingTreeSourceView(SourceView):
    """Read one accepted working tree with containment and race guards."""

    def __init__(
        self,
        repo_root: Path,
        commit: str,
        expected_fingerprint: str,
        exclusions: Sequence[str],
        run_id: str,
    ) -> None:
        try:
            self.repo_root = repo_root.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise DiscoveryError("repository-unavailable", str(exc)) from exc
        if not self.repo_root.is_dir() or not commit or not expected_fingerprint or not run_id:
            raise DiscoveryError(
                "invalid-snapshot-state",
                "working-tree commit, fingerprint, repository, and run ID are required",
            )
        self.revision = commit
        self.source_mode = "working-tree"
        self.expected_fingerprint = expected_fingerprint
        self.exclusions = tuple(exclusions)
        self.snapshot_identity = f"working-tree:{run_id}:{expected_fingerprint}"
        self.verify_run_guard()
        self._index = self._build_index()
        self.verify_run_guard()

    def _fingerprint(self) -> str:
        try:
            return working_tree_fingerprint(
                self.repo_root, self.revision, self.exclusions
            )
        except ValueError as exc:
            code = (
                "source-outside-repository"
                if "outside workspace" in str(exc)
                else "working-tree-snapshot-drift"
            )
            raise DiscoveryError(code, str(exc)) from exc

    def verify_run_guard(self) -> None:
        actual = self._fingerprint()
        if actual != self.expected_fingerprint:
            raise DiscoveryError(
                "working-tree-snapshot-drift",
                "working tree no longer matches the confirmed run guard fingerprint",
            )

    def _build_index(self) -> dict[str, _IndexedFile]:
        index: dict[str, _IndexedFile] = {}

        def visit(directory: Path, prefix: PurePosixPath | None = None) -> None:
            try:
                entries = sorted(os.scandir(directory), key=lambda item: (item.name.casefold(), item.name))
            except OSError as exc:
                raise DiscoveryError("source-list-failed", str(exc)) from exc
            for entry in entries:
                relative_path = (
                    PurePosixPath(entry.name)
                    if prefix is None
                    else prefix / entry.name
                )
                relative = normalize_source_path(relative_path.as_posix())
                candidate = Path(entry.path)
                if entry.is_dir(follow_symlinks=False):
                    if relative == ".git" or relative.startswith(".git/"):
                        continue
                    visit(candidate, relative_path)
                    continue
                if entry.is_symlink() and entry.is_dir(follow_symlinks=True):
                    # Directory symlinks are deliberately not traversed, even internally.
                    continue
                if not entry.is_file(follow_symlinks=True):
                    continue
                try:
                    with _opened_source(
                        self.repo_root, candidate, relative
                    ) as (handle, before, resolved, identity):
                        digest = hashlib.sha256()
                        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                            digest.update(chunk)
                        after = os.fstat(handle.fileno())
                except OSError as exc:
                    raise DiscoveryError(
                        "source-read-failed", str(exc), path=relative
                    ) from exc
                if (
                    _file_identity(after, relative) != identity
                    or before.st_size != after.st_size
                    or before.st_mtime_ns != after.st_mtime_ns
                ):
                    raise DiscoveryError(
                        "source-changed-during-scan",
                        "source changed while it was indexed",
                        path=relative,
                    )
                _verify_current_target(
                    self.repo_root,
                    candidate,
                    relative,
                    expected_resolved=resolved,
                    expected_identity=identity,
                )
                index[relative] = _IndexedFile(
                    resolved=resolved,
                    identity=identity,
                    size=before.st_size,
                    mtime_ns=before.st_mtime_ns,
                    sha256=digest.hexdigest(),
                )

        visit(self.repo_root)
        return index

    def list_paths(self) -> tuple[str, ...]:
        return tuple(sorted(self._index))

    def read_bytes(self, path: str, max_bytes: int) -> bytes:
        normalized = normalize_source_path(path)
        limit = _byte_limit(max_bytes)
        record = self._index.get(normalized)
        if record is None:
            raise DiscoveryError(
                "source-not-indexed", "source was not present at snapshot selection", path=normalized
            )
        candidate = self.repo_root / Path(*PurePosixPath(normalized).parts)
        with _opened_source(
            self.repo_root,
            candidate,
            normalized,
            expected_resolved=record.resolved,
            expected_identity=record.identity,
        ) as (handle, before, resolved, identity):
            if before.st_size != record.size or before.st_mtime_ns != record.mtime_ns:
                raise DiscoveryError(
                    "source-changed-during-scan",
                    "source metadata changed after indexing",
                    path=normalized,
                )
            if before.st_size > limit:
                raise DiscoveryError(
                    "source-file-too-large",
                    f"source is {before.st_size} bytes; hard limit is {limit}",
                    path=normalized,
                )
            content = handle.read(limit + 1)
            after = os.fstat(handle.fileno())
        if (
            len(content) > limit
            or _file_identity(after, normalized) != identity
            or after.st_size != record.size
            or after.st_mtime_ns != record.mtime_ns
            or hashlib.sha256(content).hexdigest() != record.sha256
        ):
            raise DiscoveryError(
                "source-changed-during-scan", "source bytes changed after indexing", path=normalized
            )
        _verify_current_target(
            self.repo_root,
            candidate,
            normalized,
            expected_resolved=resolved,
            expected_identity=identity,
        )
        return content

    def sha256(self, path: str) -> str:
        normalized = normalize_source_path(path)
        record = self._index.get(normalized)
        if record is None:
            raise DiscoveryError(
                "source-not-indexed", "source was not present at snapshot selection", path=normalized
            )
        # Force the race checks before exposing the indexed identity.
        self.read_bytes(normalized, record.size)
        return record.sha256


def source_view(
    repo_root: Path,
    snapshot_state: Mapping[str, Any],
    run_id: str,
) -> SourceView:
    """Construct the exact source view selected by one workspace snapshot record."""
    if snapshot_state.get("available") is False:
        raise DiscoveryError("repository-unavailable", "snapshot repository is unavailable")
    commit = snapshot_state.get("commit")
    policy = snapshot_state.get("dirty_policy")
    if not isinstance(commit, str) or policy not in {"clean", "HEAD", "working-tree"}:
        raise DiscoveryError("invalid-snapshot-state", "commit and dirty policy are required")
    if policy in {"clean", "HEAD"}:
        return GitTreeSourceView(Path(repo_root), commit)
    fingerprint = snapshot_state.get("working_tree_fingerprint")
    exclusions = snapshot_state.get("exclude", ())
    if not isinstance(fingerprint, str) or not isinstance(exclusions, (list, tuple)):
        raise DiscoveryError(
            "invalid-snapshot-state", "working-tree fingerprint and exclusions are required"
        )
    if not all(isinstance(item, str) for item in exclusions):
        raise DiscoveryError("invalid-snapshot-state", "exclusions must be strings")
    return WorkingTreeSourceView(
        Path(repo_root), commit, fingerprint, tuple(exclusions), run_id
    )

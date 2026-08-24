"""One real multi-repository check for the bounded discovery MVP."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
DISCOVERY = REPO_ROOT / "tools" / "methodology_discovery" / "methodology_discovery.py"
WORKSPACE = REPO_ROOT / "tools" / "workspace_discovery" / "workspace_discovery.py"


class DiscoveryMvpTest(unittest.TestCase):
    def test_scan_and_confirm_four_repositories_with_manual_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            root = temporary_root / "workspace"
            load_tests = root / "load-tests"
            run_dir = load_tests / "run"
            load_tests.mkdir(parents=True)
            sources = {
                "orders-contracts": (
                    "openapi.yaml",
                    """openapi: 3.0.3
info:
  title: Orders
  x-service-id: orders
paths:
  /documents:
    post:
      responses:
        '201': {description: Created}
""",
                ),
                "orders-backend": (
                    "pom.xml",
                    "<project><artifactId>orders-backend</artifactId></project>\n",
                ),
                "orders-infra": (
                    "deployment.yaml",
                    """apiVersion: apps/v1
kind: Deployment
metadata: {name: orders-api}
spec:
  template:
    spec:
      containers:
        - name: api
          ports: [{containerPort: 8080}]
""",
                ),
                "orders-docs": (
                    "README.md",
                    "# Architecture\nDocuments are created asynchronously.\n",
                ),
            }
            before: dict[str, str] = {}
            for repo_id, (relative, content) in sources.items():
                repository = root / repo_id
                repository.mkdir()
                (repository / relative).write_text(content, encoding="utf-8")
                self._git(repository, "init", "-q")
                self._git(repository, "add", ".")
                self._git(
                    repository,
                    "-c", "user.name=Test",
                    "-c", "user.email=test@example.invalid",
                    "commit", "-qm", "fixture",
                )
                before[repo_id] = self._tree_hash(repository)

            manifest = load_tests / "workspace.yaml"
            manifest.write_text(
                yaml.safe_dump({
                    "version": 2,
                    "system": "SHOP",
                    "workspace_root": "..",
                    "load_test_module": "load-tests",
                    "repositories": [
                        {
                            "id": repo_id,
                            "path": repo_id,
                            "roles": [repo_id.removeprefix("orders-")],
                            "service_id": "orders",
                        }
                        for repo_id in sources
                    ],
                    "write_policy": {
                        "allowed_modules": ["load-tests"],
                        "sut_modules": "read-only",
                    },
                }, sort_keys=False),
                encoding="utf-8",
            )

            snapshot = self._run(
                WORKSPACE,
                "snapshot",
                "--manifest", manifest,
                "--run-dir", run_dir,
            )
            self.assertEqual(snapshot.returncode, 0, snapshot.stderr)

            scan = self._run(
                DISCOVERY,
                "scan",
                "--manifest", manifest,
                "--workspace-snapshot", run_dir / "workspace-snapshot.json",
                "--run-dir", run_dir,
                "--load-test-root", load_tests,
            )
            self.assertEqual(scan.returncode, 0, scan.stderr)

            candidate = json.loads(
                (run_dir / "surface-candidate.json").read_text(encoding="utf-8")
            )
            self.assertIn(
                "http:orders:POST:/documents",
                {item["canonical_key"] for item in candidate["entities"]},
            )
            self.assertEqual(
                sorted(path.parent.name for path in (run_dir / "discovery").glob("*/discovery-index.json")),
                sorted(sources),
            )

            decisions = run_dir / "surface-decisions.yaml"
            decisions.write_text(yaml.safe_dump({
                "version": 1,
                "candidate_id": candidate["candidate_id"],
                "accept_all": True,
                "include": [],
                "exclude": [],
                "add": [{
                    "entity_type": "flow",
                    "canonical_key": "flow:user:document-created",
                    "display_name": "Document created",
                    "attributes": {"source": "manual"},
                }],
                "conflict_resolutions": [],
                "duplicate_merges": [],
            }, sort_keys=False), encoding="utf-8")
            confirm = self._run(
                DISCOVERY,
                "confirm",
                "--candidate", run_dir / "surface-candidate.json",
                "--decisions", decisions,
                "--out", run_dir / "surface-review.json",
                "--load-test-root", load_tests,
            )
            self.assertEqual(confirm.returncode, 0, confirm.stderr)
            review = json.loads(
                (run_dir / "surface-review.json").read_text(encoding="utf-8")
            )
            self.assertEqual(review["status"], "confirmed")
            self.assertEqual(review["added"][0]["canonical_key"], "flow:user:document-created")
            self.assertEqual(
                {repo_id: self._tree_hash(root / repo_id) for repo_id in sources},
                before,
            )

            outside = temporary_root / "outside"
            outside.mkdir()
            (outside / "openapi.yaml").write_text(sources["orders-contracts"][1], encoding="utf-8")
            self._git(outside, "init", "-q")
            self._git(outside, "add", ".")
            self._git(
                outside, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                "commit", "-qm", "fixture",
            )
            escaped_state = {
                "available": True,
                "path": "../outside",
                "roles": ["contracts"],
                "service_id": "outside",
                "required": True,
                "inspect": [],
                "exclude": [],
                "commit": self._git_output(outside, "rev-parse", "HEAD"),
                "branch": self._git_output(outside, "branch", "--show-current"),
                "remote": None,
                "dirty": False,
                "dirty_policy": "clean",
            }
            escaped_manifest = load_tests / "escaped-workspace.yaml"
            escaped_manifest.write_text(yaml.safe_dump({
                "version": 2,
                "system": "SHOP",
                "workspace_root": "..",
                "load_test_module": "load-tests",
                "repositories": [{
                    "id": "outside", "path": "../outside", "roles": ["contracts"],
                    "service_id": "outside",
                }],
                "write_policy": {"allowed_modules": ["load-tests"], "sut_modules": "read-only"},
            }, sort_keys=False), encoding="utf-8")
            encoded = json.dumps({"outside": escaped_state}, sort_keys=True, separators=(",", ":")).encode()
            escaped_snapshot = run_dir / "escaped-snapshot.json"
            escaped_snapshot.write_text(json.dumps({
                "version": 2,
                "snapshot_id": hashlib.sha256(encoded).hexdigest(),
                "workspace_root": str(root.resolve()),
                "status": "complete",
                "repositories": {"outside": escaped_state},
            }), encoding="utf-8")
            escaped = self._run(
                DISCOVERY,
                "scan",
                "--manifest", escaped_manifest,
                "--workspace-snapshot", escaped_snapshot,
                "--run-dir", run_dir / "escaped",
                "--load-test-root", load_tests,
            )
            self.assertEqual(escaped.returncode, 2)
            self.assertIn("outside workspace", escaped.stderr)

    def _run(self, script: Path, *arguments: object) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(script), *(str(value) for value in arguments)],
            capture_output=True,
            text=True,
            check=False,
        )

    def _git(self, repository: Path, *arguments: str) -> None:
        subprocess.run(
            ["git", *arguments], cwd=repository, capture_output=True, check=True
        )

    def _git_output(self, repository: Path, *arguments: str) -> str:
        return subprocess.run(
            ["git", *arguments], cwd=repository, capture_output=True, text=True, check=True
        ).stdout.strip()

    def _tree_hash(self, repository: Path) -> str:
        digest = hashlib.sha256()
        for path in sorted(item for item in repository.rglob("*") if item.is_file() and ".git" not in item.parts):
            digest.update(path.relative_to(repository).as_posix().encode())
            digest.update(path.read_bytes())
        return digest.hexdigest()


if __name__ == "__main__":
    unittest.main()

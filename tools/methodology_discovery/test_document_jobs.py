"""Boundary tests for immutable bounded-document jobs and result loading."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

if __package__:
    from . import contracts, document_jobs, source_views
else:
    import contracts
    import document_jobs
    import source_views


class DocumentJobTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / "sut"
        self.run_dir = self.root / "load-tests" / "methodology-runs" / "RUN-001"
        self.repo.mkdir(parents=True)
        self.run_dir.mkdir(parents=True)
        self._git("init")
        self._git("config", "user.email", "test@example.com")
        self._git("config", "user.name", "Discovery Test")
        (self.repo / "docs").mkdir()
        (self.repo / "docs" / "architecture.md").write_text("committed architecture\n", encoding="utf-8")
        self._git("add", "docs/architecture.md")
        self._git("commit", "-m", "initial")
        self.commit = self._git("rev-parse", "HEAD").stdout.strip()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_head_and_working_jobs_materialize_exact_source_view_bytes(self) -> None:
        dirty = b"dirty accepted architecture\n"
        (self.repo / "docs" / "architecture.md").write_bytes(dirty)
        fingerprint = source_views.working_tree_fingerprint(self.repo, self.commit, ())
        cases = (
            (
                "HEAD",
                {"repo_id": "orders-docs", "commit": self.commit, "dirty_policy": "HEAD"},
                source_views.source_view(self.repo, {"commit": self.commit, "dirty_policy": "HEAD"}, "RUN-001"),
                b"committed architecture\n",
            ),
            (
                "working",
                {"repo_id": "orders-docs", "commit": self.commit, "dirty_policy": "working-tree", "working_tree_fingerprint": fingerprint},
                source_views.source_view(
                    self.repo,
                    {"commit": self.commit, "dirty_policy": "working-tree", "working_tree_fingerprint": fingerprint, "exclude": []},
                    "RUN-001",
                ),
                dirty,
            ),
        )
        for label, snapshot, view, expected in cases:
            with self.subTest(label=label):
                run_dir = self.run_dir / label
                run_dir.mkdir()
                index = self._index(view, expected)

                artifact = document_jobs.build_document_jobs(index, snapshot, view, run_dir)

                contracts.validate_artifact(artifact, "methodology-document-jobs.schema.json")
                self.assertEqual(len(artifact["jobs"]), 1)
                job = artifact["jobs"][0]
                self.assertEqual(job["allowed_fact_types"], ["component", "interface", "integration", "flow"])
                self.assertEqual(job["candidate_output_path"], "discovery/orders-docs/extractor-results/bounded-document-v1.candidate.json")
                self.assertEqual(job["final_output_path"], "discovery/orders-docs/extractor-results/bounded-document-v1.json")
                self.assertEqual((run_dir / job["materialized_path"]).read_bytes(), expected)
                self.assertEqual(json.loads((run_dir / "discovery/orders-docs/document-jobs.json").read_text(encoding="utf-8")), artifact)
                self.assertNotIn(str(self.repo.resolve()), json.dumps(artifact))

    def test_only_document_reasons_are_selected_and_twenty_is_a_hard_cap(self) -> None:
        content = b"architecture\n"

        class View:
            snapshot_identity = "commit:0123456789abcdef"
            revision = "0123456789abcdef"
            source_mode = "git-object"

            def read_bytes(self, path: str, max_bytes: int) -> bytes:
                return content

            def verify_run_guard(self) -> None:
                return None

        selected = [self._source(f"docs/architecture-{number:02d}.md", content, "architecture-document") for number in range(21)]
        selected.append(self._source("api/openapi.yaml", content, "openapi-signature"))
        for record in selected:
            record["revision"] = View.revision
        index = self._base_index(View(), selected)

        artifact = document_jobs.build_document_jobs(
            index,
            {"repo_id": "orders-docs", "commit": View.revision, "dirty_policy": "HEAD"},
            View(),
            self.run_dir,
        )

        self.assertEqual(len(artifact["jobs"]), 20)
        self.assertNotIn("api/openapi.yaml", {job["source_path"] for job in artifact["jobs"]})

    def test_index_snapshot_view_and_bytes_must_agree_exactly(self) -> None:
        view = source_views.source_view(self.repo, {"commit": self.commit, "dirty_policy": "HEAD"}, "RUN-001")
        content = b"committed architecture\n"
        valid_index = self._index(view, content)
        cases = []
        wrong_repo = deepcopy(valid_index)
        wrong_repo["repo_id"] = "other"
        cases.append((wrong_repo, {"repo_id": "orders-docs", "commit": self.commit, "dirty_policy": "HEAD"}))
        wrong_snapshot = deepcopy(valid_index)
        wrong_snapshot["snapshot_identity"] = "commit:deadbeef"
        cases.append((wrong_snapshot, {"repo_id": "orders-docs", "commit": self.commit, "dirty_policy": "HEAD"}))
        wrong_hash = deepcopy(valid_index)
        wrong_hash["selected_files"][0]["sha256"] = "0" * 64
        cases.append((wrong_hash, {"repo_id": "orders-docs", "commit": self.commit, "dirty_policy": "HEAD"}))
        wrong_size = deepcopy(valid_index)
        wrong_size["selected_files"][0]["size_bytes"] += 1
        cases.append((wrong_size, {"repo_id": "orders-docs", "commit": self.commit, "dirty_policy": "HEAD"}))

        for invalid_index, snapshot in cases:
            with self.subTest(index=invalid_index):
                with self.assertRaises((ValueError, source_views.DiscoveryError)):
                    document_jobs.build_document_jobs(invalid_index, snapshot, view, self.run_dir)

    def test_final_results_are_bound_to_sibling_job_and_every_selected_fact(self) -> None:
        view = source_views.source_view(self.repo, {"commit": self.commit, "dirty_policy": "HEAD"}, "RUN-001")
        content = b"committed architecture\n"
        artifact = document_jobs.build_document_jobs(
            self._index(view, content),
            {"repo_id": "orders-docs", "commit": self.commit, "dirty_policy": "HEAD"},
            view,
            self.run_dir,
        )
        job = artifact["jobs"][0]
        final_path = self.run_dir / job["final_output_path"]
        result = self._result(job, artifact)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        final_path.write_text(json.dumps(result), encoding="utf-8")

        loaded = document_jobs.load_document_results([final_path])

        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].to_dict(), result)

        mutations = (
            ("repo", lambda value: value.__setitem__("repo_id", "other")),
            ("snapshot", lambda value: value.__setitem__("snapshot_identity", "commit:other")),
            ("source-path", lambda value: value["candidates"][0]["source"].__setitem__("path", "docs/other.md")),
            ("source-hash", lambda value: value["candidates"][0]["source"].__setitem__("sha256", "f" * 64)),
            ("selection", lambda value: value["candidates"][0]["source"].__setitem__("selection_reason", "other-document")),
            ("entity", lambda value: value["candidates"][0].__setitem__("entity_type", "unknown")),
            ("extractor", lambda value: value.__setitem__("extractor_id", "other")),
            ("version", lambda value: value.__setitem__("extractor_version", 2)),
            ("revision", lambda value: value["candidates"][0]["source"].__setitem__("revision", "deadbeef")),
        )
        for label, mutate in mutations:
            with self.subTest(label=label):
                invalid = deepcopy(result)
                mutate(invalid)
                final_path.write_text(json.dumps(invalid), encoding="utf-8")
                with self.assertRaises(ValueError):
                    document_jobs.load_document_results([final_path])

        unassigned = final_path.with_name("other.json")
        unassigned.write_text(json.dumps(result), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "assigned final output"):
            document_jobs.load_document_results([unassigned])

        final_path.write_text(json.dumps(result), encoding="utf-8")
        job_path = self.run_dir / "discovery/orders-docs/document-jobs.json"
        tampered_job = deepcopy(artifact)
        wrong_materialized = "discovery/orders-docs/extractor-results/not-an-input.txt"
        tampered_job["jobs"][0]["materialized_path"] = wrong_materialized
        (self.run_dir / wrong_materialized).write_bytes(content)
        job_path.write_text(json.dumps(tampered_job), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "assigned document-inputs path"):
            document_jobs.load_document_results([final_path])

        wrong_reason_job = deepcopy(artifact)
        wrong_reason_job["jobs"][0]["selection_reason"] = "openapi-signature"
        wrong_reason_result = deepcopy(result)
        wrong_reason_result["candidates"][0]["source"]["selection_reason"] = "openapi-signature"
        job_path.write_text(json.dumps(wrong_reason_job), encoding="utf-8")
        final_path.write_text(json.dumps(wrong_reason_result), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "document selection reason"):
            document_jobs.load_document_results([final_path])

        duplicate_job = deepcopy(artifact)
        second_content = b"second architecture\n"
        second_hash = hashlib.sha256(second_content).hexdigest()
        second = deepcopy(job)
        second["sha256"] = second_hash
        second["size_bytes"] = len(second_content)
        second["materialized_path"] = f"discovery/orders-docs/document-inputs/002-{second_hash}.txt"
        duplicate_job["jobs"].append(second)
        (self.run_dir / second["materialized_path"]).write_bytes(second_content)
        duplicate_result = deepcopy(result)
        duplicate_result["warnings"] = [{"code": "no-facts", "message": "No second facts.", "path": job["source_path"]}]
        job_path.write_text(json.dumps(duplicate_job), encoding="utf-8")
        final_path.write_text(json.dumps(duplicate_result), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "duplicate selected source coverage"):
            document_jobs.load_document_results([final_path])

        too_many_job = deepcopy(artifact)
        too_many_result = deepcopy(result)
        for ordinal in range(2, 22):
            extra = deepcopy(job)
            extra["source_path"] = f"docs/architecture-{ordinal:02d}.md"
            extra["materialized_path"] = f"discovery/orders-docs/document-inputs/{ordinal:03d}-{job['sha256']}.txt"
            too_many_job["jobs"].append(extra)
            (self.run_dir / extra["materialized_path"]).write_bytes(content)
            too_many_result["warnings"].append({"code": "no-facts", "message": "No facts.", "path": extra["source_path"]})
        job_path.write_text(json.dumps(too_many_job), encoding="utf-8")
        final_path.write_text(json.dumps(too_many_result), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "at most 20"):
            document_jobs.load_document_results([final_path])

    def test_reordered_candidates_and_diagnostics_are_not_normalized_on_load(self) -> None:
        view = source_views.source_view(
            self.repo, {"commit": self.commit, "dirty_policy": "HEAD"}, "RUN-001"
        )
        content = b"committed architecture\n"
        artifact = document_jobs.build_document_jobs(
            self._index(view, content),
            {"repo_id": "orders-docs", "commit": self.commit, "dirty_policy": "HEAD"},
            view,
            self.run_dir,
        )
        job = artifact["jobs"][0]
        final_path = self.run_dir / job["final_output_path"]
        value = self._result(job, artifact)
        second = deepcopy(value["candidates"][0])
        second["canonical_key"] = "component:orders:z-worker"
        second["display_name"] = "z-worker"
        value["candidates"] = [second, value["candidates"][0]]
        value["warnings"] = [
            {"code": "z-warning", "message": "Second warning.", "path": job["source_path"]},
            {"code": "a-warning", "message": "First warning.", "path": job["source_path"]},
        ]
        value["errors"] = [
            {"code": "z-error", "message": "Second error.", "path": job["source_path"]},
            {"code": "a-error", "message": "First error.", "path": job["source_path"]},
        ]
        final_path.parent.mkdir(parents=True, exist_ok=True)
        final_path.write_text(json.dumps(value), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "deterministically normalized"):
            document_jobs.load_document_results([final_path])

        value["candidates"].reverse()
        value["warnings"].reverse()
        value["errors"].reverse()
        final_path.write_text(json.dumps(value), encoding="utf-8")
        loaded = document_jobs.load_document_results([final_path])
        self.assertEqual(loaded[0].to_dict(), value)

    def _index(self, view: object, content: bytes) -> dict:
        return self._base_index(view, [self._source("docs/architecture.md", content, "architecture-document")])

    def _base_index(self, view: object, selected: list[dict]) -> dict:
        return {
            "version": 1,
            "repo_id": "orders-docs",
            "snapshot_identity": view.snapshot_identity,
            "source_mode": view.source_mode,
            "effective_budget": {"structured_file_bytes": 1024, "document_count": 20, "document_file_bytes": 1024, "source_marker_candidates": 0},
            "selected_files": selected,
            "skipped_files": [],
            "counters": {"selected_files": len(selected)},
            "warnings": [],
            "limit_reached": False,
        }

    def _source(self, path: str, content: bytes, reason: str) -> dict:
        return {
            "repo_id": "orders-docs",
            "revision": getattr(self, "commit", "0123456789abcdef"),
            "path": path,
            "pointer": "#",
            "selection_reason": reason,
            "size_bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }

    def _result(self, job: dict, artifact: dict) -> dict:
        return {
            "version": 1,
            "extractor_id": "bounded-document",
            "extractor_version": 1,
            "repo_id": artifact["repo_id"],
            "snapshot_identity": artifact["snapshot_identity"],
            "candidates": [{
                "entity_type": "component",
                "canonical_key": "component:orders:orders-api",
                "display_name": "orders-api",
                "service_identity": {"value": "orders", "basis": "metadata"},
                "attributes": {"kind": "service"},
                "source": {
                    "repo_id": artifact["repo_id"],
                    "revision": self.commit,
                    "path": job["source_path"],
                    "pointer": "#L1-L1",
                    "selection_reason": job["selection_reason"],
                    "sha256": job["sha256"],
                },
                "confidence": "confirmed",
            }],
            "warnings": [],
            "errors": [],
            "limit_reached": False,
        }

    def _git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", *args], cwd=self.repo, capture_output=True, text=True, check=True, shell=False)


if __name__ == "__main__":
    unittest.main()

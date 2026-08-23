"""Contract tests for bounded discovery artifacts."""

from __future__ import annotations

from copy import deepcopy
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

if __package__:
    from . import contracts
    from .fixtures import interface_candidate, valid_extractor_result
    from .models import Candidate, DiscoveryBudget, ExtractorResult, SourceRecord
else:
    import contracts
    from fixtures import interface_candidate, valid_extractor_result
    from models import Candidate, DiscoveryBudget, ExtractorResult, SourceRecord


class DiscoveryContractTests(unittest.TestCase):
    def test_extractor_result_round_trips_through_schema(self) -> None:
        """Removing a required extractor-result field must invalidate its artifact."""
        result = valid_extractor_result(
            extractor_id="openapi",
            candidate=interface_candidate(
                canonical_key="http:orders:POST:/documents",
                source_path="api/openapi.yaml",
                pointer="#/paths/~1documents/post",
            ),
        )

        contracts.validate_artifact(result, "methodology-extractor-result.schema.json")

    def test_source_record_requires_selection_reason_and_hash(self) -> None:
        """A source without provenance must not become a validated finding."""
        result = valid_extractor_result()
        del result["candidates"][0]["source"]["selection_reason"]

        with self.assertRaisesRegex(ValueError, "selection_reason"):
            contracts.validate_artifact(result, "methodology-extractor-result.schema.json")

    def test_extractor_result_rejects_absolute_or_parent_source_paths(self) -> None:
        """A source path escaping a selected repository must be rejected."""
        for path in ("C:/private/openapi.yaml", "/private/openapi.yaml", "api/../openapi.yaml"):
            with self.subTest(path=path):
                result = valid_extractor_result()
                result["candidates"][0]["source"]["path"] = path
                with self.assertRaisesRegex(ValueError, "path"):
                    contracts.validate_artifact(result, "methodology-extractor-result.schema.json")

    def test_nul_paths_are_rejected_by_every_artifact_family(self) -> None:
        """An embedded NUL must never reach a filesystem or Git boundary."""
        nul_path = "docs/architecture\x00.md"
        source = valid_extractor_result()["candidates"][0]["source"]
        extracted = interface_candidate()
        surface_entity = {key: value for key, value in extracted.items() if key != "source"}
        surface_entity["sources"] = [extracted["source"]]
        cases = (
            (
                "extractor source",
                valid_extractor_result(),
                "methodology-extractor-result.schema.json",
                lambda value: value["candidates"][0]["source"].__setitem__("path", nul_path),
            ),
            (
                "extractor diagnostic",
                valid_extractor_result(),
                "methodology-extractor-result.schema.json",
                lambda value: value.__setitem__("warnings", [{"code": "bounded", "message": "limited", "path": nul_path}]),
            ),
            (
                "discovery selected file",
                {"version": 1, "repo_id": "orders", "snapshot_identity": "commit:abc", "source_mode": "git-object", "effective_budget": {"structured_file_bytes": 1, "document_count": 0, "document_file_bytes": 1, "source_marker_candidates": 0}, "selected_files": [source], "skipped_files": [], "counters": {}, "warnings": [], "limit_reached": False},
                "methodology-discovery-index.schema.json",
                lambda value: value["selected_files"][0].__setitem__("path", nul_path),
            ),
            (
                "discovery skipped file",
                {"version": 1, "repo_id": "orders", "snapshot_identity": "commit:abc", "source_mode": "git-object", "effective_budget": {"structured_file_bytes": 1, "document_count": 0, "document_file_bytes": 1, "source_marker_candidates": 0}, "selected_files": [], "skipped_files": [{"path": "docs/architecture.md", "reason": "budget"}], "counters": {}, "warnings": [], "limit_reached": False},
                "methodology-discovery-index.schema.json",
                lambda value: value["skipped_files"][0].__setitem__("path", nul_path),
            ),
            (
                "discovery diagnostic",
                {"version": 1, "repo_id": "orders", "snapshot_identity": "commit:abc", "source_mode": "git-object", "effective_budget": {"structured_file_bytes": 1, "document_count": 0, "document_file_bytes": 1, "source_marker_candidates": 0}, "selected_files": [], "skipped_files": [], "counters": {}, "warnings": [{"code": "bounded", "message": "limited", "path": nul_path}], "limit_reached": False},
                "methodology-discovery-index.schema.json",
                lambda value: None,
            ),
            (
                "document job paths",
                {"version": 1, "repo_id": "orders", "snapshot_identity": "commit:abc", "jobs": [{"source_path": "docs/architecture.md", "materialized_path": "document-inputs/one.txt", "allowed_fact_types": ["flow"], "candidate_output_path": "extractor-results/one.candidate.json", "final_output_path": "extractor-results/one.json", "size_bytes": 1, "sha256": "a" * 64, "selection_reason": "architecture-document"}]},
                "methodology-document-jobs.schema.json",
                lambda value: [value["jobs"][0].__setitem__(key, nul_path) for key in ("source_path", "materialized_path", "candidate_output_path", "final_output_path")],
            ),
            (
                "surface source",
                {"version": 1, "candidate_id": "candidate-001", "snapshot_id": "b" * 64, "entities": [deepcopy(surface_entity)], "review_groups": [{"group_id": "orders:http", "display_name": "Orders / HTTP", "entity_keys": [surface_entity["canonical_key"]]}], "conflicts": [], "possible_duplicates": [], "repository_diagnostics": [], "warnings": [],},
                "methodology-surface-candidate.schema.json",
                lambda value: value["entities"][0]["sources"][0].__setitem__("path", nul_path),
            ),
            (
                "surface diagnostic",
                {"version": 1, "candidate_id": "candidate-001", "snapshot_id": "b" * 64, "entities": [deepcopy(surface_entity)], "review_groups": [{"group_id": "orders:http", "display_name": "Orders / HTTP", "entity_keys": [surface_entity["canonical_key"]]}], "conflicts": [], "possible_duplicates": [], "repository_diagnostics": [], "warnings": [{"code": "bounded", "message": "limited", "path": nul_path}]},
                "methodology-surface-candidate.schema.json",
                lambda value: None,
            ),
        )

        for name, artifact, schema_name, mutate in cases:
            with self.subTest(name=name):
                mutate(artifact)
                with self.assertRaisesRegex(ValueError, "path"):
                    contracts.validate_artifact(artifact, schema_name)

        with self.assertRaisesRegex(ValueError, "normalized relative POSIX"):
            SourceRecord("orders", "abc", nul_path, "#", "fixture", "a" * 64)

    def test_extractor_result_rejects_nested_attribute_values(self) -> None:
        """Nested arbitrary JSON must not leak through normalized attributes."""
        result = valid_extractor_result()
        result["candidates"][0]["attributes"]["nested"] = {"not": "scalar"}

        with self.assertRaisesRegex(ValueError, "nested"):
            contracts.validate_artifact(result, "methodology-extractor-result.schema.json")

    def test_discovery_index_requires_effective_budget_and_bounded_source_records(self) -> None:
        """Locator output must retain the budget and source provenance that bound it."""
        index = {
            "version": 1,
            "repo_id": "orders-contracts",
            "snapshot_identity": "commit:0123456789abcdef",
            "source_mode": "git-object",
            "effective_budget": {
                "structured_file_bytes": 5_242_880,
                "document_count": 20,
                "document_file_bytes": 1_048_576,
                "source_marker_candidates": 500,
            },
            "selected_files": [valid_extractor_result()["candidates"][0]["source"]],
            "skipped_files": [],
            "counters": {"selected_files": 1, "skipped_files": 0},
            "warnings": [],
            "limit_reached": False,
        }

        contracts.validate_artifact(index, "methodology-discovery-index.schema.json")
        del index["effective_budget"]
        with self.assertRaisesRegex(ValueError, "effective_budget"):
            contracts.validate_artifact(index, "methodology-discovery-index.schema.json")

    def test_document_jobs_forbid_arbitrary_prompts(self) -> None:
        """Document extraction input must be selected facts, not an unrestricted prompt."""
        jobs = {
            "version": 1,
            "repo_id": "orders-docs",
            "snapshot_identity": "commit:0123456789abcdef",
            "jobs": [
                {
                    "source_path": "docs/architecture.md",
                    "materialized_path": "document-inputs/orders-docs/000-a.txt",
                    "allowed_fact_types": ["component", "flow"],
                    "candidate_output_path": "document-candidates/orders-docs/architecture.json",
                    "final_output_path": "document-results/orders-docs/architecture.json",
                    "size_bytes": 100,
                    "sha256": "a" * 64,
                    "selection_reason": "architecture-document",
                }
            ],
        }
        contracts.validate_artifact(jobs, "methodology-document-jobs.schema.json")
        jobs["jobs"][0]["prompt"] = "Read every file"
        with self.assertRaisesRegex(ValueError, "prompt"):
            contracts.validate_artifact(jobs, "methodology-document-jobs.schema.json")

    def test_surface_candidate_requires_sorted_entities_and_closed_diagnostics(self) -> None:
        """System candidates must preserve deterministic ordering and diagnostic shape."""
        extracted = interface_candidate()
        entity = {key: value for key, value in extracted.items() if key != "source"}
        entity["sources"] = [extracted["source"]]
        surface = {
            "version": 1,
            "candidate_id": "candidate-001",
            "snapshot_id": "b" * 64,
            "entities": [entity],
            "review_groups": [
                {"group_id": "orders:http", "display_name": "Orders / HTTP", "entity_keys": [entity["canonical_key"]]}
            ],
            "conflicts": [],
            "possible_duplicates": [],
            "repository_diagnostics": [],
            "warnings": [],
        }
        contracts.validate_artifact(surface, "methodology-surface-candidate.schema.json")
        unordered_extracted = interface_candidate(canonical_key="http:orders:GET:/documents")
        unordered_entity = {key: value for key, value in unordered_extracted.items() if key != "source"}
        unordered_entity["sources"] = [unordered_extracted["source"]]
        surface["entities"].append(unordered_entity)
        with self.assertRaisesRegex(ValueError, "entities"):
            contracts.validate_artifact(surface, "methodology-surface-candidate.schema.json")

    def test_surface_candidate_rejects_same_path_sources_in_reverse_stable_order(self) -> None:
        """Swapping two same-path repository sources must change validation outcome."""
        extracted = interface_candidate()
        first = extracted["source"] | {"repo_id": "orders-a", "revision": "aaaa"}
        second = extracted["source"] | {"repo_id": "orders-b", "revision": "bbbb"}
        entity = {key: value for key, value in extracted.items() if key != "source"}
        entity["sources"] = [second, first]
        surface = {
            "version": 1,
            "candidate_id": "candidate-001",
            "snapshot_id": "b" * 64,
            "entities": [entity],
            "review_groups": [{"group_id": "orders:http", "display_name": "Orders / HTTP", "entity_keys": [entity["canonical_key"]]}],
            "conflicts": [],
            "possible_duplicates": [],
            "repository_diagnostics": [],
            "warnings": [],
        }

        with self.assertRaisesRegex(ValueError, "entity sources"):
            contracts.validate_artifact(surface, "methodology-surface-candidate.schema.json")

    def test_surface_decisions_allow_manual_addition_without_caller_source(self) -> None:
        """Manual additions are normalized later by the review applicator, not callers."""
        decisions = {
            "version": 1,
            "candidate_id": "candidate-001",
            "accept_all": False,
            "include": ["http:orders:POST:/documents"],
            "exclude": [],
            "add": [
                {
                    "entity_type": "flow",
                    "canonical_key": "flow:orders:document-created",
                    "display_name": "Document created",
                    "attributes": {"protocol": "HTTP", "tags": ["documents", "write"]},
                }
            ],
            "conflict_resolutions": [],
            "duplicate_merges": [],
        }
        contracts.validate_artifact(decisions, "methodology-surface-decisions.schema.json")
        decisions["add"][0]["source"] = valid_extractor_result()["candidates"][0]["source"]
        with self.assertRaisesRegex(ValueError, "source"):
            contracts.validate_artifact(decisions, "methodology-surface-decisions.schema.json")

    def test_frozen_models_serialize_complete_normalized_contracts(self) -> None:
        """Serialization must remain deterministic and never expose absolute paths."""
        budget = DiscoveryBudget(
            structured_file_bytes=5_242_880,
            document_count=20,
            document_file_bytes=1_048_576,
            source_marker_candidates=500,
        )
        source = SourceRecord(
            repo_id="orders-contracts",
            revision="0123456789abcdef",
            path="api/openapi.yaml",
            pointer="#/paths/~1documents/post",
            selection_reason="openapi-signature",
            sha256="a" * 64,
        )
        candidate = Candidate(
            entity_type="interface",
            canonical_key="http:orders:POST:/documents",
            display_name="POST /documents",
            service_identity_value="orders",
            service_identity_basis="manifest",
            attributes={"path": "/documents", "method": "POST", "operation": "POST /documents", "protocol": "HTTP"},
            source=source,
            confidence="confirmed",
        )
        result = ExtractorResult(
            extractor_id="openapi",
            extractor_version=1,
            repo_id="orders-contracts",
            snapshot_identity="commit:0123456789abcdef",
            candidates=(candidate,),
            warnings=(),
            errors=(),
            limit_reached=False,
        )

        self.assertEqual(
            budget.to_dict(),
            {"document_count": 20, "document_file_bytes": 1_048_576, "source_marker_candidates": 500, "structured_file_bytes": 5_242_880},
        )
        self.assertEqual(list(candidate.to_dict()["attributes"]), ["method", "operation", "path", "protocol"])
        self.assertEqual(result.to_dict(), valid_extractor_result())
        self.assertNotIn("C:/", repr(result.to_dict()))
        with self.assertRaises(FrozenInstanceError):
            source.path = "other.yaml"  # type: ignore[misc]

    def test_atomic_writer_produces_sorted_json(self) -> None:
        """A malformed or reordered write must not create non-deterministic artifacts."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "artifact.json"
            contracts.write_json_atomic(path, {"z": 1, "a": {"y": 2}})
            self.assertEqual(path.read_text(encoding="utf-8"), '{\n  "a": {\n    "y": 2\n  },\n  "z": 1\n}\n')


if __name__ == "__main__":
    unittest.main()

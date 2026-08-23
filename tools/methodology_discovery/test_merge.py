"""Behavioral tests for deterministic system-level discovery merging."""

from __future__ import annotations

from copy import deepcopy
import json
import unittest

if __package__:
    from . import contracts, merge
else:
    import contracts
    import merge


SNAPSHOT_ID = "b" * 64


def source(repo_id: str, path: str, marker: str) -> dict:
    return {
        "repo_id": repo_id,
        "revision": f"revision-{repo_id}",
        "path": path,
        "pointer": f"#{marker}",
        "selection_reason": "test-fixture",
        "sha256": marker * 64,
    }


def candidate(
    repo_id: str,
    canonical_key: str,
    *,
    entity_type: str = "interface",
    identity: str = "orders",
    basis: str = "manifest",
    attributes: dict | None = None,
    confidence: str = "confirmed",
    marker: str = "a",
) -> dict:
    return {
        "entity_type": entity_type,
        "canonical_key": canonical_key,
        "display_name": canonical_key.rsplit(":", 1)[-1],
        "service_identity": {"value": identity, "basis": basis},
        "attributes": attributes or {},
        "source": source(repo_id, f"src/{repo_id}.yaml", marker),
        "confidence": confidence,
    }


def result(repo_id: str, candidates: list[dict], *, warnings: list[dict] | None = None) -> dict:
    return {
        "version": 1,
        "extractor_id": f"fixture-{repo_id}",
        "extractor_version": 1,
        "repo_id": repo_id,
        "snapshot_identity": f"commit:{repo_id}",
        "candidates": candidates,
        "warnings": warnings or [],
        "errors": [],
        "limit_reached": False,
    }


class MergeResultsTests(unittest.TestCase):
    def test_result_cannot_inject_a_candidate_source_from_another_repository(self) -> None:
        """Repository-scoped identity must be derived from provenance owned by the result."""
        injected = result(
            "contracts",
            [
                candidate(
                    "backend",
                    "http:repo-backend:GET:/health",
                    identity="repo-backend",
                    basis="unknown",
                    attributes={"protocol": "HTTP", "method": "GET", "path": "/health"},
                )
            ],
        )

        with self.assertRaisesRegex(ValueError, "source repo_id.*extractor result"):
            merge.merge_results(SNAPSHOT_ID, [injected], [])

    def test_explicit_identity_merges_sources_and_preserves_scalar_conflict_provenance(self) -> None:
        """A confidence change must never discard one competing scalar value or source."""
        contracts_result = result(
            "contracts",
            [
                candidate(
                    "contracts",
                    "http:orders:post://documents/",
                    attributes={
                        "protocol": "http",
                        "method": "post",
                        "path": "//documents/",
                        "operation": "post //documents/",
                        "summary": "Create from contract",
                    },
                    marker="a",
                )
            ],
        )
        backend_result = result(
            "backend",
            [
                candidate(
                    "backend",
                    "http:orders:POST:/documents",
                    attributes={
                        "protocol": "HTTP",
                        "method": "POST",
                        "path": "/documents",
                        "operation": "POST /documents",
                        "summary": "Create from code",
                    },
                    confidence="candidate",
                    marker="c",
                )
            ],
        )

        merged = merge.merge_results(SNAPSHOT_ID, [backend_result, contracts_result], [])

        contracts.validate_artifact(merged, "methodology-surface-candidate.schema.json")
        self.assertEqual(len(merged["entities"]), 1)
        entity = merged["entities"][0]
        self.assertEqual(entity["canonical_key"], "http:orders:POST:/documents")
        self.assertEqual([item["repo_id"] for item in entity["sources"]], ["backend", "contracts"])
        self.assertNotIn("summary", entity["attributes"])
        self.assertEqual(len(merged["conflicts"]), 1)
        conflict = merged["conflicts"][0]
        self.assertEqual(conflict["canonical_key"], entity["canonical_key"])
        self.assertEqual(conflict["attribute"], "summary")
        self.assertEqual(
            [(item["value"], [source["repo_id"] for source in item["sources"]]) for item in conflict["values"]],
            [("Create from code", ["backend"]), ("Create from contract", ["contracts"])],
        )

    def test_unknown_identity_stays_repo_scoped_and_only_groups_by_protocol_signature(self) -> None:
        """Removing repository scope from an unknown identity must auto-merge unrelated evidence."""
        first = result(
            "contracts",
            [
                candidate(
                    "contracts",
                    "http:anything:get:/documents/{ DocumentId }/",
                    identity="repo-contracts",
                    basis="unknown",
                    attributes={"protocol": "HTTP", "method": "get", "path": "/documents/{ DocumentId }/"},
                    marker="a",
                )
            ],
        )
        second = result(
            "backend",
            [
                candidate(
                    "backend",
                    "http:same:get:/documents/{documentid}",
                    identity="repo-backend",
                    basis="unknown",
                    attributes={"protocol": "http", "method": "GET", "path": "//documents/{documentid}"},
                    marker="c",
                )
            ],
        )

        merged = merge.merge_results(SNAPSHOT_ID, [first, second], [])

        self.assertEqual(
            [entity["canonical_key"] for entity in merged["entities"]],
            [
                "http:repo-backend:GET:/documents/{documentid}",
                "http:repo-contracts:GET:/documents/{documentid}",
            ],
        )
        self.assertEqual(len(merged["possible_duplicates"]), 1)
        duplicate = merged["possible_duplicates"][0]
        self.assertEqual(duplicate["protocol_signature"], "http:GET:/documents/{documentid}")
        self.assertEqual(duplicate["entity_keys"], [entity["canonical_key"] for entity in merged["entities"]])
        self.assertEqual(merged["conflicts"], [])

    def test_protocol_keys_canonicalize_graphql_and_message_operations(self) -> None:
        """Changing root, field, channel, or direction normalization must split one operation."""
        value = result(
            "contracts",
            [
                candidate(
                    "contracts",
                    "graphql:wrong:mutation: createDocument ",
                    attributes={
                        "protocol": "graphql",
                        "root_operation": "mutation",
                        "field": " createDocument ",
                    },
                    marker="a",
                ),
                candidate(
                    "contracts",
                    "message:wrong: document.created :send",
                    attributes={
                        "protocol": "AsyncAPI",
                        "channel": " document.created ",
                        "direction": "send",
                    },
                    marker="c",
                ),
            ],
        )

        merged = merge.merge_results(SNAPSHOT_ID, [value], [])

        self.assertEqual(
            [entity["canonical_key"] for entity in merged["entities"]],
            [
                "graphql:orders:Mutation:createDocument",
                "message:orders:document.created:publish",
            ],
        )
        by_key = {item["canonical_key"]: item for item in merged["entities"]}
        self.assertEqual(by_key["graphql:orders:Mutation:createDocument"]["attributes"]["root_operation"], "Mutation")
        self.assertEqual(by_key["message:orders:document.created:publish"]["attributes"]["direction"], "publish")

    def test_only_explicit_flow_entities_survive_and_review_groups_are_stable(self) -> None:
        """A relationship or similarly named attribute must never synthesize a business flow."""
        value = result(
            "docs",
            [
                candidate(
                    "docs",
                    "flow:orders:document-created",
                    entity_type="flow",
                    attributes={"protocol": "Documented", "description": "Document created"},
                    marker="d",
                ),
                candidate(
                    "docs",
                    "integration:orders:archive",
                    entity_type="integration",
                    attributes={"protocol": "HTTP", "flow": "looks flow-like"},
                    marker="e",
                ),
                candidate(
                    "docs",
                    "component:orders:api",
                    entity_type="component",
                    attributes={"kind": "service"},
                    marker="f",
                ),
            ],
        )

        merged = merge.merge_results(SNAPSHOT_ID, [value], [])

        self.assertEqual([item["entity_type"] for item in merged["entities"]].count("flow"), 1)
        self.assertEqual([group["group_id"] for group in merged["review_groups"]], sorted(group["group_id"] for group in merged["review_groups"]))
        for group in merged["review_groups"]:
            self.assertEqual(group["entity_keys"], sorted(group["entity_keys"]))

    def test_candidate_json_and_id_ignore_all_caller_order_and_do_not_mutate_inputs(self) -> None:
        """Permuting results, entities, sources, and diagnostics must not change canonical bytes."""
        one = candidate(
            "contracts",
            "http:orders:POST:/documents",
            attributes={"summary": "B", "path": "/documents", "method": "POST", "protocol": "HTTP"},
            marker="a",
        )
        two = candidate(
            "backend",
            "http:orders:post:/documents/",
            attributes={"protocol": "http", "method": "post", "path": "/documents/", "summary": "A"},
            marker="c",
        )
        three = candidate(
            "infra",
            "component:orders:api",
            entity_type="component",
            attributes={"name": "api", "kind": "Deployment"},
            marker="d",
        )
        results = [
            result("contracts", [one], warnings=[{"code": "z-warning", "message": "Z", "path": "z.txt"}]),
            result("backend", [two]),
            result("infra", [three], warnings=[{"code": "a-warning", "message": "A"}]),
        ]
        diagnostics = [
            {"repo_id": "infra", "diagnostics": [{"code": "z", "message": "last"}, {"code": "a", "message": "first"}]},
            {"repo_id": "backend", "diagnostics": []},
        ]
        original_results = deepcopy(results)
        original_diagnostics = deepcopy(diagnostics)

        first = merge.merge_results(SNAPSHOT_ID, results, diagnostics)
        reversed_results = deepcopy(list(reversed(results)))
        for item in reversed_results:
            item["candidates"].reverse()
            item["warnings"].reverse()
        reversed_diagnostics = deepcopy(list(reversed(diagnostics)))
        for item in reversed_diagnostics:
            item["diagnostics"].reverse()
        second = merge.merge_results(SNAPSHOT_ID, reversed_results, reversed_diagnostics)

        canonical = lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        self.assertEqual(canonical(first), canonical(second))
        self.assertEqual(first["candidate_id"], second["candidate_id"])
        self.assertRegex(first["candidate_id"], r"^[0-9a-f]{64}$")
        self.assertEqual(results, original_results)
        self.assertEqual(diagnostics, original_diagnostics)


if __name__ == "__main__":
    unittest.main()

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
    display_name: str | None = None,
) -> dict:
    return {
        "entity_type": entity_type,
        "canonical_key": canonical_key,
        "display_name": display_name or canonical_key.rsplit(":", 1)[-1],
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
    def test_stable_key_prefix_is_authoritative_over_incidental_message_attributes(self) -> None:
        """A component destination/channel must never reclassify it as a message entity."""
        value = result(
            "infra",
            [
                candidate(
                    "infra",
                    "component:orders:worker",
                    entity_type="component",
                    attributes={
                        "kind": "Deployment",
                        "destination": "document.created",
                        "channel": "ops",
                        "direction": "send",
                    },
                )
            ],
        )

        merged = merge.merge_results(SNAPSHOT_ID, [value], [])

        self.assertEqual(merged["entities"][0]["canonical_key"], "component:orders:worker")
        self.assertEqual(merged["entities"][0]["entity_type"], "component")
        self.assertEqual(merged["possible_duplicates"], [])

    def test_attribute_arrays_preserve_order_and_duplicates_and_different_orders_conflict(self) -> None:
        """Treating ordered JSON arrays as sets must erase semantic conflicts."""
        first = candidate(
            "contracts",
            "http:orders:POST:/documents",
            attributes={"protocol": "HTTP", "method": "POST", "path": "/documents", "steps": ["a", "b", "a"]},
            marker="a",
        )
        second = candidate(
            "backend",
            "http:orders:POST:/documents",
            attributes={"protocol": "HTTP", "method": "POST", "path": "/documents", "steps": ["b", "a", "a"]},
            marker="b",
        )

        merged = merge.merge_results(
            SNAPSHOT_ID,
            [result("backend", [second]), result("contracts", [first])],
            [],
        )

        conflict = next(item for item in merged["conflicts"] if item["attribute"] == "steps")
        self.assertEqual(
            {json.dumps(item["value"]) for item in conflict["values"]},
            {'["a", "b", "a"]', '["b", "a", "a"]'},
        )
        single = merge.merge_results(SNAPSHOT_ID, [result("contracts", [first])], [])
        self.assertEqual(single["entities"][0]["attributes"]["steps"], ["a", "b", "a"])

    def test_top_level_fact_disagreements_become_visible_source_linked_conflicts(self) -> None:
        """Entity type, display name, and atomic service identity must not get silent winners."""
        first = candidate(
            "contracts",
            "http:orders:POST:/documents",
            entity_type="interface",
            basis="manifest",
            display_name="Create contract document",
            attributes={"protocol": "HTTP", "method": "POST", "path": "/documents"},
            marker="a",
        )
        second = candidate(
            "backend",
            "http:orders:POST:/documents",
            entity_type="integration",
            basis="contract",
            display_name="Create backend document",
            attributes={"protocol": "HTTP", "method": "POST", "path": "/documents"},
            marker="b",
        )

        merged = merge.merge_results(
            SNAPSHOT_ID,
            [result("contracts", [first]), result("backend", [second])],
            [],
        )

        conflicts = {item["attribute"]: item for item in merged["conflicts"]}
        self.assertEqual(
            set(conflicts),
            {"__entity_type__", "__display_name__", "__service_identity__"},
        )
        self.assertEqual(
            {tuple(item["value"]) for item in conflicts["__service_identity__"]["values"]},
            {("orders", "contract"), ("orders", "manifest")},
        )
        for conflict in conflicts.values():
            self.assertEqual(
                sorted(source["repo_id"] for value in conflict["values"] for source in value["sources"]),
                ["backend", "contracts"],
            )

    def test_duplicate_signature_links_explicit_to_unknown_and_metadata_but_not_explicit_only(self) -> None:
        """A fallback candidate must see explicit peers while two explicit services stay separate."""
        def http(repo_id: str, identity: str, basis: str, marker: str) -> dict:
            return candidate(
                repo_id,
                f"http:{identity}:GET:/health",
                identity=identity,
                basis=basis,
                attributes={"protocol": "HTTP", "method": "GET", "path": "/health"},
                marker=marker,
            )

        manifest = result("manifest", [http("manifest", "orders", "manifest", "a")])
        unknown = result("unknown", [http("unknown", "repo-unknown", "unknown", "b")])
        metadata = result("metadata", [http("metadata", "orders-title", "metadata", "c")])
        contract = result("contract", [http("contract", "billing", "contract", "d")])

        manifest_unknown = merge.merge_results(SNAPSHOT_ID, [manifest, unknown], [])
        self.assertEqual(len(manifest_unknown["possible_duplicates"]), 1)
        self.assertEqual(
            manifest_unknown["possible_duplicates"][0]["entity_keys"],
            ["http:orders:GET:/health", "http:repo-unknown:GET:/health"],
        )
        manifest_metadata = merge.merge_results(SNAPSHOT_ID, [manifest, metadata], [])
        self.assertEqual(len(manifest_metadata["possible_duplicates"]), 1)
        self.assertIn("http:repo-metadata:GET:/health", manifest_metadata["possible_duplicates"][0]["entity_keys"])
        explicit_only = merge.merge_results(SNAPSHOT_ID, [manifest, contract], [])
        self.assertEqual(explicit_only["possible_duplicates"], [])

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
                    display_name="POST /documents",
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
                    display_name="POST /documents",
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

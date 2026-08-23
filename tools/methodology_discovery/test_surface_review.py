"""Behavioral tests for applying grouped surface decisions."""

from __future__ import annotations

from copy import deepcopy
import unittest

if __package__:
    from . import contracts, merge, surface_review
    from .test_merge import SNAPSHOT_ID, candidate, result
else:
    import contracts
    import merge
    import surface_review
    from test_merge import SNAPSHOT_ID, candidate, result


def merged_candidate(*, conflict: bool = False, duplicates: bool = False) -> dict:
    candidates = [
        candidate(
            "contracts",
            "http:orders:POST:/documents",
            attributes={
                "protocol": "HTTP",
                "method": "POST",
                "path": "/documents",
                "summary": "Contract summary",
            },
            marker="a",
        ),
        candidate(
            "backend",
            "http:orders:GET:/actuator/health",
            attributes={"protocol": "HTTP", "method": "GET", "path": "/actuator/health"},
            confidence="candidate",
            marker="b",
        ),
    ]
    values = [result("contracts", [candidates[0]]), result("backend", [candidates[1]])]
    if conflict:
        values.append(
            result(
                "backend-contract",
                [
                    candidate(
                        "backend-contract",
                        "http:orders:POST:/documents",
                        attributes={
                            "protocol": "HTTP",
                            "method": "POST",
                            "path": "/documents",
                            "summary": "Code summary",
                        },
                        confidence="candidate",
                        marker="c",
                    )
                ],
            )
        )
    if duplicates:
        values.extend(
            [
                result(
                    "unknown-a",
                    [
                        candidate(
                            "unknown-a",
                            "graphql:any:query:health",
                            identity="repo-unknown-a",
                            basis="unknown",
                            attributes={"protocol": "GraphQL", "root_operation": "Query", "field": "health"},
                            marker="d",
                        )
                    ],
                ),
                result(
                    "unknown-b",
                    [
                        candidate(
                            "unknown-b",
                            "graphql:any:Query:health",
                            identity="repo-unknown-b",
                            basis="unknown",
                            attributes={"protocol": "GraphQL", "root_operation": "Query", "field": "health"},
                            marker="e",
                        )
                    ],
                ),
            ]
        )
    return merge.merge_results(SNAPSHOT_ID, values, [])


def decisions_for(candidate_value: dict, **overrides: object) -> dict:
    value = {
        "version": 1,
        "candidate_id": candidate_value["candidate_id"],
        "accept_all": True,
        "include": [],
        "exclude": [],
        "add": [],
        "conflict_resolutions": [],
        "duplicate_merges": [],
    }
    value.update(overrides)
    return value


class SurfaceReviewTests(unittest.TestCase):
    def test_top_level_conflict_resolutions_update_fields_not_reserved_attributes(self) -> None:
        """Reserved resolutions must update entity fields instead of leaking into attributes."""
        first = candidate(
            "contracts",
            "http:orders:POST:/documents",
            entity_type="interface",
            basis="manifest",
            display_name="Contract name",
            attributes={"protocol": "HTTP", "method": "POST", "path": "/documents"},
            marker="a",
        )
        second = candidate(
            "backend",
            "http:orders:POST:/documents",
            entity_type="integration",
            basis="contract",
            display_name="Backend name",
            attributes={"protocol": "HTTP", "method": "POST", "path": "/documents"},
            marker="b",
        )
        candidate_value = merge.merge_results(
            SNAPSHOT_ID,
            [result("contracts", [first]), result("backend", [second])],
            [],
        )
        resolutions = []
        selected = {
            "__entity_type__": "integration",
            "__display_name__": "Backend name",
            "__service_identity__": ["orders", "contract"],
        }
        for conflict in candidate_value["conflicts"]:
            resolutions.append({"conflict_id": conflict["conflict_id"], "value": selected[conflict["attribute"]]})

        review = surface_review.apply_surface_decisions(
            candidate_value,
            decisions_for(candidate_value, conflict_resolutions=resolutions),
        )

        entity = review["included"][0]
        self.assertEqual(entity["entity_type"], "integration")
        self.assertEqual(entity["display_name"], "Backend name")
        self.assertTrue(set(selected).isdisjoint(entity["attributes"]))

    def test_review_groups_must_equal_deterministic_derivation_even_when_id_is_unchanged(self) -> None:
        """Tampered group IDs, labels, membership, order, or coverage must not be trusted."""
        candidate_value = merged_candidate(duplicates=True)
        mutations = (
            lambda value: value["review_groups"][0].__setitem__("display_name", "tampered"),
            lambda value: value["review_groups"][0].__setitem__("group_id", "tampered"),
            lambda value: value["review_groups"].reverse(),
            lambda value: value["review_groups"].pop(),
        )
        for mutate in mutations:
            tampered = deepcopy(candidate_value)
            mutate(tampered)
            with self.subTest(groups=tampered["review_groups"]), self.assertRaisesRegex(ValueError, "review_groups.*(derivation|sorted)"):
                surface_review.apply_surface_decisions(tampered, decisions_for(candidate_value))

    def test_possible_duplicates_must_equal_protocol_derivation_without_fabrication_or_overlap(self) -> None:
        """A candidate cannot fabricate signatures, component duplicates, or overlapping groups."""
        candidate_value = merged_candidate(duplicates=True)
        fabricated_signature = deepcopy(candidate_value)
        fabricated_signature["possible_duplicates"][0]["protocol_signature"] = "component:fabricated"
        fabricated_signature["candidate_id"] = merge.candidate_id_for(fabricated_signature)

        overlapping = deepcopy(candidate_value)
        duplicate = deepcopy(overlapping["possible_duplicates"][0])
        duplicate["duplicate_id"] = "duplicate:overlap"
        overlapping["possible_duplicates"].append(duplicate)
        overlapping["candidate_id"] = merge.candidate_id_for(overlapping)

        component_candidate = merge.merge_results(
            SNAPSHOT_ID,
            [
                result("a", [candidate("a", "component:repo-a:worker", entity_type="component", identity="repo-a", basis="unknown", marker="a")]),
                result("b", [candidate("b", "component:repo-b:worker", entity_type="component", identity="repo-b", basis="unknown", marker="b")]),
            ],
            [],
        )
        fabricated_component = deepcopy(component_candidate)
        fabricated_component["possible_duplicates"] = [{
            "duplicate_id": "duplicate:component",
            "protocol_signature": "component:worker",
            "entity_keys": [item["canonical_key"] for item in fabricated_component["entities"]],
        }]
        fabricated_component["candidate_id"] = merge.candidate_id_for(fabricated_component)

        for tampered in (fabricated_signature, overlapping, fabricated_component):
            with self.subTest(duplicates=tampered["possible_duplicates"]), self.assertRaisesRegex(ValueError, "possible_duplicates.*derivation"):
                surface_review.apply_surface_decisions(tampered, decisions_for(tampered))

    def test_null_candidate_manual_and_conflict_values_are_omitted_from_confirmed_review(self) -> None:
        """Null means unresolved and must not cross the non-null Plan 1 review bridge."""
        first = candidate(
            "contracts",
            "http:orders:POST:/documents",
            attributes={
                "protocol": "HTTP",
                "method": "POST",
                "path": "/documents",
                "optional": None,
                "ordered": ["a", None, "a", None],
                "summary": None,
            },
            marker="a",
        )
        second = candidate(
            "backend",
            "http:orders:POST:/documents",
            attributes={
                "protocol": "HTTP",
                "method": "POST",
                "path": "/documents",
                "optional": None,
                "ordered": ["a", None, "a", None],
                "summary": "known",
            },
            marker="b",
        )
        candidate_value = merge.merge_results(
            SNAPSHOT_ID,
            [result("contracts", [first]), result("backend", [second])],
            [],
        )
        summary_conflict = next(item for item in candidate_value["conflicts"] if item["attribute"] == "summary")
        manual = {
            "entity_type": "flow",
            "canonical_key": "flow:orders:manual",
            "display_name": "Manual flow",
            "attributes": {"optional": None, "ordered": ["x", None, "x"]},
        }

        review = surface_review.apply_surface_decisions(
            candidate_value,
            decisions_for(
                candidate_value,
                add=[manual],
                conflict_resolutions=[{"conflict_id": summary_conflict["conflict_id"], "value": None}],
            ),
        )

        discovered = review["included"][0]
        self.assertNotIn("optional", discovered["attributes"])
        self.assertNotIn("summary", discovered["attributes"])
        self.assertEqual(discovered["attributes"]["ordered"], ["a", "a"])
        self.assertNotIn("optional", review["added"][0]["attributes"])
        self.assertEqual(review["added"][0]["attributes"]["ordered"], ["x", "x"])
        contracts.validate_artifact(review, "methodology-surface-review.schema.json")

    def test_accept_all_resolves_conflicts_excludes_with_scope_reason_and_adds_manual_source(self) -> None:
        """Review output must not lose exclusions/provenance or leak candidate-only fields."""
        candidate_value = merged_candidate(conflict=True)
        conflict = candidate_value["conflicts"][0]
        decisions = decisions_for(
            candidate_value,
            exclude=["http:orders:GET:/actuator/health"],
            add=[
                {
                    "entity_type": "interface",
                    "canonical_key": "graphql:orders:Mutation:createDocument",
                    "display_name": "Mutation.createDocument",
                    "attributes": {"protocol": "GraphQL", "root_operation": "Mutation", "field": "createDocument"},
                }
            ],
            conflict_resolutions=[{"conflict_id": conflict["conflict_id"], "value": "Code summary"}],
        )

        review = surface_review.apply_surface_decisions(candidate_value, decisions)

        contracts.validate_artifact(review, "methodology-surface-review.schema.json")
        self.assertEqual(review["snapshot_id"], SNAPSHOT_ID)
        self.assertEqual(review["status"], "confirmed")
        self.assertEqual([item["canonical_key"] for item in review["included"]], ["http:orders:POST:/documents"])
        self.assertEqual(review["included"][0]["attributes"]["summary"], "Code summary")
        excluded = review["excluded"][0]
        self.assertEqual(excluded["canonical_key"], "http:orders:GET:/actuator/health")
        self.assertEqual(excluded["attributes"]["exclusion_reason"], "scope-excluded")
        self.assertTrue(excluded["sources"])
        self.assertNotIn("does not exist", repr(excluded).casefold())
        manual = review["added"][0]
        self.assertEqual(manual["sources"], [{
            "repo_id": "user",
            "revision": candidate_value["candidate_id"],
            "relative_path": "surface-review",
            "pointer": "graphql:orders:Mutation:createDocument",
            "selection_reason": "manual-addition",
            "sha256": candidate_value["candidate_id"],
        }])
        for collection in ("included", "excluded", "added"):
            for entity in review[collection]:
                self.assertNotIn("confidence", entity)
                self.assertNotIn("service_identity", entity)
                self.assertTrue(all("relative_path" in item and "path" not in item for item in entity["sources"]))

    def test_accept_all_false_includes_only_explicit_keys_and_classifies_the_rest_excluded(self) -> None:
        """A false accept_all flag must never silently include an unlisted candidate."""
        candidate_value = merged_candidate()
        review = surface_review.apply_surface_decisions(
            candidate_value,
            decisions_for(candidate_value, accept_all=False, include=["http:orders:POST:/documents"]),
        )

        self.assertEqual([item["canonical_key"] for item in review["included"]], ["http:orders:POST:/documents"])
        self.assertEqual([item["canonical_key"] for item in review["excluded"]], ["http:orders:GET:/actuator/health"])

    def test_candidate_and_decisions_are_schema_validated_before_references_are_applied(self) -> None:
        """Malformed closed artifacts must fail at the boundary instead of being partially applied."""
        candidate_value = merged_candidate()
        malformed_candidate = deepcopy(candidate_value)
        malformed_candidate["unexpected"] = True
        with self.assertRaisesRegex(ValueError, "methodology-surface-candidate"):
            surface_review.apply_surface_decisions(malformed_candidate, decisions_for(candidate_value))

        malformed_decisions = decisions_for(candidate_value)
        malformed_decisions["unexpected"] = True
        with self.assertRaisesRegex(ValueError, "methodology-surface-decisions"):
            surface_review.apply_surface_decisions(candidate_value, malformed_decisions)

    def test_rejects_schema_valid_candidate_content_with_a_stale_integrity_id(self) -> None:
        """Changing canonical candidate content without its ID must invalidate prior decisions."""
        candidate_value = merged_candidate()
        mutations = (
            lambda value: value["entities"][0].__setitem__("display_name", "Tampered but schema-valid"),
            lambda value: value.__setitem__("warnings", [{"code": "tampered", "message": "Changed diagnostic"}]),
        )
        for mutate in mutations:
            tampered = deepcopy(candidate_value)
            mutate(tampered)
            with self.subTest(tampered=tampered), self.assertRaisesRegex(ValueError, "candidate_id.*content"):
                surface_review.apply_surface_decisions(tampered, decisions_for(candidate_value))

    def test_rejects_candidate_internal_dangling_entity_references(self) -> None:
        """Schema-valid review groups and duplicate groups must still reference real entities."""
        ordinary = merged_candidate()
        dangling_review_group = deepcopy(ordinary)
        dangling_review_group["review_groups"][0]["entity_keys"] = ["http:orders:GET:/missing"]
        dangling_review_group["candidate_id"] = merge.candidate_id_for(dangling_review_group)

        with self.assertRaisesRegex(ValueError, "review group.*unknown entity"):
            surface_review.apply_surface_decisions(
                dangling_review_group, decisions_for(dangling_review_group)
            )

        duplicate_candidate = merged_candidate(duplicates=True)
        dangling_duplicate = deepcopy(duplicate_candidate)
        dangling_duplicate["possible_duplicates"][0]["entity_keys"][0] = "graphql:missing:Query:health"
        dangling_duplicate["candidate_id"] = merge.candidate_id_for(dangling_duplicate)

        with self.assertRaisesRegex(ValueError, "possible duplicate.*unknown entity"):
            surface_review.apply_surface_decisions(
                dangling_duplicate, decisions_for(dangling_duplicate)
            )

    def test_rejects_stale_unknown_duplicate_and_overlapping_entity_references(self) -> None:
        """Every include/exclude reference must be unique, current, known, and unambiguous."""
        candidate_value = merged_candidate()
        cases = (
            (decisions_for(candidate_value, candidate_id="stale"), "candidate_id"),
            (decisions_for(candidate_value, include=["http:orders:GET:/missing"]), "unknown entity"),
            (decisions_for(candidate_value, exclude=["http:orders:GET:/missing"]), "unknown entity"),
            (decisions_for(candidate_value, include=["http:orders:POST:/documents"], exclude=["http:orders:POST:/documents"]), "include and exclude"),
            (decisions_for(candidate_value, include=["http:orders:POST:/documents", "http:orders:POST:/documents"]), "methodology-surface-decisions"),
        )
        for decisions, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                surface_review.apply_surface_decisions(candidate_value, decisions)

    def test_every_conflict_has_exactly_one_resolution_to_an_offered_value(self) -> None:
        """Missing, repeated, unknown, or invented resolutions must never pick a scalar winner."""
        candidate_value = merged_candidate(conflict=True)
        conflict = candidate_value["conflicts"][0]
        valid = {"conflict_id": conflict["conflict_id"], "value": conflict["values"][0]["value"]}
        cases = (
            ([], "unresolved conflict"),
            ([valid, valid], "duplicate conflict resolution"),
            ([{"conflict_id": "unknown", "value": valid["value"]}], "unknown conflict"),
            ([{"conflict_id": conflict["conflict_id"], "value": "invented"}], "offered value"),
        )
        for resolutions, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                surface_review.apply_surface_decisions(
                    candidate_value,
                    decisions_for(candidate_value, conflict_resolutions=resolutions),
                )

    def test_manual_additions_reject_sources_duplicate_keys_and_candidate_collisions(self) -> None:
        """A caller source or duplicate key must never impersonate confirmed discovery evidence."""
        candidate_value = merged_candidate()
        manual = {
            "entity_type": "flow",
            "canonical_key": "flow:orders:document-created",
            "display_name": "Document created",
            "attributes": {"description": "Explicit manual fact"},
        }
        supplied_source = deepcopy(manual)
        supplied_source["sources"] = [{"repo_id": "attacker"}]
        cases = (
            ([supplied_source], "methodology-surface-decisions"),
            ([manual, deepcopy(manual)], "duplicate manual"),
            ([manual | {"canonical_key": "http:orders:POST:/documents"}], "already exists"),
        )
        for additions, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                surface_review.apply_surface_decisions(
                    candidate_value,
                    decisions_for(candidate_value, add=additions),
                )

    def test_manual_addition_cannot_reuse_an_original_key_removed_by_duplicate_merge(self) -> None:
        """Duplicate merging must not make an original discovery key available for manual reuse."""
        candidate_value = merged_candidate(duplicates=True)
        duplicate = candidate_value["possible_duplicates"][0]
        target, removed = duplicate["entity_keys"]
        manual = {
            "entity_type": "interface",
            "canonical_key": removed,
            "display_name": "Impersonated removed candidate",
            "attributes": {"protocol": "GraphQL", "root_operation": "Query", "field": "health"},
        }

        with self.assertRaisesRegex(ValueError, "already exists"):
            surface_review.apply_surface_decisions(
                candidate_value,
                decisions_for(
                    candidate_value,
                    add=[manual],
                    duplicate_merges=[{"duplicate_id": duplicate["duplicate_id"], "canonical_key": target}],
                ),
            )

    def test_valid_duplicate_merge_uses_a_member_key_and_preserves_all_sources(self) -> None:
        """Merging a possible duplicate must retain provenance from every reviewed entity."""
        candidate_value = merged_candidate(duplicates=True)
        duplicate = candidate_value["possible_duplicates"][0]
        target = duplicate["entity_keys"][0]

        review = surface_review.apply_surface_decisions(
            candidate_value,
            decisions_for(candidate_value, duplicate_merges=[{"duplicate_id": duplicate["duplicate_id"], "canonical_key": target}]),
        )

        merged_entity = next(item for item in review["included"] if item["canonical_key"] == target)
        self.assertEqual([item["repo_id"] for item in merged_entity["sources"]], ["unknown-a", "unknown-b"])
        self.assertFalse(any(item["canonical_key"] in duplicate["entity_keys"][1:] for item in review["included"]))
        contracts.validate_artifact(review, "methodology-surface-review.schema.json")

    def test_rejects_invalid_or_duplicate_duplicate_merges(self) -> None:
        """Unknown groups, non-member targets, and repeated decisions must not lose an entity."""
        candidate_value = merged_candidate(duplicates=True)
        duplicate = candidate_value["possible_duplicates"][0]
        valid = {"duplicate_id": duplicate["duplicate_id"], "canonical_key": duplicate["entity_keys"][0]}
        cases = (
            ([{"duplicate_id": "unknown", "canonical_key": duplicate["entity_keys"][0]}], "unknown duplicate"),
            ([{"duplicate_id": duplicate["duplicate_id"], "canonical_key": "http:orders:POST:/documents"}], "member"),
            ([valid, valid], "duplicate duplicate merge"),
        )
        for duplicate_merges, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                surface_review.apply_surface_decisions(
                    candidate_value,
                    decisions_for(candidate_value, duplicate_merges=duplicate_merges),
                )

    def test_duplicate_merge_cannot_override_mixed_include_and_exclude_scope(self) -> None:
        """A merge decision must not smuggle an explicitly unselected member into scope."""
        candidate_value = merged_candidate(duplicates=True)
        duplicate = candidate_value["possible_duplicates"][0]
        target = duplicate["entity_keys"][0]

        with self.assertRaisesRegex(ValueError, "different scope decisions"):
            surface_review.apply_surface_decisions(
                candidate_value,
                decisions_for(
                    candidate_value,
                    accept_all=False,
                    include=[target],
                    duplicate_merges=[{"duplicate_id": duplicate["duplicate_id"], "canonical_key": target}],
                ),
            )

    def test_output_arrays_are_sorted_and_caller_inputs_remain_unchanged(self) -> None:
        """Applying decisions must be deterministic without sorting caller-owned lists in place."""
        candidate_value = merged_candidate()
        decisions = decisions_for(
            candidate_value,
            accept_all=False,
            include=["http:orders:POST:/documents"],
            add=[
                {"entity_type": "flow", "canonical_key": "flow:orders:z", "display_name": "Z", "attributes": {}},
                {"entity_type": "component", "canonical_key": "component:orders:a", "display_name": "A", "attributes": {}},
            ],
        )
        original_candidate = deepcopy(candidate_value)
        original_decisions = deepcopy(decisions)

        review = surface_review.apply_surface_decisions(candidate_value, decisions)

        for name in ("included", "excluded", "added"):
            keys = [(item["entity_type"], item["canonical_key"]) for item in review[name]]
            self.assertEqual(keys, sorted(keys))
        self.assertEqual(candidate_value, original_candidate)
        self.assertEqual(decisions, original_decisions)


if __name__ == "__main__":
    unittest.main()

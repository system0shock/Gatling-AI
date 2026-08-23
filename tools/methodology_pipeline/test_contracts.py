#!/usr/bin/env python3
"""Behavior tests for methodology-first configuration contracts."""

from __future__ import annotations

import unittest
from pathlib import Path

if __package__:
    from . import contracts
    from .sections import CANONICAL_HEADINGS
else:
    import contracts
    from sections import CANONICAL_HEADINGS


REPO_ROOT = Path(__file__).resolve().parents[2]


class MethodologyAssetContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.package = REPO_ROOT / ".gigacode" / "skills" / "manage-methodology"

    def test_default_profile_contains_approved_values(self) -> None:
        profile = contracts.load_yaml_mapping(
            self.package / "profiles" / "default-v1.yaml",
            "methodology-profile.schema.json",
        )
        self.assertEqual(profile["profile_id"], "default-v1")
        self.assertEqual(profile["profile_version"], 1)
        self.assertEqual(profile["tests"]["maximum_search"]["step_minutes"], 20)
        self.assertEqual(profile["tests"]["maximum_confirmation"]["duration_minutes"], 120)
        self.assertEqual(profile["tests"]["stability"]["duration_minutes"], 480)
        self.assertEqual(profile["tests"]["stability"]["load_factor"], 0.8)
        self.assertEqual(profile["criteria"]["response_time"]["percentile"], "p95")
        self.assertEqual(profile["criteria"]["response_time"]["threshold_ms"], 1000)
        self.assertEqual(profile["criteria"]["technical_errors"]["max_percent"], 5)
        self.assertEqual(profile["criteria"]["cpu"]["max_percent"], 40)
        self.assertEqual(profile["criteria"]["memory"]["max_percent"], 80)

    def test_question_ids_and_targets_are_unique(self) -> None:
        catalog = contracts.load_yaml_mapping(
            self.package / "questions.yaml",
            "methodology-questions.schema.json",
        )
        ids = [item["id"] for item in catalog["questions"]]
        targets = [item["target"] for item in catalog["questions"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(targets), len(set(targets)))

    def test_template_contract_matches_all_canonical_headings(self) -> None:
        contract = contracts.load_yaml_mapping(
            self.package / "templates" / "methodology-template-contract.yaml",
            "methodology-template-contract.schema.json",
        )
        self.assertEqual(
            [item["heading"] for item in contract["sections"]],
            list(CANONICAL_HEADINGS),
        )


class MethodologySchemaBoundaryTest(unittest.TestCase):
    def test_profile_review_values_accept_scalar_arrays_but_questions_do_not(self) -> None:
        answers = {
            "version": 1,
            "profile": {
                "accepted": True,
                "meta_values": {"criteria.technical_errors.exclusions": {"value": ["timeout", "cancelled"], "source_reference": "runbook#42"}},
                "overrides": {},
            },
            "questions": {"load.initial": {"value": 20}},
            "not_applicable_sections": [],
        }
        contracts.validate_artifact(answers, "methodology-answers.schema.json")
        answers["questions"]["load.initial"]["value"] = [20]
        with self.assertRaisesRegex(ValueError, "is not of type"):
            contracts.validate_artifact(answers, "methodology-answers.schema.json")

    def test_profile_percentile_accepts_full_positive_range(self) -> None:
        profile = _profile(percentile="p0.1")
        contracts.validate_artifact(profile, "methodology-profile.schema.json")
        profile["criteria"]["response_time"]["percentile"] = "p100"
        contracts.validate_artifact(profile, "methodology-profile.schema.json")
        profile["criteria"]["response_time"]["percentile"] = "p0"
        with self.assertRaisesRegex(ValueError, "does not match"):
            contracts.validate_artifact(profile, "methodology-profile.schema.json")

    def test_input_rejects_malformed_embedded_profile_and_surface(self) -> None:
        value = _input()
        contracts.validate_artifact(value, "methodology-input.schema.json")
        value["profile"]["invented"] = True
        with self.assertRaisesRegex(ValueError, "Additional properties"):
            contracts.validate_artifact(value, "methodology-input.schema.json")
        value = _input()
        value["surface"]["status"] = "draft"
        with self.assertRaisesRegex(ValueError, "was expected"):
            contracts.validate_artifact(value, "methodology-input.schema.json")

    def test_surface_added_entities_require_user_surface_review_provenance(self) -> None:
        review = _surface()
        review["added"] = [_entity(repo_id="user", relative_path="surface-review")]
        contracts.validate_artifact(review, "methodology-surface-review.schema.json")
        review["added"][0]["sources"][0]["repo_id"] = "catalog"
        with self.assertRaisesRegex(ValueError, "was expected"):
            contracts.validate_artifact(review, "methodology-surface-review.schema.json")

    def test_canonical_headings_is_a_hashable_plain_tuple(self) -> None:
        self.assertIs(type(CANONICAL_HEADINGS), tuple)
        self.assertIsInstance(hash(CANONICAL_HEADINGS), int)

    def test_generation_state_uses_section_keyed_blocks(self) -> None:
        digest = "a" * 64
        state = {"version": 1, "blocks": {"scope": {"sha256": digest, "rendered_sha256": digest, "resolution": "rendered"}}}
        contracts.validate_artifact(state, "methodology-generation-state.schema.json")
        state["blocks"]["scope"]["rendered_sha256"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "hashes must match"):
            contracts.validate_artifact(state, "methodology-generation-state.schema.json")
        state["blocks"]["scope"]["resolution"] = "keep"
        contracts.validate_artifact(state, "methodology-generation-state.schema.json")

    def test_drift_decisions_use_section_keyed_actions(self) -> None:
        contracts.validate_artifact(
            {"version": 1, "decisions": {"scope": "keep", "risks": "move-to-manual"}},
            "methodology-drift-decisions.schema.json",
        )

    def test_readiness_report_has_downstream_shape(self) -> None:
        contracts.validate_artifact(
            {"version": 1, "status": "blocked", "ready_for_test": False, "workspace_snapshot_id": "b" * 64,
             "missing": [{"target": "load.initial", "question_id": "load.initial", "message": "Initial load is required"}]},
            "methodology-readiness-report.schema.json",
        )

    def test_template_report_has_complete_section_classifications(self) -> None:
        sections = [
            {"id": f"section-{index}", "heading": f"Section {index}", "status": "complete", "gaps": [], "question_links": []}
            for index in range(17)
        ]
        contracts.validate_artifact(
            {"version": 1, "status": "complete", "template_complete": True, "sections": sections},
            "methodology-template-report.schema.json",
        )

    def test_not_applicable_sections_require_explicit_reason(self) -> None:
        answers = {"version": 1, "profile": {"accepted": False, "meta_values": {}, "overrides": {}}, "questions": {},
                   "not_applicable_sections": [{"section_id": "integrations", "reason": "No external interfaces"}]}
        contracts.validate_artifact(answers, "methodology-answers.schema.json")
        answers["not_applicable_sections"] = ["integrations"]
        with self.assertRaisesRegex(ValueError, "is not of type"):
            contracts.validate_artifact(answers, "methodology-answers.schema.json")


def _profile(percentile: str = "p95") -> dict[str, object]:
    return {
        "version": 1, "profile_id": "default-v1", "profile_version": 1,
        "tests": {"maximum_search": {"step_minutes": 20}, "maximum_confirmation": {"duration_minutes": 120, "load_factor": 1.0}, "stability": {"duration_minutes": 480, "load_factor": 0.8}},
        "criteria": {"response_time": {"percentile": percentile, "threshold_ms": 1000}, "technical_errors": {"max_percent": 5, "exclusions": []}, "cpu": {"max_percent": 40, "scope": "one-openshift-arm"}, "memory": {"max_percent": 80, "no_sustained_growth": True}},
    }


def _entity(repo_id: str = "catalog", relative_path: str = "service.yaml") -> dict[str, object]:
    return {"entity_type": "service", "canonical_key": "orders", "display_name": "Orders", "attributes": {}, "sources": [{"repo_id": repo_id, "revision": "r1", "relative_path": relative_path, "pointer": "#", "selection_reason": "manual", "sha256": "a" * 64}]}


def _surface() -> dict[str, object]:
    return {"version": 1, "snapshot_id": "a" * 64, "status": "confirmed", "included": [], "excluded": [], "added": []}


def _input() -> dict[str, object]:
    return {"version": 1, "workspace_snapshot_id": "a" * 64, "surface": _surface(), "profile": _profile(), "load": {}, "environment": {}, "observability": {}, "test_data": {}, "document": {}, "not_applicable_sections": []}


if __name__ == "__main__":
    unittest.main()

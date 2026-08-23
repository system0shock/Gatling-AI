"""Behavior tests for deterministic methodology profile resolution."""

from __future__ import annotations

import unittest

from . import fixtures, profiles


class ProfileResolutionTest(unittest.TestCase):
    def test_user_override_wins_over_manual_meta_and_default(self) -> None:
        resolved = profiles.resolve_profile(
            fixtures.default_profile(),
            {
                "version": 1,
                "profile": {
                    "accepted": True,
                    "meta_values": {
                        "criteria.response_time.threshold_ms": {
                            "value": 800,
                            "source_reference": "META-42",
                        }
                    },
                    "overrides": {
                        "criteria.response_time.threshold_ms": {"value": 650}
                    },
                },
                "questions": {},
                "not_applicable_sections": [],
            },
        )
        self.assertEqual(resolved["criteria"]["response_time"]["threshold_ms"], 650)
        self.assertEqual(
            resolved["sources"]["criteria.response_time.threshold_ms"]["source"],
            "user",
        )

    def test_manual_meta_value_records_reference_and_acceptance(self) -> None:
        resolved = profiles.resolve_profile(
            fixtures.default_profile(),
            {
                "profile": {
                    "accepted": True,
                    "meta_values": {
                        "criteria.cpu.max_percent": {
                            "value": 35,
                            "source_reference": "runbook#cpu",
                        }
                    },
                    "overrides": {},
                }
            },
        )
        self.assertEqual(resolved["criteria"]["cpu"]["max_percent"], 35)
        self.assertEqual(
            resolved["sources"]["criteria.cpu.max_percent"],
            {"source": "meta-manual", "source_reference": "runbook#cpu"},
        )
        self.assertTrue(resolved["accepted"])

    def test_manual_meta_value_rejects_missing_null_and_blank_references(self) -> None:
        missing = object()
        for reference in (missing, None, "", " \t"):
            with self.subTest(
                reference="missing" if reference is missing else reference
            ):
                entry = {"value": 35}
                if reference is not missing:
                    entry["source_reference"] = reference
                with self.assertRaisesRegex(ValueError, "source_reference"):
                    profiles.resolve_profile(
                        fixtures.default_profile(),
                        {
                            "profile": {
                                "accepted": True,
                                "meta_values": {
                                    "criteria.cpu.max_percent": entry,
                                },
                                "overrides": {},
                            }
                        },
                    )

    def test_user_override_reference_remains_optional(self) -> None:
        resolved = profiles.resolve_profile(
            fixtures.default_profile(),
            {
                "profile": {
                    "accepted": True,
                    "meta_values": {},
                    "overrides": {
                        "criteria.cpu.max_percent": {"value": 35},
                    },
                }
            },
        )
        self.assertEqual(
            resolved["sources"]["criteria.cpu.max_percent"],
            {"source": "user"},
        )

    def test_default_scalar_values_have_default_provenance(self) -> None:
        resolved = profiles.resolve_profile(fixtures.default_profile(), {"profile": {}})
        self.assertEqual(
            resolved["sources"]["tests.stability.load_factor"],
            {"source": "default-v1"},
        )

    def test_missing_acceptance_resolves_to_false(self) -> None:
        resolved = profiles.resolve_profile(fixtures.default_profile(), {"profile": {}})
        self.assertFalse(resolved["accepted"])

    def test_unknown_target_is_rejected_by_resolved_profile_schema(self) -> None:
        with self.assertRaisesRegex(ValueError, "Additional properties"):
            profiles.resolve_profile(
                fixtures.default_profile(),
                {
                    "profile": {
                        "meta_values": {},
                        "overrides": {"criteria.cpu.invented": {"value": 1}},
                    }
                },
            )

    def test_resolution_does_not_mutate_the_default_profile(self) -> None:
        default = fixtures.default_profile()
        profiles.resolve_profile(
            default,
            {
                "profile": {
                    "meta_values": {},
                    "overrides": {"criteria.cpu.max_percent": {"value": 20}},
                }
            },
        )
        self.assertEqual(default["criteria"]["cpu"]["max_percent"], 40)
        self.assertNotIn("sources", default)


if __name__ == "__main__":
    unittest.main()

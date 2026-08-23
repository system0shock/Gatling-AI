"""Small valid artifact builders shared by methodology pipeline tests."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def default_profile() -> dict[str, Any]:
    return {
        "version": 1, "profile_id": "default-v1", "profile_version": 1,
        "tests": {"maximum_search": {"step_minutes": 20}, "maximum_confirmation": {"duration_minutes": 120, "load_factor": 1.0}, "stability": {"duration_minutes": 480, "load_factor": 0.8}},
        "criteria": {"response_time": {"percentile": "p95", "threshold_ms": 1000}, "technical_errors": {"max_percent": 5, "exclusions": []}, "cpu": {"max_percent": 40, "scope": "one-openshift-arm"}, "memory": {"max_percent": 80, "no_sustained_growth": True}},
    }


def question_catalog() -> dict[str, Any]:
    return {"version": 1, "questions": []}


def question_by_id(catalog: dict[str, Any], question_id: str) -> dict[str, Any]:
    for question in catalog["questions"]:
        if question["id"] == question_id:
            return deepcopy(question)
    raise KeyError(question_id)


def answers() -> dict[str, Any]:
    return {"version": 1, "profile": {"accepted": False, "meta_values": {}, "overrides": {}}, "questions": {}, "not_applicable_sections": []}


def confirmed_surface_review() -> dict[str, Any]:
    return {"version": 1, "snapshot_id": "0" * 64, "status": "confirmed", "included": [], "excluded": [], "added": []}

"""Small valid artifact builders shared by methodology pipeline tests."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import re
from typing import Any

if __package__:
    from .sections import CANONICAL_SECTIONS
else:
    from sections import CANONICAL_SECTIONS


def document_with_blocks(
    *, generated: str = "исходный\n", manual: str = "", section_id: str = "test-types"
) -> str:
    headings = dict(CANONICAL_SECTIONS)
    return (
        "# Методика\n\n"
        f"## {headings[section_id]}\n\n"
        f"<!-- mnt:generated:start id={section_id} -->\n"
        f"{generated}"
        "<!-- mnt:generated:end -->\n\n"
        f"<!-- mnt:manual:start id={section_id} -->\n"
        f"{manual}"
        "<!-- mnt:manual:end -->\n"
    )


def generation_state(markdown: str) -> dict[str, Any]:
    blocks: dict[str, Any] = {}
    pattern = re.compile(
        r"<!-- mnt:generated:start id=([a-z][a-z0-9-]*) -->\r?\n"
        r"(.*?)<!-- mnt:generated:end -->",
        re.DOTALL,
    )
    for match in pattern.finditer(markdown):
        digest = hashlib.sha256(match.group(2).encode("utf-8")).hexdigest()
        blocks[match.group(1)] = {
            "sha256": digest,
            "rendered_sha256": digest,
            "resolution": "rendered",
        }
    return {"version": 1, "blocks": blocks}


def default_profile() -> dict[str, Any]:
    return {
        "version": 1, "profile_id": "default-v1", "profile_version": 1,
        "tests": {"maximum_search": {"step_minutes": 20}, "maximum_confirmation": {"duration_minutes": 120, "load_factor": 1.0}, "stability": {"duration_minutes": 480, "load_factor": 0.8}},
        "criteria": {"response_time": {"percentile": "p95", "threshold_ms": 1000}, "technical_errors": {"max_percent": 5, "exclusions": []}, "cpu": {"max_percent": 40, "scope": "one-openshift-arm"}, "memory": {"max_percent": 80, "no_sustained_growth": True}},
    }


def question_catalog() -> dict[str, Any]:
    return {
        "version": 1,
        "questions": [
            {
                "id": "load.unit",
                "section": "Load",
                "prompt": "Load unit",
                "target": "load.unit",
                "type": "choice",
                "choices": ["rps", "users_per_second"],
                "required": True,
                "applies_to": [],
            },
            {
                "id": "load.initial",
                "section": "Load",
                "prompt": "Initial load",
                "target": "load.initial",
                "type": "number",
                "required": True,
                "applies_to": [],
            },
            {
                "id": "load.step_increment",
                "section": "Load",
                "prompt": "Load increment",
                "target": "load.step_increment",
                "type": "number",
                "required": True,
                "applies_to": [],
            },
            {
                "id": "load.operation_mix",
                "section": "Load",
                "prompt": "Operation mix",
                "target": "load.operation_mix",
                "type": "text",
                "required": True,
                "applies_to": [],
            },
            {
                "id": "environment.name",
                "section": "Environment",
                "prompt": "Environment name",
                "target": "environment.name",
                "type": "text",
                "required": True,
                "applies_to": [],
            },
            {
                "id": "observability.cpu_signal",
                "section": "Observability",
                "prompt": "CPU signal",
                "target": "observability.cpu_signal",
                "type": "text",
                "required": True,
                "applies_to": [],
            },
            {
                "id": "observability.memory_signal",
                "section": "Observability",
                "prompt": "Memory signal",
                "target": "observability.memory_signal",
                "type": "text",
                "required": True,
                "applies_to": [],
            },
            {
                "id": "observability.memory_growth_window",
                "section": "Observability",
                "prompt": "Memory growth window",
                "target": "observability.memory_growth_window",
                "type": "number",
                "required": True,
                "applies_to": [],
            },
            {
                "id": "observability.dashboard",
                "section": "Observability",
                "prompt": "Dashboard",
                "target": "observability.dashboard",
                "type": "text",
                "required": True,
                "applies_to": [],
            },
            {
                "id": "test_data.ready",
                "section": "Test data",
                "prompt": "Test data ready",
                "target": "test_data.ready",
                "type": "boolean",
                "required": True,
                "applies_to": [],
            },
        ],
    }


def question(question_id: str) -> dict[str, Any]:
    return question_by_id(question_catalog(), question_id)


def question_by_id(catalog: dict[str, Any], question_id: str) -> dict[str, Any]:
    for question in catalog["questions"]:
        if question["id"] == question_id:
            return deepcopy(question)
    raise KeyError(question_id)


def answers() -> dict[str, Any]:
    return {"version": 1, "profile": {"accepted": False, "meta_values": {}, "overrides": {}}, "questions": {}, "not_applicable_sections": []}


def confirmed_surface_review() -> dict[str, Any]:
    return {"version": 1, "snapshot_id": "0" * 64, "status": "confirmed", "included": [], "excluded": [], "added": []}


def workspace_snapshot() -> dict[str, Any]:
    return {"snapshot_id": "a" * 64}


def surface_review() -> dict[str, Any]:
    return {
        "version": 1,
        "snapshot_id": "a" * 64,
        "status": "confirmed",
        "included": [_surface_entity()],
        "excluded": [],
        "added": [],
    }


def resolved_profile() -> dict[str, Any]:
    value = default_profile()
    value["accepted"] = True
    value["sources"] = {}
    return value


def complete_answers() -> dict[str, Any]:
    return {
        "version": 1,
        "profile": {"accepted": True, "meta_values": {}, "overrides": {}},
        "questions": {
            "load.unit": {"value": "rps"},
            "load.initial": {"value": 10},
            "load.step_increment": {"value": 5},
            "load.operation_mix": {"value": "orders: 100%"},
            "environment.name": {"value": "staging"},
            "observability.cpu_signal": {"value": "node_cpu"},
            "observability.memory_signal": {"value": "rss"},
            "observability.memory_growth_window": {"value": 30},
            "observability.dashboard": {"value": "grafana"},
            "test_data.ready": {"value": True},
        },
        "not_applicable_sections": [
            {"section_id": "integrations", "reason": "No external interfaces"}
        ],
    }


def methodology_input() -> dict[str, Any]:
    return {
        "version": 1,
        "workspace_snapshot_id": "a" * 64,
        "surface": surface_review(),
        "profile": resolved_profile(),
        "load": {
            "unit": "rps",
            "initial": 10,
            "step_increment": 5,
            "operation_mix": "orders: 100%",
        },
        "environment": {"name": "staging"},
        "observability": {
            "cpu_signal": "node_cpu",
            "memory_signal": "rss",
            "memory_growth_window": 30,
            "dashboard": "grafana",
        },
        "test_data": {"ready": True},
        "document": {},
        "not_applicable_sections": [
            {"section_id": "integrations", "reason": "No external interfaces"}
        ],
    }


def _surface_entity() -> dict[str, Any]:
    return {
        "entity_type": "service",
        "canonical_key": "orders",
        "display_name": "Orders",
        "attributes": {"protocol": "http"},
        "sources": [{
            "repo_id": "catalog",
            "revision": "r1",
            "relative_path": "service.yaml",
            "pointer": "#",
            "selection_reason": "catalog entry",
            "sha256": "b" * 64,
        }],
    }

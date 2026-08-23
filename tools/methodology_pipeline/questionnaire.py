"""Catalog-driven handling for scalar methodology questions."""

from __future__ import annotations

import copy
from collections.abc import Collection, Mapping
from typing import Any

from .paths import MISSING, get_target, set_target


def validate_answer(question: Mapping[str, Any], value: Any) -> None:
    """Raise ValueError unless value matches the catalog's scalar question."""
    question_id = question["id"]
    kind = question["type"]
    valid = (
        (kind == "text" and isinstance(value, str))
        or (
            kind == "number"
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
        )
        or (kind == "boolean" and isinstance(value, bool))
        or (
            kind == "choice"
            and any(
                type(value) is type(choice) and value == choice
                for choice in question["choices"]
            )
        )
    )
    if not valid:
        raise ValueError(f"invalid answer for {question_id}")


def apply_scalar_answers(
    base: Mapping[str, Any],
    catalog: Mapping[str, Any],
    answers: Mapping[str, Any],
) -> dict[str, Any]:
    """Copy base and apply validated scalar answers by their catalog targets."""
    result = copy.deepcopy(dict(base))
    by_id = {item["id"]: item for item in catalog["questions"]}
    for question_id, answer in sorted(answers.get("questions", {}).items()):
        if question_id not in by_id:
            raise ValueError(f"unknown question id: {question_id}")
        validate_answer(by_id[question_id], answer["value"])
        set_target(result, by_id[question_id]["target"], answer["value"])
    return result


def unresolved_questions(
    model: Mapping[str, Any],
    catalog: Mapping[str, Any],
    capabilities: Collection[str],
) -> list[dict[str, Any]]:
    """Return required catalog questions that apply and remain unanswered."""
    pending = []
    capability_set = set(capabilities)
    for question in catalog["questions"]:
        applies_to = set(question.get("applies_to", []))
        if applies_to and applies_to.isdisjoint(capability_set):
            continue
        value = get_target(model, question["target"])
        if question["required"] and (value is MISSING or value is None or value == ""):
            pending.append(dict(question))
    return pending

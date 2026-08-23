"""Independent readiness formatting and methodology template conformance."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

if __package__:
    from .contracts import validate_artifact
    from .managed_blocks import ManagedSectionView, parse_managed_sections
    from .paths import MISSING, get_target
else:
    from contracts import validate_artifact
    from managed_blocks import ManagedSectionView, parse_managed_sections
    from paths import MISSING, get_target


NO_DATA = "> Нет подтверждённых данных."


def template_report(
    markdown: str,
    contract: Mapping[str, Any],
    methodology_input: Mapping[str, Any],
) -> dict[str, Any]:
    """Classify every shipped template section without altering readiness."""
    if not isinstance(markdown, str):
        raise ValueError("candidate methodology must be Markdown text")
    validate_artifact(contract, "methodology-template-contract.schema.json")
    validate_artifact(methodology_input, "methodology-input.schema.json")
    sections = contract["sections"]
    decisions = _not_applicable_decisions(methodology_input, sections)
    _validate_canonical_heading_syntax(markdown, sections)
    parsed = parse_managed_sections(markdown)

    records = [
        _classify_section(section, parsed, methodology_input, decisions)
        for section in sections
    ]
    complete = all(
        record["status"] in ("complete", "not_applicable")
        for record in records
    )
    result = {
        "version": 1,
        "status": "complete" if complete else "incomplete",
        "template_complete": complete,
        "sections": records,
    }
    validate_artifact(result, "methodology-template-report.schema.json")
    return result


def render_readiness_markdown(report: Mapping[str, Any]) -> str:
    """Render a stable, human-readable readiness report."""
    validate_artifact(report, "methodology-readiness-report.schema.json")
    status = "READY" if report["status"] == "ready" else "BLOCKED"
    lines = ["# Methodology readiness", "", f"Status: {status}"]
    for item in report["missing"]:
        question = item["question_id"]
        target = item["target"]
        label = f"{target} (question: {question})" if question else target
        lines.extend(("", f"- {label}: {item['message']}"))
    return "\n".join(lines) + "\n"


def render_template_markdown(report: Mapping[str, Any]) -> str:
    """Render partial and missing template sections in contract order."""
    validate_artifact(report, "methodology-template-report.schema.json")
    complete_count = sum(
        section["status"] in ("complete", "not_applicable")
        for section in report["sections"]
    )
    lines = [
        "# Methodology template conformance",
        "",
        f"Complete: {complete_count}/{len(report['sections'])}",
    ]
    for status, title in (("partial", "Partial"), ("missing", "Missing")):
        grouped = [item for item in report["sections"] if item["status"] == status]
        if not grouped:
            continue
        lines.extend(("", f"## {title}", ""))
        for item in grouped:
            question_suffix = ""
            if item["question_links"]:
                question_suffix = " [questions: " + ", ".join(item["question_links"]) + "]"
            lines.append(
                f"- {item['heading']}{question_suffix}: {'; '.join(item['gaps'])}"
            )
    return "\n".join(lines) + "\n"


def _not_applicable_decisions(
    methodology_input: Mapping[str, Any],
    sections: Sequence[Mapping[str, Any]],
) -> dict[str, str]:
    known = {section["id"]: section for section in sections}
    decisions: dict[str, str] = {}
    for item in methodology_input["not_applicable_sections"]:
        section_id = item["section_id"]
        reason = item["reason"]
        if section_id in decisions:
            raise ValueError(f"duplicate not applicable section: {section_id}")
        section = known.get(section_id)
        if section is None:
            raise ValueError(f"unknown not applicable section: {section_id}")
        if not section["allow_not_applicable"]:
            raise ValueError(f"section does not allow not applicable: {section_id}")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"not applicable reason is empty: {section_id}")
        decisions[section_id] = reason
    return decisions


def _validate_canonical_heading_syntax(
    markdown: str, sections: Sequence[Mapping[str, Any]]
) -> None:
    canonical_headings = {section["heading"] for section in sections}
    for line in markdown.splitlines():
        match = re.fullmatch(r"(#{1,6})([ \t]*)(.*)", line)
        if match is None:
            continue
        title = re.sub(r"[ \t]+#+[ \t]*$", "", match.group(3)).strip(" \t")
        if title in canonical_headings and line != f"## {title}":
            raise ValueError(f"malformed canonical heading: {title}")


def _classify_section(
    section: Mapping[str, Any],
    parsed: Mapping[str, ManagedSectionView],
    methodology_input: Mapping[str, Any],
    decisions: Mapping[str, str],
) -> dict[str, Any]:
    section_id = section["id"]
    record = {
        "id": section_id,
        "heading": section["heading"],
        "status": "complete",
        "gaps": [],
        "question_links": list(section["related_question_ids"]),
    }
    if section_id in decisions:
        record["status"] = "not_applicable"
        return record

    view = parsed.get(section_id)
    if view is None:
        record["status"] = "missing"
        record["gaps"].append("section heading is missing")
        return record
    semantic_body = _semantic_body(view)
    if not semantic_body.strip() or semantic_body.strip() == NO_DATA:
        record["status"] = "missing"
        record["gaps"].append("section has no confirmed data")
        return record

    gaps = record["gaps"]
    if view.generated is None:
        gaps.append("generated block is missing")
    for target in section["required_input_targets"]:
        if _input_is_missing(get_target(methodology_input, target)):
            gaps.append(f"required input is missing: {target}")
    for literal in section["required_literals"]:
        if literal not in (view.generated or "").splitlines():
            gaps.append(f"missing required construct: {literal}")
    if "table_columns" in section:
        gaps.extend(_table_gaps(view.generated or "", section))
    if gaps:
        record["status"] = "partial"
    return record


def _input_is_missing(value: Any) -> bool:
    return value is MISSING or value is None or (
        isinstance(value, str) and not value.strip()
    )


def _semantic_body(view: ManagedSectionView) -> str:
    if view.generated is None and view.manual is None:
        return view.body
    return (view.generated or "") + (view.manual or "")


def _table_gaps(body: str, section: Mapping[str, Any]) -> list[str]:
    columns = section["table_columns"]
    expected_header = "| " + " | ".join(columns) + " |"
    lines = body.splitlines()
    try:
        header_index = lines.index(expected_header)
    except ValueError:
        return ["required table header is missing"]
    if header_index + 1 >= len(lines) or not _is_table_separator(
        lines[header_index + 1], len(columns)
    ):
        return ["required table separator is missing"]
    data_rows = 0
    for line in lines[header_index + 2:]:
        if not line.startswith("|"):
            break
        if _is_data_row(line, len(columns)):
            data_rows += 1
    minimum = section["minimum_data_rows"]
    if data_rows < minimum:
        return [f"required table has fewer than {minimum} data rows"]
    return []


def _is_table_separator(line: str, columns: int) -> bool:
    if not line.startswith("|") or not line.endswith("|"):
        return False
    cells = line[1:-1].split("|")
    return len(cells) == columns and all(re.fullmatch(r"\s*:?-{3,}:?\s*", cell) for cell in cells)


def _is_data_row(line: str, columns: int) -> bool:
    if _is_table_separator(line, columns):
        return False
    if not line.endswith("|"):
        return False
    cells = line[1:-1].split("|")
    return len(cells) == columns and all(cell.strip() for cell in cells)

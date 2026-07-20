#!/usr/bin/env python3
"""Presentation layer for the JMeter migration IR.

Pure rendering of a parsed ``ir`` dict into the human-facing ``inventory.md``
report and the short CLI summary. These functions read the IR only — no XML, no
ParseState — so they live apart from the parser. ``jmx_parser`` re-exports them
to keep the public surface (``jmx_parser.render_inventory``, ...) stable.
"""

from __future__ import annotations

from typing import Any


def md_cell(value: str) -> str:
    """Escape pipes so free-form names cannot break Markdown table rows."""
    return value.replace("|", "\\|")


def render_stage(stage: dict[str, Any]) -> str:
    target = stage.get("users", stage.get("users_per_second"))
    unit = "u" if "users" in stage else "u/s"
    hold = stage.get("hold_seconds")
    hold_text = f"{hold}s" if hold is not None else "-"
    return f"{target}{unit} ramp {stage.get('ramp_seconds', 0)}s hold {hold_text}"


def render_inventory(ir: dict[str, Any]) -> str:
    source = ir["source"]
    stats = ir["stats"]
    lines = [
        f"# JMX Inventory — {source['file']}",
        "",
        f"- Size: {source['size_bytes']} bytes (sha256 `{source['sha256'][:12]}`)",
        f"- Test plan: {ir['test_plan']['name']}"
        + (f" (serialize_threadgroups: {ir['test_plan']['serialize_threadgroups']})"
           if ir['test_plan'].get('serialize_threadgroups') else ""),
        f"- Elements: {stats['elements_total']} total, {stats['elements_disabled']} disabled",
        f"- Bodies externalized: {stats['bodies_externalized']}",
        f"- JSR223: {stats['jsr223']['typical']} typical, {stats['jsr223']['complex']} complex",
        "",
        "## Elements",
        "",
        "| Kind | Count |",
        "|---|---|",
    ]
    lines.extend(f"| {kind} | {count} |" for kind, count in stats["by_kind"].items())

    lines.extend(["", "## Unsupported elements", ""])
    if ir["unsupported"]:
        for item in ir["unsupported"]:
            base = f"- `{item['type']}` — {item['name']} (id {item['id']}, at {'/'.join(item['path'])}"
            raw = item.get("raw_props")
            if raw:
                prop_names = ", ".join(raw.keys())
                base += f"; props: {prop_names}"
            base += ")"
            lines.append(base)
    else:
        lines.append("- None")

    lines.extend(
        ["", "## Thread groups", "", "| Name | Flavor | Model | Stages | Start after | Note |", "|---|---|---|---|---|---|"]
    )

    def thread_group_rows(node: dict[str, Any]) -> None:
        if node["kind"] == "thread_group":
            normalized = node["load"].get("normalized")
            note = node["load"].get("normalization_note", "")
            if normalized:
                model = normalized["model"]
                stages = "; ".join(render_stage(stage) for stage in normalized["stages"])
                start = f"{normalized['start_after_seconds']}s"
            else:
                model, stages, start = "?", "needs review", "?"
            suffix = "" if node["enabled"] else " (disabled)"
            lines.append(
                f"| {md_cell(node['name'])}{suffix} | {node['flavor']} | {model} | {stages} | {start} | {md_cell(note)} |"
            )
        for child in node["children"]:
            thread_group_rows(child)

    for child in ir["children"]:
        thread_group_rows(child)

    findings = ir["variables"]["findings"]
    lines.extend(["", "## Data flow findings", ""])
    body = False
    for item in findings["consumed_not_produced"]:
        lines.append(
            f"- `${{{item['variable']}}}` is consumed but never produced "
            f"(elements: {', '.join(item['elements'])}) — props, external file or hidden logic?"
        )
        body = True
    for item in findings["produced_not_consumed"]:
        lines.append(
            f"- `${{{item['variable']}}}` is produced but never consumed "
            f"(elements: {', '.join(item['elements'])}) — dead correlation?"
        )
        body = True
    for name, record in ir["variables"]["props"].items():
        lines.append(
            f"- prop `{name}`: writers {', '.join(record['writers']) or '-'}; "
            f"readers {', '.join(record['readers']) or '-'}"
        )
        body = True
    if not body:
        lines.append("- None")

    lines.extend(["", "## Complexity flags", ""])
    if ir["complexity_flags"]:
        lines.extend(
            f"- **{flag['flag']}**: {flag['details']}" for flag in ir["complexity_flags"]
        )
    else:
        lines.append("- None")

    return "\n".join(lines) + "\n"


def render_summary(ir: dict[str, Any]) -> str:
    lines = [
        f"plan: {ir['test_plan']['name']} ({ir['source']['file']}, "
        f"{ir['source']['size_bytes']} bytes)",
        f"elements: {ir['stats']['elements_total']} "
        f"({ir['stats']['elements_disabled']} disabled), "
        f"unsupported: {len(ir['unsupported'])}",
    ]

    def visit(node: dict[str, Any]) -> None:
        if node["kind"] == "thread_group":
            normalized = node["load"].get("normalized")
            detail = (
                f"{normalized['model']}, {len(normalized['stages'])} stage(s)"
                if normalized
                else "load needs review"
            )
            lines.append(f"thread group {node['id']} '{node['name']}': {detail}")
        for child in node["children"]:
            visit(child)

    for child in ir["children"]:
        visit(child)
    for flag in ir["complexity_flags"]:
        lines.append(f"flag {flag['flag']}: {flag['details']}")
    return "\n".join(lines)

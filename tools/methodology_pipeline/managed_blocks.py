"""Strict, byte-preserving managed blocks for methodology Markdown."""

from __future__ import annotations

import hashlib
import re
from collections import OrderedDict
from collections.abc import Collection, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

if __package__:
    from . import contracts
    from .sections import CANONICAL_SECTIONS
else:
    import contracts
    from sections import CANONICAL_SECTIONS


_HEADING_TO_ID = {heading: section_id for section_id, heading in CANONICAL_SECTIONS}
_START_RE = re.compile(
    r"<!-- mnt:(generated|manual):start id=([a-z][a-z0-9-]*) -->"
)
_CONSTRUCT_RE = re.compile(r"<!-- mnt:construct:[a-z][a-z0-9-]* -->")


@dataclass(frozen=True)
class BlockMergeResult:
    markdown: str
    generation_state: dict[str, Any]
    conflicts: tuple[dict[str, str], ...]
    warnings: tuple[dict[str, str], ...]


@dataclass(frozen=True)
class ManagedSectionView:
    """Read-only canonical section content split by managed ownership."""

    section_id: str
    body: str
    generated: str | None
    manual: str | None


@dataclass(frozen=True)
class _Section:
    section_id: str
    body_start: int
    body_end: int
    newline: str


@dataclass(frozen=True)
class _Block:
    kind: str
    section_id: str
    content_start: int
    content_end: int
    newline: str


@dataclass(frozen=True)
class _ParsedDocument:
    sections: OrderedDict[str, _Section]
    generated: dict[str, _Block]
    manual: dict[str, _Block]


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_sections(markdown: str) -> OrderedDict[str, str]:
    parsed = _parse_document(markdown)
    return OrderedDict(
        (section_id, markdown[section.body_start:section.body_end])
        for section_id, section in parsed.sections.items()
    )


def parse_managed_sections(markdown: str) -> OrderedDict[str, ManagedSectionView]:
    """Return canonical bodies with generated and manual content isolated."""
    parsed = _parse_document(markdown)
    views: OrderedDict[str, ManagedSectionView] = OrderedDict()
    for section_id, section in parsed.sections.items():
        generated = parsed.generated.get(section_id)
        manual = parsed.manual.get(section_id)
        views[section_id] = ManagedSectionView(
            section_id=section_id,
            body=markdown[section.body_start:section.body_end],
            generated=(
                markdown[generated.content_start:generated.content_end]
                if generated is not None else None
            ),
            manual=(
                markdown[manual.content_start:manual.content_end]
                if manual is not None else None
            ),
        )
    return views


def migrate_legacy(markdown: str, headings: Sequence[str]) -> str:
    parsed = _parse_document(markdown)
    requested_ids: list[str] = []
    for heading in headings:
        try:
            requested_ids.append(_HEADING_TO_ID[heading])
        except KeyError as exc:
            raise ValueError(f"unknown canonical heading: {heading}") from exc

    edits: list[tuple[int, int, str]] = []
    for section_id in requested_ids:
        section = parsed.sections.get(section_id)
        if section is None:
            continue
        if section_id in parsed.generated or section_id in parsed.manual:
            continue
        body = markdown[section.body_start:section.body_end]
        newline = section.newline
        manual_tail = "" if body.endswith(("\n", "\r")) else newline
        replacement = (
            f"<!-- mnt:generated:start id={section_id} -->{newline}"
            f"<!-- mnt:generated:end -->{newline}{newline}"
            f"<!-- mnt:manual:start id={section_id} -->{newline}"
            f"{body}{manual_tail}"
            f"<!-- mnt:manual:end -->{newline}"
        )
        edits.append((section.body_start, section.body_end, replacement))
    return _apply_edits(markdown, edits)


def merge_generated(
    current: str,
    generated_by_id: Mapping[str, str],
    previous_state: Mapping[str, Any],
    *,
    allowed_constructs_by_id: Mapping[str, Collection[str]] | None = None,
) -> BlockMergeResult:
    contracts.validate_artifact(
        previous_state, "methodology-generation-state.schema.json"
    )
    _validate_generated(generated_by_id, allowed_constructs_by_id)
    parsed = _parse_document(current)
    conflicts = _detect_conflicts(current, generated_by_id, previous_state, parsed)
    if conflicts:
        return BlockMergeResult(
            current, deepcopy(dict(previous_state)), tuple(conflicts), ()
        )

    edits: list[tuple[int, int, str]] = []
    state_blocks = deepcopy(previous_state["blocks"])
    for section_id, rendered in generated_by_id.items():
        block = _require_generated_block(parsed, section_id)
        edits.append((block.content_start, block.content_end, rendered))
        state_blocks[section_id] = _rendered_state(rendered)
    state = {"version": 1, "blocks": state_blocks}
    contracts.validate_artifact(state, "methodology-generation-state.schema.json")
    return BlockMergeResult(_apply_edits(current, edits), state, (), ())


def resolve_drift(
    current: str,
    generated_by_id: Mapping[str, str],
    previous_state: Mapping[str, Any],
    decisions: Mapping[str, Any],
    *,
    allowed_constructs_by_id: Mapping[str, Collection[str]] | None = None,
) -> BlockMergeResult:
    artifact = _decision_artifact(decisions)
    contracts.validate_artifact(
        artifact, "methodology-drift-decisions.schema.json"
    )
    contracts.validate_artifact(
        previous_state, "methodology-generation-state.schema.json"
    )
    _validate_generated(generated_by_id, allowed_constructs_by_id)
    parsed = _parse_document(current)
    conflicts = _detect_conflicts(current, generated_by_id, previous_state, parsed)
    conflicted_ids = {item["section_id"] for item in conflicts}
    provided_ids = set(artifact["decisions"])
    missing = sorted(conflicted_ids - provided_ids)
    if missing:
        raise ValueError(f"missing drift decision: {missing[0]}")
    unknown = sorted(provided_ids - conflicted_ids)
    if unknown:
        raise ValueError(f"unknown drift decision: {unknown[0]}")

    edits: list[tuple[int, int, str]] = []
    warnings: list[dict[str, str]] = []
    state_blocks = deepcopy(previous_state["blocks"])
    for section_id, rendered in generated_by_id.items():
        block = _require_generated_block(parsed, section_id)
        actual = current[block.content_start:block.content_end]
        action = artifact["decisions"].get(section_id)
        if action == "keep":
            state_blocks[section_id] = {
                "sha256": sha256_text(actual),
                "rendered_sha256": sha256_text(rendered),
                "resolution": "keep",
            }
            warnings.append(
                {
                    "rule": "user-kept-generated-block",
                    "section_id": section_id,
                    "message": f"user kept changed generated block for this run: {section_id}",
                }
            )
            continue

        edits.append((block.content_start, block.content_end, rendered))
        state_blocks[section_id] = _rendered_state(rendered)
        if action == "move-to-manual":
            try:
                manual = parsed.manual[section_id]
            except KeyError as exc:
                raise ValueError(
                    f"manual block missing for drift resolution: {section_id}"
                ) from exc
            old_manual = current[manual.content_start:manual.content_end]
            moved_manual = _append_with_blank_line(old_manual, actual, manual.newline)
            edits.append((manual.content_start, manual.content_end, moved_manual))

    state = {"version": 1, "blocks": state_blocks}
    contracts.validate_artifact(state, "methodology-generation-state.schema.json")
    return BlockMergeResult(
        _apply_edits(current, edits), state, (), tuple(warnings)
    )


def _parse_document(markdown: str) -> _ParsedDocument:
    heading_matches = list(
        re.finditer(r"(?m)^## ([^\r\n]+)(\r\n|\n|\r|$)", markdown)
    )
    sections: OrderedDict[str, _Section] = OrderedDict()
    for index, match in enumerate(heading_matches):
        heading = match.group(1)
        section_id = _HEADING_TO_ID.get(heading)
        if section_id is None:
            continue
        if section_id in sections:
            raise ValueError(f"duplicate canonical heading: {heading}")
        body_end = (
            heading_matches[index + 1].start()
            if index + 1 < len(heading_matches)
            else len(markdown)
        )
        newline = match.group(2) or _infer_newline(markdown)
        sections[section_id] = _Section(
            section_id, match.end(), body_end, newline
        )

    generated: dict[str, _Block] = {}
    manual: dict[str, _Block] = {}
    open_marker: tuple[str, str, int, str] | None = None
    offset = 0
    for line in markdown.splitlines(keepends=True):
        newline = _line_ending(line)
        token = line[:-len(newline)] if newline else line
        if "<!-- mnt:" not in token:
            offset += len(line)
            continue
        if _CONSTRUCT_RE.fullmatch(token):
            if open_marker is None or open_marker[0] != "generated":
                raise ValueError(
                    "construct marker must be inside a generated block"
                )
            offset += len(line)
            continue
        start = _START_RE.fullmatch(token)
        end_kind = None
        if token == "<!-- mnt:generated:end -->":
            end_kind = "generated"
        elif token == "<!-- mnt:manual:end -->":
            end_kind = "manual"
        elif start is None:
            raise ValueError(f"malformed managed marker at offset {offset}")

        if start is not None:
            if open_marker is not None:
                raise ValueError("nested managed marker")
            kind, section_id = start.groups()
            target = generated if kind == "generated" else manual
            if section_id in target:
                raise ValueError(f"duplicate {kind} marker: {section_id}")
            containing = _containing_section(sections, offset)
            if containing != section_id:
                raise ValueError(
                    f"marker id does not match canonical section: {section_id}"
                )
            open_marker = (kind, section_id, offset + len(line), newline or "\n")
        else:
            if open_marker is None or open_marker[0] != end_kind:
                raise ValueError("mismatched managed marker")
            kind, section_id, content_start, marker_newline = open_marker
            block = _Block(
                kind, section_id, content_start, offset, marker_newline
            )
            target = generated if kind == "generated" else manual
            target[section_id] = block
            open_marker = None
        offset += len(line)

    if open_marker is not None:
        raise ValueError(
            f"unterminated managed marker: {open_marker[1]}"
        )
    return _ParsedDocument(sections, generated, manual)


def _containing_section(
    sections: Mapping[str, _Section], marker_offset: int
) -> str | None:
    for section_id, section in sections.items():
        if section.body_start <= marker_offset < section.body_end:
            return section_id
    return None


def _detect_conflicts(
    current: str,
    generated_by_id: Mapping[str, str],
    previous_state: Mapping[str, Any],
    parsed: _ParsedDocument,
) -> list[dict[str, str]]:
    conflicts: list[dict[str, str]] = []
    previous_blocks = previous_state["blocks"]
    for section_id, rendered in generated_by_id.items():
        block = _require_generated_block(parsed, section_id)
        actual = current[block.content_start:block.content_end]
        previous = previous_blocks.get(section_id)
        if previous is None:
            if actual:
                conflicts.append(
                    {
                        "rule": "generation-state-missing",
                        "section_id": section_id,
                        "message": f"generation state missing for non-empty block: {section_id}",
                    }
                )
        elif sha256_text(actual) != previous["sha256"]:
            conflicts.append(
                {
                    "rule": "managed-block-drift",
                    "section_id": section_id,
                    "message": f"generated block changed outside the renderer: {section_id}",
                }
            )
    return conflicts


def _decision_artifact(decisions: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(decisions)
    if "version" in value or "decisions" in value:
        return value
    return {"version": 1, "decisions": value}


def _rendered_state(rendered: str) -> dict[str, str]:
    digest = sha256_text(rendered)
    return {
        "sha256": digest,
        "rendered_sha256": digest,
        "resolution": "rendered",
    }


def _require_generated_block(
    parsed: _ParsedDocument, section_id: str
) -> _Block:
    try:
        return parsed.generated[section_id]
    except KeyError as exc:
        raise ValueError(f"generated block missing: {section_id}") from exc


def _validate_generated(
    generated_by_id: Mapping[str, str],
    allowed_constructs_by_id: Mapping[str, Collection[str]] | None,
) -> None:
    for section_id, rendered in generated_by_id.items():
        allowed = None
        if allowed_constructs_by_id is not None:
            declared = allowed_constructs_by_id.get(section_id, ())
            if isinstance(declared, str):
                raise ValueError(
                    f"construct allowance must be a collection: {section_id}"
                )
            allowed = frozenset(declared)
        _require_text(rendered, section_id, allowed)


def _require_text(
    value: Any,
    section_id: str,
    allowed_constructs: frozenset[str] | None,
) -> None:
    if not isinstance(value, str):
        raise ValueError(f"generated body must be text: {section_id}")
    if value and not value.endswith(("\n", "\r")):
        raise ValueError(
            f"generated body must end with a terminal newline: {section_id}"
        )
    seen_constructs: set[str] = set()
    for line in value.splitlines():
        if "<!-- mnt:" not in line:
            continue
        if _CONSTRUCT_RE.fullmatch(line):
            if allowed_constructs is None or line not in allowed_constructs:
                raise ValueError(
                    f"generated body contains undeclared construct: {section_id}"
                )
            if line in seen_constructs:
                raise ValueError(
                    f"generated body contains duplicate construct: {section_id}"
                )
            seen_constructs.add(line)
            continue
        raise ValueError(f"generated body contains a managed marker: {section_id}")


def _append_with_blank_line(existing: str, addition: str, newline: str) -> str:
    if not existing:
        return addition
    trailing_newlines = 0
    remainder = existing
    while remainder.endswith(newline):
        trailing_newlines += 1
        remainder = remainder[:-len(newline)]
    separator = newline * max(0, 2 - trailing_newlines)
    return existing + separator + addition


def _apply_edits(markdown: str, edits: Sequence[tuple[int, int, str]]) -> str:
    result = markdown
    previous_start = len(markdown) + 1
    for start, end, replacement in sorted(edits, reverse=True):
        if end > previous_start:
            raise ValueError("overlapping managed block edits")
        result = result[:start] + replacement + result[end:]
        previous_start = start
    return result


def _line_ending(line: str) -> str:
    if line.endswith("\r\n"):
        return "\r\n"
    if line.endswith("\n"):
        return "\n"
    if line.endswith("\r"):
        return "\r"
    return ""


def _infer_newline(markdown: str) -> str:
    match = re.search(r"\r\n|\n|\r", markdown)
    return match.group(0) if match else "\n"

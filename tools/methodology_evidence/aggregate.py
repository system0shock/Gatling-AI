"""Lossless aggregation of module evidence captured against a workspace snapshot."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path
from typing import Any

try:
    from .contracts import EvidenceDocument, EvidenceRecord, SourceRef, load_evidence, write_evidence
except ImportError:
    from contracts import EvidenceDocument, EvidenceRecord, SourceRef, load_evidence, write_evidence


@dataclass
class EntityCandidates:
    """All source-backed candidate facts for one stable entity."""

    entity_type: str
    entity_id: str
    candidates: dict[str, list[EvidenceRecord]] = dataclass_field(default_factory=dict)


@dataclass
class Aggregation:
    """Evidence grouped by stable entity ID and field without resolving conflicts."""

    entities: dict[tuple[str, str], EntityCandidates]


def source_sort_key(source: SourceRef) -> tuple[str, str, str, str, str, str, str]:
    """Return a deterministic key that includes every provenance component."""
    return (
        source.source_type,
        source.module_id or "",
        source.revision or "",
        source.ref,
        source.page_id or "",
        "" if source.page_version is None else str(source.page_version),
        source.observed_at or "",
    )


def evidence_sort_key(record: EvidenceRecord) -> tuple[str, ...]:
    """Return a deterministic, provenance-preserving evidence-record key."""
    return (
        record.entity_type,
        record.entity_id,
        record.section,
        record.field,
        record.statement,
        *source_sort_key(record.source),
        record.confidence,
        record.freshness,
    )


def aggregate_records(records: Iterable[EvidenceRecord]) -> Aggregation:
    """Group records by entity and field while retaining every candidate source."""
    entities: dict[tuple[str, str], EntityCandidates] = {}
    for record in sorted(records, key=evidence_sort_key):
        key = (record.entity_type, record.entity_id)
        entity = entities.setdefault(key, EntityCandidates(*key))
        entity.candidates.setdefault(record.field, []).append(record)
    return Aggregation(entities=entities)


def aggregate_modules(snapshot: dict[str, Any], paths: list[Path]) -> EvidenceDocument:
    """Load module evidence only when repository/OpenAPI facts match the snapshot."""
    states = snapshot.get("modules")
    if not isinstance(states, dict):
        raise ValueError("snapshot must contain modules")

    records: list[EvidenceRecord] = []
    for path in sorted(paths, key=lambda candidate: str(candidate)):
        document = load_evidence(path)
        for record in document.records:
            source = record.source
            if source.source_type in {"repository", "openapi"}:
                state = states.get(source.module_id)
                expected = state.get("commit") if isinstance(state, dict) else None
                if expected != source.revision:
                    raise ValueError(
                        f"{source.module_id} evidence does not match snapshot revision"
                    )
            records.append(record)

    return EvidenceDocument(
        producer="methodology-evidence-aggregator",
        records=tuple(sorted(records, key=evidence_sort_key)),
    )


def write_aggregation_outputs(document: EvidenceDocument, output_dir: Path) -> dict[str, Path]:
    """Write endpoint, integration, and complete repository evidence from one document."""
    output_dir = Path(output_dir)
    records_by_name = {
        "endpoint-inventory.json": tuple(
            record for record in document.records if record.entity_type == "endpoint"
        ),
        "integration-inventory.json": tuple(
            record for record in document.records if record.entity_type == "integration"
        ),
        "repository-evidence.json": document.records,
    }
    outputs: dict[str, Path] = {}
    for name, records in records_by_name.items():
        path = output_dir / name
        write_evidence(
            EvidenceDocument(
                producer=document.producer,
                records=records,
                generated_at=document.generated_at,
            ),
            path,
        )
        outputs[name] = path
    return outputs
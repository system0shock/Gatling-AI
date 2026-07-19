"""Deterministic reconciliation and gap reporting for methodology evidence."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

try:
    from .aggregate import evidence_sort_key
    from .contracts import EvidenceDocument, EvidenceRecord, atomic_write_text
except ImportError:
    from aggregate import evidence_sort_key
    from contracts import EvidenceDocument, EvidenceRecord, atomic_write_text


STATUSES = frozenset({"confirmed", "repo_only", "docs_only", "conflict", "inferred", "unknown", "not_applicable"})
STATUS_PRIORITY = {"conflict": 6, "unknown": 5, "inferred": 4, "docs_only": 3, "repo_only": 2, "confirmed": 1, "not_applicable": 0}

# These headings are the fixed MNT structure from the design specification.
REQUIRED_MNT_SECTIONS = (
    ("\u041f\u0430\u0441\u043f\u043e\u0440\u0442 \u0434\u043e\u043a\u0443\u043c\u0435\u043d\u0442\u0430", {"document"}),
    ("\u041d\u0430\u0437\u043d\u0430\u0447\u0435\u043d\u0438\u0435 \u0438 \u043e\u0431\u043b\u0430\u0441\u0442\u044c \u0442\u0435\u0441\u0442\u0438\u0440\u043e\u0432\u0430\u043d\u0438\u044f", {"scope"}),
    ("\u041e\u043f\u0438\u0441\u0430\u043d\u0438\u0435 \u0441\u0438\u0441\u0442\u0435\u043c\u044b \u0438 \u0444\u0443\u043d\u043a\u0446\u0438\u043e\u043d\u0430\u043b\u044c\u043d\u043e\u0441\u0442\u0438", {"system", "feature", "business-process"}),
    ("\u0410\u0440\u0445\u0438\u0442\u0435\u043a\u0442\u0443\u0440\u0430", {"architecture", "component", "deployment"}),
    ("\u0420\u0435\u0435\u0441\u0442\u0440 \u0438\u043d\u0442\u0435\u0433\u0440\u0430\u0446\u0438\u0439", {"integration"}),
    ("\u0420\u0435\u0435\u0441\u0442\u0440 \u0442\u0435\u0441\u0442\u0438\u0440\u0443\u0435\u043c\u044b\u0445 \u0438\u043d\u0442\u0435\u0440\u0444\u0435\u0439\u0441\u043e\u0432", {"endpoint"}),
    ("\u041f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c\u0441\u043a\u0438\u0435 \u0438 \u0442\u0435\u0445\u043d\u0438\u0447\u0435\u0441\u043a\u0438\u0435 \u043f\u043e\u0442\u043e\u043a\u0438", {"flow"}),
    ("\u041c\u043e\u0434\u0435\u043b\u044c \u043d\u0430\u0433\u0440\u0443\u0437\u043a\u0438", {"workload"}),
    ("\u0412\u0438\u0434\u044b \u0442\u0435\u0441\u0442\u043e\u0432", {"test-type"}),
    ("SLA, SLO \u0438 \u043a\u0440\u0438\u0442\u0435\u0440\u0438\u0438 \u043f\u0440\u0438\u0435\u043c\u043a\u0438", {"sla", "slo"}),
    ("\u0422\u0435\u0441\u0442\u043e\u0432\u044b\u0439 \u0441\u0442\u0435\u043d\u0434", {"environment", "test-environment"}),
    ("\u0422\u0440\u0435\u0431\u043e\u0432\u0430\u043d\u0438\u044f \u043a \u0442\u0435\u0441\u0442\u043e\u0432\u044b\u043c \u0434\u0430\u043d\u043d\u044b\u043c", {"test-data"}),
    ("\u041d\u0430\u0431\u043b\u044e\u0434\u0430\u0435\u043c\u043e\u0441\u0442\u044c \u0438 \u0434\u0438\u0430\u0433\u043d\u043e\u0441\u0442\u0438\u043a\u0430", {"monitoring", "observability"}),
    ("\u041f\u043e\u0440\u044f\u0434\u043e\u043a \u043f\u0440\u043e\u0432\u0435\u0434\u0435\u043d\u0438\u044f \u0442\u0435\u0441\u0442\u043e\u0432", {"test-procedure"}),
    ("\u0420\u0438\u0441\u043a\u0438, \u043e\u0433\u0440\u0430\u043d\u0438\u0447\u0435\u043d\u0438\u044f \u0438 \u0434\u043e\u043f\u0443\u0449\u0435\u043d\u0438\u044f", {"risk", "constraint", "assumption"}),
    ("\u0410\u0440\u0442\u0435\u0444\u0430\u043a\u0442\u044b \u0438 \u043e\u0442\u0447\u0435\u0442\u043d\u043e\u0441\u0442\u044c", {"artifact"}),
    ("\u0410\u043a\u0442\u0443\u0430\u043b\u0438\u0437\u0430\u0446\u0438\u044f \u043c\u0435\u0442\u043e\u0434\u0438\u043a\u0438", {"methodology-update"}),
)


@dataclass(frozen=True)
class Finding:
    rule: str
    message: str
    severity: str = "blocking"
    entity_type: str | None = None
    entity_id: str | None = None


@dataclass(frozen=True)
class ResolvedEntity:
    entity_type: str
    entity_id: str
    status: str
    fields: dict[str, tuple[EvidenceRecord, ...]]


@dataclass(frozen=True)
class Reconciliation:
    entities: dict[tuple[str, str], ResolvedEntity]
    blocking_gaps: tuple[Finding, ...]

    def entity(self, entity_type: str, entity_id: str) -> ResolvedEntity:
        return self.entities[(entity_type, entity_id)]


def normalize_statement(statement: str) -> str:
    """Compare claims independent of case and non-semantic whitespace."""
    return re.sub(r"\s+", " ", statement).strip().casefold()


def field_status(records: Iterable[EvidenceRecord]) -> str:
    """Resolve one field without discarding the evidence that led to its status."""
    candidates = list(records)
    source_types = {record.source.source_type for record in candidates}
    if "manual-confirmation" in source_types:
        return "confirmed"
    if len({normalize_statement(record.statement) for record in candidates}) > 1:
        return "conflict"
    if source_types <= {"repository", "openapi"}:
        return "repo_only"
    if source_types == {"confluence"}:
        return "docs_only"
    if any(record.confidence == "inferred" for record in candidates):
        return "inferred"
    return "confirmed"


def reconcile_documents(repository: EvidenceDocument, confluence: EvidenceDocument, confirmations: EvidenceDocument) -> Reconciliation:
    """Reconcile facts by stable entity and field; never select a conflicting claim."""
    grouped: dict[tuple[str, str], dict[str, list[EvidenceRecord]]] = {}
    for record in (*repository.records, *confluence.records, *confirmations.records):
        grouped.setdefault((record.entity_type, record.entity_id), {}).setdefault(record.field, []).append(record)

    entities: dict[tuple[str, str], ResolvedEntity] = {}
    gaps: list[Finding] = []
    for (entity_type, entity_id), fields in sorted(grouped.items()):
        frozen_fields = {name: tuple(sorted(records, key=evidence_sort_key)) for name, records in sorted(fields.items())}
        status = max((field_status(records) for records in frozen_fields.values()), key=STATUS_PRIORITY.__getitem__)
        entities[(entity_type, entity_id)] = ResolvedEntity(entity_type, entity_id, status, frozen_fields)
        if status == "conflict":
            gaps.append(Finding("evidence-conflict", "conflicting source claims", entity_type=entity_type, entity_id=entity_id))
        if entity_type == "sla" and not any(record.source.source_type == "manual-confirmation" for records in frozen_fields.values() for record in records):
            gaps.append(Finding("sla-normative-source", "SLA requires normative confirmation", entity_type=entity_type, entity_id=entity_id))
    if not any(entity_type == "workload" for entity_type, _ in entities):
        gaps.append(Finding("production-workload", "production workload evidence is missing"))
    return Reconciliation(entities, tuple(gaps))


def evidence_id(record: EvidenceRecord) -> str:
    return f"{record.entity_type}.{record.entity_id}.{record.field}"


def _entity_dict(entity: ResolvedEntity) -> dict[str, object]:
    return {"entity_type": entity.entity_type, "entity_id": entity.entity_id, "status": entity.status, "fields": {field: [asdict(record) for record in records] for field, records in entity.fields.items()}}


def _coverage(result: Reconciliation) -> dict[str, object]:
    sections = []
    for heading, entity_types in REQUIRED_MNT_SECTIONS:
        matching = [entity for entity in result.entities.values() if entity.entity_type in entity_types]
        ids = sorted({evidence_id(record) for entity in matching for records in entity.fields.values() for record in records})
        statuses = {entity.status for entity in matching}
        status = "missing" if not matching else "covered" if statuses == {"confirmed"} else "partial"
        sections.append({"heading": heading, "status": status, "evidence_ids": ids})
    return {"version": 1, "sections": sections}


def _render_findings(title: str, findings: Iterable[Finding], empty: str) -> str:
    lines = [f"# {title}", ""]
    ordered = sorted(findings, key=lambda item: (item.rule, item.entity_type or "", item.entity_id or "", item.message))
    if not ordered:
        return "\n".join(lines + [empty, ""])
    for finding in ordered:
        target = "" if finding.entity_type is None else f" ({finding.entity_type}:{finding.entity_id})"
        lines.append(f"- [{finding.severity}] `{finding.rule}`: {finding.message}{target}")
    return "\n".join(lines) + "\n"


def write_reconciliation_outputs(result: Reconciliation, output_dir: Path) -> dict[str, Path]:
    """Write stable JSON and Markdown reports, even when the gap gate blocks."""
    output_dir = Path(output_dir)
    entities = [_entity_dict(entity) for _, entity in sorted(result.entities.items())]
    outputs = {
        "resolved-evidence.json": output_dir / "resolved-evidence.json",
        "discrepancies.md": output_dir / "discrepancies.md",
        "methodology-gaps.md": output_dir / "methodology-gaps.md",
        "section-coverage.json": output_dir / "section-coverage.json",
    }
    atomic_write_text(outputs["resolved-evidence.json"], json.dumps({"version": 1, "entities": entities}, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    conflicts = [gap for gap in result.blocking_gaps if gap.rule == "evidence-conflict"]
    atomic_write_text(outputs["discrepancies.md"], _render_findings("Evidence discrepancies", conflicts, "No discrepancies."))
    atomic_write_text(outputs["methodology-gaps.md"], _render_findings("Methodology gaps", result.blocking_gaps, "No blocking gaps."))
    atomic_write_text(outputs["section-coverage.json"], json.dumps(_coverage(result), ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    return outputs
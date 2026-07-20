"""Reusable methodology-evidence test fixtures."""

from __future__ import annotations

from pathlib import Path

if __package__:
    from .contracts import EvidenceDocument, EvidenceRecord, SourceRef, write_evidence
else:
    from contracts import EvidenceDocument, EvidenceRecord, SourceRef, write_evidence


def source(source_type: str, *, module: str | None = None, revision: str | None = None) -> SourceRef:
    if source_type in {"repository", "openapi"}:
        return SourceRef(
            source_type=source_type,
            ref="src/App.java:10",
            module_id=module or "orders",
            revision=revision or "abc",
        )
    if source_type == "confluence":
        return SourceRef(source_type="confluence", ref="https://wiki/page", page_id="42", page_version=3)
    return SourceRef(source_type=source_type, ref="user-confirmation")


def record(
    source_type: str,
    statement: str,
    *,
    entity_type: str = "endpoint",
    entity_id: str = "orders.get-order",
    field: str = "method_path",
    module: str | None = None,
    revision: str | None = None,
) -> EvidenceRecord:
    return EvidenceRecord(
        entity_type=entity_type,
        entity_id=entity_id,
        section="interfaces",
        field=field,
        statement=statement,
        source=source(source_type, module=module, revision=revision),
        confidence="confirmed",
        freshness="current",
    )


def evidence_doc(*records: EvidenceRecord) -> EvidenceDocument:
    return EvidenceDocument(producer="test", records=tuple(records))


def evidence_file(root: Path, *, module: str, revision: str) -> Path:
    path = root / f"{module}.json"
    write_evidence(
        evidence_doc(record("repository", "GET /orders/{id}", module=module, revision=revision)), path
    )
    return path


def openapi_endpoint(path: str) -> EvidenceRecord:
    return record("openapi", path, module="api-contracts")


def backend_endpoint(path: str) -> EvidenceRecord:
    return record("repository", path, module="orders-backend")


def same_endpoint_from_openapi() -> EvidenceRecord:
    return openapi_endpoint("GET /orders/{id}")


def same_endpoint_from_backend() -> EvidenceRecord:
    return backend_endpoint("GET /orders/{id}")


def confluence_sla(value: str) -> EvidenceRecord:
    return record("confluence", value, entity_type="sla", entity_id="checkout", field="threshold")


def manual_confirmation(entity_type: str, entity_id: str, field: str, value: str) -> EvidenceRecord:
    return record("manual-confirmation", value, entity_type=entity_type, entity_id=entity_id, field=field)


def repo_doc() -> EvidenceDocument:
    return evidence_doc(
        record("repository", "p95 <= 800ms", entity_type="sla", entity_id="checkout", field="threshold")
    )


def confluence_doc() -> EvidenceDocument:
    return evidence_doc(confluence_sla("p95 <= 500ms"))

"""Immutable, schema-validated contracts for methodology evidence artifacts."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field as dataclass_field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jsonschema


SOURCE_TYPES = frozenset({"repository", "confluence", "manual-confirmation", "monitoring", "openapi"})
REPOSITORY_SOURCE_TYPES = frozenset({"repository", "openapi"})


def _require_text(name: str, value: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")


@dataclass(frozen=True)
class SourceRef:
    source_type: str
    ref: str
    module_id: str | None = None
    revision: str | None = None
    page_id: str | None = None
    page_version: int | None = None
    observed_at: str | None = None

    def __post_init__(self) -> None:
        if self.source_type not in SOURCE_TYPES:
            raise ValueError(f"unsupported source_type: {self.source_type!r}")
        _require_text("ref", self.ref)
        if self.source_type in REPOSITORY_SOURCE_TYPES and not (self.module_id and self.revision):
            raise ValueError("repository/openapi source requires module_id and revision")
        if self.source_type == "confluence" and not (self.page_id and self.page_version is not None):
            raise ValueError("confluence source requires page_id and page_version")


@dataclass(frozen=True)
class EvidenceRecord:
    entity_type: str
    entity_id: str
    section: str
    field: str
    statement: str
    source: SourceRef
    confidence: str
    freshness: str

    def __post_init__(self) -> None:
        for name in ("entity_type", "entity_id", "section", "field", "statement", "confidence", "freshness"):
            _require_text(name, getattr(self, name))
        if not isinstance(self.source, SourceRef):
            raise ValueError("source must be a SourceRef")


@dataclass(frozen=True)
class EvidenceDocument:
    producer: str
    records: tuple[EvidenceRecord, ...]
    version: int = 1
    generated_at: str = dataclass_field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self) -> None:
        if self.version != 1:
            raise ValueError("evidence document version must be 1")
        _require_text("producer", self.producer)
        _require_text("generated_at", self.generated_at)
        if not isinstance(self.records, tuple) or not all(isinstance(record, EvidenceRecord) for record in self.records):
            raise ValueError("records must be a tuple of EvidenceRecord instances")


def load_schema(name: str) -> dict[str, Any]:
    """Load one bundled evidence JSON schema."""
    schema_path = Path(__file__).resolve().parents[2] / "schemas" / name
    with schema_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def document_to_dict(document: EvidenceDocument) -> dict[str, Any]:
    """Convert an immutable document to its schema representation."""
    return {
        "version": document.version,
        "producer": document.producer,
        "generated_at": document.generated_at,
        "records": [asdict(record) for record in document.records],
    }


def document_from_dict(data: dict[str, Any]) -> EvidenceDocument:
    """Construct immutable contracts from data already validated against the schema."""
    records = []
    for item in data["records"]:
        values = dict(item)
        values["source"] = SourceRef(**values["source"])
        records.append(EvidenceRecord(**values))
    return EvidenceDocument(
        version=data["version"],
        producer=data["producer"],
        generated_at=data["generated_at"],
        records=tuple(records),
    )


def atomic_write_text(path: Path, text: str) -> None:
    """Atomically replace *path* with UTF-8 text using a sibling temporary file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def write_evidence(document: EvidenceDocument, path: Path) -> None:
    """Validate then atomically write a deterministic UTF-8 evidence artifact."""
    data = document_to_dict(document)
    jsonschema.validate(data, load_schema("methodology-evidence.schema.json"))
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


def load_evidence(path: Path) -> EvidenceDocument:
    """Read, validate, then construct one evidence document."""
    data = json.loads(path.read_text(encoding="utf-8"))
    jsonschema.validate(data, load_schema("methodology-evidence.schema.json"))
    return document_from_dict(data)

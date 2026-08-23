"""Frozen internal records for normalized discovery artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Mapping


def _relative_posix_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or value.startswith("/")
        or ":" in value.split("/", 1)[0]
        or any(part in {".", ".."} for part in path.parts)
        or "//" in value
    ):
        raise ValueError(f"source path must be a normalized relative POSIX path: {value!r}")
    return value


def _sorted_attributes(attributes: Mapping[str, Any]) -> dict[str, Any]:
    return {key: attributes[key] for key in sorted(attributes)}


@dataclass(frozen=True)
class DiscoveryBudget:
    structured_file_bytes: int
    document_count: int
    document_file_bytes: int
    source_marker_candidates: int

    def to_dict(self) -> dict[str, int]:
        return {
            "document_count": self.document_count,
            "document_file_bytes": self.document_file_bytes,
            "source_marker_candidates": self.source_marker_candidates,
            "structured_file_bytes": self.structured_file_bytes,
        }


@dataclass(frozen=True)
class SourceRecord:
    repo_id: str
    revision: str
    path: str
    pointer: str
    selection_reason: str
    sha256: str

    def __post_init__(self) -> None:
        _relative_posix_path(self.path)

    def to_dict(self) -> dict[str, str]:
        return {
            "repo_id": self.repo_id,
            "revision": self.revision,
            "path": self.path,
            "pointer": self.pointer,
            "selection_reason": self.selection_reason,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class Candidate:
    entity_type: str
    canonical_key: str
    display_name: str
    service_identity_value: str
    service_identity_basis: str
    attributes: Mapping[str, Any]
    source: SourceRecord
    confidence: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_type": self.entity_type,
            "canonical_key": self.canonical_key,
            "display_name": self.display_name,
            "service_identity": {
                "value": self.service_identity_value,
                "basis": self.service_identity_basis,
            },
            "attributes": _sorted_attributes(self.attributes),
            "source": self.source.to_dict(),
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class ExtractorResult:
    extractor_id: str
    extractor_version: int
    repo_id: str
    snapshot_identity: str
    candidates: tuple[Candidate, ...]
    warnings: tuple[Mapping[str, Any], ...]
    errors: tuple[Mapping[str, Any], ...]
    limit_reached: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "extractor_id": self.extractor_id,
            "extractor_version": self.extractor_version,
            "repo_id": self.repo_id,
            "snapshot_identity": self.snapshot_identity,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "warnings": [_sorted_attributes(warning) for warning in self.warnings],
            "errors": [_sorted_attributes(error) for error in self.errors],
            "limit_reached": self.limit_reached,
        }

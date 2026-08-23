"""Small valid artifacts shared by bounded discovery contract tests."""

from __future__ import annotations

from typing import Any


SHA256 = "a" * 64


def indexed_source_record(size_bytes: int = 42) -> dict[str, Any]:
    """Return one selected-file record for a discovery index."""
    return {
        "repo_id": "orders-contracts",
        "revision": "0123456789abcdef",
        "path": "api/openapi.yaml",
        "pointer": "#",
        "selection_reason": "openapi-signature",
        "size_bytes": size_bytes,
        "sha256": SHA256,
    }


def interface_candidate(
    canonical_key: str = "http:orders:POST:/documents",
    source_path: str = "api/openapi.yaml",
    pointer: str = "#/paths/~1documents/post",
) -> dict[str, Any]:
    return {
        "entity_type": "interface",
        "canonical_key": canonical_key,
        "display_name": "POST /documents",
        "service_identity": {"value": "orders", "basis": "manifest"},
        "attributes": {"method": "POST", "operation": "POST /documents", "path": "/documents", "protocol": "HTTP"},
        "source": {
            "repo_id": "orders-contracts",
            "revision": "0123456789abcdef",
            "path": source_path,
            "pointer": pointer,
            "selection_reason": "openapi-signature",
            "sha256": SHA256,
        },
        "confidence": "confirmed",
    }


def valid_extractor_result(
    extractor_id: str = "openapi", candidate: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "version": 1,
        "extractor_id": extractor_id,
        "extractor_version": 1,
        "repo_id": "orders-contracts",
        "snapshot_identity": "commit:0123456789abcdef",
        "candidates": [candidate if candidate is not None else interface_candidate()],
        "warnings": [],
        "errors": [],
        "limit_reached": False,
    }

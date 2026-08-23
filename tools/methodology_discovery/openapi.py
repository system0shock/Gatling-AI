"""Deterministic extraction of bounded OpenAPI 3 and Swagger 2 documents."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from typing import Any

import yaml

if __package__:
    from . import contracts
    from .models import Candidate, ExtractorResult, SourceRecord
else:
    import contracts
    from models import Candidate, ExtractorResult, SourceRecord


EXTRACTOR_VERSION = 1
HTTP_OPERATION_KEYS = frozenset(
    {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
)
_IDENTITY_PART = re.compile(r"[^a-z0-9]+")
_PATH_PARAMETER = re.compile(r"\{\s*([^{}]+?)\s*\}")


def _slug(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = _IDENTITY_PART.sub("-", value.strip().casefold()).strip("-")
    return normalized or None


def _diagnostic(code: str, message: str, path: str | None) -> dict[str, str]:
    value = {"code": code, "message": message}
    if path:
        value["path"] = path
    return value


def _context_values(context: Mapping[str, Any]) -> tuple[str, str, Mapping[str, Any], str | None]:
    if not isinstance(context, Mapping):
        raise ValueError("extractor context must be a mapping")
    repo_id = context.get("repo_id")
    snapshot_identity = context.get("snapshot_identity")
    source = context.get("source")
    service_id = context.get("service_id")
    if not isinstance(repo_id, str) or not repo_id:
        raise ValueError("extractor context requires repo_id")
    if not isinstance(snapshot_identity, str) or not snapshot_identity:
        raise ValueError("extractor context requires snapshot_identity")
    if not isinstance(source, Mapping):
        raise ValueError("extractor context requires source provenance")
    for field in ("repo_id", "revision", "path", "selection_reason", "sha256"):
        if not isinstance(source.get(field), str) or not source[field]:
            raise ValueError(f"extractor context source requires {field}")
    if source["repo_id"] != repo_id:
        raise ValueError("extractor context source repo_id must match repo_id")
    if service_id is not None and not isinstance(service_id, str):
        raise ValueError("extractor context service_id must be a string or null")
    return repo_id, snapshot_identity, source, service_id


def _source(context: Mapping[str, Any], pointer: str) -> SourceRecord:
    _repo_id, _snapshot, source, _service_id = _context_values(context)
    return SourceRecord(
        repo_id=source["repo_id"],
        revision=source["revision"],
        path=source["path"],
        pointer=pointer,
        selection_reason=source["selection_reason"],
        sha256=source["sha256"],
    )


def _resolve_service_identity(
    context: Mapping[str, Any], info: Any
) -> tuple[str, str, list[dict[str, str]]]:
    repo_id, _snapshot, source, manifest_raw = _context_values(context)
    manifest = _slug(manifest_raw)
    contract_raw = info.get("x-service-id") if isinstance(info, Mapping) else None
    contract = _slug(contract_raw)
    warnings: list[dict[str, str]] = []
    if manifest and contract:
        if manifest == contract:
            return contract, "contract", warnings
        warnings.append(
            _diagnostic(
                "service-identity-conflict",
                f"Manifest service_id {manifest_raw!r} conflicts with contract info.x-service-id {contract_raw!r}.",
                source["path"],
            )
        )
        return f"repo-{_slug(repo_id) or 'unknown'}", "unknown", warnings
    if contract:
        return contract, "contract", warnings
    if manifest:
        return manifest, "manifest", warnings
    title = _slug(info.get("title")) if isinstance(info, Mapping) else None
    if title:
        return title, "metadata", warnings
    return f"repo-{_slug(repo_id) or 'unknown'}", "unknown", warnings


def _validated_result(
    extractor_id: str,
    context: Mapping[str, Any],
    candidates: Sequence[Candidate],
    warnings: Sequence[Mapping[str, Any]],
    errors: Sequence[Mapping[str, Any]],
) -> ExtractorResult:
    repo_id, snapshot_identity, _source_value, _service_id = _context_values(context)
    result = ExtractorResult(
        extractor_id=extractor_id,
        extractor_version=EXTRACTOR_VERSION,
        repo_id=repo_id,
        snapshot_identity=snapshot_identity,
        candidates=tuple(
            sorted(
                candidates,
                key=lambda item: (
                    item.canonical_key,
                    item.source.pointer,
                    item.display_name,
                ),
            )
        ),
        warnings=tuple(
            sorted(
                warnings,
                key=lambda item: (
                    str(item.get("code", "")),
                    str(item.get("path", "")),
                    str(item.get("message", "")),
                ),
            )
        ),
        errors=tuple(
            sorted(
                errors,
                key=lambda item: (
                    str(item.get("code", "")),
                    str(item.get("path", "")),
                    str(item.get("message", "")),
                ),
            )
        ),
        limit_reached=False,
    )
    contracts.validate_artifact(result.to_dict(), "methodology-extractor-result.schema.json")
    return result


def _pointer_part(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _parsed_mapping(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    if not isinstance(value, str):
        return None
    try:
        parsed = yaml.safe_load(value)
    except (yaml.YAMLError, ValueError):
        return None
    return parsed if isinstance(parsed, Mapping) else None


def _supported_openapi_document(document: Mapping[str, Any]) -> bool:
    has_openapi = "openapi" in document
    has_swagger = "swagger" in document
    if has_openapi == has_swagger:
        return False
    if has_openapi:
        return str(document.get("openapi", "")).strip().startswith("3.")
    return str(document.get("swagger", "")).strip() == "2.0"


def _normalize_path(value: Any) -> str | None:
    if not isinstance(value, str) or "\x00" in value or not value.strip():
        return None
    path = value.strip().replace("\\", "/")
    path = re.sub(r"/+", "/", path)
    if not path.startswith("/"):
        path = f"/{path}"
    path = _PATH_PARAMETER.sub(lambda match: "{" + match.group(1).strip() + "}", path)
    if len(path) > 1:
        path = path.rstrip("/")
    return path


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({item.strip() for item in value if isinstance(item, str) and item.strip()})


def _servers(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted(
        {
            item["url"].strip()
            for item in value
            if isinstance(item, Mapping)
            and isinstance(item.get("url"), str)
            and item["url"].strip()
        }
    )


def _operation_attributes(
    operation: Mapping[str, Any], method: str, path: str, document: Mapping[str, Any]
) -> dict[str, Any]:
    attributes: dict[str, Any] = {
        "protocol": "HTTP",
        "operation": f"{method} {path}",
        "method": method,
        "path": path,
    }
    operation_id = operation.get("operationId")
    if isinstance(operation_id, str) and operation_id.strip():
        attributes["operation_id"] = operation_id.strip()
    tags = _string_list(operation.get("tags"))
    if tags:
        attributes["tags"] = tags
    summary = operation.get("summary")
    if isinstance(summary, str) and summary.strip():
        attributes["summary"] = summary.strip()
    responses = operation.get("responses")
    if isinstance(responses, Mapping):
        attributes["response_codes"] = sorted(str(code) for code in responses)
    server_values = _servers(operation.get("servers")) or _servers(document.get("servers"))
    if server_values:
        attributes["servers"] = server_values
    base_path = document.get("basePath")
    if isinstance(base_path, str) and base_path.strip():
        attributes["base_path"] = base_path.strip()
    host = document.get("host")
    if isinstance(host, str) and host.strip():
        attributes["host"] = host.strip()
    schemes = _string_list(document.get("schemes"))
    if schemes:
        attributes["schemes"] = schemes
    return attributes


def extract_openapi(document: Any, context: Mapping[str, Any]) -> ExtractorResult:
    """Extract local operation facts from one already bounded parsed document."""
    _repo_id, _snapshot, source, _manifest = _context_values(context)
    source_path = source["path"]
    parsed_document = _parsed_mapping(document)
    if parsed_document is None or not _supported_openapi_document(parsed_document):
        return _validated_result(
            "openapi",
            context,
            (),
            (),
            (_diagnostic("invalid-openapi-document", "Expected an OpenAPI 3 or Swagger 2 mapping.", source_path),),
        )
    document = parsed_document
    paths = document.get("paths")
    if not isinstance(paths, Mapping):
        return _validated_result(
            "openapi",
            context,
            (),
            (),
            (_diagnostic("invalid-openapi-document", "Document paths must be a mapping.", source_path),),
        )

    identity, basis, warnings = _resolve_service_identity(context, document.get("info"))
    candidates: list[Candidate] = []
    for raw_path, path_item in sorted(paths.items(), key=lambda item: str(item[0])):
        normalized_path = _normalize_path(raw_path)
        if normalized_path is None:
            warnings.append(_diagnostic("malformed-path", "Path key must be a non-empty string.", source_path))
            continue
        if not isinstance(path_item, Mapping):
            warnings.append(_diagnostic("malformed-path-item", f"Path item {raw_path!r} is not a mapping.", source_path))
            continue
        if "$ref" in path_item:
            warnings.append(_diagnostic("reference-not-resolved", f"Reference at path {raw_path!r} was not resolved.", source_path))
        for operation_key, operation in sorted(path_item.items(), key=lambda item: str(item[0])):
            if not isinstance(operation_key, str) or operation_key.casefold() not in HTTP_OPERATION_KEYS:
                continue
            method = operation_key.upper()
            if not isinstance(operation, Mapping):
                warnings.append(_diagnostic("malformed-operation", f"{method} {normalized_path} is not a mapping.", source_path))
                continue
            pointer = f"#/paths/{_pointer_part(str(raw_path))}/{operation_key.casefold()}"
            candidates.append(
                Candidate(
                    entity_type="interface",
                    canonical_key=f"http:{identity}:{method}:{normalized_path}",
                    display_name=f"{method} {normalized_path}",
                    service_identity_value=identity,
                    service_identity_basis=basis,
                    attributes=_operation_attributes(operation, method, normalized_path, document),
                    source=_source(context, pointer),
                    confidence="confirmed",
                )
            )
    return _validated_result("openapi", context, candidates, warnings, ())

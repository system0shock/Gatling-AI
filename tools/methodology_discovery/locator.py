"""Deterministic signature location under the approved discovery budget."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

import yaml

if __package__:
    from . import contracts
    from .models import DiscoveryBudget
    from .source_views import DiscoveryError, SourceView, normalize_source_path
else:
    import contracts
    from models import DiscoveryBudget
    from source_views import DiscoveryError, SourceView, normalize_source_path


MIB = 1024 * 1024
DEFAULT_BUDGET = DiscoveryBudget(
    structured_file_bytes=5 * MIB,
    document_count=20,
    document_file_bytes=1 * MIB,
    source_marker_candidates=500,
)

DiscoveryIndex = dict[str, Any]

_EXCLUDED_PARTS = frozenset({
    ".git",
    ".gradle",
    ".idea",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "env",
    "generated",
    "generated-sources",
    "node_modules",
    "out",
    "report",
    "reports",
    "site-packages",
    "target",
    "vendor",
    "venv",
})

_GRAPHQL_DEFINITION = re.compile(
    r"(?m)^\s*(?:schema|type|interface|input|enum|scalar|union|directive)\b"
)
_JAVA_MARKER = re.compile(
    rb"@(?:RequestMapping|GetMapping|PostMapping|PutMapping|DeleteMapping|"
    rb"PatchMapping|KafkaListener|QueryMapping|MutationMapping|SubscriptionMapping|"
    rb"SchemaMapping|DgsQuery|DgsMutation|DgsSubscription)\b"
)


@dataclass(frozen=True)
class _Selected:
    category: int
    priority: int
    inspected: int
    path: str
    reason: str
    content: bytes

    @property
    def sort_key(self) -> tuple[int, int, int, str]:
        return (self.category, self.inspected, self.priority, self.path)


def _matches_hint(path: str, hints: Sequence[str]) -> bool:
    relative = PurePosixPath(path)
    for hint in hints:
        normalized = hint.replace("\\", "/").strip("/")
        if not normalized:
            continue
        if (
            path == normalized
            or path.startswith(f"{normalized}/")
            or relative.match(normalized)
        ):
            return True
    return False


def _excluded(path: str, configured: Sequence[str]) -> bool:
    if any(part.casefold() in _EXCLUDED_PARTS for part in PurePosixPath(path).parts):
        return True
    return _matches_hint(path, configured)


def _document_signature(path: str, user_documents: frozenset[str]) -> tuple[int, str] | None:
    if path in user_documents:
        return (0, "user-supplied-document")
    lower = path.casefold()
    parts = PurePosixPath(lower).parts
    basename = parts[-1]
    if basename == "readme" or basename.startswith("readme."):
        return (1, "readme-document")
    if len(parts) >= 2 and parts[0] == "docs" and parts[1] == "architecture":
        return (2, "architecture-document")
    if len(parts) >= 2 and parts[0] == "docs" and parts[1] in {"adr", "adrs"}:
        return (3, "adr-document")
    if "architecture" in lower:
        return (4, "architecture-document")
    if "endpoint" in lower:
        return (5, "endpoint-document")
    if "flow" in lower:
        return (6, "flow-document")
    return None


def _mapping_documents(path: str, content: bytes) -> tuple[Mapping[str, Any], ...]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DiscoveryError(
            "source-not-utf8-text", "structured source is not UTF-8", path=path
        ) from exc
    try:
        if path.casefold().endswith(".json"):
            value = json.loads(text)
            return (value,) if isinstance(value, Mapping) else ()
        values = tuple(yaml.safe_load_all(text))
    except (json.JSONDecodeError, yaml.YAMLError, ValueError):
        return ()
    return tuple(value for value in values if isinstance(value, Mapping))


def _structured_signature(path: str, content: bytes) -> tuple[int, str] | None:
    lower = path.casefold()
    basename = PurePosixPath(lower).name
    suffix = PurePosixPath(lower).suffix

    if suffix in {".graphql", ".graphqls", ".gql"}:
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DiscoveryError(
                "source-not-utf8-text", "GraphQL source is not UTF-8", path=path
            ) from exc
        if _GRAPHQL_DEFINITION.search(text):
            return (0, "graphql-sdl-signature")
        return None

    mappings: tuple[Mapping[str, Any], ...] = ()
    if suffix in {".yaml", ".yml", ".json"}:
        mappings = _mapping_documents(path, content)
        for mapping in mappings:
            if "openapi" in mapping or "swagger" in mapping:
                return (0, "openapi-signature")
            if "asyncapi" in mapping:
                return (0, "asyncapi-signature")

    if basename == "chart.yaml":
        if any("apiVersion" in mapping and "name" in mapping for mapping in mappings):
            return (2, "helm-chart-signature")
        return None
    if basename == "pom.xml":
        if re.search(rb"<(?:project|artifactId)(?:\s|>)", content):
            return (2, "maven-build-signature")
        return None
    if basename in {"build.gradle", "build.gradle.kts"}:
        if re.search(rb"\b(?:plugins|dependencies|rootProject\.name|group)\b", content):
            return (2, "gradle-build-signature")
        return None

    for mapping in mappings:
        if "apiVersion" in mapping and "kind" in mapping:
            return (2, "kubernetes-signature")
        services = mapping.get("services")
        compose_name = basename in {
            "compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml"
        }
        compose_marker = "name" in mapping or "version" in mapping
        if isinstance(services, Mapping) and (compose_name or compose_marker):
            return (2, "docker-compose-signature")

    is_spring_name = (
        basename.startswith("application.")
        or basename.startswith("application-")
        or basename.startswith("bootstrap.")
        or basename.startswith("bootstrap-")
    )
    if is_spring_name:
        if suffix == ".properties":
            if re.search(rb"(?m)^\s*spring\.[A-Za-z0-9_.-]+\s*=", content):
                return (2, "spring-configuration-signature")
        elif any("spring" in mapping for mapping in mappings):
            return (2, "spring-configuration-signature")
    return None


def _is_structured_candidate(path: str) -> bool:
    lower = path.casefold()
    basename = PurePosixPath(lower).name
    return (
        PurePosixPath(lower).suffix in {".yaml", ".yml", ".json", ".graphql", ".graphqls", ".gql"}
        or basename in {"pom.xml", "build.gradle", "build.gradle.kts"}
        or basename.startswith("application.")
        or basename.startswith("application-")
        or basename.startswith("bootstrap.")
        or basename.startswith("bootstrap-")
    )


def _source_record(
    view: SourceView, repo_id: str, selection: _Selected
) -> dict[str, str]:
    return {
        "repo_id": repo_id,
        "revision": view.revision,
        "path": selection.path,
        "pointer": "#",
        "selection_reason": selection.reason,
        "sha256": hashlib.sha256(selection.content).hexdigest(),
    }


def _warning(code: str, message: str, path: str | None = None) -> dict[str, str]:
    result = {"code": code, "message": message}
    if path is not None:
        result["path"] = path
    return result


def _repository_value(repository: Any, name: str, default: Any) -> Any:
    return getattr(repository, name, default)


def locate_sources(
    view: SourceView,
    repository: Any,
    budget: DiscoveryBudget,
    source_markers_enabled: bool,
    *,
    user_documents: Sequence[str] = (),
) -> DiscoveryIndex:
    """Return one schema-valid, deterministic, hard-bounded discovery index."""
    if not isinstance(budget, DiscoveryBudget):
        raise DiscoveryError("invalid-discovery-budget", "budget must be DiscoveryBudget")
    repo_id = _repository_value(repository, "module_id", None)
    if not isinstance(repo_id, str) or not repo_id:
        raise DiscoveryError("invalid-repository", "repository ID is required")
    inspect = tuple(_repository_value(repository, "inspect", ()))
    exclude = tuple(_repository_value(repository, "exclude", ()))
    if not all(isinstance(value, str) for value in (*inspect, *exclude)):
        raise DiscoveryError("invalid-repository", "inspect and exclude hints must be strings")

    normalized_user_documents: list[str] = []
    for path in user_documents:
        normalized_user_documents.append(normalize_source_path(path))
    if len(normalized_user_documents) != len(set(normalized_user_documents)):
        raise DiscoveryError("duplicate-user-document", "user document paths must be unique")
    user_document_set = frozenset(normalized_user_documents)

    try:
        paths = tuple(sorted(normalize_source_path(path) for path in view.list_paths()))
        available = set(paths)
        for path in normalized_user_documents:
            if path not in available:
                raise DiscoveryError(
                    "user-document-not-found", "explicit document is absent from the snapshot", path=path
                )
            if _excluded(path, exclude):
                raise DiscoveryError(
                    "user-document-excluded", "explicit document is excluded by repository policy", path=path
                )

        selected: list[_Selected] = []
        structured_selected_paths: set[str] = set()
        skipped: list[dict[str, str]] = []
        warnings: list[dict[str, str]] = []
        limit_reached = False

        candidates = [path for path in paths if not _excluded(path, exclude)]

        # Contracts/configuration are signature-selected. Unknown files are not read.
        for path in candidates:
            if not _is_structured_candidate(path):
                continue
            try:
                content = view.read_bytes(path, budget.structured_file_bytes)
            except DiscoveryError as exc:
                if exc.code != "source-file-too-large":
                    raise
                skipped.append({"path": path, "reason": "structured-file-byte-limit"})
                warnings.append(_warning(
                    "structured-file-byte-limit",
                    f"Structured source exceeds {budget.structured_file_bytes} bytes and was not selected.",
                    path,
                ))
                limit_reached = True
                continue
            try:
                signature = _structured_signature(path, content)
            except DiscoveryError as exc:
                if exc.code != "source-not-utf8-text":
                    raise
                skipped.append({"path": path, "reason": exc.code})
                warnings.append(_warning(exc.code, "Structured source is not UTF-8 text.", path))
                continue
            if signature is None:
                skipped.append({"path": path, "reason": "unrecognized-signature"})
                continue
            category, reason = signature
            selected.append(_Selected(
                category=category,
                priority=0,
                inspected=0 if _matches_hint(path, inspect) else 1,
                path=path,
                reason=reason,
                content=content,
            ))
            structured_selected_paths.add(path)

        # Documents are chosen by deterministic path priority before content reads.
        document_paths: list[tuple[int, int, str, str]] = []
        for path in candidates:
            if path in structured_selected_paths:
                continue
            signature = _document_signature(path, user_document_set)
            if signature is None:
                continue
            priority, reason = signature
            document_paths.append((0 if _matches_hint(path, inspect) else 1, priority, path, reason))
        document_paths.sort()
        documents_selected = 0
        for inspected, priority, path, reason in document_paths:
            if documents_selected >= budget.document_count:
                skipped.append({"path": path, "reason": "document-count-limit"})
                warnings.append(_warning(
                    "document-count-limit",
                    f"Only {budget.document_count} documents may be selected; explicit deepening is required.",
                    path,
                ))
                limit_reached = True
                continue
            try:
                text = view.read_text(path, budget.document_file_bytes)
            except DiscoveryError as exc:
                if exc.code == "source-not-utf8-text" and path in user_document_set:
                    raise
                if exc.code not in {"source-file-too-large", "source-not-utf8-text"}:
                    raise
                skip_reason = (
                    "document-file-byte-limit"
                    if exc.code == "source-file-too-large"
                    else exc.code
                )
                skipped.append({"path": path, "reason": skip_reason})
                warnings.append(_warning(
                    skip_reason,
                    (
                        f"Document exceeds {budget.document_file_bytes} bytes and was not selected."
                        if exc.code == "source-file-too-large"
                        else "Document is not UTF-8 text and was not selected."
                    ),
                    path,
                ))
                if exc.code == "source-file-too-large":
                    limit_reached = True
                continue
            selected.append(_Selected(
                category=1,
                priority=priority,
                inspected=inspected,
                path=path,
                reason=reason,
                content=text.encode("utf-8"),
            ))
            documents_selected += 1

        marker_candidates = 0
        if source_markers_enabled:
            for path in candidates:
                if not path.casefold().endswith(".java"):
                    continue
                try:
                    content = view.read_bytes(path, budget.structured_file_bytes)
                except DiscoveryError as exc:
                    if exc.code != "source-file-too-large":
                        raise
                    skipped.append({"path": path, "reason": "structured-file-byte-limit"})
                    warnings.append(_warning(
                        "structured-file-byte-limit",
                        f"Source-marker file exceeds {budget.structured_file_bytes} bytes.",
                        path,
                    ))
                    limit_reached = True
                    continue
                matches = tuple(_JAVA_MARKER.finditer(content))
                if not matches:
                    skipped.append({"path": path, "reason": "unrecognized-signature"})
                    continue
                if marker_candidates >= budget.source_marker_candidates:
                    skipped.append({"path": path, "reason": "source-marker-candidate-limit"})
                    warnings.append(_warning(
                        "source-marker-candidate-limit",
                        f"Only {budget.source_marker_candidates} source-marker candidates may be retained.",
                        path,
                    ))
                    limit_reached = True
                    continue
                selected.append(_Selected(
                    category=3,
                    priority=0,
                    inspected=0 if _matches_hint(path, inspect) else 1,
                    path=path,
                    reason="java-framework-marker",
                    content=content,
                ))
                retained = min(
                    len(matches), budget.source_marker_candidates - marker_candidates
                )
                marker_candidates += retained
                if retained < len(matches):
                    warnings.append(_warning(
                        "source-marker-candidate-limit",
                        f"Only {budget.source_marker_candidates} source-marker candidates may be retained.",
                        path,
                    ))
                    limit_reached = True

        selected.sort(key=lambda item: item.sort_key)
        skipped.sort(key=lambda item: (item["path"], item["reason"]))
        warnings.sort(key=lambda item: (item["code"], item.get("path", ""), item["message"]))
        index: DiscoveryIndex = {
            "version": 1,
            "repo_id": repo_id,
            "snapshot_identity": view.snapshot_identity,
            "source_mode": view.source_mode,
            "effective_budget": budget.to_dict(),
            "selected_files": [_source_record(view, repo_id, item) for item in selected],
            "skipped_files": skipped,
            "counters": {
                "documents_selected": documents_selected,
                "indexed_paths": len(paths),
                "selected_files": len(selected),
                "skipped_files": len(skipped),
                "source_marker_candidates": marker_candidates,
            },
            "warnings": warnings,
            "limit_reached": limit_reached,
        }
        contracts.validate_artifact(index, "methodology-discovery-index.schema.json")
        return index
    finally:
        view.verify_run_guard()

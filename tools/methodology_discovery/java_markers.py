"""Fixed, line-oriented extraction of explicitly selected Java annotations."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

if __package__:
    from . import contracts
    from .models import Candidate, ExtractorResult
    from .openapi import _context_values, _diagnostic, _normalize_path, _resolve_service_identity, _source
else:
    import contracts
    from models import Candidate, ExtractorResult
    from openapi import _context_values, _diagnostic, _normalize_path, _resolve_service_identity, _source


_ANNOTATION = re.compile(
    r'^\s*@(?P<name>RequestMapping|GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping|KafkaListener|QueryMapping|MutationMapping|SubscriptionMapping|SchemaMapping|DgsQuery|DgsMutation|DgsSubscription)\s*(?:\((?P<args>.*)\))?\s*$'
)
_CLASS = re.compile(r"\b(?:class|interface|record)\s+[A-Za-z_$][A-Za-z0-9_$]*")
_METHOD = re.compile(r"\b([A-Za-z_$][A-Za-z0-9_$]*)\s*\([^;{}]*\)\s*(?:\{|throws\b|$)")
_STRING = re.compile(r'"([^"\\]*(?:\\.[^"\\]*)*)"')
_REQUEST_METHOD = re.compile(r"\bRequestMethod\.(GET|POST|PUT|DELETE|PATCH|OPTIONS|HEAD)\b")
_HTTP_METHODS = {
    "GetMapping": "GET",
    "PostMapping": "POST",
    "PutMapping": "PUT",
    "DeleteMapping": "DELETE",
    "PatchMapping": "PATCH",
}
_GRAPHQL_ROOTS = {
    "QueryMapping": "Query",
    "DgsQuery": "Query",
    "MutationMapping": "Mutation",
    "DgsMutation": "Mutation",
    "SubscriptionMapping": "Subscription",
    "DgsSubscription": "Subscription",
}


def _literal_values(
    args: str | None, names: tuple[str, ...], *, positional: bool = True
) -> tuple[tuple[str, ...], bool]:
    if args is None or not args.strip():
        return (), False
    selected: str | None = None
    named_present = False
    for name in names:
        if re.search(rf"\b{re.escape(name)}\s*=", args):
            named_present = True
        match = re.search(
            rf"\b{re.escape(name)}\s*=\s*(\{{[^}}]*\}}|\"(?:[^\"\\]|\\.)*\")",
            args,
        )
        if match is not None:
            selected = match.group(1)
            break
    if selected is None and positional:
        stripped = args.strip()
        if stripped.startswith('"') or stripped.startswith("{"):
            selected = stripped
    if selected is None:
        return (), named_present
    values: list[str] = []
    dynamic = False
    for match in _STRING.finditer(selected):
        value = match.group(1).strip()
        if not value or "${" in value or "#{" in value:
            dynamic = True
        else:
            values.append(value)
    if not values:
        dynamic = True
    return tuple(dict.fromkeys(values)), dynamic


def _joined_path(prefix: str | None, suffix: str | None) -> str:
    parts = [part.strip("/") for part in (prefix, suffix) if isinstance(part, str) and part.strip("/")]
    return _normalize_path("/".join(parts)) or "/"


def _candidate(
    context: Mapping[str, Any],
    identity: str,
    basis: str,
    entity_type: str,
    canonical_key: str,
    display_name: str,
    attributes: Mapping[str, Any],
    line_number: int,
) -> Candidate:
    return Candidate(
        entity_type=entity_type,
        canonical_key=canonical_key,
        display_name=display_name,
        service_identity_value=identity,
        service_identity_basis=basis,
        attributes=dict(attributes),
        source=_source(context, f"#L{line_number}"),
        confidence="candidate",
    )


def extract_java_markers(
    text: Any,
    context: Mapping[str, Any],
    remaining_candidate_budget: int,
) -> ExtractorResult:
    """Extract literal framework annotations from one already-selected Java text."""
    if (
        not isinstance(remaining_candidate_budget, int)
        or isinstance(remaining_candidate_budget, bool)
        or remaining_candidate_budget < 0
    ):
        raise ValueError("remaining_candidate_budget must be a non-negative integer")
    _repo_id, snapshot_identity, source, _service_id = _context_values(context)
    identity, basis, warnings = _resolve_service_identity(context, {})
    errors: list[dict[str, str]] = []
    if not isinstance(text, str):
        errors.append(_diagnostic("invalid-java-source", "Java marker input must be text.", source["path"]))
        text = ""

    candidates: list[Candidate] = []
    class_paths: tuple[str | None, ...] = (None,)
    pending_class_paths: tuple[str | None, ...] | None = None
    pending_graphql: tuple[str, tuple[str, ...], int] | None = None
    brace_depth = 0
    active_class_depth: int | None = None
    in_block_comment = False
    budget_reached = False

    def retain(candidate: Candidate) -> None:
        nonlocal budget_reached
        if len(candidates) < remaining_candidate_budget:
            candidates.append(candidate)
        else:
            budget_reached = True

    for line_number, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line
        if in_block_comment:
            if "*/" not in line:
                continue
            line = line.split("*/", 1)[1]
            in_block_comment = False
        while "/*" in line:
            before, after = line.split("/*", 1)
            if "*/" in after:
                line = before + after.split("*/", 1)[1]
                continue
            line = before
            in_block_comment = True
            break
        annotation = _ANNOTATION.fullmatch(line)
        if annotation is not None:
            name = annotation.group("name")
            args = annotation.group("args")
            if name == "RequestMapping" and active_class_depth is None:
                values, dynamic = _literal_values(args, ("path", "value"))
                if dynamic:
                    warnings.append(_diagnostic("dynamic-java-annotation", "Dynamic class RequestMapping was not resolved.", source["path"]))
                pending_class_paths = () if dynamic else values or (None,)
                continue
            if name in _HTTP_METHODS or name == "RequestMapping":
                methods = (_HTTP_METHODS[name],) if name in _HTTP_METHODS else tuple(dict.fromkeys(_REQUEST_METHOD.findall(args or "")))
                values, dynamic = _literal_values(args, ("path", "value"))
                if dynamic:
                    warnings.append(_diagnostic("dynamic-java-annotation", f"Dynamic {name} path was not resolved.", source["path"]))
                if not values and dynamic:
                    continue
                if not methods:
                    warnings.append(_diagnostic("dynamic-java-annotation", "RequestMapping without one literal HTTP method was not emitted.", source["path"]))
                    continue
                for class_path in class_paths:
                    for value in values or (None,):
                        path = _joined_path(class_path, value)
                        for method in methods:
                            retain(_candidate(context, identity, basis, "interface", f"http:{identity}:{method}:{path}", f"{method} {path}", {"method": method, "operation": f"{method} {path}", "path": path, "protocol": "HTTP"}, line_number))
                continue
            if name == "KafkaListener":
                topics, dynamic = _literal_values(args, ("topics",), positional=False)
                if dynamic:
                    warnings.append(_diagnostic("dynamic-java-annotation", "KafkaListener without one literal topic was not emitted.", source["path"]))
                for topic in topics:
                    retain(_candidate(context, identity, basis, "integration", f"message:{identity}:{topic}:subscribe", f"subscribe {topic}", {"direction": "subscribe", "operation": f"subscribe {topic}", "protocol": "Kafka", "topic": topic}, line_number))
                continue
            if name in _GRAPHQL_ROOTS:
                fields, dynamic = _literal_values(args, ("name", "value", "field"))
                if dynamic:
                    warnings.append(_diagnostic("dynamic-java-annotation", f"Dynamic {name} field was not resolved.", source["path"]))
                    continue
                pending_graphql = (_GRAPHQL_ROOTS[name], fields, line_number)
                continue
            if name == "SchemaMapping":
                fields, dynamic = _literal_values(args, ("field", "value", "name"), positional=False)
                if dynamic or not fields:
                    warnings.append(_diagnostic("dynamic-java-annotation", "SchemaMapping without a literal field was not emitted.", source["path"]))
                    continue
                pending_graphql = ("Schema", fields, line_number)
                continue

        if _CLASS.search(line):
            class_paths = pending_class_paths if pending_class_paths is not None else (None,)
            pending_class_paths = None
            active_class_depth = brace_depth + max(1, line.count("{") - line.count("}"))
        if pending_graphql is not None:
            method = _METHOD.search(line)
            if method is not None:
                root, explicit_fields, annotation_line = pending_graphql
                for field in explicit_fields or (method.group(1),):
                    retain(_candidate(context, identity, basis, "interface", f"graphql:{identity}:{root}:{field}", f"{root}.{field}", {"field": field, "operation": f"{root}.{field}", "protocol": "GraphQL", "root_operation": root}, annotation_line))
                pending_graphql = None
        brace_depth += line.count("{") - line.count("}")
        if active_class_depth is not None and brace_depth < active_class_depth:
            active_class_depth = None
            class_paths = (None,)

    if pending_graphql is not None:
        warnings.append(_diagnostic("incomplete-java-annotation", "GraphQL annotation had no following method declaration.", source["path"]))
    if budget_reached:
        warnings.append(_diagnostic("source-marker-candidate-limit", f"Only {remaining_candidate_budget} source-marker candidates may be retained.", source["path"]))

    result = ExtractorResult(
        extractor_id="java-markers",
        extractor_version=1,
        repo_id=context["repo_id"],
        snapshot_identity=snapshot_identity,
        candidates=tuple(sorted(candidates, key=lambda item: (item.canonical_key, item.source.pointer, item.display_name))),
        warnings=tuple(sorted(warnings, key=lambda item: (item["code"], item.get("path", ""), item["message"]))),
        errors=tuple(sorted(errors, key=lambda item: (item["code"], item.get("path", ""), item["message"]))),
        limit_reached=budget_reached,
    )
    contracts.validate_artifact(result.to_dict(), "methodology-extractor-result.schema.json")
    return result

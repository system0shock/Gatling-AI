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
_ANY_ANNOTATION = re.compile(
    r"^\s*@[A-Za-z_$][A-Za-z0-9_$.]*(?:\s*\(.*\))?\s*$"
)
_CLASS = re.compile(
    r"\b(?:class|interface|record)\s+(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)"
)
_METHOD = re.compile(
    r"^\s*(?P<prefix>[^;{}()=]+?)\s+"
    r"(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)\s*"
    r"\([^;{}]*\)\s*(?:throws\b[^;{}]*)?\s*(?:\{|;|$)"
)
_STRING = re.compile(r'"(?P<value>(?:[^"\\\r\n]|\\.)*)"')
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


def _split_top_level(value: str) -> tuple[tuple[str, ...], bool]:
    """Split comma-separated Java annotation arguments without recursion."""
    parts: list[str] = []
    start = 0
    stack: list[str] = []
    quote: str | None = None
    escaped = False
    pairs = {")": "(", "]": "[", "}": "{"}
    for index, character in enumerate(value):
        if quote is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in {'"', "'"}:
            quote = character
        elif character in "([{":
            stack.append(character)
        elif character in ")]}":
            if not stack or stack.pop() != pairs[character]:
                return (value,), False
        elif character == "," and not stack:
            parts.append(value[start:index])
            start = index + 1
    parts.append(value[start:])
    return tuple(parts), quote is None and not stack


def _argument_expression(
    args: str | None,
    names: tuple[str, ...],
    *,
    positional: bool,
) -> tuple[str | None, bool]:
    if args is None or not args.strip():
        return None, False
    parts, valid = _split_top_level(args)
    if not valid:
        return None, True
    for name in names:
        pattern = re.compile(rf"^\s*{re.escape(name)}\s*=\s*(.*?)\s*$")
        for part in parts:
            match = pattern.fullmatch(part)
            if match is not None:
                return match.group(1), False
    has_named_argument = any(
        re.match(r"^\s*[A-Za-z_$][A-Za-z0-9_$]*\s*=", part)
        for part in parts
    )
    if positional and len(parts) == 1 and not has_named_argument:
        return parts[0].strip(), False
    return None, False


def _literal_values(
    args: str | None,
    names: tuple[str, ...],
    *,
    positional: bool = True,
) -> tuple[tuple[str, ...], frozenset[str]]:
    expression, malformed = _argument_expression(args, names, positional=positional)
    issues: set[str] = {"unsupported-java-literal"} if malformed else set()
    if expression is None:
        return (), frozenset(issues)
    stripped = expression.strip()
    is_array = stripped.startswith("{") and stripped.endswith("}")
    if stripped.startswith("{") != stripped.endswith("}"):
        return (), frozenset({*issues, "unsupported-java-literal"})
    members, valid = _split_top_level(stripped[1:-1] if is_array else stripped)
    if not valid:
        return (), frozenset({*issues, "unsupported-java-literal"})
    values: list[str] = []
    for member in members:
        literal = member.strip()
        match = _STRING.fullmatch(literal)
        if match is None:
            issues.add(
                "unsupported-java-literal"
                if is_array or '"' in literal
                else "dynamic-java-annotation"
            )
            continue
        raw_value = match.group("value")
        if "\\" in raw_value:
            issues.add("unsupported-java-literal")
            continue
        value = raw_value.strip()
        if not value:
            issues.add("unsupported-java-literal")
        elif "${" in value or "#{" in value:
            issues.add("dynamic-java-annotation")
        else:
            values.append(value)
    if not members or (not values and not issues):
        issues.add("dynamic-java-annotation")
    return tuple(dict.fromkeys(values)), frozenset(issues)


def _request_methods(args: str | None) -> tuple[tuple[str, ...], frozenset[str]]:
    expression, malformed = _argument_expression(args, ("method",), positional=False)
    issues: set[str] = {"unsupported-java-literal"} if malformed else set()
    if expression is None:
        return (), frozenset(issues)
    stripped = expression.strip()
    is_array = stripped.startswith("{") and stripped.endswith("}")
    if stripped.startswith("{") != stripped.endswith("}"):
        return (), frozenset({*issues, "unsupported-java-literal"})
    members, valid = _split_top_level(stripped[1:-1] if is_array else stripped)
    if not valid:
        return (), frozenset({*issues, "unsupported-java-literal"})
    methods: list[str] = []
    for member in members:
        match = _REQUEST_METHOD.fullmatch(member.strip())
        if match is None:
            issues.add(
                "unsupported-java-literal"
                if is_array
                else "dynamic-java-annotation"
            )
        else:
            methods.append(match.group(1))
    return tuple(dict.fromkeys(methods)), frozenset(issues)


def _java_lexical_views(text: str) -> tuple[str, str]:
    """Return comment-masked and code-only views with exact source offsets."""
    visible = list(text)
    structural = list(text)
    state = "code"
    escaped = False
    index = 0

    def mask(position: int, *, comments: bool) -> None:
        if text[position] not in "\r\n":
            structural[position] = " "
            if comments:
                visible[position] = " "

    while index < len(text):
        character = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        if state == "line-comment":
            if character in "\r\n":
                state = "code"
            else:
                mask(index, comments=True)
            index += 1
            continue
        if state == "block-comment":
            if character == "*" and following == "/":
                mask(index, comments=True)
                mask(index + 1, comments=True)
                state = "code"
                index += 2
                continue
            mask(index, comments=True)
            index += 1
            continue
        if state == "text-block":
            if text.startswith('"""', index) and not escaped:
                for offset in range(3):
                    mask(index + offset, comments=False)
                state = "code"
                index += 3
                continue
            mask(index, comments=False)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            index += 1
            continue
        if state in {"string", "character"}:
            mask(index, comments=False)
            quote = '"' if state == "string" else "'"
            if character in "\r\n":
                state = "code"
                escaped = False
            elif escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                state = "code"
            index += 1
            continue
        if character == "/" and following == "/":
            mask(index, comments=True)
            mask(index + 1, comments=True)
            state = "line-comment"
            index += 2
            continue
        if character == "/" and following == "*":
            mask(index, comments=True)
            mask(index + 1, comments=True)
            state = "block-comment"
            index += 2
            continue
        if text.startswith('"""', index):
            for offset in range(3):
                mask(index + offset, comments=False)
            state = "text-block"
            escaped = False
            index += 3
            continue
        if character == '"':
            mask(index, comments=False)
            state = "string"
            escaped = False
            index += 1
            continue
        if character == "'":
            mask(index, comments=False)
            state = "character"
            escaped = False
            index += 1
            continue
        index += 1
    return "".join(visible), "".join(structural)


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
    class_paths: tuple[str | None, ...] | None = (None,)
    unresolved_class_path = object()
    pending_class_paths: tuple[str | None, ...] | object | None = None
    pending_http: tuple[tuple[str, ...], tuple[str, ...], int] | None = None
    pending_graphql: tuple[str, tuple[str, ...], int, bool] | None = None
    pending_kafka: tuple[tuple[str, ...], int] | None = None
    brace_depth = 0
    active_class_depth: int | None = None
    active_class_name: str | None = None
    budget_reached = False

    def retain(candidate: Candidate) -> None:
        nonlocal budget_reached
        if len(candidates) < remaining_candidate_budget:
            candidates.append(candidate)
        else:
            budget_reached = True

    def warn_literal_issues(issues: frozenset[str], subject: str) -> None:
        for code in sorted(issues):
            if code == "unsupported-java-literal":
                message = f"{subject} contained an unsupported Java literal or nonliteral member."
            else:
                message = f"Dynamic {subject} was not resolved."
            warnings.append(_diagnostic(code, message, source["path"]))

    def clear_pending(
        *, class_mapping: bool = True, method_mappings: bool = True
    ) -> None:
        nonlocal pending_class_paths, pending_http, pending_graphql, pending_kafka
        if class_mapping and pending_class_paths is not None:
            warnings.append(_diagnostic("incomplete-java-annotation", "Class RequestMapping had no following compatible class declaration.", source["path"]))
            pending_class_paths = None
        if method_mappings and pending_http is not None:
            warnings.append(_diagnostic("incomplete-java-annotation", "HTTP mapping had no following compatible method declaration.", source["path"]))
        if method_mappings and pending_graphql is not None:
            warnings.append(_diagnostic("incomplete-java-annotation", "GraphQL mapping had no following compatible method declaration.", source["path"]))
        if method_mappings and pending_kafka is not None:
            warnings.append(_diagnostic("incomplete-java-annotation", "KafkaListener had no following compatible method declaration.", source["path"]))
        if method_mappings:
            pending_http = None
            pending_graphql = None
            pending_kafka = None

    visible_text, structural_text = _java_lexical_views(text)
    visible_lines = visible_text.splitlines()
    structural_lines = structural_text.splitlines()
    for line_number, (line, code_line) in enumerate(
        zip(visible_lines, structural_lines, strict=True), 1
    ):
        code_starts_annotation = code_line.lstrip().startswith("@")
        annotation = _ANNOTATION.fullmatch(line) if code_starts_annotation else None
        if annotation is not None:
            clear_pending()
            name = annotation.group("name")
            args = annotation.group("args")
            if name == "RequestMapping" and active_class_depth is None:
                values, issues = _literal_values(args, ("path", "value"))
                warn_literal_issues(issues, "class RequestMapping path")
                pending_class_paths = (
                    values
                    if values
                    else unresolved_class_path
                    if issues
                    else (None,)
                )
                continue
            if name in _HTTP_METHODS or name == "RequestMapping":
                values, path_issues = _literal_values(args, ("path", "value"))
                warn_literal_issues(path_issues, f"{name} path")
                if not values and path_issues:
                    continue
                if name in _HTTP_METHODS:
                    methods = (_HTTP_METHODS[name],)
                    method_issues = frozenset()
                else:
                    methods, method_issues = _request_methods(args)
                    warn_literal_issues(method_issues, "RequestMapping HTTP method")
                if not methods:
                    if not method_issues:
                        warnings.append(_diagnostic("dynamic-java-annotation", "RequestMapping without one literal HTTP method was not emitted.", source["path"]))
                    continue
                if class_paths is None:
                    continue
                paths = tuple(
                    dict.fromkeys(
                        _joined_path(class_path, value)
                        for class_path in class_paths
                        for value in values or (None,)
                    )
                )
                pending_http = (methods, paths, line_number)
                continue
            if name == "KafkaListener":
                topics, issues = _literal_values(args, ("topics",), positional=False)
                warn_literal_issues(issues, "KafkaListener topic")
                if not topics:
                    if not issues:
                        warnings.append(_diagnostic("dynamic-java-annotation", "KafkaListener without one literal topic was not emitted.", source["path"]))
                    continue
                pending_kafka = (topics, line_number)
                continue
            if name in _GRAPHQL_ROOTS:
                fields, issues = _literal_values(args, ("name", "value", "field"))
                warn_literal_issues(issues, f"{name} field")
                if not fields and issues:
                    continue
                pending_graphql = (_GRAPHQL_ROOTS[name], fields, line_number, False)
                continue
            if name == "SchemaMapping":
                type_names, type_issues = _literal_values(
                    args, ("typeName",), positional=False
                )
                fields, field_issues = _literal_values(
                    args, ("field", "value", "name"), positional=False
                )
                warn_literal_issues(type_issues, "SchemaMapping parent type")
                warn_literal_issues(field_issues, "SchemaMapping field")
                if len(type_names) != 1:
                    warnings.append(_diagnostic("schema-mapping-parent-required", "SchemaMapping requires one explicit literal typeName.", source["path"]))
                    continue
                if len(fields) > 1 or (not fields and field_issues):
                    continue
                pending_graphql = (type_names[0], fields, line_number, True)
                continue

        if code_starts_annotation and _ANY_ANNOTATION.fullmatch(line) is not None:
            continue

        class_match = _CLASS.search(code_line)
        method = _METHOD.search(code_line)
        if method is not None and (
            method.group("name") == active_class_name
            or method.group("prefix").split()[0] in {
                "assert", "case", "new", "return", "throw", "yield"
            }
        ):
            method = None
        class_started = class_match is not None
        if class_started:
            if pending_http is not None or pending_graphql is not None or pending_kafka is not None:
                clear_pending(class_mapping=False)
            if pending_class_paths is unresolved_class_path:
                class_paths = None
            elif isinstance(pending_class_paths, tuple):
                class_paths = pending_class_paths
            else:
                class_paths = (None,)
            pending_class_paths = None
            active_class_name = class_match.group("name")
            active_class_depth = brace_depth + max(
                1, code_line.count("{") - code_line.count("}")
            )
        elif pending_class_paths is not None and code_line.strip():
            clear_pending(method_mappings=False)

        if method is not None:
            method_name = method.group("name")
            if pending_http is not None:
                methods, paths, annotation_line = pending_http
                for http_method in methods:
                    for path in paths:
                        retain(_candidate(context, identity, basis, "interface", f"http:{identity}:{http_method}:{path}", f"{http_method} {path}", {"method": http_method, "operation": f"{http_method} {path}", "path": path, "protocol": "HTTP"}, annotation_line))
                pending_http = None
            if pending_graphql is not None:
                root, explicit_fields, annotation_line, schema_field = pending_graphql
                for field in explicit_fields or (method_name,):
                    attributes = {"field": field, "operation": f"{root}.{field}", "protocol": "GraphQL", "root_operation": root}
                    if schema_field:
                        attributes.update({"mapping_kind": "schema-field", "type_name": root})
                    retain(_candidate(context, identity, basis, "interface", f"graphql:{identity}:{root}:{field}", f"{root}.{field}", attributes, annotation_line))
                pending_graphql = None
            if pending_kafka is not None:
                topics, annotation_line = pending_kafka
                for topic in topics:
                    retain(_candidate(context, identity, basis, "integration", f"message:{identity}:{topic}:subscribe", f"subscribe {topic}", {"direction": "subscribe", "operation": f"subscribe {topic}", "protocol": "Kafka", "topic": topic}, annotation_line))
                pending_kafka = None
        elif code_line.strip() and not class_started:
            clear_pending(class_mapping=False)

        brace_depth += code_line.count("{") - code_line.count("}")
        if (
            active_class_depth is not None
            and not class_started
            and brace_depth < active_class_depth
        ):
            active_class_depth = None
            active_class_name = None
            class_paths = (None,)

    clear_pending()
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

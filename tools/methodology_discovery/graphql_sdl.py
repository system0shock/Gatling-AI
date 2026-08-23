"""Deterministic root-field extraction from bounded GraphQL SDL text."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from graphql import GraphQLError, parse, print_ast
from graphql.language.ast import (
    ObjectTypeDefinitionNode,
    ObjectTypeExtensionNode,
    SchemaDefinitionNode,
    SchemaExtensionNode,
)

if __package__:
    from .models import Candidate, ExtractorResult
    from .openapi import (
        _context_values,
        _diagnostic,
        _resolve_service_identity,
        _source,
        _validated_result,
    )
else:
    from models import Candidate, ExtractorResult
    from openapi import (
        _context_values,
        _diagnostic,
        _resolve_service_identity,
        _source,
        _validated_result,
    )


_ROOT_OPERATION_NAMES = {
    "query": "Query",
    "mutation": "Mutation",
    "subscription": "Subscription",
}


def extract_graphql_sdl(text: Any, context: Mapping[str, Any]) -> ExtractorResult:
    """Parse SDL only and emit interfaces for declared root object fields."""
    _repo_id, _snapshot, source, _manifest = _context_values(context)
    source_path = source["path"]
    if not isinstance(text, str):
        return _validated_result(
            "graphql-sdl",
            context,
            (),
            (),
            (_diagnostic("invalid-graphql-sdl", "GraphQL SDL must be text.", source_path),),
        )
    try:
        document = parse(text)
    except GraphQLError as exc:
        message = str(exc).strip() or "GraphQL SDL could not be parsed."
        return _validated_result(
            "graphql-sdl",
            context,
            (),
            (),
            (_diagnostic("invalid-graphql-sdl", message, source_path),),
        )

    schema_nodes = tuple(
        node
        for node in document.definitions
        if isinstance(node, (SchemaDefinitionNode, SchemaExtensionNode))
    )
    if schema_nodes:
        root_types: dict[str, str] = {}
        for node in schema_nodes:
            for operation in node.operation_types:
                root_types[operation.operation.value] = operation.type.name.value
    else:
        root_types = {name.casefold(): name for name in ("Query", "Mutation", "Subscription")}

    object_fields: dict[str, list[Any]] = defaultdict(list)
    for node in document.definitions:
        if isinstance(node, (ObjectTypeDefinitionNode, ObjectTypeExtensionNode)):
            object_fields[node.name.value].extend(node.fields or ())

    identity, basis, warnings = _resolve_service_identity(context, {})
    candidates: list[Candidate] = []
    seen: set[tuple[str, str]] = set()
    for operation_name, root_type in sorted(root_types.items(), key=lambda item: item[0]):
        root_operation = _ROOT_OPERATION_NAMES.get(operation_name.casefold(), operation_name.title())
        for field in sorted(object_fields.get(root_type, ()), key=lambda item: item.name.value):
            field_name = field.name.value
            stable_field = (root_operation, field_name)
            if stable_field in seen:
                warnings.append(
                    _diagnostic(
                        "duplicate-root-field",
                        f"Duplicate root field {root_type}.{field_name} was ignored.",
                        source_path,
                    )
                )
                continue
            seen.add(stable_field)
            argument_pairs = sorted(
                ((argument.name.value, print_ast(argument.type)) for argument in field.arguments or ()),
                key=lambda item: item[0],
            )
            attributes: dict[str, Any] = {
                "protocol": "GraphQL",
                "operation": f"{root_operation}.{field_name}",
                "root_operation": root_operation,
                "root_type": root_type,
                "field": field_name,
                "return_type": print_ast(field.type),
            }
            if argument_pairs:
                attributes["argument_names"] = [name for name, _type in argument_pairs]
                attributes["argument_types"] = [_type for _name, _type in argument_pairs]
                attributes["arguments"] = [f"{name}: {_type}" for name, _type in argument_pairs]
            candidates.append(
                Candidate(
                    entity_type="interface",
                    canonical_key=f"graphql:{identity}:{root_operation}:{field_name}",
                    display_name=f"{root_operation}.{field_name}",
                    service_identity_value=identity,
                    service_identity_basis=basis,
                    attributes=attributes,
                    source=_source(context, f"#type/{root_type}/field/{field_name}"),
                    confidence="confirmed",
                )
            )
    return _validated_result("graphql-sdl", context, candidates, warnings, ())

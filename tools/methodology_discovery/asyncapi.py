"""Deterministic extraction of bounded AsyncAPI v2 and v3 documents."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

if __package__:
    from .models import Candidate, ExtractorResult
    from .openapi import (
        _context_values,
        _collision_diagnostics,
        _diagnostic,
        _parsed_mapping,
        _pointer_part,
        _resolve_service_identity,
        _source,
        _supported_semver_major,
        _validated_result,
    )
else:
    from models import Candidate, ExtractorResult
    from openapi import (
        _context_values,
        _collision_diagnostics,
        _diagnostic,
        _parsed_mapping,
        _pointer_part,
        _resolve_service_identity,
        _source,
        _supported_semver_major,
        _validated_result,
    )


def _tags(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    names: set[str] = set()
    for item in value:
        if isinstance(item, str) and item.strip():
            names.add(item.strip())
        elif isinstance(item, Mapping) and isinstance(item.get("name"), str) and item["name"].strip():
            names.add(item["name"].strip())
    return sorted(names)


def _message_names(value: Any, cycle_detected: list[bool] | None = None) -> list[str]:
    names: set[str] = set()
    active: set[int] = set()
    stack: list[tuple[bool, Any]] = [(False, value)]
    while stack:
        exiting, item = stack.pop()
        if not isinstance(item, (list, Mapping)):
            continue
        identity = id(item)
        if exiting:
            active.discard(identity)
            continue
        if identity in active:
            if cycle_detected is not None:
                cycle_detected[0] = True
            continue
        active.add(identity)
        stack.append((True, item))
        if isinstance(item, list):
            stack.extend((False, nested) for nested in reversed(item))
            continue
        name = item.get("name")
        if isinstance(name, str) and name.strip():
            names.add(name.strip())
        reference = item.get("$ref")
        if isinstance(reference, str) and reference.startswith("#/"):
            tail = reference.rsplit("/", 1)[-1].replace("~1", "/").replace("~0", "~")
            if tail:
                names.add(tail)
        one_of = item.get("oneOf")
        if isinstance(one_of, list):
            stack.append((False, one_of))
    return sorted(names)


def _server_attributes(value: Any) -> list[str]:
    if not isinstance(value, Mapping):
        return []
    servers: set[str] = set()
    for name, server in value.items():
        if not isinstance(server, Mapping):
            continue
        url = server.get("url")
        protocol = server.get("protocol")
        if isinstance(url, str) and url.strip():
            parts = [str(name)]
            if isinstance(protocol, str) and protocol.strip():
                parts.append(protocol.strip())
            parts.append(url.strip())
            servers.add(":".join(parts))
    return sorted(servers)


def _direction(value: Any) -> str:
    if isinstance(value, str):
        normalized = value.casefold()
        if normalized in {"publish", "send"}:
            return "publish"
        if normalized in {"subscribe", "receive"}:
            return "subscribe"
    return "unspecified"


def _channel_reference(value: Any, channels: Mapping[str, Any]) -> tuple[str | None, Mapping[str, Any] | None]:
    if isinstance(value, str) and value in channels:
        item = channels[value]
        return value, item if isinstance(item, Mapping) else None
    if not isinstance(value, Mapping):
        return None, None
    reference = value.get("$ref")
    if not isinstance(reference, str) or not reference.startswith("#/channels/"):
        return None, None
    key = reference[len("#/channels/") :].replace("~1", "/").replace("~0", "~")
    item = channels.get(key)
    return key, item if isinstance(item, Mapping) else None


def _operation_message_names(
    operation: Mapping[str, Any],
    channel_item: Mapping[str, Any] | None,
    cycle_detected: list[bool],
) -> list[str]:
    value = operation.get("message") if "message" in operation else operation.get("messages")
    names = set(_message_names(value, cycle_detected))
    if channel_item is not None and isinstance(channel_item.get("messages"), Mapping):
        channel_messages = channel_item["messages"]
        resolved: set[str] = set()
        for name in names:
            message = channel_messages.get(name)
            if isinstance(message, Mapping):
                resolved.update(_message_names(message, cycle_detected) or [name])
            else:
                resolved.add(name)
        names = resolved
    return sorted(names)


def _candidate(
    context: Mapping[str, Any],
    identity: str,
    basis: str,
    channel: str,
    direction: str,
    operation: Mapping[str, Any],
    pointer: str,
    servers: list[str],
    channel_item: Mapping[str, Any] | None,
    warnings: list[dict[str, str]],
    source_path: str,
    fallback_operation_id: str | None = None,
) -> Candidate:
    attributes: dict[str, Any] = {
        "protocol": "AsyncAPI",
        "operation": f"{direction} {channel}",
        "channel": channel,
        "direction": direction,
    }
    operation_id = operation.get("operationId")
    if not isinstance(operation_id, str) or not operation_id.strip():
        operation_id = fallback_operation_id
    if isinstance(operation_id, str) and operation_id.strip():
        attributes["operation_id"] = operation_id.strip()
    cycle_detected = [False]
    messages = _operation_message_names(operation, channel_item, cycle_detected)
    if cycle_detected[0]:
        warnings.append(
            _diagnostic(
                "cyclic-message-one-of",
                f"Cyclic message oneOf on {channel!r} was not traversed.",
                source_path,
            )
        )
    if messages:
        attributes["message_names"] = messages
    tags = _tags(operation.get("tags"))
    if tags:
        attributes["tags"] = tags
    if servers:
        attributes["servers"] = servers
    return Candidate(
        entity_type="interface",
        canonical_key=f"message:{identity}:{channel}:{direction}",
        display_name=f"{direction} {channel}",
        service_identity_value=identity,
        service_identity_basis=basis,
        attributes=attributes,
        source=_source(context, pointer),
        confidence="confirmed",
    )


def extract_asyncapi(document: Any, context: Mapping[str, Any]) -> ExtractorResult:
    """Extract channel-operation facts without resolving references or inferring flows."""
    _repo_id, _snapshot, source, _manifest = _context_values(context)
    source_path = source["path"]
    parsed_document = _parsed_mapping(document)
    if parsed_document is None or not _supported_semver_major(
        parsed_document.get("asyncapi"), {2, 3}
    ):
        return _validated_result(
            "asyncapi",
            context,
            (),
            (),
            (_diagnostic("invalid-asyncapi-document", "Expected an AsyncAPI mapping.", source_path),),
        )
    document = parsed_document
    channels = document.get("channels")
    if not isinstance(channels, Mapping):
        return _validated_result(
            "asyncapi",
            context,
            (),
            (),
            (_diagnostic("invalid-asyncapi-document", "Document channels must be a mapping.", source_path),),
        )

    identity, basis, warnings = _resolve_service_identity(context, document.get("info"))
    servers = _server_attributes(document.get("servers"))
    candidates: list[Candidate] = []
    for channel_key, channel_item in sorted(channels.items(), key=lambda item: str(item[0])):
        if not isinstance(channel_key, str) or not channel_key.strip():
            warnings.append(_diagnostic("malformed-channel", "Channel key must be a non-empty string.", source_path))
            continue
        if not isinstance(channel_item, Mapping):
            warnings.append(_diagnostic("malformed-channel", f"Channel {channel_key!r} is not a mapping.", source_path))
            continue
        if "$ref" in channel_item:
            warnings.append(_diagnostic("reference-not-resolved", f"Reference at channel {channel_key!r} was not resolved.", source_path))
        address = channel_item.get("address")
        channel = address.strip() if isinstance(address, str) and address.strip() else channel_key.strip()
        for operation_key in ("publish", "subscribe", "send", "receive"):
            if operation_key not in channel_item:
                continue
            operation = channel_item[operation_key]
            if not isinstance(operation, Mapping):
                warnings.append(_diagnostic("malformed-operation", f"{operation_key} on {channel!r} is not a mapping.", source_path))
                continue
            candidates.append(
                _candidate(
                    context,
                    identity,
                    basis,
                    channel,
                    _direction(operation_key),
                    operation,
                    f"#/channels/{_pointer_part(channel_key)}/{operation_key}",
                    servers,
                    channel_item,
                    warnings,
                    source_path,
                )
            )

    operations = document.get("operations", {})
    if operations is not None and not isinstance(operations, Mapping):
        warnings.append(_diagnostic("malformed-operations", "Top-level operations must be a mapping.", source_path))
        operations = {}
    for operation_key, operation in sorted(operations.items(), key=lambda item: str(item[0])):
        if not isinstance(operation_key, str) or not isinstance(operation, Mapping):
            warnings.append(_diagnostic("malformed-operation", f"Operation {operation_key!r} is not a mapping.", source_path))
            continue
        channel_key, channel_item = _channel_reference(operation.get("channel"), channels)
        if channel_key is None or channel_item is None:
            warnings.append(_diagnostic("reference-not-resolved", f"Channel reference for operation {operation_key!r} was not resolved.", source_path))
            continue
        address = channel_item.get("address")
        channel = address.strip() if isinstance(address, str) and address.strip() else channel_key
        candidates.append(
            _candidate(
                context,
                identity,
                basis,
                channel,
                _direction(operation.get("action")),
                operation,
                f"#/operations/{_pointer_part(operation_key)}",
                servers,
                channel_item,
                warnings,
                source_path,
                fallback_operation_id=operation_key,
            )
        )
    warnings.extend(_collision_diagnostics(candidates, source_path))
    return _validated_result("asyncapi", context, candidates, warnings, ())

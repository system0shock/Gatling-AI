"""Bounded, in-memory deployment/configuration and build metadata extraction."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath
import re
from typing import Any
import xml.etree.ElementTree as ElementTree

import yaml

if __package__:
    from .models import Candidate, ExtractorResult
    from .openapi import (
        _context_values,
        _diagnostic,
        _pointer_part,
        _resolve_service_identity,
        _slug,
        _source,
        _validated_result,
    )
else:
    from models import Candidate, ExtractorResult
    from openapi import (
        _context_values,
        _diagnostic,
        _pointer_part,
        _resolve_service_identity,
        _slug,
        _source,
        _validated_result,
    )


_WORKLOAD_KINDS = frozenset({"Deployment", "StatefulSet", "DeploymentConfig"})
_DYNAMIC = re.compile(r"(?:\$\{|#\{)")
_PROPERTY_DESTINATION = re.compile(
    r"^\s*spring\.cloud\.stream\.bindings\.([A-Za-z0-9_.-]+)\.destination\s*=\s*(.*?)\s*$"
)
_GRADLE_ROOT = re.compile(
    r"(?m)^[ \t]*rootProject\.name[ \t]*=[ \t]*(['\"])([^'\"\r\n]+)\1[ \t]*$"
)
_GRADLE_PLUGIN = re.compile(r"\bid\s*(?:\(\s*)?(['\"])([^'\"\r\n]+)\1\s*\)?")
_PORT_TOKEN = re.compile(r"^([0-9]+)(?:-([0-9]+))?$")
_KUBERNETES_PORT_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,13}[a-z0-9])?$")


def _stable_name(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() and "\x00" not in value else None


def _candidate(
    context: Mapping[str, Any],
    *,
    entity_type: str,
    key_kind: str,
    name: str,
    identity: str,
    basis: str,
    attributes: Mapping[str, Any],
    pointer: str,
) -> Candidate:
    stable = _slug(name) or "unknown"
    return Candidate(
        entity_type=entity_type,
        canonical_key=f"{key_kind}:{identity}:{stable}",
        display_name=name,
        service_identity_value=identity,
        service_identity_basis=basis,
        attributes=dict(attributes),
        source=_source(context, pointer),
        confidence="confirmed",
    )


def _documents(value: Any) -> tuple[list[Any], str | None]:
    if isinstance(value, Mapping):
        return [value], None
    if isinstance(value, (list, tuple)):
        return list(value), None
    if not isinstance(value, str):
        return [], "Deployment input must be a mapping, sequence, or YAML text."
    try:
        return list(yaml.safe_load_all(value)), None
    except (yaml.YAMLError, ValueError, RecursionError):
        return [], "Deployment YAML could not be parsed safely."


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _mapping_labels(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(key): str(item)
        for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        if isinstance(key, str) and key and isinstance(item, (str, int, float, bool))
    }


def _literal(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        return None
    stripped = value.strip()
    return None if _DYNAMIC.search(stripped) else stripped


def _spring_bindings(
    document: Mapping[str, Any],
    context: Mapping[str, Any],
    document_index: int,
    identity: str,
    basis: str,
    warnings: list[dict[str, str]],
) -> list[Candidate]:
    source_path = context["source"]["path"]
    spring = _mapping(document.get("spring"))
    cloud = _mapping(spring.get("cloud"))
    stream = _mapping(cloud.get("stream"))
    bindings = stream.get("bindings")
    if not isinstance(bindings, Mapping):
        return []
    candidates: list[Candidate] = []
    for raw_binding, raw_config in sorted(bindings.items(), key=lambda pair: str(pair[0])):
        binding = _stable_name(raw_binding)
        if binding is None or not isinstance(raw_config, Mapping) or "destination" not in raw_config:
            continue
        destination = _literal(raw_config.get("destination"))
        if destination is None:
            warnings.append(_diagnostic("dynamic-destination", f"Binding {raw_binding!r} has no literal destination.", source_path))
            continue
        pointer = f"#/documents/{document_index}/spring/cloud/stream/bindings/{_pointer_part(binding)}/destination"
        candidates.append(
            _candidate(
                context,
                entity_type="integration",
                key_kind="message",
                name=destination,
                identity=identity,
                basis=basis,
                attributes={"binding": binding, "destination": destination, "protocol": "Spring Cloud Stream"},
                pointer=pointer,
            )
        )
    return candidates


def _bounded_port_token(value: Any, *, ranges: bool) -> int | str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 1 <= value <= 65535 else None
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if len(stripped) > len("65535-65535"):
        return None
    match = _PORT_TOKEN.fullmatch(stripped)
    if match is None:
        return None
    if len(match.group(1)) > 5 or (
        match.group(2) is not None and len(match.group(2)) > 5
    ):
        return None
    start = int(match.group(1))
    end_text = match.group(2)
    if end_text is None:
        return start if 1 <= start <= 65535 else None
    end = int(end_text)
    if not ranges or not 1 <= start <= end <= 65535:
        return None
    return f"{start}-{end}"


def _range_size(value: int | str) -> int:
    if isinstance(value, int):
        return 1
    start, end = value.split("-", 1)
    return int(end) - int(start) + 1


def _kubernetes_target_port(value: Any) -> int | str | None:
    numeric = _bounded_port_token(value, ranges=False)
    if numeric is not None:
        return numeric
    name = _stable_name(value)
    if (
        name is None
        or name.isdigit()
        or len(name) > 15
        or _KUBERNETES_PORT_NAME.fullmatch(name) is None
        or not any(character.isalpha() for character in name)
    ):
        return None
    return name


def _declared_ports(
    value: Any, port_field: str
) -> list[tuple[int, int, int | str | None, str | None, str]]:
    if not isinstance(value, list):
        return []
    ports: list[tuple[int, int, int | str | None, str | None, str]] = []
    for original_index, item in enumerate(value):
        if not isinstance(item, Mapping):
            continue
        port = _bounded_port_token(item.get(port_field), ranges=False)
        if not isinstance(port, int):
            continue
        target: int | str | None = None
        if "targetPort" in item:
            target = _kubernetes_target_port(item["targetPort"])
            if target is None:
                continue
        if "name" in item:
            name = _stable_name(item["name"])
            if name is None:
                continue
        else:
            name = None
        if "protocol" in item:
            raw_protocol = item["protocol"]
            if not isinstance(raw_protocol, str):
                continue
            protocol = raw_protocol.strip().upper()
            if protocol not in {"TCP", "UDP", "SCTP"}:
                continue
        else:
            protocol = "TCP"
        ports.append((original_index, port, target, name, protocol))
    return ports


def _compose_protocol(value: Any) -> str | None:
    if value is None:
        return "TCP"
    if not isinstance(value, str):
        return None
    protocol = value.strip().upper()
    return protocol if protocol in {"TCP", "UDP"} else None


def _compose_port(value: Any) -> tuple[int | str, int | str | None, str | None, str] | None:
    if isinstance(value, Mapping):
        if "target" not in value:
            return None
        target = _bounded_port_token(value["target"], ranges=False)
        if target is None:
            return None
        if "published" in value:
            published = _bounded_port_token(value["published"], ranges=True)
            if published is None:
                return None
            port = published
            target_value: int | str | None = target
        else:
            port = target
            target = None
            target_value = None
        if "name" in value:
            name = _stable_name(value["name"])
            if name is None:
                return None
        else:
            name = None
        protocol = (
            _compose_protocol(value["protocol"])
            if "protocol" in value
            else "TCP"
        )
        if protocol is None:
            return None
        if "host_ip" in value and _stable_name(value["host_ip"]) is None:
            return None
        if "app_protocol" in value and _stable_name(value["app_protocol"]) is None:
            return None
        if "mode" in value and (
            not isinstance(value["mode"], str)
            or value["mode"].strip().casefold() not in {"host", "ingress"}
        ):
            return None
        return port, target_value, name, protocol

    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        port = _bounded_port_token(value, ranges=False)
        return (port, None, None, "TCP") if isinstance(port, int) else None
    if not isinstance(value, str) or not value.strip() or value.count("/") > 1:
        return None
    address, separator, raw_protocol = value.strip().partition("/")
    protocol = _compose_protocol(raw_protocol if separator else None)
    if protocol is None:
        return None
    pieces = address.rsplit(":", 2)
    if len(pieces) == 1:
        port = _bounded_port_token(pieces[0], ranges=True)
        return (port, None, None, protocol) if port is not None else None
    if len(pieces) == 2:
        published_text, target_text = pieces
    else:
        host, published_text, target_text = pieces
        if not host.strip():
            return None
    published = _bounded_port_token(published_text, ranges=True)
    target = _bounded_port_token(target_text, ranges=True)
    if (
        published is None
        or target is None
        or _range_size(published) != _range_size(target)
    ):
        return None
    return published, target, None, protocol


def _port_candidate(
    context: Mapping[str, Any],
    identity: str,
    basis: str,
    owner: str,
    port: int | str,
    target: int | str | None,
    name: str | None,
    pointer: str,
    protocol: str,
) -> Candidate:
    attributes: dict[str, Any] = {"owner": owner, "port": port, "protocol": protocol}
    if target is not None:
        attributes["target_port"] = target
    if name is not None:
        attributes["name"] = name
    return _candidate(
        context,
        entity_type="interface",
        key_kind="network",
        name=f"{owner}:{port}",
        identity=identity,
        basis=basis,
        attributes=attributes,
        pointer=pointer,
    )


def extract_deployment(document: Any, context: Mapping[str, Any]) -> ExtractorResult:
    """Extract only facts explicitly declared in caller-supplied bounded data."""
    _repo_id, _snapshot, source, _service = _context_values(context)
    identity, basis, warnings = _resolve_service_identity(context, {})
    candidates: list[Candidate] = []
    errors: list[dict[str, str]] = []
    documents, parse_error = _documents(document)
    if parse_error is not None:
        errors.append(_diagnostic("invalid-deployment-document", parse_error, source["path"]))
        return _validated_result("deployment", context, (), warnings, errors)

    workloads: list[tuple[str, dict[str, str], int]] = []
    selectors: list[tuple[str, dict[str, str], int]] = []
    for document_index, item in enumerate(documents):
        if item is None:
            continue
        if not isinstance(item, Mapping):
            warnings.append(_diagnostic("malformed-deployment-document", f"YAML document {document_index} is not a mapping.", source["path"]))
            continue
        candidates.extend(_spring_bindings(item, context, document_index, identity, basis, warnings))

        services = item.get("services")
        if isinstance(services, Mapping):
            for raw_name, raw_service in sorted(services.items(), key=lambda pair: str(pair[0])):
                name = _stable_name(raw_name)
                if name is None or not isinstance(raw_service, Mapping):
                    warnings.append(_diagnostic("stable-name-required", "Compose service requires a stable mapping name and mapping body.", source["path"]))
                    continue
                base = f"#/documents/{document_index}/services/{_pointer_part(name)}"
                candidates.append(_candidate(context, entity_type="component", key_kind="component", name=name, identity=identity, basis=basis, attributes={"kind": "compose-service", "name": name}, pointer=base))
                ports = raw_service.get("ports")
                if isinstance(ports, list):
                    for port_index, raw_port in enumerate(ports):
                        parsed = _compose_port(raw_port)
                        if parsed is None:
                            continue
                        port, target, port_name, protocol = parsed
                        candidates.append(_port_candidate(context, identity, basis, name, port, target, port_name, f"{base}/ports/{port_index}", protocol))
                depends_on = raw_service.get("depends_on")
                dependencies = depends_on.keys() if isinstance(depends_on, Mapping) else depends_on if isinstance(depends_on, list) else ()
                for dependency in sorted({_stable_name(value) for value in dependencies} - {None}):
                    candidates.append(_candidate(context, entity_type="integration", key_kind="dependency", name=f"{name}->{dependency}", identity=identity, basis=basis, attributes={"kind": "depends_on", "source": name, "target": dependency}, pointer=f"{base}/depends_on/{_pointer_part(dependency)}"))
            continue

        kind = _stable_name(item.get("kind"))
        if kind is None:
            continue
        metadata = _mapping(item.get("metadata"))
        name = _stable_name(metadata.get("name"))
        if name is None:
            warnings.append(_diagnostic("stable-name-required", f"{kind} requires metadata.name.", source["path"]))
            continue
        base = f"#/documents/{document_index}"
        spec = _mapping(item.get("spec"))
        if kind in _WORKLOAD_KINDS:
            candidates.append(_candidate(context, entity_type="component", key_kind="component", name=name, identity=identity, basis=basis, attributes={"kind": kind, "name": name}, pointer=f"{base}/metadata/name"))
            template = _mapping(spec.get("template"))
            labels = _mapping_labels(_mapping(template.get("metadata")).get("labels"))
            workloads.append((name, labels, document_index))
            pod_spec = _mapping(template.get("spec"))
            containers = pod_spec.get("containers")
            if isinstance(containers, list):
                for container_index, container in enumerate(containers):
                    if not isinstance(container, Mapping):
                        continue
                    for port_index, port, target, port_name, protocol in _declared_ports(container.get("ports"), "containerPort"):
                        candidates.append(_port_candidate(context, identity, basis, name, port, target, port_name, f"{base}/spec/template/spec/containers/{container_index}/ports/{port_index}", protocol))
        elif kind == "Service":
            selector = _mapping_labels(spec.get("selector"))
            if selector:
                selectors.append((name, selector, document_index))
            for port_index, port, target, port_name, protocol in _declared_ports(spec.get("ports"), "port"):
                candidates.append(_port_candidate(context, identity, basis, name, port, target, port_name, f"{base}/spec/ports/{port_index}", protocol))
        elif kind == "Ingress":
            rules = spec.get("rules")
            if isinstance(rules, list):
                for rule_index, rule in enumerate(rules):
                    if not isinstance(rule, Mapping):
                        continue
                    host = _stable_name(rule.get("host"))
                    http = _mapping(rule.get("http"))
                    paths = http.get("paths") if isinstance(http.get("paths"), list) else [{}]
                    for path_index, path_item in enumerate(paths):
                        path = _stable_name(path_item.get("path")) if isinstance(path_item, Mapping) else None
                        if host is None and path is None:
                            continue
                        attributes = {"kind": "Ingress", "owner": name, "protocol": "HTTP"}
                        if host is not None:
                            attributes["host"] = host
                        if path is not None:
                            attributes["path"] = path
                        candidates.append(_candidate(context, entity_type="interface", key_kind="route", name=f"{host or '*'}{path or '/'}", identity=identity, basis=basis, attributes=attributes, pointer=f"{base}/spec/rules/{rule_index}/http/paths/{path_index}"))
        elif kind == "Route":
            host = _stable_name(spec.get("host"))
            path = _stable_name(spec.get("path"))
            attributes = {"kind": "Route", "owner": name, "protocol": "HTTP"}
            if host is not None:
                attributes["host"] = host
            if path is not None:
                attributes["path"] = path
            route_name = f"{host or '*'}{path or '/'}" if host is not None or path is not None else name
            candidates.append(_candidate(context, entity_type="interface", key_kind="route", name=route_name, identity=identity, basis=basis, attributes=attributes, pointer=f"{base}/spec"))

    for service, selector, document_index in selectors:
        for workload, labels, workload_document_index in workloads:
            if labels and all(labels.get(key) == value for key, value in selector.items()):
                candidates.append(_candidate(context, entity_type="integration", key_kind="selector", name=f"{service}->{workload}", identity=identity, basis=basis, attributes={"kind": "selector", "selector": [f"{key}={selector[key]}" for key in sorted(selector)], "source": service, "target": workload}, pointer=f"#/documents/{document_index}/spec/selector"))

    return _validated_result("deployment", context, candidates, warnings, errors)


def _xml_local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _direct_child(element: ElementTree.Element, name: str) -> ElementTree.Element | None:
    return next((child for child in list(element) if _xml_local(child.tag) == name), None)


def _child_text(element: ElementTree.Element | None, name: str) -> str | None:
    child = _direct_child(element, name) if element is not None else None
    return _stable_name(child.text) if child is not None else None


def _component_result(
    context: Mapping[str, Any],
    name: str | None,
    attributes: Mapping[str, Any],
    pointer: str,
    warnings: Sequence[Mapping[str, Any]] = (),
    errors: Sequence[Mapping[str, Any]] = (),
) -> ExtractorResult:
    identity, basis, identity_warnings = _resolve_service_identity(context, {})
    all_warnings = [*identity_warnings, *warnings]
    candidates: list[Candidate] = []
    if name is not None:
        candidates.append(_candidate(context, entity_type="component", key_kind="component", name=name, identity=identity, basis=basis, attributes=attributes, pointer=pointer))
    return _validated_result("build-metadata", context, candidates, all_warnings, errors)


def _mask_gradle_comments(text: str) -> str:
    """Mask comments without changing offsets or quoted Gradle declarations."""
    masked = list(text)
    state = "code"
    quote = ""
    escaped = False
    index = 0
    while index < len(text):
        character = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        if state == "line-comment":
            if character in "\r\n":
                state = "code"
            else:
                masked[index] = " "
            index += 1
            continue
        if state == "block-comment":
            if character == "*" and following == "/":
                masked[index] = masked[index + 1] = " "
                state = "code"
                index += 2
                continue
            if character not in "\r\n":
                masked[index] = " "
            index += 1
            continue
        if state == "quoted":
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                state = "code"
            index += 1
            continue
        if character in {"'", '"'}:
            state = "quoted"
            quote = character
            index += 1
            continue
        if character == "/" and following == "/":
            masked[index] = masked[index + 1] = " "
            state = "line-comment"
            index += 2
            continue
        if character == "/" and following == "*":
            masked[index] = masked[index + 1] = " "
            state = "block-comment"
            index += 2
            continue
        index += 1
    return "".join(masked)


def extract_build_metadata(text: Any, path: str, context: Mapping[str, Any]) -> ExtractorResult:
    """Extract declared project metadata from supplied text without invoking build tools."""
    _repo, _snapshot, source, _service = _context_values(context)
    if not isinstance(text, str) or not isinstance(path, str):
        return _component_result(context, None, {}, "#", errors=(_diagnostic("invalid-build-metadata", "Build/config input and path must be text.", source["path"]),))
    if path != source["path"]:
        raise ValueError("build metadata path must equal the context source path")
    basename = PurePosixPath(path.replace("\\", "/")).name.casefold()

    spring_named = (
        basename.startswith("application.")
        or basename.startswith("application-")
        or basename.startswith("bootstrap.")
        or basename.startswith("bootstrap-")
    )
    suffix = PurePosixPath(basename).suffix
    if spring_named and suffix in {".yaml", ".yml"}:
        extracted = extract_deployment(text, context)
        return _validated_result(
            "build-metadata",
            context,
            extracted.candidates,
            extracted.warnings,
            extracted.errors,
        )
    if spring_named and suffix == ".properties":
        identity, basis, warnings = _resolve_service_identity(context, {})
        candidates: list[Candidate] = []
        for line_number, line in enumerate(text.splitlines(), 1):
            match = _PROPERTY_DESTINATION.fullmatch(line)
            if match is None:
                continue
            binding, raw_destination = match.groups()
            destination = _literal(raw_destination)
            if destination is None:
                warnings.append(_diagnostic("dynamic-destination", f"Binding {binding!r} has no literal destination.", source["path"]))
                continue
            candidates.append(_candidate(context, entity_type="integration", key_kind="message", name=destination, identity=identity, basis=basis, attributes={"binding": binding, "destination": destination, "protocol": "Spring Cloud Stream"}, pointer=f"#L{line_number}"))
        return _validated_result("build-metadata", context, candidates, warnings, ())

    if basename == "chart.yaml":
        try:
            document = yaml.safe_load(text)
        except (yaml.YAMLError, ValueError, RecursionError):
            document = None
        if not isinstance(document, Mapping):
            return _component_result(context, None, {}, "#/name", errors=(_diagnostic("invalid-build-metadata", "Chart.yaml must be a safe YAML mapping.", source["path"]),))
        name = _stable_name(document.get("name"))
        if name is None:
            return _component_result(context, None, {}, "#/name", warnings=(_diagnostic("stable-name-required", "Chart.yaml requires name.", source["path"]),))
        attributes: dict[str, Any] = {"kind": "helm-chart", "name": name}
        app_version = document.get("appVersion")
        if isinstance(app_version, (str, int, float)) and not isinstance(app_version, bool):
            attributes["app_version"] = str(app_version)
        return _component_result(context, name, attributes, "#/documents/0/name")

    if basename == "pom.xml":
        if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
            root = None
        else:
            try:
                root = ElementTree.fromstring(text)
            except (ElementTree.ParseError, RecursionError):
                root = None
        if root is None or _xml_local(root.tag) != "project":
            return _component_result(context, None, {}, "#/project/artifactId", errors=(_diagnostic("invalid-build-metadata", "pom.xml must contain one safe project element.", source["path"]),))
        artifact_id = _child_text(root, "artifactId")
        if artifact_id is None:
            return _component_result(context, None, {}, "#/project/artifactId", warnings=(_diagnostic("stable-name-required", "pom.xml requires a project artifactId.", source["path"]),))
        markers: set[str] = set()
        build = _direct_child(root, "build")
        plugins = _direct_child(build, "plugins") if build is not None else None
        if plugins is not None:
            for plugin in list(plugins):
                if _xml_local(plugin.tag) != "plugin":
                    continue
                marker = _child_text(plugin, "artifactId")
                if marker is not None:
                    markers.add(marker)
        attributes = {"artifact_id": artifact_id, "kind": "maven-project"}
        if markers:
            attributes["markers"] = sorted(markers)
        return _component_result(context, artifact_id, attributes, "#/project/artifactId")

    if basename in {"build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts"}:
        visible_text = _mask_gradle_comments(text)
        root_match = _GRADLE_ROOT.search(visible_text)
        name = _stable_name(root_match.group(2)) if root_match else None
        if name is None:
            return _component_result(context, None, {}, "#L1", warnings=(_diagnostic("stable-name-required", "Gradle metadata requires rootProject.name.", source["path"]),))
        markers = sorted({match.group(2).strip() for match in _GRADLE_PLUGIN.finditer(visible_text) if match.group(2).strip()})
        attributes = {"kind": "gradle-project", "root_project_name": name}
        if markers:
            attributes["markers"] = markers
        line = text[: root_match.start()].count("\n") + 1
        return _component_result(context, name, attributes, f"#L{line}")

    return _component_result(context, None, {}, "#", errors=(_diagnostic("unsupported-build-metadata", f"Unsupported build/config path {path!r}.", source["path"]),))

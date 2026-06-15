"""Builders for minimal valid JMX-IR dicts used by the ir_to_scenario tests."""
from __future__ import annotations
from typing import Any

_COUNTER = {"n": 0}


def eid() -> str:
    _COUNTER["n"] += 1
    return f"e-{_COUNTER['n']:04d}"


def element(kind: str, name: str = "", **detail: Any) -> dict[str, Any]:
    node = {
        "id": eid(), "kind": kind, "type": kind, "name": name,
        "enabled": detail.pop("enabled", True), "path": [], "children": detail.pop("children", []),
    }
    node.update(detail)
    return node


def http_sampler(name: str, method: str = "GET", path: str = "/", **extra: Any) -> dict[str, Any]:
    detail = {
        "method": method,
        "url": {"protocol": "", "domain": "", "port": "", "path": path},
        "follow_redirects": True,
    }
    detail.update(extra)
    return element("http_sampler", name, **detail)


def thread_group(name: str, children: list[dict], normalized: dict | None, note: str | None = None) -> dict[str, Any]:
    return element(
        "thread_group", name,
        flavor="standard", raw={}, load={"normalized": normalized, "note": note},
        children=children,
    )


def ir(children: list[dict], **over: Any) -> dict[str, Any]:
    by_kind: dict[str, int] = {}

    def walk(node: dict) -> None:
        by_kind[node["kind"]] = by_kind.get(node["kind"], 0) + 1
        for child in node.get("children", []):
            walk(child)

    for child in children:
        walk(child)
    total = sum(by_kind.values())
    doc = {
        "version": 1,
        "source": {"file": "test.jmx", "sha256": "0" * 64, "size_bytes": 0},
        "test_plan": {"name": "Test", "comments": ""},
        "children": children,
        "unsupported": [],
        "variables": {"index": {}, "functions": [], "props": {}, "findings": {"consumed_not_produced": [], "produced_not_consumed": []}},
        "complexity_flags": [],
        "stats": {
            "elements_total": total, "elements_disabled": 0, "by_kind": by_kind,
            "bodies_externalized": 0, "jsr223": {"typical": 0, "complex": 0},
        },
    }
    doc.update(over)
    return doc

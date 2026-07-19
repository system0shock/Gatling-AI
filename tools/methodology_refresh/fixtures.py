"""Small deterministic fixtures for methodology refresh tests."""

MODULES = {"openapi": ("api-contracts", "api-spec"), "backend": ("orders-backend", "backend"), "frontend": ("web-frontend", "frontend")}

def snapshot(**commits: str) -> dict:
    return {"snapshot_id": "fixture", "modules": {MODULES[key][0]: {"commit": value, "dirty": False, "kind": MODULES[key][1]} for key, value in commits.items()}}

def source_map() -> dict:
    return {"version": 1, "sources": {}, "sections": {}}

def manifest() -> dict:
    return {"modules": [{"id": module_id, "kind": kind} for module_id, kind in MODULES.values()]}

def pages(versions: dict[str, int]) -> dict:
    return {"pages": {page_id: {"version": version} for page_id, version in versions.items()}}

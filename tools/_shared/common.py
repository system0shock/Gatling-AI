#!/usr/bin/env python3
"""Shared helpers for Gatling-AI Phase 0 tools."""

from __future__ import annotations

import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only on hosts without PyYAML.
    yaml = None


VARIABLE_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_.-]*)\}")

BLOCKING = "blocking"
WARNING = "warning"
WAIVED = "waived"


@dataclass(frozen=True)
class Finding:
    rule: str
    message: str
    severity: str | None = None
    path: str | None = None
    artifact: str | None = None
    check: str | None = None
    command: str | None = None
    output: str | None = None


def finding_to_dict(finding: Finding) -> dict[str, Any]:
    return {key: value for key, value in asdict(finding).items() if value is not None}


def load_yaml(path: Path) -> Any:
    if yaml is None:
        raise RuntimeError("PyYAML is unavailable; install PyYAML to run Gatling-AI tools.")
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def find_repo_root(*starts: Path) -> Path | None:
    candidates = [*starts, Path(__file__)]
    for start in candidates:
        try:
            current = start.resolve()
        except OSError:
            current = start.absolute()
        if current.is_file():
            current = current.parent
        for directory in (current, *current.parents):
            if (directory / ".git").exists():
                return directory
    return None


def rel_path(path: Path, repo_root: Path | None) -> str:
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path.absolute()
    if repo_root is not None:
        try:
            return resolved.relative_to(repo_root.resolve()).as_posix()
        except (OSError, ValueError):
            pass
    return resolved.as_posix()


def run_command(
    args: list[str], cwd: Path, timeout: int | None = 120
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        shell=False,
    )


def pascal_case(identifier: str) -> str:
    parts = [part for part in identifier.split("-") if part]
    return "".join(part[:1].upper() + part[1:] for part in parts)


def variables_in(value: Any) -> set[str]:
    if isinstance(value, str):
        return set(VARIABLE_RE.findall(value))
    found: set[str] = set()
    if isinstance(value, dict):
        for child in value.values():
            found.update(variables_in(child))
    elif isinstance(value, list):
        for child in value:
            found.update(variables_in(child))
    return found

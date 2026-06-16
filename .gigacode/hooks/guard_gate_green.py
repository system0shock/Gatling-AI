#!/usr/bin/env python3
"""Stop hook: refuse handoff until the quality gate is green (opt-in, blocking).

Closes the process gap that advisory ``gate_reminder`` cannot: a model declaring
"done" without a passing gate. When enforcement is ON (env ``GIGACODE_ENFORCE``
truthy), this hook blocks the Stop (exit 2, reason on stderr) while scenarios
exist and the gate report is missing / stale / not ``passed`` /
``passed_with_warnings``.

Loop-safe: it blocks at most ``GIGACODE_ENFORCE_MAX`` times per session
(default 3, tracked in a temp state file keyed by ``session_id``); after that it
falls back to a loud advisory ``systemMessage`` and lets the turn end, so a
headless run can never hang forever.

Advisory by default: with enforcement OFF it never blocks (exit 0).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT = REPO_ROOT / "quality-gate-report.json"
SCENARIO_ROOTS = (REPO_ROOT / "scenarios", REPO_ROOT / "examples" / "scenarios")
PASSING = {"passed", "passed_with_warnings"}
TRUTHY = {"1", "true", "yes", "on"}
DEFAULT_LIMIT = 3


def passing(status) -> bool:
    """True if a gate status counts as green."""
    return status in PASSING


def should_block(scenario_mtimes: list, report_mtime, status) -> bool:
    """Block when scenarios exist and the gate is missing/stale/not-green."""
    if not scenario_mtimes:
        return False
    if report_mtime is None:
        return True
    if max(scenario_mtimes) > report_mtime:
        return True
    return not passing(status)


def decide(block_condition: bool, count: int, limit: int) -> str:
    """Map (condition, prior block count, limit) to allow / block / advisory."""
    if not block_condition:
        return "allow"
    if count < limit:
        return "block"
    return "advisory"


def enforcing(env=None) -> bool:
    env = os.environ if env is None else env
    return env.get("GIGACODE_ENFORCE", "").strip().lower() in TRUTHY


def block_limit(env=None) -> int:
    env = os.environ if env is None else env
    try:
        return int(env.get("GIGACODE_ENFORCE_MAX", ""))
    except (TypeError, ValueError):
        return DEFAULT_LIMIT


# --- filesystem / state glue (thin; pure logic above is what's unit-tested) ---

def scenario_mtimes() -> list:
    mtimes: list = []
    for root in SCENARIO_ROOTS:
        if root.exists():
            for path in root.glob("**/scenario.yaml"):
                mtimes.append(path.stat().st_mtime)
    return mtimes


def report_mtime():
    return REPORT.stat().st_mtime if REPORT.exists() else None


def report_status():
    try:
        data = json.loads(REPORT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data.get("status") if isinstance(data, dict) else None


def _count_path(session_id: str) -> Path:
    safe = "".join(c for c in (session_id or "default") if c.isalnum() or c in "-_")
    return Path(tempfile.gettempdir()) / f"gigacode_gate_block_{safe or 'default'}.txt"


def read_count(session_id: str) -> int:
    try:
        return int(_count_path(session_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0


def write_count(session_id: str, value: int) -> None:
    try:
        _count_path(session_id).write_text(str(value), encoding="utf-8")
    except OSError:
        pass


def main() -> int:
    raw = sys.stdin.read()
    if not enforcing():
        return 0
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        payload = {}
    session_id = payload.get("session_id", "") if isinstance(payload, dict) else ""

    block = should_block(scenario_mtimes(), report_mtime(), report_status())
    count = read_count(session_id)
    decision = decide(block, count, block_limit())

    if decision == "block":
        write_count(session_id, count + 1)
        sys.stderr.write(
            "BLOCKED-STOP by gigacode guard: the quality gate is not green. Run "
            "the quality-gate skill/command and reach status passed or "
            f"passed_with_warnings before finishing (report: {REPORT}).\n"
        )
        return 2
    if decision == "advisory":
        print(json.dumps({
            "systemMessage": (
                "Quality gate still not green after the enforced block limit. "
                "Proceeding, but DO NOT treat the work as done — run the gate and "
                f"fix the blocking findings (report: {REPORT})."
            )
        }))
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())

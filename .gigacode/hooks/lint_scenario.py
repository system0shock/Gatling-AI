#!/usr/bin/env python3
"""PostToolUse hook: auto-lint an edited scenario.yaml.

Gigacode/Qwen passes the event payload as JSON on stdin after a tool runs. We
scan the payload for any file path whose basename is ``scenario.yaml`` and run
the repository linter on each one that exists, returning findings to the model
via ``hookSpecificOutput.additionalContext`` so it can fix them.

Advisory: always exits 0, never blocks the edit. Schema-agnostic by design —
instead of depending on exact Qwen field names (which may differ in Gigacode),
we walk the whole payload collecting strings.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LINTER = REPO_ROOT / "tools" / "scenario_lint" / "scenario_lint.py"
SCENARIO_NAME = "scenario.yaml"


def iter_strings(value):
    """Yield every string contained in a nested JSON value."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from iter_strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from iter_strings(v)


def scenario_paths_from_payload(payload, repo_root: Path) -> list[Path]:
    """Return existing scenario.yaml paths referenced anywhere in the payload."""
    cwd = repo_root
    if isinstance(payload, dict) and payload.get("cwd"):
        cwd = Path(payload["cwd"])
    found: list[Path] = []
    seen: set[Path] = set()
    for s in iter_strings(payload):
        if Path(s).name != SCENARIO_NAME:
            continue
        candidate = Path(s)
        if not candidate.is_absolute():
            candidate = cwd / candidate
        candidate = candidate.resolve()
        if candidate.exists() and candidate not in seen:
            seen.add(candidate)
            found.append(candidate)
    return found


def run_lint(path: Path) -> tuple[int, str]:
    """Run the scenario linter; return (exit_code, combined_output)."""
    proc = subprocess.run(
        [sys.executable, str(LINTER), str(path), "--format", "text"],
        capture_output=True,
        text=True,
    )
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return 0

    paths = scenario_paths_from_payload(payload, REPO_ROOT)
    if not paths or not LINTER.exists():
        return 0

    blocking = []
    for path in paths:
        code, output = run_lint(path)
        if code != 0:
            blocking.append(output)

    if blocking:
        context = "scenario-lint found blocking issues after your edit:\n\n" + "\n\n".join(blocking)
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": context,
            }
        }))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""PreToolUse hook: block hand-written/edited generated Java (opt-in, blocking).

``scenario.yaml`` is the single source of truth; Java is produced by the
generator, never hand-written. When enforcement is ON (env ``GIGACODE_ENFORCE``
truthy) this hook blocks any write/edit whose target is a generated Java file
(``**/src/test/java/**/*.java``) by exiting 2 with a reason on stderr. The
generator runs as a separate process, so its writes never pass through this
hook — only the model's direct ``write_file``/``edit`` calls do.

Advisory by default: with enforcement OFF it never blocks (exit 0), so the
package is safe on hosts whose exit-2 behavior is unconfirmed. Schema-agnostic:
walks the whole payload for strings, like ``lint_scenario``.
"""
from __future__ import annotations

import json
import os
import re
import sys

GENERATED_JAVA_RE = re.compile(r"src/test/java/.*\.java$", re.IGNORECASE)
TRUTHY = {"1", "true", "yes", "on"}


def is_generated_java(path: str) -> bool:
    """True if ``path`` points at a generated Gatling Java file."""
    return bool(GENERATED_JAVA_RE.search(path.replace("\\", "/")))


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


def java_targets_from_payload(payload) -> list:
    """Return every generated-Java path referenced anywhere in the payload."""
    return [s for s in iter_strings(payload) if is_generated_java(s)]


def enforcing(env=None) -> bool:
    """True when blocking enforcement is opted in via GIGACODE_ENFORCE."""
    env = os.environ if env is None else env
    return env.get("GIGACODE_ENFORCE", "").strip().lower() in TRUTHY


def main() -> int:
    raw = sys.stdin.read()
    if not enforcing():
        return 0
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return 0
    targets = java_targets_from_payload(payload)
    if targets:
        sys.stderr.write(
            "BLOCKED by gigacode guard: refusing to hand-write generated Java "
            f"({targets[0]}). scenario.yaml is the single source of truth: edit "
            "the scenario and regenerate with tools/gatling_generator, never "
            "hand-edit Java.\n"
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

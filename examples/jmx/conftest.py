"""Ensure tools/jmx_parser is on sys.path before other tool directories
so that jmx_build.py can ``import fixtures`` from the correct location
when pytest is invoked from the repository root.

The complication: tools/ir_to_scenario/test_ir_to_scenario.py imports
``fixtures`` at module level, which caches tools/ir_to_scenario/fixtures.py
in sys.modules under the bare name 'fixtures'.  We evict that entry so
that jmx_build.py's own sys.path.insert (which puts jmx_parser first) is
honoured when it does ``from fixtures import bool_prop``.
"""
from __future__ import annotations
import sys
from pathlib import Path

_JMX_PARSER = Path(__file__).resolve().parents[2] / "tools" / "jmx_parser"

# Evict any previously cached 'fixtures' that belongs to ir_to_scenario.
_cached = sys.modules.get("fixtures")
if _cached is not None:
    _cached_path = getattr(_cached, "__file__", "") or ""
    if "ir_to_scenario" in _cached_path:
        del sys.modules["fixtures"]

# Make sure jmx_parser comes first so the next ``import fixtures`` resolves here.
sys.path.insert(0, str(_JMX_PARSER))

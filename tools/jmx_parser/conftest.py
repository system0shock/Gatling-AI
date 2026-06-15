"""Ensure tools/jmx_parser is on sys.path so that local imports work
even when pytest is invoked from the repository root alongside other
tool directories that have their own fixtures.py."""
from __future__ import annotations
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

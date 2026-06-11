#!/usr/bin/env python3
"""Env-gated streaming budget test for jmx_parser (~150MB synthetic plan).

Run from repo root:
    $env:GATLING_AI_PERF = "1"; python tools/jmx_parser/test_jmx_parser_perf.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import tracemalloc
import unittest
from pathlib import Path

import fixtures
import jmx_parser

SAMPLERS = 30
BODY_BYTES = 5 * 1024 * 1024
TIME_BUDGET_SECONDS = 240  # generous: includes tracemalloc overhead
MEMORY_BUDGET_BYTES = 400 * 1024 * 1024


@unittest.skipUnless(
    os.environ.get("GATLING_AI_PERF") == "1", "set GATLING_AI_PERF=1 to run"
)
class StreamingBudgetTest(unittest.TestCase):
    def test_large_plan_parses_within_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            jmx_path = tmp_path / "big.jmx"
            samplers = []
            for index in range(SAMPLERS):
                body = (
                    f'{{"sampler":{index},"data":"' + "x" * BODY_BYTES + '"}'
                )
                samplers.append(
                    fixtures.http_sampler(
                        f"req-{index}", method="POST", path=f"/x/{index}", body=body
                    )
                )
            document = fixtures.jmx(
                fixtures.thread_group("Main", children="\n".join(samplers))
            )
            jmx_path.write_text(document, encoding="utf-8")
            del document, samplers
            self.assertGreater(jmx_path.stat().st_size, 140 * 1024 * 1024)

            tracemalloc.start()
            started = time.monotonic()
            ir = jmx_parser.parse_jmx(jmx_path, tmp_path / "out")
            elapsed = time.monotonic() - started
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()

            self.assertEqual(ir["stats"]["bodies_externalized"], SAMPLERS)
            self.assertLess(elapsed, TIME_BUDGET_SECONDS)
            self.assertLess(peak, MEMORY_BUDGET_BYTES)


if __name__ == "__main__":
    sys.exit(unittest.main())

# examples/jmx/test_golden_pipeline.py
# Observed dispositions (golden #1 / #2) — see test_disposition_reconciles_100pct:
#   simple-backend : converted=18  (auto=100%, total=18)
#   staged-pipeline: converted=16, partial=1  (auto=94%, total=17)
#   Note: JSR223 pre/post-processors are recorded CONVERTED (captured as todo hooks);
#         JDBC sampler is recorded PARTIAL (stub until protocol spike).
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "jmx_parser"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "ir_to_scenario"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import jmx_parser            # noqa: E402
import ir_to_scenario        # noqa: E402
import jmx_build as jb       # noqa: E402

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover
    Draft202012Validator = None


def _scenario_validator():
    schema = json.loads((REPO_ROOT / "schemas" / "scenario.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


class GoldenPipelineBase(unittest.TestCase):
    DOCUMENT = ""
    SCENARIO_ID = ""
    NUMBER = 0

    # Prevent pytest from collecting the base class directly.
    __test__ = False

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        jmx_path = self.tmp / "plan.jmx"
        jmx_path.write_text(self.DOCUMENT, encoding="utf-8")
        self.ir = jmx_parser.parse_jmx(jmx_path, self.tmp / "migration")
        self.conv = ir_to_scenario.convert(
            self.ir, system="SHOP", scenario_id=self.SCENARIO_ID, number=self.NUMBER
        )

    def dispositions(self) -> dict:
        return self.conv.disposition_counts()

    def test_disposition_reconciles_100pct(self) -> None:
        total = self.ir["stats"]["elements_total"]
        self.assertEqual(sum(self.dispositions().values()), total)
        rules = {f.rule for f in self.conv.findings if f.severity == "blocking"}
        self.assertNotIn("convert.disposition-mismatch", rules)

    def test_scenario_is_schema_valid(self) -> None:
        if Draft202012Validator is None:
            self.skipTest("jsonschema unavailable")
        errors = list(_scenario_validator().iter_errors(self.conv.scenario))
        self.assertEqual(errors, [], errors[:1])

    def test_no_blocking_findings(self) -> None:
        blockers = [f for f in self.conv.findings if f.severity == "blocking"]
        self.assertEqual(blockers, [], blockers)


class SimpleGoldenTest(GoldenPipelineBase):
    __test__ = True
    SCENARIO_ID = "legacy-backend"
    NUMBER = 10

    @classmethod
    def setUpClass(cls) -> None:
        cls.DOCUMENT = jb.build_simple_backend()

    def test_m2_at_least_80pct_auto(self) -> None:
        counts = self.dispositions()
        total = sum(counts.values())
        auto = counts.get("converted", 0)
        self.assertGreaterEqual(auto / total, 0.80, counts)


class StagedGoldenTest(GoldenPipelineBase):
    __test__ = True
    SCENARIO_ID = "legacy-staged"
    NUMBER = 11

    @classmethod
    def setUpClass(cls) -> None:
        cls.DOCUMENT = jb.build_staged_pipeline()

    def test_has_partial_dispositions(self) -> None:
        """Staged golden contains at least one PARTIAL element (the JDBC stub)."""
        counts = self.dispositions()
        self.assertGreater(counts.get("partial", 0), 0, counts)


if __name__ == "__main__":
    unittest.main()

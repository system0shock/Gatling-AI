# examples/jmx/test_jmx_build.py
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "jmx_parser"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import jmx_parser  # noqa: E402
import jmx_build as jb  # noqa: E402


def parse(document: str, tmp: Path):
    jmx_path = tmp / "plan.jmx"
    jmx_path.write_text(document, encoding="utf-8")
    return jmx_parser.parse_jmx(jmx_path, tmp / "out")


class WrapperKindTest(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_wrappers_parse_to_expected_kinds(self) -> None:
        import fixtures
        doc = fixtures.jmx(
            jb.ultimate_tg("U", users=50, delay=0, rampup=120, hold=600, shutdown=60,
                           children=fixtures.http_sampler("ping")),
            jb.udv("Env", {"BASE_URL": "http://shop.local", "host": "shop.local"}),
            jb.csv_data_set("data", filename="search-terms.csv", variable_names="term"),
        )
        ir = parse(doc, self.tmp)
        kinds = [c["kind"] for c in ir["children"]]
        self.assertEqual(kinds, ["thread_group", "user_defined_variables", "csv_data_set"])
        self.assertEqual(ir["children"][0]["flavor"], "ultimate")
        self.assertEqual(ir["children"][0]["load"]["normalized"]["model"], "closed")


if __name__ == "__main__":
    unittest.main()

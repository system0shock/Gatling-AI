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

    def test_more_wrappers_parse_to_expected_kinds(self) -> None:
        import fixtures
        doc = fixtures.jmx(
            jb.concurrency_tg("C", target=20, rampup=2, steps=2, hold=10,
                              children=fixtures.http_sampler("ping")),
            jb.http_defaults("Defaults", domain="${host}", port="8080"),
        )
        ir = parse(doc, self.tmp)
        tg = ir["children"][0]
        self.assertEqual(tg["kind"], "thread_group")
        self.assertEqual(tg["flavor"], "concurrency")
        self.assertEqual(ir["children"][1]["kind"], "http_defaults")


class GoldenSimpleTest(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_simple_backend_shape(self) -> None:
        ir = parse(jb.build_simple_backend(), self.tmp)
        by_kind = ir["stats"]["by_kind"]
        self.assertEqual(by_kind["thread_group"], 1)
        self.assertEqual(by_kind["transaction"], 3)
        self.assertGreaterEqual(by_kind["http_sampler"], 3)
        self.assertEqual(by_kind["csv_data_set"], 1)
        self.assertEqual(by_kind["user_defined_variables"], 1)
        self.assertEqual(by_kind.get("jsr223_pre", 0), 1)
        self.assertEqual(ir["stats"]["jsr223"], {"typical": 1, "complex": 0})
        self.assertEqual(ir["complexity_flags"], [])
        self.assertEqual(ir["unsupported"], [])
        tg = ir["children"][0]
        self.assertEqual(tg["load"]["normalized"]["model"], "closed")
        self.assertEqual(tg["load"]["normalized"]["start_after_seconds"], 0)

    def test_large_body_is_externalized(self) -> None:
        ir = parse(jb.build_simple_backend(), self.tmp)

        def walk(nodes):
            for n in nodes:
                if isinstance(n, dict):
                    yield n
                    yield from walk(n.get("children", []))

        externalized = [
            n for n in walk(ir["children"])
            if isinstance(n.get("body"), dict) and "ref" in n["body"]
        ]
        self.assertEqual(len(externalized), 1, externalized)
        self.assertTrue(externalized[0]["body"]["ref"].startswith("bodies/"))


class GoldenStagedTest(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_staged_pipeline_flags(self) -> None:
        ir = parse(jb.build_staged_pipeline(), self.tmp)
        flags = {f["flag"] for f in ir["complexity_flags"]}
        self.assertIn("staged-thread-groups", flags)
        self.assertIn("inter-thread-props", flags)
        self.assertIn("props-usage", flags)
        by_kind = ir["stats"]["by_kind"]
        self.assertEqual(by_kind["thread_group"], 2)
        self.assertEqual(by_kind.get("jdbc_sampler", 0), 1)
        self.assertGreaterEqual(ir["stats"]["jsr223"]["complex"], 1)
        self.assertEqual(ir["unsupported"], [])
        self.assertIn("sharedToken", ir["variables"]["props"])


class DeterminismTest(unittest.TestCase):
    def test_committed_jmx_match_builder(self) -> None:
        here = Path(__file__).resolve().parent
        self.assertEqual(
            (here / "simple-backend.jmx").read_text(encoding="utf-8"),
            jb.build_simple_backend(),
        )
        self.assertEqual(
            (here / "staged-pipeline.jmx").read_text(encoding="utf-8"),
            jb.build_staged_pipeline(),
        )


if __name__ == "__main__":
    unittest.main()

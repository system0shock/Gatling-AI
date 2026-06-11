#!/usr/bin/env python3
"""Unit tests for the JMX parser."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import fixtures
import jmx_parser


class ParserCase(unittest.TestCase):
    """Shared setup: write a fixture document, parse it into a temp out dir."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.out_dir = self.tmp / "out"

    def parse(self, document: str, **kwargs):
        jmx_path = self.tmp / "plan.jmx"
        jmx_path.write_text(document, encoding="utf-8")
        return jmx_parser.parse_jmx(jmx_path, self.out_dir, **kwargs)


class WalkerTest(ParserCase):
    def test_minimal_plan(self) -> None:
        ir = self.parse(fixtures.jmx())
        self.assertEqual(ir["version"], 1)
        self.assertEqual(ir["test_plan"]["name"], "Test Plan")
        self.assertEqual(ir["test_plan"]["comments"], "fixture plan")
        self.assertEqual(ir["children"], [])
        self.assertEqual(ir["unsupported"], [])
        self.assertEqual(ir["source"]["file"], "plan.jmx")
        self.assertEqual(len(ir["source"]["sha256"]), 64)
        self.assertGreater(ir["source"]["size_bytes"], 0)

    def test_unknown_element_is_recorded_not_dropped(self) -> None:
        ir = self.parse(fixtures.jmx(fixtures.element("com.example.WeirdSampler", "weird")))
        node = ir["children"][0]
        self.assertEqual(node["kind"], "unknown")
        self.assertEqual(node["type"], "com.example.WeirdSampler")
        self.assertEqual(node["name"], "weird")
        self.assertEqual(ir["unsupported"][0]["id"], node["id"])
        self.assertEqual(ir["unsupported"][0]["path"], ["Test Plan"])

    def test_ids_follow_document_order(self) -> None:
        ir = self.parse(
            fixtures.jmx(
                fixtures.element("com.example.A", "a"),
                fixtures.element("com.example.B", "b"),
            )
        )
        self.assertEqual([node["id"] for node in ir["children"]], ["e-0001", "e-0002"])

    def test_nesting_follows_hash_trees(self) -> None:
        ir = self.parse(
            fixtures.jmx(
                fixtures.element(
                    "com.example.Outer", "outer",
                    children=fixtures.element("com.example.Inner", "inner"),
                )
            )
        )
        outer = ir["children"][0]
        self.assertEqual(outer["children"][0]["name"], "inner")
        self.assertEqual(outer["children"][0]["path"], ["Test Plan", "outer"])
        self.assertEqual(outer["children"][0]["id"], "e-0002")

    def test_disabled_element_keeps_enabled_false(self) -> None:
        ir = self.parse(fixtures.jmx(fixtures.element("com.example.A", "a", enabled=False)))
        self.assertFalse(ir["children"][0]["enabled"])


class ThreadGroupTest(ParserCase):
    def test_standard_thread_group_raw_load(self) -> None:
        ir = self.parse(fixtures.jmx(fixtures.thread_group("Main", threads=10, ramp=30)))
        node = ir["children"][0]
        self.assertEqual(node["kind"], "thread_group")
        self.assertEqual(node["flavor"], "standard")
        self.assertEqual(node["load"]["raw"]["num_threads"], "10")
        self.assertEqual(node["load"]["raw"]["ramp_time"], "30")

    def test_plugin_thread_group_flavor(self) -> None:
        document = fixtures.jmx(
            fixtures.element(
                "kg.apc.jmeter.threads.UltimateThreadGroup", "U",
                guiclass="UltimateThreadGroupGui",
            )
        )
        ir = self.parse(document)
        node = ir["children"][0]
        self.assertEqual(node["kind"], "thread_group")
        self.assertEqual(node["flavor"], "ultimate")


class HttpSamplerTest(ParserCase):
    def test_http_sampler_method_path_and_inline_body(self) -> None:
        ir = self.parse(
            fixtures.jmx(
                fixtures.thread_group(
                    "Main",
                    children=fixtures.http_sampler(
                        "checkout", method="POST", path="/checkout", body='{"a":1}'
                    ),
                )
            )
        )
        sampler = ir["children"][0]["children"][0]
        self.assertEqual(sampler["kind"], "http_sampler")
        self.assertEqual(sampler["method"], "POST")
        self.assertEqual(sampler["url"]["path"], "/checkout")
        self.assertEqual(sampler["body"]["inline"], '{"a":1}')
        self.assertEqual(sampler["body"]["variables"], [])
        self.assertEqual(sampler["body"]["functions"], [])

    def test_http_sampler_query_params(self) -> None:
        ir = self.parse(
            fixtures.jmx(
                fixtures.thread_group(
                    "Main",
                    children=fixtures.http_sampler(
                        "search", path="/search", params={"q": "${term}"}
                    ),
                )
            )
        )
        sampler = ir["children"][0]["children"][0]
        self.assertNotIn("body", sampler)
        self.assertEqual(sampler["params"], [{"name": "q", "value": "${term}"}])

    def test_plain_get_has_neither_body_nor_params(self) -> None:
        ir = self.parse(
            fixtures.jmx(
                fixtures.thread_group("Main", children=fixtures.http_sampler("ping"))
            )
        )
        sampler = ir["children"][0]["children"][0]
        self.assertNotIn("body", sampler)
        self.assertNotIn("params", sampler)


class BodyStoreTest(ParserCase):
    def sampler_with_body(self, body: str, name: str = "req") -> str:
        return fixtures.jmx(
            fixtures.thread_group(
                "Main",
                children=fixtures.http_sampler(name, method="POST", path="/x", body=body),
            )
        )

    def two_samplers_with_body(self, body: str) -> str:
        return fixtures.jmx(
            fixtures.thread_group(
                "Main",
                children="\n".join(
                    [
                        fixtures.http_sampler("a", method="POST", path="/x", body=body),
                        fixtures.http_sampler("b", method="POST", path="/y", body=body),
                    ]
                ),
            )
        )

    def test_small_body_stays_inline_with_variables(self) -> None:
        ir = self.parse(self.sampler_with_body('{"id":"${productId}","t":"${__time()}"}'))
        body = ir["children"][0]["children"][0]["body"]
        self.assertEqual(body["variables"], ["productId"])
        self.assertEqual(body["functions"], ["time"])
        self.assertIn("inline", body)

    def test_large_body_is_externalized(self) -> None:
        payload = '{"data":"' + "x" * 5000 + '","user":"${user}"}'
        ir = self.parse(self.sampler_with_body(payload))
        body = ir["children"][0]["children"][0]["body"]
        self.assertNotIn("inline", body)
        self.assertTrue(body["ref"].startswith("bodies/"))
        self.assertTrue(body["ref"].endswith(".json"))
        self.assertEqual(body["bytes"], len(payload.encode("utf-8")))
        self.assertEqual(body["variables"], ["user"])
        self.assertEqual(body["preview"], payload[:200])
        stored = (self.out_dir / body["ref"]).read_text(encoding="utf-8")
        self.assertEqual(stored, payload)

    def test_identical_bodies_are_deduplicated(self) -> None:
        payload = "y" * 5000
        ir = self.parse(self.two_samplers_with_body(payload))
        steps = ir["children"][0]["children"]
        self.assertEqual(steps[0]["body"]["ref"], steps[1]["body"]["ref"])
        self.assertTrue(steps[0]["body"]["ref"].endswith(".txt"))
        self.assertEqual(len(list((self.out_dir / "bodies").iterdir())), 1)

    def test_threshold_is_configurable(self) -> None:
        ir = self.parse(self.sampler_with_body("z" * 100), max_inline_body=10)
        self.assertIn("ref", ir["children"][0]["children"][0]["body"])


if __name__ == "__main__":
    sys.exit(unittest.main())

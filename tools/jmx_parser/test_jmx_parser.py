#!/usr/bin/env python3
"""Unit tests for the JMX parser."""

from __future__ import annotations

import hashlib
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
        self.assertEqual(set(sampler["body"].keys()), {"inline", "variables", "functions"})

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
        self.assertEqual(body["sha256"], hashlib.sha256(payload.encode("utf-8")).hexdigest())
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


def module_controller(name: str, target_path: list[str]) -> str:
    rows = "\n".join(
        f'    <stringProp name="node_{index}">{value}</stringProp>'
        for index, value in enumerate(target_path)
    )
    props = (
        '  <collectionProp name="ModuleController.node_path">\n'
        f"{rows}\n"
        "  </collectionProp>"
    )
    return fixtures.element(
        "ModuleController", name, guiclass="ModuleControllerGui", props=props
    )


class ControllerTest(ParserCase):
    def test_transaction_and_simple_controllers(self) -> None:
        ir = self.parse(
            fixtures.jmx(
                fixtures.thread_group(
                    "Main",
                    children="\n".join(
                        [
                            fixtures.element(
                                "TransactionController", "Login",
                                props=fixtures.bool_prop("TransactionController.parent", True),
                                children=fixtures.http_sampler("post-login"),
                            ),
                            fixtures.element(
                                "IfController", "maybe",
                                props=fixtures.string_prop(
                                    "IfController.condition", '"${flag}" == "1"'
                                ),
                            ),
                            fixtures.element(
                                "LoopController", "thrice",
                                props=fixtures.string_prop("LoopController.loops", "3"),
                            ),
                            fixtures.element("OnceOnlyController", "setup"),
                            fixtures.element("GenericController", "plain"),
                            fixtures.element(
                                "ThroughputController", "half",
                                props=fixtures.string_prop(
                                    "ThroughputController.percentThroughput", "50.0"
                                ),
                            ),
                        ]
                    ),
                )
            )
        )
        children = ir["children"][0]["children"]
        kinds = [node["kind"] for node in children]
        self.assertEqual(
            kinds, ["transaction", "if", "loop", "once_only", "simple", "throughput"]
        )
        self.assertTrue(children[0]["generate_parent_sample"])
        self.assertEqual(children[0]["children"][0]["kind"], "http_sampler")
        self.assertEqual(children[1]["condition"], '"${flag}" == "1"')
        self.assertEqual(children[2]["loops"], "3")
        self.assertEqual(children[5]["percent"], "50.0")
        self.assertEqual(children[5]["style"], 0)
        self.assertEqual(ir["unsupported"], [])

    def test_module_controller_resolves_fragment(self) -> None:
        ir = self.parse(
            fixtures.jmx(
                fixtures.element(
                    "TestFragmentController", "Shared steps",
                    children=fixtures.http_sampler("shared-call"),
                ),
                fixtures.thread_group(
                    "Main",
                    children=module_controller("use shared", ["Test Plan", "Shared steps"]),
                ),
            )
        )
        fragment = ir["children"][0]
        module = ir["children"][1]["children"][0]
        self.assertEqual(fragment["kind"], "fragment")
        self.assertEqual(module["kind"], "module")
        self.assertEqual(module["target_path"], ["Test Plan", "Shared steps"])
        self.assertEqual(module["target_id"], fragment["id"])
        self.assertFalse(module["unresolved"])

    def test_module_controller_unresolved_target(self) -> None:
        ir = self.parse(
            fixtures.jmx(
                fixtures.thread_group(
                    "Main",
                    children=module_controller("dangling", ["Test Plan", "missing"]),
                )
            )
        )
        module = ir["children"][0]["children"][0]
        self.assertIsNone(module["target_id"])
        self.assertTrue(module["unresolved"])


def arguments_props(values: dict[str, str]) -> str:
    rows = "\n".join(
        '    <elementProp name="" elementType="Argument">\n'
        f'      <stringProp name="Argument.name">{key}</stringProp>\n'
        f'      <stringProp name="Argument.value">{value}</stringProp>\n'
        "    </elementProp>"
        for key, value in values.items()
    )
    return f'  <collectionProp name="Arguments.arguments">\n{rows}\n  </collectionProp>'


class ConfigElementTest(ParserCase):
    def test_csv_data_set(self) -> None:
        props = "\n".join(
            [
                fixtures.string_prop("filename", "users.csv"),
                fixtures.string_prop("variableNames", "login, password"),
                fixtures.string_prop("delimiter", ","),
                fixtures.bool_prop("recycle", True),
                fixtures.string_prop("shareMode", "shareMode.all"),
            ]
        )
        ir = self.parse(
            fixtures.jmx(fixtures.element("CSVDataSet", "users", props=props))
        )
        node = ir["children"][0]
        self.assertEqual(node["kind"], "csv_data_set")
        self.assertEqual(node["file"], "users.csv")
        self.assertEqual(node["variable_names"], ["login", "password"])
        self.assertTrue(node["recycle"])

    def test_user_defined_variables(self) -> None:
        ir = self.parse(
            fixtures.jmx(
                fixtures.element(
                    "Arguments", "Env", guiclass="ArgumentsPanel",
                    props=arguments_props({"host": "shop.local", "port": "8080"}),
                )
            )
        )
        node = ir["children"][0]
        self.assertEqual(node["kind"], "user_defined_variables")
        self.assertEqual(node["values"], {"host": "shop.local", "port": "8080"})

    def test_http_defaults_and_managers(self) -> None:
        defaults_props = "\n".join(
            [
                fixtures.string_prop("HTTPSampler.domain", "${host}"),
                fixtures.string_prop("HTTPSampler.port", "${port}"),
                fixtures.string_prop("HTTPSampler.protocol", "https"),
            ]
        )
        header_props = (
            '  <collectionProp name="HeaderManager.headers">\n'
            '    <elementProp name="" elementType="Header">\n'
            '      <stringProp name="Header.name">Content-Type</stringProp>\n'
            '      <stringProp name="Header.value">application/json</stringProp>\n'
            "    </elementProp>\n"
            "  </collectionProp>"
        )
        ir = self.parse(
            fixtures.jmx(
                fixtures.element(
                    "ConfigTestElement", "Defaults", guiclass="HttpDefaultsGui",
                    props=defaults_props,
                ),
                fixtures.element("HeaderManager", "Headers", props=header_props),
                fixtures.element("CookieManager", "Cookies"),
            )
        )
        defaults, headers, cookies = ir["children"]
        self.assertEqual(defaults["kind"], "http_defaults")
        self.assertEqual(defaults["url"]["domain"], "${host}")
        self.assertEqual(headers["kind"], "header_manager")
        self.assertEqual(headers["headers"], {"Content-Type": "application/json"})
        self.assertEqual(cookies["kind"], "cookie_manager")

    def test_counter_and_random_variable(self) -> None:
        counter_props = "\n".join(
            [
                fixtures.string_prop("CounterConfig.name", "orderNo"),
                fixtures.string_prop("CounterConfig.start", "1"),
                fixtures.string_prop("CounterConfig.incr", "1"),
            ]
        )
        random_props = "\n".join(
            [
                fixtures.string_prop("variableName", "rndUser"),
                fixtures.string_prop("minimumValue", "1"),
                fixtures.string_prop("maximumValue", "100"),
            ]
        )
        ir = self.parse(
            fixtures.jmx(
                fixtures.element("CounterConfig", "Counter", props=counter_props),
                fixtures.element("RandomVariableConfig", "Random", props=random_props),
            )
        )
        counter, random_var = ir["children"]
        self.assertEqual(counter["kind"], "counter")
        self.assertEqual(counter["variable"], "orderNo")
        self.assertEqual(random_var["kind"], "random_variable")
        self.assertEqual(random_var["variable"], "rndUser")


if __name__ == "__main__":
    sys.exit(unittest.main())

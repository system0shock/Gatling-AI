#!/usr/bin/env python3
"""Unit tests for the JMX parser."""

from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import fixtures
import jmx_parser

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover
    Draft202012Validator = None

REPO_ROOT = Path(__file__).resolve().parents[2]


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
        self.assertEqual(node["delimiter"], ",")
        self.assertEqual(node["share_mode"], "shareMode.all")

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

    def test_csv_without_variable_names_signals_header_row(self) -> None:
        ir = self.parse(
            fixtures.jmx(
                fixtures.element(
                    "CSVDataSet", "headers",
                    props=fixtures.string_prop("filename", "data.csv"),
                )
            )
        )
        self.assertIsNone(ir["children"][0]["variable_names"])

    def test_config_test_element_unknown_guiclass_is_unsupported(self) -> None:
        ir = self.parse(
            fixtures.jmx(
                fixtures.element("ConfigTestElement", "FTP", guiclass="FtpDefaultsGui")
            )
        )
        node = ir["children"][0]
        self.assertEqual(node["kind"], "unknown")
        self.assertEqual(ir["unsupported"][0]["id"], node["id"])


class ExtractorAssertionTimerTest(ParserCase):
    def parse_sampler_children(self, children: str) -> list[dict]:
        ir = self.parse(
            fixtures.jmx(
                fixtures.thread_group(
                    "Main", children=fixtures.http_sampler("req", children=children)
                )
            )
        )
        return ir["children"][0]["children"][0]["children"]

    def test_regex_and_boundary_extractors(self) -> None:
        regex_props = "\n".join(
            [
                fixtures.string_prop("RegexExtractor.refname", "csrf"),
                fixtures.string_prop("RegexExtractor.regex", 'name="csrf" value="(.+?)"'),
                fixtures.string_prop("RegexExtractor.template", "$1$"),
                fixtures.string_prop("RegexExtractor.match_number", "1"),
                fixtures.string_prop("RegexExtractor.default", "NOT_FOUND"),
            ]
        )
        boundary_props = "\n".join(
            [
                fixtures.string_prop("BoundaryExtractor.refname", "token"),
                fixtures.string_prop("BoundaryExtractor.lboundary", "token="),
                fixtures.string_prop("BoundaryExtractor.rboundary", ";"),
            ]
        )
        nodes = self.parse_sampler_children(
            "\n".join(
                [
                    fixtures.element("RegexExtractor", "get csrf", props=regex_props),
                    fixtures.element("BoundaryExtractor", "get token", props=boundary_props),
                ]
            )
        )
        regex, boundary = nodes
        self.assertEqual(regex["kind"], "regex_extractor")
        self.assertEqual(regex["variable"], "csrf")
        self.assertEqual(regex["default"], "NOT_FOUND")
        self.assertEqual(boundary["kind"], "boundary_extractor")
        self.assertEqual(boundary["variable"], "token")
        self.assertEqual(boundary["left"], "token=")
        self.assertEqual(boundary["right"], ";")

    def test_jsonpath_extractor_with_multiple_refs(self) -> None:
        props = "\n".join(
            [
                fixtures.string_prop("JSONPostProcessor.referenceNames", "id;price"),
                fixtures.string_prop(
                    "JSONPostProcessor.jsonPathExprs", "$.items[0].id;$.items[0].price"
                ),
                fixtures.string_prop("JSONPostProcessor.match_numbers", "1;1"),
                fixtures.string_prop("JSONPostProcessor.defaultValues", "MISSING;0"),
            ]
        )
        nodes = self.parse_sampler_children(
            fixtures.element("JSONPostProcessor", "ids", props=props)
        )
        node = nodes[0]
        self.assertEqual(node["kind"], "jsonpath_extractor")
        self.assertEqual(
            node["extracts"],
            [
                {"variable": "id", "expr": "$.items[0].id", "match_number": "1", "default": "MISSING"},
                {"variable": "price", "expr": "$.items[0].price", "match_number": "1", "default": "0"},
            ],
        )

    def test_assertions(self) -> None:
        response_props = (
            '  <collectionProp name="Asserion.test_strings">\n'
            '    <stringProp name="s0">200</stringProp>\n'
            "  </collectionProp>\n"
            + fixtures.string_prop("Assertion.test_field", "Assertion.response_code")
            + "\n"
            + '  <intProp name="Assertion.test_type">8</intProp>'
        )
        json_props = "\n".join(
            [
                fixtures.string_prop("JSON_PATH", "$.status"),
                fixtures.string_prop("EXPECTED_VALUE", "OK"),
                fixtures.bool_prop("JSONVALIDATION", True),
            ]
        )
        duration_props = fixtures.string_prop("DurationAssertion.duration", "2000")
        nodes = self.parse_sampler_children(
            "\n".join(
                [
                    fixtures.element("ResponseAssertion", "status 200", props=response_props),
                    fixtures.element("JSONPathAssertion", "status ok", props=json_props),
                    fixtures.element("DurationAssertion", "fast", props=duration_props),
                ]
            )
        )
        response, json_assert, duration = nodes
        self.assertEqual(response["kind"], "response_assertion")
        self.assertEqual(response["field"], "Assertion.response_code")
        self.assertEqual(response["patterns"], ["200"])
        self.assertEqual(response["test_type"], 8)
        self.assertEqual(json_assert["kind"], "json_assertion")
        self.assertEqual(json_assert["json_path"], "$.status")
        self.assertEqual(duration["kind"], "duration_assertion")
        self.assertEqual(duration["duration_ms"], "2000")

    def test_timers(self) -> None:
        constant = fixtures.element(
            "ConstantTimer", "wait",
            props=fixtures.string_prop("ConstantTimer.delay", "1000"),
        )
        uniform = fixtures.element(
            "UniformRandomTimer", "jitter",
            props="\n".join(
                [
                    fixtures.string_prop("ConstantTimer.delay", "500"),
                    fixtures.string_prop("RandomTimer.range", "1000"),
                ]
            ),
        )
        throughput = fixtures.element(
            "ConstantThroughputTimer", "pace",
            props=(
                "  <doubleProp>\n"
                "    <name>throughput</name>\n"
                "    <value>120.0</value>\n"
                "  </doubleProp>\n"
                '  <intProp name="calcMode">0</intProp>'
            ),
        )
        nodes = self.parse_sampler_children("\n".join([constant, uniform, throughput]))
        self.assertEqual(
            [node["kind"] for node in nodes],
            ["constant_timer", "uniform_random_timer", "constant_throughput_timer"],
        )
        self.assertEqual(nodes[0]["delay_ms"], "1000")
        self.assertEqual(nodes[1]["range_ms"], "1000")
        self.assertEqual(nodes[1]["offset_ms"], "500")
        self.assertEqual(nodes[2]["throughput_per_min"], "120.0")
        self.assertEqual(nodes[2]["calc_mode"], 0)


def jsr223(testclass: str, name: str, script: str, language: str = "groovy") -> str:
    props = "\n".join(
        [
            fixtures.string_prop("script", script),
            fixtures.string_prop("scriptLanguage", language),
        ]
    )
    return fixtures.element(testclass, name, props=props)


class Jsr223Test(ParserCase):
    def parse_pre(self, script: str) -> dict:
        ir = self.parse(
            fixtures.jmx(
                fixtures.thread_group(
                    "Main",
                    children=fixtures.http_sampler(
                        "req", children=jsr223("JSR223PreProcessor", "prep", script)
                    ),
                )
            )
        )
        return ir["children"][0]["children"][0]["children"][0]

    def test_typical_uuid_script(self) -> None:
        node = self.parse_pre(
            'def rid = UUID.randomUUID().toString()\nvars.put("requestId", rid)'
        )
        self.assertEqual(node["kind"], "jsr223_pre")
        self.assertEqual(node["classification"], "typical")
        self.assertEqual(node["classification_reasons"], [])
        self.assertEqual(node["writes"], ["requestId"])
        self.assertEqual(node["reads"], [])
        self.assertTrue(node["script_ref"].startswith("jsr223/"))
        stored = (self.out_dir / node["script_ref"]).read_text(encoding="utf-8")
        self.assertIn("randomUUID", stored)

    def test_props_usage_is_complex(self) -> None:
        node = self.parse_pre('props.put("sharedToken", vars.get("token"))')
        self.assertEqual(node["classification"], "complex")
        self.assertIn("uses props (inter-thread state)", node["classification_reasons"])
        self.assertEqual(node["props_writes"], ["sharedToken"])
        self.assertEqual(node["reads"], ["token"])

    def test_unknown_api_is_complex_with_reason(self) -> None:
        node = self.parse_pre(
            'def signed = SignerUtil.hmac(vars.get("body"))\nvars.put("sig", signed)'
        )
        self.assertEqual(node["classification"], "complex")
        self.assertTrue(
            any("SignerUtil" in reason for reason in node["classification_reasons"])
        )

    def test_external_script_file_is_complex(self) -> None:
        ir = self.parse(
            fixtures.jmx(
                fixtures.thread_group(
                    "Main",
                    children=fixtures.element(
                        "JSR223Sampler", "ext",
                        props=fixtures.string_prop("filename", "scripts/do_stuff.groovy"),
                    ),
                )
            )
        )
        node = ir["children"][0]["children"][0]
        self.assertEqual(node["kind"], "jsr223_sampler")
        self.assertEqual(node["script_file"], "scripts/do_stuff.groovy")
        self.assertEqual(node["classification"], "complex")
        self.assertEqual(node["classification_reasons"], ["external script file"])

    def test_identical_scripts_share_one_file(self) -> None:
        script = 'vars.put("ts", String.valueOf(System.currentTimeMillis()))'
        ir = self.parse(
            fixtures.jmx(
                fixtures.thread_group(
                    "Main",
                    children="\n".join(
                        [
                            fixtures.http_sampler(
                                "a", children=jsr223("JSR223PreProcessor", "p1", script)
                            ),
                            fixtures.http_sampler(
                                "b", children=jsr223("JSR223PreProcessor", "p2", script)
                            ),
                        ]
                    ),
                )
            )
        )
        steps = ir["children"][0]["children"]
        ref_a = steps[0]["children"][0]["script_ref"]
        ref_b = steps[1]["children"][0]["script_ref"]
        self.assertEqual(ref_a, ref_b)
        self.assertEqual(len(list((self.out_dir / "jsr223").iterdir())), 1)

    def test_props_with_dynamic_key_is_complex(self) -> None:
        node = self.parse_pre('def k = "sharedToken"\nString v = props.get(k)')
        self.assertEqual(node["classification"], "complex")
        self.assertIn("uses props (inter-thread state)", node["classification_reasons"])

    def test_object_vars_are_complex_but_tracked(self) -> None:
        node = self.parse_pre('vars.putObject("session", SignerUtil.init())')
        self.assertEqual(node["classification"], "complex")
        self.assertEqual(node["writes"], ["session"])

    def test_jdbc_sampler_is_recognized_for_stub_conversion(self) -> None:
        ir = self.parse(
            fixtures.jmx(
                fixtures.thread_group(
                    "Main",
                    children=fixtures.element(
                        "JDBCSampler", "check balance",
                        props=fixtures.string_prop("query", "SELECT 1"),
                    ),
                )
            )
        )
        node = ir["children"][0]["children"][0]
        self.assertEqual(node["kind"], "jdbc_sampler")
        self.assertEqual(node["query"], "SELECT 1")
        self.assertEqual(ir["unsupported"], [])


def plugin_thread_group(testclass: str, guiclass: str, props: str, name: str = "TG") -> str:
    return fixtures.element(testclass, name, guiclass=guiclass, props=props)


class LoadNormalizationTest(ParserCase):
    def load_of_first(self, document: str) -> dict:
        return self.parse(document)["children"][0]["load"]

    def test_standard_with_scheduler(self) -> None:
        load = self.load_of_first(
            fixtures.jmx(fixtures.thread_group("Main", threads=10, ramp=30, duration=330, delay=60))
        )
        self.assertEqual(
            load["normalized"],
            {
                "model": "closed",
                "stages": [{"users": 10, "ramp_seconds": 30, "hold_seconds": 300}],
                "start_after_seconds": 60,
            },
        )

    def test_standard_parameterized_is_not_normalized(self) -> None:
        document = fixtures.jmx(
            plugin_thread_group(
                "ThreadGroup", "ThreadGroupGui",
                fixtures.string_prop("ThreadGroup.num_threads", "${THREADS}"),
            )
        )
        load = self.load_of_first(document)
        self.assertIsNone(load["normalized"])
        self.assertIn("parameterized", load["normalization_note"])

    def test_stepping_builds_staircase(self) -> None:
        props = "\n".join(
            [
                fixtures.string_prop("ThreadGroup.num_threads", "30"),
                fixtures.string_prop("Start users count", "10"),
                fixtures.string_prop("Start users period", "60"),
                fixtures.string_prop("rampUp", "5"),
                fixtures.string_prop("flighttime", "300"),
                fixtures.string_prop("Threads initial delay", "0"),
            ]
        )
        load = self.load_of_first(
            fixtures.jmx(
                plugin_thread_group(
                    "kg.apc.jmeter.threads.SteppingThreadGroup", "SteppingThreadGroupGui", props
                )
            )
        )
        self.assertEqual(
            load["normalized"]["stages"],
            [
                {"users": 10, "ramp_seconds": 5, "hold_seconds": 60},
                {"users": 20, "ramp_seconds": 5, "hold_seconds": 60},
                {"users": 30, "ramp_seconds": 5, "hold_seconds": 300},
            ],
        )

    def test_ultimate_single_row(self) -> None:
        props = (
            '  <collectionProp name="ultimatethreadgroupdata">\n'
            '    <collectionProp name="row">\n'
            '      <stringProp name="c0">50</stringProp>\n'
            '      <stringProp name="c1">10</stringProp>\n'
            '      <stringProp name="c2">120</stringProp>\n'
            '      <stringProp name="c3">600</stringProp>\n'
            '      <stringProp name="c4">60</stringProp>\n'
            "    </collectionProp>\n"
            "  </collectionProp>"
        )
        load = self.load_of_first(
            fixtures.jmx(
                plugin_thread_group(
                    "kg.apc.jmeter.threads.UltimateThreadGroup", "UltimateThreadGroupGui", props
                )
            )
        )
        self.assertEqual(
            load["normalized"],
            {
                "model": "closed",
                "stages": [{"users": 50, "ramp_seconds": 120, "hold_seconds": 600}],
                "start_after_seconds": 10,
            },
        )
        self.assertEqual(
            load["normalization_note"],
            "shutdown ramp-down not representable in stages; ignored",
        )

    def test_ultimate_multi_row_left_for_review(self) -> None:
        row = (
            '    <collectionProp name="r">\n'
            '      <stringProp name="c0">10</stringProp>\n'
            '      <stringProp name="c1">0</stringProp>\n'
            '      <stringProp name="c2">60</stringProp>\n'
            '      <stringProp name="c3">300</stringProp>\n'
            '      <stringProp name="c4">30</stringProp>\n'
            "    </collectionProp>\n"
        )
        props = (
            '  <collectionProp name="ultimatethreadgroupdata">\n' + row + row +
            "  </collectionProp>"
        )
        load = self.load_of_first(
            fixtures.jmx(
                plugin_thread_group(
                    "kg.apc.jmeter.threads.UltimateThreadGroup", "UltimateThreadGroupGui", props
                )
            )
        )
        self.assertIsNone(load["normalized"])
        self.assertIn("2 schedule rows", load["normalization_note"])
        self.assertEqual(len(load["raw"]["rows"]), 2)

    def test_concurrency_with_steps(self) -> None:
        props = "\n".join(
            [
                fixtures.string_prop("TargetLevel", "20"),
                fixtures.string_prop("RampUp", "4"),
                fixtures.string_prop("Steps", "2"),
                fixtures.string_prop("Hold", "10"),
                fixtures.string_prop("Unit", "M"),
            ]
        )
        load = self.load_of_first(
            fixtures.jmx(
                plugin_thread_group(
                    "com.blazemeter.jmeter.threads.concurrency.ConcurrencyThreadGroup",
                    "ConcurrencyThreadGroupGui", props,
                )
            )
        )
        self.assertEqual(load["normalized"]["model"], "closed")
        self.assertEqual(
            load["normalized"]["stages"],
            [
                {"users": 10, "ramp_seconds": 120, "hold_seconds": 300},
                {"users": 20, "ramp_seconds": 120, "hold_seconds": 300},
            ],
        )

    def test_arrivals_is_open_model(self) -> None:
        props = "\n".join(
            [
                fixtures.string_prop("TargetLevel", "120"),
                fixtures.string_prop("RampUp", "1"),
                fixtures.string_prop("Steps", "0"),
                fixtures.string_prop("Hold", "5"),
                fixtures.string_prop("Unit", "M"),
            ]
        )
        load = self.load_of_first(
            fixtures.jmx(
                plugin_thread_group(
                    "com.blazemeter.jmeter.threads.arrivals.ArrivalsThreadGroup",
                    "ArrivalsThreadGroupGui", props,
                )
            )
        )
        self.assertEqual(load["normalized"]["model"], "open")
        self.assertEqual(
            load["normalized"]["stages"],
            [{"users_per_second": 2.0, "ramp_seconds": 60, "hold_seconds": 300}],
        )

    def test_arrivals_with_steps_builds_open_staircase(self) -> None:
        props = "\n".join(
            [
                fixtures.string_prop("TargetLevel", "120"),
                fixtures.string_prop("RampUp", "2"),
                fixtures.string_prop("Steps", "2"),
                fixtures.string_prop("Hold", "10"),
                fixtures.string_prop("Unit", "M"),
            ]
        )
        load = self.load_of_first(
            fixtures.jmx(
                plugin_thread_group(
                    "com.blazemeter.jmeter.threads.arrivals.ArrivalsThreadGroup",
                    "ArrivalsThreadGroupGui", props,
                )
            )
        )
        self.assertEqual(
            load["normalized"]["stages"],
            [
                {"users_per_second": 1.0, "ramp_seconds": 60, "hold_seconds": 300},
                {"users_per_second": 2.0, "ramp_seconds": 60, "hold_seconds": 300},
            ],
        )

    def test_ultimate_single_row_has_shutdown_note(self) -> None:
        props = (
            '  <collectionProp name="ultimatethreadgroupdata">\n'
            '    <collectionProp name="row">\n'
            '      <stringProp name="c0">50</stringProp>\n'
            '      <stringProp name="c1">10</stringProp>\n'
            '      <stringProp name="c2">120</stringProp>\n'
            '      <stringProp name="c3">600</stringProp>\n'
            '      <stringProp name="c4">60</stringProp>\n'
            "    </collectionProp>\n"
            "  </collectionProp>"
        )
        load = self.load_of_first(
            fixtures.jmx(
                plugin_thread_group(
                    "kg.apc.jmeter.threads.UltimateThreadGroup", "UltimateThreadGroupGui", props
                )
            )
        )
        self.assertEqual(
            load["normalization_note"],
            "shutdown ramp-down not representable in stages; ignored",
        )

    def test_ultimate_empty_schedule(self) -> None:
        props = '  <collectionProp name="ultimatethreadgroupdata">\n  </collectionProp>'
        load = self.load_of_first(
            fixtures.jmx(
                plugin_thread_group(
                    "kg.apc.jmeter.threads.UltimateThreadGroup", "UltimateThreadGroupGui", props
                )
            )
        )
        self.assertIsNone(load["normalized"])
        self.assertEqual(load["normalization_note"], "empty schedule (no rows)")

    def test_standard_without_scheduler_has_open_ended_hold(self) -> None:
        load = self.load_of_first(
            fixtures.jmx(fixtures.thread_group("Main", threads=5, ramp=10))
        )
        self.assertIsNone(load["normalized"]["stages"][0]["hold_seconds"])
        self.assertNotIn("normalization_note", load)


class VariableIndexTest(ParserCase):
    def test_extractor_to_consumer_link(self) -> None:
        regex_props = "\n".join(
            [
                fixtures.string_prop("RegexExtractor.refname", "csrf"),
                fixtures.string_prop("RegexExtractor.regex", "v=(.+?);"),
            ]
        )
        ir = self.parse(
            fixtures.jmx(
                fixtures.thread_group(
                    "Main",
                    children="\n".join(
                        [
                            fixtures.http_sampler(
                                "login",
                                children=fixtures.element(
                                    "RegexExtractor", "get csrf", props=regex_props
                                ),
                            ),
                            fixtures.http_sampler("submit", path="/submit?c=${csrf}"),
                        ]
                    ),
                )
            )
        )
        entry = ir["variables"]["index"]["csrf"]
        self.assertEqual(len(entry["producers"]), 1)
        self.assertEqual(len(entry["consumers"]), 1)
        findings = ir["variables"]["findings"]
        self.assertEqual(findings["consumed_not_produced"], [])
        self.assertEqual(findings["produced_not_consumed"], [])

    def test_orphan_and_dead_variables(self) -> None:
        regex_props = fixtures.string_prop("RegexExtractor.refname", "unusedVar")
        ir = self.parse(
            fixtures.jmx(
                fixtures.thread_group(
                    "Main",
                    children="\n".join(
                        [
                            fixtures.http_sampler(
                                "a", path="/x?g=${ghost}",
                                children=fixtures.element(
                                    "RegexExtractor", "dead", props=regex_props
                                ),
                            ),
                        ]
                    ),
                )
            )
        )
        findings = ir["variables"]["findings"]
        self.assertEqual(findings["consumed_not_produced"][0]["variable"], "ghost")
        self.assertEqual(findings["produced_not_consumed"][0]["variable"], "unusedVar")

    def test_functions_are_not_variables(self) -> None:
        ir = self.parse(
            fixtures.jmx(
                fixtures.thread_group(
                    "Main",
                    children=fixtures.http_sampler("a", path="/x?t=${__time()}"),
                )
            )
        )
        self.assertIn("time", ir["variables"]["functions"])
        self.assertNotIn("__time", ir["variables"]["index"])

    def test_externalized_body_variables_are_indexed(self) -> None:
        body = '{"pad":"' + "x" * 5000 + '","user":"${login}"}'
        ir = self.parse(
            fixtures.jmx(
                fixtures.thread_group(
                    "Main",
                    children=fixtures.http_sampler("a", method="POST", path="/x", body=body),
                )
            )
        )
        self.assertIn("login", ir["variables"]["index"])
        self.assertEqual(
            ir["variables"]["findings"]["consumed_not_produced"][0]["variable"], "login"
        )

    def test_disabled_elements_do_not_contribute(self) -> None:
        ir = self.parse(
            fixtures.jmx(
                fixtures.thread_group(
                    "Main",
                    children=fixtures.http_sampler("off", path="/x?g=${ghost}"),
                    enabled=False,
                )
            )
        )
        self.assertEqual(ir["variables"]["findings"]["consumed_not_produced"], [])


class ComplexityFlagTest(ParserCase):
    def test_props_across_thread_groups(self) -> None:
        ir = self.parse(
            fixtures.jmx(
                fixtures.thread_group(
                    "Writer", delay=0,
                    children=fixtures.http_sampler(
                        "w",
                        children=jsr223(
                            "JSR223PostProcessor", "share",
                            'props.put("shared", vars.get("x"))',
                        ),
                    ),
                ),
                fixtures.thread_group(
                    "Reader", delay=1200, duration=600,
                    children=fixtures.http_sampler(
                        "r",
                        children=jsr223(
                            "JSR223PreProcessor", "take",
                            'vars.put("y", props.get("shared"))',
                        ),
                    ),
                ),
            )
        )
        flags = {flag["flag"] for flag in ir["complexity_flags"]}
        self.assertIn("props-usage", flags)
        self.assertIn("inter-thread-props", flags)
        self.assertIn("staged-thread-groups", flags)
        props = ir["variables"]["props"]["shared"]
        self.assertEqual(len(props["writers"]), 1)
        self.assertEqual(len(props["readers"]), 1)

    def test_inter_thread_props_with_same_named_groups(self) -> None:
        ir = self.parse(
            fixtures.jmx(
                fixtures.thread_group(
                    "TG",
                    children=fixtures.http_sampler(
                        "w",
                        children=jsr223(
                            "JSR223PostProcessor", "share", 'props.put("p", "1")'
                        ),
                    ),
                ),
                fixtures.thread_group(
                    "TG",
                    children=fixtures.http_sampler(
                        "r",
                        children=jsr223(
                            "JSR223PreProcessor", "take", 'vars.put("y", props.get("p"))'
                        ),
                    ),
                ),
            )
        )
        flags = {flag["flag"] for flag in ir["complexity_flags"]}
        self.assertIn("inter-thread-props", flags)

    def test_unknown_and_unresolved_flags(self) -> None:
        ir = self.parse(
            fixtures.jmx(
                fixtures.thread_group(
                    "Main",
                    children="\n".join(
                        [
                            fixtures.element("com.example.Strange", "odd"),
                            module_controller("dangling", ["Test Plan", "nope"]),
                        ]
                    ),
                )
            )
        )
        flags = {flag["flag"] for flag in ir["complexity_flags"]}
        self.assertIn("unknown-elements", flags)
        self.assertIn("unresolved-module", flags)

    def test_stats(self) -> None:
        ir = self.parse(
            fixtures.jmx(
                fixtures.thread_group(
                    "Main",
                    children="\n".join(
                        [
                            fixtures.http_sampler("a"),
                            fixtures.http_sampler("b"),
                        ]
                    ),
                )
            )
        )
        self.assertEqual(ir["stats"]["by_kind"]["http_sampler"], 2)
        self.assertEqual(ir["stats"]["elements_total"], 3)
        self.assertEqual(ir["stats"]["elements_disabled"], 0)


class InventoryTest(ParserCase):
    def test_inventory_sections(self) -> None:
        ir = self.parse(
            fixtures.jmx(
                fixtures.thread_group(
                    "Main", threads=5, ramp=10,
                    children="\n".join(
                        [
                            fixtures.http_sampler("a", path="/x?g=${ghost}"),
                            fixtures.element("com.example.Strange", "odd"),
                        ]
                    ),
                )
            )
        )
        text = jmx_parser.render_inventory(ir)
        self.assertIn("# JMX Inventory — plan.jmx", text)
        self.assertIn("## Elements", text)
        self.assertIn("| http_sampler | 1 |", text)
        self.assertIn("## Unsupported elements", text)
        self.assertIn("com.example.Strange", text)
        self.assertIn("## Thread groups", text)
        self.assertIn("| Main | standard | closed |", text)
        self.assertIn("## Data flow findings", text)
        self.assertIn("ghost", text)
        self.assertIn("## Complexity flags", text)
        self.assertIn("unknown-elements", text)

    def test_inventory_is_deterministic(self) -> None:
        document = fixtures.jmx(
            fixtures.thread_group("Main", children=fixtures.http_sampler("a"))
        )
        first = jmx_parser.render_inventory(self.parse(document))
        out_dir_2 = self.tmp / "out2"
        jmx_path = self.tmp / "plan.jmx"
        second = jmx_parser.render_inventory(jmx_parser.parse_jmx(jmx_path, out_dir_2))
        self.assertEqual(first, second)

    def test_pipe_in_thread_group_name_is_escaped(self) -> None:
        ir = self.parse(
            fixtures.jmx(
                fixtures.thread_group(
                    "Main | Checkout", children=fixtures.http_sampler("a")
                )
            )
        )
        text = jmx_parser.render_inventory(ir)
        self.assertIn("| Main \\| Checkout |", text)

    def test_needs_review_row_for_unnormalized_load(self) -> None:
        ir = self.parse(
            fixtures.jmx(
                plugin_thread_group(
                    "ThreadGroup", "ThreadGroupGui",
                    fixtures.string_prop("ThreadGroup.num_threads", "${THREADS}"),
                    name="Param",
                )
            )
        )
        text = jmx_parser.render_inventory(ir)
        self.assertIn("| Param | standard | ? | needs review | ? | parameterized thread count |", text)

    def test_open_ended_hold_renders_dash(self) -> None:
        ir = self.parse(
            fixtures.jmx(
                fixtures.thread_group("Main", threads=5, ramp=10, children=fixtures.http_sampler("a"))
            )
        )
        text = jmx_parser.render_inventory(ir)
        self.assertIn("5u ramp 10s hold -", text)


class CliTest(ParserCase):
    def write_plan(self) -> Path:
        jmx_path = self.tmp / "plan.jmx"
        jmx_path.write_text(
            fixtures.jmx(
                fixtures.thread_group("Main", children=fixtures.http_sampler("a"))
            ),
            encoding="utf-8",
        )
        return jmx_path

    def run_cli(self, *argv: str) -> tuple[int, str]:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = jmx_parser.main(list(argv))
        return code, buffer.getvalue()

    def test_parse_writes_artifacts(self) -> None:
        jmx_path = self.write_plan()
        code, output = self.run_cli(
            "parse", str(jmx_path), "--out-dir", str(self.out_dir), "--format", "json"
        )
        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertTrue((self.out_dir / "ir.json").is_file())
        self.assertTrue((self.out_dir / "inventory.md").is_file())
        self.assertEqual(payload["complexity_flags"], [])
        ir = json.loads((self.out_dir / "ir.json").read_text(encoding="utf-8"))
        self.assertEqual(ir["version"], 1)

    def test_parse_is_deterministic_byte_for_byte(self) -> None:
        jmx_path = self.write_plan()
        out_a, out_b = self.tmp / "a", self.tmp / "b"
        self.run_cli("parse", str(jmx_path), "--out-dir", str(out_a))
        self.run_cli("parse", str(jmx_path), "--out-dir", str(out_b))
        self.assertEqual(
            (out_a / "ir.json").read_bytes(), (out_b / "ir.json").read_bytes()
        )
        self.assertEqual(
            (out_a / "inventory.md").read_bytes(), (out_b / "inventory.md").read_bytes()
        )

    def test_parse_failure_is_blocking(self) -> None:
        broken = self.tmp / "broken.jmx"
        broken.write_text("<jmeterTestPlan><hashTree>", encoding="utf-8")
        code, output = self.run_cli(
            "parse", str(broken), "--out-dir", str(self.out_dir), "--format", "json"
        )
        self.assertEqual(code, 1)
        payload = json.loads(output)
        self.assertEqual(payload["blocking"][0]["rule"], "jmx-parser.parse-failed")
        self.assertEqual(payload["blocking"][0]["severity"], "blocking")

    def test_parse_text_format_prints_inventory_path(self) -> None:
        jmx_path = self.write_plan()
        code, output = self.run_cli(
            "parse", str(jmx_path), "--out-dir", str(self.out_dir), "--format", "text"
        )
        self.assertEqual(code, 0)
        self.assertTrue(output.strip().endswith("inventory.md"))

    def test_summary_and_element(self) -> None:
        jmx_path = self.write_plan()
        self.run_cli("parse", str(jmx_path), "--out-dir", str(self.out_dir))
        code, output = self.run_cli("summary", str(self.out_dir / "ir.json"))
        self.assertEqual(code, 0)
        self.assertIn("Main", output)
        code, output = self.run_cli("element", str(self.out_dir / "ir.json"), "e-0002")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["kind"], "http_sampler")
        code, _ = self.run_cli("element", str(self.out_dir / "ir.json"), "e-9999")
        self.assertEqual(code, 1)


@unittest.skipUnless(Draft202012Validator is not None, "jsonschema unavailable")
class IrSchemaTest(ParserCase):
    def validator(self) -> "Draft202012Validator":
        schema = json.loads(
            (REPO_ROOT / "schemas" / "jmx-ir.schema.json").read_text(encoding="utf-8")
        )
        return Draft202012Validator(schema)

    def test_fixture_ir_validates(self) -> None:
        ir = self.parse(
            fixtures.jmx(
                fixtures.thread_group(
                    "Main",
                    children="\n".join(
                        [
                            fixtures.http_sampler("a", method="POST", path="/x", body="b" * 5000),
                            fixtures.element("com.example.Strange", "odd"),
                        ]
                    ),
                )
            )
        )
        self.assertEqual(list(self.validator().iter_errors(ir)), [])

    def test_schema_rejects_element_without_id(self) -> None:
        ir = self.parse(fixtures.jmx(fixtures.thread_group("Main")))
        del ir["children"][0]["id"]
        self.assertTrue(list(self.validator().iter_errors(ir)))


if __name__ == "__main__":
    sys.exit(unittest.main())

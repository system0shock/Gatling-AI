#!/usr/bin/env python3
from __future__ import annotations
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ir_to_scenario
import fixtures


class SkeletonTest(unittest.TestCase):
    def test_emits_scenario_meta_from_args(self) -> None:
        doc = fixtures.ir([
            fixtures.thread_group(
                "Main", [fixtures.http_sampler("home", path="/")],
                {"model": "closed", "stages": [{"users": 5, "ramp_seconds": 10, "hold_seconds": 60}], "start_after_seconds": 0},
            )
        ])
        result = ir_to_scenario.convert(doc, system="SHOP", scenario_id="checkout-mix", number=1)
        scenario = result.scenario["scenario"]
        self.assertEqual(scenario["system"], "SHOP")
        self.assertEqual(scenario["id"], "checkout-mix")
        self.assertEqual(scenario["number"], 1)
        self.assertEqual(scenario["source"], {"type": "jmeter", "ref": "test.jmx"})

    def test_every_element_has_a_disposition(self) -> None:
        doc = fixtures.ir([
            fixtures.thread_group(
                "Main", [fixtures.http_sampler("home", path="/")],
                {"model": "closed", "stages": [{"users": 5, "ramp_seconds": 10, "hold_seconds": 60}], "start_after_seconds": 0},
            )
        ])
        result = ir_to_scenario.convert(doc, system="SHOP", scenario_id="demo", number=1)
        self.assertEqual(sum(result.disposition_counts().values()), doc["stats"]["elements_total"])


class LoadMappingTest(unittest.TestCase):
    def _convert(self, groups):
        return ir_to_scenario.convert(fixtures.ir(groups), system="SHOP", scenario_id="demo", number=1)

    def test_single_thread_group_is_single_flow(self) -> None:
        conv = self._convert([
            fixtures.thread_group("Main", [fixtures.http_sampler("home")],
                {"model": "closed", "stages": [{"users": 5, "ramp_seconds": 10, "hold_seconds": 60}], "start_after_seconds": 0})
        ])
        scenario = conv.scenario["scenario"]
        self.assertNotIn("populations", scenario)
        self.assertEqual(scenario["load"], {"model": "closed", "profile": "stages",
            "stages": [{"users": 5, "ramp_seconds": 10, "hold_seconds": 60}]})

    def test_two_thread_groups_become_populations(self) -> None:
        conv = self._convert([
            fixtures.thread_group("Main flow", [fixtures.http_sampler("home")],
                {"model": "closed", "stages": [{"users": 5, "ramp_seconds": 10, "hold_seconds": 60}], "start_after_seconds": 0}),
            fixtures.thread_group("Background", [fixtures.http_sampler("bg", path="/bg")],
                {"model": "open", "stages": [{"users_per_second": 2, "ramp_seconds": 5, "hold_seconds": 30}], "start_after_seconds": 120}),
        ])
        scenario = conv.scenario["scenario"]
        self.assertNotIn("load", scenario)
        names = [p["name"] for p in scenario["populations"]]
        self.assertEqual(names, ["main-flow", "background"])
        self.assertEqual(scenario["populations"][1]["start_after_seconds"], 120)

    def test_unnormalizable_load_blocks(self) -> None:
        conv = self._convert([
            fixtures.thread_group("Main", [fixtures.http_sampler("home")], None, note="parameterized thread count")
        ])
        rules = [f.rule for f in conv.findings]
        self.assertIn("convert.load-not-normalized", rules)

    def test_disabled_thread_group_recorded_not_dropped(self) -> None:
        on = fixtures.thread_group("Main", [fixtures.http_sampler("home")],
            {"model": "closed", "stages": [{"users": 1, "ramp_seconds": 0, "hold_seconds": 1}], "start_after_seconds": 0})
        off = fixtures.thread_group("Old", [fixtures.http_sampler("legacy", path="/old")],
            {"model": "closed", "stages": [{"users": 1, "ramp_seconds": 0, "hold_seconds": 1}], "start_after_seconds": 0})
        off["enabled"] = False
        doc = fixtures.ir([on, off])
        conv = ir_to_scenario.convert(doc, system="SHOP", scenario_id="demo", number=1)
        # disabled TG and its sampler are recorded (skipped), nothing dropped
        self.assertEqual(sum(conv.disposition_counts().values()), doc["stats"]["elements_total"])
        statuses = {r["id"]: r["status"] for r in conv.report_rows}
        self.assertEqual(statuses[off["id"]], "skipped-disabled")


class StructureWalkTest(unittest.TestCase):
    def _steps(self, conv):
        s = conv.scenario["scenario"]
        return s.get("steps") or s["populations"][0]["steps"]

    def test_samplers_become_steps_in_order(self) -> None:
        tg = fixtures.thread_group("Main",
            [fixtures.http_sampler("open-home", path="/"), fixtures.http_sampler("submit", method="POST", path="/submit")],
            {"model": "closed", "stages": [{"users": 1, "ramp_seconds": 0, "hold_seconds": 10}], "start_after_seconds": 0})
        conv = ir_to_scenario.convert(fixtures.ir([tg]), system="SHOP", scenario_id="demo", number=1)
        steps = self._steps(conv)
        self.assertEqual([s["name"] for s in steps], ["open-home", "submit"])
        self.assertEqual(steps[0]["transaction"], "01 demo.open-home - open-home")

    def test_transaction_controller_seeds_step_names(self) -> None:
        txn = fixtures.element("transaction", "Checkout",
            children=[fixtures.http_sampler("submit", method="POST", path="/checkout")])
        tg = fixtures.thread_group("Main", [txn],
            {"model": "closed", "stages": [{"users": 1, "ramp_seconds": 0, "hold_seconds": 10}], "start_after_seconds": 0})
        conv = ir_to_scenario.convert(fixtures.ir([tg]), system="SHOP", scenario_id="demo", number=1)
        steps = self._steps(conv)
        self.assertEqual(steps[0]["transaction"], "01 demo.checkout - submit")

    def test_if_controller_recorded_partial_but_child_converts(self) -> None:
        cond = fixtures.element("if", "only-prod", condition="${env}=='prod'",
            children=[fixtures.http_sampler("guarded", path="/g")])
        tg = fixtures.thread_group("Main", [cond],
            {"model": "closed", "stages": [{"users": 1, "ramp_seconds": 0, "hold_seconds": 10}], "start_after_seconds": 0})
        conv = ir_to_scenario.convert(fixtures.ir([tg]), system="SHOP", scenario_id="demo", number=1)
        statuses = {r["kind"]: r["status"] for r in conv.report_rows}
        self.assertEqual(statuses["if"], "partial")
        self.assertEqual(statuses["http_sampler"], "converted")
        self.assertEqual(len(self._steps(conv)), 1)


class HttpStepTest(unittest.TestCase):
    def _one_step(self, sampler, extra_children=None):
        children = [sampler] + (extra_children or [])
        tg = fixtures.thread_group("Main", children,
            {"model": "closed", "stages": [{"users": 1, "ramp_seconds": 0, "hold_seconds": 10}], "start_after_seconds": 0})
        conv = ir_to_scenario.convert(fixtures.ir([tg]), system="SHOP", scenario_id="demo", number=1)
        s = conv.scenario["scenario"]
        return (s.get("steps") or s["populations"][0]["steps"])[0], conv

    def test_method_and_path(self) -> None:
        step, _ = self._one_step(fixtures.http_sampler("home", method="GET", path="/home"))
        self.assertEqual(step["request"]["method"], "GET")
        self.assertEqual(step["request"]["path"], "/home")

    def test_inline_body(self) -> None:
        sampler = fixtures.http_sampler("post", method="POST", path="/p",
            body={"variables": ["id"], "inline": '{"id":"${id}"}'})
        step, _ = self._one_step(sampler)
        self.assertEqual(step["request"]["body"], '{"id":"${id}"}')

    def test_external_body_becomes_body_file(self) -> None:
        sampler = fixtures.http_sampler("post", method="POST", path="/p",
            body={"variables": [], "ref": "bodies/abc123.json"})
        step, _ = self._one_step(sampler)
        self.assertEqual(step["request"]["body_file"], "bodies/abc123.json")
        self.assertNotIn("body", step["request"])

    def test_headers_from_sibling_manager(self) -> None:
        hm = fixtures.element("header_manager", "hdrs", headers={"Accept": "application/json"})
        step, _ = self._one_step(fixtures.http_sampler("home", path="/"), [hm])
        self.assertEqual(step["request"]["headers"], {"Accept": "application/json"})

    def test_form_params_recorded_partial(self) -> None:
        sampler = fixtures.http_sampler("form", method="POST", path="/f",
            params=[{"name": "a", "value": "1"}])
        step, conv = self._one_step(sampler)
        statuses = [r for r in conv.report_rows if r["id"] == sampler["id"]]
        self.assertEqual(statuses[0]["status"], "partial")
        self.assertIn("form params", statuses[0]["note"])


class ChecksTest(unittest.TestCase):
    def _step(self, sampler_children):
        sampler = fixtures.http_sampler("home", path="/")
        sampler["children"] = sampler_children
        tg = fixtures.thread_group("Main", [sampler],
            {"model": "closed", "stages": [{"users": 1, "ramp_seconds": 0, "hold_seconds": 10}], "start_after_seconds": 0})
        conv = ir_to_scenario.convert(fixtures.ir([tg]), system="SHOP", scenario_id="demo", number=1)
        s = conv.scenario["scenario"]
        return (s.get("steps") or s["populations"][0]["steps"])[0], conv

    def test_default_status_check_when_no_assertion(self) -> None:
        step, _ = self._step([])
        self.assertIn({"status": 200}, step["checks"])

    def test_regex_extractor_becomes_extract_check(self) -> None:
        ex = fixtures.element("regex_extractor", "csrf", variable="csrf",
            regex="name=csrf value=(.+?)", template="$1$", match_number="1", default="NF")
        step, conv = self._step([ex])
        extracts = [c for c in step["checks"] if "extract" in c]
        self.assertEqual(extracts[0]["extract"], {"type": "regex", "expr": "name=csrf value=(.+?)", "saveAs": "csrf"})

    def test_jsonpath_extractor_multi(self) -> None:
        ex = fixtures.element("jsonpath_extractor", "ids",
            extracts=[{"variable": "orderId", "expr": "$.id", "match_number": "1", "default": ""}])
        step, _ = self._step([ex])
        extracts = [c["extract"] for c in step["checks"] if "extract" in c]
        self.assertIn({"type": "jsonPath", "expr": "$.id", "saveAs": "orderId"}, extracts)

    def test_response_assertion_status(self) -> None:
        a = fixtures.element("response_assertion", "code", field="Assertion.response_code",
            test_type=8, patterns=["200"])
        step, conv = self._step([a])
        self.assertIn({"status": 200}, step["checks"])
        statuses = {r["id"]: r["status"] for r in conv.report_rows}
        self.assertEqual(statuses[a["id"]], "converted")

    def test_multi_pattern_status_recorded_partial(self) -> None:
        # JMeter ORs the patterns; scenario status checks AND -> partial for review.
        a = fixtures.element("response_assertion", "code", field="Assertion.response_code",
            test_type=8, patterns=["200", "201"])
        step, conv = self._step([a])
        self.assertIn({"status": 200}, step["checks"])
        self.assertIn({"status": 201}, step["checks"])
        statuses = {r["id"]: r["status"] for r in conv.report_rows}
        self.assertEqual(statuses[a["id"]], "partial")

    def test_non_numeric_response_code_recorded_partial(self) -> None:
        a = fixtures.element("response_assertion", "code", field="Assertion.response_code",
            test_type=8, patterns=["2xx"])
        step, conv = self._step([a])
        statuses = {r["id"]: r["status"] for r in conv.report_rows}
        self.assertEqual(statuses[a["id"]], "partial")

    def test_boundary_extractor_recorded_partial(self) -> None:
        ex = fixtures.element("boundary_extractor", "token", variable="token",
            left="token=", right="&", match_number="1", default="NF")
        step, conv = self._step([ex])
        rows = [r for r in conv.report_rows if r["id"] == ex["id"]]
        self.assertEqual(rows[0]["status"], "partial")

    def test_non_status_assertion_recorded_partial(self) -> None:
        a = fixtures.element("response_assertion", "body-check", field="Assertion.response_data",
            test_type=2, patterns=["OK"])
        step, conv = self._step([a])
        rows = [r for r in conv.report_rows if r["id"] == a["id"]]
        self.assertEqual(rows[0]["status"], "partial")

    def test_disabled_child_recorded_skipped(self) -> None:
        ex = fixtures.element("regex_extractor", "csrf", variable="csrf",
            regex="(.+)", template="$1$", match_number="1", default="NF")
        ex["enabled"] = False
        step, conv = self._step([ex])
        rows = [r for r in conv.report_rows if r["id"] == ex["id"]]
        self.assertEqual(rows[0]["status"], "skipped-disabled")

    def test_sampler_children_not_double_recorded(self) -> None:
        """Each extractor/assertion child must be recorded exactly once."""
        ex = fixtures.element("regex_extractor", "csrf", variable="csrf",
            regex="(.+)", template="$1$", match_number="1", default="NF")
        sampler = fixtures.http_sampler("home", path="/")
        sampler["children"] = [ex]
        tg = fixtures.thread_group("Main", [sampler],
            {"model": "closed", "stages": [{"users": 1, "ramp_seconds": 0, "hold_seconds": 10}], "start_after_seconds": 0})
        doc = fixtures.ir([tg])
        conv = ir_to_scenario.convert(doc, system="SHOP", scenario_id="demo", number=1)
        # total recorded == total elements in IR (no double-count, no drop)
        self.assertEqual(sum(conv.disposition_counts().values()), doc["stats"]["elements_total"])
        # extractor recorded exactly once
        ex_rows = [r for r in conv.report_rows if r["id"] == ex["id"]]
        self.assertEqual(len(ex_rows), 1)


class FeederEnvTest(unittest.TestCase):
    def _convert(self, children):
        tg = fixtures.thread_group("Main", [fixtures.http_sampler("home", path="/")],
            {"model": "closed", "stages": [{"users": 1, "ramp_seconds": 0, "hold_seconds": 10}], "start_after_seconds": 0})
        tg["children"] = children + tg["children"]
        return ir_to_scenario.convert(fixtures.ir([tg]), system="SHOP", scenario_id="demo", number=1)

    def test_csv_becomes_feeder(self) -> None:
        csv = fixtures.element("csv_data_set", "users",
            file="users.csv", variable_names=["username", "password"], delimiter=",", recycle=True, stop_thread=False, share_mode="all")
        conv = self._convert([csv])
        feeders = conv.scenario["scenario"]["data"]["feeders"]
        self.assertEqual(feeders[0]["file"], "users.csv")
        self.assertEqual(feeders[0]["strategy"], "circular")

    def test_csv_stop_thread_is_queue(self) -> None:
        csv = fixtures.element("csv_data_set", "ids",
            file="ids.csv", variable_names=["id"], delimiter=",", recycle=False, stop_thread=True, share_mode="all")
        conv = self._convert([csv])
        self.assertEqual(conv.scenario["scenario"]["data"]["feeders"][0]["strategy"], "queue")

    def test_base_url_from_udv(self) -> None:
        udv = fixtures.element("user_defined_variables", "globals", values={"BASE_URL": "https://sut.example.com", "tenant": "acme"})
        conv = self._convert([udv])
        self.assertEqual(conv.scenario["scenario"]["sut"]["base_url"], "${BASE_URL}")
        rows = [r for r in conv.report_rows if r["id"] == udv["id"]]
        self.assertEqual(rows[0]["status"], "converted")

    def test_csv_no_variable_names_is_partial(self) -> None:
        csv = fixtures.element("csv_data_set", "data",
            file="data.csv", variable_names=None, delimiter=",", recycle=True, stop_thread=False, share_mode="all")
        conv = self._convert([csv])
        feeders = conv.scenario["scenario"]["data"]["feeders"]
        self.assertEqual(len(feeders), 1)
        rows = [r for r in conv.report_rows if r["id"] == csv["id"]]
        self.assertEqual(rows[0]["status"], "partial")

    def test_disabled_csv_not_emitted_but_recorded(self) -> None:
        csv = fixtures.element("csv_data_set", "users",
            file="users.csv", variable_names=["u"], delimiter=",", recycle=True, stop_thread=False, share_mode="all")
        csv["enabled"] = False
        doc = fixtures.ir([fixtures.thread_group("Main", [csv, fixtures.http_sampler("home", path="/")],
            {"model": "closed", "stages": [{"users": 1, "ramp_seconds": 0, "hold_seconds": 10}], "start_after_seconds": 0})])
        conv = ir_to_scenario.convert(doc, system="SHOP", scenario_id="demo", number=1)
        # No feeder emitted for disabled CSV
        self.assertNotIn("data", conv.scenario["scenario"])
        # But the element IS recorded (skipped-disabled), so counts reconcile
        self.assertEqual(sum(conv.disposition_counts().values()), doc["stats"]["elements_total"])
        rows = [r for r in conv.report_rows if r["id"] == csv["id"]]
        self.assertEqual(rows[0]["status"], "skipped-disabled")

    def test_csv_and_udv_not_double_recorded(self) -> None:
        """CSV and UDV recorded exactly once; total disposition == elements_total."""
        csv = fixtures.element("csv_data_set", "users",
            file="users.csv", variable_names=["u"], delimiter=",", recycle=True, stop_thread=False, share_mode="all")
        udv = fixtures.element("user_defined_variables", "env", values={"BASE_URL": "http://localhost"})
        tg = fixtures.thread_group("Main", [csv, udv, fixtures.http_sampler("home", path="/")],
            {"model": "closed", "stages": [{"users": 1, "ramp_seconds": 0, "hold_seconds": 10}], "start_after_seconds": 0})
        doc = fixtures.ir([tg])
        conv = ir_to_scenario.convert(doc, system="SHOP", scenario_id="demo", number=1)
        self.assertEqual(sum(conv.disposition_counts().values()), doc["stats"]["elements_total"])
        # Each recorded exactly once
        csv_rows = [r for r in conv.report_rows if r["id"] == csv["id"]]
        udv_rows = [r for r in conv.report_rows if r["id"] == udv["id"]]
        self.assertEqual(len(csv_rows), 1)
        self.assertEqual(len(udv_rows), 1)

    def test_feeder_name_is_kebab_of_element_name(self) -> None:
        csv = fixtures.element("csv_data_set", "User Credentials",
            file="creds.csv", variable_names=["u", "p"], delimiter=",", recycle=True, stop_thread=False, share_mode="all")
        conv = self._convert([csv])
        feeders = conv.scenario["scenario"]["data"]["feeders"]
        self.assertEqual(feeders[0]["name"], "user-credentials")

    def test_feeder_name_falls_back_to_file_stem(self) -> None:
        csv = fixtures.element("csv_data_set", "",
            file="test_data/my-users.csv", variable_names=["u"], delimiter=",", recycle=True, stop_thread=False, share_mode="all")
        conv = self._convert([csv])
        feeders = conv.scenario["scenario"]["data"]["feeders"]
        self.assertEqual(feeders[0]["name"], "my-users")


class TimersCountersTest(unittest.TestCase):
    def _convert(self, tg_children):
        tg = fixtures.thread_group("Main", tg_children,
            {"model": "closed", "stages": [{"users": 1, "ramp_seconds": 0, "hold_seconds": 10}], "start_after_seconds": 0})
        return ir_to_scenario.convert(fixtures.ir([tg]), system="SHOP", scenario_id="demo", number=1)

    def test_constant_timer_becomes_pause_on_prior_step(self) -> None:
        conv = self._convert([
            fixtures.http_sampler("home", path="/"),
            fixtures.element("constant_timer", "wait", delay_ms="2000"),
            fixtures.http_sampler("next", path="/n"),
        ])
        s = conv.scenario["scenario"]
        steps = s.get("steps") or s["populations"][0]["steps"]
        self.assertEqual(steps[0]["pause_seconds"], 2)

    def test_counter_recorded_partial(self) -> None:
        conv = self._convert([fixtures.element("counter", "c", variable="n", start="1", increment="1", per_user=True),
                              fixtures.http_sampler("home", path="/")])
        rows = {r["kind"]: r["status"] for r in conv.report_rows}
        self.assertEqual(rows["counter"], "partial")

    def test_timer_with_no_prior_step_recorded_partial(self) -> None:
        """A timer that has no preceding step is recorded PARTIAL, not CONVERTED."""
        conv = self._convert([
            fixtures.element("constant_timer", "early", delay_ms="1000"),
            fixtures.http_sampler("home", path="/"),
        ])
        rows = {r["kind"]: r["status"] for r in conv.report_rows}
        self.assertEqual(rows["constant_timer"], "partial")

    def test_timer_zero_delay_recorded_partial(self) -> None:
        """A timer with delay_ms=0 produces no pause; recorded PARTIAL."""
        conv = self._convert([
            fixtures.http_sampler("home", path="/"),
            fixtures.element("constant_timer", "zero", delay_ms="0"),
        ])
        rows = {r["kind"]: r["status"] for r in conv.report_rows}
        self.assertEqual(rows["constant_timer"], "partial")

    def test_timer_fractional_seconds_emits_float(self) -> None:
        """1500 ms -> 1.5 (float, not int)."""
        conv = self._convert([
            fixtures.http_sampler("home", path="/"),
            fixtures.element("constant_timer", "half", delay_ms="1500"),
        ])
        s = conv.scenario["scenario"]
        steps = s.get("steps") or s["populations"][0]["steps"]
        self.assertEqual(steps[0]["pause_seconds"], 1.5)
        self.assertIsInstance(steps[0]["pause_seconds"], float)

    def test_timer_integral_seconds_emits_int(self) -> None:
        """2000 ms -> 2 (int, not 2.0)."""
        conv = self._convert([
            fixtures.http_sampler("home", path="/"),
            fixtures.element("constant_timer", "two-sec", delay_ms="2000"),
        ])
        s = conv.scenario["scenario"]
        steps = s.get("steps") or s["populations"][0]["steps"]
        self.assertIsInstance(steps[0]["pause_seconds"], int)
        self.assertEqual(steps[0]["pause_seconds"], 2)

    def test_random_variable_recorded_partial(self) -> None:
        conv = self._convert([
            fixtures.element("random_variable", "rv", variable="rnd", minimum="1", maximum="10", per_thread=True),
            fixtures.http_sampler("home", path="/"),
        ])
        rows = {r["kind"]: r["status"] for r in conv.report_rows}
        self.assertEqual(rows["random_variable"], "partial")

    def test_timer_and_counter_not_double_recorded(self) -> None:
        """Timer and counter must not also appear in record_non_step_element path."""
        timer = fixtures.element("constant_timer", "wait", delay_ms="1000")
        counter = fixtures.element("counter", "c", variable="n", start="1", increment="1", per_user=True)
        tg_children = [
            fixtures.http_sampler("home", path="/"),
            timer,
            counter,
        ]
        tg = fixtures.thread_group("Main", tg_children,
            {"model": "closed", "stages": [{"users": 1, "ramp_seconds": 0, "hold_seconds": 10}], "start_after_seconds": 0})
        doc = fixtures.ir([tg])
        conv = ir_to_scenario.convert(doc, system="SHOP", scenario_id="demo", number=1)
        self.assertEqual(sum(conv.disposition_counts().values()), doc["stats"]["elements_total"])
        timer_rows = [r for r in conv.report_rows if r["id"] == timer["id"]]
        counter_rows = [r for r in conv.report_rows if r["id"] == counter["id"]]
        self.assertEqual(len(timer_rows), 1)
        self.assertEqual(len(counter_rows), 1)

    def test_uniform_random_timer_attaches_pause(self) -> None:
        """uniform_random_timer with offset_ms=3000 -> pause_seconds=3 on prior step."""
        conv = self._convert([
            fixtures.http_sampler("home", path="/"),
            fixtures.element("uniform_random_timer", "rnd", offset_ms="3000", range_ms="1000"),
        ])
        s = conv.scenario["scenario"]
        steps = s.get("steps") or s["populations"][0]["steps"]
        self.assertEqual(steps[0]["pause_seconds"], 3)


class JsrJdbcTest(unittest.TestCase):
    def _convert(self, tg_children):
        tg = fixtures.thread_group("Main", tg_children,
            {"model": "closed", "stages": [{"users": 1, "ramp_seconds": 0, "hold_seconds": 10}], "start_after_seconds": 0})
        return ir_to_scenario.convert(fixtures.ir([tg]), system="SHOP", scenario_id="demo", number=1)

    def test_jsr223_post_becomes_after_todo_hook(self) -> None:
        sampler = fixtures.http_sampler("home", path="/")
        sampler["children"] = [fixtures.element("jsr223_post", "sign", language="groovy",
            reads=["user"], writes=["sig"], props_reads=[], props_writes=[],
            classification="complex", classification_reasons=["uses props"], script_ref="jsr223/abc.groovy", script_preview="...")]
        conv = self._convert([sampler])
        s = conv.scenario["scenario"]
        step = (s.get("steps") or s["populations"][0]["steps"])[0]
        hook = step["hooks"]["after"][0]
        self.assertEqual(hook["kind"], "todo")
        self.assertEqual(hook["ref"], "jsr223/abc.groovy")
        self.assertEqual(hook["writes"], ["sig"])

    def test_jsr223_pre_becomes_before_todo_hook(self) -> None:
        sampler = fixtures.http_sampler("home", path="/")
        sampler["children"] = [fixtures.element("jsr223_pre", "setup", language="groovy",
            reads=[], writes=["token"], props_reads=[], props_writes=[],
            classification="typical", classification_reasons=[], script_ref="jsr223/setup.groovy", script_preview="def token=...")]
        conv = self._convert([sampler])
        s = conv.scenario["scenario"]
        step = (s.get("steps") or s["populations"][0]["steps"])[0]
        hook = step["hooks"]["before"][0]
        self.assertEqual(hook["kind"], "todo")
        self.assertEqual(hook["ref"], "jsr223/setup.groovy")
        self.assertEqual(hook["summary"], "setup")

    def test_jsr223_hook_reads_writes_omitted_when_empty(self) -> None:
        """reads/writes must be absent (not []) when the IR lists no reads or writes."""
        sampler = fixtures.http_sampler("home", path="/")
        sampler["children"] = [fixtures.element("jsr223_post", "cleanup", language="groovy",
            reads=[], writes=[], props_reads=[], props_writes=[],
            classification="typical", classification_reasons=[], script_ref="jsr223/cleanup.groovy", script_preview="log.info('done')")]
        conv = self._convert([sampler])
        s = conv.scenario["scenario"]
        step = (s.get("steps") or s["populations"][0]["steps"])[0]
        hook = step["hooks"]["after"][0]
        self.assertNotIn("reads", hook)
        self.assertNotIn("writes", hook)

    def test_jsr223_hook_uses_script_file_fallback(self) -> None:
        """When script_ref is absent, script_file is used as ref."""
        sampler = fixtures.http_sampler("home", path="/")
        sampler["children"] = [fixtures.element("jsr223_pre", "load-token", language="groovy",
            reads=[], writes=["token"], props_reads=[], props_writes=[],
            classification="typical", classification_reasons=[], script_file="scripts/load-token.groovy", script_preview="")]
        conv = self._convert([sampler])
        s = conv.scenario["scenario"]
        step = (s.get("steps") or s["populations"][0]["steps"])[0]
        hook = step["hooks"]["before"][0]
        self.assertEqual(hook["ref"], "scripts/load-token.groovy")

    def test_jsr223_hook_summary_falls_back_to_preview(self) -> None:
        """When name is empty, summary is first 60 chars of script_preview."""
        sampler = fixtures.http_sampler("home", path="/")
        sampler["children"] = [fixtures.element("jsr223_post", "", language="groovy",
            reads=[], writes=[], props_reads=[], props_writes=[],
            classification="typical", classification_reasons=[], script_ref="jsr223/x.groovy", script_preview="log.info('hello world')")]
        conv = self._convert([sampler])
        s = conv.scenario["scenario"]
        step = (s.get("steps") or s["populations"][0]["steps"])[0]
        hook = step["hooks"]["after"][0]
        self.assertEqual(hook["summary"], "log.info('hello world')")

    def test_jsr223_processor_recorded_converted_exactly_once(self) -> None:
        """jsr223_pre/post is recorded CONVERTED exactly once (not via record_non_step_element)."""
        sampler = fixtures.http_sampler("home", path="/")
        post = fixtures.element("jsr223_post", "sign", language="groovy",
            reads=["user"], writes=["sig"], props_reads=[], props_writes=[],
            classification="complex", classification_reasons=[], script_ref="jsr223/abc.groovy", script_preview="")
        sampler["children"] = [post]
        tg = fixtures.thread_group("Main", [sampler],
            {"model": "closed", "stages": [{"users": 1, "ramp_seconds": 0, "hold_seconds": 10}], "start_after_seconds": 0})
        doc = fixtures.ir([tg])
        conv = ir_to_scenario.convert(doc, system="SHOP", scenario_id="demo", number=1)
        # disposition count must match IR total (no double-count / no drop)
        self.assertEqual(sum(conv.disposition_counts().values()), doc["stats"]["elements_total"])
        # jsr223_post recorded exactly once as converted
        post_rows = [r for r in conv.report_rows if r["id"] == post["id"]]
        self.assertEqual(len(post_rows), 1)
        self.assertEqual(post_rows[0]["status"], "converted")

    def test_jdbc_sampler_becomes_jdbc_stub(self) -> None:
        conv = self._convert([fixtures.element("jdbc_sampler", "lookup", query="SELECT 1", query_type="Select Statement", data_source="ds")])
        s = conv.scenario["scenario"]
        step = (s.get("steps") or s["populations"][0]["steps"])[0]
        self.assertEqual(step["protocol"], "jdbc")
        self.assertEqual(step["jdbc"]["query"], "SELECT 1")

    def test_jdbc_sampler_recorded_partial(self) -> None:
        """jdbc_sampler produces a PARTIAL disposition (stub until protocol spike)."""
        sampler = fixtures.element("jdbc_sampler", "lookup", query="SELECT id FROM users", query_type="Select Statement", data_source="ds")
        tg = fixtures.thread_group("Main", [sampler],
            {"model": "closed", "stages": [{"users": 1, "ramp_seconds": 0, "hold_seconds": 10}], "start_after_seconds": 0})
        doc = fixtures.ir([tg])
        conv = ir_to_scenario.convert(doc, system="SHOP", scenario_id="demo", number=1)
        rows = [r for r in conv.report_rows if r["id"] == sampler["id"]]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "partial")

    def test_jdbc_sampler_no_checks_field(self) -> None:
        """jdbc steps must NOT have a 'checks' key (schema variant has no checks)."""
        conv = self._convert([fixtures.element("jdbc_sampler", "q", query="SELECT 1", query_type="Select Statement", data_source="ds")])
        s = conv.scenario["scenario"]
        step = (s.get("steps") or s["populations"][0]["steps"])[0]
        self.assertNotIn("checks", step)

    def test_standalone_jsr223_sampler_returns_none_and_recorded_todo(self) -> None:
        """A standalone jsr223_sampler cannot become a contract step; recorded TODO, no step emitted."""
        sampler = fixtures.element("jsr223_sampler", "compute", language="groovy",
            reads=["id"], writes=["result"], props_reads=[], props_writes=[],
            classification="complex", classification_reasons=["side effects"], script_ref="jsr223/compute.groovy", script_preview="")
        tg = fixtures.thread_group("Main", [sampler],
            {"model": "closed", "stages": [{"users": 1, "ramp_seconds": 0, "hold_seconds": 10}], "start_after_seconds": 0})
        doc = fixtures.ir([tg])
        conv = ir_to_scenario.convert(doc, system="SHOP", scenario_id="demo", number=1)
        # No steps emitted for a standalone jsr223_sampler
        s = conv.scenario["scenario"]
        steps = s.get("steps") or []
        self.assertEqual(len(steps), 0)
        # recorded exactly once as todo
        rows = [r for r in conv.report_rows if r["id"] == sampler["id"]]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "todo")
        # disposition total still reconciles
        self.assertEqual(sum(conv.disposition_counts().values()), doc["stats"]["elements_total"])

    def test_standalone_jsr223_sampler_does_not_affect_http_step(self) -> None:
        """A jsr223_sampler mixed with an http_sampler: only the http step is emitted."""
        jsr = fixtures.element("jsr223_sampler", "compute", language="groovy",
            reads=[], writes=["x"], props_reads=[], props_writes=[],
            classification="typical", classification_reasons=[], script_ref="jsr223/x.groovy", script_preview="")
        http = fixtures.http_sampler("home", path="/")
        tg = fixtures.thread_group("Main", [jsr, http],
            {"model": "closed", "stages": [{"users": 1, "ramp_seconds": 0, "hold_seconds": 10}], "start_after_seconds": 0})
        doc = fixtures.ir([tg])
        conv = ir_to_scenario.convert(doc, system="SHOP", scenario_id="demo", number=1)
        s = conv.scenario["scenario"]
        steps = s.get("steps") or s["populations"][0]["steps"]
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]["protocol"], "http")
        # All elements accounted for
        self.assertEqual(sum(conv.disposition_counts().values()), doc["stats"]["elements_total"])

    def test_both_pre_and_post_hooks_on_same_step(self) -> None:
        """jsr223_pre and jsr223_post both attached to the same http step."""
        sampler = fixtures.http_sampler("home", path="/")
        pre = fixtures.element("jsr223_pre", "setup", language="groovy",
            reads=[], writes=["authToken"], props_reads=[], props_writes=[],
            classification="typical", classification_reasons=[], script_ref="jsr223/setup.groovy", script_preview="")
        post = fixtures.element("jsr223_post", "teardown", language="groovy",
            reads=["authToken"], writes=[], props_reads=[], props_writes=[],
            classification="typical", classification_reasons=[], script_ref="jsr223/teardown.groovy", script_preview="")
        sampler["children"] = [pre, post]
        conv = self._convert([sampler])
        s = conv.scenario["scenario"]
        step = (s.get("steps") or s["populations"][0]["steps"])[0]
        self.assertIn("before", step["hooks"])
        self.assertIn("after", step["hooks"])
        self.assertEqual(step["hooks"]["before"][0]["ref"], "jsr223/setup.groovy")
        self.assertEqual(step["hooks"]["after"][0]["ref"], "jsr223/teardown.groovy")


if __name__ == "__main__":
    sys.exit(unittest.main())

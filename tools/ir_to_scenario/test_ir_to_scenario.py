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
        step, _ = self._step([a])
        self.assertIn({"status": 200}, step["checks"])

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


if __name__ == "__main__":
    sys.exit(unittest.main())

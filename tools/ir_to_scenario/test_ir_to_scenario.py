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


if __name__ == "__main__":
    sys.exit(unittest.main())

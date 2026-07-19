#!/usr/bin/env python3
"""Tests for the deterministic methodology quality gate."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
TEST_TEMP_ROOT = Path(__file__).resolve().parent / ".test-fixtures-2"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import methodology_quality_gate as gate
from methodology_evidence.reconcile import REQUIRED_MNT_SECTIONS
from methodology_quality_gate.fixtures import HEADINGS, NO_DATA, write_gate_fixture


class MethodologyGateTest(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TEMP_ROOT.mkdir(exist_ok=True)
        self.root = TEST_TEMP_ROOT
        self._clear_test_root()

    def tearDown(self) -> None:
        self._clear_test_root()

    def _clear_test_root(self) -> None:
        for path in self.root.iterdir():
            if path.is_file():
                path.unlink()
    def assert_rule(self, report, rule: str, severity: str = "blocking") -> None:
        self.assertTrue(any(item.rule == rule and item.severity == severity for item in report.findings))

    def test_fixture_uses_the_canonical_17_utf8_headings(self) -> None:
        self.assertEqual(HEADINGS, tuple(heading for heading, _ in REQUIRED_MNT_SECTIONS))
        self.assertEqual(len(HEADINGS), 17)
        self.assertEqual(NO_DATA, "Нет подтвержденных данных.")

    def test_missing_required_section_blocks(self) -> None:
        report = gate.run_gate(**write_gate_fixture(self.root, omit="Архитектура"))
        self.assertEqual(report.status, "blocked")
        self.assert_rule(report, "required-section")

    def test_sla_without_source_map_entry_blocks(self) -> None:
        report = gate.run_gate(
            **write_gate_fixture(self.root, sla="p95 <= 500 ms", source_map={})
        )
        self.assert_rule(report, "sla-source")

    def test_secret_like_value_blocks_without_echoing_value(self) -> None:
        secret = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig"
        report = gate.run_gate(**write_gate_fixture(self.root, extra=secret))
        self.assert_rule(report, "secret-detection")
        self.assertTrue(all(secret not in finding.message for finding in report.findings))

    def test_scenario_data_section_blocks_scope_leak(self) -> None:
        report = gate.run_gate(
            **write_gate_fixture(self.root, extra="users.csv: login,password")
        )
        self.assert_rule(report, "artifact-boundary")

    def test_all_remaining_contract_checks_block_their_invalid_input(self) -> None:
        cases = (
            ("placeholder-scan", lambda p: p["candidate"].write_text(p["candidate"].read_text(encoding="utf-8") + "TODO\n", encoding="utf-8")),
            ("source-map-schema", lambda p: p["source_map"].write_text("{}", encoding="utf-8")),
            ("endpoint-source", lambda p: self._claim_and_unmap(p, "интерфейсов")),
            ("integration-source", lambda p: self._claim_and_unmap(p, "интеграций")),
            ("blocking-conflicts", lambda p: p["resolved_evidence"].write_text(json.dumps({"blocking_gaps": [{"rule": "conflict"}]}), encoding="utf-8")),
            ("module-coverage", lambda p: self._mark_coverage_partial(p)),
            ("patch-scope", lambda p: p["patch"].write_text("--- outside.md\n+++ outside.md\n", encoding="utf-8")),
            ("snapshot-freshness", lambda p: self._mark_snapshot_stale(p)),
        )
        for rule, mutate in cases:
            with self.subTest(rule=rule):
                paths = write_gate_fixture(self.root)
                mutate(paths)
                self.assert_rule(gate.run_gate(**paths), rule)

    def test_placeholder_metavariables_and_no_data_are_allowed(self) -> None:
        report = gate.run_gate(
            **write_gate_fixture(self.root, extra="<SYSTEM> <RUN-ID> <MODULE-ID>")
        )
        self.assertEqual(report.status, "passed")

    def test_warning_status_has_exit_code_one(self) -> None:
        report = gate.GateReport(
            "passed_with_warnings", (gate.Finding("advisory", "review", "warning"),), ()
        )
        self.assertEqual(gate.exit_code_for(report), 1)

    def test_reports_are_schema_shaped_and_redact_secret_findings(self) -> None:
        paths = write_gate_fixture(
            self.root, extra="api_key: a-secret-value-that-must-not-be-reported"
        )
        report = gate.run_gate(**paths)
        outputs = gate.write_reports(report, paths["candidate"], self.root)
        payload = json.loads(outputs["json"].read_text(encoding="utf-8"))
        self.assertEqual(set(payload), {"version", "status", "candidate", "candidate_sha256", "checks", "findings", "generated_at"})
        self.assertEqual(payload["status"], "blocked")
        self.assertNotIn("a-secret-value", outputs["markdown"].read_text(encoding="utf-8"))

    def test_cli_writes_reports_and_returns_blocked_exit_code(self) -> None:
        paths = write_gate_fixture(self.root, omit="Архитектура")
        completed = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).with_name("methodology_quality_gate.py")),
                "--candidate", str(paths["candidate"]),
                "--resolved-evidence", str(paths["resolved_evidence"]),
                "--coverage", str(paths["coverage"]),
                "--source-map", str(paths["source_map"]),
                "--base", str(paths["base"]),
                "--patch", str(paths["patch"]),
                "--out-dir", str(self.root),
            ],
            capture_output=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(completed.returncode, 2, completed.stderr)
        self.assertTrue((self.root / "methodology-quality-report.json").is_file())
        self.assertTrue((self.root / "methodology-quality-report.md").is_file())

    def _claim_and_unmap(self, paths: dict[str, Path], fragment: str) -> None:
        heading = next(heading for heading in HEADINGS if fragment in heading)
        text = paths["candidate"].read_text(encoding="utf-8")
        paths["candidate"].write_text(text.replace(NO_DATA, "claim", 1 if heading == HEADINGS[0] else 0), encoding="utf-8")
        marker = f"## {heading}\n\n{NO_DATA}"
        paths["candidate"].write_text(text.replace(marker, f"## {heading}\n\nclaim"), encoding="utf-8")
        source_map = json.loads(paths["source_map"].read_text(encoding="utf-8"))
        source_map["sections"][heading] = []
        paths["source_map"].write_text(json.dumps(source_map), encoding="utf-8")

    def _mark_coverage_partial(self, paths: dict[str, Path]) -> None:
        coverage = json.loads(paths["coverage"].read_text(encoding="utf-8"))
        coverage["sections"][HEADINGS[0]] = "partial"
        paths["coverage"].write_text(json.dumps(coverage), encoding="utf-8")

    def _mark_snapshot_stale(self, paths: dict[str, Path]) -> None:
        source_map = json.loads(paths["source_map"].read_text(encoding="utf-8"))
        source_map["workspace_snapshot"] = {"stale": True}
        paths["source_map"].write_text(json.dumps(source_map), encoding="utf-8")


    def test_source_map_rejects_unknown_or_malformed_evidence_ids(self) -> None:
        paths = write_gate_fixture(self.root)
        source_map = json.loads(paths["source_map"].read_text(encoding="utf-8"))
        source_map["sections"][HEADINGS[0]] = ["unknown.evidence.id"]
        paths["source_map"].write_text(json.dumps(source_map), encoding="utf-8")
        self.assert_rule(gate.run_gate(**paths), "source-map-schema")

    def test_coverage_rejects_missing_extra_or_malformed_contract_keys(self) -> None:
        for mutation in ("missing", "extra", "bad-status", "bad-version"):
            with self.subTest(mutation=mutation):
                paths = write_gate_fixture(self.root)
                coverage = json.loads(paths["coverage"].read_text(encoding="utf-8"))
                if mutation == "missing":
                    del coverage["sections"][HEADINGS[0]]
                elif mutation == "extra":
                    coverage["sections"]["attacker supplied"] = "covered"
                elif mutation == "bad-status":
                    coverage["sections"][HEADINGS[0]] = "complete"
                else:
                    coverage["version"] = True
                paths["coverage"].write_text(json.dumps(coverage), encoding="utf-8")
                self.assert_rule(gate.run_gate(**paths), "module-coverage")

    def test_patch_requires_one_expected_pair_and_hunk(self) -> None:
        for patch in (
            "arbitrary text\n",
            "--- outside.md\n+++ outside.md\n@@ -1 +1 @@\n-old\n+new\n",
            "--- base.md\n+++ candidate.md\n",
        ):
            with self.subTest(patch=patch):
                paths = write_gate_fixture(self.root)
                paths["patch"].write_text(patch, encoding="utf-8")
                self.assert_rule(gate.run_gate(**paths), "patch-scope")

    def test_snapshot_contract_requires_immutable_fresh_identity(self) -> None:
        for snapshot in (
            {},
            {"version": 1, "snapshot_id": "not-a-hash", "fresh": True},
            {"version": 1, "snapshot_id": "a" * 64, "fresh": False},
        ):
            with self.subTest(snapshot=snapshot):
                paths = write_gate_fixture(self.root)
                source_map = json.loads(paths["source_map"].read_text(encoding="utf-8"))
                source_map["workspace_snapshot"] = snapshot
                paths["source_map"].write_text(json.dumps(source_map), encoding="utf-8")
                self.assert_rule(gate.run_gate(**paths), "snapshot-freshness")

    def test_artifact_boundary_detects_embedded_concrete_artifacts_but_allows_requirements(self) -> None:
        blocked = (
            "| users.csv | login,password |",
            "```yaml\nscenario_id: checkout-001\n```",
            "Run ID: RUN-001\nresult: passed",
            "dataset: accounts.csv (login,password)",
        )
        for extra in blocked:
            with self.subTest(extra=extra):
                paths = write_gate_fixture(self.root, extra=extra)
                self.assert_rule(gate.run_gate(**paths), "artifact-boundary")
        allowed = gate.run_gate(**write_gate_fixture(
            self.root,
            extra="Тестовые данные должны быть маскированы и храниться в отдельном артефакте.",
        ))
        self.assertFalse(any(item.rule == "artifact-boundary" for item in allowed.findings))
    def test_report_payload_validator_rejects_schema_violation(self) -> None:
        with self.assertRaisesRegex(ValueError, "does not match schema"):
            gate.validate_report_payload({"version": 1})
if __name__ == "__main__":
    raise SystemExit(unittest.main(verbosity=2))

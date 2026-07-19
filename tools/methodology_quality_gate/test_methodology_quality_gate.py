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
from methodology_authoring import methodology_authoring as authoring
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
                "--workspace-snapshot", str(paths["workspace_snapshot"]),
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
    def test_patch_must_apply_exactly_to_base_and_candidate(self) -> None:
        paths = write_gate_fixture(self.root)
        paths["base"].write_text("old\nkeep\n", encoding="utf-8")
        paths["candidate"].write_text("new\nkeep\n", encoding="utf-8")
        paths["patch"].write_text(
            f"--- {paths['base']}\n+++ {paths['candidate']}\n@@ -1,2 +1,2 @@\n-old\n+new\n",
            encoding="utf-8",
        )
        self.assert_rule(gate.run_gate(**paths), "patch-scope")

    def test_patch_applies_zero_count_hunk_and_no_newline_markers(self) -> None:
        paths = write_gate_fixture(self.root)
        paths["base"].write_text("a\nb\n", encoding="utf-8")
        paths["candidate"].write_text("a\nb\nc\n", encoding="utf-8")
        paths["patch"].write_text(
            f"--- {paths['base']}\n+++ {paths['candidate']}\n@@ -2,0 +3 @@\n+c\n",
            encoding="utf-8",
        )
        self.assertFalse(any(item.rule == "patch-scope" for item in gate.run_gate(**paths).findings))

        paths["base"].write_text("old", encoding="utf-8")
        paths["candidate"].write_text("new", encoding="utf-8")
        paths["patch"].write_text(
            f"--- {paths['base']}\n+++ {paths['candidate']}\n@@ -1 +1 @@\n-old\n\\ No newline at end of file\n+new\n\\ No newline at end of file\n",
            encoding="utf-8",
        )
        self.assertFalse(any(item.rule == "patch-scope" for item in gate.run_gate(**paths).findings))

    def test_patch_rejects_traversal_multiple_files_and_bad_no_newline_marker(self) -> None:
        paths = write_gate_fixture(self.root)
        invalid_patches = (
            f"--- ../base.md\n+++ {paths['candidate']}\n@@ -1 +1 @@\n-# МНТ\n+# МНТ\n",
            f"--- {paths['base']}\n+++ {paths['candidate']}\n@@ -1 +1 @@\n-# МНТ\n+# МНТ\n--- other.md\n+++ other.md\n@@ -1 +1 @@\n-a\n+b\n",
            f"--- {paths['base']}\n+++ {paths['candidate']}\n@@ -1 +1 @@\n-# МНТ\n\\ No newline at end of file\n+# МНТ\n",
        )
        for patch in invalid_patches:
            with self.subTest(patch=patch):
                paths["patch"].write_text(patch, encoding="utf-8")
                self.assert_rule(gate.run_gate(**paths), "patch-scope")
    def test_authoring_prepare_patches_pass_gate_for_all_line_endings_and_edit_shapes(self) -> None:
        cases = (
            (b"# MNT\n", lambda candidate: candidate, "normal-lf"),
            (b"# MNT\r\n", lambda candidate: candidate.replace(b"\n", b"\r\n"), "crlf"),
            (b"# MNT\n", lambda candidate: b"# MNT\nInserted evidence\n" + candidate, "insertion"),
            (b"# MNT\nobsolete\n" + b"x" * 0, lambda candidate: candidate, "deletion"),
            (b"# MNT", lambda candidate: candidate.rstrip(b"\n"), "unterminated"),
        )
        for base_bytes, make_candidate, label in cases:
            with self.subTest(label=label):
                paths = write_gate_fixture(self.root)
                base = self.root / "methodology.md"
                candidate = self.root / "methodology.candidate.md"
                patch = self.root / "methodology.patch"
                base.write_bytes(base_bytes)
                candidate_bytes = make_candidate(paths["candidate"].read_bytes())
                candidate.write_bytes(candidate_bytes)
                descriptor = authoring.prepare("methodology-patch", base, candidate, patch)
                self.assertEqual(descriptor.patch_sha256, authoring.sha256_path(patch))
                report = gate.run_gate(
                    candidate=candidate,
                    resolved_evidence=paths["resolved_evidence"],
                    coverage=paths["coverage"],
                    source_map=paths["source_map"],
                    workspace_snapshot=paths["workspace_snapshot"],
                    patch=patch,
                    base=base,
                )
                self.assertFalse(any(item.rule == "patch-scope" for item in report.findings))
    def test_snapshot_file_must_match_source_map_identity(self) -> None:
        paths = write_gate_fixture(self.root)
        snapshot = json.loads(paths["workspace_snapshot"].read_text(encoding="utf-8"))
        snapshot["snapshot_id"] = "b" * 64
        paths["workspace_snapshot"].write_text(json.dumps(snapshot), encoding="utf-8")
        self.assert_rule(gate.run_gate(**paths), "snapshot-freshness")
if __name__ == "__main__":
    raise SystemExit(unittest.main(verbosity=2))

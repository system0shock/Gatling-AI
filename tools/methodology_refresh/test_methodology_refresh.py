#!/usr/bin/env python3
"""Contract tests for deterministic selective methodology refresh planning."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import methodology_refresh as refresh
from fixtures import manifest, pages, snapshot, source_map


class SnapshotComparisonTest(unittest.TestCase):
    def test_commit_change_is_a_single_deterministic_module_change(self) -> None:
        previous = {"snapshot_id": "a" * 64, "modules": {"api-contracts": {"commit": "aaa", "dirty": False}}}
        current = {"snapshot_id": "b" * 64, "modules": {"api-contracts": {"commit": "ddd", "dirty": False}}}
        changes = refresh.compare_snapshots(previous, current)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].source_id, "api-contracts")
        self.assertEqual(changes[0].previous_revision, "aaa:False")
        self.assertEqual(changes[0].current_revision, "ddd:False")
        self.assertEqual(changes[0].reason, "git-state-changed")

    def test_added_removed_and_dirty_modules_are_never_silently_ignored(self) -> None:
        previous = snapshot(openapi="aaa", backend="bbb", frontend="ccc"); previous["snapshot_id"] = "a" * 64
        current = snapshot(openapi="aaa", frontend="ccc"); current["snapshot_id"] = "b" * 64
        current["modules"]["web-frontend"]["dirty"] = True
        current["modules"]["database"] = {"commit": "ddd", "dirty": False, "kind": "database"}
        changes = refresh.compare_snapshots(previous, current)
        self.assertEqual([change.source_id for change in changes], ["database", "orders-backend", "web-frontend"])
        self.assertEqual([change.reason for change in changes], ["module-added", "module-removed", "git-state-changed"])


class RefreshPlanTest(unittest.TestCase):
    def test_only_changed_openapi_module_targets_interfaces(self) -> None:
        plan = refresh.build_refresh_plan(refresh.compare_snapshots(snapshot(openapi="aaa", backend="bbb", frontend="ccc"), snapshot(openapi="ddd", backend="bbb", frontend="ccc")), source_map(), manifest())
        self.assertEqual(plan["inspect_modules"], ["api-contracts"])
        self.assertEqual(plan["affected_sections"], ["Реестр тестируемых интерфейсов"])
        self.assertNotIn("orders-backend", plan["inspect_modules"])

    def test_changed_confluence_sla_targets_sla_section(self) -> None:
        changes = refresh.compare_confluence_pages(pages({"sla-page": 4}), pages({"sla-page": 5}), page_roles={"sla-page": ["sla"]})
        plan = refresh.build_refresh_plan(changes, source_map(), manifest())
        self.assertEqual(plan["fetch_page_ids"], ["sla-page"])
        self.assertEqual(plan["affected_sections"], ["SLA, SLO и критерии приемки"])

    def test_unknown_module_fails_instead_of_skipping_its_refresh(self) -> None:
        change = refresh.SourceChange("module", "unknown", "a:False", "b:False", "a" * 64, "b" * 64, "git-state-changed")
        with self.assertRaisesRegex(ValueError, "unknown module"):
            refresh.build_refresh_plan((change,), source_map(), manifest())

    def test_unknown_confluence_role_conservatively_broadens_sections(self) -> None:
        change = refresh.SourceChange("confluence", "page", 1, 2, "a" * 64, "b" * 64, "page-version-changed", ("unknown",))
        plan = refresh.build_refresh_plan((change,), source_map(), manifest())
        self.assertEqual(plan["affected_sections"], sorted(refresh.ALL_SECTIONS))

    def test_source_entity_mapping_narrows_defaults_to_linked_section(self) -> None:
        change = refresh.SourceChange("module", "orders-backend", "a:False", "b:False", "a" * 64, "b" * 64, "git-state-changed")
        mapped = source_map(); mapped["sources"] = {"module:orders-backend": {"entity_ids": ["integration.payment.protocol"], "sections": []}}
        mapped["sections"] = {"Реестр интеграций": ["integration.payment.protocol"]}
        plan = refresh.build_refresh_plan((change,), mapped, manifest())
        self.assertEqual(plan["affected_entity_ids"], ["integration.payment.protocol"])
        self.assertEqual(plan["affected_sections"], ["Реестр интеграций"])


    def test_plan_serializes_roles_as_json_arrays(self) -> None:
        snapshot_id = "a" * 64
        change = refresh.SourceChange("module", "api-contracts", "a:False", "b:False", snapshot_id, snapshot_id, "git-state-changed")
        plan = refresh.build_refresh_plan((change,), source_map(), manifest(), previous_snapshot_id=snapshot_id, current_snapshot_id=snapshot_id)
        self.assertEqual(plan["changed_sources"][0]["roles"], [])

    def test_empty_plan_derives_a_valid_snapshot_identity_from_source_map(self) -> None:
        snapshot_id = "a" * 64
        mapped = {"version": 1, "sources": {}, "sections": {}, "workspace_snapshot": {"version": 1, "snapshot_id": snapshot_id, "fresh": True}}
        plan = refresh.build_refresh_plan((), mapped, manifest())
        self.assertEqual(plan["previous_snapshot_id"], snapshot_id)
        self.assertEqual(plan["current_snapshot_id"], snapshot_id)
        refresh.validate_refresh_plan(plan)

    def test_mixed_change_histories_are_rejected(self) -> None:
        changes = (
            refresh.SourceChange("module", "api-contracts", "a:False", "b:False", "a" * 64, "b" * 64, "git-state-changed"),
            refresh.SourceChange("module", "orders-backend", "a:False", "b:False", "c" * 64, "b" * 64, "git-state-changed"),
        )
        with self.assertRaisesRegex(ValueError, "mixed snapshot histories"):
            refresh.build_refresh_plan(changes, source_map(), manifest())

    def test_explicit_identity_must_match_every_change(self) -> None:
        change = refresh.SourceChange("module", "api-contracts", "a:False", "b:False", "a" * 64, "b" * 64, "git-state-changed")
        with self.assertRaisesRegex(ValueError, "do not match"):
            refresh.build_refresh_plan((change,), source_map(), manifest(), previous_snapshot_id="c" * 64, current_snapshot_id="b" * 64)

    def test_malformed_optional_source_mapping_is_rejected(self) -> None:
        change = refresh.SourceChange("module", "api-contracts", "a:False", "b:False", "a" * 64, "b" * 64, "git-state-changed")
        mapped = source_map(); mapped["sources"] = {"module:api-contracts": {"entity_ids": "not-an-array"}}
        with self.assertRaisesRegex(ValueError, "invalid source mapping"):
            refresh.build_refresh_plan((change,), mapped, manifest())

    def test_snapshot_manifest_validation_accepts_add_remove_with_embedded_known_kind(self) -> None:
        previous = self._phase_snapshot({"orders-backend": "backend"})
        current = self._phase_snapshot({"api-contracts": "api-spec"})
        current_manifest = {"modules": [{"id": "api-contracts", "kind": "api-spec"}]}
        refresh.validate_snapshot_manifest_consistency(previous, current, current_manifest)

    def test_snapshot_manifest_validation_rejects_unrelated_manifest(self) -> None:
        previous = self._phase_snapshot({"api-contracts": "api-spec"})
        current = self._phase_snapshot({"api-contracts": "backend"})
        with self.assertRaisesRegex(ValueError, "manifest"):
            refresh.validate_snapshot_manifest_consistency(previous, current, {"modules": [{"id": "api-contracts", "kind": "api-spec"}]})

    @staticmethod
    def _phase_snapshot(kinds: dict[str, str]) -> dict:
        modules = {module_id: {"commit": "abc", "branch": "main", "dirty": False, "remote": None, "path": module_id, "kind": kind, "dirty_policy": "clean"} for module_id, kind in kinds.items()}
        snapshot_id = hashlib.sha256(json.dumps(modules, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        return {"version": 1, "snapshot_id": snapshot_id, "workspace_root": "fixture", "modules": modules}

    def test_optional_source_mapping_requires_both_array_fields(self) -> None:
        change = refresh.SourceChange("module", "api-contracts", "a:False", "b:False", "a" * 64, "b" * 64, "git-state-changed")
        mapped = source_map(); mapped["sources"] = {"module:api-contracts": {"entity_ids": []}}
        with self.assertRaisesRegex(ValueError, "invalid source mapping"):
            refresh.build_refresh_plan((change,), mapped, manifest())

    def test_removed_module_uses_previous_kind_sections_without_recollection(self) -> None:
        change = refresh.SourceChange("module", "orders-backend", "a:False", None, "a" * 64, "b" * 64, "module-removed")
        plan = refresh.build_refresh_plan((change,), source_map(), {"modules": [{"id": "api-contracts", "kind": "api-spec"}]}, previous_module_kinds={"orders-backend": "backend"}, current_module_kinds={"api-contracts": "api-spec"})
        self.assertEqual(plan["inspect_modules"], [])
        self.assertIn("Архитектура", plan["affected_sections"])
        self.assertIn("Реестр интеграций", plan["affected_sections"])

    def test_same_commit_kind_change_is_explicit_and_manifest_validation_blocks_it(self) -> None:
        previous = self._phase_snapshot({"api-contracts": "backend"})
        current = self._phase_snapshot({"api-contracts": "frontend"})
        changes = refresh.compare_snapshots(previous, current)
        self.assertEqual(changes[0].reason, "module-kind-changed")
        with self.assertRaisesRegex(ValueError, "kind"):
            refresh.validate_snapshot_manifest_consistency(previous, current, {"modules": [{"id": "api-contracts", "kind": "frontend"}]})

    def test_nested_mapping_element_is_a_controlled_value_error(self) -> None:
        change = refresh.SourceChange("module", "api-contracts", "a:False", "b:False", "a" * 64, "b" * 64, "git-state-changed")
        mapped = source_map(); mapped["sources"] = {"module:api-contracts": {"entity_ids": [["nested"]], "sections": []}}
        with self.assertRaises(ValueError):
            refresh.build_refresh_plan((change,), mapped, manifest())

class CliTest(unittest.TestCase):
    def test_cli_validates_phase_3a_inputs_and_writes_under_derived_load_test_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            previous_run, current_run, workspace, load_tests = self._write_inputs(root, self._snapshot("aaa"), self._snapshot("bbb"))
            source_path = self._write_source_map(root, json.loads((previous_run / "workspace-snapshot.json").read_text(encoding="utf-8")))
            completed = self._run(previous_run, current_run, workspace, source_path, "methodology-runs/RUN-002/methodology-refresh-plan.json")
            self.assertEqual(completed.returncode, 0, completed.stderr)
            output = load_tests / "methodology-runs" / "RUN-002" / "methodology-refresh-plan.json"
            self.assertTrue(output.is_file())
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["inspect_modules"], ["api-contracts"])

    def test_cli_rejects_parent_root_output_without_writing_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            previous_run, current_run, workspace, _ = self._write_inputs(root, self._snapshot("aaa"), self._snapshot("bbb"))
            source_path = self._write_source_map(root, json.loads((previous_run / "workspace-snapshot.json").read_text(encoding="utf-8")))
            outside = root / "methodology-refresh-plan.json"
            completed = self._run(previous_run, current_run, workspace, source_path, str(outside))
            self.assertEqual(completed.returncode, 2)
            self.assertIn("outside load-test root", completed.stderr)
            self.assertFalse(outside.exists())

    def test_cli_plans_removed_module_from_previous_kind_without_recollection(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            previous = self._snapshot_with_kinds({"load-tests": "load-tests", "orders-backend": "backend"})
            current = self._snapshot_with_kinds({"load-tests": "load-tests"})
            previous_run, current_run, workspace, load_tests = self._write_inputs(root, previous, current, current_modules=[("load-tests", "load-tests")])
            source_path = self._write_source_map(root, previous)
            completed = self._run(previous_run, current_run, workspace, source_path, "methodology-runs/RUN-002/methodology-refresh-plan.json")
            self.assertEqual(completed.returncode, 0, completed.stderr)
            plan = json.loads((load_tests / "methodology-runs" / "RUN-002" / "methodology-refresh-plan.json").read_text(encoding="utf-8"))
            self.assertEqual(plan["inspect_modules"], [])
            self.assertIn("Архитектура", plan["affected_sections"])

    def test_cli_rejects_nested_source_mapping_with_domain_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            previous_run, current_run, workspace, load_tests = self._write_inputs(root, self._snapshot("aaa"), self._snapshot("bbb"))
            previous = json.loads((previous_run / "workspace-snapshot.json").read_text(encoding="utf-8"))
            source_path = self._write_source_map(root, previous, sources={"module:api-contracts": {"entity_ids": [["bad"]], "sections": []}})
            output = load_tests / "methodology-runs" / "RUN-002" / "methodology-refresh-plan.json"
            completed = self._run(previous_run, current_run, workspace, source_path, "methodology-runs/RUN-002/methodology-refresh-plan.json")
            self.assertEqual(completed.returncode, 2)
            self.assertIn("invalid source mapping", completed.stderr)
            self.assertNotIn("Traceback", completed.stderr)
            self.assertFalse(output.exists())

    def test_reparse_output_route_is_rejected_when_symlinks_are_available(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); load_tests, sut = root / "load-tests", root / "sut"; load_tests.mkdir(); sut.mkdir()
            link = load_tests / "link"
            try:
                link.symlink_to(sut, target_is_directory=True)
            except OSError:
                self.skipTest("symlinks unavailable")
            with self.assertRaisesRegex(ValueError, "outside load-test root"):
                refresh.resolve_output_inside_load_test_root(load_tests, link / "plan.json")

    def _write_inputs(self, root: Path, previous: dict, current: dict, current_modules: list[tuple[str, str]] | None = None) -> tuple[Path, Path, Path, Path]:
        previous_run, current_run = root / "RUN-001", root / "RUN-002"; previous_run.mkdir(); current_run.mkdir()
        (previous_run / "workspace-snapshot.json").write_text(json.dumps(previous), encoding="utf-8")
        (current_run / "workspace-snapshot.json").write_text(json.dumps(current), encoding="utf-8")
        load_tests = root / "load-tests"; (load_tests / "systems" / "SHOP").mkdir(parents=True)
        modules = current_modules or [("load-tests", "load-tests"), ("api-contracts", "api-spec")]
        module_yaml = "\n".join(f"  - id: {module_id}\n    path: {module_id}\n    kind: {kind}" for module_id, kind in modules)
        workspace = load_tests / "systems" / "SHOP" / "workspace.yaml"
        workspace.write_text(f"version: 1\nsystem: SHOP\nworkspace_root: ../../..\nload_test_module: load-tests\nmodules:\n{module_yaml}\nwrite_policy:\n  allowed_modules: [load-tests]\n  sut_modules: read-only\n", encoding="utf-8")
        return previous_run, current_run, workspace, load_tests

    @staticmethod
    def _write_source_map(root: Path, previous: dict, sources: dict | None = None) -> Path:
        source = {"version": 1, "sections": {heading: [] for heading in refresh.ALL_SECTIONS}, "workspace_snapshot": {"version": 1, "snapshot_id": previous["snapshot_id"], "fresh": True}}
        if sources is not None:
            source["sources"] = sources
        source_path = root / "source-map.json"; source_path.write_text(json.dumps(source, ensure_ascii=False), encoding="utf-8")
        return source_path

    @staticmethod
    def _run(previous_run: Path, current_run: Path, workspace: Path, source_map: Path, output: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(Path(refresh.__file__)), "--previous-run", str(previous_run), "--current-run", str(current_run), "--workspace", str(workspace), "--source-map", str(source_map), "--out", output], capture_output=True, encoding="utf-8", check=False)

    @staticmethod
    def _snapshot(commit: str) -> dict:
        snapshot = CliTest._snapshot_with_kinds({"load-tests": "load-tests", "api-contracts": "api-spec"}, "stable")
        snapshot["modules"]["api-contracts"]["commit"] = commit
        snapshot["snapshot_id"] = hashlib.sha256(json.dumps(snapshot["modules"], sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        return snapshot

    @staticmethod
    def _snapshot_with_kinds(kinds: dict[str, str], commit: str = "abc") -> dict:
        modules = {module_id: {"commit": commit, "branch": "main", "dirty": False, "remote": None, "path": module_id, "kind": kind, "dirty_policy": "clean"} for module_id, kind in kinds.items()}
        snapshot_id = hashlib.sha256(json.dumps(modules, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        return {"version": 1, "snapshot_id": snapshot_id, "workspace_root": "fixture", "modules": modules}

if __name__ == "__main__":
    raise SystemExit(unittest.main(verbosity=2))
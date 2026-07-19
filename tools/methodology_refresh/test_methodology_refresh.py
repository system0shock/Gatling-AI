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
        mapped = source_map(); mapped["sources"] = {"module:orders-backend": {"entity_ids": ["integration.payment.protocol"]}}
        mapped["sections"] = {"Реестр интеграций": ["integration.payment.protocol"]}
        plan = refresh.build_refresh_plan((change,), mapped, manifest())
        self.assertEqual(plan["affected_entity_ids"], ["integration.payment.protocol"])
        self.assertEqual(plan["affected_sections"], ["Реестр интеграций"])


    def test_plan_serializes_roles_as_json_arrays(self) -> None:
        snapshot_id = "a" * 64
        change = refresh.SourceChange("module", "api-contracts", "a:False", "b:False", snapshot_id, snapshot_id, "git-state-changed")
        plan = refresh.build_refresh_plan((change,), source_map(), manifest(), previous_snapshot_id=snapshot_id, current_snapshot_id=snapshot_id)
        self.assertEqual(plan["changed_sources"][0]["roles"], [])

class CliTest(unittest.TestCase):
    def test_cli_validates_phase_3a_inputs_and_writes_deterministic_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); previous_run, current_run = root / "RUN-001", root / "RUN-002"; previous_run.mkdir(); current_run.mkdir()
            previous = self._snapshot("aaa"); current = self._snapshot("bbb")
            (previous_run / "workspace-snapshot.json").write_text(json.dumps(previous), encoding="utf-8")
            (current_run / "workspace-snapshot.json").write_text(json.dumps(current), encoding="utf-8")
            workspace = root / "workspace.yaml"
            workspace.write_text("version: 1\nsystem: SHOP\nworkspace_root: .\nload_test_module: load-tests\nmodules:\n  - id: api-contracts\n    path: api\n    kind: api-spec\nwrite_policy:\n  allowed_modules: [load-tests]\n  sut_modules: read-only\n", encoding="utf-8")
            source = {"version": 1, "sections": {heading: [] for heading in refresh.ALL_SECTIONS}, "workspace_snapshot": {"version": 1, "snapshot_id": previous["snapshot_id"], "fresh": True}}
            source_path, output = root / "source-map.json", root / "methodology-refresh-plan.json"
            source_path.write_text(json.dumps(source, ensure_ascii=False), encoding="utf-8")
            completed = subprocess.run([sys.executable, str(Path(refresh.__file__)), "--previous-run", str(previous_run), "--current-run", str(current_run), "--workspace", str(workspace), "--source-map", str(source_path), "--out", str(output)], capture_output=True, encoding="utf-8", check=False)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            plan = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(plan["previous_snapshot_id"], previous["snapshot_id"])
            self.assertEqual(plan["current_snapshot_id"], current["snapshot_id"])
            self.assertEqual(plan["inspect_modules"], ["api-contracts"])

    @staticmethod
    def _snapshot(commit: str) -> dict:
        modules = {"api-contracts": {"commit": commit, "branch": "main", "dirty": False, "remote": None, "path": "api", "kind": "api-spec", "dirty_policy": "clean"}}
        snapshot_id = hashlib.sha256(json.dumps(modules, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        return {"version": 1, "snapshot_id": snapshot_id, "workspace_root": "fixture", "modules": modules}


if __name__ == "__main__":
    raise SystemExit(unittest.main(verbosity=2))
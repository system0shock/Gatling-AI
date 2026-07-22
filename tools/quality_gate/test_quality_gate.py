#!/usr/bin/env python3
"""Unit tests for quality gate checks."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

import quality_gate

REPO_ROOT = Path(__file__).resolve().parents[2]

SCENARIO_YAML = """scenario:
  id: demo-flow
  title: Demo flow
  system: SHOP
  number: 7
  source:
    type: manual
    ref: test
  sut:
    base_url: "${BASE_URL}"
  steps:
    - name: open-home
      title: Open home
      transaction: "01 demo.open-home - Open home"
      protocol: http
      request:
        method: GET
        path: /
      checks:
        - status: 200
  load:
    model: closed
    profile: constant
    users: 1
    duration_seconds: 60
  assertions:
    - name: p95
      metric: global.responseTime.p95
      op: "<"
      value: 800
"""


def write_demo_scenario(tmp: Path) -> Path:
    scenario = tmp / "demo.yaml"
    scenario.write_text(SCENARIO_YAML, encoding="utf-8")
    return scenario


def make_ctx(
    tmp: Path, scenario: Path | None = None, docs_dir: Path | None = None
) -> quality_gate.GateContext:
    return quality_gate.GateContext(
        repo_root=REPO_ROOT,
        scenario=scenario or REPO_ROOT / "examples" / "scenarios" / "SHOP"
        / "login-and-search-002" / "scenario.yaml",
        project=REPO_ROOT / "examples" / "generated" / "java",
        schema=REPO_ROOT / "schemas" / "scenario.schema.json",
        profile="mvp",
        json_report=tmp / "report.json",
        md_report=tmp / "report.md",
        docs_dir=docs_dir,
    )


class RendererCheckTest(unittest.TestCase):
    def test_fresh_colocated_passport_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scenario = write_demo_scenario(Path(tmp))
            subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "tools" / "scenario_renderer" / "scenario_renderer.py"),
                    str(scenario),
                ],
                check=True,
                cwd=REPO_ROOT,
            )
            ctx = make_ctx(Path(tmp), scenario=scenario)
            quality_gate.run_renderer_check(ctx)
            self.assertEqual(ctx.checks[-1].status, quality_gate.PASSED)
            self.assertEqual(ctx.blocking, [])

    def test_stale_colocated_passport_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scenario = write_demo_scenario(Path(tmp))
            (Path(tmp) / "passport.md").write_text("outdated\n", encoding="utf-8")
            ctx = make_ctx(Path(tmp), scenario=scenario)
            quality_gate.run_renderer_check(ctx)
            self.assertEqual(ctx.checks[-1].status, quality_gate.BLOCKED)
            self.assertEqual(ctx.blocking[-1].rule, "renderer.docs-stale")

    def test_docs_dir_override_keeps_id_named_doc(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scenario = write_demo_scenario(Path(tmp))
            docs = Path(tmp) / "docs"
            docs.mkdir()
            (docs / "demo.md").write_text("outdated\n", encoding="utf-8")
            ctx = make_ctx(Path(tmp), scenario=scenario, docs_dir=docs)
            quality_gate.run_renderer_check(ctx)
            self.assertEqual(ctx.blocking[-1].rule, "renderer.docs-stale")
            self.assertIn("docs", ctx.blocking[-1].artifact)


class SmokeCheckTest(unittest.TestCase):
    def test_smoke_runs_simulation_class(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scenario = write_demo_scenario(Path(tmp))
            ctx = make_ctx(Path(tmp), scenario=scenario)
            completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            with patch.object(
                quality_gate, "resolve_maven_executable", return_value="mvn"
            ), patch.object(quality_gate, "run_command", return_value=completed) as run:
                quality_gate.run_smoke_check(ctx, None)
            argv = run.call_args.args[0]
            self.assertIn("gatling:test", argv)
            self.assertIn("-Dgatling.simulationClass=SHOP_DemoFlow_007", argv)
            self.assertEqual(ctx.checks[-1].status, quality_gate.PASSED)

    def test_smoke_failure_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scenario = write_demo_scenario(Path(tmp))
            ctx = make_ctx(Path(tmp), scenario=scenario)
            completed = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="boom")
            with patch.object(
                quality_gate, "resolve_maven_executable", return_value="mvn"
            ), patch.object(quality_gate, "run_command", return_value=completed):
                quality_gate.run_smoke_check(ctx, None)
            self.assertEqual(ctx.blocking[-1].rule, "smoke.run-failed")


class PomPinsTest(unittest.TestCase):
    def make_ctx(self, project: Path, tmp: Path) -> quality_gate.GateContext:
        return quality_gate.GateContext(
            repo_root=REPO_ROOT,
            scenario=REPO_ROOT / "examples" / "scenarios" / "SHOP"
            / "login-and-search-002" / "scenario.yaml",
            project=project,
            schema=REPO_ROOT / "schemas" / "scenario.schema.json",
            profile="mvp",
            json_report=tmp / "report.json",
            md_report=tmp / "report.md",
        )

    def test_wrong_plugin_version_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            project = tmp / "project"
            project.mkdir()
            (project / "pom.xml").write_text(
                """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<project xmlns=\"http://maven.apache.org/POM/4.0.0\">
  <properties>
    <gatling.version>3.9.0</gatling.version>
    <gatling.maven.plugin.version>4.0.0</gatling.maven.plugin.version>
  </properties>
</project>
""",
                encoding="utf-8",
            )
            ctx = self.make_ctx(project, tmp)
            quality_gate.run_pom_pins_check(ctx)
            rules = [finding.rule for finding in ctx.blocking]
            self.assertIn("dependency-lint.gatling-pins", rules)

    def test_golden_project_pins_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            ctx = self.make_ctx(REPO_ROOT / "examples" / "generated" / "java", tmp)
            quality_gate.run_pom_pins_check(ctx)
            self.assertEqual([finding.rule for finding in ctx.blocking], [])

    def test_nested_plugin_properties_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            project = tmp / "project"
            project.mkdir()
            (project / "pom.xml").write_text(
                """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<project xmlns=\"http://maven.apache.org/POM/4.0.0\">
  <build>
    <pluginManagement>
      <plugins>
        <plugin>
          <configuration>
            <properties>
              <gatling.version>9.9.9</gatling.version>
              <gatling.maven.plugin.version>9.9.9</gatling.maven.plugin.version>
            </properties>
          </configuration>
        </plugin>
      </plugins>
    </pluginManagement>
  </build>
  <properties>
    <gatling.version>3.13.5</gatling.version>
    <gatling.maven.plugin.version>4.21.7</gatling.maven.plugin.version>
  </properties>
</project>
""",
                encoding="utf-8",
            )
            ctx = self.make_ctx(project, tmp)
            quality_gate.run_pom_pins_check(ctx)
            self.assertEqual([finding.rule for finding in ctx.blocking], [])

    def test_missing_pom_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            project = tmp / "project"
            project.mkdir()
            ctx = self.make_ctx(project, tmp)
            quality_gate.run_pom_pins_check(ctx)
            rules = [finding.rule for finding in ctx.blocking]
            self.assertIn("dependency-lint.gatling-pins", rules)
            self.assertIn("not found", ctx.blocking[-1].message)


class SkipLateChecksTest(unittest.TestCase):
    def test_smoke_skipped_entry_when_smoke_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctx = make_ctx(Path(tmp))
            quality_gate.skip_late_checks(ctx, smoke=True)
            check_names = [c.name for c in ctx.checks]
            self.assertIn("smoke", check_names)
            smoke_check = next(c for c in ctx.checks if c.name == "smoke")
            self.assertEqual(smoke_check.status, quality_gate.SKIPPED)

    def test_smoke_not_in_checks_when_smoke_not_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctx = make_ctx(Path(tmp))
            quality_gate.skip_late_checks(ctx, smoke=False)
            check_names = [c.name for c in ctx.checks]
            self.assertNotIn("smoke", check_names)


class MockLifecycleTest(unittest.TestCase):
    def test_start_mock_server_yields_reachable_base_url(self) -> None:
        routes = (
            REPO_ROOT / "examples" / "scenarios" / "SHOP" / "checkout-mix-001"
            / "mock.routes.json"
        )
        process, base_url = quality_gate.start_mock_server(REPO_ROOT, routes)
        try:
            with urllib.request.urlopen(f"{base_url}/__health", timeout=5) as response:
                self.assertEqual(response.status, 200)
        finally:
            quality_gate.stop_mock_server(process)

    def test_start_mock_server_reports_bad_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "routes.json"
            bad.write_text("{not json", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                process, _ = quality_gate.start_mock_server(REPO_ROOT, bad)


class ManualReviewTest(unittest.TestCase):
    def test_counts_todo_hooks_across_populations(self) -> None:
        document = {
            "scenario": {
                "id": "demo",
                "populations": [
                    {
                        "name": "a",
                        "steps": [
                            {
                                "name": "s1",
                                "hooks": {
                                    "before": [
                                        {"ref": "x.groovy", "kind": "todo", "summary": "t"}
                                    ],
                                    "after": [
                                        {
                                            "ref": "y.groovy",
                                            "kind": "translated",
                                            "snippet": "snippets/Y.java",
                                            "summary": "t",
                                        }
                                    ],
                                },
                            }
                        ],
                        "load": {},
                    },
                    {
                        "name": "b",
                        "steps": [
                            {
                                "name": "s2",
                                "hooks": {
                                    "after": [
                                        {"ref": "z.groovy", "kind": "todo", "summary": "t"}
                                    ]
                                },
                            }
                        ],
                        "load": {},
                    },
                ],
            }
        }
        self.assertEqual(quality_gate.count_todo_hooks(document), 2)

    def test_zero_for_document_without_hooks(self) -> None:
        self.assertEqual(quality_gate.count_todo_hooks({"scenario": {"id": "x", "steps": []}}), 0)

    def test_counts_todo_hooks_in_single_flow_form(self) -> None:
        document = {
            "scenario": {
                "id": "demo",
                "steps": [
                    {
                        "name": "s1",
                        "hooks": {
                            "before": [{"ref": "x.groovy", "kind": "todo", "summary": "t"}],
                            "after": [
                                {
                                    "ref": "y.groovy",
                                    "kind": "translated",
                                    "snippet": "snippets/Y.java",
                                    "summary": "t",
                                }
                            ],
                        },
                    }
                ],
                "load": {},
            }
        }
        self.assertEqual(quality_gate.count_todo_hooks(document), 1)

    def test_non_dict_document_counts_zero(self) -> None:
        self.assertEqual(quality_gate.count_todo_hooks(None), 0)
        self.assertEqual(quality_gate.count_todo_hooks({"scenario": "not-a-dict"}), 0)


class GeneratedBlocksTest(unittest.TestCase):
    def test_extract_generated_blocks(self) -> None:
        content = (
            "// @generated\nimport foo;\n// @generated-end\n"
            "// @custom:protocols\ncustom stuff\n// @custom-end\n"
            "// @generated\nclass Bar {}\n// @generated-end\n"
        )
        extracted = quality_gate.extract_generated_blocks(content)
        self.assertIn("import foo;", extracted)
        self.assertIn("class Bar {}", extracted)
        self.assertNotIn("custom stuff", extracted)


if __name__ == "__main__":
    sys.exit(unittest.main())

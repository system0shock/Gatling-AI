#!/usr/bin/env python3
"""Unit tests for quality gate checks."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import quality_gate

REPO_ROOT = Path(__file__).resolve().parents[2]


def make_ctx(tmp: Path, docs_dir: Path) -> quality_gate.GateContext:
    return quality_gate.GateContext(
        repo_root=REPO_ROOT,
        scenario=REPO_ROOT / "examples" / "scenarios" / "login-and-search.yaml",
        project=REPO_ROOT / "examples" / "generated" / "java",
        schema=REPO_ROOT / "schemas" / "scenario.schema.json",
        profile="mvp",
        json_report=tmp / "report.json",
        md_report=tmp / "report.md",
        docs_dir=docs_dir,
    )


class RendererCheckTest(unittest.TestCase):
    def test_fresh_docs_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctx = make_ctx(Path(tmp), REPO_ROOT / "examples" / "generated" / "docs")
            quality_gate.run_renderer_check(ctx)
            self.assertEqual(ctx.checks[-1].name, "renderer")
            self.assertEqual(ctx.checks[-1].status, quality_gate.PASSED)
            self.assertEqual(ctx.blocking, [])

    def test_stale_docs_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stale_docs = Path(tmp) / "docs"
            stale_docs.mkdir()
            (stale_docs / "login-and-search.md").write_text("outdated\n", encoding="utf-8")
            ctx = make_ctx(Path(tmp), stale_docs)
            quality_gate.run_renderer_check(ctx)
            self.assertEqual(ctx.checks[-1].status, quality_gate.BLOCKED)
            self.assertEqual(ctx.blocking[-1].rule, "renderer.docs-stale")


class SmokeCheckTest(unittest.TestCase):
    def test_smoke_runs_simulation_class(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctx = make_ctx(Path(tmp), REPO_ROOT / "examples" / "generated" / "docs")
            completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            with patch.object(
                quality_gate, "resolve_maven_executable", return_value="mvn"
            ), patch.object(quality_gate, "run_command", return_value=completed) as run:
                quality_gate.run_smoke_check(ctx)
            argv = run.call_args.args[0]
            self.assertIn("gatling:test", argv)
            self.assertIn("-Dgatling.simulationClass=LoginAndSearchSimulation", argv)
            self.assertEqual(ctx.checks[-1].status, quality_gate.PASSED)

    def test_smoke_failure_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctx = make_ctx(Path(tmp), REPO_ROOT / "examples" / "generated" / "docs")
            completed = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="boom")
            with patch.object(
                quality_gate, "resolve_maven_executable", return_value="mvn"
            ), patch.object(quality_gate, "run_command", return_value=completed):
                quality_gate.run_smoke_check(ctx)
            self.assertEqual(ctx.blocking[-1].rule, "smoke.run-failed")


class PomPinsTest(unittest.TestCase):
    def make_ctx(self, project: Path, tmp: Path) -> quality_gate.GateContext:
        return quality_gate.GateContext(
            repo_root=REPO_ROOT,
            scenario=REPO_ROOT / "examples" / "scenarios" / "login-and-search.yaml",
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
    <gatling.version>3.12.0</gatling.version>
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


if __name__ == "__main__":
    sys.exit(unittest.main())

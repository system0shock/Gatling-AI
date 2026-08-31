"""End-to-end tests for the methodology-first core CLI."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import yaml

if __package__:
    from . import fixtures, methodology_pipeline
    from .sections import CANONICAL_SECTIONS
else:
    import fixtures
    import methodology_pipeline
    from sections import CANONICAL_SECTIONS


ARTIFACTS = (
    "resolved-profile.yaml",
    "methodology-input.yaml",
    "generation-state.json",
    "methodology.candidate.md",
    "methodology-readiness-report.json",
    "methodology-readiness-report.md",
    "methodology-template-report.json",
    "methodology-template-report.md",
)


class MethodologyPipelineCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "load-test"
        self.paths = fixtures.write_core_cli_fixture(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_cli(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(args, capture_output=True, text=True, check=False)

    def test_build_is_deterministic_and_emits_both_reports(self) -> None:
        args = fixtures.core_build_args(self.paths)
        first = self.run_cli(args)
        self.assertEqual(first.returncode, 0, first.stderr)
        first_bytes = {
            name: (self.paths["out_dir"] / name).read_bytes()
            for name in ARTIFACTS
        }

        second = self.run_cli(args)

        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(
            {name: (self.paths["out_dir"] / name).read_bytes() for name in ARTIFACTS},
            first_bytes,
        )
        self.assertFalse(any(path.name.startswith(".") for path in self.paths["out_dir"].iterdir()))
        readiness_value = self.read_json("methodology-readiness-report.json")
        template_value = self.read_json("methodology-template-report.json")
        self.assertEqual(readiness_value["status"], "ready")
        self.assertTrue(readiness_value["ready_for_test"])
        self.assertEqual(template_value["status"], "complete")
        self.assertTrue(template_value["template_complete"])
        state = self.read_json("generation-state.json")
        self.assertEqual(
            set(state["blocks"]),
            {section_id for section_id, _ in CANONICAL_SECTIONS},
        )
        self.assertFalse(self.paths["current"].exists())

    def test_build_rejects_unknown_previous_generation_state_block(self) -> None:
        self.assertEqual(self.run_cli(fixtures.core_build_args(self.paths)).returncode, 0)
        run = self.paths["out_dir"]
        self.paths["current"].write_bytes(
            (run / "methodology.candidate.md").read_bytes()
        )
        state_path = run / "generation-state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["blocks"]["unknown-section"] = {
            "sha256": "a" * 64,
            "rendered_sha256": "a" * 64,
            "resolution": "rendered",
        }
        state_path.write_text(
            json.dumps(state, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        args = fixtures.core_build_args(self.paths)
        args.extend(["--previous-generation-state", str(state_path)])

        result = self.run_cli(args)

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(
            result.stderr,
            "error: unknown previous generation state block: unknown-section\n",
        )

    def test_update_mode_preserves_manual_and_outside_text_without_applying(self) -> None:
        self.assertEqual(self.run_cli(fixtures.core_build_args(self.paths)).returncode, 0)
        candidate = self.paths["out_dir"] / "methodology.candidate.md"
        original = candidate.read_bytes()
        updated_current = (b"outside-prefix\n" + original).replace(
            b"<!-- mnt:manual:end -->",
            b"manual-preserved\n<!-- mnt:manual:end -->",
            1,
        )
        self.paths["current"].write_bytes(updated_current)
        args = fixtures.core_build_args(self.paths)
        args.extend([
            "--previous-generation-state",
            str(self.paths["out_dir"] / "generation-state.json"),
        ])

        result = self.run_cli(args)

        self.assertEqual(result.returncode, 0, result.stderr)
        generated = candidate.read_bytes()
        self.assertIn(b"outside-prefix", generated)
        self.assertIn(b"manual-preserved", generated)
        self.assertEqual(self.paths["current"].read_bytes(), updated_current)

    def test_update_preserves_mixed_line_endings_outside_generated_bodies(self) -> None:
        self.assertEqual(self.run_cli(fixtures.core_build_args(self.paths)).returncode, 0)
        candidate = self.paths["out_dir"] / "methodology.candidate.md"
        original = candidate.read_bytes()
        manual = b"manual-crlf\r\nmanual-cr\rmanual-lf\n"
        mixed_current = (
            b"outside-crlf\r\noutside-cr\routside-lf\n"
            + original.replace(
                b"<!-- mnt:manual:end -->",
                manual + b"<!-- mnt:manual:end -->",
                1,
            )
        )
        self.paths["current"].write_bytes(mixed_current)
        answers = yaml.safe_load(self.paths["answers"].read_text(encoding="utf-8"))
        answers["questions"]["environment.name"]["value"] = "performance"
        self.paths["answers"].write_text(
            yaml.safe_dump(answers, allow_unicode=True, sort_keys=True),
            encoding="utf-8",
        )
        args = fixtures.core_build_args(self.paths)
        args.extend([
            "--previous-generation-state",
            str(self.paths["out_dir"] / "generation-state.json"),
        ])

        result = self.run_cli(args)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            candidate.read_bytes(),
            mixed_current.replace(b"staging", b"performance", 1),
        )
        self.assertEqual(self.paths["current"].read_bytes(), mixed_current)

    def test_check_uses_only_existing_generated_artifacts(self) -> None:
        self.assertEqual(self.run_cli(fixtures.core_build_args(self.paths)).returncode, 0)
        for key in ("workspace_snapshot", "surface_review", "answers"):
            self.paths[key].unlink()
        check_out = self.root / "check"
        args = self.check_args(check_out)

        result = self.run_cli(args)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            sorted(path.name for path in check_out.iterdir()),
            sorted((
                "methodology-readiness-report.json",
                "methodology-readiness-report.md",
                "methodology-template-report.json",
                "methodology-template-report.md",
            )),
        )

    def test_check_rejects_tampered_generated_body_and_writes_reports(self) -> None:
        self.assertEqual(self.run_cli(fixtures.core_build_args(self.paths)).returncode, 0)
        candidate = self.paths["out_dir"] / "methodology.candidate.md"
        candidate.write_bytes(candidate.read_bytes().replace(
            b"<!-- mnt:construct:test-step-search -->",
            b"tampered generated body\n<!-- mnt:construct:test-step-search -->",
            1,
        ))
        check_out = self.root / "check-tampered"

        result = self.run_cli(self.check_args(check_out))

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(
            result.stderr,
            "error: check state conflict: candidate generated hash mismatch: test-types\n",
        )
        self.assert_report_artifacts(check_out)

    def test_check_rejects_empty_and_incomplete_generation_state(self) -> None:
        self.assertEqual(self.run_cli(fixtures.core_build_args(self.paths)).returncode, 0)
        state_path = self.paths["out_dir"] / "generation-state.json"
        complete_state = json.loads(state_path.read_text(encoding="utf-8"))
        incomplete_state = json.loads(json.dumps(complete_state))
        del incomplete_state["blocks"]["test-types"]
        for name, state in (
            ("empty", {"version": 1, "blocks": {}}),
            ("incomplete", incomplete_state),
        ):
            with self.subTest(name=name):
                state_path.write_text(
                    json.dumps(state, ensure_ascii=False, sort_keys=True),
                    encoding="utf-8",
                )
                check_out = self.root / f"check-{name}"

                result = self.run_cli(self.check_args(check_out))

                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(
                    result.stderr,
                    "error: check state conflict: generation state blocks do not match canonical sections\n",
                )
                self.assert_report_artifacts(check_out)

    def test_check_rejects_incorrect_deterministic_render_hash(self) -> None:
        self.assertEqual(self.run_cli(fixtures.core_build_args(self.paths)).returncode, 0)
        state_path = self.paths["out_dir"] / "generation-state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["blocks"]["test-types"]["resolution"] = "keep"
        state["blocks"]["test-types"]["rendered_sha256"] = "c" * 64
        state_path.write_text(
            json.dumps(state, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
        check_out = self.root / "check-rendered-hash"

        result = self.run_cli(self.check_args(check_out))

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(
            result.stderr,
            "error: check state conflict: deterministic rendered hash mismatch: test-types\n",
        )
        self.assert_report_artifacts(check_out)

    def test_check_accepts_state_bound_keep_body_as_warning(self) -> None:
        self.assertEqual(self.run_cli(fixtures.core_build_args(self.paths)).returncode, 0)
        run = self.paths["out_dir"]
        candidate = run / "methodology.candidate.md"
        changed = candidate.read_bytes().replace(
            b"<!-- mnt:construct:test-step-search -->",
            b"user-kept body\n<!-- mnt:construct:test-step-search -->",
            1,
        )
        candidate.write_bytes(changed)
        body = candidate.read_text(encoding="utf-8").split(
            "<!-- mnt:generated:start id=test-types -->\n", 1
        )[1].split("<!-- mnt:generated:end -->", 1)[0]
        state_path = run / "generation-state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        rendered_hash = state["blocks"]["test-types"]["rendered_sha256"]
        state["blocks"]["test-types"] = {
            "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            "rendered_sha256": rendered_hash,
            "resolution": "keep",
        }
        state_path.write_text(
            json.dumps(state, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
        check_out = self.root / "check-valid-keep"

        result = self.run_cli(self.check_args(check_out))

        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assert_report_artifacts(check_out)

    def test_ready_template_warning_returns_one(self) -> None:
        answers = yaml.safe_load(self.paths["answers"].read_text(encoding="utf-8"))
        answers["not_applicable_sections"] = [
            item for item in answers["not_applicable_sections"]
            if item["section_id"] != "risks"
        ]
        self.paths["answers"].write_text(
            yaml.safe_dump(answers, allow_unicode=True, sort_keys=True),
            encoding="utf-8",
        )

        result = self.run_cli(fixtures.core_build_args(self.paths))

        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertTrue(self.read_json("methodology-readiness-report.json")["ready_for_test"])
        self.assertFalse(self.read_json("methodology-template-report.json")["template_complete"])

    def test_parseable_blocked_build_returns_two_and_writes_reports(self) -> None:
        answers = yaml.safe_load(self.paths["answers"].read_text(encoding="utf-8"))
        del answers["questions"]["environment.name"]
        self.paths["answers"].write_text(
            yaml.safe_dump(answers, allow_unicode=True, sort_keys=True),
            encoding="utf-8",
        )

        result = self.run_cli(fixtures.core_build_args(self.paths))

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(self.read_json("methodology-readiness-report.json")["status"], "blocked")
        self.assertTrue((self.paths["out_dir"] / "methodology-template-report.json").is_file())

    def test_parseable_conflict_returns_two_and_writes_reports(self) -> None:
        self.assertEqual(self.run_cli(fixtures.core_build_args(self.paths)).returncode, 0)
        candidate = self.paths["out_dir"] / "methodology.candidate.md"
        changed = candidate.read_bytes().replace(
            b"<!-- mnt:construct:test-step-search -->",
            b"manual generated edit\n<!-- mnt:construct:test-step-search -->",
            1,
        )
        self.paths["current"].write_bytes(changed)
        args = fixtures.core_build_args(self.paths)
        args.extend([
            "--previous-generation-state",
            str(self.paths["out_dir"] / "generation-state.json"),
        ])

        result = self.run_cli(args)

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(
            (self.paths["out_dir"] / "methodology.candidate.md").read_bytes(),
            changed,
        )
        self.assertTrue((self.paths["out_dir"] / "methodology-readiness-report.json").is_file())
        self.assertTrue((self.paths["out_dir"] / "methodology-template-report.json").is_file())
        self.assertEqual(self.paths["current"].read_bytes(), changed)

    def test_keep_resolution_returns_one_and_does_not_apply_current(self) -> None:
        self.assertEqual(self.run_cli(fixtures.core_build_args(self.paths)).returncode, 0)
        candidate = self.paths["out_dir"] / "methodology.candidate.md"
        changed = candidate.read_bytes().replace(
            b"<!-- mnt:construct:test-step-search -->",
            b"manual generated edit\n<!-- mnt:construct:test-step-search -->",
            1,
        )
        self.paths["current"].write_bytes(changed)
        decisions = self.root / "drift.yaml"
        decisions.write_text(
            "version: 1\ndecisions:\n  test-types: keep\n",
            encoding="utf-8",
        )
        args = fixtures.core_build_args(self.paths)
        args.extend([
            "--previous-generation-state",
            str(self.paths["out_dir"] / "generation-state.json"),
            "--drift-decisions",
            str(decisions),
        ])

        result = self.run_cli(args)

        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn(b"manual generated edit", candidate.read_bytes())
        self.assertEqual(self.paths["current"].read_bytes(), changed)

    def test_invalid_input_returns_two_without_traceback(self) -> None:
        self.paths["answers"].write_text("- not-a-mapping\n", encoding="utf-8")

        result = self.run_cli(fixtures.core_build_args(self.paths))

        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse(self.paths["current"].exists())

    def test_missing_null_and_blank_meta_references_are_cli_invalid(self) -> None:
        original = yaml.safe_load(self.paths["answers"].read_text(encoding="utf-8"))
        missing = object()
        for reference in (missing, None, "", " \t"):
            with self.subTest(
                reference="missing" if reference is missing else reference
            ):
                answers = yaml.safe_load(yaml.safe_dump(original))
                entry = {"value": 35}
                if reference is not missing:
                    entry["source_reference"] = reference
                answers["profile"]["meta_values"] = {
                    "criteria.cpu.max_percent": entry
                }
                self.paths["answers"].write_text(
                    yaml.safe_dump(answers, allow_unicode=True, sort_keys=True),
                    encoding="utf-8",
                )

                result = self.run_cli(fixtures.core_build_args(self.paths))

                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("methodology-answers.schema.json", result.stderr)

    def test_rejects_runtime_input_outside_load_test_root(self) -> None:
        outside = Path(self.temporary.name) / "outside-snapshot.json"
        shutil.copyfile(self.paths["workspace_snapshot"], outside)
        args = fixtures.core_build_args(self.paths)
        index = args.index(str(self.paths["workspace_snapshot"]))
        args[index] = str(outside)

        result = self.run_cli(args)

        self.assertEqual(result.returncode, 2)
        self.assertIn("outside load-test root", result.stderr)
        self.assertFalse(self.paths["out_dir"].exists())

    def test_rejects_package_asset_outside_manage_methodology_root(self) -> None:
        outside = self.root / "profile.yaml"
        shutil.copyfile(self.paths["profile"], outside)
        args = fixtures.core_build_args(self.paths)
        index = args.index(str(self.paths["profile"]))
        args[index] = str(outside)

        result = self.run_cli(args)

        self.assertEqual(result.returncode, 2)
        self.assertIn("outside manage-methodology root", result.stderr)
        self.assertFalse(self.paths["out_dir"].exists())

    def test_rejects_resolved_escape_independent_of_symlink_privileges(self) -> None:
        requested = self.root / "linked" / "run"
        resolved_root = self.root.resolve()
        resolved_escape = (Path(self.temporary.name) / "outside" / "run").resolve()
        with mock.patch.object(Path, "resolve", return_value=resolved_escape):
            with self.assertRaisesRegex(ValueError, "outside load-test root"):
                methodology_pipeline._contained_path(
                    requested,
                    resolved_root,
                    "load-test root",
                    must_exist=False,
                )

    def test_rejects_symlink_escape_for_current_and_out_dir(self) -> None:
        outside = Path(self.temporary.name) / "outside"
        outside.mkdir()
        current_target = outside / "methodology.md"
        current_target.write_text("do not read or change", encoding="utf-8")
        out_target = outside / "run"
        out_target.mkdir()
        try:
            os.symlink(current_target, self.paths["current"])
            os.symlink(out_target, self.root / "linked-run", target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlinks unavailable: {exc}")

        current_result = self.run_cli(fixtures.core_build_args(self.paths))
        out_args = fixtures.core_build_args(self.paths)
        out_args[out_args.index(str(self.paths["out_dir"]))] = str(self.root / "linked-run")
        out_result = self.run_cli(out_args)

        self.assertEqual(current_result.returncode, 2)
        self.assertEqual(out_result.returncode, 2)
        self.assertEqual(current_target.read_text(encoding="utf-8"), "do not read or change")
        self.assertEqual(list(out_target.iterdir()), [])

    def read_json(self, name: str) -> dict[str, object]:
        return json.loads(
            (self.paths["out_dir"] / name).read_text(encoding="utf-8")
        )

    def assert_report_artifacts(self, out_dir: Path) -> None:
        self.assertEqual(
            {path.name for path in out_dir.iterdir()},
            {
                "methodology-readiness-report.json",
                "methodology-readiness-report.md",
                "methodology-template-report.json",
                "methodology-template-report.md",
            },
        )

    def check_args(self, out_dir: Path) -> list[str]:
        run = self.paths["out_dir"]
        return [
            sys.executable,
            str(self.paths["script"]),
            "check",
            "--candidate",
            str(run / "methodology.candidate.md"),
            "--methodology-input",
            str(run / "methodology-input.yaml"),
            "--generation-state",
            str(run / "generation-state.json"),
            "--template-contract",
            str(self.paths["template_contract"]),
            "--out-dir",
            str(out_dir),
            "--load-test-root",
            str(self.paths["root"]),
        ]


if __name__ == "__main__":
    unittest.main()

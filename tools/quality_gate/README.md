# Quality Gate Command

`quality_gate.py` runs the Phase 0 Gatling-AI quality gate and writes both JSON
and Markdown reports at the repository root by default.

## Usage

```bash
python tools/quality_gate/quality_gate.py --scenario examples/scenarios/login-and-search.yaml --project examples/generated/java --profile mvp
```

The command exits non-zero when the final gate status is `blocked`.

## MVP Checks

- JSON Schema validation against `schemas/scenario.schema.json`.
- Scenario lint through `tools/scenario_lint/scenario_lint.py` (waivers from the
  scenario's `lint_waivers` block are applied and reported).
- Generator reproducibility through two temporary runs of
  `tools/gatling_generator/gatling_generator.py`.
- Scenario doc render through `tools/scenario_renderer/scenario_renderer.py`:
  the render must be deterministic and match the committed Markdown in the
  `--docs-dir` directory (default `examples/generated/docs`).
- Maven compile in the provided generated Java project.
- Optional smoke run with `--smoke`: executes
  `mvn -q gatling:test -Dgatling.simulationClass=<ScenarioId>Simulation` in the
  project. **This loads the SUT**, so it never runs by default — pass the flag
  only with explicit permission.

If schema validation or scenario lint finds blocking issues, generator,
renderer, and Maven compile checks are skipped and the skip is recorded as a
warning. This keeps invalid scenario reports focused on the first actionable
blockers.

### Examples

```bash
# Custom docs directory for the renderer drift check
python tools/quality_gate/quality_gate.py --scenario examples/scenarios/login-and-search.yaml --project examples/generated/java --docs-dir examples/generated/docs

# Opt-in smoke run (requires BASE_URL and a reachable SUT)
python tools/quality_gate/quality_gate.py --scenario examples/scenarios/login-and-search.yaml --project examples/generated/java --smoke
```

## Reports

Default report paths:

- `quality-gate-report.json`
- `quality-gate-report.md`

The JSON report includes:

- `status`
- `profile`
- `checked_at`
- `artifacts`
- `blocking`
- `warnings`
- `waivers`
- `checks`

Artifact paths are repository-relative POSIX paths when the artifact is inside
the repository.

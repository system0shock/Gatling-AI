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
- Scenario lint through `tools/scenario_lint/scenario_lint.py`.
- Generator reproducibility through two temporary runs of
  `tools/gatling_generator/gatling_generator.py`.
- Maven compile in the provided generated Java project.

If schema validation or scenario lint finds blocking issues, generator and Maven
compile checks are skipped and the skip is recorded as a warning. This keeps
invalid scenario reports focused on the first actionable blockers.

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

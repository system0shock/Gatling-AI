# Quality Gate

Use this skill before handing back Gatling-AI scenario or generated Java changes.
It runs the Phase 0 quality gate and checks the generated reports.

## Command

```bash
python tools/quality_gate/quality_gate.py --scenario examples/scenarios/login-and-search.yaml --project examples/generated/java --profile mvp
```

Use `--scenario` for the scenario under review and `--project` for the generated
Java Maven project. The command writes:

- `quality-gate-report.json`
- `quality-gate-report.md`

## Status Handling

- `passed`: no blockers, warnings, or waivers.
- `passed_with_warnings`: no blockers, but warnings or waivers are present.
- `blocked`: at least one blocking finding exists.

Treat `blocked` as not ready for handoff. Read the Markdown report first for a
compact reviewer view, then inspect JSON if exact machine-readable fields are
needed.

## Expected Phase 0 Verification

Run the invalid scenario to verify blocking behavior:

```bash
python tools/quality_gate/quality_gate.py --scenario examples/scenarios/invalid/missing-check.yaml --project examples/generated/java --profile mvp
```

Run the golden scenario to verify full schema, lint, generator, and Maven compile:

```bash
python tools/quality_gate/quality_gate.py --scenario examples/scenarios/login-and-search.yaml --project examples/generated/java --profile mvp
```

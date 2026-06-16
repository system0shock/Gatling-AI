# Quality Gate

Use this skill before handing back Gatling-AI scenario or generated Java changes.
It runs the Phase 0 quality gate and checks the generated reports.

## Command

```bash
python tools/quality_gate/quality_gate.py --scenario examples/scenarios/SHOP/login-and-search-002/scenario.yaml --project examples/generated/java --profile mvp
```

Also applies to golden #2:

```bash
python tools/quality_gate/quality_gate.py --scenario examples/scenarios/SHOP/checkout-mix-001/scenario.yaml --project examples/generated/checkout-java --profile mvp
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

The `pom-pins` check is blocking when the Gatling version pins in `pom.xml`
diverge from 3.12.x / gatling-maven-plugin 4.21.7. Fix by updating the pom to
match the required pins (or run generation into a fresh directory to get a
bootstrapped pom).

## Smoke Run (opt-in)

The gate never loads a SUT by default (FR5.7.7). With explicit user permission:

    python tools/quality_gate/quality_gate.py --scenario scenarios/<SYSTEM>/<id>-<NNN>/scenario.yaml \
        --project <project> --smoke --mock-routes scenarios/<SYSTEM>/<id>-<NNN>/mock.routes.json

With `--mock-routes` the gate starts `tools/mock_sut`, points `BASE_URL` at it,
runs `mvn gatling:test`, and stops the mock. Without `--mock-routes`, `BASE_URL`
must already point at a SUT the user explicitly allowed to load.

## Expected Phase 0 Verification

Run the invalid scenario to verify blocking behavior:

```bash
python tools/quality_gate/quality_gate.py --scenario examples/scenarios/invalid/missing-check.yaml --project examples/generated/java --profile mvp
```

Run the golden scenario to verify full schema, lint, generator, scenario doc
render (committed `passport.md` next to the scenario (or the `--docs-dir` override) must
match a fresh render), and Maven compile:

```bash
python tools/quality_gate/quality_gate.py --scenario examples/scenarios/SHOP/login-and-search-002/scenario.yaml --project examples/generated/java --profile mvp
```

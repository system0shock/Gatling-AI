# Architecture

## System Goal

Gatling-AI Workflow turns ambiguous performance-test inputs into deterministic, reviewable artifacts. The system should never jump straight from prose to code without leaving a scenario contract and a verification report.

## Artifact Flow

```text
Confluence / Markdown / Manual input
        |
        v
scenario-from-docs skill
        |
        v
scenario.yaml + scenario.schema.json validation
        |
        v
scenario-to-gatling skill
        |
        v
Java Gatling Simulation
        |
        v
quality-gate hooks + validator-subagent
        |
        v
Runnable test + reports + review notes
```

JMeter migration joins the same flow by normalizing `.jmx` plans into the scenario contract before code generation.

## Components

| Component | Responsibility |
|---|---|
| `scenario-from-docs` | Implemented skill. Extract endpoints, checks, data, load profile, and unknowns from documents or dialogue; produces a lint-clean scenario.yaml and rendered reviewer doc. |
| `scenario.schema.json` | Validate the structural contract of scenario YAML. |
| `scenario-lint` | Validate semantic consistency that JSON Schema cannot express well. |
| `scenario-to-gatling` | Implemented skill. Generate and verify a Java Gatling simulation from an approved scenario.yaml; covers bootstrap, generation, compile, smoke run, and the mandatory quality gate. |
| `scenario_renderer` | Render scenario YAML into reviewer-facing Markdown (one-way generated artifact, drift-checked by the quality gate). |
| `script-style-lint` | Enforce transaction naming, request naming, checks, feeders, correlation, environment, and dependency rules. |
| `quality-gate` | Run scoped checks and produce machine-readable and human-readable reports. |
| `mock_sut` | Deterministic local HTTP stub for smoke runs; behavior declared in JSON route configs. |
| `jmx_parser` | Stream-parse legacy `.jmx` into `ir.json`, `inventory.md`, externalized bodies and classified JSR223 scripts; the only component that reads JMX XML (Phase 2). |
| `ir_to_scenario` | Second migration stage: walks `ir.json` and maps each element to `scenario.yaml`, recording a disposition for every element (Phase 2). |
| `document-legacy-jmeter` skill | Agent skill: reads `ir.json` + `inventory.md` and produces a human-readable legacy documentation report (Phase 2c). |
| `convert-from-jmeter` skill | Agent skill: orchestrates the full JMX → `scenario.yaml` pipeline and runs the quality gate (Phase 2c). Golden fixtures in `examples/jmx/`; converted artifacts in `examples/scenarios/SHOP/legacy-backend-010/` and `legacy-staged-011/`. |
| `validator-subagent` | Read-only reviewer that checks artifacts and reports before final handoff. |

## Quality Boundary

Generated code is not considered done when it compiles. It is done only when:

- Scenario YAML is schema-valid.
- Domain lint has no blocking errors.
- Java compiles.
- A smoke run path is documented or executed.
- `quality-gate-report.json` exists.
- The validator-subagent accepts the evidence or marks the task blocked.

## Planned Repository Structure

```text
schemas/
  scenario.schema.json
  jmx-ir.schema.json

examples/
  scenarios/
    SHOP/
      checkout-mix-001/
        scenario.yaml
        passport.md
        terms.csv
        mock.routes.json
      login-and-search-002/
        scenario.yaml
        passport.md
        users.csv
    invalid/
  generated/
    java/
    checkout-java/
  requirements/
    checkout-mix.md

skills/
  scenario-from-docs/
  scenario-to-gatling/
  quality-gate/

tools/
  _shared/
  scenario_lint/
  gatling_generator/
  scenario_renderer/
  quality_gate/
  mock_sut/
  hook_router/
  jmx_parser/
```

The structure may change once the real Gigacode skill packaging requirements are verified. The boundary should remain: schemas and examples are product artifacts; tools are executable checks/generators; skills are agent-facing workflows.


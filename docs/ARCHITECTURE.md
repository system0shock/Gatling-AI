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
| `scenario-from-docs` | Extract endpoints, checks, data, load profile, and unknowns from documents or dialogue. |
| `scenario.schema.json` | Validate the structural contract of scenario YAML. |
| `scenario-lint` | Validate semantic consistency that JSON Schema cannot express well. |
| `scenario-to-gatling` | Generate Java Gatling simulations from scenario YAML. |
| `scenario_renderer` | Render scenario YAML into reviewer-facing Markdown (one-way generated artifact, drift-checked by the quality gate). |
| `script-style-lint` | Enforce transaction naming, request naming, checks, feeders, correlation, environment, and dependency rules. |
| `quality-gate` | Run scoped checks and produce machine-readable and human-readable reports. |
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

examples/
  scenarios/
    login-and-search.yaml
    invalid/
  generated/
    java/

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
  hook_router/
```

The structure may change once the real Gigacode skill packaging requirements are verified. The boundary should remain: schemas and examples are product artifacts; tools are executable checks/generators; skills are agent-facing workflows.


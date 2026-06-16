# Getting Started

This repository starts from a PRD and a foundation plan. The first goal is to prove the core contract:

`requirements text -> scenario.yaml -> Java Gatling simulation -> local verification report`

## Working Rules

- Keep Gatling OSS only.
- Generate Java simulations only.
- Prefer Maven for the first working path.
- Keep all generated artifacts reviewable.
- Do not report a task as complete without a quality gate status.
- Treat hook support in Gigacode as a spike until verified.

## First Week Checklist

1. Create the scenario schema and one valid HTTP example.
2. Create one invalid example for each blocking lint rule.
3. Implement schema validation before code generation.
4. Implement script-style lint before formatting polish.
5. Generate one Java Gatling simulation from the valid example.
6. Compile the generated simulation locally.
7. Write `quality-gate-report.json` and `quality-gate-report.md`.
8. Document any Gigacode hook gaps and fallback behavior.

## Expected Repository Shape After Phase 0

```text
.
├── README.md
├── docs/
│   ├── PRD.md
│   ├── ARCHITECTURE.md
│   ├── GETTING_STARTED.md
│   ├── QUALITY_GATE.md
│   ├── SCENARIO_FORMAT.md
│   └── superpowers/
│       └── plans/
├── examples/
│   ├── scenarios/
│   └── generated/
├── schemas/
├── skills/
└── tools/
```

## Decision Defaults

| Topic | Default |
|---|---|
| Java version | Java 17 until a stronger internal requirement appears |
| Build tool | Maven first, Gradle second |
| Scenario format | YAML with JSON Schema validation |
| Transaction names | `<NN> <domain>.<action> - <human title>` |
| Quality profile | `mvp` first, `engineering` as target |
| Hook fallback | Explicit `quality-gate` command |

## Phase 1 Walkthrough

This section mirrors the E2E acceptance path added in Phase 1. It assumes the
repository root as the working directory.

### 1. Requirements

The example requirements document lives at
`examples/requirements/checkout-mix.md`. Read it to understand the checkout
flow that the generated scenario and simulation cover.

### 2. Scenario from docs (agent workflow)

Invoke the `scenario-from-docs` skill in Gigacode (or run the process manually).
The skill reads the requirements file, asks clarifying questions, and writes
`examples/scenarios/SHOP/checkout-mix-001/scenario.yaml`.

### 3. Lint and render

Verify the scenario is schema-valid and semantically clean:

```bash
python tools/scenario_lint/scenario_lint.py examples/scenarios/SHOP/checkout-mix-001/scenario.yaml --format text
```

Expected output: `examples/scenarios/SHOP/checkout-mix-001/scenario.yaml: passed` (no blocking findings).

Render the reviewer passport:

```bash
python tools/scenario_renderer/scenario_renderer.py examples/scenarios/SHOP/checkout-mix-001/scenario.yaml
```

Review `examples/scenarios/SHOP/checkout-mix-001/passport.md` and confirm with the user
before proceeding.

### 4. Generate with bootstrap into a scratch directory

```bash
python tools/gatling_generator/gatling_generator.py examples/scenarios/SHOP/checkout-mix-001/scenario.yaml <scratch-dir> --format json
```

Replace `<scratch-dir>` with any empty directory. Because there is no `pom.xml`
there, the generator bootstraps a pinned Maven project (Gatling 3.12 /
gatling-maven-plugin 4.21.7) automatically. To use the committed example
project instead:

```bash
python tools/gatling_generator/gatling_generator.py examples/scenarios/SHOP/checkout-mix-001/scenario.yaml examples/generated/checkout-java --format json
```

### 5. Quality gate with smoke run against the mock

Run the full gate including a smoke execution against the local deterministic
mock:

```bash
python tools/quality_gate/quality_gate.py \
    --scenario examples/scenarios/SHOP/checkout-mix-001/scenario.yaml \
    --project examples/generated/checkout-java \
    --profile mvp \
    --smoke \
    --mock-routes examples/scenarios/SHOP/checkout-mix-001/mock.routes.json
```

Expected report status: `passed`. The gate starts `tools/mock_sut`, sets
`BASE_URL`, runs `mvn gatling:test`, stops the mock, and writes
`quality-gate-report.json` and `quality-gate-report.md` into the repository root.

### 6. Installing skills into Gigacode

Skills are agent-facing workflow files. They are not executed directly; the
agent reads them when the matching skill name is invoked.

- **Project-level:** skills already live in `.gigacode/skills/<name>` inside this
  repository.
- **Personal (all projects):** copy `.gigacode/skills/<name>` to
  `~/.gigacode/skills/<name>`.

Tools (`tools/`) stay in this repository and are invoked by relative path from
the project root. The skills reference them as
`python tools/<tool>/<tool>.py ...`.


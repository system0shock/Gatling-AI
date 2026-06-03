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


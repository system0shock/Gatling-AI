# Gatling-AI Workflow for Gigacode

Gatling-AI Workflow is a set of Gigacode skills, commands, hooks, and subagents that help engineers move from requirements or legacy JMeter plans to runnable Gatling OSS simulations in Java. The workflow ships as a `.gigacode/` configuration package that is version-controlled alongside the tools and examples.

The project is currently in documentation-first phase. The immediate target is a narrow foundation:

1. Define the machine-readable scenario contract.
2. Build an HTTP-only end-to-end example.
3. Generate Java Gatling simulations from that scenario.
4. Add a hook-driven quality gate with linters and validator-subagent review.

## Documentation Map

- [PRD](docs/PRD.md) - product scope, goals, requirements, roadmap, risks.
- [Getting Started](docs/GETTING_STARTED.md) - how to begin work from the current repository state.
- [Architecture](docs/ARCHITECTURE.md) - workflow components, artifact flow, and planned repository structure.
- [Scenario Format](docs/SCENARIO_FORMAT.md) - YAML contract, naming rules, validation expectations.
- [Quality Gate](docs/QUALITY_GATE.md) - hooks, linters, statuses, and report format.
- [Phase 0 Plan](docs/superpowers/plans/2026-06-03-phase-0-foundation.md) - implementation plan for the foundation phase.
- [.gigacode/](.gigacode/README.md) - Gigacode configuration package (skills, settings, hooks, agents, commands).

## Current Scope

In scope for the first implementation slice:

- YAML scenario schema.
- HTTP protocol only.
- Java Gatling simulation generation.
- Maven-first local compile/run path.
- Basic `script-style-lint`.
- Quality gate reports in JSON and Markdown.

Out of scope for the first implementation slice:

- Gatling Enterprise.
- Real Confluence publication.
- Kafka/JDBC code generation.
- Full JMeter conversion.
- Remote agents and Jenkins execution.

## Recommended First Move

Start with [Phase 0 Plan](docs/superpowers/plans/2026-06-03-phase-0-foundation.md). It is intentionally small: schema, one example, one generator path, and one quality gate path.


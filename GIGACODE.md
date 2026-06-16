# Gatling-AI — Agent Context

Compact always-on context for Gigacode. The full rules live in `docs/`; this
file is the map and the non-negotiables.

## Working rules

- Gatling **OSS** only (never Enterprise).
- Generate **Java** simulations only.
- **Maven** first (Gatling 3.12, gatling-maven-plugin 4.21.7).
- `scenario.yaml` is the single source of truth — fix problems by editing the
  scenario and regenerating, never by hand-editing generated Java.
- Never invent `system` / `id` / `number`. Ask the user.
- **Never report work done without a quality gate** whose status is `passed` or
  `passed_with_warnings`. `blocked` means not ready — say so with the report path.

## Layout

- `.gigacode/skills/` — agent workflows (model-invoked / `/skills <name>`).
- `.gigacode/agents/` — subagents (read-only `validator-subagent`).
- `.gigacode/commands/` — slash commands (`/quality-gate`).
- `.gigacode/hooks/` — advisory hooks (auto-lint, gate reminder).
- `tools/` — executable checks/generators, invoked as `python tools/<tool>/<tool>.py …`.
- `schemas/` — JSON Schemas (`scenario.schema.json`, `jmx-ir.schema.json`).
- `scenarios/`, `examples/scenarios/` — scenario artifacts.

## Key docs

- `docs/PRD.md`, `docs/ARCHITECTURE.md`, `docs/GETTING_STARTED.md`
- `docs/SCENARIO_FORMAT.md`, `docs/QUALITY_GATE.md`

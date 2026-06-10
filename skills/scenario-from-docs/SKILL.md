---
name: scenario-from-docs
description: Use when turning requirements (dialogue, Markdown/text files) into a machine-readable Gatling-AI scenario YAML. Produces a lint-clean scenario.yaml plus a rendered reviewer doc. Never proceeds to code generation without user approval of the scenario.
---

# Scenario From Docs

Turn requirements into `scenario.yaml` — the single contract consumed by
`scenario-to-gatling`. The schema is `schemas/scenario.schema.json`; the format
reference is `docs/SCENARIO_FORMAT.md`.

## Hard rules

- NEVER guess. Ambiguity → ask the user one question at a time.
- NEVER write Java at this stage. The output of this skill is YAML + rendered doc.
- Unresolved items become `# TODO:` comments in the YAML, visible to reviewers.
- Do not proceed to scenario-to-gatling until the user approves the scenario.

## Process

1. **Collect input.** Read every requirements file the user points at
   (Markdown/text). Everything else comes from dialogue.
2. **Extract entities** using this checklist; tag each one
   `known / inferred (needs confirmation) / unknown`:
   - endpoints (method, path), headers, bodies
   - expected statuses and checks
   - extractions/correlations (what later steps need from earlier responses)
   - test data / feeders (CSV columns, strategies)
   - load profile per population: model (open/closed), profile
     (ramp/constant/soak/stress/spike), numbers
   - think time between steps
   - separate scripts (main flow + background flows) → populations
   - environments and the BASE_URL variable
   - SLA assertions
3. **Ask clarifying questions** — one per message, multiple choice when
   possible. Minimum to proceed: base_url placeholder, steps with checks, a
   load profile, at least one SLA assertion.
4. **Write the scenario** to the project. Naming rules (lint enforces them):
   kebab-case ids/names, transactions `<NN> <domain>.<action> - <Title>`,
   unique across the whole simulation.
5. **Self-check:** run
   `python tools/scenario_lint/scenario_lint.py <scenario>.yaml --format text`
   and fix every blocking finding by editing the YAML.
6. **Render for review:**
   `python tools/scenario_renderer/scenario_renderer.py <scenario>.yaml --output <docs>/<id>.md`
   Show the rendered passport to the user together with the open questions
   list. Iterate until the user approves.

## Output

- Lint-clean `scenario.yaml` (with `# TODO:` comments for unknowns)
- Rendered Markdown passport
- Explicit user approval → hand off to scenario-to-gatling

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
   - system code, scenario id, script number → ask the user; NEVER invent them.
     You may PROPOSE defaults (id from the requirements file name, the next free
     number from scanning `scenarios/<SYSTEM>/`) but only as a question to confirm.
3. **Ask clarifying questions** — one per message, multiple choice when
   possible. Minimum to proceed: base_url placeholder, steps with checks, a
   load profile, at least one SLA assertion.
4. **Write the scenario** to `scenarios/<SYSTEM>/<id>-<NNN>/scenario.yaml`
   (NNN = zero-padded number; feeders as `<feeder-name>.csv` in the same
   folder). Naming rules (lint enforces them): kebab-case ids/names,
   `system` matches `^[A-Z][A-Z0-9]{1,9}$`, transactions
   `<NN> <domain>.<action> - <Title>` with through-numbering across the whole
   simulation, unique `(system, number)` per repository.
5. **Self-check:** run
   `python tools/scenario_lint/scenario_lint.py scenarios/<SYSTEM>/<id>-<NNN>/scenario.yaml --format text`
   and fix every blocking finding by editing the YAML.
6. **Render for review:**
   `python tools/scenario_renderer/scenario_renderer.py scenarios/<SYSTEM>/<id>-<NNN>/scenario.yaml`
   (writes `passport.md` next to the scenario). Show the rendered passport to
   the user together with the open questions list. Iterate until approval.

## Output

- Lint-clean `scenarios/<SYSTEM>/<id>-<NNN>/scenario.yaml` (with `# TODO:` comments for unknowns)
- Co-located `passport.md` rendered next to the scenario
- Explicit user approval → hand off to scenario-to-gatling

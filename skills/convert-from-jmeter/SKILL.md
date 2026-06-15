---
name: convert-from-jmeter
description: Use when converting a documented legacy JMeter test (approved migration passport) into a runnable Gatling simulation. Orchestrates the deterministic ir_to_scenario tool (pass 1), a lint + report review gate, agent translation of JSR223 todo hooks (pass 2), then hands off to scenario-to-gatling. Disposition must reconcile 100% — no silent drops.
---

# Convert From JMeter

Drive an approved legacy passport to a runnable simulation through review gates.
The deterministic tools own the mechanical ~90 %; the agent translates only what
needs judgement (JSR223), one block at a time, with the user approving each.

## Preconditions

- An approved `migration/passport.md` exists (from `document-legacy-jmeter`).
  Without it, send the user there first.
- `migration/ir.json` exists (parser output). The agent never reads the raw `.jmx`
  or the full `ir.json` — it works from the passport, `conversion-report.md`, and
  parser slices.

## Process

1. **Gate 0.** Confirm `system` / `id` / `number` (NEVER invent). Use the migration
   folder `scenarios/<SYSTEM>/<id>-<NNN>/`.
2. **Pass 1 — deterministic conversion:**
   `python tools/ir_to_scenario/ir_to_scenario.py scenarios/<SYSTEM>/<id>-<NNN>/migration/ir.json --system <SYSTEM> --id <id> --number <NNN> --out-dir scenarios/<SYSTEM>/<id>-<NNN>`
   Writes `scenario.yaml` + `conversion-report.md`. If it exits 1, read the blocking
   finding (e.g. a non-normalizable thread-group load) and resolve with the user —
   do not force past it. Idempotency: with existing artifacts it refuses to
   overwrite without `--force`; review the diff before re-running.
3. **Copy data dependencies** the scenario references: feeder CSVs next to the
   scenario (named `<feeder-name>.csv`); externalized request bodies into `bodies/`.
   Tag kafka-via-proxy HTTP steps with `tags: [kafka-via-proxy]`.
4. **Gate 3 — lint + report review.** Run
   `python tools/scenario_lint/scenario_lint.py scenarios/<SYSTEM>/<id>-<NNN>/scenario.yaml --format text`
   and review `conversion-report.md`: confirm the disposition sum reconciles with
   `inventory.md` (no silent drop) and ≥ 80 % auto for simple scripts. A consumed
   `${var}` that has no extractor / feeder / env producer is a blocking lint finding —
   resolve it by adding the missing producer to the source, not by hand-editing.
   Refine transaction names from the mask to the business names in the passport.
5. **Pass 2 — JSR223 translation.** For each `kind: todo` hook, show the original
   Groovy (`migration/jsr223/*.groovy`) plus context (vars in/out, passport
   description). Translate it into a standalone Java class file
   `snippets/<PascalCaseName>.java` (the file stem is the class name) with a
   `public static Session apply(Session session)` method that returns an updated
   session — Gatling `Session` is immutable, so `return session.set("var", ...)`.
   The generator wires it as `exec(<ClassName>::apply)`. On user approval, save the
   file, set the hook `kind: translated` with `snippet: snippets/<PascalCaseName>.java`,
   and update the report. Stopping on any block is fine — the rest stay explicit
   `todo` (→ `manual_review_required`).
6. **Final — hand off to `scenario-to-gatling`** (bootstrap/generate, render
   passport, compile, optional smoke, quality gate). Remaining `todo` hooks make the
   gate `passed_with_warnings`, not a clean `passed`; report the status and the
   report path honestly.

## Output

- `scenarios/<SYSTEM>/<id>-<NNN>/scenario.yaml` (lint-clean, schema-valid)
- `conversion-report.md` with a reconciled disposition table
- `snippets/*.java` for translated JSR223 (when pass 2 ran)
- Hand-off to `scenario-to-gatling` for the runnable simulation + quality gate

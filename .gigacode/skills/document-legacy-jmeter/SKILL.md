---
name: document-legacy-jmeter
description: Use when documenting a legacy JMeter .jmx as a reviewable passport BEFORE any conversion. Runs the deterministic jmx_parser, reviews the inventory (Gate 1), optionally reconciles with Confluence, and writes a curated migration passport (Gate 2). Documentation only — never writes scenario.yaml or Java.
---

# Document Legacy JMeter

Turn an opaque legacy `.jmx` into a reviewed, human-readable passport. The IR from
`jmx_parser` is the source of truth; the agent works only with curated slices
(`inventory.md`, `--summary`, `--element <id>`), never the raw `.jmx` or the full
`ir.json`.

## Hard rules

- NEVER read the raw `.jmx` or the full `ir.json` into context — only parser slices.
- NEVER guess business meaning. Ambiguity → ask the user one question at a time.
- Confluence is context, not truth. "Docs say X, script does Y" → a Discrepancies
  section in the passport, never silently resolved.
- This skill stops at the passport. Conversion is `convert-from-jmeter`.

## Process

1. **Ask** for the `.jmx` path (kept outside the repo) and the target
   `system` / `id` / `number` (NEVER invent them). Migration artifacts go under
   `scenarios/<SYSTEM>/<id>-<NNN>/migration/`.
2. **Parse:**
   `python tools/jmx_parser/jmx_parser.py parse <plan.jmx> --out-dir scenarios/<SYSTEM>/<id>-<NNN>/migration --format json`
3. **Gate 1 — review `inventory.md`.** Show it to the user. If it lists complexity
   flags (staged thread groups, inter-thread `props`, unresolved Module Controller,
   unknown plugins, standalone JSR223 sampler), announce the **careful path**: every
   gate is an explicit stop, no auto-advance. Note: Module Controllers with resolved
   targets and multi-row Ultimate Thread Groups with non-overlapping rows are now
   handled automatically by the converter — they no longer require the careful path
   unless the target is unresolved or the rows overlap.
4. **Inspect details on demand** (subcommands of the same tool) —
   `python tools/jmx_parser/jmx_parser.py summary <ir.json>` and
   `python tools/jmx_parser/jmx_parser.py element <ir.json> e-NNNN` — never dump the
   whole tree.
5. **Optional Confluence.** If the user gives a page, read it via the Atlassian MCP
   (fallback: a file export). Use it only to enrich/contrast the passport.
6. **Write `migration/passport.md`** (scenario-passport style plus legacy sections):
   purpose & business process; transaction table (original name → proposed
   `NN domain.action - Title` mask); per-step data flow (from `variable_index`
   slices); JSR223 table (what each does, reads/writes, typical/complex); load
   profile in words; env config from UDV; dependencies (CSV, properties,
   proxy-Kafka); Confluence discrepancies; unsupported elements.
7. **Gate 2 — passport approval.** Iterate until the user approves. Then either stop
   (documentation-only) or hand off to `convert-from-jmeter`.

## Output

- `scenarios/<SYSTEM>/<id>-<NNN>/migration/` populated by the parser
  (`ir.json`, `inventory.md`, `bodies/`, `jsr223/*.groovy`).
- `scenarios/<SYSTEM>/<id>-<NNN>/migration/passport.md` — the curated, approved
  legacy passport (Gate 2 artifact). NOTE: this is distinct from the top-level
  `passport.md` that `scenario-to-gatling` renders from `scenario.yaml` and the
  quality gate validates — do not overwrite that file from here.

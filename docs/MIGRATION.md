# Migration: JMeter → Gatling-AI Scenario

## Role in the pipeline

`tools/ir_to_scenario/ir_to_scenario.py` is the second stage of the Phase-2
migration pipeline:

```
.jmx  →  [jmx_parser]  →  ir.json  →  [ir_to_scenario]  →  scenario.yaml
                                                          →  conversion-report.md
```

`jmx_parser` produces a language-neutral Intermediate Representation (IR) of
a JMeter test plan.  `ir_to_scenario` walks that IR and maps each element to
the Phase-2b `scenario.yaml` contract, recording a **disposition** for every
element so that nothing is silently dropped.

The resulting `scenario.yaml` is then refined by the Gatling-AI agent skill
(Phase 2c-2): transaction names are improved, JSR223 hooks are translated to
Groovy/Scala, and the `kafka-via-proxy` tag is applied where appropriate.

## Disposition statuses

Every IR element receives exactly one of four disposition labels:

| Status | Meaning |
|---|---|
| `converted` | Fully mapped; no manual work required. |
| `partial` | Mapped with caveats — see the note column in the report table. Manual review is needed (e.g. form params, multiple OR-ed response-code patterns, boundary extractor with no contract type). |
| `todo` | Cannot be expressed in the Phase-2b contract at all and requires agent translation (e.g. standalone `jsr223_sampler` nodes, unknown element kinds). |
| `skipped-disabled` | The element (or its parent) was disabled in JMeter; nothing is emitted. |
| `inlined` | A Module Controller's target subtree was inlined into the current population's step list. The report records the source target ID. |

## Reconciliation guarantee

After the conversion walk, `ir_to_scenario` asserts:

```
sum(disposition_counts.values()) == ir.stats.elements_total
```

If this invariant is violated (a silent drop or double-count), a blocking
finding with rule `convert.disposition-mismatch` is appended to the report and
`main()` exits with code 1.  This ensures the `conversion-report.md` is always
a 1:1 inventory of the IR, matching the `inventory.md` produced by `jmx_parser`.

## CLI usage

```powershell
python tools/ir_to_scenario/ir_to_scenario.py ir.json \
    --system SHOP \
    --id checkout-mix \
    --number 1 \
    --out-dir out/

# Overwrite an existing scenario.yaml:
python tools/ir_to_scenario/ir_to_scenario.py ir.json \
    --system SHOP --id checkout-mix --number 1 \
    --out-dir out/ --force
```

Exit codes:
- `0` — conversion complete, no blocking findings.
- `1` — conversion complete, but one or more blocking findings (see `conversion-report.md`).
- `2` — refused to overwrite an existing `scenario.yaml`; use `--force` to proceed.

## Extended fields and features (2026-07-20)

### `unsupported[].raw_props`

Unknown JMeter elements (`kind: unknown`) now capture their configuration
properties in a `raw_props` object (string → string/list). This allows reviewers
and agents to see *what* an unknown plugin was configured to do, not just that
it existed. `collectionProp` children are serialized as lists; nested `hashTree`
is skipped.

### CSV feeder options

`csv_details` now captures additional JMeter `CSVDataSet` options beyond
`file`/`variable_names`/`stop_thread`:

| JMeter option | Scenario field | Gatling equivalent |
|---|---|---|
| `delimiter` | `delimiter` | `.separator()` |
| `ignoreFirstLine` | `ignore_first_line` | `.skipHeaderRow()` |
| `quotedData` | `quoted_text` | `.quote()` |
| `shareMode` | `share_mode` | **TODO** (no Gatling equivalent) |
| `recycle` | `recycle` | **TODO** (no Gatling equivalent) |
| `randomOrder` | `random_order` | **TODO** (no Gatling equivalent) |

Options without a Gatling equivalent emit a `// TODO: <option>=<value> — no
Gatling equivalent; review` comment in the generated Java.

### `hooks[].hints` (intent_hints)

Complex JSR223 scripts and inline FIFO functions (`${__fifoPut(...)}`, etc.)
produce structured `intent_hints[]` arrays. Each hint has a `kind` (e.g.
`var_put`, `var_get`, `prop_get`, `prev_call`, `log_call`, `branch`,
`external_call`, `fifo_put`, `fifo_pop`) and relevant fields (`var`, `expr`,
`fifo`, `save_as`, `timeout`, `key`, `method`, `level`, `summary`).

Hints are deterministic and conservative: unrecognized patterns stay in
`script_preview` and the externalized `.groovy` file. Hints augment, never
replace, the source.

### `fifo-cross-thread` complexity flag

When any `fifo_put_post` / `fifo_pop_pre` element is present OR inline FIFO
functions are detected, the IR carries a `fifo-cross-thread` complexity flag.
The `inventory.md` header lists the unique queue names and the element/sampler
IDs that reference them. Cross-thread FIFO has no Gatling equivalent (sessions
are per-VU); it surfaces as a `kind: todo` hook with structured `hints`, not as
fake step logic.

### `test_plan.serialize_threadgroups`

The `TestPlan.serialize_threadgroups` boolean is captured in the IR and shown
in the `inventory.md` header next to the test plan name.

### Pass 2 translation rule

When translating JSR223 hooks (Pass 2, `convert-from-jmeter` skill):

1. If `hints` cover the whole script, translate from `hints` only and verify
   against the original Groovy.
2. If `hints` is empty or partial, read the original `jsr223/<sha>.groovy` and
   translate as before.

This gives weak models (35B-class) structured facts to translate from, reducing
over-reach and mis-translation.

## Module Controller inlining (2026-07-21)

When `ir_to_scenario` encounters a `kind: module` element, it reads the
`target_id` resolved by the parser and inlines the target's children into the
current population's step list. The conversion report records the disposition as
`converted` with a note naming the inlined target. Unresolved targets
(parser could not match the name path) are recorded as `partial`. Cycles (a
module target that transitively includes the same module) are detected via a
visited-set and recorded as `partial` with a cycle note.

Supported target kinds: `fragment`, `thread_group`, `transaction`, `simple`,
and any controller with children. Nested module controllers are inlined
recursively. If two Module Controllers target the same element, only the first
inlines it; the second is recorded as `partial` to avoid double-counting.

## Attribution

Element-mapping rules for HTTP functions, extractors, redirects, and CSV
`shareMode` are adapted from Gatling's Apache-2.0 `gatling-convert-from-jmeter`
skill (`github.com/gatling/gatling-ai-extensions`).  The contract-first pipeline
(IR → `scenario.yaml` → generator), the disposition ledger, and the
reconciliation guarantee are original to this project.

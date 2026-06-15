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

## Attribution

Element-mapping rules for HTTP functions, extractors, redirects, and CSV
`shareMode` are adapted from Gatling's Apache-2.0 `gatling-convert-from-jmeter`
skill (`github.com/gatling/gatling-ai-extensions`).  The contract-first pipeline
(IR → `scenario.yaml` → generator), the disposition ledger, and the
reconciliation guarantee are original to this project.

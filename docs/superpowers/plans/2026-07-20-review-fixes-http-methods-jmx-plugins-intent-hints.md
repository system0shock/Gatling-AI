# Review Fixes: HTTP methods, JMeter plugin elements, intent_hints — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the three gaps surfaced by the live Qwen3.6 test
(`docs/superpowers/notes/2026-06-16-qwen-code-live-test-results.md`) and by
real-world JMeter plans that use custom plugins:

1. **HTTP methods** — `scenario_lint` and `gatling_generator` only accept
   `GET`/`POST`, blocking migration of any plan with `PUT`/`PATCH`/`DELETE`/
   `HEAD`/`OPTIONS`.
2. **Custom JMeter plugin elements** — Inter-Thread Communication (FIFO) and
   `HTTPRawSampler` fall into `kind: unknown`; CSV `DataSet` config options are
   dropped. Reviewer-facing passports lose this information.
3. **Complex script logic for weak models** — complex JSR223 scripts become
   `kind: todo` hooks that the agent must translate from raw Groovy; a 35B
   local model cannot reliably do this. Provide a deterministic
   `intent_hints` layer so the agent translates from structured facts.

**Architecture:** The Phase-2 pipeline stays deterministic and contract-first.
The plan extends the existing IR (`schemas/jmx-ir.schema.json`), the
`scenario.yaml` contract (`schemas/scenario.schema.json`), and the three
consumers (`jmx_parser`, `ir_to_scenario`, `scenario_lint` /
`scenario_renderer` / `gatling_generator`). No new top-level tool is created.
Cross-thread FIFO remains non-representable in the flat Gatling contract
(Gatling sessions are per-VU) — it stays a `kind: todo` hook with structured
`hints` plus a deterministic `fifo-cross-thread` complexity flag; the agent
(or engineer) decides on a real queue (Redis / SUT-side) at translation time.

**Tech Stack:** Python 3.11+ stdlib, PyYAML, existing `tools/_shared/common.py`
helpers; `unittest` run directly; inputs validated against
`schemas/jmx-ir.schema.json`; outputs validated against
`schemas/scenario.schema.json`; `tools/test_contract_coverage.py` enforces
schema↔consumer coverage.

## Global Constraints

- The Phase-2b `scenario.yaml` contract stays executable: any new field
  consumed by `gatling_generator` MUST have a code path or an explicit
  TODO-comment path — never a silent drop.
- Cross-thread communication (FIFO) is NOT expressible in Gatling; it MUST
  surface as a `todo` hook + complexity flag, not as fake step logic.
- `intent_hints` are deterministic and conservative: whatever is not
  recognized stays in `script_preview`; the agent always has access to the
  original script. `intent_hints` augment, never replace, the source.
- Python 3.11+ and existing pinned dependencies only; no new runtime packages.
- Schema enums are uppercase for HTTP methods; kebab-case for IR kinds.

---

## Source-of-truth references

- Live-test findings: `docs/superpowers/notes/2026-06-16-qwen-code-live-test-results.md`.
- Methodology design (evidence-first pattern reused for `intent_hints`):
  `docs/superpowers/specs/2026-07-19-load-testing-methodology-generation-design.md`.
- Pipeline + disposition ledger: `docs/MIGRATION.md`.
- IR shape: `schemas/jmx-ir.schema.json` (`KIND_BY_TESTCLASS`, `unsupported[]`,
  `test_plan`, jsr223 fields).
- Scenario contract: `schemas/scenario.schema.json` (`steps[].request.method`,
  `data.feeders[]`, `$defs/hooks`).
- Plugin reference plan: `SynchronizationPluginsExample.jmx`
  (https://jmeter-plugins.org/img/examples/SynchronizationPluginsExample.jmx) —
  canonical source of the JP@GC Inter-Thread Communication testclasses.

## Final file structure (touched files)

```text
schemas/jmx-ir.schema.json                         # enum kind, unsupported.raw_props, test_plan.serialize_threadgroups, intent_hints
schemas/scenario.schema.json                       # method enum, feeders[] options, hooks[].hints
tools/jmx_parser/jmx_parser.py                     # KIND_BY_TESTCLASS, csv_details, classify_jsr223, detail builders, complexity flag
tools/jmx_parser/jmx_inventory.py                  # render raw_props, serialize_threadgroups, fifo flag
tools/jmx_parser/test_jmx_parser.py                # new cases
tools/ir_to_scenario/ir_to_scenario.py             # fifo todo-hooks, http_raw_sampler, csv options, intent_hints plumbing, raw_props column
tools/ir_to_scenario/test_ir_to_scenario.py        # new cases
tools/scenario_lint/scenario_lint.py               # _SUPPORTED_METHODS
tools/scenario_lint/test_scenario_lint.py         # rewrite UnsupportedMethodLintTest
tools/gatling_generator/gatling_generator.py       # method→method_call mapping, feeder options
tools/gatling_generator/test_gatling_generator.py  # per-method + feeder cases
tools/scenario_renderer/scenario_renderer.py       # CSV options columns, hints section
tools/scenario_renderer/test_scenario_renderer.py # new cases
tools/test_contract_coverage.py                   # only consumed-sets; no logic
.gigacode/skills/convert-from-jmeter/SKILL.md      # Pass 2 instruction: translate from hints
docs/PRD.md                                       # FR2.2 method/element list
docs/MIGRATION.md                                 # document new fields
```

---

## Task 1: Full HTTP method set (lint + generator + schema)

**Files:**
- Modify: `tools/scenario_lint/scenario_lint.py`
- Modify: `tools/gatling_generator/gatling_generator.py`
- Modify: `schemas/scenario.schema.json`
- Modify: `tools/scenario_lint/test_scenario_lint.py`
- Modify: `tools/gatling_generator/test_gatling_generator.py`

**Background:** `scenario_lint.py:614` hardcodes `_SUPPORTED_METHODS = {"GET","POST"}`
and emits a blocking `scenario-lint.unsupported-method` for anything else.
`gatling_generator.py:373` `raise ValueError("unsupported HTTP method")`.
`ir_to_scenario.py:494` `fill_http` already passes the JMeter method through
unchanged — so a JMeter plan with `PUT` produces a `scenario.yaml` that the
linter immediately blocks and the generator raises on. End-to-end migration is
broken for non-GET/POST. The lint branch at `scenario_lint.py:625` already
treats `PUT`/`PATCH`/`DELETE` as mutating for the status-check rule, which is
dead code today because those methods are rejected at line 614.

- [ ] **Step 1.1: Expand the lint allowlist.** In `scenario_lint.py:614`,
  replace `_SUPPORTED_METHODS = {"GET", "POST"}` with
  `_SUPPORTED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}`.
  Leave the mutating-status-check branch at `:625` as-is — it is now live for
  `{POST, PUT, PATCH, DELETE}`. Run `test_scenario_lint.py` — expect
  `UnsupportedMethodLintTest` to fail (that's the signal to rewrite it next).

- [ ] **Step 1.2: Rewrite `UnsupportedMethodLintTest`.** In
  `tools/scenario_lint/test_scenario_lint.py:418`, replace the cases so the
  rule now asserts that `GET`/`POST`/`PUT`/`PATCH`/`DELETE`/`HEAD`/`OPTIONS`
  pass, and that `TRACE`/`CONNECT`/`"FOO"` still raise
  `scenario-lint.unsupported-method`.

- [ ] **Step 1.3: Map methods in the generator.** In
  `gatling_generator.py:370`–`:374` (`request_chain`), replace the
  `if method not in {"GET","POST"}: raise` with a method→call mapping:
  `{"GET":"get","POST":"post","PUT":"put","PATCH":"patch","DELETE":"delete","HEAD":"head","OPTIONS":"options"}`.
  Unknown methods still raise `ValueError("unsupported HTTP method: …")`.

- [ ] **Step 1.4: Pin the schema enum.** In `schemas/scenario.schema.json:161`
  change `method: { "type": "string", "minLength": 1 }` to
  `{ "type": "string", "enum": ["GET","POST","PUT","PATCH","DELETE","HEAD","OPTIONS"] }`.
  Run `python tools/scenario_lint/test_scenario_lint.py`,
  `python tools/gatling_generator/test_gatling_generator.py`,
  `python tools/test_contract_coverage.py`.

- [ ] **Step 1.5: Per-method generator tests.** Add cases in
  `test_gatling_generator.py` that assert the emitted `.get/.post/.put/.patch/
  .delete/.head/.options(...)` call matches the input method.

---

## Task 2: Generic `raw_props` for unsupported elements

**Files:**
- Modify: `tools/jmx_parser/jmx_parser.py`
- Modify: `schemas/jmx-ir.schema.json`
- Modify: `tools/jmx_parser/jmx_inventory.py`
- Modify: `tools/ir_to_scenario/ir_to_scenario.py`
- Modify: `tools/jmx_parser/test_jmx_parser.py`

**Background:** `jmx_parser.py:1082` records `kind: unknown` elements into
`state.unsupported` with only `id`/`type`/`name`/`path`. The element's
configuration props are lost — so a reviewer can see *that* an unknown plugin
existed, but not *what it was configured to do*. Capturing raw props lets the
agent and the reviewer reason about even unmodeled plugins, and gives
`ir_to_scenario` something to put in the conversion report.

- [ ] **Step 2.1: Extend the IR schema.** In `schemas/jmx-ir.schema.json:71`–`:84`
  (`unsupported` items), add an optional
  `"raw_props": { "type": "object" }` (free-form string→string/list dict). The
  `additionalProperties: false` already there must be updated to include the
  new key.

- [ ] **Step 2.2: Collect raw_props for unknown kinds.** In `jmx_parser.py`
  where `kind == "unknown"` (around `:1082`), collect all direct
  `stringProp` children of the element into a `raw_props` dict (name → text).
  `collectionProp` children are serialized as a list of their `stringProp`
  texts. Skip nested `hashTree` (they are walked separately). Attach
  `raw_props` to the `unsupported` entry only when non-empty.

- [ ] **Step 2.3: Render raw_props in inventory.** In `jmx_inventory.py:47`–`:52`
  (`## Unsupported elements`), append the prop names in parentheses when
  `raw_props` is present: `` `type` — name (id, at path; props: a, b, c) ``.

- [ ] **Step 2.4: Surface raw_props in conversion report.** In
  `ir_to_scenario.py:226` (`walk_children` TODO branch) and in
  `render_report`, when a TODO node carries `raw_props` (passed through from
  the IR element), add a «Свойства» column or a sub-line listing the prop keys
  and values (truncated to ~120 chars per value to bound the report size).

- [ ] **Step 2.5: Tests.** In `test_jmx_parser.py:53`
  (`test_unknown_element_is_recorded_not_dropped`), assert that an unknown
  element with `<stringProp name="Foo">bar</stringProp>` produces
  `unsupported[0].raw_props == {"Foo": "bar"}`. Add a case for
  `collectionProp` serialization.

---

## Task 3: First-class JP@GC Inter-Thread Communication + HTTPRawSampler

**Files:**
- Modify: `tools/jmx_parser/jmx_parser.py`
- Modify: `schemas/jmx-ir.schema.json`
- Modify: `tools/jmx_parser/jmx_inventory.py`
- Modify: `tools/ir_to_scenario/ir_to_scenario.py`
- Modify: `tools/jmx_parser/test_jmx_parser.py`
- Modify: `tools/ir_to_scenario/test_ir_to_scenario.py`

**Background:** The JP@GC Inter-Thread Communication plugin
(https://jmeter-plugins.org/wiki/InterThreadCommunication/) exposes global
FIFO string queues for cross-thread / cross-Thread-Group synchronization. It
has two element flavours and four inline functions:

- `kg.apc.jmeter.modifiers.FifoPutPostProcessor` (PostProcessor) — props
  `Value`, `FifoName`.
- `kg.apc.jmeter.modifiers.FifoPopPreProcessor` (PreProcessor) — props
  `Variable`, `FifoName`, `Timeout`.
- Inline functions `${__fifoPut(name,val)}`, `${__fifoPop(name,var)}`,
  `${__fifoGet(name,var)}`, `${__fifoSize(name,var)}` used in any stringProp.
- (Separately) `kg.apc.jmeter.samplers.HTTPRawSampler` — raw HTTP/1.x request
  text; props `hostname`, `port`, `data`, `keepalive`, `timeout`, `parse`.

Cross-thread FIFO has no Gatling equivalent (sessions are per-VU), so it stays
a `kind: todo` hook with structured `hints`; a `fifo-cross-thread` complexity
flag makes the blocker visible in `inventory.md`.

- [ ] **Step 3.1: Add the new kinds.** In `jmx_parser.py:129`
  (`KIND_BY_TESTCLASS`), add:
  `"kg.apc.jmeter.modifiers.FifoPutPostProcessor": "fifo_put_post"`,
  `"kg.apc.jmeter.modifiers.FifoPopPreProcessor": "fifo_pop_pre"`,
  `"kg.apc.jmeter.samplers.HTTPRawSampler": "http_raw_sampler"`.
  Extend the `kind` enum in `schemas/jmx-ir.schema.json:18` with these three
  values.

- [ ] **Step 3.2: Detail builders.** In `jmx_parser.py` `DETAIL_BUILDERS`,
  add:
  - `fifo_put_post`: read `Value` and `FifoName` stringProps; emit
    `{"value": ..., "fifo_name": ...}`.
  - `fifo_pop_pre`: read `Variable`, `FifoName`, `Timeout`; emit
    `{"variable": ..., "fifo_name": ..., "timeout": <int or None>}`.
  - `http_raw_sampler`: read `hostname`, `port`, `data`, `keepalive`,
    `timeout`, `parse`; emit them as fields.

- [ ] **Step 3.3: Cross-thread FIFO complexity flag.** In `jmx_parser.py:966`
  (the `complexity_flags` builder), add a `fifo-cross-thread` flag whenever
  any `fifo_put_post` / `fifo_pop_pre` element is present OR
  `variables.functions` contains `__fifoPut` / `__fifoPop` / `__fifoGet` /
  `__fifoSize`. `details` lists the unique queue names and the element ids or
  sampler ids that reference them.

- [ ] **Step 3.4: Capture `serialize_threadgroups`.** In
  `schemas/jmx-ir.schema.json` `test_plan` (`:61`–`:69`), add
  `"serialize_threadgroups": { "type": "boolean" }`. In `jmx_parser.py` where
  the `TestPlan` element is parsed, read the `TestPlan.serialize_threadgroups`
  boolProp and attach it. In `jmx_inventory.py`, show the value next to the
  test plan name in the inventory header.

- [ ] **Step 3.5: IR → scenario mapping for FIFO.** In
  `ir_to_scenario.py` `checks_from_children` (sampler-children scan, `:425`+)
  and `walk_steps`, recognize the new kinds:
  - `fifo_put_post` child of a sampler → append a `kind: todo` hook to
    `step.hooks.after[]` with `ref: "<ref_prefix>/fifo/<id>"` (no script file —
    leave `ref` empty or a synthetic marker), `summary`, and `hints: [{"kind":
    "fifo_put", "fifo": <name>, "value": <value or "${...}"}]`. Record
    CONVERTED.
  - `fifo_pop_pre` child of a sampler → append a `kind: todo` hook to
    `step.hooks.before[]` with `hints: [{"kind": "fifo_pop", "fifo": <name>,
    "save_as": <variable>, "timeout": <int>}]` and add `<variable>` to the
    hook's `writes`. Record CONVERTED.
  - If `fifo_put_post` / `fifo_pop_pre` appear outside a sampler (directly
    under a TG or controller), record PARTIAL with note «FIFO element outside
    a sampler; attach to a step manually» and do not descend.

- [ ] **Step 3.6: IR → scenario mapping for HTTPRawSampler.** In
  `ir_to_scenario.py` `build_step` (`:346`), add a branch for
  `http_raw_sampler`: emit an http step with
  `request = {"method": "GET", "path": <hostname+port+path-from-data or "/">,
  "body": <data>}` and record PARTIAL with note «raw HTTP/1.x request text;
  manual review — method/path/headers must be parsed from the raw text».
  Add `http_raw_sampler` to `SAMPLER_KINDS` only if it should produce a step
  (it should).

- [ ] **Step 3.7: Tests.** In `test_jmx_parser.py`, add cases for each new
  kind (parses, props extracted), the `fifo-cross-thread` flag (fires for both
  element and inline-function usage), and `test_plan.serialize_threadgroups`.
  In `test_ir_to_scenario.py`, add cases asserting: `fifo_put_post` →
  after-todo-hook with the right hints; `fifo_pop_pre` → before-todo-hook
  with `writes` containing the variable; `http_raw_sampler` → http step with
  PARTIAL disposition.

- [ ] **Step 3.8: Smoke on the real example.** Download
  `SynchronizationPluginsExample.jmx` into a temp dir, run
  `python tools/jmx_parser/jmx_parser.py parse <file> --out-dir <tmp> --format json`,
  then `python tools/ir_to_scenario/ir_to_scenario.py <tmp>/ir.json --system
  SYNC --id fifo-example --number 1 --out-dir <tmp2>`. Confirm
  `inventory.md` shows the `fifo-cross-thread` flag and `serialize_threadgroups`,
  and `conversion-report.md` shows the two FIFO elements as CONVERTED todo-hooks.

---

## Task 4: CSV feeder options in the contract

**Files:**
- Modify: `tools/jmx_parser/jmx_parser.py`
- Modify: `schemas/jmx-ir.schema.json`
- Modify: `schemas/scenario.schema.json`
- Modify: `tools/ir_to_scenario/ir_to_scenario.py`
- Modify: `tools/gatling_generator/gatling_generator.py`
- Modify: `tools/scenario_renderer/scenario_renderer.py`
- Modify: `tools/test_contract_coverage.py`
- Modify: relevant test files

**Background:** `csv_details` (`jmx_parser.py:554`) only captures `file`,
`variable_names`, `stop_thread`. JMeter `CSVDataSet` has more options
(`delimiter`, `ignoreFirstLine`, `quotedData`, `shareMode`, `recycle`,
`randomOrder`, `enforceRFC4180`) that affect runtime semantics. The scenario
contract currently stores only `name`/`file`/`strategy`, so the passport and
the generated feeder lose them.

- [ ] **Step 4.1: Capture CSV options in the parser.** In `csv_details`
  (`jmx_parser.py:554`), read `delimiter`, `CSVDataSet.ignoreFirstLine`,
  `CSVDataSet.quotedData`, `CSVDataSet.shareMode`, `CSVDataSet.recycle`,
  `CSVDataSet.randomOrder`, `CSVDataSet.enforceRFC4180`. Attach to the
  `csv_data_set` element's details. The `jmx-ir.schema.json` csv fields are
  free-form (`additionalProperties`), so no schema change is strictly needed,
  but document the new fields in the schema with a comment.

- [ ] **Step 4.2: Extend the scenario contract.** In
  `schemas/scenario.schema.json` `data.feeders[]`, add optional fields:
  `delimiter` (string), `ignore_first_line` (boolean), `quoted_text` (boolean),
  `share_mode` (enum: `all` / `threads` / `group`), `recycle` (boolean),
  `random_order` (boolean). All optional; default values documented in the
  schema.

- [ ] **Step 4.3: Plumb options through `ir_to_scenario`.** In
  `ir_to_scenario.py:564` (`build_data_and_env` csv branch), emit the
  non-default options into the `feeders[]` entry. Map JMeter names to the
  contract names: `ignoreFirstLine`→`ignore_first_line`, `quotedData`→
  `quoted_text`, `shareMode`→`share_mode`, `randomOrder`→`random_order`.

- [ ] **Step 4.4: Emit explicit feeder options in the generator.** In
  `gatling_generator.py:288` (feeder builder), for non-default options emit
  the corresponding Gatling `CsvFeederBuilder` calls where the API supports
  them (delimiter, skipHeaderRow, quoted); for options without a Gatling
  equivalent (`share_mode`, `recycle`, `random_order`), emit a `// TODO:
  <option>=<value> — no Gatling equivalent; review` comment on the feeder
  line. Never silently drop.

- [ ] **Step 4.5: Render options in the passport.** In
  `scenario_renderer.py` (the «Тестовые данные» table), add columns for the
  non-default options only when they are present in the feeder (so default
  feeders stay compact).

- [ ] **Step 4.6: Contract coverage.** Add the new feeder field paths to
  `scenario_renderer.SCENARIO_CONSUMED_FIELDS` / `STEP_LOAD_CONSUMED` (and
  the generator's equivalent) so `tools/test_contract_coverage.py` stays green.

- [ ] **Step 4.7: Tests.** Extend `test_jmx_parser.py:363`
  (`test_csv_data_set`) to assert the new fields. Extend
  `test_ir_to_scenario.py:289` (`test_csv_no_variable_names_is_partial`) with
  a case that non-default options flow through. Add a `scenario_renderer`
  case for a feeder with `delimiter=;` and `ignore_first_line=true`. Add a
  `gatling_generator` case asserting the TODO comment for `share_mode`.

---

## Task 5: `intent_hints` for complex JSR223 and inline FIFO functions

**Files:**
- Modify: `tools/jmx_parser/jmx_parser.py`
- Modify: `schemas/jmx-ir.schema.json`
- Modify: `schemas/scenario.schema.json`
- Modify: `tools/ir_to_scenario/ir_to_scenario.py`
- Modify: `tools/scenario_renderer/scenario_renderer.py`
- Modify: `.gigacode/skills/convert-from-jmeter/SKILL.md`
- Modify: relevant test files

**Background:** Complex JSR223 scripts are classified as `complex`
(`jmx_parser.py:702`) and become `kind: todo` hooks (`ir_to_scenario.py:325`).
The `convert-from-jmeter` skill expects the agent to read the original Groovy
plus context and emit a Java snippet. For a 35B-class model this is the
hardest step and the place where the live test showed over-reach and
mis-translation. A deterministic `intent_hints[]` layer extracted from the
script gives the model structured facts to translate from. The same extractor
handles inline `${__fifoPut(...)}` / `${__fifoPop(...)}` functions so FIFO
hints (Task 3) and JSR223 hints share one representation.

Target models (per user): DeepSeek v4 flash, Minimax M3, Qwen3.6 35b — all
local/cheap; `intent_hints` must carry enough that a weak model can translate
without re-reading Groovy when `hints` cover the whole script.

- [ ] **Step 5.1: Extend the IR schema.** In `schemas/jmx-ir.schema.json`,
  for the jsr223 kinds (`jsr223_sampler`, `jsr223_pre`, `jsr223_post`) and
  for any element that carries stringProp values (http_sampler,
  csv_data_set, fifo_put_post, fifo_pop_pre), add an optional
  `intent_hints: array` of objects. Each hint object has a `kind` (string) and
  free-form fields (`var`, `expr`, `fifo`, `save_as`, `timeout`, `key`,
  `method`, `level`, `summary`).

- [ ] **Step 5.2: Static extractor for Groovy.** In `jmx_parser.py` near
  `classify_jsr223` (`:702`), add `extract_intent_hints(script: str) ->
  list[dict]`. Conservative regex-based, no Groovy parser:
  - `vars.put("X", expr)` → `{"kind":"var_put","var":"X","expr":expr}`.
  - `vars.get("X")` → `{"kind":"var_get","var":"X"}`.
  - `props.put("K", expr)` / `props.get("K")` → `{"kind":"prop_put"/"prop_get",
    "key":"K"}`.
  - `prev.getResponseData()` / `getResponseCode()` / `getResponseHeaders()` /
    `isSuccessful()` / `getURL()` → `{"kind":"prev_call","method":...}`.
  - `log.info/warn/error(...)` → `{"kind":"log_call","level":...}`.
  - `if (cond)` / `for (...)` / `while (...)` → `{"kind":"branch",
    "summary":"if (cond)"}` (first ~80 chars of the condition).
  - `new URL(...)` / `Class.forName(...)` / `SampleResult(...)` →
    `{"kind":"external_call","expr":...}`.
  Anything unmatched is left out — the agent still has `script_preview` and the
  externalized `jsr223/<sha>.groovy` file.

- [ ] **Step 5.3: Inline-function hints.** Extend the same extractor (or a
  sibling `extract_inline_hints(value: str)`) to detect
  `${__fifoPut(name,val)}`, `${__fifoPop(name,var)}`, `${__fifoGet(name,var)}`,
  `${__fifoSize(name,var)}` in any stringProp the parser already scans, and
  attach the resulting hints to the owning element's `intent_hints`. This
  supersedes the ad-hoc FIFO hints from Task 3.5: FIFO elements and inline
  functions both produce `intent_hints` entries with `kind` in
  `fifo_put`/`fifo_pop`/`fifo_get`/`fifo_size`.

- [ ] **Step 5.4: Plumb hints into `scenario.yaml`.** In
  `ir_to_scenario.py:325` (`todo_hook`), copy `node["intent_hints"]` (if any)
  into `hook["hints"]`. In `schemas/scenario.schema.json` `$defs/hooks`, add
  the optional `hints: array` field (free-form items).

- [ ] **Step 5.5: Render hints in the passport.** In
  `scenario_renderer.py` (hook rendering), when a hook carries `hints`, emit a
  «Намерения:» line listing `kind` and the relevant fields, so a reviewer can
  see the structured intent without opening the `.groovy` file.

- [ ] **Step 5.6: Rewrite the Pass 2 instruction.** In
  `.gigacode/skills/convert-from-jmeter/SKILL.md:40`–`:49`, change the JSR223
  translation step to: «Translate from `hints` + the original Groovy. If `hints`
  cover the whole script, translate from `hints` only and verify against the
  Groovy. If `hints` is empty or partial, read the original `jsr223/<sha>.groovy`
  and translate as before.» Keep the same Java snippet contract
  (`snippets/<PascalCaseName>.java` with `public static Session apply(Session)`).

- [ ] **Step 5.7: Tests.** Extend `test_jmx_parser.py:664`
  (`test_unknown_api_is_complex_with_reason`) and the JSR223 cases
  (`test_jsr223_*`) to assert `intent_hints` for typical scripts. Extend
  `test_ir_to_scenario.py:449` (`test_jsr223_post_becomes_after_todo_hook`)
  to assert `hook["hints"]` is populated. Add a `scenario_renderer` case for
  the «Намерения:» line.

---

## Task 6: Documentation

**Files:**
- Modify: `docs/PRD.md`
- Modify: `docs/MIGRATION.md`
- Modify: `GIGACODE.md` (if it references the migration flow)

- [ ] **Step 6.1: PRD.** In `docs/PRD.md` FR2.2, update the supported HTTP
  methods list to `GET/POST/PUT/PATCH/DELETE/HEAD/OPTIONS` and add the new
  JMeter element kinds (`fifo_put_post`, `fifo_pop_pre`, `http_raw_sampler`)
  to the mapping list. Note that cross-thread FIFO is surfaced as a
  `todo` hook + `fifo-cross-thread` complexity flag, not converted.

- [ ] **Step 6.2: MIGRATION.** In `docs/MIGRATION.md`, add a section
  documenting: `unsupported[].raw_props`; CSV feeder options and their
  Gatling-equivalent mapping (or TODO); `hooks[].hints`; the
  `fifo-cross-thread` complexity flag; `test_plan.serialize_threadgroups`; and
  the Pass 2 translation rule (translate from `hints` first).

- [ ] **Step 6.3: GIGACODE.** If `GIGACODE.md` references the conversion flow,
  add a one-liner that Pass 2 now reads `intent_hints` first.

---

## Ordering and dependencies

1. **Task 1** (HTTP methods) — isolated, no schema overlap with others. Do first.
2. **Task 2** (raw_props) — isolated. Parallel to Task 1.
3. **Task 4** (CSV options) — touches `scenario.schema.json` feeders; do after
   Task 1 (shared schema-freeze discipline). Independent of Task 2/3.
4. **Task 3** (FIFO + HTTPRawSampler) — depends on Task 2 conceptually (unknown
   fallback uses `raw_props`), and on Task 5 for the shared hint representation.
   Implement after Task 2; coordinate the `intent_hints` shape with Task 5
   before writing the extractor.
5. **Task 5** (intent_hints) — depends on Task 3 for FIFO hint kinds. Implement
   after Task 3.3 (complexity flag) and Task 3.5 (todo-hook plumbing) so the
   extractor can reuse the FIFO hint shape.
6. **Task 6** (docs) — last, after behaviour is frozen.

## Verification (run after every task; all must be green before commit)

```powershell
python tools/jmx_parser/test_jmx_parser.py
python tools/ir_to_scenario/test_ir_to_scenario.py
python tools/scenario_lint/scenario_lint.py <scenario.yaml> --format text
python tools/gatling_generator/test_gatling_generator.py
python tools/scenario_renderer/test_scenario_renderer.py
python tools/quality_gate/test_quality_gate.py
python tools/test_contract_coverage.py
python tools/hook_router/test_hook_router.py
```

Optional (slow): `python tools/jmx_parser/test_jmx_parser_perf.py` with
`GATLING_AI_PERF=1` to confirm no memory regression on large plans.

## Final end-to-end acceptance

1. Run `SynchronizationPluginsExample.jmx` (JP@GC site) through
   `document-legacy-jmeter`: parse, review `inventory.md`. Confirm the
   `fifo-cross-thread` flag and `serialize_threadgroups` appear, and that
   `FifoPutPostProcessor` / `FifoPopPreProcessor` are recognized kinds (not in
   «Unsupported elements»).
2. Hand off to `convert-from-jmeter`: confirm `scenario.yaml` has `todo` hooks
   with `hints` on the FIFO steps; `conversion-report.md` reconciles 1:1 with
   `inventory.md`.
3. `scenario-to-gatling`: render `passport.md` (hints visible), generate Java,
   `mvn -q compile`. The FIFO hooks stay `todo` → expected
   `quality-gate: passed_with_warnings`, not `passed`.
4. Construct a synthetic scenario with `method: PUT` (and a CSV feeder with
   `delimiter: ";"`, `ignore_first_line: true`): lint passes, generator emits
   `.put(...)` and the feeder TODO comment for `share_mode`; `passport.md`
   shows the CSV options; `quality-gate: passed`.

## Risks

- **Gatling feeder API does not cover every JMeter CSV option** — `share_mode`,
  `recycle`, `random_order` have no direct equivalent; they become TODO
  comments in Java. This is acceptable (silent-drop → explicit TODO).
- **`intent_hints` via regex may miss rare Groovy patterns** — the extractor
  is conservative: anything unrecognized stays in `script_preview` and the
  original `.groovy` file; the agent still has the source. `intent_hints`
  augment, never replace.
- **Cross-thread FIFO has no Gatling equivalent** — todo-hook + flag is the
  best deterministic representation; the agent (or engineer) must choose a
  real queue (Redis / SUT-side) at translation time. This is by design.
- **`http_raw_sampler` raw request text** — parsing HTTP/1.x request lines
  out of the `data` string is not deterministic enough to fully map; the step
  is emitted as PARTIAL with the raw text in the body and a manual-review
  note. Acceptable per the disposition contract.

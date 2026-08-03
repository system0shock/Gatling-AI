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

- `.gigacode/skills/` — 6 workflows, including `manage-methodology`
  (model-invoked / `/skills <name>`).
- `.gigacode/agents/` — subagents: read-only `validator-subagent`, bounded
  `mnt-module-inspector`, read-only `mnt-confluence-researcher`, file-only
  `mnt-evidence-reconciler`, bounded `mnt-author`, and minimal read-only
  `mnt-validator`.
- `.gigacode/commands/` — slash commands (`/quality-gate`, `/manage-methodology`).
- `.gigacode/hooks/` — advisory hooks (auto-lint, gate reminder).
- `tools/` — executable checks/generators, invoked as `python tools/<tool>/<tool>.py …`.
- `schemas/` — JSON Schemas (`scenario.schema.json`, `jmx-ir.schema.json`).
- `scenarios/` — live scenarios (hand-authored `scenario.yaml` + generated `passport.md`).
- `examples/scenarios/` — read-only golden fixtures (tests/docs only; do not edit).

## Key docs

- `docs/PRD.md`, `docs/ARCHITECTURE.md`, `docs/GETTING_STARTED.md`
- `docs/SCENARIO_FORMAT.md`, `docs/QUALITY_GATE.md`
- `docs/MIGRATION.md` — JMeter → Gatling pipeline, disposition ledger, new fields (`raw_props`, `hints`, `fifo-cross-thread`).

## Methodology evidence handoff

Use the MNT collectors only after Phase 3a has created `workspace-snapshot.json`.
`mnt-module-inspector` reads one selected inline `inspector_jobs[]` object plus its
`workspace-snapshot.json` path/context and module path; it never edits SUT modules
or `methodology.md`. `mnt-confluence-researcher` is limited to its
page/search scope, captures page ID/version/date provenance, and never publishes to
Confluence. Both hand off schema-valid files and return only their compact JSON
envelopes—never raw source files or page bodies.

`mnt-evidence-reconciler` consumes evidence artifacts only and invokes the
deterministic reconciliation CLI. It preserves all conflicting OpenAPI, backend,
frontend, infrastructure, and Confluence candidates. `docs_only` is not obsolete,
`repo_only` is not business-approved, and an SLA without an explicit normative
source remains blocking. Atlassian MCP setup is host-specific. The packaged baseline
contains no concrete Confluence MCP tool names, credentials, or server configuration.
The host overlay may supply page-read/search capability to the researcher and
page-read/page-update capability only to `mnt-confluence-publisher`. If a required
capability is unavailable, the relevant role returns `blocked`; do not substitute a
tool name or add another publisher capability to this package.

## Local methodology approval

Invoke `/manage-methodology` for `create`, `update-local`, or `publish`. `create`
and `update-local` always perform a full recollection of every confirmed source.
The local MNT approvals (`workspace-manifest` then `methodology-patch`) remain
hash-bound, and the canonical MNT must pass its post-apply gate. `publish` is a separate explicit approval after the exact
Confluence diff is shown. It uses the fixed page ID from the confirmed snapshot and
dispatches only `mnt-confluence-publisher` for the host-supplied update. Missing
approval, changed local MNT, or changed page version returns `blocked` without an
update. Deferred mechanisms are tracked in `docs/METHODOLOGY-DEFERRED.md`.

`mnt-validator` is minimal and read-only: it returns inline `accept|blocked`
evidence over pre-existing quality-report, descriptor, and source-map artifacts;
it never creates a validator report.


It checks pre-existing artifact content and declarations only; it does not recompute
hashes or bytes. The deterministic apply engine performs byte/hash revalidation
immediately before installation.


Immediately after authoring, prepare one exact methodology patch and descriptor.
The quality gate, validator, review, approval, and apply operations reuse that same
unchanged methodology patch and descriptor; it is not regenerated.

## Conversion flow note

Pass 2 (JSR223 translation) now reads `intent_hints` first; falls back to Groovy only when hints are partial or empty.

Pass 1 now inlines Module Controller targets automatically (fragment, thread group,
transaction controller) with cycle detection. Multi-row Ultimate Thread Group
schedules with non-overlapping rows are normalized to `profile: stages`.
Overlapping rows and unresolved module targets remain blocking.

## Methodology incremental run

`/manage-methodology` supports resume via `run-state.json` in the run directory.
Gap approval (step 7) is iterative: the engineer may answer some gaps now and
defer others. By request, the skill exports `questions.md` for offline filling.
Authoring launches only when all blocking gaps are closed.

## Anti-hallucination grounding

`mnt-module-inspector` now collects descriptive evidence (READMEs, architecture
docs, OpenAPI descriptions, deployment configs) as direct quotes — no
paraphrasing. `mnt-author` follows per-section grounding rules: sections with
`missing` coverage get a placeholder only; `partial` sections get only
evidence-backed sentences. The methodology quality gate blocks hallucinated
content in `missing` sections via `grounding-missing-section`.

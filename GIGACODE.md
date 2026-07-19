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
- `scenarios/`, `examples/scenarios/` — scenario artifacts.

## Key docs

- `docs/PRD.md`, `docs/ARCHITECTURE.md`, `docs/GETTING_STARTED.md`
- `docs/SCENARIO_FORMAT.md`, `docs/QUALITY_GATE.md`

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
source remains blocking. Atlassian MCP setup is host-specific: install a host overlay
that injects the actual verified read/search MCP tool identifiers into the host agent
configuration, without Confluence write operations. The packaged baseline contains no
concrete Confluence read tool names. If the overlay's read capability is unavailable,
the researcher returns `blocked`; do not substitute a tool name or add credentials
or publisher tools to this package.

## Local methodology approval

Invoke `/manage-methodology` for `create` or `update-local`. It requires two
separate explicit approvals: first for the exact `workspace-manifest` patch before
snapshot/collection, then for the exact `methodology-patch` after independent
quality and validator review. `record-approval` and `apply` are hash-bound and
leave the target byte-for-byte unchanged on any missing, stale, or mismatched
approval. The final canonical MNT must pass a post-apply gate. Confluence remains
unchanged; the host overlay supplies no write operation and unavailable reads block
the run.

`mnt-validator` is minimal and read-only: it returns inline `accept|blocked`
evidence over pre-existing quality-report, descriptor, and source-map artifacts;
it never creates a validator report.


It checks pre-existing artifact content and declarations only; it does not recompute
hashes or bytes. The deterministic apply engine performs byte/hash revalidation
immediately before installation.


Immediately after authoring, prepare one exact methodology patch and descriptor.
The quality gate, validator, review, approval, and apply operations reuse that same
unchanged methodology patch and descriptor; it is not regenerated.

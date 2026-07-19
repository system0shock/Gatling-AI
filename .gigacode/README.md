# `.gigacode/` — Gigacode configuration package

Canonical, version-controlled config for the Gatling-AI workflow on Gigacode
(the corporate Qwen Code fork). Layout follows Qwen Code conventions.

## Contents

- `settings.json` — context wiring + layered hooks.
- `skills/` — the 5 agent skills (single source of truth).
- `agents/validator-subagent.md` — read-only reviewer.
- `agents/mnt-module-inspector.md` — bounded, read-only repository/OpenAPI collector.
- `agents/mnt-confluence-researcher.md` — bounded, read-only Confluence collector.
- `agents/mnt-evidence-reconciler.md` — file-only deterministic evidence reconciler.
- commands/quality-gate.md — /quality-gate slash command.
- commands/manage-methodology.md — /manage-methodology explicit two-approval MNT workflow.
- `hooks/` — advisory `lint_scenario.py` (PostToolUse) and `gate_reminder.py`
  (Stop), plus opt-in **blocking** guards `guard_no_handwritten_java.py`
  (PreToolUse) and `guard_gate_green.py` (Stop). See **Enforcement** below.

## Install

- **Project (recommended):** this `.gigacode/` is already in the repo root, next
  to `tools/`. Skills invoke tools by relative path, so they only work when run
  from a project that contains `tools/`.
- **Personal (all projects):** copy individual skills to `~/.gigacode/skills/`.
  Note: tools are NOT bundled in skills, so personal-installed skills still
  require a project that contains `tools/`.

### Host model setup (verified on OSS Qwen Code 0.18.1)

- For an OpenAI-compatible model (e.g. a local ollama), the API key must live at
  **`security.auth.apiKey`** in the host `settings.json` (with
  `security.auth.selectedType: "openai"`), not inside `modelProviders[]`.
  Equivalently, set the `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL`
  env vars.
- On first load the host may rewrite `settings.json` (adds `"$version"`, reflows
  JSON, drops a `.orig` backup). `.orig` files are gitignored; the reflow is
  cosmetic — re-commit or revert as you prefer.

## Enforcement (opt-in blocking)

The four hooks split into two layers:

- **Advisory (always on):** `lint_scenario` (lints an edited `scenario.yaml` and
  feeds findings back) and `gate_reminder` (reminds to run the gate). Both always
  `exit 0` — feedback, never a wall.
- **Blocking (opt-in):** off by default; enabled per host with
  `GIGACODE_ENFORCE=1`. When on:
  - `guard_no_handwritten_java` (PreToolUse) denies any `write_file`/`edit` whose
    target is generated Java (`**/src/test/java/**/*.java`) — Java must come from
    `tools/gatling_generator`, never by hand. The generator runs as its own
    process, so it is never blocked.
  - `guard_gate_green` (Stop) refuses to let the model finish while a scenario
    exists and the gate report is missing / stale / not `passed` /
    `passed_with_warnings`. Loop-safe: blocks at most `GIGACODE_ENFORCE_MAX`
    times per session (default 3), then falls back to a loud advisory.

Ship default-safe (advisory); flip `GIGACODE_ENFORCE=1` once you have confirmed
`exit 2` is honored on your host (confirm-item #4).

## Confirm-items (verify against a live Gigacode)

1. The config directory name is `.gigacode/` and `settings.json` uses the Qwen
   schema verbatim.
2. The context file name (`context.fileName: ["GIGACODE.md"]`) is honored.
3. The project-dir env var used by hooks (`$QWEN_PROJECT_DIR` in Qwen) — our
   hooks avoid it by resolving paths relative to their own location.
4. Hooks are supported, and the host honors a non-zero (`exit 2`) hook as a
   blocking deny. Confirmed on OSS Qwen Code 0.18.1 for both `PreToolUse` and
   `Stop` (2026-06-16 live-test); re-confirm on your Gigacode build before
   relying on the blocking guards. If `exit 2` is NOT honored, the guards
   degrade to no-ops and the gate/command/CI remain the enforcement.
5. Subagent tool names (`read_file`, `write_file`, …) match Gigacode's vocabulary.
6. `permissions` / `mcpServers` are intentionally omitted from `settings.json`;
   add them once their Gigacode syntax is confirmed. Example Atlassian MCP block:

   ```json
   "mcpServers": {
     "atlassian": { "command": "npx", "args": ["-y", "mcp-atlassian"] }
   }
   ```

## Methodology evidence subagents

The MNT subagents exchange file artifacts, not source material in chat. The module
inspector receives one selected inline `inspector_jobs[]` object plus its
`workspace-snapshot.json` path/context and collects one schema-valid module evidence
file while reading only that selected module. The Confluence
researcher is read-only: it records page ID, version, date, and provenance in
`confluence-snapshot.json` plus Confluence evidence. The evidence reconciler reads
only evidence artifacts and runs the deterministic methodology-evidence CLI; it
never rereads source repositories or Confluence.

Collectors never edit SUT modules or `methodology.md`, and their messages use only
the compact JSON envelope declared in their agent definitions. They must preserve
stable entity keys and exact provenance for every fact. Conflicting candidates stay
in the artifacts for deterministic reconciliation; neither `docs_only` nor
`repo_only` is business approval.

Atlassian/Confluence MCP configuration is deliberately host-specific. Install a
host overlay that injects the actual verified read/search MCP tool identifiers into
the host agent configuration; this packaged baseline deliberately contains none.
The overlay must provide no Confluence write operation. If its read capability is
not configured or unavailable, the researcher returns `blocked` rather than
substituting a tool name. This package ships no credentials, server configuration,
or publish capabilities.

## Local MNT approval workflow

`/manage-methodology` runs the bounded Phase 3c workflow. It first confirms a
workspace preview, prepares and shows the exact `workspace-manifest` patch, then
requires an explicit workspace-manifest approval before `record-approval` and
`apply`. Only then does it snapshot confirmed modules, collect and reconcile
evidence, persist blocking-gap answers, author a candidate with the independently
validated workspace snapshot, and run the deterministic quality gate plus the
read-only `mnt-validator`.

The candidate summary, warnings, and exact MNT diff are shown before a separate,
explicit `methodology-patch` approval. That approval is recorded and applied only
when base/candidate/patch hashes still match, then the canonical MNT receives a
post-apply quality gate. Confluence remains unchanged: host overlays provide only
verified read/search capability; unavailable capability returns `blocked`, and this
package includes no publisher or concrete Confluence tool name.
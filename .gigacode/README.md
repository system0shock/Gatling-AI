# `.gigacode/` — Gigacode configuration package

Canonical, version-controlled config for the Gatling-AI workflow on Gigacode
(the corporate Qwen Code fork). Layout follows Qwen Code conventions.

## Contents

- `settings.json` — context wiring + layered hooks.
- `skills/` — the 5 agent skills (single source of truth).
- `agents/validator-subagent.md` — read-only reviewer.
- `commands/quality-gate.md` — `/quality-gate` slash command.
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

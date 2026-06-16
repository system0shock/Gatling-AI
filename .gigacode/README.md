# `.gigacode/` — Gigacode configuration package

Canonical, version-controlled config for the Gatling-AI workflow on Gigacode
(the corporate Qwen Code fork). Layout follows Qwen Code conventions.

## Contents

- `settings.json` — context wiring + layered hooks.
- `skills/` — the 5 agent skills (single source of truth).
- `agents/validator-subagent.md` — read-only reviewer.
- `commands/quality-gate.md` — `/quality-gate` slash command.
- `hooks/` — advisory `lint_scenario.py` (PostToolUse) and `gate_reminder.py` (Stop).

## Install

- **Project (recommended):** this `.gigacode/` is already in the repo root, next
  to `tools/`. Skills invoke tools by relative path, so they only work when run
  from a project that contains `tools/`.
- **Personal (all projects):** copy individual skills to `~/.gigacode/skills/`.
  Note: tools are NOT bundled in skills, so personal-installed skills still
  require a project that contains `tools/`.

## Confirm-items (verify against a live Gigacode)

1. The config directory name is `.gigacode/` and `settings.json` uses the Qwen
   schema verbatim.
2. The context file name (`context.fileName: ["GIGACODE.md"]`) is honored.
3. The project-dir env var used by hooks (`$QWEN_PROJECT_DIR` in Qwen) — our
   hooks avoid it by resolving paths relative to their own location.
4. Hooks are supported. If not, `/quality-gate` and the `quality-gate` skill
   still work without them.
5. Subagent tool names (`read_file`, `write_file`, …) match Gigacode's vocabulary.
6. `permissions` / `mcpServers` are intentionally omitted from `settings.json`;
   add them once their Gigacode syntax is confirmed. Example Atlassian MCP block:

   ```json
   "mcpServers": {
     "atlassian": { "command": "npx", "args": ["-y", "mcp-atlassian"] }
   }
   ```

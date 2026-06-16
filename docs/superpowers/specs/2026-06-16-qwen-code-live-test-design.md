# Live-test: `.gigacode` on real Qwen Code + ollama/qwen3.6

**Date:** 2026-06-16
**Status:** approved (design)
**Branch:** gigacode-packaging

## Goal

Validate **both the packaging and the end-to-end flow** of the `.gigacode/`
package against OSS Qwen Code, driven by the local model
`qwen3.6:35b-a3b-q4_K_M` via ollama.

This is the live execution of the **Confirm-items** block in
`.gigacode/README.md`, which until now has only been reasoned about, never run
on a real Qwen Code.

## Success criteria

- **Part A (packaging):** the package is actually picked up by Qwen Code —
  `settings.json` loads, `GIGACODE.md` is read as context, the 5 skills /
  the validator subagent / `/quality-gate` are visible, and both hooks fire.
  All 6 confirm-items get a recorded verdict (pass / fail / n-a + the observed
  fact).
- **Part B (flow):** `e2e/checkout-mix.md` → (`scenario-from-docs`) →
  `scenario.yaml` → (`scenario-to-gatling`) → Gatling Java → `/quality-gate`
  reaches status `passed` or `passed_with_warnings`.
- A short report records: the 6 confirm-items, every fork↔OSS discrepancy
  found, and how `qwen3.6` behaved on an agentic flow (tool-calling, whether it
  reaches the gate).

Success ≠ "everything green". Some confirm-items are expected to answer
"OSS ≠ corporate fork" — that is a useful finding, not a failure.

## Environment

Already present: node 24.14, npm 11.9, ollama 0.30.8 (running), model
`qwen3.6:35b-a3b-q4_K_M` (23 GB, MoE 35B / 3B-active, q4 — has tool-calling),
Python 3.14.

To add:

- Install OSS Qwen Code: `npm i -g @qwen-code/qwen-code`.
- Wire ollama as an OpenAI-compatible provider in `~/.qwen/settings.json`:
  - `modelProviders.openai[]` with `baseUrl: http://localhost:11434/v1`,
    `apiKey: "ollama"` (placeholder), `id` / `model.name` =
    `qwen3.6:35b-a3b-q4_K_M`, `generationConfig.contextWindowSize` sized to the
    model.
  - `security.auth.selectedType: "openai"`.

## Bridge `.gigacode` → `.qwen`

OSS Qwen Code expects the project config directory to be `.qwen/`, while our
package lives in `.gigacode/` (the name used by the corporate fork). This name
difference **is** the answer to confirm-item #1.

**Chosen approach:** a directory junction `.qwen → .gigacode`
(`mklink /J`, needs no admin on Windows). Then:

- our `settings.json` is picked up as-is;
- its `context.fileName: ["GIGACODE.md"]` points at the `GIGACODE.md` already
  in the repo root — nothing to copy, we test the real files;
- the hooks reference `.gigacode/hooks/...`, a path that stays valid.

**Fallback:** copy `.gigacode/` → `.qwen/` (throwaway, removed after) if the
junction cannot be created.

The junction is a test artifact, not a committed change.

## Part A — packaging validation (mostly scriptable)

Walk the 6 confirm-items, recording expectation vs. observed fact for each:

1. Config dir name `.gigacode/` vs `.qwen/`; `settings.json` uses the Qwen
   schema (loads with no error — `/about` or a clean start).
2. `context.fileName: ["GIGACODE.md"]` is honored (the model has the GIGACODE.md
   rules in context).
3. Project-dir env var: our hooks resolve paths relative to their own location,
   so they should not depend on `$QWEN_PROJECT_DIR`.
4. Hooks supported: `lint_scenario.py` (PostToolUse) and `gate_reminder.py`
   (Stop) actually fire.
5. Subagent tool names match Gigacode's vocabulary.
6. `permissions` / `mcpServers` intentionally omitted — confirm nothing breaks
   without them.

**Discrepancies suspected in advance (to confirm live):**

- Custom command file format: ours is `quality-gate.md`; Qwen Code may expect
  `.toml` for custom commands.
- Grep tool name: the validator subagent uses `search_file_content`, while Qwen
  docs also show `grep_search`.

The hook schema otherwise matches Qwen Code verbatim (events `PostToolUse` /
`Stop`, `matcher` + `hooks[]`, `type: command`, `name`, `timeout`, stdin-JSON
input, exit-code semantics).

## Part B — end-to-end flow (interactive, user-driven)

Division of labor:

- **Claude Code does:** environment setup, the junction/bridge, the scriptable
  Part A checks, and a headless smoke run.
- **User drives:** the interactive `scenario-from-docs` skill in the `qwen` TUI
  (the skill asks clarifying questions one at a time by design), then
  `scenario-to-gatling`. Claude Code observes the produced artifacts and
  verifies them (lint, rendered passport, generated Java, gate report).
- Where possible, hand the model fully-specified prompts so it does not stall.

Flow target: start from `e2e/checkout-mix.md`, produce a lint-clean
`scenario.yaml`, generate the Gatling Maven project, run `/quality-gate`.

## What we record

A short table: the 6 confirm-items (verdict + observed fact); fork↔OSS
discrepancies found; `qwen3.6` behavior on the agentic flow (tool-calling,
reaching the gate); a bug/debt list to feed back into the package.

## Risks

- A local 35B-MoE-q4 model may be weak at sustaining a long agentic flow /
  tool-calling — hence the short path and ready-made prompts.
- Several confirm-items will answer "OSS ≠ fork"; expected and useful, not a
  failure.

## Out of scope

- The `jmx → scenario` migration path (separate confirm of `jmx_parser`).
- Changing the `.gigacode/` package to fit OSS — this run only *discovers* what
  would need changing; fixes are follow-up work.

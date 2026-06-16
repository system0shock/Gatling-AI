# Qwen Code live-test — results (2026-06-16)

Model: `qwen3.6:35b-a3b-q4_K_M` via ollama. OSS Qwen Code version: <fill>.

## Confirm-items (from .gigacode/README)

| # | Item | Verdict | Observed fact |
|---|------|---------|---------------|
| 1 | config dir `.gigacode` vs `.qwen`; settings schema | | |
| 2 | `context.fileName: ["GIGACODE.md"]` honored | | |
| 3 | hooks avoid `$QWEN_PROJECT_DIR` (relative paths) | | |
| 4 | hooks supported (lint PostToolUse, gate Stop) | | |
| 5 | subagent tool names match | | |
| 6 | omitted `permissions`/`mcpServers` cause no break | | |

## Suspected discrepancies (verify live)

| Area | Ours | Qwen OSS | Verdict |
|------|------|----------|---------|
| custom command file format | `.md` | `.toml`? | |
| grep tool name | `search_file_content` | `grep_search`? | |

## Flow (Part B)

| Stage | Artifact | Result |
|-------|----------|--------|
| docs → scenario | `scenario.yaml` lint-clean? | |
| scenario → Java | Maven project generated? | |
| quality gate | status | |

## qwen3.6 behavior notes

- Pre-flight warm-up: replied `OK` correctly, but emitted a visible
  `Thinking...` reasoning block first (qwen3 thinking mode on). Watch for
  thinking-mode noise leaking into tool-call flows.

## Bugs / debt for the package

-

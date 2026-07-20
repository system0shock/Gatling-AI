# Qwen Code Live-Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **NOTE — this is not a code-feature plan.** It installs OSS Qwen Code, wires it
> to a local ollama model, and runs an observational live-test of the
> `.gigacode/` package. Steps are "command → expected result" verifications, and
> several Part-B steps are **interactive and user-driven** (the human drives the
> `qwen` TUI; the agent observes artifacts). A background subagent cannot drive
> an interactive TUI — prefer inline execution.

**Goal:** Validate that the `.gigacode/` package loads on real OSS Qwen Code and
that the `docs → scenario → Java` flow runs end-to-end under
`qwen3.6:35b-a3b-q4_K_M` via ollama.

**Architecture:** Install Qwen Code globally; put the ollama OpenAI-compatible
provider in user-level `~/.qwen/settings.json`; bridge the project package with a
directory junction `.qwen → .gigacode` so our project-level `settings.json`
(hooks + `context.fileName: ["GIGACODE.md"]`) is picked up as-is. Then run Part A
(packaging confirm-items) and Part B (interactive flow), recording every
observation into a results note.

**Tech Stack:** OSS Qwen Code (`@qwen-code/qwen-code`, npm), ollama 0.30.8,
model `qwen3.6:35b-a3b-q4_K_M`, Python 3.14 (hooks/tools), Windows 11 / PowerShell.

## Global Constraints

- Test the **real** package files — do not edit `.gigacode/` to make the test
  pass. This run *discovers* needed changes; fixes are follow-up work.
- The junction `.qwen` and user settings are **test artifacts**, never committed
  to tracked files. Exclude `.qwen/` via `.git/info/exclude` (local, not
  `.gitignore`).
- Model name must be `qwen3.6:35b-a3b-q4_K_M` verbatim everywhere (provider `id`,
  `model.name`) so Qwen routes to the ollama model.
- ollama OpenAI-compatible endpoint: `http://localhost:11434/v1`, placeholder
  `apiKey: "ollama"`.
- Success ≠ "all green". A confirm-item answering "OSS ≠ corporate fork" is a
  valid recorded finding, not a failure.
- Teardown must remove the junction **without** deleting the `.gigacode` target
  (reparse-point-safe delete only).

---

### Task 1: Pre-flight — environment & model warm-up

**Files:**
- None (verification only).

**Interfaces:**
- Produces: confirmation that ollama serves `qwen3.6:35b-a3b-q4_K_M` and that
  node/npm are usable for the global install in Task 2.

- [ ] **Step 1: Confirm ollama is up and the model is present**

Run:
```powershell
ollama list
```
Expected: a row containing `qwen3.6:35b-a3b-q4_K_M` (≈23 GB). If ollama is not
running, launch the Ollama app/service first, then re-run.

- [ ] **Step 2: Warm the model and confirm it generates**

Run:
```powershell
ollama run qwen3.6:35b-a3b-q4_K_M "Reply with exactly: OK"
```
Expected: the model loads into memory and prints a short reply containing `OK`
(first load may take tens of seconds). This warms the weights so the later
Qwen Code calls don't time out on cold start.

- [ ] **Step 3: Confirm node/npm**

Run:
```powershell
node --version; npm --version
```
Expected: node `v24.x`, npm `11.x`.

- [ ] **Step 4: Record results-note skeleton**

Create `docs/superpowers/notes/2026-06-16-qwen-code-live-test-results.md` with
the recording table skeleton:
```markdown
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

-

## Bugs / debt for the package

-
```

- [ ] **Step 5: Commit the skeleton**

```powershell
git add docs/superpowers/notes/2026-06-16-qwen-code-live-test-results.md
git commit -m @'
docs: results-note skeleton for Qwen Code live-test

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
'@
```

---

### Task 2: Install OSS Qwen Code

**Files:**
- None (global npm install).

**Interfaces:**
- Produces: `qwen` on PATH, version recorded in the results note.

- [ ] **Step 1: Install globally**

Run:
```powershell
npm i -g @qwen-code/qwen-code
```
Expected: install completes; npm prints the installed version.

- [ ] **Step 2: Verify the binary**

Run:
```powershell
qwen --version
```
Expected: a version string prints (no "command not found"). If `qwen` is not
found, open a new shell so PATH refreshes, then re-run.

- [ ] **Step 3: Record the version**

Edit the results note: fill `OSS Qwen Code version: <value>` from Step 2.

---

### Task 3: Wire ollama as an OpenAI-compatible provider (user-level)

**Files:**
- Modify/Create: `C:\Users\Omega\.qwen\settings.json` (user-level Qwen settings).

**Interfaces:**
- Consumes: ollama endpoint from Task 1.
- Produces: a Qwen Code session that routes to `qwen3.6:35b-a3b-q4_K_M`. Later
  tasks assume `qwen` started in the project talks to this model.

- [ ] **Step 1: Back up any existing user settings**

Run:
```powershell
if (Test-Path "$HOME\.qwen\settings.json") { Copy-Item "$HOME\.qwen\settings.json" "$HOME\.qwen\settings.json.bak-livetest" -Force; Get-Content "$HOME\.qwen\settings.json" }
else { Write-Host "no existing user settings" }
```
Expected: either the current contents print (note them — we must MERGE, not
clobber, any existing keys) or "no existing user settings".

- [ ] **Step 2: Write the provider config**

If no existing settings, write `C:\Users\Omega\.qwen\settings.json` exactly:
```json
{
  "modelProviders": {
    "openai": [
      {
        "id": "qwen3.6:35b-a3b-q4_K_M",
        "name": "Qwen3.6 35B-A3B (Ollama local)",
        "baseUrl": "http://localhost:11434/v1",
        "apiKey": "ollama",
        "description": "qwen3.6 MoE running locally via Ollama",
        "generationConfig": {
          "contextWindowSize": 131072
        }
      }
    ]
  },
  "security": {
    "auth": {
      "selectedType": "openai"
    }
  },
  "model": {
    "name": "qwen3.6:35b-a3b-q4_K_M"
  }
}
```
If settings already existed (Step 1 printed content), merge these three top-level
keys (`modelProviders`, `security`, `model`) into the existing JSON instead of
overwriting other keys.

- [ ] **Step 3: Smoke the model binding (non-interactive)**

Run (from the project root so cwd is consistent):
```powershell
qwen -p "Reply with exactly: BOUND"
```
Expected: output contains `BOUND`, proving Qwen Code reaches the ollama model.

- [ ] **Step 4: Fallback if Step 3 fails (env-var route)**

If the model does not bind (auth error / empty reply), set OpenAI-compatible env
vars for the session and re-smoke:
```powershell
$env:OPENAI_API_KEY="ollama"; $env:OPENAI_BASE_URL="http://localhost:11434/v1"; $env:OPENAI_MODEL="qwen3.6:35b-a3b-q4_K_M"
qwen -p "Reply with exactly: BOUND"
```
Expected: output contains `BOUND`. Record in the results note which route worked
(settings vs env vars).

---

### Task 4: Bridge `.qwen → .gigacode` (project junction)

**Files:**
- Create: junction `F:\Coding\Gatling-AI\.qwen` → `.gigacode` (test artifact).
- Modify: `F:\Coding\Gatling-AI\.git\info\exclude` (local exclude).

**Interfaces:**
- Consumes: the project `.gigacode/` package.
- Produces: a project-level `.qwen/settings.json` (= our file) that Qwen Code
  loads, with `context.fileName: ["GIGACODE.md"]` and the two hooks.

- [ ] **Step 1: Exclude `.qwen/` locally (no tracked-file change)**

Run:
```powershell
Add-Content -Path ".git\info\exclude" -Value ".qwen/"
```
Expected: no error. `.qwen/` will not show in `git status`.

- [ ] **Step 2: Create the directory junction**

Run:
```powershell
New-Item -ItemType Junction -Path ".qwen" -Target ".gigacode"
```
Expected: PowerShell reports a new junction `.qwen`. (If it fails, fallback:
`cmd /c mklink /J .qwen .gigacode`.)

- [ ] **Step 3: Verify the junction resolves to our package**

Run:
```powershell
(Get-Item ".qwen").LinkType; Test-Path ".qwen\settings.json"; Get-Content ".qwen\settings.json"
```
Expected: LinkType `Junction`; `Test-Path` is `True`; the printed JSON is our
`.gigacode/settings.json` (the `context.fileName: ["GIGACODE.md"]` + hooks block).

- [ ] **Step 4: Confirm `git status` is clean of `.qwen`**

Run:
```powershell
git status --short
```
Expected: no `.qwen` entry (it is excluded). Pre-existing modifications may show;
that's fine.

---

### Task 5: Part A — packaging load checks (interactive)

**Files:**
- Modify: results note (fill confirm-items 1, 2, 5, 6 and the discrepancy table).

**Interfaces:**
- Consumes: the bound Qwen Code session (Task 3) + the junction (Task 4).
- Produces: recorded verdicts for confirm-items 1, 2, 5, 6 and the command/grep
  discrepancy rows.

> Run `qwen` interactively from `F:\Coding\Gatling-AI`. The user issues the
> slash commands below; the agent records what appears.

- [ ] **Step 1: Clean start / settings load (confirm-item 1)**

In `qwen`, run `/about` (or observe a clean startup with no settings-parse
error). Expected: Qwen Code starts; project settings loaded from `.qwen/`
(our junctioned file). Record: dir name is `.qwen` on OSS vs `.gigacode` on the
fork → confirm-item 1 = "OSS uses .qwen; schema otherwise accepted".

- [ ] **Step 2: Context file honored (confirm-item 2)**

In `qwen`, prompt:
```
What are the non-negotiable working rules for this project? List them.
```
Expected: the model recites GIGACODE.md rules (Gatling OSS only, Java only,
Maven first, scenario.yaml single source of truth, never invent system/id/number,
never report done without a passed quality gate). Record verdict for
confirm-item 2.

- [ ] **Step 3: Skills visible**

In `qwen`, run `/skills` (or the platform's skill-list command). Expected: the 5
skills appear — `convert-from-jmeter`, `document-legacy-jmeter`, `quality-gate`,
`scenario-from-docs`, `scenario-to-gatling`. Record any that are missing.

- [ ] **Step 4: Slash command + format discrepancy**

In `qwen`, check whether `/quality-gate` is listed/usable. Expected: this is
where the `.md` vs `.toml` command-format question resolves. Record: if
`/quality-gate` does NOT appear, note "OSS expects `.toml` custom commands" in
the discrepancy table; if it appears, note "`.md` accepted".

- [ ] **Step 5: Subagent visible + tool-name check (confirm-item 5)**

In `qwen`, list agents (e.g. `/agents`) and confirm `validator-subagent` appears.
Inspect whether its declared tools (`read_file`, `read_many_files`, `glob`,
`search_file_content`, `run_shell_command`) are all recognized. Expected: record
whether `search_file_content` is accepted or whether Qwen reports an unknown tool
(would point to `grep_search`). Fill confirm-item 5 + the grep-tool discrepancy
row.

- [ ] **Step 6: No-break on omitted keys (confirm-item 6)**

Confirm nothing above errored due to missing `permissions` / `mcpServers`.
Expected: session is fully functional without them → confirm-item 6 = pass.
Record.

---

### Task 6: Part A — hooks fire (interactive)

**Files:**
- Modify: results note (fill confirm-items 3, 4).

**Interfaces:**
- Consumes: the interactive session from Task 5.
- Produces: recorded evidence that `lint_scenario.py` (PostToolUse) and
  `gate_reminder.py` (Stop) execute.

- [ ] **Step 1: Trigger the PostToolUse lint hook**

In `qwen`, ask the model to write a small scratch scenario file, e.g.:
```
Create a file scratch/try.yaml with a minimal scenario.yaml body, then stop.
```
Expected: after the `write_file` tool runs, the `lint-scenario` hook
(`python .gigacode/hooks/lint_scenario.py`) executes and surfaces advisory lint
output (or runs silently with exit 0 if the path isn't a scenario). Record
whether the hook fired (confirm-item 4, PostToolUse half).

- [ ] **Step 2: Trigger the Stop gate-reminder hook**

Let the turn end (model concludes its response). Expected: the `gate-reminder`
hook (`python .gigacode/hooks/gate_reminder.py`) fires on `Stop` and emits its
advisory reminder about the quality gate. Record whether it fired (confirm-item 4,
Stop half).

- [ ] **Step 3: Confirm relative-path resolution (confirm-item 3)**

Verify the hooks ran without needing `$QWEN_PROJECT_DIR` (they resolve paths
relative to their own location / cwd). Expected: hooks executed from the project
root with no env-var dependency → confirm-item 3 = pass. Record.

- [ ] **Step 4: Clean up the scratch file**

Run:
```powershell
if (Test-Path "scratch\try.yaml") { Remove-Item "scratch\try.yaml" -Force }; if ((Test-Path "scratch") -and -not (Get-ChildItem "scratch")) { Remove-Item "scratch" -Force }
```
Expected: scratch artifact removed.

---

### Task 7: Part B — docs → scenario (interactive, user-driven)

**Files:**
- Create (by the flow): `scenarios/<SYSTEM>/<id>-<NNN>/scenario.yaml` +
  co-located `passport.md` (paths chosen by the skill / user).
- Modify: results note (flow table, `docs → scenario` row).

**Interfaces:**
- Consumes: bound session + loaded package + the input doc `e2e/checkout-mix.md`.
- Produces: a lint-clean `scenario.yaml` the agent can verify and that Task 8
  feeds to `scenario-to-gatling`.

> User-driven: the `scenario-from-docs` skill asks clarifying questions one at a
> time. The user answers in the TUI (system code, scenario id, number — the skill
> must NOT invent them). The agent verifies the resulting artifacts.

- [ ] **Step 1: Invoke the skill on the input doc**

In `qwen`, prompt:
```
Use the scenario-from-docs skill to turn e2e/checkout-mix.md into a scenario.yaml.
Ask me for system code, scenario id, and number — do not invent them.
```
Expected: the model loads the skill and begins extracting entities, asking
clarifying questions (e.g. system code). The user answers.

- [ ] **Step 2: Let the skill self-lint**

Expected: per the skill, it runs
`python tools/scenario_lint/scenario_lint.py <scenario.yaml> --format text` and
fixes blocking findings by editing the YAML.

- [ ] **Step 3: Agent verifies the scenario independently**

Run (substitute the real path the skill chose):
```powershell
python tools/scenario_lint/scenario_lint.py scenarios\<SYSTEM>\<id>-<NNN>\scenario.yaml --format text
```
Expected: no blocking findings. Record the scenario path + lint result in the
results note (flow table).

---

### Task 8: Part B — scenario → Java + quality gate (interactive, user-driven)

**Files:**
- Create (by the flow): generated Gatling Maven project (path chosen by the
  skill).
- Create (by the flow): `quality-gate-report.json` / `quality-gate-report.md`.
- Modify: results note (flow table: `scenario → Java`, `quality gate`).

**Interfaces:**
- Consumes: the approved `scenario.yaml` from Task 7.
- Produces: a generated project + a quality-gate report whose status the agent
  records.

- [ ] **Step 1: Generate Java via the skill**

In `qwen`, after approving the scenario, prompt:
```
Use scenario-to-gatling to generate the Gatling Java project from that scenario.yaml.
```
Expected: the skill generates the Maven/Java project (Gatling 3.12 conventions).

- [ ] **Step 2: Run the quality gate**

In `qwen`, run:
```
/quality-gate
```
(supplying the scenario path and generated project path when asked). Expected:
the gate runs and reports `passed`, `passed_with_warnings`, or `blocked` with a
report path.

- [ ] **Step 3: Agent verifies the gate report independently**

Run (substitute the real report path):
```powershell
Get-Content <path>\quality-gate-report.md
```
Expected: a status line of `passed` or `passed_with_warnings`. If `blocked`,
record the failing check verbatim (this is a valid finding, not a plan failure).
Fill the flow table.

---

### Task 9: Record findings & teardown

**Files:**
- Modify: results note (finalize behavior notes + bug/debt list).
- Delete: junction `.qwen` (reparse-point-safe).
- Restore: `~/.qwen/settings.json` from backup if one existed.

**Interfaces:**
- Consumes: all recorded observations.
- Produces: a committed results note and a clean working tree (no test
  artifacts).

- [ ] **Step 1: Finalize the results note**

Fill the "qwen3.6 behavior notes" (tool-calling reliability, whether it reached
the gate, where it stalled) and "Bugs / debt for the package" (e.g. command
format must be `.toml`, grep tool rename, anything else found).

- [ ] **Step 2: Remove the junction WITHOUT deleting the target**

Run:
```powershell
(Get-Item ".qwen").Delete()
```
Expected: `.qwen` link removed. Verify the target is intact:
```powershell
Test-Path ".qwen"; Test-Path ".gigacode\settings.json"
```
Expected: first `False`, second `True`. (Never use `Remove-Item -Recurse` on a
junction — it can recurse into and delete `.gigacode`.)

- [ ] **Step 3: Restore user settings if they were backed up**

Run:
```powershell
if (Test-Path "$HOME\.qwen\settings.json.bak-livetest") { Move-Item "$HOME\.qwen\settings.json.bak-livetest" "$HOME\.qwen\settings.json" -Force }
```
Expected: original user settings restored (or skipped if no backup).

- [ ] **Step 4: Commit the results note**

```powershell
git add docs/superpowers/notes/2026-06-16-qwen-code-live-test-results.md
git commit -m @'
docs: record Qwen Code live-test results

Verdicts for the 6 .gigacode confirm-items, fork-vs-OSS discrepancies,
and qwen3.6 flow behavior.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
'@
```

- [ ] **Step 5: Final clean check**

Run:
```powershell
git status --short
```
Expected: no `.qwen` artifact; only intended/pre-existing changes remain.

# Qwen Code live-test — results (2026-06-16)

Model: `qwen3.6:35b-a3b-q4_K_M` via ollama. OSS Qwen Code version: `0.18.1`.

## Conclusion — are hooks enough to stop a wayward model?

**No, and they were never meant to be.** Both hooks are advisory by design
(exit 0, never block): `lint_scenario` only injects `additionalContext`,
`gate_reminder` only injects a `systemMessage`. The live model proved the point
— asked for `scenario.yaml` only, qwen3.6 jumped the stage gate and also wrote
Java/pom; the hooks did not (and cannot) stop it.

Enforcement lives in the **deterministic quality gate**, not the hooks. Verified
in code AND empirically:

- The gate's `generator` check does a **byte-parity** comparison: project
  `src/test/java` + `src/test/resources` must equal a fresh generator run
  (`quality_gate.py:368-380`, `GENERATED_COMPARE_DIRS`).
- Empirical: the model's prematurely-written Java happened to be **byte-identical**
  to the generator output → gate `passed`. Injecting a single stray line →
  gate `blocked` with `generator.project-output-stale: generated project files
  do not match a fresh generator run`. So drift/hand-edits are caught hard.

So split "breaking the flow" in two:

- **Breaking the artifact** (wrong/hand-edited Java, drift): the gate blocks it
  mechanically. Hooks irrelevant here — the gate is the teeth.
- **Breaking the process** (skipping stages/approval, declaring "done" without
  running the gate): hooks only *remind*; nothing *blocks*. The Stop hook cannot
  prevent a model from just saying "done". Real enforcement must be external:
  CI re-running the gate, the read-only `validator-subagent` gating handoff, or
  a blocking `PreToolUse`/`Stop` hook — but the latter needs the host to honor
  exit-2 / `permissionDecision: deny`, which is unconfirmed on the fork
  (README confirm-item #4). Until confirmed, advisory hooks + a hard gate +
  out-of-band re-run is the only robust combination.

## Confirm-items (from .gigacode/README)

| # | Item | Verdict | Observed fact |
|---|------|---------|---------------|
| 1 | config dir `.gigacode` vs `.qwen`; settings schema | PASS* | OSS dir name is `.qwen` (fork = `.gigacode`); bridged via junction. Our `settings.json` schema is accepted (loads, no parse error). *Caveat: Qwen migrates it (see findings). |
| 2 | `context.fileName: ["GIGACODE.md"]` honored | PASS | `qwen -p` recited all 6 GIGACODE.md non-negotiables and named the file. |
| 3 | hooks avoid `$QWEN_PROJECT_DIR` (relative paths) | PASS | Both hooks resolve everything via `REPO_ROOT = Path(__file__).parents[2]`; payload `cwd` is optional. No `$QWEN_PROJECT_DIR` dependency. |
| 4 | hooks supported (lint PostToolUse, gate Stop) | PASS* | Schema matches Qwen docs verbatim; both scripts behave correctly fed Qwen's stdin-JSON: lint→`hookSpecificOutput.additionalContext` (blocking finding), gate→`systemMessage` (staleness), both exit 0. *Runtime invocation by Qwen still to confirm in TUI (yolo run blocked for the agent). Note: hook path-matching needs a native OS `cwd`; a unix-style `/f/...` cwd would mis-resolve, but Qwen-on-Windows passes Windows paths and the REPO_ROOT fallback covers no-cwd. |
| 5 | subagent tool names match | PARTIAL | In installed Qwen 0.18.1 source: `read_file`(30), `write_file`(27), `read_many_files`(1), `run_shell_command`(22), `glob`(20), `list_directory`(16) all present. BUT our subagent's `search_file_content` appears only 2× (legacy alias); canonical grep tool is `grep_search` (27×). Recommend renaming. |
| 6 | omitted `permissions`/`mcpServers` cause no break | PASS | Session fully functional with neither key present. |

## Suspected discrepancies (verify live)

| Area | Ours | Qwen OSS | Verdict |
|------|------|----------|---------|
| custom command file format | `.md` | both `.toml` and `.md` | NOT a discrepancy. `cli.js` FileCommandLoader builds `[...tomlCommandPromises, ...mdCommandPromises]`; the md loader does `glob("**/*.md")` + frontmatter parsing. Our `quality-gate.md` (frontmatter `description:` + `{{args}}` body) should load. |
| grep tool name | `search_file_content` | `grep_search` | REAL discrepancy. `grep_search` = 27 refs in source; `search_file_content` = 2 (legacy alias). Rename in `validator-subagent.md` to be safe. |

## Flow (Part B)

| Stage | Artifact | Result |
|-------|----------|--------|
| docs → scenario | `scenarios/SHOP/checkout-mix-003/scenario.yaml` | ✅ qwen3.6 (yolo, write-only) generated it; lint = `passed`. Faithful to the doc: 2 populations (checkout closed/stress 10u·2lvl·30s; search open/constant 2rps·60s), graphql price step, `productId` jsonPath extract, `terms.csv` circular feeder, both SLAs, `# TODO` feeder note per skill convention. |
| scenario → Java | `build/qwen-livetest-003/` (pom + `SHOP_CheckoutMix_003.java` + feeder) | ✅ generated via canonical `gatling_generator.py` (run by the verifier — Qwen's headless shell crashes, see findings). |
| quality gate | status | ✅ `passed` — schema, scenario-lint, generator, renderer, pom-pins, maven-compile all passed; 0 blocking, 0 warnings. |

## qwen3.6 behavior notes

- Pre-flight warm-up: replied `OK` correctly, but emitted a visible
  `Thinking...` reasoning block first (qwen3 thinking mode on). Watch for
  thinking-mode noise leaking into tool-call flows.
- Non-interactive `qwen -p` binding to ollama works once auth is fixed; the
  `BOUND` smoke returned cleanly with no thinking-block noise.
- **Headless yolo + shell crashes on Windows:** `qwen -y -p` aborted hard with
  `Error: AttachConsole failed` from `node-pty`
  (`conpty_console_list_agent.js`) the moment a `run_shell_command` was needed —
  node-pty cannot attach a console when the parent is not a real TTY. Workaround
  used: instruct the model to WRITE files only (no shell); the verifier ran the
  generator / mvn / gate. So an autonomous headless agentic loop that needs a
  shell is not viable in this setup without a sandbox/TTY.
- **Model over-reached the skill contract:** asked only for `scenario.yaml`,
  qwen3.6 also wrote `passport.md`, `pom.xml`, the Java simulation and the
  feeder in one shot — i.e. it ran scenario-from-docs AND scenario-to-gatling
  together, despite the skill rule that docs→scenario must NOT emit Java and
  must wait for approval. Useful signal: the local model does not respect
  stage/approval gates on its own; the gate + hooks are what enforce them.
- Quality of the scenario it did produce was high and lint-clean on the first
  pass (minor: used `$.id` not `$.productId` for the extract, and put productId
  in the graphql path query — both acceptable, neither blocking).

## Environment / setup findings (OSS Qwen Code 0.18.1)

- **OpenAI-compatible auth location:** `modelProviders[].apiKey` is NOT used for
  auth. Qwen errored "Отсутствует API Key … укажите settings.security.auth.apiKey
  или OPENAI_API_KEY". Fix: put `apiKey` (+ `baseUrl`) under
  `security.auth`. (Matches upstream issue #3384 friction.)
- **Settings auto-migration (CONFIRMED on the package file):** Qwen rewrote
  `~/.qwen/settings.json` adding `"$version": 4`, AND — because the project
  `.qwen` is a junction to `.gigacode` — on first project load Qwen migrated and
  **rewrote the tracked `.gigacode/settings.json` in place**: reflowed
  `fileName` to multi-line, appended `"$version": 4`, dropped the trailing
  newline, and dropped a `.gigacode/settings.json.orig` backup next to it.
  Implication for shipping: the fork will likely rewrite our committed
  `settings.json` on first run. Decide whether to pre-bake `$version` (once the
  fork's schema version is confirmed) or to .gitignore the `.orig`. Both the
  mutation and the `.orig` are reverted at teardown to keep the package clean.

## Bugs / debt for the package

- **Rename grep tool in `.gigacode/agents/validator-subagent.md`:**
  `search_file_content` → `grep_search` (canonical in Qwen 0.18.1; old name is a
  2-ref legacy alias and may not resolve on the fork).
- **Decide settings `$version` strategy:** Qwen migrates `settings.json` in place
  on first load (adds `"$version": 4`, reflows, drops trailing newline, writes a
  `.orig` backup). Either pre-bake the version the fork expects, or `.gitignore`
  `*.orig`, so first-run does not show the package as "modified".
- **Auth must live at `security.auth.apiKey`** (not `modelProviders[].apiKey`)
  for OpenAI-compatible providers in OSS 0.18.1 — note this in the README
  Confirm-items / install guidance once the fork's behavior is confirmed.

## Exact prompts issued to qwen

1. Pre-flight warm-up (ollama, not Qwen Code):
   `ollama run qwen3.6:35b-a3b-q4_K_M "Reply with exactly: OK"`
2. Binding smoke: `qwen -p "Reply with exactly: BOUND"`
3. Context-honored check (confirm-item 2):
   `qwen -p "What are the non-negotiable working rules for this project? List them as bullets."`
4. Tool enumeration (confirm-item 5, self-report — unreliable):
   `qwen -p "List the exact machine names of every tool you can call, one per line, nothing else."`
5. Part B docs→scenario (yolo, write-only — the run that succeeded):
   `qwen -y -p "Use the scenario-from-docs skill to convert the requirements file e2e/checkout-mix.md into a Gatling-AI scenario.yaml. IMPORTANT: do NOT run any shell commands (no run_shell_command) — only read files and WRITE the YAML file. Use EXACTLY these identifiers, do not ask and do not invent others: system=SHOP, id=checkout-mix, number=003. Write the scenario to scenarios/SHOP/checkout-mix-003/scenario.yaml (create directories as needed). Follow docs/SCENARIO_FORMAT.md and schemas/scenario.schema.json. When done, print the full path of the file you wrote."`
   (An earlier variant that allowed shell crashed on node-pty `AttachConsole`.)

Java generation + quality gate were run by the verifier (not qwen) because of
the headless-shell crash:
- `python tools/gatling_generator/gatling_generator.py scenarios/SHOP/checkout-mix-003/scenario.yaml build/qwen-livetest-003 --format text`
- `python tools/scenario_renderer/scenario_renderer.py scenarios/SHOP/checkout-mix-003/scenario.yaml`
- `python tools/quality_gate/quality_gate.py --scenario scenarios/SHOP/checkout-mix-003/scenario.yaml --project build/qwen-livetest-003`

## Teardown

- Junction `.qwen` removed reparse-safe; `.gigacode` intact.
- `.gigacode/settings.json` reverted (`git checkout`); `.orig` deleted.
- `quality-gate-report.*` and `build/` are gitignored (no repo pollution).
- `~/.qwen/settings.json` (ollama provider) kept — no prior backup existed; it
  is user-level, not a repo artifact.
- Untracked test artifacts left for inspection: `scenarios/SHOP/checkout-mix-003/`
  (scenario.yaml + passport.md are canonical; the stray `pom.xml`/`src/` there
  are the model's over-reach) and `build/qwen-livetest-003/` (canonical
  generated project, gitignored).

# Methodology-First Workflow Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make methodology-first generation the default `/manage-methodology` path while preserving resumability, exact workspace/methodology approvals, manual editing, deterministic final control, and guarded publication.

**Architecture:** The orchestration skill coordinates the workspace and discovery CLIs, two grouped user reviews, the catalog-driven questionnaire, and the deterministic methodology pipeline. A small state tool records resumable checkpoints; the quality gate gains a methodology-first input bundle while retaining its legacy interface. Only the bounded document extractor remains agentic on the local default path, and it can read only locator-selected documents.

**Tech Stack:** Markdown skill/agent contracts, Python 3.11+, existing methodology authoring/publish tools, methodology pipeline from Plan 1, discovery pipeline from Plan 2, unittest/pytest.

**Spec:** `docs/superpowers/specs/2026-08-23-methodology-first-generation-design.md`

## Global Constraints

- Complete Plans 1 and 2 before this plan.
- Preserve the two existing local approval kinds: `workspace-manifest` and `methodology-patch`.
- Never treat surface/profile confirmation as permission to write a canonical file.
- Never apply or offer publication while `ready_for_test` is blocked.
- Treat template incompleteness as advisory unless the document structure itself is invalid.
- Keep existing evidence collectors, reconciler, author, and validator files installed for legacy use, but do not dispatch them on the new default local path.
- The final readiness/template/quality checks are deterministic and invoke no agent.
- The bounded document agent may read only paths selected in `document-jobs.json` and may write only its assigned candidate result; the deterministic CLI validates and installs the final result.
- META remains a user prompt; never claim that the service was queried.
- Source-marker scanning remains an explicit opt-in after the initial bounded scan.
- Manual edits to `answers.yaml` and methodology manual blocks remain supported.
- Reuse the unchanged methodology candidate, patch, descriptor, and approval through pre-apply review and apply.
- Keep publication separate, fixed-target, and separately approved.

---

## Planned File Structure

    schemas/methodology-run-state.schema.json
        Resumable methodology-first checkpoints and artifact identities.
    tools/methodology_workflow/__init__.py
        Package marker.
    tools/methodology_workflow/run_state.py
        State validation, transitions, artifact hashing, and resume summaries.
    tools/methodology_workflow/methodology_workflow.py
        `init`, `advance`, `wait`, `resume`, and `complete` state CLI.
    tools/methodology_workflow/test_run_state.py
        Transition and stale-artifact tests.
    tools/methodology_workflow/test_methodology_first_e2e.py
        Full local four-repository workflow simulation.
    tools/methodology_workflow/README.md
        State CLI and workflow checkpoints.
    tools/methodology_discovery/document_jobs.py
        Adds strict result persistence for the bounded document agent.
    tools/methodology_discovery/methodology_discovery.py
        Adds `record-document-result` CLI command.
    tools/methodology_discovery/test_document_jobs.py
        Tests one-job/one-output persistence and result caps.
    tools/methodology_quality_gate/methodology_quality_gate.py
        Adds deterministic methodology-first pre/post-apply checks.
    tools/methodology_quality_gate/test_methodology_quality_gate.py
        Covers new bundle and preserves all legacy cases.
    tools/methodology_quality_gate/README.md
        Documents both invocation modes and warning semantics.
    .gigacode/agents/mnt-document-extractor.md
        Reads only selected high-signal documents and returns explicit facts.
    .gigacode/skills/manage-methodology/SKILL.md
        Replaces the default evidence-first local sequence.
    .gigacode/commands/manage-methodology.md
        Describes the methodology-first command behavior.
    .gigacode/test_gigacode_package.py
        Structural boundaries, exact command order, and interaction wording.
    GIGACODE.md
        Operator-level methodology-first summary.
    .gigacode/README.md
        Package and agent documentation.
    docs/METHODOLOGY.md
        Artifact flow, questions, manual fallback, readiness, and publication.
    docs/METHODOLOGY-DEFERRED.md
        Moves graph generation and META provider integration to explicit future work.

### Task 1: Add a deterministic methodology-first quality-gate bundle

**Files:**
- Modify: `tools/methodology_quality_gate/methodology_quality_gate.py`
- Modify: `tools/methodology_quality_gate/test_methodology_quality_gate.py`
- Modify: `tools/methodology_quality_gate/README.md`

**Interfaces:**
- Preserves: `run_gate(...) -> GateReport` for legacy evidence mode
- Produces: `run_methodology_first_gate(...) -> GateReport`
- Extends CLI with: `--mode methodology-first`, `--methodology-input`, `--readiness-report`, `--template-report`, `--generation-state`, `--template-contract`, `--questions`, `--descriptor`, and `--load-test-root`
- Extends CLI with: `--post-apply`

- [ ] **Step 1: Write failing compatibility and new-mode tests**

Keep every existing test unchanged, then add:

    def test_methodology_first_ready_with_template_gaps_is_warning_only(self) -> None:
        paths = fixtures.methodology_first_gate_fixture(template_status="incomplete")
        report = gate.run_methodology_first_gate(**paths.pre_apply_arguments())
        self.assertEqual(report.status, "passed_with_warnings")
        self.assertFalse(any(item.rule == "readiness-status" for item in report.findings))
        self.assertTrue(any(item.rule == "template-completeness" for item in report.findings))

    def test_methodology_first_readiness_blocks_approval(self) -> None:
        paths = fixtures.methodology_first_gate_fixture(readiness_status="blocked")
        report = gate.run_methodology_first_gate(**paths.pre_apply_arguments())
        self.assertEqual(report.status, "blocked")

    def test_reports_are_recomputed_not_blindly_trusted(self) -> None:
        paths = fixtures.methodology_first_gate_fixture()
        paths.readiness_report.write_text('{"version": 1, "status": "ready"}', encoding="utf-8")
        report = gate.run_methodology_first_gate(**paths.pre_apply_arguments())
        self.assertEqual(report.status, "blocked")
        self.assertIn("control-report-mismatch", finding_rules(report))

Add cases for candidate/generation-state mismatch, v2 snapshot identity, exact
patch scope, secret/artifact-boundary checks, post-apply descriptor binding, and
mutually exclusive legacy/methodology-first bundles.

- [ ] **Step 2: Run the focused tests and confirm failure**

Run:

    python tools/methodology_quality_gate/test_methodology_quality_gate.py -v

Expected: existing tests pass and new methodology-first tests fail because the
new bundle is unavailable.

- [ ] **Step 3: Separate shared, legacy, and methodology-first checks**

Shared checks remain:

- required canonical headings;
- placeholder scan;
- secret detection;
- artifact-boundary enforcement;
- exact patch scope in pre-apply mode;
- workspace snapshot structural/hash validation for version 1 or 2.

For v2 snapshots, unavailable entries are valid only with the exact
`repository-unavailable` diagnostic shape from Plan 2. An unavailable required
repository or top-level snapshot status `blocked` is a blocking finding; an
unavailable optional repository is a warning.

Legacy checks remain unchanged behind the legacy bundle. The methodology-first
bundle adds:

- validate `methodology-input.yaml` against its schema;
- require the input snapshot ID to equal `workspace-snapshot.json`;
- require confirmed surface and accepted profile;
- recompute readiness from methodology input and question catalog, then compare
  it to the supplied readiness report;
- recompute template conformance from candidate, input, and template contract,
  then compare it to the supplied template report;
- require `ready_for_test` and `template_complete` booleans to agree with their
  respective status fields;
- verify every candidate generated-block body hash against the state's actual
  hash and every freshly rendered body against `rendered_sha256`; allow a hash
  difference only when state resolution is `keep`, then emit
  `user-kept-generated-block` as a warning;
- block on readiness, invalid report bindings, invalid markers, or unresolved
  managed-block drift;
- emit one warning per partial/missing template section without blocking.

Import the Plan 1 functions instead of implementing a second readiness or
template engine.

- [ ] **Step 4: Bind pre-apply and post-apply bytes differently**

Pre-apply mode requires `--base`, `--patch`, and `--descriptor`; verify that the
patch transforms base into candidate and that all three SHA-256 values equal the
descriptor.

Post-apply mode receives canonical `methodology.md` as `--candidate`, the same
descriptor, and the same methodology-first control inputs. It does not reapply
the patch to the now-updated base. Instead it requires the canonical file hash
to equal `descriptor.candidate_sha256` and reruns shared and methodology-first
checks over those exact bytes.

- [ ] **Step 5: Preserve the old CLI and add exact new invocations**

Existing commands without `--mode` retain legacy validation. The new pre-apply
invocation is:

    python tools/methodology_quality_gate/methodology_quality_gate.py --mode methodology-first --candidate <run-dir>/methodology.candidate.md --methodology-input <run-dir>/methodology-input.yaml --readiness-report <run-dir>/methodology-readiness-report.json --template-report <run-dir>/methodology-template-report.json --generation-state <run-dir>/generation-state.json --template-contract <load-test-root>/.gigacode/skills/manage-methodology/templates/methodology-template-contract.yaml --questions <load-test-root>/.gigacode/skills/manage-methodology/questions.yaml --workspace-snapshot <run-dir>/workspace-snapshot.json --base <load-test-root>/methodology.md --patch <run-dir>/methodology.patch --descriptor <run-dir>/methodology-descriptor.json --out-dir <run-dir> --load-test-root <load-test-root>

The post-apply command adds `--post-apply`, points `--candidate` at canonical
`methodology.md`, and omits `--base` and `--patch`.

In methodology-first mode, resolve candidate, input, reports, state, snapshot,
base/patch/descriptor, and output paths below `--load-test-root` before reading
or writing. The shipped question/template assets must resolve below the installed
manage-methodology skill directory. Legacy mode keeps its current CLI contract.

Return codes remain 0 passed, 1 passed with warnings, and 2 blocked/invalid.
`passed_with_warnings` is safe for apply when readiness is ready.

- [ ] **Step 6: Run gate tests**

Run:

    python tools/methodology_quality_gate/test_methodology_quality_gate.py -v

Expected: PASS in both legacy and methodology-first modes.

- [ ] **Step 7: Commit the new gate mode**

    git add tools/methodology_quality_gate/methodology_quality_gate.py tools/methodology_quality_gate/test_methodology_quality_gate.py tools/methodology_quality_gate/README.md
    git commit -m "feat: gate methodology-first candidates"

### Task 2: Make resume state explicit and artifact-bound

**Files:**
- Create: `schemas/methodology-run-state.schema.json`
- Create: `tools/methodology_workflow/__init__.py`
- Create: `tools/methodology_workflow/run_state.py`
- Create: `tools/methodology_workflow/methodology_workflow.py`
- Create: `tools/methodology_workflow/test_run_state.py`
- Create: `tools/methodology_workflow/README.md`

**Interfaces:**
- Produces: `load_state(path: Path) -> RunState`
- Produces: `advance(state, stage, artifacts) -> RunState`
- Produces: `wait_for_user(state, kind, item_ids) -> RunState`
- Produces: `resume_summary(state, run_dir) -> dict[str, Any]`
- Produces CLI: `init`, `advance`, `wait`, `resume`, `complete`

- [ ] **Step 1: Write failing state-machine tests**

The ordered stage IDs are:

    workspace-review
    workspace-snapshot
    discovery
    surface-review
    profile-review
    questionnaire
    render
    output-control
    patch-prepare
    patch-review
    patch-apply
    post-apply-control
    completed

Tests must prove:

- stages cannot skip predecessors;
- `wait` accepts only `workspace`, `surface`, `profile`, `questions`,
  `managed-drift`, or `methodology-approval`;
- resume lists pending question IDs and recorded artifact paths;
- an artifact whose current SHA-256 differs from state is reported stale;
- stale discovery/surface/profile/answers artifacts roll the safe resume point
  back to their owning stage;
- state never counts as an approval and contains no `approved_by` field;
- state output is atomic and confined to the supplied run directory.

- [ ] **Step 2: Run tests and confirm failure**

Run:

    python tools/methodology_workflow/test_run_state.py -v

Expected: FAIL because the workflow state package does not exist.

- [ ] **Step 3: Implement the closed v2 run-state contract**

The state contains:

    version: 2
    run_id: RUN-001
    mode: create
    current_stage: surface-review
    step_status: awaiting_user
    completed_stages: [workspace-review, workspace-snapshot, discovery]
    waiting:
      kind: surface
      item_ids: [http:orders:POST:/documents]
    snapshot_id: 64-lowercase-hex
    candidate_id: 64-lowercase-hex-or-null
    artifacts:
      surface-candidate:
        path: surface-candidate.json
        sha256: 64-lowercase-hex
    updated_at: RFC3339-UTC

Artifact paths are run-relative POSIX paths and cannot escape the run directory.
`mode` is `create` or `update-local`; publication is not a local run stage.

- [ ] **Step 4: Implement exact CLI commands**

    python tools/methodology_workflow/methodology_workflow.py init --run-dir <run-dir> --run-id RUN-001 --mode create --load-test-root <load-test-root>
    python tools/methodology_workflow/methodology_workflow.py advance --run-dir <run-dir> --stage discovery --artifact workspace-snapshot=workspace-snapshot.json --load-test-root <load-test-root>
    python tools/methodology_workflow/methodology_workflow.py wait --run-dir <run-dir> --kind questions --item environment.name --item observability.dashboard --load-test-root <load-test-root>
    python tools/methodology_workflow/methodology_workflow.py resume --run-dir <run-dir> --load-test-root <load-test-root>
    python tools/methodology_workflow/methodology_workflow.py complete --run-dir <run-dir> --artifact post-apply-report=methodology-quality-report.json --load-test-root <load-test-root>

Each mutating command validates the existing state and target artifact hashes
before atomically replacing `run-state.json`. `resume` is read-only and prints a
compact JSON summary. Every command first resolves run-dir beneath the explicit
load-test root and rejects symlink/reparse escapes.

- [ ] **Step 5: Run state tests**

Run:

    python tools/methodology_workflow/test_run_state.py -v

Expected: PASS.

- [ ] **Step 6: Commit resumable state support**

    git add schemas/methodology-run-state.schema.json tools/methodology_workflow/__init__.py tools/methodology_workflow/run_state.py tools/methodology_workflow/methodology_workflow.py tools/methodology_workflow/test_run_state.py tools/methodology_workflow/README.md
    git commit -m "feat: track methodology-first run state"

### Task 3: Add the only bounded local extraction agent

**Files:**
- Create: `.gigacode/agents/mnt-document-extractor.md`
- Modify: `tools/methodology_discovery/document_jobs.py`
- Modify: `tools/methodology_discovery/methodology_discovery.py`
- Modify: `tools/methodology_discovery/test_document_jobs.py`
- Modify: `.gigacode/test_gigacode_package.py`

**Interfaces:**
- Produces CLI: `record-document-result`
- Produces agent envelope: `{status, summary, counts, artifact, next_action}`

- [ ] **Step 1: Write failing result-persistence tests**

The exact command is:

    python tools/methodology_discovery/methodology_discovery.py record-document-result --job <run-dir>/discovery/orders-docs/document-jobs.json --candidate <run-dir>/discovery/orders-docs/extractor-results/bounded-document-v1.candidate.json --out <run-dir>/discovery/orders-docs/extractor-results/bounded-document-v1.json --load-test-root <load-test-root>

Tests reject:

- output outside the job's assigned path;
- candidate input over 512 KiB;
- invalid UTF-8 or JSON;
- a source path/hash absent from the job;
- more than 500 candidates;
- an inferred flow not accompanied by an explicit source line range;
- mismatched repository or snapshot identity.

The successful case writes one schema-valid extractor result atomically.

- [ ] **Step 2: Write failing agent structural tests**

Require `mnt-document-extractor` in `REQUIRED_AGENTS` and assert that its contract:

- allows only `read_file`, `write_file`, and `run_shell_command`;
- disallows `edit`, `glob`, and `grep_search`;
- accepts exactly one selected `document-jobs.json` repository job;
- reads only the job's materialized run-directory paths and forbids reading SUT
  paths, unlisted paths, code, workspace manifests, and methodology;
- permits only component/interface/integration/explicit-flow facts;
- requires relative path plus exact line range for every fact;
- forbids inference from names and forbids full architecture summaries;
- writes only the job's assigned candidate path and uses only
  `record-document-result` to install the final artifact;
- returns no document content or reasoning in its compact envelope.

- [ ] **Step 3: Run tests and confirm failure**

Run:

    python -m pytest tools/methodology_discovery/test_document_jobs.py .gigacode/test_gigacode_package.py -q

Expected: FAIL because result persistence and the agent do not exist.

- [ ] **Step 4: Implement validated result persistence**

Require the candidate and output paths to equal the two paths stored in the job,
enforce the candidate byte cap before decoding JSON, validate the job binding
and extractor-result schema, then atomically write the final assigned output.
Return exit 2 for domain errors without a traceback. Never modify or delete the
agent candidate; it remains an auditable untrusted input inside the run.

- [ ] **Step 5: Write the bounded agent contract**

The agent reads the job, then each listed materialized file only. Its normalized result uses
`extractor_id: bounded-document`, `extractor_version: 1`, and confidence
`confirmed` only for text that explicitly states the fact. A flow requires an
explicit sequence/trigger/outcome in the source; otherwise the agent emits no
flow. Failure returns `blocked` or `completed` with warnings so the workflow can
offer manual entry.

- [ ] **Step 6: Run document/agent tests**

Run:

    python -m pytest tools/methodology_discovery/test_document_jobs.py .gigacode/test_gigacode_package.py -q

Expected: PASS.

- [ ] **Step 7: Commit the bounded agent path**

    git add .gigacode/agents/mnt-document-extractor.md .gigacode/test_gigacode_package.py tools/methodology_discovery/document_jobs.py tools/methodology_discovery/methodology_discovery.py tools/methodology_discovery/test_document_jobs.py
    git commit -m "feat: add bounded document extraction agent"

### Task 4: Replace the default local skill sequence and encode the questionnaire UX

**Files:**
- Modify: `.gigacode/skills/manage-methodology/SKILL.md`
- Modify: `.gigacode/commands/manage-methodology.md`
- Modify: `.gigacode/test_gigacode_package.py`

- [ ] **Step 1: Replace old structural expectations with failing methodology-first expectations**

Preserve the six labelled lifecycle command tests for workspace and methodology
prepare/record/apply. Replace assertions that require the evidence reconciler,
author, and validator on the default local path with assertions for this order:

1. resume/restart check;
2. workspace preview, exact manifest diff, and explicit workspace approval only
   when membership changed;
3. independent workspace snapshot;
4. cached bounded discovery;
5. optional selected-document extractor jobs;
6. one grouped surface review;
7. one default profile/META review;
8. catalog-derived missing question blocks;
9. deterministic build and two reports;
10. managed-drift resolution when present;
11. one exact methodology patch/descriptor;
12. methodology-first quality gate;
13. exact diff and explicit methodology approval;
14. unchanged apply and post-apply gate;
15. completed local state.

Also assert that the local workflow section does not mention dispatching
`mnt-module-inspector`, `mnt-confluence-researcher`, `mnt-evidence-reconciler`,
`mnt-author`, or `mnt-validator`. Keep their files and package membership tests.

- [ ] **Step 2: Add exact interaction-copy tests**

Require the following user-visible blocks in the skill.

Surface review:

    Обнаружена поверхность системы, сгруппированная по компонентам и протоколам.
    Ответьте «принять всё», «исключить: <номера>» или
    «добавить: <тип>, <название>».

Profile review:

    Предлагается профиль default-v1:
    - p95 времени отклика <= 1 с;
    - технические ошибки <= 5%;
    - CPU приложения на одном плече OpenShift <= 40%;
    - память <= 80% без устойчивого роста;
    - ступень 20 минут, подтверждение 2 часа, стабильность 8 часов на 0,8 максимума.

    Проверьте SLA/SLO в контракте META. META автоматически не опрашивалась.
    Ответьте «оставить по умолчанию» либо перечислите изменения и ссылку/ID META.

Question block:

    Остались обязательные параметры из questions.yaml:
    - environment.name — На каком стенде будут проводиться испытания?
    - observability.dashboard — Где отслеживать CPU, память и время отклика?

    Можно ответить в сообщении или вручную изменить <run-dir>/answers.yaml.
    После ручного изменения повторно запускаются только валидация и рендеринг;
    discovery не повторяется.

The skill may replace concrete question lines with the actual catalog entries,
but the headers, answer grammar, manual-file fallback, and no-rescan statement
must be exact and tested.

- [ ] **Step 3: Run package tests and confirm failure**

Run:

    python .gigacode/test_gigacode_package.py -v

Expected: FAIL against the existing evidence-first sequence.

- [ ] **Step 4: Rewrite `create` and `update-local` orchestration**

Encode these operational rules:

- if workspace membership is unchanged and already confirmed, do not manufacture
  a manifest diff or ask for workspace approval again;
- on an explicit restart choice, move the unfinished run to a sibling
  `<run-id>.abandoned.<UTC-timestamp>` directory after resolving both paths under
  the load-test root; do not recursively delete the old run;
- snapshot every repository and honor each dirty policy;
- stop before discovery when the v2 snapshot status is blocked by an unavailable
  required repository; show optional unavailable repositories as warnings;
- run the `contracts` layer first and merge its result;
- when that result is not reviewable, run `documents`, process only its selected
  jobs, and merge again; when it is still not reviewable, run `configuration`;
- stop entering later layers as soon as a reviewable surface exists unless the
  user explicitly asks to deepen discovery;
- if contracts/documents/configuration still produce no reviewable surface,
  offer exactly: enable bounded source markers, name another document as
  `<repo-id>:<relative-path>`, or enter the surface manually;
- dispatch `mnt-document-extractor` only for emitted jobs and ingest only schema-
  valid results;
- show the merged surface in numbered groups and store decisions before creating
  `surface-review.json`;
- when a group has more than 25 entities, show its count and first 25 stable
  keys, then expand only that group on request; never convert hidden rows into
  implicit acceptance or exclusion;
- show the whole default profile once, include per-field sources, show the META
  reminder, and persist accept/overrides in `answers.yaml`;
- load unresolved questions from `questions.yaml`, group by section, and show at
  most four at a time;
- accept chat corrections by stable question ID or manual `answers.yaml` edits;
- rerun pipeline build/check after each answer without rerunning discovery;
- show both readiness and 17-section completeness summaries;
- for each template gap, show its related catalog question when available; for
  sections whose contract allows it, accept `not applicable` only together with
  a non-empty reason stored in `answers.yaml`;
- stop before patch preparation when readiness is blocked;
- allow template warnings to continue to exact diff/approval;
- resolve generated-block drift through explicit `keep`, `replace`, or `move to
  manual` decisions supported by Plan 1, then rerender;
- retain the exact labelled authoring CLI invocations and approval boundaries;
- before requesting methodology approval, show a compact change summary from
  the candidate/generation state (changed generated section IDs, preserved
  manual section IDs, readiness, template gaps, warnings, and candidate hash),
  followed by the complete unchanged patch;
- use the new quality-gate command before approval and in post-apply mode after
  apply;
- never dispatch any legacy evidence/author/validator agent on this path.

`keep` preserves the changed generated body for this run and records a warning;
`replace` restores the deterministic generated body; `move to manual` transfers
the changed body to that section's manual block before regeneration. A later
clean regeneration may replace a one-run `keep`, so the durable prose fallback
is `move to manual`. Every decision is recorded in the run artifact used by the
renderer.

Preserve these six labels and invocations exactly in the rewritten skill:

    <!-- cli: workspace-prepare -->
    `python tools/methodology_authoring/methodology_authoring.py prepare --kind workspace-manifest --base <load-test-root>/workspace.yaml --candidate <run-dir>/workspace.candidate.yaml --patch <run-dir>/workspace.patch --out <run-dir>/workspace-descriptor.json --load-test-root <load-test-root>`

    <!-- cli: workspace-record -->
    `python tools/methodology_authoring/methodology_authoring.py record-approval --descriptor <run-dir>/workspace-descriptor.json --approved-by <approved-identity> --out <run-dir>/workspace-approval.json --load-test-root <load-test-root>`

    <!-- cli: workspace-apply -->
    `python tools/methodology_authoring/methodology_authoring.py apply --base <load-test-root>/workspace.yaml --candidate <run-dir>/workspace.candidate.yaml --patch <run-dir>/workspace.patch --approval <run-dir>/workspace-approval.json --load-test-root <load-test-root>`

    <!-- cli: methodology-prepare -->
    `python tools/methodology_authoring/methodology_authoring.py prepare --kind methodology-patch --base <load-test-root>/methodology.md --candidate <run-dir>/methodology.candidate.md --patch <run-dir>/methodology.patch --out <run-dir>/methodology-descriptor.json --load-test-root <load-test-root>`

    <!-- cli: methodology-record -->
    `python tools/methodology_authoring/methodology_authoring.py record-approval --descriptor <run-dir>/methodology-descriptor.json --approved-by <approved-identity> --out <run-dir>/methodology-approval.json --load-test-root <load-test-root>`

    <!-- cli: methodology-apply -->
    `python tools/methodology_authoring/methodology_authoring.py apply --base <load-test-root>/methodology.md --candidate <run-dir>/methodology.candidate.md --patch <run-dir>/methodology.patch --approval <run-dir>/methodology-approval.json --load-test-root <load-test-root>`

- [ ] **Step 5: Update command delegation text**

The command describes bounded discovery, the default profile, catalog-driven
questions, independent readiness/template reports, manual fallback, exact two-
approval local lifecycle, and separate publication. It must not claim full
repository or Confluence recollection.

- [ ] **Step 6: Run package and lifecycle parser tests**

Run:

    python .gigacode/test_gigacode_package.py -v
    python tools/methodology_authoring/test_methodology_authoring.py -v

Expected: PASS. All six labelled lifecycle examples parse and reuse matching
operands.

- [ ] **Step 7: Commit the methodology-first orchestration**

    git add .gigacode/skills/manage-methodology/SKILL.md .gigacode/commands/manage-methodology.md .gigacode/test_gigacode_package.py
    git commit -m "feat: make methodology-first the default workflow"

### Task 5: Preserve fixed-target publication without restoring local evidence collection

**Files:**
- Modify: `.gigacode/skills/manage-methodology/SKILL.md`
- Modify: `.gigacode/test_gigacode_package.py`
- Modify: `.gigacode/agents/mnt-confluence-researcher.md`

- [ ] **Step 1: Write failing publish-boundary tests**

Require publication to:

- start only from a completed local run whose post-apply gate is not blocked and
  whose readiness report is `ready`;
- use an existing confirmed `confluence-snapshot.json` when it matches the run;
- when the new local path has no snapshot, ask for an exact page ID and dispatch
  the read-only Confluence researcher in `fixed-page-snapshot` mode;
- never search for a page in `fixed-page-snapshot` mode;
- stop if no exact page ID or host read capability is available;
- retain exact publish prepare/diff/approval/validate/update ordering;
- keep `mnt-confluence-publisher` as the only page writer.

For methodology-first runs, both `passed` and `passed_with_warnings` are green
publication preconditions when `ready_for_test` is true; advisory template gaps
remain visible in the published methodology and report.

- [ ] **Step 2: Run publish tests and confirm failure**

Run:

    python .gigacode/test_gigacode_package.py -v

Expected: FAIL because the existing publish path assumes the local evidence run
already created a page snapshot.

- [ ] **Step 3: Add fixed-page snapshot mode to the researcher contract**

The mode receives one explicit page ID, permits one host page-read call for that
ID, writes the existing `confluence-snapshot.json` shape, and returns blocked on
missing capability. It does not search, select, rank, or substitute pages and
never receives repository paths.

- [ ] **Step 4: Update publish orchestration**

Reuse the existing confirmed snapshot when present. Otherwise, ask for the exact
target page ID, obtain only its read snapshot, show the target identity to the
user, and then continue through the existing publish preparation and separate
approval. Do not run this branch during `create` or `update-local`.

- [ ] **Step 5: Run publication regression tests**

Run:

    python -m pytest .gigacode/test_gigacode_package.py tools/methodology_publish -q

Expected: PASS, including all stale page/local hash failure cases.

- [ ] **Step 6: Commit fixed-target publish compatibility**

    git add .gigacode/skills/manage-methodology/SKILL.md .gigacode/agents/mnt-confluence-researcher.md .gigacode/test_gigacode_package.py
    git commit -m "fix: preserve fixed-target methodology publication"

### Task 6: Update operator documentation and explicit deferrals

**Files:**
- Modify: `GIGACODE.md`
- Modify: `.gigacode/README.md`
- Modify: `docs/METHODOLOGY.md`
- Modify: `docs/METHODOLOGY-DEFERRED.md`

- [ ] **Step 1: Write a documentation checklist test**

Extend `.gigacode/test_gigacode_package.py` to require the operator docs to name:

- arbitrary multi-repository workspace roles;
- bounded layered discovery and its default budgets;
- source-marker opt-in;
- one grouped surface review and one profile review;
- default-v1 values and META manual reminder;
- stable-ID `questions.yaml` plus editable `answers.yaml`;
- all 17 sections;
- blocking readiness versus advisory template completeness;
- managed/manual blocks and drift choices;
- exact approvals and separate publish approval;
- legacy evidence path retained but not default;
- graph construction, META provider, and class-specific profiles as deferred.

- [ ] **Step 2: Run the checklist and confirm failure**

Run:

    python .gigacode/test_gigacode_package.py -v

Expected: FAIL until documentation matches the new workflow.

- [ ] **Step 3: Rewrite the methodology documentation around actual artifacts**

Use the run tree from the approved spec. Include copyable CLI examples for
workspace snapshot, discovery scan/merge/review, pipeline build/check,
methodology prepare/gate/record/apply/post-apply, and publication. Explain the
meaning of return codes 0/1/2 and that 1 is a non-blocking warning for this flow.

Document how an owner adds an ordinary question:

1. add one entry with a unique stable ID and existing target to `questions.yaml`;
2. run contract/questionnaire tests;
3. no skill orchestration change is required;
4. a new target still requires schema, catalog, renderer, and contract changes.

Show manual corrections using `answers.yaml` and manual prose using managed
section markers. State that editing generated blocks triggers a choice rather
than silent overwrite.

- [ ] **Step 4: Update deferred work without claiming implementation**

List these separately:

- system-class profile selection and percentile policy;
- authenticated META provider through MCP or another API;
- adapters for existing Graphify/Code Graph artifacts;
- opt-in jQAssistant Java graph provider;
- additional extractor families and UI forms.

Do not list bounded discovery, multi-repo support, editable answers, or structural
output control as deferred after this implementation.

- [ ] **Step 5: Run documentation/package tests**

Run:

    python .gigacode/test_gigacode_package.py -v

Expected: PASS.

- [ ] **Step 6: Commit operator documentation**

    git add GIGACODE.md .gigacode/README.md docs/METHODOLOGY.md docs/METHODOLOGY-DEFERRED.md .gigacode/test_gigacode_package.py
    git commit -m "docs: explain methodology-first workflow"

### Task 7: Prove the full local workflow and regressions

**Files:**
- Create: `tools/methodology_workflow/test_methodology_first_e2e.py`
- Modify: `tools/methodology_workflow/README.md`

- [ ] **Step 1: Write a failing end-to-end local run**

Reuse the Plan 2 four-repository fixture and drive the public CLIs in the same
order as the skill. Provide a validated bounded-document result, accept the
surface except health, accept default-v1 with one manual META response-time
value/reference, answer all required scalar questions, and begin with an
existing methodology containing manual prose.

- [ ] **Step 2: Assert all accepted outcomes**

The test must prove:

1. workspace snapshot contains all repositories;
2. discovery reads only indexed files and merges one system surface;
3. `surface-review.json` is confirmed;
4. resolved profile uses user override over manual META over default;
5. the happy path asks no more than ten scalar questions;
6. candidate contains each canonical heading once;
7. manual prose survives byte-for-byte;
8. readiness is ready while template completeness is independently reported;
9. pre-apply gate is not blocked;
10. apply fails without the exact approval and succeeds with it;
11. post-apply gate binds canonical bytes to the same descriptor;
12. rerunning identical inputs produces identical candidate and reports;
13. editing only `answers.yaml` rerenders without invoking discovery;
14. changing one repository rescans only it;
15. completed run state contains artifact hashes but no approval authority;
16. all SUT repository bytes remain unchanged.

- [ ] **Step 3: Run the E2E test and confirm failure**

Run:

    python tools/methodology_workflow/test_methodology_first_e2e.py -v

Expected: FAIL until the three plans integrate cleanly.

- [ ] **Step 4: Fix integration defects without expanding scope**

Do not introduce a graph builder, META network access, whole-tree agent scan,
new profile-selection UI, or automatic business-flow inference to satisfy the
fixture.

- [ ] **Step 5: Run all relevant suites**

Run:

    python -m pytest tools/workspace_discovery tools/methodology_discovery tools/methodology_pipeline tools/methodology_workflow tools/methodology_authoring tools/methodology_quality_gate tools/methodology_publish .gigacode/test_gigacode_package.py -q

Expected: PASS.

- [ ] **Step 6: Run full repository regression tests**

Run:

    python -m unittest discover -s tools -p "test_*.py" -v
    python .gigacode/test_gigacode_package.py -v
    python -m pip check

Expected: all tests pass and dependencies are consistent.

- [ ] **Step 7: Scan implementation for unfinished placeholders**

Run:

    rg -n "TODO|FIXME|TBD|NotImplementedError" tools/methodology_pipeline tools/methodology_discovery tools/methodology_workflow tools/methodology_quality_gate .gigacode/skills/manage-methodology .gigacode/agents/mnt-document-extractor.md

Expected: no hits.

- [ ] **Step 8: Commit full-workflow acceptance coverage**

    git add tools/methodology_workflow/test_methodology_first_e2e.py tools/methodology_workflow/README.md
    git commit -m "test: prove methodology-first workflow end to end"

## Plan 3 Completion Evidence

Before declaring the implementation complete, capture:

    python -m pytest tools/workspace_discovery tools/methodology_discovery tools/methodology_pipeline tools/methodology_workflow tools/methodology_authoring tools/methodology_quality_gate tools/methodology_publish .gigacode/test_gigacode_package.py -q
    python -m unittest discover -s tools -p "test_*.py" -v
    python -m pip check
    git status --short

Expected: all selected and full tool suites pass; there are no broken
dependencies; no SUT fixture was mutated; and the worktree contains only
intentional implementation or pre-existing user changes.

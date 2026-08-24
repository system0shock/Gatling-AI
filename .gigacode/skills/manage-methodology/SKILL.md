---
name: manage-methodology
description: Use when creating, updating, checking, or publishing a system load-testing methodology (MNT).
---

# Manage Methodology

Use this skill for `create`, `update-local`, and `publish` methodology runs.
`create` and `update-local` use the methodology-first MVP below. The longer
evidence workflow remains available only when the user explicitly asks for it.
Only `publish` may request a Confluence update through the separate publisher
role.

## Default local MVP

This route replaces legacy steps 5–8 and their subagent requirements for normal
`create` and `update-local` runs. Keep the existing hash-bound workspace and
methodology approvals; do not treat surface or profile confirmation as file-write
approval.

1. Reuse a confirmed `workspace.yaml`, or follow legacy steps 1–4 only when
   repository membership needs confirmation. Produce a fresh
   `workspace-snapshot.json` for every run.
2. Run the thin bounded scanner:

   `python tools/methodology_discovery/methodology_discovery.py scan --manifest <load-test-root>/workspace.yaml --workspace-snapshot <run-dir>/workspace-snapshot.json --run-dir <run-dir> --load-test-root <load-test-root>`

   It reads signature-selected OpenAPI, AsyncAPI, GraphQL, deployment, build, and
   configuration files. It indexes selected architecture/endpoint documents but
   does not ask an agent to summarize them. Do not dispatch repository inspectors,
   a reconciler, author, validator, graph builder, or Java source scan on this
   route.
3. Show `surface-candidate.json` in grouped, numbered form and ask:

   > Обнаружена поверхность системы. Оставить всё, исключить элементы по номерам
   > или добавить вручную: тип и название?

   Save the answer in `surface-decisions.yaml`; manual additions use its `add`
   list. Then run:

   `python tools/methodology_discovery/methodology_discovery.py confirm --candidate <run-dir>/surface-candidate.json --decisions <run-dir>/surface-decisions.yaml --out <run-dir>/surface-review.json --load-test-root <load-test-root>`

4. Show `profiles/default-v1.yaml` once and ask:

   > Оставить набор тестов и SLA/SLO по умолчанию или скорректировать?

   State the defaults in the same message: p95 ≤ 1 s, technical errors ≤ 5%,
   application CPU on one OpenShift arm ≤ 40%, memory ≤ 80% without sustained
   growth, 20-minute maximum-search steps, 2-hour confirmation, and 8-hour
   stability at 0.8 of the confirmed maximum. Remind the user that SLA/SLO may be
   copied manually from META; never claim META was queried. Record acceptance,
   META references, and overrides in `<run-dir>/answers.yaml`.
5. Run `methodology_pipeline.py build` with the confirmed snapshot/surface,
   default profile, `questions.yaml`, `answers.yaml`, and shipped template as
   documented in `tools/methodology_pipeline/README.md`. Read the readiness report,
   map missing question IDs back to `questions.yaml`, and ask at most four at a
   time. The question catalog is the extension point: adding an ordinary question
   does not require changing this skill.

   > Остались обязательные параметры из questions.yaml. Можно ответить здесь по
   > стабильным ID или вручную изменить `<run-dir>/answers.yaml`.

   After chat or manual edits, rerun only `build`; do not rescan repositories.
6. Show both outcomes: blocking `ready_for_test` and advisory completeness of all
   17 template sections. Stop before patch preparation while readiness is blocked.
   Template gaps remain visible but do not start an agent. Manual text stays in
   manual blocks; generated-block drift uses explicit `keep`, `replace`, or
   `move-to-manual` decisions already supported by the pipeline.
7. When ready, run `methodology_pipeline.py check`, prepare the exact methodology
   patch with the labelled `methodology-prepare` command below, show the complete
   diff, and wait for explicit `methodology-patch` approval. Record/apply with the
   existing labelled commands, then run `check` again against canonical
   `methodology.md`. `create` and `update-local` never change Confluence.

## Non-negotiable boundaries

- The load-test repository is the only writable location. SUT modules, raw source
  inputs, canonical MNT text before approval, and Confluence are read-only.
- On an explicitly requested legacy evidence run, use fresh subagents with narrow
  prompts. Read only compact JSON envelopes unless a blocker requires artifact detail.
- Treat a `blocked` result from any required stage as a stop. Do not request an
  approval, prepare a substitute, apply a patch, or publish after that stop.
- `workspace-manifest` and `methodology-patch` are separate approval kinds.
  Their approvals bind the exact base, candidate, and patch SHA-256 values.

## Run-state file

`run-state.json` in the run directory tracks incremental progress so the workflow
survives conversation interruptions. It is advisory (not security-critical like
approval artifacts) and is written by the orchestrating skill after each step:

```json
{
  "version": 1,
  "run_id": "RUN-001",
  "mode": "create|update-local",
  "current_step": 7,
  "step_status": "awaiting_user|completed|blocked",
  "completed_steps": [1,2,3,4,5,6],
  "gap_state": {
    "total": 5,
    "answered": ["gap-001", "gap-003"],
    "pending": ["gap-002", "gap-004", "gap-005"]
  },
  "updated_at": "2026-07-21T14:30:00Z"
}
```

The hash-bound approval artifacts (`workspace-approval.json`,
`methodology-approval.json`) remain the security boundary; `run-state.json` only
tracks workflow progress and never authorizes a file write.

## Legacy evidence workflow

### 0. Check for an unfinished run

Before starting a new run, check the run directory for `run-state.json`. If it
exists and `step_status` is not `completed`, show the user the current step,
completed steps, and pending gaps. Offer **resume** (continue from the recorded
step) or **restart** (discard the run directory and start fresh). If the user
chooses resume, skip to the recorded `current_step` and reuse existing
artifacts. Update `run-state.json` after each completed step so that an
interruption never loses progress.

### 1. Workspace preview approval

Run the Phase 3a preview from the bootstrap manifest. Show the discovery preview
and ask the user to confirm only the modules to include. This is the **workspace
preview approval**; it selects candidates but is not permission to change the
manifest. Write `run-state.json` with `current_step: 2` after the user confirms.

### 2. Prepare the workspace candidate

Create `workspace.candidate.yaml` from the user-confirmed modules. The descriptor
carries the approved kind used by later record and apply commands.

<!-- cli: workspace-prepare -->
`python tools/methodology_authoring/methodology_authoring.py prepare --kind workspace-manifest --base <load-test-root>/workspace.yaml --candidate <run-dir>/workspace.candidate.yaml --patch <run-dir>/workspace.patch --out <run-dir>/workspace-descriptor.json --load-test-root <load-test-root>`

Do not edit `workspace.yaml` directly.

### 3. Show exact workspace diff and obtain the first explicit approval

**Show exact workspace diff** from the prepared patch. Wait for explicit
workspace-manifest approval after showing the exact diff and capture the approved
identity. Do not infer approval from the preview or from an earlier run.

Update `run-state.json` with `current_step: 4` and `completed_steps: [1,2,3]`
after the approval is recorded.

Only after that reply, record the descriptor's kind and apply the approved
workspace candidate:

<!-- cli: workspace-record -->
`python tools/methodology_authoring/methodology_authoring.py record-approval --descriptor <run-dir>/workspace-descriptor.json --approved-by <approved-identity> --out <run-dir>/workspace-approval.json --load-test-root <load-test-root>`

<!-- cli: workspace-apply -->
`python tools/methodology_authoring/methodology_authoring.py apply --base <load-test-root>/workspace.yaml --candidate <run-dir>/workspace.candidate.yaml --patch <run-dir>/workspace.patch --approval <run-dir>/workspace-approval.json --load-test-root <load-test-root>`

A missing, stale, or hash-mismatched approval leaves `workspace.yaml`
byte-for-byte unchanged.

### 4. Produce the confirmed workspace snapshot

Run Phase 3a snapshot against the now-confirmed manifest. Require a fresh,
independently validated workspace snapshot in `workspace-snapshot.json`; reject a
stale, malformed, or identity-mismatched snapshot before evidence collection.

### 5. Collect evidence in parallel

Dispatch the Confluence researcher and per-module inspectors in parallel. These are fresh subagents. Give each module inspector exactly one inline `inspector_jobs[]` object
and snapshot context. Give the researcher only the bounded page/search scope and
host overlay capability. Consume only compact JSON envelopes unless a blocker needs
artifact detail. No concrete Confluence MCP tool names belong in this package.

### 6. Aggregate and reconcile

Aggregate and reconcile the returned artifact paths with the deterministic Phase
3b tooling. Preserve conflicts and provenance; never select a business value from
conflicting candidates.

Write `run-state.json` with `current_step: 7`, `step_status: "awaiting_user"`,
`completed_steps: [1..6]`, and the gap state derived from `methodology-gaps.md`.

### 6.5. Coverage assessment

Before proceeding to gap approval, read `section-coverage.json` and show the user
a summary of coverage across the 17 sections. If more than half are `missing`,
**proactively offer** to:

1. Dispatch additional targeted module inspectors for specific descriptive files
   (e.g. "read `docs/architecture.md` in module X" or "scan `README.md` files").
2. Ask the user to point at additional Confluence pages or repository documents.
3. Continue with current coverage — sections without evidence will receive the
   `> Нет подтверждённых данных` placeholder in the candidate, and the quality
   gate will block any hallucinated content via `grounding-missing-section`.

This step never blocks the flow; it gives the engineer a choice before committing
to a sparse authoring pass.

### 7. Gap approval (iterative)

Read `methodology-gaps.md` and ask only questions for blocking gaps. Save each
answer as UTF-8 `manual-confirmations.json`. This **gap approval** records factual
confirmation; it is neither the workspace-manifest approval nor a patch approval.

This step is **iterative**. The engineer may answer some gaps now and defer
others (they often require meetings, cross-team confirmations, or Confluence
lookups). After each answer:

1. Update `manual-confirmations.json` with the new answer.
2. Update `run-state.json`: set `current_step: 7`, `step_status: "awaiting_user"`,
   and refresh `gap_state.answered` / `gap_state.pending`.
3. Tell the user how many gaps remain and offer two paths:
   - **Continue answering** now (stay in step 7).
   - **Export the questionnaire** — write `questions.md` to the run directory
     with all pending gaps as numbered questions, each with context and a blank
     answer field. The engineer can fill it offline and return with
     `answers.json` (or answer in chat on resume).

On resume (step 0), if `current_step == 7` and gaps remain pending, show the
pending gaps and continue the loop. Only proceed to step 8 when all blocking
gaps are answered.

### 8. Bounded candidate authoring

Dispatch a fresh `mnt-author` with exactly **six artifact paths**: the template,
current methodology, `resolved-evidence.json`, `manual-confirmations.json`,
`section-coverage.json`, and `workspace-snapshot.json` (the independently validated workspace snapshot). The
author receives no raw source or Confluence context and may write only run-directory
candidate artifacts. Read its envelope, not raw reasoning.

### 9. Prepare the exact methodology patch and descriptor

Immediately after the author returns its candidate artifacts, prepare the exact
canonical MNT patch and descriptor once. The descriptor carries the approved kind
used by later record and apply commands.

Update `run-state.json` with `current_step: 10` and `completed_steps: [1..9]`.

<!-- cli: methodology-prepare -->
`python tools/methodology_authoring/methodology_authoring.py prepare --kind methodology-patch --base <load-test-root>/methodology.md --candidate <run-dir>/methodology.candidate.md --patch <run-dir>/methodology.patch --out <run-dir>/methodology-descriptor.json --load-test-root <load-test-root>`

The same unchanged patch and descriptor are the required inputs for the quality
gate, validator, review, approval, and apply. Do not regenerate them later.

### 10. Deterministic quality gate

Run the methodology **quality gate** over the candidate, resolved evidence,
coverage, source map, current base, workspace snapshot, and the same unchanged
patch and descriptor produced after authoring. A blocked report stops the workflow
and prevents a patch-approval request.

### 11. Independent validation

Dispatch fresh `mnt-validator` with the candidate, deterministic reports, gaps,
source map, resolved evidence, snapshot, and the same unchanged patch descriptor.
Stop immediately on `blocked`; do not reinterpret it as a warning.

### 12. Review the exact MNT change

Show `change-summary.md`, quality warnings, and **show exact MNT diff** from the
same unchanged prepared methodology patch. State the candidate hash and approval
identity still required.

### 13. Second explicit methodology approval

Wait for explicit methodology-patch approval for this exact patch. This second
explicit approval is distinct from the earlier `workspace-manifest` approval.
Explicit approval is mandatory; do not reuse an approval or accept an implicit
acknowledgement.

### 14. Record and apply only the approved patch

After explicit approval, record the descriptor's kind and apply the unchanged
approved candidate:

<!-- cli: methodology-record -->
`python tools/methodology_authoring/methodology_authoring.py record-approval --descriptor <run-dir>/methodology-descriptor.json --approved-by <approved-identity> --out <run-dir>/methodology-approval.json --load-test-root <load-test-root>`

<!-- cli: methodology-apply -->
`python tools/methodology_authoring/methodology_authoring.py apply --base <load-test-root>/methodology.md --candidate <run-dir>/methodology.candidate.md --patch <run-dir>/methodology.patch --approval <run-dir>/methodology-approval.json --load-test-root <load-test-root>`

The compare-and-swap validation must bind the exact base, candidate, and patch.
Apply writes only within the load-test repository.

### 15. Post-apply quality gate

Run the **post-apply quality gate** on canonical `methodology.md` using the same
approved inputs. Report the resulting report path and stop if it is non-green.

### 16. Close the local run

Mark `run-state.json` with `current_step: 16`, `step_status: "completed"`, and
`completed_steps: [1..16]`.


For create and update-local, state that **Confluence remains unchanged** in Phase
3c. This workflow performs no Confluence write, comment, move, or publish operation.

## Publish

Use `publish` only after a completed local run. It is a separate user action from
both local approvals and never changes the target page selected by the confirmed
snapshot.

### 1. Require a green canonical MNT

Require that canonical methodology is green under the post-apply quality gate.
Stop when the canonical methodology is non-green or the report is unavailable.

### 2. Bind publication to the fixed target

Use the confirmed page snapshot from the completed collection. Never search for,
select, or substitute another page ID.

### 3. Prepare the exact publication diff

Prepare publish with the existing guard and the final local `methodology.md`:

`python tools/methodology_publish/methodology_publish.py prepare --methodology <load-test-root>/methodology.md --page-snapshot <run-dir>/confluence-snapshot.json --out-dir <run-dir>`

Show confluence.patch from that run directory before requesting publication
approval.

### 4. Obtain the separate explicit publication approval

Wait for explicit publish approval for the exact prepared descriptor. It is not
the workspace-manifest or methodology-patch approval.

### 5. Record the approval

Record publish approval for that descriptor only:

`python tools/methodology_publish/methodology_publish.py approve --descriptor <run-dir>/publish-descriptor.json --approved-by <approved-identity> --out <run-dir>/publish-approval.json`

Do not dispatch mnt-confluence-publisher without recorded publish approval. Stop
before dispatching mnt-confluence-publisher if the canonical MNT is not green, the
confirmed snapshot is unavailable, or the approval is missing.

### 6. Dispatch the bounded publisher

Dispatch mnt-confluence-publisher with paths to the final local methodology, the
confirmed page snapshot, and `publish-approval.json`. Display the publisher's
inline result. The host overlay supplies page-read and page-update capabilities;
if either is unavailable, the publisher returns `blocked` without an update.

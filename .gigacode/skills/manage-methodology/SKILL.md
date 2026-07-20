---
name: manage-methodology
description: Create or update a system MNT through bounded workspace discovery, reconciled evidence, deterministic review, exact local diffs, and two explicit approvals.
---

# Manage Methodology

Use this skill for `create`, `update-local`, and `publish` methodology runs.
`create` and `update-local` perform a full recollection of every confirmed
repository and Confluence source; never request or invoke a selective refresh.
Only `publish` may request a Confluence update through the separate publisher
role. This package never names concrete Confluence MCP tools: a host overlay
supplies verified capabilities, or the relevant role returns `blocked`.

## Non-negotiable boundaries

- The load-test repository is the only writable location. SUT modules, raw source
  inputs, canonical MNT text before approval, and Confluence are read-only.
- Use fresh subagents for every run, with narrow prompts. Read only compact JSON
  envelopes from them unless a blocker requires artifact detail.
- Treat a `blocked` result from any required stage as a stop. Do not request an
  approval, prepare a substitute, apply a patch, or publish after that stop.
- `workspace-manifest` and `methodology-patch` are separate approval kinds.
  Their approvals bind the exact base, candidate, and patch SHA-256 values.

## Ordered workflow

### 1. Workspace preview approval

Run the Phase 3a preview from the bootstrap manifest. Show the discovery preview
and ask the user to confirm only the modules to include. This is the **workspace
preview approval**; it selects candidates but is not permission to change the
manifest.

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

### 7. Gap approval

Read `methodology-gaps.md` and ask only questions for blocking gaps. Save each
answer as UTF-8 `manual-confirmations.json`. This **gap approval** records factual
confirmation; it is neither the workspace-manifest approval nor a patch approval.

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

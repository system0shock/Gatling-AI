---
name: manage-methodology
description: Create or update a system MNT through bounded workspace discovery, reconciled evidence, deterministic review, exact local diffs, and two explicit approvals.
---

# Manage Methodology

Use this skill for `create` and `update-local` methodology runs. It performs only
local load-test-repository changes. It never publishes to Confluence and never
names concrete Confluence MCP tools: a host overlay supplies verified read/search
capabilities, or the researcher returns `blocked`.

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

Create `workspace.candidate.yaml` from the user-confirmed modules. Run:

`python tools/methodology_authoring/methodology_authoring.py prepare --kind workspace-manifest --base workspace.yaml --candidate workspace.candidate.yaml --patch <run-dir>/workspace.patch`

Do not edit `workspace.yaml` directly.

### 3. Show exact workspace diff and obtain the first explicit approval

**Show exact workspace diff** from the prepared patch. Wait for explicit
workspace-manifest approval after showing the exact diff and capture the approved
identity. Do not infer approval from the preview or from an earlier run.

Only after that reply, run `record-approval --kind workspace-manifest`, then run
`apply --kind workspace-manifest` with that approval. A missing, stale, or
hash-mismatched approval leaves `workspace.yaml` byte-for-byte unchanged.

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

### 9. Deterministic quality gate

Run the methodology **quality gate** over the candidate, resolved evidence,
coverage, source map, exact patch, current base, and workspace snapshot. A blocked
report stops the workflow and prevents a patch-approval request.

### 10. Independent validation

Dispatch fresh `mnt-validator` with the candidate, deterministic reports, gaps,
source map, patch descriptor, resolved evidence, and snapshot. Stop immediately on
`blocked`; do not reinterpret it as a warning.

### 11. Review the exact MNT change

Show `change-summary.md`, quality warnings, and **show exact MNT diff** from the
prepared methodology patch. State the candidate hash and approval identity still
required.

### 12. Second explicit methodology approval

Wait for explicit methodology-patch approval for this exact patch. This second
explicit approval is distinct from the earlier `workspace-manifest` approval.
Explicit approval is mandatory; do not reuse an approval or accept an implicit
acknowledgement.

### 13. Record and apply only the approved patch

After explicit approval, run `record-approval --kind methodology-patch` with the
approved identity, then run `apply --kind methodology-patch`. The compare-and-swap
validation must bind the exact base, candidate, and patch. Apply writes only within
the load-test repository.

### 14. Post-apply quality gate

Run the **post-apply quality gate** on canonical `methodology.md` using the same
approved inputs. Report the resulting report path and stop if it is non-green.

### 15. Close the local run

State that **Confluence remains unchanged** in Phase 3c. This workflow performs no
Confluence write, comment, move, or publish operation.

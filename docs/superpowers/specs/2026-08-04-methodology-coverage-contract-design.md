# Design: Mandatory-coverage contract with registry review acts

Date: 2026-08-04
Status: approved (brainstorming)
Trigger: RUN-001 (create, system MD) blocked at step 10 — deterministic quality gate returned `blocked` (EXIT=2), 9 blocking findings; see `DEBUG/block-report.md`.

## 1. Problem

Three independent contradictions between the documented workflow and the
deterministic tooling make the documented "sparse coverage" path impossible:

1. **SKILL.md step 6.5 vs `module-coverage`.** The skill promises "Continue with
   current coverage… this step never blocks the flow" with
   `grounding-missing-section` as the hallucination guard. The gate blocks ANY
   `missing`/`partial` section (`methodology_quality_gate.py:215-216`,
   `finding()` defaults to `severity="blocking"`).
2. **`source-map-schema` is unsatisfiable for missing sections.** All 17
   canonical sections must map to non-empty lists of known evidence IDs
   (`_is_id_list` requires `bool(value)`). A section with zero evidence can
   never comply.
3. **`*-source` checks are unsatisfiable for missing sections.**
   `check_section_sources` treats any body != exact `NO_DATA` as a claim; the
   documented placeholder `> Нет подтверждённых данных…` is not equal to
   `NO_DATA`, so a missing SLA section is blocked even when perfectly grounded.

Additionally the gap/questionnaire mechanism never fires for coverage holes:
`reconcile_documents` emits `blocking_gaps` only for `evidence-conflict`,
`sla-normative-source`, and `production-workload`. Missing/partial coverage
produces no gaps, so step 7 (gap approval, offline questionnaire export)
passes trivially and the flow walks into the gate with an unpassable candidate.

Authoring-side defects observed in the RUN-001 candidate: STUB/placeholder
config values cited as integration facts, `TBD` markers quoted from sources,
empty table skeletons copied from the template into dataless sections,
`<!-- evidence: ... -->` template comments left in the candidate body,
per-section `> Частичное покрытие…` meta-commentary repeated in the document
body, raw pipe-quoted dumps instead of synthesis, and content placed under
semantically wrong headings. The mnt-author prompt itself contains the same
contradiction (missing sections must contain ONLY the placeholder, yet the
source map must list non-empty IDs for all 17 sections), and the template
ships the empty table skeletons.

## 2. Decision: hybrid coverage contract

Five mandatory sections must reach `covered` before the gate passes; the
remaining twelve may stay sparse (placeholder + `grounding-missing-section`
guard, gate severity `warning`).

| Section | Entity types | Closure mode |
|---|---|---|
| Модель нагрузки | `workload` | **review** (list act) |
| SLA, SLO и критерии приемки | `sla`, `slo` | **strict** (per-fact confirmation) |
| Реестр тестируемых интерфейсов | `endpoint` | **review** |
| Пользовательские и технические потоки | `flow` | **strict** |
| Реестр интеграций | `integration` | **review** |

Rationale: registries/workload are machine-extracted lists where the human
judgment is "is the composition right" (review: approve/exclude/add); flows
and SLA are individual commitments that must be confirmed per fact. SLA keeps
the existing `sla-normative-source` rule (manual confirmation on `threshold`).

## 3. New artifact: `section-reviews.json`

Written by the orchestrator from questionnaire answers; validated against a
new JSON schema in `schemas/`. Version 1:

```json
{
  "version": 1,
  "reviews": {
    "Реестр тестируемых интерфейсов": {
      "reviewed_by": "<identity>",
      "approved": ["endpoint.kildin-gadus./v2/work-units/{id}"],
      "excluded": ["endpoint.legacy./v1/old"],
      "added": [
        {"entity_type": "endpoint", "entity_id": "kildin-gadus./v2/new",
         "fields": {"identifier": "…", "type": "REST", "operation": "GET …"}}
      ]
    }
  }
}
```

- Keys: canonical headings of the three review sections only; a review
  targeting any other section is a schema-validation error on load.
- IDs: composite `entity_type.entity_id`.
- `reviewed_by` is required (named, auditable act).
- Editing a reviewed entity is expressed as `excluded` (original) plus an
  `added` replacement entity; there is no separate "edit" verb.
- Reviews are per-run; reuse across runs is future work.

## 4. Reconcile changes (`tools/methodology_evidence/reconcile.py`)

**Merge.** Section reviews become the fourth evidence source (after
repository, confluence, confirmations):

- `approved` → entity status `confirmed` (the reviewer approved the row as
  extracted, all fields).
- `excluded` → entity status `not_applicable` (the status exists in the enum
  but is currently produced by nothing). Excluded entities are skipped in
  coverage computation and produce no gaps.
- `added` → new entities with status `confirmed`, provenance `section-review`.
- Reference to a non-existent entity → blocking gap `review-stale-reference`
  (reviews bind to the entity set; changed evidence requires re-review).
- An entity in `conflict` cannot be approved — conflict wins,
  `evidence-conflict` gap persists.

**New gap rules** (in addition to `evidence-conflict`, `sla-normative-source`;
`production-workload` is subsumed and removed):

- `mandatory-section-missing` — a mandatory section has no non-excluded
  entities.
- `mandatory-entity-unconfirmed` — a strict-section entity is not `confirmed`
  (one gap per entity).
- `registry-review-required` — a review section has unreviewed entities (ONE
  gap per section; review is a list act, not 66 questions).

A missing strict section (e.g. SLA with zero entities) is closed via
manual-confirmations creating entities; a missing review section may be closed
by a review with `added` entities. Unreviewed, unexcluded entities keep their
status and leave the section `partial`.

## 5. Gate changes (`tools/methodology_quality_gate/methodology_quality_gate.py`)

Single source of truth: `MANDATORY_MNT_SECTIONS` (5 headings + `strict|review`
mode) defined next to `REQUIRED_MNT_SECTIONS` in `reconcile.py`, imported by
the gate.

| Rule | Now | After |
|---|---|---|
| `module-coverage` | blocking for any `missing`/`partial` | mandatory: not `covered` → blocking; optional: `missing`/`partial` → warning |
| `source-map-schema` | non-empty IDs for all 17 sections | empty list allowed iff the section is optional AND coverage = `missing`; mandatory sections always non-empty |
| `sla-source` / `endpoint-source` / `integration-source` | blocking when body has claims without IDs | additionally skipped when the section's coverage is `missing` |
| `grounding-missing-section` | blocking content in missing sections | unchanged (primary guard for optional sections) |
| `placeholder-scan`, `secret-detection`, others | — | unchanged |

Canonical missing-section body is exactly `Нет подтвержденных данных.`
(`NO_DATA`) — no quote form, no comments, no table skeletons. The gate keeps
accepting both placeholder prefixes (backwards compatibility); authoring
standardizes on `NO_DATA`.

## 6. Workflow changes (`.gigacode/skills/manage-methodology/SKILL.md`)

**Step 6.5** rewritten: remove "never blocks the flow" / "Continue with
current coverage". New semantics: check coverage against the mandatory bar;
if mandatory sections lack evidence, proactively offer additional collection
(module inspectors, Confluence pages) BEFORE the questionnaire. Honest
promise: mandatory sections must reach `covered` by step 10; the step-7
questionnaire is the mechanism.

**Step 7** produces two item types derived from the new gap rules:

- **Strict questions** (`mandatory-entity-unconfirmed`,
  `sla-normative-source`, `evidence-conflict`): per-fact, answered into
  `manual-confirmations.json` (unchanged channel).
- **Review lists** (`registry-review-required`, `mandatory-section-missing`
  for review sections): the full entity list from resolved evidence, marked
  approve/exclude/add (an edit is exclude + add); the orchestrator
  deterministically expands answers into `section-reviews.json`
  (schema-validated on reconcile load).

The exported `questions.md` includes both types; offline return is
`answers.json` plus review markup.

**Step 8**: author inputs unchanged (reviews are already reflected in
resolved-evidence statuses).

## 7. Authoring changes

**`methodology-template.md`:**

- Remove empty table skeletons from section bodies (they migrate into
  candidates). Table column sets move into the author prompt as "use these
  columns when data exists".
- `<!-- evidence: ... -->` comments are template-internal; forbidden in the
  candidate.

**`.gigacode/agents/mnt-author.md`:**

- Resolve the internal contradiction: empty source-map lists are legal for
  missing sections; missing-section body is exactly `NO_DATA`, nothing else.
- Garbage filtering: never cite STUB/placeholder config values (`STUB_*`,
  placeholder hosts) as facts — a stub statement is dropped and noted as a
  limitation; never carry `TBD`/`TODO` markers from source quotes.
- Synthesis over dumps: group facts, use tables for registries, no raw
  pipe-quoted bullets.
- Section discipline: content must match the heading semantics (teams/mailing
  lists do not belong in "Архитектура"; historical run pages are not "Виды
  тестов").
- Meta-commentary `> Частичное покрытие…` moves from the candidate body into
  `change-summary.md` (reviewed at step 12). Gaps remain tracked in
  `methodology-gaps.md` and coverage JSON.

## 8. Acceptance: RUN-001 resume

1. Resume at step 6 on existing evidence: reconcile now emits gaps for the 5
   mandatory sections.
2. Step 7 generates the questionnaire: 3 review lists (endpoints,
   integrations, workload) + strict questions (flows, SLA normative source).
3. Answers → `manual-confirmations.json` + `section-reviews.json` →
   reconcile → mandatory sections `covered` (or consciously `excluded`).
4. Authoring → gate: `passed` / `passed_with_warnings` (warnings only for the
   12 optional sections) → steps 11–16 proceed.

## 9. Testing

- **reconcile**: review merge (approve/exclude/add), `not_applicable` skipped
  in coverage, stale refs → gap, conflict > approve, new gap rules,
  `production-workload` removal.
- **gate**: mandatory/optional split in `module-coverage`, empty IDs allowed
  for optional-missing in `source-map-schema`, `*-source` skip on missing,
  regression of remaining rules (update `_mark_coverage_partial` test).
- **e2e fixture "RUN-001"**: evidence with 5 missing + 12 partial → without
  reviews the gate is `blocked` listing the new gaps; with
  reviews/confirmations → `passed_with_warnings`.
- **package**: `test_gigacode_package.py` covers template/prompt edits.

## 10. Non-goals and risks

- No changes to publish flow, module inspectors, or `questions.md` format
  beyond what is required.
- Reviews are per-run; reuse between `update-local` runs is future work.
- Risk: rubber-stamp reviews — mitigated by named `reviewed_by` and binding
  to the entity set (stale references surface as gaps).

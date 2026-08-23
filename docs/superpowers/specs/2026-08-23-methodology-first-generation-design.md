# Methodology-first generation with bounded multi-repo discovery

**Date:** 2026-08-23

**Status:** Approved

**Scope:** Local creation and update of a system load-testing methodology (MNT)

## 1. Problem

The current methodology workflow is evidence-first: it collects repository and
documentation facts and then attempts to prove enough material for all 17 MNT
sections. A real run demonstrated the failure mode: five missing sections,
twelve partial sections, and roughly 110 repository/documentation entities that
would require manual confirmation before the quality gate could pass. The
workflow spends most of its effort reconstructing the product rather than
describing how it will be load-tested.

The new workflow reverses the dependency:

1. Start from a stable, versioned load-testing method.
2. Discover only the system surface needed to apply that method.
3. Ask the engineer only for values that cannot be obtained safely from the
   selected sources or defaults.
4. Render and validate the methodology deterministically.

The repository is not a source from which the workflow must reconstruct a full
business or architectural description. It is a bounded source of candidate
components, interfaces, integrations, and explicitly documented flows.

## 2. Goals

- Produce a useful methodology without full-codebase analysis.
- Keep a fixed default test set and default SLA/SLO guardrails.
- Let the engineer accept the complete proposed profile or change individual
  values.
- Support systems composed of arbitrary, heterogeneous repositories.
- Discover and confirm the test surface as one grouped review act rather than
  one question per endpoint or evidence field.
- Keep all 17 canonical MNT sections and report their structural completeness.
- Distinguish readiness to execute tests from completeness of the document.
- Let methodology owners add ordinary questions without changing orchestration
  code.
- Preserve manual Markdown edits as a controlled fallback.
- Retain exact diffs, explicit approval, safe apply, and resumable runs.
- Make identical confirmed inputs produce identical candidates and reports.

## 3. Non-goals

- Reconstructing the complete product architecture or business domain from code.
- Automatically building a code/property graph in the MVP.
- Automatically connecting to the internal META service in the MVP.
- Treating filenames, endpoint names, or package names as proof of a business
  process.
- Proving every repository fact through a second independent source.
- Asking the user to confirm every endpoint field separately.
- Using an agent to perform final template or readiness validation.
- Removing the existing legacy evidence tooling in the same change.

## 4. Core decision and data flow

The selected approach is **methodology-first with bounded discovery**:

```text
confirmed multi-repo workspace
             |
             v
      bounded discovery
             |
             v
   surface-candidate.json
             |
       grouped review
             v
    surface-review.json
             |
             +-----------> default-v1
             |                 |
             |          user checks META
             |                 |
             +------ profile review/overrides
                               |
                               v
                     methodology-input.yaml
                               |
                    missing required questions
                               |
                               v
                    deterministic renderer
                               |
                               v
                  methodology.candidate.md
                               |
              readiness + template conformance
                               |
                         exact diff
                               |
                       explicit approval
                               |
                               v
                       methodology.md
```

The workflow has six independently testable responsibilities:

1. Workspace snapshotting.
2. Source location and extraction.
3. Surface merging and user review.
4. Profile resolution and bounded questioning.
5. Deterministic Markdown rendering.
6. Deterministic conformance, diff, approval, and apply.

## 5. Multi-repo system workspace

The unit of work is a system workspace, not a single repository. The existing
workspace preview, explicit selection, revision snapshot, and dirty-repository
policy remain useful and should be retained.

The manifest supports an arbitrary number of repositories:

```yaml
system: document-manager
repositories:
  - id: core-platform
    path: ../core-platform
    roles: [backend, contracts, shared-library]
    required: true

  - id: business-docs
    path: ../business-docs
    roles: [documentation, custom-domain]
    required: false
```

Rules:

- `id` is stable within the system workspace.
- `path` is resolved and checked using the existing workspace boundary rules.
- `roles` is an optional, open list of strings. It is not an enum.
- A repository may have zero, one, or many roles.
- Roles prioritize discovery but never authorize, prohibit, or prove a finding.
- Extractors select inputs using actual content/file signatures.
- `required` controls the consequence of an unavailable repository and defaults
  to `true` when omitted.
- Existing per-repository `inspect` and `exclude` settings remain available as
  explicit discovery hints and always override role-based prioritization.
- Every repository snapshot records commit/revision, branch, remote, dirty state,
  and the selected dirty policy.
- A change to workspace membership requires explicit workspace confirmation.

Discovery artifacts are cached per repository by:

```text
repo_id + revision/working-tree snapshot + extractor_id + extractor_version
```

An unchanged clean repository is not rescanned. If one repository changes, only
its discovery results are invalidated; the system surface is then re-merged from
the changed result and valid cached results. A dirty repository confirmed with
the `HEAD` policy uses the clean commit cache key. A dirty repository confirmed
with the `working-tree` policy may reuse artifacts only inside the same run and
is rescanned on a new run; this avoids treating an incomplete dirty-state
fingerprint as a stable cross-run identity.

## 6. Bounded discovery

Discovery is layered. Later layers are not entered automatically when earlier
layers provide a reviewable surface.

### 6.1. Layers

1. **Contracts:** OpenAPI/Swagger, AsyncAPI, and GraphQL SDL.
2. **High-signal documentation:** README, architecture documents, ADRs, and
   documents explicitly describing flows or endpoints.
3. **Configuration:** Maven/Gradle metadata, OpenShift/Kubernetes manifests,
   deployment files, Kafka configuration, and similar structured inputs.
4. **Bounded source scan:** files containing known framework markers such as
   Spring request mappings, Kafka listeners, or GraphQL resolvers. This layer
   requires an explicit user choice when the first three layers are insufficient.
5. **Existing graph artifacts:** consumed through an adapter if already present.
   The workflow does not generate a new graph in the MVP.

Structured formats use deterministic parsers. Unstructured documentation may be
read by a bounded agent extractor, but only after a deterministic locator has
selected the high-signal files. The extractor receives only those files and may
return only the requested fact types with precise source references. It never
reads the rest of the codebase.

### 6.2. Selection budget

The MVP uses deterministic default limits to prevent accidental deep analysis:

- index filenames while excluding `.git`, build outputs, dependency/vendor
  directories, generated sources, reports, and configured exclusions;
- parse matching structured contracts up to 5 MiB per file;
- read at most 20 high-signal text documents per repository, sorted by source
  priority and normalized path, up to 1 MiB per file;
- retain at most 500 bounded source-marker candidates per repository before
  grouping and reporting overflow;
- never follow symlinks outside the confirmed repository root.

Limits are configuration values, but changing them is an explicit run option and
is recorded in the discovery artifact. Reaching a limit produces a visible
warning and choices to continue, identify a source, or explicitly deepen the
scan. It never silently expands the budget.

### 6.3. Extractor contract

Each extractor returns normalized candidates and diagnostics. It must not edit a
source repository or methodology:

```yaml
extractor_id: openapi
extractor_version: 1
repo_id: core-platform
revision: <snapshot identity>
candidates:
  - entity_type: interface
    canonical_key: http:documents:POST:/documents
    attributes:
      protocol: HTTP
      operation: POST /documents
    source_ref: api/openapi.yaml#/paths/~1documents/post
    confidence: confirmed
warnings: []
```

Supported entity types in the MVP are `component`, `interface`, `integration`,
and `flow`. A flow is emitted only when a source describes it explicitly; it is
not inferred from names or a call chain.

### 6.4. Graph tools

Graph construction is an optional future provider, not the main path. Existing
Graphify/Code Graph artifacts may be adapted to the extractor contract. For Java,
jQAssistant is a possible later adapter because it scans Java artifacts into an
embedded Neo4j graph and supports Cypher queries. It is deliberately excluded
from the MVP default path because it introduces build/bytecode and graph-store
costs that are unnecessary when contracts and documentation are available.

## 7. Surface merge and review

Candidates from all repositories are merged before asking the user anything.
Every value retains `repo_id`, revision, source reference, extractor, and
confidence.

Stable keys are protocol-aware and include the owning component when known. For
example, an HTTP interface key includes service identity, method, and normalized
path. Matching OpenAPI and backend candidates become one entity with multiple
sources. Cross-repository candidates are auto-merged only when service identity
is explicit in a contract, manifest hint, or extracted metadata. When it is not,
the workflow shows a possible-duplicate group for one user decision rather than
risk merging identical paths from different services. Competing values are
retained as one visible conflict, not duplicated questions.

The user sees a compact list grouped first by component/service and then by
protocol or contract tag. The review supports three actions:

- accept candidates;
- exclude candidates;
- add a missing component, interface, integration, or explicit flow.

The result is `surface-review.json`. Only included and user-added entities enter
the methodology. Exclusion is an explicit scope decision, not a claim that an
endpoint does not exist.

Typical interaction:

```text
Found four candidates:

1. POST /documents — OpenAPI, backend
2. GET /documents/{id} — OpenAPI, backend
3. Kafka document.created — AsyncAPI
4. GET /actuator/health — backend

Reply with "accept all", "exclude 4", or "add: GraphQL createDocument".
```

Large lists are reviewed by group. The user expands a group only when needed.

## 8. Versioned default profile

The profile contract contains `profile_id` and `profile_version`. The MVP ships
one profile, `default-v1`; the data shape already permits later profiles selected
by system class.

### 8.1. Default SLA/SLO and resource guardrails

If the user does not provide a contract value, `default-v1` proposes:

- response time: `p95 <= 1 second`;
- technical error share: `<= 5%`, excluding expected business rejections and
  explicitly negative scenarios;
- application CPU on one OpenShift arm: `<= 40%`;
- memory utilization: `<= 80%` and no sustained growth.

The concrete metric name, aggregation, observation source, and definition of a
sustained memory-growth signal are execution-critical inputs. Discovery may
suggest them; otherwise the questionnaire asks for them. The profile does not
invent monitoring semantics.

The highest passed load is the last complete search step for which all selected
SLA/SLO, error, and resource criteria pass.

### 8.2. Default tests

1. **Stepwise maximum search**
   - Each step lasts 20 minutes.
   - Load increases by a user-confirmed equal increment.
   - The run stops when an accepted stop criterion is violated.
   - The result is the last fully completed passing step.

2. **Maximum confirmation**
   - Load is the maximum found by the search.
   - Duration is 2 hours.
   - All accepted criteria must pass for the complete interval.

3. **Stability test**
   - Load is `0.8 * confirmed maximum`.
   - Duration is 8 hours.
   - The test additionally checks for memory growth and response degradation.

The engineer must supply or confirm the values that cannot be derived safely:

- load unit (for example RPS, users/s, or messages/s);
- initial load;
- step increment;
- operation/flow mix;
- monitoring signals and dashboards;
- expected business rejections excluded from technical errors;
- environment and test-data readiness.

The profile review is one act: accept the complete proposal or change individual
fields.

## 9. META boundary

META is an internal web service and has no integration in the MVP. The workflow
must not claim that META was searched or that no contract exists. It shows this
prompt instead:

```text
Check the SLA/SLO values in the META contract. You may keep default-v1 or enter
the contract value and its link/ID.
```

An entered value stores both the value and its declared source reference. Current
resolution is:

```text
default-v1 base -> manually supplied META contract value -> explicit user change
```

Equivalently, the final precedence is user override over META over the default.
The future `meta-provider` will implement the same field-level source contract and
pre-fill values before profile review. Whether that provider uses MCP or another
API does not affect the questionnaire, renderer, or profile schema.

## 10. Minimal extensible questionnaire

The questionnaire is intentionally not a general forms framework. The MVP has:

- one version-controlled `questions.yaml` catalog;
- one run-scoped `answers.yaml` file;
- two built-in review steps for the system surface and test/SLA profile;
- generic scalar questions only for unresolved inputs.

An ordinary question has this minimal shape:

```yaml
questions:
  - id: environment.name
    section: Тестовый стенд
    prompt: На каком стенде будут проводиться испытания?
    target: environment.name
    type: text
    required: true
    applies_to: []
```

Supported scalar types are `text`, `number`, `boolean`, and `choice`.
`applies_to` is an optional list of simple protocol/capability labels; an empty
list means the question is universal. There is no arbitrary condition DSL,
question revision framework, or pack system.

Rules:

- `id` is stable and unique.
- Questions are grouped by `section` and shown in small thematic blocks.
- A question is asked only when its target has no resolved value.
- Existing answers are reused by stable ID on resume.
- Adding a question for an existing target requires only a catalog entry.
- Introducing a new target requires an intentional change to the input schema,
  catalog, and output template.
- Type and cross-field validation belong to the methodology input schema, not to
  a second questionnaire framework.
- The user can correct an answer in chat by ID or edit `answers.yaml`; validation
  and rendering then rerun without discovery.

Typical missing-input interaction:

```text
Two values are still required:

1. On which environment will the tests run?
2. Where should CPU and memory be observed?

You may answer both in one message.
```

## 11. Deterministic document with manual fallback

All 17 canonical headings in the existing methodology template remain. Their
content is assembled from:

- the fixed profile and procedural method;
- confirmed discovery and questionnaire data;
- preserved manual additions.

`methodology-input.yaml` is the source of truth for generated values, but
`methodology.md` remains manually editable. Each canonical section supports a
managed and manual block:

```markdown
## Виды тестов

<!-- mnt:generated:start id=test-types -->
...deterministically rendered content...
<!-- mnt:generated:end -->

<!-- mnt:manual:start id=test-types -->
...user-maintained additions...
<!-- mnt:manual:end -->
```

Rules:

- The renderer replaces only generated blocks.
- Manual blocks and text outside managed blocks are preserved byte-for-byte.
- The last generated block hashes are stored in a generation-state artifact.
- A manual change inside a generated block creates a `managed-block-drift`
  conflict. The workflow offers keep, replace, or move to the manual block and
  never silently overwrites it.
- The exact final diff is shown before approval.
- On first migration of an existing 17-section document, current section bodies
  are preserved in manual blocks and generated blocks are added alongside them.
  Heading-based migration is deterministic and requires approval through the
  normal diff.

Manual prose may make a template section structurally non-empty, but it does not
automatically satisfy execution-critical structured inputs. Readiness is derived
from the validated input model.

## 12. Two output-control results

Final control is deterministic and invokes no agent.

### 12.1. `ready_for_test`

This is the blocking execution-readiness result. It requires:

- confirmed system surface;
- accepted test profile;
- load unit, initial load, step increment, and operation/flow mix;
- target environment;
- monitoring signals required by the selected criteria;
- test-data readiness;
- all selected SLA/SLO and stop-criterion definitions.

A candidate and report may be generated when readiness is false, but the
canonical methodology is not updated and publication is not offered.

### 12.2. `template_complete`

This is a non-blocking structural conformance result for all 17 headings. Each
section is `complete`, `partial`, `missing`, or `not_applicable`. The check uses a
declarative `methodology-template-contract.yaml` containing section IDs,
expected constructs/fields, whether `not_applicable` is legal, and related
question IDs.

The check verifies heading presence, non-placeholder content, required generated
constructs, and non-empty data rows where a canonical table is expected. It does
not judge the truth of free-form manual prose.

An incomplete non-critical section produces a warning and may still be applied.
`not_applicable` is accepted only as an explicit user decision with a reason; it
is never inferred from absent discovery evidence. The report links each detected
gap to an existing question when one is available. The user can answer it and
rerender without rescanning repositories.

Example summary:

```text
Readiness: READY
Template completeness: 14/17

Partial:
- Architecture: component relationships are absent
- Observability: memory dashboard is absent

Missing:
- Methodology update owner
```

## 13. End-to-end run

1. Detect an unfinished run and offer resume or restart.
2. Preview and confirm workspace membership when it changed.
3. Prepare, show, approve, and apply an exact workspace-manifest diff when
   required.
4. Snapshot every confirmed repository.
5. Reuse valid per-repository discovery cache entries and scan only invalidated
   repositories.
6. Merge candidates across the complete workspace.
7. Review the system surface as grouped lists.
8. Show `default-v1`, the META reminder, sources for proposed values, and the
   accept-or-edit profile action.
9. Ask unresolved required questions in small thematic blocks.
10. Render `methodology.candidate.md` deterministically.
11. Produce readiness and template-conformance JSON and Markdown reports.
12. Resolve managed-block drift, if any.
13. Show warnings, change summary, hashes, and the exact methodology diff.
14. Obtain explicit methodology-patch approval.
15. Apply the unchanged approved candidate with the existing hash-bound apply
    mechanism.
16. Run deterministic post-apply control and close the run.

Publication remains a separate action with its existing separate approval and
fixed-target safeguards.

## 14. Error and fallback policy

- **No contracts or architecture documents:** offer bounded source-marker scan,
  a user-supplied document, or manual surface entry.
- **One parser fails:** retain diagnostics, exclude that parser result, and
  continue when other sources/manual entry can provide a safe surface.
- **Source conflict:** show one merged conflict with all source references and
  ask for one resolution.
- **Too many candidates:** group them, report the exceeded budget, and require an
  explicit choice before deeper inspection.
- **Missing required repository:** readiness is blocked.
- **Missing optional repository:** report a warning and continue.
- **Missing execution-critical input:** render a draft/report, but do not update
  canonical methodology.
- **Missing non-critical template content:** warn without blocking apply.
- **Bounded documentation agent fails:** fall back to the related manual question;
  do not fail the entire workflow.
- **Managed block drift:** require an explicit keep/replace/move decision.
- **Duplicate or malformed canonical headings/markers:** render a report but do
  not apply until the document structure is corrected or explicitly migrated.
- **Interrupted dialogue:** persist the step, snapshots, surface review, profile
  decision, and answers. Do not repeat discovery while snapshot identities and
  extractor versions remain valid.

## 15. Run artifacts

The load-test repository remains the only writable location. A run contains:

```text
methodology-runs/<RUN-ID>/
  run-state.json
  workspace-snapshot.json
  discovery/
    <repo-id>/
      discovery-index.json
      extractor-results/*.json
  surface-candidate.json
  surface-review.json
  resolved-profile.yaml
  answers.yaml
  methodology-input.yaml
  generation-state.json
  methodology.candidate.md
  methodology-template-report.json
  methodology-template-report.md
  methodology-readiness-report.json
  methodology-readiness-report.md
  methodology.patch
  methodology-descriptor.json
  methodology-approval.json
```

The normalized input and reports have JSON Schemas (YAML artifacts are parsed to
the same JSON data model). Artifact ordering and serialization are deterministic.

## 16. Integration with the current Gatling-AI workflow

Reuse:

- workspace preview, manifest approval, snapshots, and dirty policies;
- run-state/resume mechanics;
- exact candidate/patch descriptor and hash-bound approval/apply;
- separate guarded publication flow;
- the canonical 17-section template headings.

Replace on the default methodology path:

- exhaustive per-module evidence collection;
- entity-by-entity business confirmation;
- reconciliation whose goal is full evidence coverage of all 17 sections;
- free-form author agent generation;
- agent-based final validation.

The existing evidence collectors, reconciler, author, and related schemas remain
in place during the first implementation but are not invoked by the new default
path. Their deprecation or removal is a separate decision after the new workflow
passes acceptance tests.

## 17. Verification strategy

### 17.1. Unit and contract tests

- workspace boundaries and open repository roles;
- source locator ordering, exclusions, and budgets;
- OpenAPI, AsyncAPI, GraphQL, deployment, and bounded Java-marker normalization;
- per-repository cache keys and invalidation;
- cross-repository stable-key merge, deduplication, and conflicts;
- `default-v1` resolution and user overrides;
- selection of only unresolved required questions;
- input-schema validation;
- deterministic rendering of all canonical sections;
- manual-block preservation and managed-block drift detection;
- readiness and structural template statuses;
- identical outputs for identical snapshots, reviews, profile, and answers.

### 17.2. Integration fixtures

- documented REST service with OpenAPI;
- Kafka service with AsyncAPI;
- GraphQL contract;
- repository with no contract or architecture document;
- conflicting contract and implementation markers;
- missing optional and required repositories;
- interrupted and resumed questionnaire;
- existing manually written methodology migration;
- absent META integration with manually entered contract reference.

### 17.3. Multi-repo end-to-end acceptance

The primary fixture represents one system split across at least four repositories:
contract, backend, infrastructure, and documentation. The test must prove:

1. All repositories receive independent snapshots and discovery results.
2. Contract and backend representations of the same endpoint merge into one
   candidate with two source references.
3. The user reviews one system-level surface.
4. `default-v1` is accepted or changed in one profile review.
5. No more than ten additional scalar questions are required for the documented
   happy-path fixture.
6. All 17 headings are rendered.
7. `ready_for_test` is green and template gaps are reported independently.
8. Exact approval and apply preserve manual blocks.
9. Repeating the run with identical revisions produces identical outputs.
10. Changing one repository revision rescans only that repository and then
    deterministically re-merges the system surface.

### 17.4. MVP usefulness criteria

- A typical documented system uses two major review acts (surface and profile)
  plus at most ten simple questions.
- Every read content file has a recorded selection reason.
- Deep source analysis and graph construction never run automatically.
- Final control never invokes an agent.
- Non-critical gaps are visible but do not block a safe methodology.
- Manual text survives every successful regeneration.

## 18. Future extensions

The following extensions fit the contracts without changing the workflow:

- additional profiles selected by system class;
- an automated META provider through MCP or another authenticated API;
- additional repository roles and extractors;
- adapters for existing Graphify/Code Graph artifacts;
- an opt-in jQAssistant Java graph provider;
- additional scalar questions and template fields;
- UI controls for grouped surface and profile review.

None is required for the MVP.

## 19. References

- Swagger Parser: <https://github.com/swagger-api/swagger-parser>
- AsyncAPI parsers: <https://www.asyncapi.com/tools/parsers>
- jQAssistant user manual: <https://jqassistant.github.io/jqassistant/current/>
- ArchUnit user guide: <https://www.archunit.org/userguide/html/000_Index.html>
- CodeQL database creation: <https://docs.github.com/en/code-security/reference/code-scanning/codeql/codeql-cli-manual/database-create>

# Bounded Multi-Repo Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Discover a reviewable load-test surface from arbitrary multi-repository systems without whole-codebase analysis, then produce one deterministic, source-linked surface review for the methodology core.

**Architecture:** Extend workspace manifests with a backward-compatible v2 repository model, read each confirmed Git snapshot through a bounded source view, run signature-selected extractors, and merge normalized candidates across repositories. Structured parsing is deterministic; selected high-signal documents are emitted as bounded jobs for the workflow agent implemented in Plan 3.

**Tech Stack:** Python 3.11+, PyYAML 6.0.3, jsonschema 4.26.0, graphql-core 3.2.11, Git CLI, unittest/pytest.

**Spec:** `docs/superpowers/specs/2026-08-23-methodology-first-generation-design.md`

## Global Constraints

- Complete `docs/superpowers/plans/2026-08-23-methodology-first-core.md` first.
- Keep workspace manifest v1 readable and preserve its `required: false` default.
- Manifest v2 uses `repositories`, open `roles`, and `required: true` by default.
- Treat roles as prioritization hints only; select extractors from file/content signatures.
- Never write to a SUT repository. All run artifacts and caches live below the load-test repository.
- Never follow a symlink outside a confirmed repository root.
- Never generate a code/property graph in the MVP.
- Run one discovery layer at a time; do not enter a later layer after an earlier
  layer produced a reviewable surface unless the user explicitly asks to deepen.
- Never enter bounded source-marker scanning unless the user explicitly enables it for the run.
- A `HEAD` snapshot must read committed Git objects, not dirty working-tree bytes.
- A `working-tree` snapshot may be reused only inside its originating run.
- Every content file read by an extractor must appear in `discovery-index.json` with a selection reason, size, and SHA-256.
- Budget exhaustion is a visible diagnostic and never triggers an automatic deeper scan.
- Keep output ordering and serialization deterministic.

---

## Planned File Structure

    requirements.txt
        Adds the pinned GraphQL SDL parser.
    .gitignore
        Excludes discovery cache, materialized document inputs, and untrusted agent candidates.
    schemas/workspace-v2.schema.json
        Open-role multi-repository workspace contract.
    schemas/methodology-extractor-result.schema.json
        Normalized component/interface/integration/flow candidates and diagnostics.
    schemas/methodology-discovery-index.schema.json
        Selected/skipped paths, budgets, source hashes, and warnings per repository.
    schemas/methodology-document-jobs.schema.json
        Bounded high-signal document extraction envelopes.
    schemas/methodology-surface-candidate.schema.json
        Merged system-level review groups, conflicts, and possible duplicates.
    schemas/methodology-surface-decisions.schema.json
        Deterministic grouped-review decisions supplied by the workflow.
    tools/workspace_discovery/models.py
        Loads v1 modules and v2 repositories into one compatibility model.
    tools/workspace_discovery/discovery.py
        Emits version-aware independent repository snapshots.
    tools/workspace_discovery/fixtures.py
        Adds v2 manifest and snapshot builders.
    tools/workspace_discovery/test_workspace_discovery.py
        Covers open roles, defaults, compatibility, and snapshot metadata.
    tools/workspace_discovery/README.md
        Documents v1/v2 behavior and migration.
    tools/methodology_discovery/__init__.py
        Package marker.
    tools/methodology_discovery/contracts.py
        Loads and validates discovery schemas and stable artifacts.
    tools/methodology_discovery/models.py
        Typed budgets, source records, candidates, diagnostics, and results.
    tools/methodology_discovery/source_views.py
        Reads committed Git trees or explicitly accepted working trees.
    tools/methodology_discovery/locator.py
        Signature classification, exclusions, ordering, and hard budgets.
    tools/methodology_discovery/openapi.py
        OpenAPI 3 and Swagger 2 interface extraction.
    tools/methodology_discovery/asyncapi.py
        AsyncAPI channel and operation extraction.
    tools/methodology_discovery/graphql_sdl.py
        GraphQL root-field extraction through graphql-core.
    tools/methodology_discovery/deployment.py
        Kubernetes/OpenShift and build/config metadata extraction.
    tools/methodology_discovery/java_markers.py
        Opt-in bounded Spring/Kafka/GraphQL Java marker extraction.
    tools/methodology_discovery/document_jobs.py
        Materializes selected snapshot bytes and emits/validates bounded document jobs/results.
    tools/methodology_discovery/merge.py
        Cross-repository stable-key merge and review grouping.
    tools/methodology_discovery/surface_review.py
        Applies accept/exclude/add/conflict decisions to a candidate.
    tools/methodology_discovery/cache.py
        Per-repository, snapshot, extractor, and version cache.
    tools/methodology_discovery/methodology_discovery.py
        `scan`, `merge`, and `review` CLI entry points.
    tools/methodology_discovery/fixtures.py
        Small contract/config/document fixtures and artifact builders.
    tools/methodology_discovery/test_*.py
        Focused contract, locator, extractor, merge, cache, and CLI tests.
    tools/methodology_discovery/README.md
        CLI, budgets, cache, and fallback behavior.

### Task 1: Add workspace manifest v2 without breaking v1

**Files:**
- Create: `schemas/workspace-v2.schema.json`
- Modify: `tools/workspace_discovery/models.py`
- Modify: `tools/workspace_discovery/discovery.py`
- Modify: `tools/workspace_discovery/fixtures.py`
- Modify: `tools/workspace_discovery/test_workspace_discovery.py`
- Modify: `tools/workspace_discovery/README.md`

**Interfaces:**
- Extends: `ModuleConfig` with `roles: tuple[str, ...]` and `service_id: str | None`
- Extends: `WorkspaceManifest` with `version: int` and `repositories` compatibility property
- Produces: `ModuleConfig.primary_role -> str`
- Produces: `snapshot_repositories(snapshot: Mapping[str, Any]) -> Mapping[str, Any]`
- Produces: `working_tree_fingerprint(repo_root: Path, commit: str, exclusions: Sequence[str]) -> str`

- [ ] **Step 1: Write failing v2 and compatibility tests**

    def test_v2_roles_are_open_and_required_defaults_true(self) -> None:
        manifest = models.parse_manifest({
            "version": 2,
            "system": "SHOP",
            "workspace_root": ".",
            "load_test_module": "load-tests",
            "repositories": [{
                "id": "orders-contracts",
                "path": "orders-contracts",
                "roles": ["contracts", "team-specific-role"],
                "service_id": "orders",
            }],
            "write_policy": {
                "allowed_modules": ["load-tests"],
                "sut_modules": "read-only",
            },
        })
        repository = manifest.repositories[0]
        self.assertEqual(repository.roles, ("contracts", "team-specific-role"))
        self.assertEqual(repository.service_id, "orders")
        self.assertTrue(repository.required)

    def test_v1_kind_maps_to_one_role_and_keeps_optional_default(self) -> None:
        manifest = models.parse_manifest(manifest_v1_document())
        repository = manifest.repositories[0]
        self.assertEqual(repository.roles, ("backend",))
        self.assertFalse(repository.required)

    def test_v2_rejects_duplicate_roles_and_duplicate_repository_ids(self) -> None:
        with self.assertRaises(ValueError):
            models.parse_manifest(v2_document_with_duplicate_roles())
        with self.assertRaisesRegex(ValueError, "repository id"):
            models.parse_manifest(v2_document_with_duplicate_ids())

    def test_v2_snapshot_records_unavailable_repositories_by_requiredness(self) -> None:
        snapshot = discovery.build_snapshot(
            self.root, v2_manifest_with_missing_required_and_optional(), {}
        )
        self.assertEqual(snapshot["status"], "blocked")
        self.assertFalse(snapshot["repositories"]["required-docs"]["available"])
        self.assertFalse(snapshot["repositories"]["optional-ui"]["available"])
        self.assertEqual(
            snapshot["repositories"]["required-docs"]["severity"], "blocking"
        )
        self.assertEqual(
            snapshot["repositories"]["optional-ui"]["severity"], "warning"
        )

- [ ] **Step 2: Run the focused tests and confirm failure**

Run:

    python tools/workspace_discovery/test_workspace_discovery.py -v

Expected: FAIL because version 2, `repositories`, and open `roles` are not accepted.

- [ ] **Step 3: Add the exact v2 schema**

`workspace-v2.schema.json` must:

- require `version: 2`, `system`, `workspace_root`, `load_test_module`, `repositories`, and `write_policy`;
- use the existing system and repository ID patterns;
- require only `id` and `path` for each repository;
- allow `roles` as a unique array of strings matching `^[a-z][a-z0-9-]{0,63}$`;
- allow optional `service_id` matching the same open identifier pattern;
- allow optional `required`, `inspect`, `exclude`, and `authoritative_for` fields;
- close every object with `additionalProperties: false`;
- retain the exact read-only write-policy contract.

- [ ] **Step 4: Implement version dispatch and compatibility properties**

Use the existing `ModuleConfig` name so downstream v1 code remains import-compatible:

    @dataclass(frozen=True)
    class ModuleConfig:
        module_id: str
        path: str
        kind: str | None = None
        required: bool = False
        inspect: tuple[str, ...] = ()
        exclude: tuple[str, ...] = ()
        authoritative_for: tuple[str, ...] = ()
        roles: tuple[str, ...] = ()
        service_id: str | None = None

        @property
        def effective_roles(self) -> tuple[str, ...]:
            return self.roles or ((self.kind,) if self.kind else ())

        @property
        def primary_role(self) -> str:
            return self.effective_roles[0] if self.effective_roles else "other"

`parse_manifest` selects `workspace.schema.json` for version 1 and
`workspace-v2.schema.json` for version 2. It explicitly passes `False` as the
v1 `required` default and `True` as the v2 default. Reject duplicate IDs in
Python because JSON Schema uniqueness cannot compare one object field.

Keep `WorkspaceManifest.modules` as the stored tuple and expose
`repositories` as a read-only alias. This preserves old callers while making
new code use repository terminology.

- [ ] **Step 5: Make snapshots version-aware**

For v1, retain the existing version-1 output with `modules` and `kind`. For v2,
emit version 2 with `status` and `repositories`; each available record contains
`available: true`, path, roles, service ID, required, inspect, exclude, commit,
branch, remote, dirty, and dirty policy. An unavailable repository remains in
the mapping with `available: false`, path, roles, service ID, required,
`repository-unavailable`, and severity `blocking` for required or `warning` for
optional. Top-level status is blocked when any required repository is
unavailable and complete otherwise. Hash the complete normalized repository
mapping into `snapshot_id`; never omit an unavailable confirmed repository from
that identity.

For v2 `working-tree` policy, also record a run guard fingerprint. Hash the raw
`git diff --binary --no-ext-diff <commit> -- .` bytes plus sorted untracked
relative paths and their content hashes after manifest exclusions. Store only
the fingerprint, never diff bytes. The fingerprint is an in-run change detector,
not a cross-run cache identity.

Add `snapshot_repositories` so new consumers do not branch on field names:

    def snapshot_repositories(snapshot: Mapping[str, Any]) -> Mapping[str, Any]:
        key = "repositories" if snapshot.get("version") == 2 else "modules"
        value = snapshot.get(key)
        if not isinstance(value, dict):
            raise ValueError(f"workspace snapshot has no {key} mapping")
        return value

- [ ] **Step 6: Run workspace tests**

Run:

    python tools/workspace_discovery/test_workspace_discovery.py -v

Expected: PASS for all existing v1 tests and the new v2 cases.

- [ ] **Step 7: Commit workspace v2**

    git add schemas/workspace-v2.schema.json tools/workspace_discovery/models.py tools/workspace_discovery/discovery.py tools/workspace_discovery/fixtures.py tools/workspace_discovery/test_workspace_discovery.py tools/workspace_discovery/README.md
    git commit -m "feat: support open-role multi-repo workspaces"

### Task 2: Define normalized discovery contracts

**Files:**
- Create: `schemas/methodology-extractor-result.schema.json`
- Create: `schemas/methodology-discovery-index.schema.json`
- Create: `schemas/methodology-document-jobs.schema.json`
- Create: `schemas/methodology-surface-candidate.schema.json`
- Create: `schemas/methodology-surface-decisions.schema.json`
- Create: `tools/methodology_discovery/__init__.py`
- Create: `tools/methodology_discovery/contracts.py`
- Create: `tools/methodology_discovery/models.py`
- Create: `tools/methodology_discovery/fixtures.py`
- Create: `tools/methodology_discovery/test_contracts.py`

**Interfaces:**
- Produces: `DiscoveryBudget`
- Produces: `SourceRecord`
- Produces: `Candidate`
- Produces: `ExtractorResult`
- Produces: `validate_artifact(value, schema_name) -> None`
- Produces: `write_json_atomic(path, value) -> None`

- [ ] **Step 1: Write failing schema round-trip tests**

    def test_extractor_result_round_trips_through_schema(self) -> None:
        result = valid_extractor_result(
            extractor_id="openapi",
            candidate=interface_candidate(
                canonical_key="http:orders:POST:/documents",
                source_path="api/openapi.yaml",
                pointer="#/paths/~1documents/post",
            ),
        )
        contracts.validate_artifact(result, "methodology-extractor-result.schema.json")

    def test_source_record_requires_selection_reason_and_hash(self) -> None:
        result = valid_extractor_result()
        del result["candidates"][0]["source"]["selection_reason"]
        with self.assertRaisesRegex(ValueError, "selection_reason"):
            contracts.validate_artifact(result, "methodology-extractor-result.schema.json")

- [ ] **Step 2: Run tests and confirm missing modules fail**

Run:

    python tools/methodology_discovery/test_contracts.py -v

Expected: FAIL because the discovery package and schemas do not exist.

- [ ] **Step 3: Implement closed schemas with these exact shapes**

Each extractor result contains:

    version: 1
    extractor_id: openapi
    extractor_version: 1
    repo_id: orders-contracts
    snapshot_identity: commit:0123456789abcdef
    candidates: []
    warnings: []
    errors: []
    limit_reached: false

Each candidate contains:

    entity_type: interface
    canonical_key: http:orders:POST:/documents
    display_name: POST /documents
    service_identity:
      value: orders
      basis: manifest
    attributes:
      protocol: HTTP
      operation: POST /documents
      method: POST
      path: /documents
    source:
      repo_id: orders-contracts
      revision: 0123456789abcdef
      path: api/openapi.yaml
      pointer: '#/paths/~1documents/post'
      selection_reason: openapi-signature
      sha256: 64-lowercase-hex-characters
    confidence: confirmed

Contract rules:

- entity type is `component`, `interface`, `integration`, or `flow`;
- confidence is `confirmed` or `candidate`;
- service identity basis is `contract`, `manifest`, `metadata`, or `unknown`;
- source paths are normalized relative POSIX paths and cannot contain `..`;
- attributes contain JSON scalar values or arrays of JSON scalars, not nested free-form objects;
- warnings and errors use `{code, message, path}` with optional path;
- all closed objects reject additional properties.

`methodology-discovery-index.schema.json` records the effective budget, source
mode, selected files, skipped files, counters, warnings, and `limit_reached`.
`methodology-document-jobs.schema.json` records only selected document paths,
allowed fact types, one assigned candidate-output path, one final output path,
size/hash, and selection reason; it contains no arbitrary prompt field.

`methodology-surface-candidate.schema.json` contains `candidate_id`,
`snapshot_id`, sorted `entities`, `review_groups`, `conflicts`,
`possible_duplicates`, repository diagnostics, and warnings.
`methodology-surface-decisions.schema.json` contains `candidate_id`,
`accept_all`, explicit `include`, `exclude`, `add`, `conflict_resolutions`, and
`duplicate_merges`. Each `add` item contains entity_type, canonical_key,
display_name, and scalar attributes; it does not accept a caller-supplied source.
The review applicator creates the fixed user source required by the Plan 1
surface-review schema.

- [ ] **Step 4: Add typed models and stable serialization**

Use frozen dataclasses for internal records. `to_dict()` methods omit no
contract fields, sort attribute keys, and never include absolute source paths.
Use the atomic JSON writer pattern already established in
`tools/methodology_pipeline/contracts.py`; import that writer rather than
copying it when Plan 1 is installed.

- [ ] **Step 5: Run contract tests**

Run:

    python tools/methodology_discovery/test_contracts.py -v

Expected: PASS.

- [ ] **Step 6: Commit discovery contracts**

    git add schemas/methodology-extractor-result.schema.json schemas/methodology-discovery-index.schema.json schemas/methodology-document-jobs.schema.json schemas/methodology-surface-candidate.schema.json schemas/methodology-surface-decisions.schema.json tools/methodology_discovery/__init__.py tools/methodology_discovery/contracts.py tools/methodology_discovery/models.py tools/methodology_discovery/fixtures.py tools/methodology_discovery/test_contracts.py
    git commit -m "feat: define bounded discovery contracts"

### Task 3: Read exact repository snapshots through hard budgets

**Files:**
- Create: `tools/methodology_discovery/source_views.py`
- Create: `tools/methodology_discovery/locator.py`
- Create: `tools/methodology_discovery/test_source_views.py`
- Create: `tools/methodology_discovery/test_locator.py`

**Interfaces:**
- Produces: `source_view(repo_root, snapshot_state, run_id) -> SourceView`
- Produces: `SourceView.list_paths() -> tuple[str, ...]`
- Produces: `SourceView.read_bytes(path: str, max_bytes: int) -> bytes`
- Produces: `locate_sources(view, repository, budget, source_markers_enabled) -> DiscoveryIndex`

- [ ] **Step 1: Write failing committed-versus-working-tree tests**

Create a temporary Git repository, commit `openapi.yaml` with `/committed`, then
change the working file to `/dirty`.

    def test_head_policy_reads_committed_blob(self) -> None:
        view = source_views.source_view(repo, head_snapshot(), run_id="RUN-001")
        self.assertIn(b"/committed", view.read_bytes("openapi.yaml", 5 * MIB))
        self.assertNotIn(b"/dirty", view.read_bytes("openapi.yaml", 5 * MIB))

    def test_working_tree_policy_reads_dirty_bytes(self) -> None:
        view = source_views.source_view(repo, working_tree_snapshot(), run_id="RUN-001")
        self.assertIn(b"/dirty", view.read_bytes("openapi.yaml", 5 * MIB))

Also test symlink escape rejection, exact byte caps, path normalization, and a
working-tree file changing between indexing and reading. That last case must
raise `source-changed-during-scan` instead of recording a stale hash.
Add a second test that changes a dirty tracked file between discovery-layer
invocations; recreating the working-tree source view must reject the stored run
guard fingerprint and require a fresh workspace snapshot.

- [ ] **Step 2: Run source-view tests and confirm failure**

Run:

    python tools/methodology_discovery/test_source_views.py -v

Expected: FAIL because `SourceView` does not exist.

- [ ] **Step 3: Implement two source views**

`GitTreeSourceView` is used for both clean and `HEAD` policies. It lists paths
with `git ls-tree -rz --name-only <commit>` and reads bytes with
`git cat-file blob <commit>:<normalized-path>`. It validates the path before
passing it as an argument and never invokes a shell.

`WorkingTreeSourceView` indexes the confirmed root with `os.scandir`, does not
follow directory symlinks, resolves every file before reading, and rejects any
resolved path outside the repository. It records size, mtime-ns, and SHA-256 at
selection; reading verifies size/mtime before and hash after the read. On
construction and after a layer, it recomputes the v2 run guard fingerprint and
rejects drift, so sequential layers cannot silently combine different dirty
states.

Both views expose repository-relative POSIX paths, reject NUL and `..`, and
raise a domain `DiscoveryError` for command failure, oversized content, binary
decoding where text is required, or snapshot drift.

- [ ] **Step 4: Write failing locator budget and ordering tests**

Test these fixed MVP defaults:

    DEFAULT_BUDGET = DiscoveryBudget(
        structured_file_bytes=5 * 1024 * 1024,
        document_count=20,
        document_file_bytes=1 * 1024 * 1024,
        source_marker_candidates=500,
    )

Assertions must prove:

- configured `exclude` paths are removed before role prioritization;
- explicit `inspect` paths sort first but still require a recognized signature;
- `.git`, `target`, `build`, `dist`, `node_modules`, `vendor`, generated
  sources, reports, virtual environments, and cache directories are excluded;
- contracts sort before documents, documents before config, and Java markers
  last;
- only 20 high-signal documents are retained by priority then normalized path;
- reaching a limit sets a warning and does not select more files;
- source-marker files are absent unless `source_markers_enabled=True`;
- a misleading filename without the expected content signature is not parsed;
- one explicitly supplied UTF-8 document is selected with reason
  `user-supplied-document` even when its filename is not high-signal, while an
  explicit binary, oversized, escaping, or 21st document is rejected.

- [ ] **Step 5: Implement deterministic signature location**

Recognize:

- JSON/YAML with a top-level `openapi` or `swagger` key;
- JSON/YAML with a top-level `asyncapi` key;
- `.graphql`, `.graphqls`, or `.gql` text containing a schema/type-system
  definition;
- README files, `docs/architecture/**`, `docs/adr/**`, and paths containing
  `architecture`, `endpoint`, or `flow` as high-signal documents;
- Kubernetes/OpenShift JSON/YAML with `apiVersion` and `kind`;
- Docker Compose YAML with a top-level `services` mapping and a recognized
  Compose filename or `name`/`version` marker;
- `Chart.yaml`, `pom.xml`, `build.gradle`, `build.gradle.kts`, and Spring
  configuration files;
- `.java` files containing one of the fixed Spring request mapping, Kafka
  listener, or GraphQL resolver annotations, only in the opt-in layer.

Do a shallow signature parse within the relevant byte cap. Do not accept an
extension alone as proof of OpenAPI, AsyncAPI, Kubernetes, or GraphQL.

- [ ] **Step 6: Run source and locator tests**

Run:

    python -m pytest tools/methodology_discovery/test_source_views.py tools/methodology_discovery/test_locator.py -q

Expected: PASS.

- [ ] **Step 7: Commit bounded source selection**

    git add tools/methodology_discovery/source_views.py tools/methodology_discovery/locator.py tools/methodology_discovery/test_source_views.py tools/methodology_discovery/test_locator.py
    git commit -m "feat: add revision-safe bounded source locator"

### Task 4: Extract structured contracts deterministically

**Files:**
- Modify: `requirements.txt`
- Create: `tools/methodology_discovery/openapi.py`
- Create: `tools/methodology_discovery/asyncapi.py`
- Create: `tools/methodology_discovery/graphql_sdl.py`
- Create: `tools/methodology_discovery/test_openapi.py`
- Create: `tools/methodology_discovery/test_asyncapi.py`
- Create: `tools/methodology_discovery/test_graphql_sdl.py`

**Interfaces:**
- Produces: `extract_openapi(document, context) -> ExtractorResult`
- Produces: `extract_asyncapi(document, context) -> ExtractorResult`
- Produces: `extract_graphql_sdl(text, context) -> ExtractorResult`

- [ ] **Step 1: Add failing normalized extraction tests**

OpenAPI tests cover OpenAPI 3, Swagger 2, path normalization, all standard HTTP
methods, tags, operation IDs, malformed operations, and no remote `$ref`
fetching. The expected key is:

    http:orders:POST:/documents/{id}

AsyncAPI tests cover v2/v3 channel maps and send/receive or
publish/subscribe operations. Direction is normalized to `publish`, `subscribe`,
or `unspecified`, without guessing an application perspective.

GraphQL tests parse SDL and emit one interface candidate for each field of
`Query`, `Mutation`, and `Subscription`, for example:

    graphql:orders:Mutation:createDocument

Invalid SDL produces a structured extractor error with no traceback.

- [ ] **Step 2: Add and install the pinned parser**

Add exactly:

    graphql-core==3.2.11

Run:

    python -m pip install -r requirements-dev.txt

Expected: dependency installation succeeds and `python -c "import graphql"`
returns exit code 0.

- [ ] **Step 3: Run extractor tests and confirm implementation failure**

Run:

    python -m pytest tools/methodology_discovery/test_openapi.py tools/methodology_discovery/test_asyncapi.py tools/methodology_discovery/test_graphql_sdl.py -q

Expected: FAIL because the extractors do not exist.

- [ ] **Step 4: Implement OpenAPI and Swagger extraction**

Parse JSON or safe YAML supplied by the caller. Do not resolve remote URLs.
For each operation, emit method, normalized path, operation ID, tags, summary,
and declared response status codes. Resolve service identity from manifest
`service_id` and explicit `info.x-service-id` when they agree or only one is
present; if they conflict, keep a repository-scoped temporary key and emit a
`service-identity-conflict` diagnostic with both values. Use normalized
`info.title` with basis `metadata` only when neither explicit value exists;
otherwise keep basis `unknown` and scope the temporary key by repository ID.

Treat server/base-path values as attributes, not evidence of an environment.
Malformed individual operations add a warning while valid sibling operations
remain usable.

- [ ] **Step 5: Implement AsyncAPI extraction**

Emit channel name, operation direction, operation ID, message names, and tags.
Do not infer a business flow by joining channel names. Use the same service
identity agreement/conflict rule as OpenAPI.

- [ ] **Step 6: Implement GraphQL SDL extraction**

Use `graphql.parse`; walk only root object definitions and extensions. Emit the
root type, field, argument names/types, and return type as deterministic scalar
attributes. Do not execute introspection and do not contact a server.

- [ ] **Step 7: Run extractor tests**

Run:

    python -m pytest tools/methodology_discovery/test_openapi.py tools/methodology_discovery/test_asyncapi.py tools/methodology_discovery/test_graphql_sdl.py -q

Expected: PASS.

- [ ] **Step 8: Commit structured extractors**

    git add requirements.txt tools/methodology_discovery/openapi.py tools/methodology_discovery/asyncapi.py tools/methodology_discovery/graphql_sdl.py tools/methodology_discovery/test_openapi.py tools/methodology_discovery/test_asyncapi.py tools/methodology_discovery/test_graphql_sdl.py
    git commit -m "feat: extract bounded API contracts"

### Task 5: Extract deployment metadata and emit bounded fallback jobs

**Files:**
- Modify: `.gitignore`
- Create: `tools/methodology_discovery/deployment.py`
- Create: `tools/methodology_discovery/java_markers.py`
- Create: `tools/methodology_discovery/document_jobs.py`
- Create: `tools/methodology_discovery/test_deployment.py`
- Create: `tools/methodology_discovery/test_java_markers.py`
- Create: `tools/methodology_discovery/test_document_jobs.py`

**Interfaces:**
- Produces: `extract_deployment(document, context) -> ExtractorResult`
- Produces: `extract_build_metadata(text, path, context) -> ExtractorResult`
- Produces: `extract_java_markers(text, context, remaining_candidate_budget) -> ExtractorResult`
- Produces: `build_document_jobs(index, snapshot, source_view, run_dir) -> dict[str, Any]`
- Produces: `load_document_results(paths) -> tuple[ExtractorResult, ...]`

- [ ] **Step 1: Write failing deployment and build-metadata tests**

Cover Kubernetes `Deployment`, `StatefulSet`, `Service`, `Ingress`, and
OpenShift `DeploymentConfig` and `Route`. Workloads become components. Declared
ports/routes become interfaces. Label/selector relationships become integration
candidates only when both sides are explicit.

Cover Docker Compose services/ports/explicit `depends_on` relationships and
Spring YAML/properties entries with an explicit Cloud Stream binding
`destination`. A bootstrap-server address is configuration evidence, not a
topic or business integration by itself.

Cover `Chart.yaml` name/appVersion as component metadata. Do not render Helm
templates or execute Helm during discovery.

For Maven/Gradle, extract only the declared artifact/root project name and
framework/plugin markers. Do not scan dependency source or infer interfaces
from a dependency name.

- [ ] **Step 2: Write failing bounded Java marker tests**

Use short Java fixtures that prove:

- class-level and method-level Spring mappings combine into one normalized path;
- `@KafkaListener(topics = "document.created")` emits an integration candidate;
- GraphQL resolver annotations emit GraphQL interface candidates;
- dynamic annotation expressions create a warning instead of an invented value;
- candidate 501 is not emitted and sets `source-marker-candidate-limit`;
- the extractor is never called when the locator option is false.

- [ ] **Step 3: Write failing document-job boundary tests**

Each job must contain one repository, its exact snapshot identity, at most 20
selected paths, allowed fact types `[component, interface, integration, flow]`,
and exact candidate/final outputs below
`<run-dir>/discovery/<repo-id>/extractor-results/`.
Reject a document result when its repo ID, snapshot identity, source path/hash,
entity type, or output location does not match the job.

Add a dirty-policy fixture where `docs/architecture.md` differs between HEAD and
the working tree. The HEAD job's materialized input must contain committed bytes;
the working-tree job must contain the hash-verified dirty bytes. The job never
contains the absolute SUT repository root.

- [ ] **Step 4: Run the focused tests and confirm failure**

Run:

    python -m pytest tools/methodology_discovery/test_deployment.py tools/methodology_discovery/test_java_markers.py tools/methodology_discovery/test_document_jobs.py -q

Expected: FAIL because these extractors and job boundaries do not exist.

- [ ] **Step 5: Implement deployment/build extraction**

Keep all relationship rules declarative and local to one structured document.
Record JSON Pointer/YAML document index source references. A Kubernetes or
Compose object without a stable name adds a diagnostic and produces no
candidate. Emit a messaging integration only from an explicit destination/topic
field; do not derive one from a binding, dependency, or environment-variable
name.

- [ ] **Step 6: Implement the opt-in Java marker extractor**

Use fixed, line-oriented annotation parsers over only locator-selected `.java`
files. Track class-level mapping context within one file; do not resolve symbols,
follow calls, invoke a Java build, or inspect bytecode. Mark all source-derived
entities as `candidate`, not `confirmed`.

- [ ] **Step 7: Implement document job emission and result validation**

Before writing a job, read each selected document through its `SourceView` and
atomically materialize it below
`<run-dir>/discovery/<repo-id>/document-inputs/<ordinal>-<sha256>.txt`. The job
maps each original relative `source_path` and hash to one run-contained
`materialized_path`. The materialized bytes must match the discovery-index hash;
never let the agent reopen the SUT working path.

The job is data, not a free-form prompt. It gives the Plan 3 agent only the
materialized paths and asks for explicitly stated facts with exact source lines;
normalized source references still use the original repository-relative path.
Validated results are ordinary extractor results with
`extractor_id: bounded-document` and `extractor_version: 1`.
Failure or absence produces a warning and leaves manual surface entry available.

Add these local-only patterns without ignoring normalized review/report
artifacts:

    **/.methodology-cache/
    **/methodology-runs/*/discovery/*/document-inputs/
    **/methodology-runs/*/discovery/*/extractor-results/*.candidate.json

- [ ] **Step 8: Run the focused tests**

Run:

    python -m pytest tools/methodology_discovery/test_deployment.py tools/methodology_discovery/test_java_markers.py tools/methodology_discovery/test_document_jobs.py -q

Expected: PASS.

- [ ] **Step 9: Commit fallback extractors and jobs**

    git add .gitignore tools/methodology_discovery/deployment.py tools/methodology_discovery/java_markers.py tools/methodology_discovery/document_jobs.py tools/methodology_discovery/test_deployment.py tools/methodology_discovery/test_java_markers.py tools/methodology_discovery/test_document_jobs.py
    git commit -m "feat: add bounded discovery fallbacks"

### Task 6: Merge repository results into one grouped review

**Files:**
- Create: `tools/methodology_discovery/merge.py`
- Create: `tools/methodology_discovery/surface_review.py`
- Create: `tools/methodology_discovery/test_merge.py`
- Create: `tools/methodology_discovery/test_surface_review.py`

**Interfaces:**
- Produces: `merge_results(snapshot_id, results, repository_diagnostics) -> dict[str, Any]`
- Produces: `apply_surface_decisions(candidate, decisions) -> dict[str, Any]`

- [ ] **Step 1: Write failing merge tests**

Use four logical repositories: contracts, backend, infrastructure, and docs.
Tests must prove:

- OpenAPI and Java candidates for `POST /documents` merge when both carry the
  explicit `orders` service identity;
- the merged entity retains both sorted source records;
- the same method/path from two repositories with unknown service identity is
  not auto-merged and appears in one possible-duplicate group;
- competing scalar attributes appear as one conflict with all source values;
- identical inputs in different order produce byte-identical JSON;
- components sort by stable key, then protocol groups and entity keys;
- a flow is retained only when an extractor explicitly emitted `entity_type:
  flow`.

- [ ] **Step 2: Write failing grouped-decision tests**

    decisions = {
        "version": 1,
        "candidate_id": candidate["candidate_id"],
        "accept_all": True,
        "include": [],
        "exclude": ["http:orders:GET:/actuator/health"],
        "add": [manual_graphql_entity()],
        "conflict_resolutions": [],
        "duplicate_merges": [],
    }
    review = surface_review.apply_surface_decisions(candidate, decisions)
    self.assertEqual(review["status"], "confirmed")
    self.assertNotIn("http:orders:GET:/actuator/health", included_keys(review))

Also reject stale candidate IDs, unknown entity keys, unresolved conflicts,
invalid duplicate merges, duplicate manual keys, and caller-supplied source
records on manual additions.

- [ ] **Step 3: Run merge/review tests and confirm failure**

Run:

    python -m pytest tools/methodology_discovery/test_merge.py tools/methodology_discovery/test_surface_review.py -q

Expected: FAIL because merge and review modules do not exist.

- [ ] **Step 4: Implement protocol-aware stable-key merging**

Canonicalize HTTP methods and parameter names, GraphQL root/field names, and
message channel/direction values. Auto-merge only when the canonical key carries
an explicit service identity. When identity basis is unknown, preserve the
repository-scoped entity and derive a separate protocol signature solely for
possible-duplicate grouping.

An attribute conflict is a sorted list of `{value, sources}`. Never select a
winner by confidence alone. `candidate_id` is SHA-256 of canonical snapshot ID,
entities, conflicts, duplicates, and diagnostics.

- [ ] **Step 5: Implement deterministic review application**

`accept_all` includes every non-conflicting candidate except explicit excludes.
If false, only explicit includes are retained. Every conflict requires one
listed resolution. Manual additions receive confidence `confirmed` and source
`{repo_id: "user", revision: candidate_id, path: "surface-review", pointer:
canonical_key, selection_reason: "manual-addition", sha256: candidate_id}`.

Keep excluded entities, their sources, and an explicit `scope-excluded` reason
in the review artifact. Exclusion means “outside this methodology scope”; no
output may rephrase it as proof that the endpoint or integration does not exist.

Emit the Plan 1 `methodology-surface-review.schema.json` shape with sorted
`included`, `excluded`, and `added` arrays and the original `snapshot_id`.

- [ ] **Step 6: Run merge/review tests**

Run:

    python -m pytest tools/methodology_discovery/test_merge.py tools/methodology_discovery/test_surface_review.py -q

Expected: PASS.

- [ ] **Step 7: Commit system-level merge and review**

    git add tools/methodology_discovery/merge.py tools/methodology_discovery/surface_review.py tools/methodology_discovery/test_merge.py tools/methodology_discovery/test_surface_review.py
    git commit -m "feat: merge discovery into grouped surface review"

### Task 7: Add safe cache keys and discovery CLI

**Files:**
- Create: `tools/methodology_discovery/cache.py`
- Create: `tools/methodology_discovery/methodology_discovery.py`
- Create: `tools/methodology_discovery/test_cache.py`
- Create: `tools/methodology_discovery/test_cli.py`
- Create: `tools/methodology_discovery/README.md`

**Interfaces:**
- Produces: `cache_key(repo_id, snapshot_state, extractor_id, extractor_version, run_id) -> CacheKey`
- Produces CLI: `scan`
- Produces CLI: `merge`
- Produces CLI: `review`

- [ ] **Step 1: Write failing cache tests**

Assert exact behavior:

    self.assertEqual(
        cache_key("contracts", clean_state("abc"), "openapi", 1, "RUN-001").scope,
        "shared",
    )
    self.assertEqual(
        cache_key("contracts", head_state("abc"), "openapi", 1, "RUN-002").identity,
        cache_key("contracts", clean_state("abc"), "openapi", 1, "RUN-001").identity,
    )
    self.assertNotEqual(
        cache_key("backend", working_state("abc"), "java-markers", 1, "RUN-001").identity,
        cache_key("backend", working_state("abc"), "java-markers", 1, "RUN-002").identity,
    )

Changing repo ID, commit, extractor ID, or extractor version must invalidate the
entry. A corrupt entry is ignored with `cache-entry-invalid`, never trusted.

- [ ] **Step 2: Write failing CLI boundary tests**

The exact commands are:

    python tools/methodology_discovery/methodology_discovery.py scan --layer contracts --manifest systems/SHOP/workspace.yaml --workspace-snapshot systems/SHOP/methodology-runs/RUN-001/workspace-snapshot.json --run-dir systems/SHOP/methodology-runs/RUN-001 --cache-dir systems/SHOP/.methodology-cache/discovery --load-test-root <load-test-root>

    python tools/methodology_discovery/methodology_discovery.py merge --workspace-snapshot systems/SHOP/methodology-runs/RUN-001/workspace-snapshot.json --discovery-dir systems/SHOP/methodology-runs/RUN-001/discovery --out systems/SHOP/methodology-runs/RUN-001/surface-candidate.json --load-test-root <load-test-root>

    python tools/methodology_discovery/methodology_discovery.py review --candidate systems/SHOP/methodology-runs/RUN-001/surface-candidate.json --decisions systems/SHOP/methodology-runs/RUN-001/surface-decisions.yaml --out systems/SHOP/methodology-runs/RUN-001/surface-review.json --load-test-root <load-test-root>

Tests verify that every output/cache path is inside the load-test repository,
all SUT bytes remain unchanged, expected domain failures return exit code 2
without a traceback, and one invocation reads only its selected layer. The
allowed layers are `contracts`, `documents`, `configuration`, and
`source-markers`; the last also requires `--enable-source-markers`.
`--include-document <repo-id>:<relative-path>` is valid only with the documents
layer, remains subject to the 20-file/1-MiB budgets and repository boundary, and
records selection reason `user-supplied-document` without editing the manifest.
All run/cache/input artifact paths are resolved below `--load-test-root`; only
confirmed SUT source views may read outside it.

- [ ] **Step 3: Run cache/CLI tests and confirm failure**

Run:

    python -m pytest tools/methodology_discovery/test_cache.py tools/methodology_discovery/test_cli.py -q

Expected: FAIL because cache and CLI modules do not exist.

- [ ] **Step 4: Implement cache policy**

Shared cache path:

    <cache-dir>/<repo-id>/<snapshot-hash>/<extractor-id>-v<version>.json

The snapshot hash for clean and `HEAD` modes is SHA-256 of
`repo_id + "\0commit:" + commit`. Working-tree results are stored only below:

    <run-dir>/discovery/<repo-id>/run-cache/<extractor-id>-v<version>.json

Cache loads validate both the schema and every identity field. Writes are
atomic. Cache hits are copied/serialized into the current run so each run stays
self-contained.

- [ ] **Step 5: Implement scan, merge, and review commands**

`scan` validates manifest/snapshot agreement, creates one source view per
repository, and adds only the requested layer to its discovery index and
extractor results. Repeating a completed layer is idempotent. The `documents`
layer emits `document-jobs.json` when high-signal documents exist. A missing
required repository is an error diagnostic and sets scan status `blocked`; a
missing optional repository is a warning and the other repositories continue.
Failure of one parser is recorded against its exact file and excludes only that
result; other extractors and manual surface entry remain usable unless the failed
file was the only path to a required reviewable surface.

Never scan the repository whose normalized path equals `load_test_module`; it is
the writable artifact owner, not a SUT source. This path rule is authoritative
even if its optional roles contain another label. Other role values never skip
or force an extractor.

`merge` sets `reviewable: true` when the accumulated surface contains at least
one interface or integration, or an explicit component/flow accepted from a
high-signal document. The CLI reports this value but never starts the next layer.
The workflow decides whether to stop, deepen, or ask for manual surface entry.

`merge` reads all validated deterministic results, plus any valid bounded
document results already present, and writes one system candidate. `review`
validates decisions and writes the confirmed surface.

Exit codes are 0 for complete success, 1 for usable output with warnings, and 2
for blocked/invalid input. All three commands print a one-line artifact summary.

- [ ] **Step 6: Run cache/CLI tests**

Run:

    python -m pytest tools/methodology_discovery/test_cache.py tools/methodology_discovery/test_cli.py -q

Expected: PASS.

- [ ] **Step 7: Commit cache, CLI, and documentation**

    git add tools/methodology_discovery/cache.py tools/methodology_discovery/methodology_discovery.py tools/methodology_discovery/test_cache.py tools/methodology_discovery/test_cli.py tools/methodology_discovery/README.md
    git commit -m "feat: add cached bounded discovery CLI"

### Task 8: Prove the four-repository discovery path

**Files:**
- Create: `tools/methodology_discovery/test_multirepo_e2e.py`
- Modify: `tools/methodology_discovery/fixtures.py`
- Modify: `tools/workspace_discovery/test_workspace_discovery.py`

- [ ] **Step 1: Write the failing four-repository fixture**

Create temporary Git repositories with these exact roles and facts:

- `orders-contracts`: OpenAPI `POST /documents`, service ID `orders`;
- `orders-backend`: matching Spring mapping plus health endpoint, service ID
  `orders`;
- `orders-infra`: OpenShift Deployment and Route;
- `orders-docs`: architecture document explicitly naming a document-created
  flow; its bounded extractor result is supplied as a validated fixture because
  the agent is integrated in Plan 3.

The load-test repository holds workspace v2, the run, and cache. No fixture SUT
repository is writable through the discovery CLI.

- [ ] **Step 2: Assert multi-repo acceptance behavior**

The test must prove:

1. four independent snapshot records and discovery indexes exist;
2. contract/backend `POST /documents` merges to one entity with two sources;
3. health remains separately reviewable and can be excluded;
4. the explicit documented flow is retained and no flow is inferred elsewhere;
5. the surface is grouped once at system level;
6. the fixture explicitly enables the source-marker layer before asserting the
   OpenAPI/Spring duplicate, and no source marker ran during the contract layer;
7. a second identical run uses shared cache for all clean repositories;
8. changing only the infrastructure commit rescans only infrastructure and
   deterministically re-merges all four results;
9. switching backend to working-tree policy prevents cross-run reuse;
10. all read files have index records and no budget silently expands;
11. byte-for-byte repository checks prove no SUT mutation.

- [ ] **Step 3: Run the E2E test and confirm failure**

Run:

    python tools/methodology_discovery/test_multirepo_e2e.py -v

Expected: FAIL until all packages are wired consistently.

- [ ] **Step 4: Fix only integration defects exposed by the fixture**

Keep the fixture as the contract. Do not add new discovery layers, graph tools,
or unbounded fallbacks to make it pass.

- [ ] **Step 5: Run all discovery and workspace tests**

Run:

    python -m pytest tools/workspace_discovery tools/methodology_discovery -q

Expected: PASS.

- [ ] **Step 6: Verify dependency and placeholder hygiene**

Run:

    python -m pip check
    rg -n "TODO|FIXME|TBD|NotImplementedError" tools/methodology_discovery schemas/workspace-v2.schema.json schemas/methodology-*.schema.json

Expected: `pip check` reports no broken requirements and `rg` returns no hits.

- [ ] **Step 7: Commit discovery acceptance coverage**

    git add tools/methodology_discovery/fixtures.py tools/methodology_discovery/test_multirepo_e2e.py tools/workspace_discovery/test_workspace_discovery.py
    git commit -m "test: prove bounded multi-repo discovery"

## Plan 2 Completion Evidence

Before starting workflow integration, capture:

    python -m pytest tools/workspace_discovery tools/methodology_discovery -q
    python -m pip check
    git status --short

Expected: all tests pass, dependencies are consistent, and only intentionally
tracked implementation changes are present. Do not remove legacy evidence
collectors or graph tooling in this plan.

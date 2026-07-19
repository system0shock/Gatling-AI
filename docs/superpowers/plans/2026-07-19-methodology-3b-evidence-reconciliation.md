# Methodology 3b: Evidence Reconciliation and Collector Agents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add normalized evidence contracts, deterministic repository/Confluence reconciliation, and focused read-only collector subagents that communicate through files instead of raw session context.

**Architecture:** Module inspectors and the Confluence researcher write schema-valid evidence files. A deterministic aggregator and reconciler operate only on those files, preserve every conflicting candidate, and emit compact discrepancy/gap/coverage artifacts. Gigacode subagents are narrowly scoped and return envelope summaries.

**Tech Stack:** Python 3.11+, PyYAML, jsonschema, stdlib JSON/dataclasses, `unittest`, Gigacode Markdown skills/agents.

## Global Constraints

- Requires Phase 3a interfaces and `workspace-snapshot.json`.
- Collector agents are read-only and never edit SUT modules or `methodology.md`.
- Raw source pages and source files must not be returned in agent messages.
- Every evidence fact includes a stable entity key and exact source provenance.
- Reconciliation never silently chooses between conflicting OpenAPI, backend, frontend, infrastructure, and Confluence claims.
- `docs_only` does not mean obsolete; `repo_only` does not mean business-approved.
- SLA without an explicit normative source remains a blocking gap.
- No runtime dependency additions.

---

## Final file structure

```text
schemas/methodology-evidence.schema.json
tools/methodology_evidence/__init__.py
tools/methodology_evidence/fixtures.py
tools/methodology_evidence/contracts.py
tools/methodology_evidence/aggregate.py
tools/methodology_evidence/reconcile.py
tools/methodology_evidence/methodology_evidence.py
tools/methodology_evidence/test_methodology_evidence.py
tools/methodology_evidence/README.md
.gigacode/agents/mnt-module-inspector.md
.gigacode/agents/mnt-confluence-researcher.md
.gigacode/agents/mnt-evidence-reconciler.md
.gigacode/test_gigacode_package.py
.gigacode/README.md
GIGACODE.md
```

### Task 1: Evidence schema and Python contracts

**Files:**
- Create: `schemas/methodology-evidence.schema.json`
- Create: `tools/methodology_evidence/__init__.py`
- Create: `tools/methodology_evidence/fixtures.py`
- Create: `tools/methodology_evidence/contracts.py`
- Create: `tools/methodology_evidence/test_methodology_evidence.py`

**Interfaces:**
- Produces: `SourceRef`, `EvidenceRecord`, `EvidenceDocument` dataclasses.
- Produces: `load_evidence(path: Path) -> EvidenceDocument`.
- Produces: `write_evidence(document: EvidenceDocument, path: Path) -> None`.

- [ ] **Step 1.1: Write failing round-trip and provenance tests**

```python
class EvidenceContractTest(unittest.TestCase):
    def test_round_trip_preserves_exact_repository_provenance(self) -> None:
        record = contracts.EvidenceRecord(
            entity_type="endpoint", entity_id="orders.get-order",
            section="interfaces", field="method_path", statement="GET /orders/{id}",
            source=contracts.SourceRef(
                source_type="repository", module_id="orders-backend",
                ref="src/main/java/OrdersController.java:42", revision="abc123",
            ),
            confidence="confirmed", freshness="current",
        )
        doc = contracts.EvidenceDocument(producer="mnt-module-inspector", records=(record,))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "evidence.json"
            contracts.write_evidence(doc, path)
            self.assertEqual(contracts.load_evidence(path), doc)

    def test_repository_source_requires_module_and_revision(self) -> None:
        with self.assertRaisesRegex(ValueError, "module_id.*revision"):
            contracts.SourceRef(source_type="repository", ref="x.py:1")
```

Create `fixtures.py`; later tests import these helpers explicitly:

```python
from pathlib import Path
from contracts import EvidenceDocument, EvidenceRecord, SourceRef, write_evidence


def source(source_type: str, *, module: str | None = None, revision: str | None = None) -> SourceRef:
    if source_type in {"repository", "openapi"}:
        return SourceRef(source_type=source_type, ref="src/App.java:10", module_id=module or "orders", revision=revision or "abc")
    if source_type == "confluence":
        return SourceRef(source_type="confluence", ref="https://wiki/page", page_id="42", page_version=3)
    return SourceRef(source_type=source_type, ref="user-confirmation")


def record(source_type: str, statement: str, *, entity_type: str = "endpoint",
           entity_id: str = "orders.get-order", field: str = "method_path",
           module: str | None = None, revision: str | None = None) -> EvidenceRecord:
    return EvidenceRecord(
        entity_type=entity_type, entity_id=entity_id, section="interfaces", field=field,
        statement=statement, source=source(source_type, module=module, revision=revision),
        confidence="confirmed", freshness="current",
    )


def evidence_doc(*records: EvidenceRecord) -> EvidenceDocument:
    return EvidenceDocument(producer="test", records=tuple(records))


def evidence_file(root: Path, *, module: str, revision: str) -> Path:
    path = root / f"{module}.json"
    write_evidence(evidence_doc(record("repository", "GET /orders/{id}", module=module, revision=revision)), path)
    return path


def openapi_endpoint(path: str) -> EvidenceRecord:
    return record("openapi", path, module="api-contracts")


def backend_endpoint(path: str) -> EvidenceRecord:
    return record("repository", path, module="orders-backend")


def same_endpoint_from_openapi() -> EvidenceRecord:
    return openapi_endpoint("GET /orders/{id}")


def same_endpoint_from_backend() -> EvidenceRecord:
    return backend_endpoint("GET /orders/{id}")


def confluence_sla(value: str) -> EvidenceRecord:
    return record("confluence", value, entity_type="sla", entity_id="checkout", field="threshold")


def manual_confirmation(entity_type: str, entity_id: str, field: str, value: str) -> EvidenceRecord:
    return record("manual-confirmation", value, entity_type=entity_type, entity_id=entity_id, field=field)


def repo_doc() -> EvidenceDocument:
    return evidence_doc(record("repository", "p95 <= 800ms", entity_type="sla", entity_id="checkout", field="threshold"))


def confluence_doc() -> EvidenceDocument:
    return evidence_doc(confluence_sla("p95 <= 500ms"))
```

- [ ] **Step 1.2: Verify failure**

Run: `python tools/methodology_evidence/test_methodology_evidence.py EvidenceContractTest -v`
Expected: FAIL because contracts are missing.

- [ ] **Step 1.3: Implement schema and dataclasses**

The JSON schema requires top-level `version: 1`, `producer`, `generated_at`, and
`records`. Every record requires `entity_type`, `entity_id`, `section`, `field`,
`statement`, `source`, `confidence`, and `freshness`. Source types are
`repository`, `confluence`, `manual-confirmation`, `monitoring`, `openapi`.

```python
@dataclass(frozen=True)
class SourceRef:
    source_type: str
    ref: str
    module_id: str | None = None
    revision: str | None = None
    page_id: str | None = None
    page_version: int | None = None
    observed_at: str | None = None

    def __post_init__(self) -> None:
        if self.source_type in {"repository", "openapi"} and not (self.module_id and self.revision):
            raise ValueError("repository/openapi source requires module_id and revision")
        if self.source_type == "confluence" and not (self.page_id and self.page_version is not None):
            raise ValueError("confluence source requires page_id and page_version")


@dataclass(frozen=True)
class EvidenceRecord:
    entity_type: str
    entity_id: str
    section: str
    field: str
    statement: str
    source: SourceRef
    confidence: str
    freshness: str


@dataclass(frozen=True)
class EvidenceDocument:
    producer: str
    records: tuple[EvidenceRecord, ...]
    version: int = 1
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def document_to_dict(document: EvidenceDocument) -> dict[str, Any]:
    return {
        "version": document.version, "producer": document.producer,
        "generated_at": document.generated_at,
        "records": [asdict(record) for record in document.records],
    }


def document_from_dict(data: dict[str, Any]) -> EvidenceDocument:
    records = []
    for item in data["records"]:
        values = dict(item)
        values["source"] = SourceRef(**values["source"])
        records.append(EvidenceRecord(**values))
    return EvidenceDocument(
        version=data["version"], producer=data["producer"],
        generated_at=data["generated_at"], records=tuple(records),
    )


def write_evidence(document: EvidenceDocument, path: Path) -> None:
    data = document_to_dict(document)
    jsonschema.validate(data, load_schema("methodology-evidence.schema.json"))
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


def load_evidence(path: Path) -> EvidenceDocument:
    data = json.loads(path.read_text(encoding="utf-8"))
    jsonschema.validate(data, load_schema("methodology-evidence.schema.json"))
    return document_from_dict(data)
```

Use tuples for records and sorted JSON output (`ensure_ascii=False`,
`sort_keys=True`, `indent=2`). Validate serialized data before write and loaded
data before construction.

- [ ] **Step 1.4: Run tests and commit**

Run: `python tools/methodology_evidence/test_methodology_evidence.py EvidenceContractTest -v`
Expected: `OK`.

```powershell
git add schemas/methodology-evidence.schema.json tools/methodology_evidence
git commit -m "feat: add methodology evidence contract"
```

### Task 2: Repository evidence aggregation

**Files:**
- Create: `tools/methodology_evidence/aggregate.py`
- Modify: `tools/methodology_evidence/test_methodology_evidence.py`

**Interfaces:**
- Consumes: module jobs and `<module-id>-evidence.json` from Phase 3a/agents.
- Produces: `aggregate_modules(snapshot: dict, paths: list[Path]) -> EvidenceDocument`.
- Produces: endpoint and integration inventories grouped by stable IDs.

- [ ] **Step 2.1: Write failing aggregation tests**

```python
class AggregateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_rejects_evidence_revision_different_from_snapshot(self) -> None:
        snapshot = {"modules": {"orders": {"commit": "abc", "dirty": False}}}
        evidence = evidence_file(self.root, module="orders", revision="def")
        with self.assertRaisesRegex(ValueError, "snapshot revision"):
            aggregate.aggregate_modules(snapshot, [evidence])

    def test_deduplicates_identical_facts_but_keeps_all_sources(self) -> None:
        result = aggregate.aggregate_records([same_endpoint_from_openapi(), same_endpoint_from_backend()])
        item = result.entities[("endpoint", "orders.get-order")]
        self.assertEqual(len(item.candidates["method_path"]), 2)
```

- [ ] **Step 2.2: Verify failure**

Run: `python tools/methodology_evidence/test_methodology_evidence.py AggregateTest -v`
Expected: FAIL because aggregator is missing.

- [ ] **Step 2.3: Implement aggregation without source loss**

```python
@dataclass
class EntityCandidates:
    entity_type: str
    entity_id: str
    candidates: dict[str, list[EvidenceRecord]] = field(default_factory=dict)


@dataclass
class Aggregation:
    entities: dict[tuple[str, str], EntityCandidates]


def aggregate_records(records: Iterable[EvidenceRecord]) -> Aggregation:
    entities: dict[tuple[str, str], EntityCandidates] = {}
    for record in sorted(records, key=evidence_sort_key):
        key = (record.entity_type, record.entity_id)
        entity = entities.setdefault(key, EntityCandidates(*key))
        entity.candidates.setdefault(record.field, []).append(record)
    return Aggregation(entities=entities)


def aggregate_modules(snapshot: dict, paths: list[Path]) -> EvidenceDocument:
    records = []
    states = snapshot["modules"]
    for path in sorted(paths):
        document = load_evidence(path)
        for record in document.records:
            source = record.source
            if source.source_type in {"repository", "openapi"}:
                expected = states.get(source.module_id, {}).get("commit")
                if expected != source.revision:
                    raise ValueError(
                        f"{source.module_id} evidence does not match snapshot revision")
            records.append(record)
    return EvidenceDocument(
        producer="methodology-evidence-aggregator",
        records=tuple(sorted(records, key=evidence_sort_key)),
    )
```

Do not collapse sources even when statements match. Write
`endpoint-inventory.json`, `integration-inventory.json`, and
`repository-evidence.json` from this same aggregation so counts reconcile.

- [ ] **Step 2.4: Run tests and commit**

Run: `python tools/methodology_evidence/test_methodology_evidence.py AggregateTest -v`
Expected: `OK`.

```powershell
git add tools/methodology_evidence
git commit -m "feat: aggregate methodology module evidence"
```

### Task 3: Deterministic reconciliation, gaps, and coverage

**Files:**
- Create: `tools/methodology_evidence/reconcile.py`
- Create: `tools/methodology_evidence/methodology_evidence.py`
- Modify: `tools/methodology_evidence/test_methodology_evidence.py`
- Create: `tools/methodology_evidence/README.md`

**Interfaces:**
- Produces: `reconcile_documents(repository: EvidenceDocument, confluence: EvidenceDocument, confirmations: EvidenceDocument) -> Reconciliation`.
- Produces files `resolved-evidence.json`, `discrepancies.md`,
  `methodology-gaps.md`, `section-coverage.json`.
- Produces CLI `aggregate` and `reconcile` subcommands.

- [ ] **Step 3.1: Write failing status and SLA tests**

```python
class ReconcileTest(unittest.TestCase):
    def test_different_openapi_and_backend_paths_are_conflict(self) -> None:
        result = reconcile.reconcile_documents(
            evidence_doc(openapi_endpoint("GET /orders/{id}"), backend_endpoint("GET /order/{id}")),
            evidence_doc(), evidence_doc(),
        )
        self.assertEqual(result.entity("endpoint", "orders.get-order").status, "conflict")

    def test_confluence_only_sla_is_blocking_until_normative_confirmation(self) -> None:
        result = reconcile.reconcile_documents(
            evidence_doc(), evidence_doc(confluence_sla("p95 <= 500ms")), evidence_doc()
        )
        self.assertIn("SLA requires normative confirmation", result.blocking_gaps[0].message)

    def test_manual_confirmation_resolves_only_matching_entity_and_field(self) -> None:
        confirmation = manual_confirmation("sla", "checkout", "threshold", "p95 <= 800ms")
        result = reconcile.reconcile_documents(repo_doc(), confluence_doc(), evidence_doc(confirmation))
        self.assertEqual(result.entity("sla", "checkout").status, "confirmed")
```

- [ ] **Step 3.2: Verify failure**

Run: `python tools/methodology_evidence/test_methodology_evidence.py ReconcileTest -v`
Expected: FAIL.

- [ ] **Step 3.3: Implement explicit statuses**

```python
STATUSES = {"confirmed", "repo_only", "docs_only", "conflict", "inferred", "unknown", "not_applicable"}


@dataclass(frozen=True)
class Finding:
    rule: str
    message: str
    severity: str = "blocking"
    entity_type: str | None = None
    entity_id: str | None = None


@dataclass(frozen=True)
class ResolvedEntity:
    entity_type: str
    entity_id: str
    status: str
    fields: dict[str, tuple[EvidenceRecord, ...]]


@dataclass(frozen=True)
class Reconciliation:
    entities: dict[tuple[str, str], ResolvedEntity]
    blocking_gaps: tuple[Finding, ...]

    def entity(self, entity_type: str, entity_id: str) -> ResolvedEntity:
        return self.entities[(entity_type, entity_id)]


def field_status(records: list[EvidenceRecord]) -> str:
    normalized = {normalize_statement(record.statement) for record in records}
    source_types = {record.source.source_type for record in records}
    if "manual-confirmation" in source_types:
        return "confirmed"
    if len(normalized) > 1:
        return "conflict"
    if source_types <= {"repository", "openapi"}:
        return "repo_only"
    if source_types == {"confluence"}:
        return "docs_only"
    return "confirmed"


STATUS_PRIORITY = {
    "conflict": 6, "unknown": 5, "inferred": 4, "docs_only": 3,
    "repo_only": 2, "confirmed": 1, "not_applicable": 0,
}


def reconcile_documents(repository: EvidenceDocument, confluence: EvidenceDocument,
                        confirmations: EvidenceDocument) -> Reconciliation:
    grouped: dict[tuple[str, str], dict[str, list[EvidenceRecord]]] = {}
    for record in (*repository.records, *confluence.records, *confirmations.records):
        grouped.setdefault((record.entity_type, record.entity_id), {}).setdefault(
            record.field, []).append(record)

    entities = {}
    gaps = []
    for (entity_type, entity_id), fields in sorted(grouped.items()):
        frozen_fields = {
            name: tuple(sorted(records, key=evidence_sort_key))
            for name, records in sorted(fields.items())
        }
        statuses = [field_status(list(records)) for records in frozen_fields.values()]
        status = max(statuses, key=STATUS_PRIORITY.__getitem__)
        entities[(entity_type, entity_id)] = ResolvedEntity(
            entity_type, entity_id, status, frozen_fields)
        if status == "conflict":
            gaps.append(Finding("evidence-conflict", "conflicting source claims",
                                entity_type=entity_type, entity_id=entity_id))
        if entity_type == "sla" and not any(
            record.source.source_type == "manual-confirmation"
            for records in frozen_fields.values() for record in records
        ):
            gaps.append(Finding("sla-normative-source",
                                "SLA requires normative confirmation",
                                entity_type=entity_type, entity_id=entity_id))
    if not any(entity_type == "workload" for entity_type, _ in entities):
        gaps.append(Finding("production-workload", "production workload evidence is missing"))
    return Reconciliation(entities, tuple(gaps))
```

Keep candidate records in the resolved JSON. Generate Markdown from structured
findings, not by asking an LLM. Required MNT sections are the 17 headings in the
design spec; `section-coverage.json` reports `covered`, `partial`, or `missing`
and evidence IDs for each.

- [ ] **Step 3.4: Implement CLI and verify outputs**

Run:

```powershell
python tools/methodology_evidence/methodology_evidence.py reconcile `
  --repository test-fixtures/repository-evidence.json `
  --confluence test-fixtures/confluence-evidence.json `
  --confirmations test-fixtures/manual-confirmations.json `
  --out-dir .tmp/methodology-reconcile
```

Expected: exit `0` with no blocking gaps; exit `2` when blocking gaps exist;
all four output files are written in both cases.

- [ ] **Step 3.5: Run tests and commit**

Run: `python tools/methodology_evidence/test_methodology_evidence.py -v`
Expected: all tests pass.

```powershell
git add tools/methodology_evidence
git commit -m "feat: reconcile methodology evidence and gaps"
```

### Task 4: Read-only collector and reconciler subagents

**Files:**
- Create: `.gigacode/agents/mnt-module-inspector.md`
- Create: `.gigacode/agents/mnt-confluence-researcher.md`
- Create: `.gigacode/agents/mnt-evidence-reconciler.md`
- Modify: `.gigacode/test_gigacode_package.py`
- Modify: `.gigacode/README.md`
- Modify: `GIGACODE.md`

**Interfaces:**
- Module inspector consumes one Phase 3a job envelope and writes one evidence file.
- Confluence researcher consumes page/search scope and writes `confluence-snapshot.json` plus evidence.
- Reconciler consumes only evidence files and runs the deterministic CLI.

- [ ] **Step 4.1: Generalize package tests before adding agents**

Replace exact skill/agent counts with required-name subset checks:

```python
REQUIRED_AGENTS = {
    "validator-subagent", "mnt-module-inspector",
    "mnt-confluence-researcher", "mnt-evidence-reconciler",
}

def agent_names() -> set[str]:
    names = set()
    for path in (GIGACODE / "agents").glob("*.md"):
        fm = frontmatter(path.read_text(encoding="utf-8")) or ""
        match = re.search(r"(?m)^name:\s*(\S+)", fm)
        if match:
            names.add(match.group(1))
    return names


def test_required_agents_exist(self) -> None:
    self.assertTrue(REQUIRED_AGENTS <= agent_names())
```

Add a test that every `mnt-*researcher` and `mnt-*inspector` frontmatter contains
`disallowedTools` entries for `write_file` and `edit`.

- [ ] **Step 4.2: Verify package tests fail**

Run: `python .gigacode/test_gigacode_package.py -v`
Expected: FAIL listing the three missing agents.

- [ ] **Step 4.3: Write focused agent definitions**

All three use `model: inherit`, `approvalMode: default`, and explicit output
envelopes. `mnt-module-inspector` may use read/search/shell tools but its prompt
must forbid writes and restrict reads to `module_path` plus its job file.
`mnt-confluence-researcher` must forbid Confluence create/update tools and
capture page ID/version/date. `mnt-evidence-reconciler` reads only run artifacts
and invokes the deterministic reconciliation CLI; it never rereads sources.

Each returns exactly:

```json
{
  "status": "completed|blocked",
  "summary": "one paragraph",
  "counts": {"facts": 0, "warnings": 0, "blockers": 0},
  "artifacts": ["relative/path.json"],
  "next_action": "stable action name"
}
```

- [ ] **Step 4.4: Document tool boundaries and verify**

Update `.gigacode/README.md` and `GIGACODE.md` with the collector roles,
file-based handoff rule, and statement that Atlassian MCP configuration remains
host-specific. Run:

```powershell
python .gigacode/test_gigacode_package.py -v
python tools/methodology_evidence/test_methodology_evidence.py -v
```

Expected: all tests pass.

- [ ] **Step 4.5: Commit**

```powershell
git add .gigacode/agents .gigacode/test_gigacode_package.py .gigacode/README.md GIGACODE.md
git commit -m "feat: add methodology evidence subagents"
```

## Phase 3b completion gate

- Every collected fact validates against the evidence schema and cites a source.
- Aggregation counts reconcile with all module evidence inputs.
- Conflicts retain every candidate; no source is silently discarded.
- Blocking gaps include unconfirmed SLA and missing production workload.
- Collector agents cannot write SUT or MNT files and return only compact envelopes.
- Reconciler reads evidence artifacts rather than raw code or Confluence pages.

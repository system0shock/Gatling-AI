# Methodology 3d: Guarded Confluence Publishing and Incremental Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add selective refresh planning and a Confluence publication workflow that updates a page only after a separate approval bound to the final local MNT hash, target page, expected page version, and displayed Confluence diff.

**Architecture:** Deterministic refresh tooling compares composite workspace and Confluence snapshots and maps changes to affected evidence entities and MNT sections. A publish guard operates on a fetched page snapshot and local Markdown, creates a diff and approval descriptor, then a least-privilege publisher subagent performs the MCP update only after validation; publication results are captured in an auditable receipt.

**Tech Stack:** Python 3.11+ stdlib, jsonschema, `unittest`, Atlassian MCP via Gigacode host, Markdown agent definitions.

## Global Constraints

- Requires the green local `methodology.md` produced by Phase 3c.
- Local patch approval and Confluence publish approval are separate records.
- Publisher must re-read the page immediately before update and compare page version/content hash.
- Any page version, page content, local file, target page ID, or diff change invalidates publish approval.
- Git `methodology.md` is the source of published content; Confluence is a projection.
- Incremental refresh reruns only changed module/page collectors and affected reconciliation entities.
- No write is allowed to SUT repositories.
- Confluence write tools are available only to the publisher role.
- Failure after Confluence update must still produce a recoverable receipt containing observed page version and local hash.

---

## Final file structure

```text
schemas/methodology-refresh-plan.schema.json
schemas/methodology-publish-approval.schema.json
schemas/methodology-publish-receipt.schema.json
tools/methodology_refresh/__init__.py
tools/methodology_refresh/fixtures.py
tools/methodology_refresh/methodology_refresh.py
tools/methodology_refresh/test_methodology_refresh.py
tools/methodology_refresh/README.md
tools/methodology_publish/__init__.py
tools/methodology_publish/fixtures.py
tools/methodology_publish/methodology_publish.py
tools/methodology_publish/test_methodology_publish.py
tools/methodology_publish/README.md
.gigacode/agents/mnt-confluence-publisher.md
.gigacode/skills/manage-methodology/SKILL.md
.gigacode/commands/manage-methodology.md
.gigacode/test_gigacode_package.py
examples/methodology/run_golden_methodology.py
examples/methodology/README.md
docs/METHODOLOGY.md
docs/ARCHITECTURE.md
docs/GETTING_STARTED.md
docs/PRD.md
```

### Task 1: Snapshot comparison and impact mapping

**Files:**
- Create: `schemas/methodology-refresh-plan.schema.json`
- Create: `tools/methodology_refresh/__init__.py`
- Create: `tools/methodology_refresh/fixtures.py`
- Create: `tools/methodology_refresh/methodology_refresh.py`
- Create: `tools/methodology_refresh/test_methodology_refresh.py`
- Create: `tools/methodology_refresh/README.md`

**Interfaces:**
- Produces: `compare_snapshots(previous, current) -> tuple[SourceChange, ...]`.
- Produces: `build_refresh_plan(changes, source_map, manifest) -> dict`.
- CLI writes `methodology-refresh-plan.json`.

- [ ] **Step 1.1: Write failing selective-refresh tests**

```python
class RefreshPlanTest(unittest.TestCase):
    def test_only_changed_openapi_module_targets_interfaces(self) -> None:
        previous = snapshot(openapi="aaa", backend="bbb", frontend="ccc")
        current = snapshot(openapi="ddd", backend="bbb", frontend="ccc")
        plan = refresh.build_refresh_plan(
            refresh.compare_snapshots(previous, current), source_map(), manifest()
        )
        self.assertEqual(plan["inspect_modules"], ["api-contracts"])
        self.assertEqual(plan["affected_sections"], ["Реестр тестируемых интерфейсов"])
        self.assertNotIn("backend", plan["inspect_modules"])

    def test_changed_confluence_sla_targets_sla_section(self) -> None:
        changes = refresh.compare_confluence_pages(
            pages({"sla-page": 4}), pages({"sla-page": 5}), page_roles={"sla-page": ["sla"]}
        )
        plan = refresh.build_refresh_plan(changes, source_map(), manifest())
        self.assertIn("SLA, SLO и критерии приемки", plan["affected_sections"])
```

Create `tools/methodology_refresh/fixtures.py`; import all four named helpers explicitly:

```python
MODULES = {
    "openapi": ("api-contracts", "api-spec"),
    "backend": ("orders-backend", "backend"),
    "frontend": ("web-frontend", "frontend"),
}


def snapshot(**commits: str) -> dict:
    return {"snapshot_id": "fixture", "modules": {
        MODULES[key][0]: {"commit": value, "dirty": False, "kind": MODULES[key][1]}
        for key, value in commits.items()
    }}


def source_map() -> dict:
    return {"version": 1, "sources": {}, "sections": {}}


def manifest() -> dict:
    return {"modules": [
        {"id": module_id, "kind": kind} for module_id, kind in MODULES.values()
    ]}


def pages(versions: dict[str, int]) -> dict:
    return {"pages": {page_id: {"version": version} for page_id, version in versions.items()}}
```

- [ ] **Step 1.2: Verify failure**

Run: `python tools/methodology_refresh/test_methodology_refresh.py -v`
Expected: FAIL.

- [ ] **Step 1.3: Implement explicit impact rules**

```python
@dataclass(frozen=True)
class SourceChange:
    source_type: str
    source_id: str
    previous_revision: str | int | None
    current_revision: str | int | None
    previous_snapshot_id: str
    current_snapshot_id: str
    reason: str
    roles: tuple[str, ...] = ()


KIND_SECTIONS = {
    "api-spec": ("Реестр тестируемых интерфейсов",),
    "backend": ("Архитектура", "Реестр интеграций", "Реестр тестируемых интерфейсов",
                "Наблюдаемость и диагностика"),
    "frontend": ("Описание системы и функциональности", "Пользовательские и технические потоки"),
    "infrastructure": ("Архитектура", "Тестовый стенд"),
    "database": ("Архитектура", "Риски, ограничения и допущения"),
}

ROLE_SECTIONS = {
    "sla": ("SLA, SLO и критерии приемки",),
    "architecture": ("Архитектура",),
    "integrations": ("Реестр интеграций",),
    "workload": ("Модель нагрузки",),
}


def compare_snapshots(previous: dict, current: dict) -> tuple[SourceChange, ...]:
    changes = []
    previous_modules = previous.get("modules", {})
    current_modules = current.get("modules", {})
    for module_id in sorted(previous_modules.keys() | current_modules.keys()):
        before = previous_modules.get(module_id)
        after = current_modules.get(module_id)
        before_revision = None if before is None else f"{before.get('commit')}:{before.get('dirty')}"
        after_revision = None if after is None else f"{after.get('commit')}:{after.get('dirty')}"
        if before_revision != after_revision:
            changes.append(SourceChange(
                "module", module_id, before_revision, after_revision,
                previous.get("snapshot_id", "unknown"),
                current.get("snapshot_id", "unknown"), "git-state-changed",
            ))
    return tuple(changes)


def compare_confluence_pages(previous: dict, current: dict,
                             page_roles: dict[str, list[str]]) -> tuple[SourceChange, ...]:
    changes = []
    before_pages, after_pages = previous.get("pages", {}), current.get("pages", {})
    for page_id in sorted(before_pages.keys() | after_pages.keys()):
        before = before_pages.get(page_id, {}).get("version")
        after = after_pages.get(page_id, {}).get("version")
        if before != after:
            changes.append(SourceChange(
                "confluence", page_id, before, after,
                previous.get("snapshot_id", "unknown"),
                current.get("snapshot_id", "unknown"), "page-version-changed",
                tuple(sorted(page_roles.get(page_id, []))),
            ))
    return tuple(changes)


def build_refresh_plan(changes: tuple[SourceChange, ...], source_map: dict,
                       manifest: dict) -> dict:
    module_kinds = {item["id"]: item["kind"] for item in manifest["modules"]}
    inspect_modules, fetch_pages, entities, sections, reasons = set(), set(), set(), set(), []
    mapped_sources = source_map.get("sources", {})
    for change in changes:
        source_key = f"{change.source_type}:{change.source_id}"
        mapping = mapped_sources.get(source_key, {})
        entities.update(mapping.get("entity_ids", []))
        mapped_sections = set(mapping.get("sections", []))
        if change.source_type == "module":
            inspect_modules.add(change.source_id)
            default_sections = set(KIND_SECTIONS.get(module_kinds[change.source_id], ()))
        else:
            fetch_pages.add(change.source_id)
            default_sections = {section for role in change.roles for section in ROLE_SECTIONS.get(role, ())}
        sections.update(mapped_sections or default_sections)
        reasons.append({"source": source_key, "reason": change.reason})
    return {
        "version": 1,
        "previous_snapshot_id": changes[0].previous_snapshot_id if changes else "unchanged",
        "current_snapshot_id": changes[0].current_snapshot_id if changes else "unchanged",
        "changed_sources": [asdict(change) for change in changes],
        "inspect_modules": sorted(inspect_modules),
        "fetch_page_ids": sorted(fetch_pages),
        "affected_entity_ids": sorted(entities),
        "affected_sections": sorted(sections),
        "reconciliation_scope": sorted(entities) or ["affected-sections"],
        "reasons": reasons,
    }
```

Source-map entity links narrow these defaults further when available. The
refresh schema requires previous/current snapshot IDs, changed sources,
inspect modules, fetch page IDs, affected entity IDs, affected sections,
reconciliation scope, and reasons.

- [ ] **Step 1.4: Implement CLI and commit**

Run:

```powershell
python tools/methodology_refresh/methodology_refresh.py `
  --previous-run systems/SHOP/methodology-runs/RUN-001 `
  --current-run systems/SHOP/methodology-runs/RUN-002 `
  --workspace systems/SHOP/workspace.yaml `
  --source-map systems/SHOP/methodology-runs/RUN-001/methodology-source-map.json `
  --out systems/SHOP/methodology-runs/RUN-002/methodology-refresh-plan.json
```

Expected: exit `0`; deterministic JSON.

```powershell
git add schemas/methodology-refresh-plan.schema.json tools/methodology_refresh
git commit -m "feat: plan selective methodology refreshes"
```

### Task 2: Publish diff, approval, and optimistic-concurrency guard

**Files:**
- Create: `schemas/methodology-publish-approval.schema.json`
- Create: `schemas/methodology-publish-receipt.schema.json`
- Create: `tools/methodology_publish/__init__.py`
- Create: `tools/methodology_publish/fixtures.py`
- Create: `tools/methodology_publish/methodology_publish.py`
- Create: `tools/methodology_publish/test_methodology_publish.py`
- Create: `tools/methodology_publish/README.md`

**Interfaces:**
- Consumes a local MNT and fetched `confluence-page-snapshot.json`.
- Produces `confluence.patch`, `publish-descriptor.json`, `publish-approval.json`.
- Produces `validate_publish(...) -> PublishDescriptor` used immediately before MCP update.
- Produces `record_receipt(...) -> dict` after the MCP result.

- [ ] **Step 2.1: Write failing approval/concurrency tests**

```python
class PublishGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self.temp.name)
        self.methodology = self.run_dir / "methodology.md"
        self.methodology.write_text("# МНТ\n", encoding="utf-8")
        self.approval = self.run_dir / "publish-approval.json"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_approval_binds_page_id_version_local_hash_and_diff(self) -> None:
        descriptor = publish.prepare_publish(self.methodology, page_snapshot(id="123", version=7), self.run_dir)
        approval = publish.record_publish_approval(descriptor, "v.salnikov", self.approval)
        self.assertEqual(approval["page_id"], "123")
        self.assertEqual(approval["expected_page_version"], 7)
        self.assertEqual(approval["methodology_sha256"], sha256(self.methodology))

    def test_new_page_version_invalidates_approval(self) -> None:
        descriptor, approval = approved_publish(self, page_version=7)
        with self.assertRaisesRegex(ValueError, "page version"):
            publish.validate_publish(self.methodology, page_snapshot(id="123", version=8), approval)

    def test_local_change_invalidates_publish_approval(self) -> None:
        descriptor, approval = approved_publish(self, page_version=7)
        self.methodology.write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "methodology_sha256"):
            publish.validate_publish(self.methodology, page_snapshot(id="123", version=7), approval)
```

Create `tools/methodology_publish/fixtures.py`; import the helpers explicitly in the publish test:

```python
import hashlib
from pathlib import Path
import methodology_publish as publish


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def page_snapshot(id: str, version: int, body: str = "# Existing MNT\n") -> dict:
    return {
        "page_id": id, "title": "МНТ SHOP", "version": version,
        "body_markdown": body, "body_sha256": hashlib.sha256(body.encode()).hexdigest(),
        "fetched_at": "2026-07-19T12:00:00Z", "url": f"https://wiki/pages/{id}",
    }


def approved_publish(case, page_version: int):
    descriptor = publish.prepare_publish(
        case.methodology, page_snapshot("123", page_version), case.run_dir)
    approval = publish.record_publish_approval(descriptor, "v.salnikov", case.approval)
    return descriptor, approval
```

- [ ] **Step 2.2: Verify failure**

Run: `python tools/methodology_publish/test_methodology_publish.py -v`
Expected: FAIL.

- [ ] **Step 2.3: Implement snapshot and approval schemas**

```python
@dataclass(frozen=True)
class PublishDescriptor:
    page_id: str
    expected_page_version: int
    expected_page_sha256: str
    methodology_sha256: str
    confluence_patch_sha256: str
    patch_path: str
```

`publish-approval.json` requires:

```json
{
  "version": 1,
  "kind": "confluence-publish",
  "page_id": "123",
  "expected_page_version": 7,
  "expected_page_sha256": "...",
  "methodology_sha256": "...",
  "confluence_patch_sha256": "...",
  "approved_by": "v.salnikov",
  "approved_at": "2026-07-19T12:00:00Z"
}
```

Page snapshot requires `page_id`, `title`, `version`, `body_markdown`,
`body_sha256`, `fetched_at`, and `url`. Never accept a descriptor whose supplied
hash disagrees with recomputed content.

- [ ] **Step 2.4: Implement diff and receipt**

Use these exact content-bound operations:

```python
def prepare_publish(methodology: Path, page: dict, run_dir: Path) -> PublishDescriptor:
    body = methodology.read_text(encoding="utf-8")
    if hashlib.sha256(page["body_markdown"].encode()).hexdigest() != page["body_sha256"]:
        raise ValueError("page body_sha256 mismatch")
    patch_text = "".join(difflib.unified_diff(
        page["body_markdown"].splitlines(keepends=True),
        body.splitlines(keepends=True), fromfile=f"confluence:{page['page_id']}",
        tofile=str(methodology),
    ))
    patch_path = run_dir / "confluence.patch"
    atomic_write_text(patch_path, patch_text)
    return PublishDescriptor(
        page_id=page["page_id"], expected_page_version=page["version"],
        expected_page_sha256=page["body_sha256"],
        methodology_sha256=sha256_path(methodology),
        confluence_patch_sha256=sha256_path(patch_path),
        patch_path=str(patch_path),
    )


def record_publish_approval(descriptor: PublishDescriptor, approved_by: str,
                            out: Path) -> dict:
    approval = {
        "version": 1, "kind": "confluence-publish", **asdict(descriptor),
        "approved_by": approved_by,
        "approved_at": datetime.now(timezone.utc).isoformat(),
    }
    approval.pop("patch_path")
    validate_schema("methodology-publish-approval.schema.json", approval)
    atomic_write_json(out, approval)
    return approval


def validate_publish(methodology: Path, current_page: dict,
                     approval: dict) -> PublishDescriptor:
    with tempfile.TemporaryDirectory() as tmp:
        descriptor = prepare_publish(methodology, current_page, Path(tmp))
        expected = {
            "page_id": descriptor.page_id,
            "expected_page_version": descriptor.expected_page_version,
            "expected_page_sha256": descriptor.expected_page_sha256,
            "methodology_sha256": descriptor.methodology_sha256,
            "confluence_patch_sha256": descriptor.confluence_patch_sha256,
        }
        for key, value in expected.items():
            if approval.get(key) != value:
                raise ValueError(f"{key} changed after publish approval")
        return descriptor


def record_receipt(*, approval: dict, mcp_result: dict, actor: str,
                   out: Path) -> dict:
    published_version = mcp_result.get("version")
    status = "published" if published_version is not None else "write-result-unknown"
    receipt = {
        "version": 1, "status": status, "page_id": approval["page_id"],
        "previous_version": approval["expected_page_version"],
        "published_version": published_version,
        "methodology_sha256": approval["methodology_sha256"],
        "returned_page_sha256": mcp_result.get("body_sha256"),
        "mcp_operation_id": mcp_result.get("operation_id"),
        "actor": actor, "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    validate_schema("methodology-publish-receipt.schema.json", receipt)
    atomic_write_json(out, receipt)
    return receipt
```

Receipt statuses are `published`, `blocked-before-write`, and
`write-result-unknown`. Never mark `published` if the MCP response lacks a
new page version.

- [ ] **Step 2.5: Run tests and commit**

Run: `python tools/methodology_publish/test_methodology_publish.py -v`
Expected: all tests pass.

```powershell
git add schemas/methodology-publish-approval.schema.json schemas/methodology-publish-receipt.schema.json tools/methodology_publish
git commit -m "feat: guard methodology Confluence publication"
```

### Task 3: Least-privilege publisher subagent and workflow extension

**Files:**
- Create: `.gigacode/agents/mnt-confluence-publisher.md`
- Modify: `.gigacode/skills/manage-methodology/SKILL.md`
- Modify: `.gigacode/commands/manage-methodology.md`
- Modify: `.gigacode/test_gigacode_package.py`
- Modify: `.gigacode/README.md`
- Modify: `GIGACODE.md`

**Interfaces:**
- Publisher consumes final MNT, fresh page snapshot, approval, and descriptor.
- Publisher re-fetches, validates, updates through MCP, and records receipt.
- Skill adds `refresh` and `publish` actions.

- [ ] **Step 3.1: Add failing package tests**

Require `mnt-confluence-publisher`. Assert publisher instructions contain, in
order, `getConfluencePage`, `validate_publish`, `updateConfluencePage`, and
`publish-receipt.json`. Assert the collector agent still contains no update
tool and the publisher prompt forbids repository writes.

- [ ] **Step 3.2: Verify failure**

Run: `python .gigacode/test_gigacode_package.py -v`
Expected: FAIL for missing publisher.

- [ ] **Step 3.3: Implement publisher role**

The publisher performs exactly:

1. Read final local `methodology.md`.
2. Fetch the target page through Atlassian MCP.
3. Save a fresh page snapshot in the run directory.
4. Run deterministic `validate_publish` against `publish-approval.json`.
5. Stop without update on any mismatch.
6. Call `updateConfluencePage` with the approved page ID and final MNT content.
7. Save a receipt from the returned version.
8. Return an envelope with status, page URL/version, and receipt path.

The agent must not search for a different target page or change page title,
parent, labels, or permissions during publication.

- [ ] **Step 3.4: Extend the orchestrator skill**

`refresh` runs snapshot comparison, only scheduled collectors, scoped
reconciliation, authoring, local gate, and local approval. `publish` is allowed
only after the local canonical file is green. It fetches the page, prepares and
shows the Confluence diff, waits for a second explicit approval, records it,
then dispatches the publisher.

- [ ] **Step 3.5: Verify and commit**

Run:

```powershell
python .gigacode/test_gigacode_package.py -v
python tools/methodology_publish/test_methodology_publish.py -v
python tools/methodology_refresh/test_methodology_refresh.py -v
```

Expected: all tests pass.

```powershell
git add .gigacode
git commit -m "feat: publish approved methodologies to Confluence"
```

### Task 4: Golden multi-repo workflow and documentation

**Files:**
- Create: `examples/methodology/run_golden_methodology.py`
- Create: `examples/methodology/README.md`
- Modify: `docs/METHODOLOGY.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/GETTING_STARTED.md`
- Modify: `docs/PRD.md`

**Interfaces:**
- Golden runner creates temporary sibling Git modules and never relies on repo root being Git.
- It proves create, approve/apply, selective refresh, and guarded publish dry-run.

- [ ] **Step 4.1: Write the failing golden test runner**

`run_golden_methodology.py` must expose `run(work_dir: Path) -> dict` and create
five temporary sibling modules: load-tests, backend, frontend, api-spec, and
infrastructure. Initialize each with `git init`, one commit, and deterministic
fixture files. Use only local commands and no network/MCP.

Test assertions:

```python
result = run(temp_root)
self.assertEqual(result["discovery_unconfirmed"], 4)
self.assertEqual(result["confirmed_modules"], 5)
self.assertEqual(result["local_apply"], "approved")
self.assertEqual(result["refresh_inspect_modules"], ["api-contracts"])
self.assertEqual(result["publish_dry_run"], "approval-required")
```

- [ ] **Step 4.2: Verify initial failure**

Run: `python examples/methodology/run_golden_methodology.py`
Expected: FAIL until orchestration adapters are wired.

- [ ] **Step 4.3: Complete the offline golden flow**

The runner invokes the real Phase 3a–3d CLIs. It supplies fixture evidence in
place of live subagents and a fixture page snapshot in place of MCP. It must
verify byte-for-byte that neither SUT modules nor canonical MNT change before
the relevant approval record.

- [ ] **Step 4.4: Update documentation**

Document:

- permanent MNT versus separate scenario/data/protocol artifacts;
- multi-repo workspace and hybrid confirmation;
- subagent responsibilities and file envelopes;
- create/update/refresh/publish commands;
- two independent approval gates;
- Atlassian MCP read/write scopes and least privilege;
- recovery from stale page version and `write-result-unknown`;
- selective refresh triggers.

- [ ] **Step 4.5: Run full verification and commit**

Run:

```powershell
python examples/methodology/run_golden_methodology.py
python -m pytest tools/workspace_discovery tools/methodology_evidence `
  tools/methodology_authoring tools/methodology_quality_gate `
  tools/methodology_refresh tools/methodology_publish -q
python .gigacode/test_gigacode_package.py -v
```

Expected: golden summary reports all five assertions; all tests pass; no network
access and no changes outside temporary/load-test paths.

```powershell
git add examples/methodology docs
git commit -m "docs: complete methodology generation workflow"
```

## Phase 3d completion gate

- Unchanged modules/pages are not recollected during refresh.
- Local and Confluence approvals are separate and content-bound.
- Publisher re-fetches and validates the page immediately before write.
- Stale version or local hash blocks publication without side effects.
- Successful update produces a receipt with exact versions and hashes.
- Golden multi-repo flow proves no pre-approval mutation and no assumption that workspace root is Git.

# Methodology 3a: Multi-Repo Workspace Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, read-only workspace discovery and snapshot tool that identifies sibling Git modules, requires manifest confirmation before analysis, and emits bounded jobs for later module-inspector subagents.

**Architecture:** `workspace.yaml` is the confirmed allowlist stored in the load-test repository. A stdlib/PyYAML/jsonschema Python CLI resolves the non-Git workspace root, previews sibling repositories without analyzing them, validates every path against the root, and snapshots each confirmed module independently. It never writes to SUT modules.

**Tech Stack:** Python 3.11+, PyYAML 6.0.3, jsonschema 4.26.0, `unittest`, existing `tools/_shared/common.py` helpers.

## Global Constraints

- The workspace root may be empty and MUST NOT be assumed to be a Git repository.
- All module paths in committed `workspace.yaml` are relative to `workspace_root`.
- Auto-discovery creates preview data only; only modules confirmed in `workspace.yaml` may be analyzed.
- SUT modules are read-only; only the configured load-test module may be written.
- Resolved module paths and symlink targets must remain inside the resolved workspace root.
- Module snapshots record commit and dirty state separately for every repository.
- A dirty module requires an explicit `working-tree` or `HEAD` policy.
- Python 3.11+ and existing pinned dependencies only; do not add runtime packages.

---

## Source-of-truth references

- Design: `docs/superpowers/specs/2026-07-19-load-testing-methodology-generation-design.md` §§7, 8, 9.1–9.3, 16–18.
- Shared process helpers: `tools/_shared/common.py` (`load_yaml`, `run_command`, `Finding`).
- CLI/test conventions: `tools/jmx_parser/jmx_parser.py`, `tools/jmx_parser/test_jmx_parser.py`.

## Final file structure

```text
schemas/workspace.schema.json
tools/workspace_discovery/__init__.py
tools/workspace_discovery/fixtures.py
tools/workspace_discovery/models.py
tools/workspace_discovery/discovery.py
tools/workspace_discovery/workspace_discovery.py
tools/workspace_discovery/test_workspace_discovery.py
tools/workspace_discovery/README.md
docs/METHODOLOGY.md
```

### Task 1: Workspace schema and typed manifest loader

**Files:**
- Create: `schemas/workspace.schema.json`
- Create: `tools/workspace_discovery/__init__.py`
- Create: `tools/workspace_discovery/fixtures.py`
- Create: `tools/workspace_discovery/models.py`
- Create: `tools/workspace_discovery/test_workspace_discovery.py`

**Interfaces:**
- Produces: `load_manifest(path: Path) -> WorkspaceManifest`
- Produces: `resolve_workspace_root(manifest_path: Path, value: str) -> Path`
- Produces: immutable `ModuleConfig` and `WorkspaceManifest` dataclasses.

- [ ] **Step 1.1: Write failing loader tests**

```python
class ManifestLoadTest(unittest.TestCase):
    def test_loads_relative_workspace_and_modules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            load_repo = root / "load-tests"
            system_dir = load_repo / "systems" / "SHOP"
            system_dir.mkdir(parents=True)
            manifest = system_dir / "workspace.yaml"
            manifest.write_text(
                """version: 1
system: SHOP
workspace_root: ../../..
load_test_module: load-tests
modules:
  - id: orders
    path: orders-backend
    kind: backend
    required: true
    inspect: [api, integrations]
write_policy:
  allowed_modules: [load-tests]
  sut_modules: read-only
""",
                encoding="utf-8",
            )
            loaded = models.load_manifest(manifest)
            self.assertEqual(loaded.system, "SHOP")
            self.assertEqual(loaded.modules[0].module_id, "orders")
            self.assertEqual(models.resolve_workspace_root(manifest, loaded.workspace_root), root)

    def test_rejects_absolute_module_path(self) -> None:
        doc = {
            "version": 1, "system": "SHOP", "workspace_root": ".",
            "load_test_module": "load-tests",
            "modules": [{"id": "orders", "path": str(Path.cwd().anchor + "outside"),
                         "kind": "backend"}],
            "write_policy": {"allowed_modules": ["load-tests"], "sut_modules": "read-only"},
        }
        with self.assertRaisesRegex(ValueError, "relative"):
            models.parse_manifest(doc)
```

Create `fixtures.py` for later tasks with these exact constructors:

```python
from subprocess import CompletedProcess
from models import ModuleConfig, WorkspaceManifest


def module(module_id: str, path: str, kind: str) -> ModuleConfig:
    return ModuleConfig(module_id=module_id, path=path, kind=kind)


def manifest_object(modules: list[ModuleConfig]) -> WorkspaceManifest:
    return WorkspaceManifest(
        system="SHOP", workspace_root=".", load_test_module="load-tests",
        modules=tuple(modules), allowed_modules=("load-tests",),
    )


def completed_git_outputs(*, head: str, branch: str, status: str, remote: str):
    return [
        CompletedProcess(["git"], 0, head, ""),
        CompletedProcess(["git"], 0, branch, ""),
        CompletedProcess(["git"], 0, status, ""),
        CompletedProcess(["git"], 0, remote, ""),
    ]
```

Import the three helpers explicitly in the test module; do not use wildcard imports.

- [ ] **Step 1.2: Verify failure**

Run: `python tools/workspace_discovery/test_workspace_discovery.py ManifestLoadTest -v`
Expected: `ImportError` or `AttributeError` because `models` does not exist.

- [ ] **Step 1.3: Add the exact schema contract**

Create `schemas/workspace.schema.json` with required root fields
`version`, `system`, `workspace_root`, `load_test_module`, `modules`, and
`write_policy`. Module items require `id`, `path`, and `kind`; `kind` is one of
`load-tests`, `backend`, `frontend`, `api-spec`, `infrastructure`,
`shared-library`, `database`, `other`; `inspect`, `exclude`, and
`authoritative_for` are unique string arrays. Set `additionalProperties: false`
at the root, module, and write-policy levels. Constrain system with
`^[A-Z][A-Z0-9]{1,9}$` and module IDs with `^[a-z][a-z0-9-]{1,63}$`.

- [ ] **Step 1.4: Implement typed parsing**

```python
@dataclass(frozen=True)
class ModuleConfig:
    module_id: str
    path: str
    kind: str
    required: bool = False
    inspect: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    authoritative_for: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkspaceManifest:
    system: str
    workspace_root: str
    load_test_module: str
    modules: tuple[ModuleConfig, ...]
    allowed_modules: tuple[str, ...]


def parse_manifest(doc: dict[str, Any]) -> WorkspaceManifest:
    jsonschema.validate(doc, load_schema("workspace.schema.json"))
    modules = tuple(ModuleConfig(
        module_id=item["id"], path=item["path"], kind=item["kind"],
        required=bool(item.get("required", False)),
        inspect=tuple(item.get("inspect", [])),
        exclude=tuple(item.get("exclude", [])),
        authoritative_for=tuple(item.get("authoritative_for", [])),
    ) for item in doc["modules"])
    for module in modules:
        if Path(module.path).is_absolute():
            raise ValueError(f"module path must be relative: {module.path}")
    return WorkspaceManifest(
        system=doc["system"], workspace_root=doc["workspace_root"],
        load_test_module=doc["load_test_module"], modules=modules,
        allowed_modules=tuple(doc["write_policy"]["allowed_modules"]),
    )
```

Add `load_schema`, `load_manifest`, and `resolve_workspace_root`; use
`Path.resolve(strict=True)` and report a `ValueError` with the manifest path on
schema, YAML, or path failures.

- [ ] **Step 1.5: Run tests and commit**

Run: `python tools/workspace_discovery/test_workspace_discovery.py ManifestLoadTest -v`
Expected: 2 tests, `OK`.

```powershell
git add schemas/workspace.schema.json tools/workspace_discovery
git commit -m "feat: add methodology workspace manifest contract"
```

### Task 2: Safe hybrid discovery preview

**Files:**
- Create: `tools/workspace_discovery/discovery.py`
- Modify: `tools/workspace_discovery/test_workspace_discovery.py`

**Interfaces:**
- Consumes: `WorkspaceManifest`, `run_command`.
- Produces: `ensure_inside(root: Path, candidate: Path) -> Path`.
- Produces: `discover_preview(root: Path, manifest: WorkspaceManifest, max_depth: int = 1) -> dict[str, Any]`.

- [ ] **Step 2.1: Write failing path-boundary and preview tests**

```python
class DiscoveryTest(unittest.TestCase):
    def test_preview_marks_unconfirmed_sibling_without_analyzing_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "load-tests" / ".git").mkdir(parents=True)
            (root / "orders" / ".git").mkdir(parents=True)
            (root / "orders" / "pom.xml").write_text("<project/>", encoding="utf-8")
            manifest = manifest_object(modules=[])
            preview = discovery.discover_preview(root, manifest)
            orders = next(item for item in preview["candidates"] if item["path"] == "orders")
            self.assertEqual(orders["confirmation"], "required")
            self.assertEqual(orders["suggested_kind"], "backend")

    def test_symlink_escape_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            link = Path(tmp) / "escape"
            try:
                link.symlink_to(Path(outside), target_is_directory=True)
            except OSError:
                self.skipTest("symlinks unavailable")
            with self.assertRaisesRegex(ValueError, "outside workspace"):
                discovery.ensure_inside(Path(tmp), link)
```

- [ ] **Step 2.2: Verify failure**

Run: `python tools/workspace_discovery/test_workspace_discovery.py DiscoveryTest -v`
Expected: FAIL because `discovery` is missing.

- [ ] **Step 2.3: Implement bounded discovery**

```python
MARKERS = {
    "api-spec": ("openapi.yaml", "openapi.yml", "swagger.json"),
    "infrastructure": ("Chart.yaml", "terraform.tf", "kustomization.yaml"),
    "frontend": ("package.json",),
    "backend": ("pom.xml", "build.gradle", "build.gradle.kts"),
}


def ensure_inside(root: Path, candidate: Path) -> Path:
    resolved_root = root.resolve(strict=True)
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"path resolves outside workspace: {candidate}") from exc
    return resolved


def discover_preview(root: Path, manifest: WorkspaceManifest, max_depth: int = 1) -> dict[str, Any]:
    if max_depth != 1:
        raise ValueError("MVP discovery depth is exactly 1")
    confirmed = {module.path for module in manifest.modules}
    candidates = []
    for child in sorted(root.iterdir(), key=lambda path: path.name.lower()):
        if not child.is_dir() or not (child / ".git").exists():
            continue
        safe = ensure_inside(root, child)
        candidates.append({
            "path": safe.relative_to(root.resolve()).as_posix(),
            "suggested_kind": classify_module(safe),
            "confirmation": "confirmed" if child.name in confirmed else "required",
            "classification_evidence": classification_evidence(safe),
        })
    return {"version": 1, "candidates": candidates}
```

Classification is advisory. `package.json` alone suggests frontend only when it
contains a `scripts.build` or a dependency on React/Vue/Angular; otherwise use
`other`. Never open files outside the fixed marker set during discovery.

- [ ] **Step 2.4: Run tests and commit**

Run: `python tools/workspace_discovery/test_workspace_discovery.py DiscoveryTest -v`
Expected: `OK` (symlink test may be skipped on restricted Windows hosts).

```powershell
git add tools/workspace_discovery
git commit -m "feat: preview sibling methodology modules safely"
```

### Task 3: Per-module Git snapshot and inspector job envelopes

**Files:**
- Modify: `tools/workspace_discovery/discovery.py`
- Modify: `tools/workspace_discovery/test_workspace_discovery.py`

**Interfaces:**
- Produces: `git_state(path: Path) -> dict[str, Any]`.
- Produces: `build_snapshot(root: Path, manifest: WorkspaceManifest, dirty_policy: dict[str, str]) -> dict[str, Any]`.
- Produces: `build_inspector_jobs(snapshot: dict[str, Any], manifest: WorkspaceManifest, run_dir: Path) -> list[dict[str, Any]]`.

- [ ] **Step 3.1: Write failing tests**

```python
class SnapshotTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "orders" / ".git").mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    @patch.object(discovery, "run_command")
    def test_snapshot_records_each_repo_independently(self, run: Mock) -> None:
        run.side_effect = completed_git_outputs(
            head="abc123\n", branch="main\n", status=" M app.py\n", remote="ssh://git/orders\n"
        )
        manifest = manifest_object(modules=[module("orders", "orders", "backend")])
        snapshot = discovery.build_snapshot(self.root, manifest, {"orders": "working-tree"})
        state = snapshot["modules"]["orders"]
        self.assertEqual(state["commit"], "abc123")
        self.assertTrue(state["dirty"])
        self.assertEqual(state["dirty_policy"], "working-tree")

    def test_dirty_module_without_policy_blocks(self) -> None:
        with self.assertRaisesRegex(ValueError, "dirty policy required"):
            discovery.require_dirty_policy("orders", True, {})
```

- [ ] **Step 3.2: Verify failure**

Run: `python tools/workspace_discovery/test_workspace_discovery.py SnapshotTest -v`
Expected: FAIL because snapshot functions are missing.

- [ ] **Step 3.3: Implement Git state without shell strings**

Use `run_command` with argument arrays only:

```python
def git_state(path: Path) -> dict[str, Any]:
    commands = {
        "commit": ["git", "rev-parse", "HEAD"],
        "branch": ["git", "branch", "--show-current"],
        "status": ["git", "status", "--porcelain"],
        "remote": ["git", "remote", "get-url", "origin"],
    }
    values = {}
    for key, args in commands.items():
        result = run_command(args, cwd=path, timeout=15)
        if result.returncode != 0 and key != "remote":
            raise ValueError(f"cannot read git {key} for {path}: {result.stderr.strip()}")
        values[key] = result.stdout.strip() if result.returncode == 0 else None
    return {
        "commit": values["commit"], "branch": values["branch"] or None,
        "dirty": bool(values["status"]), "remote": values["remote"],
    }
```

Implement snapshot and job construction with the same boundary check:

```python
def require_dirty_policy(module_id: str, dirty: bool,
                         policies: dict[str, str]) -> str:
    if not dirty:
        return "clean"
    policy = policies.get(module_id)
    if policy not in {"working-tree", "HEAD"}:
        raise ValueError(f"dirty policy required for {module_id}")
    return policy


def build_snapshot(root: Path, manifest: WorkspaceManifest,
                   dirty_policy: dict[str, str]) -> dict[str, Any]:
    modules: dict[str, dict[str, Any]] = {}
    for module in manifest.modules:
        path = ensure_inside(root, root / module.path)
        state = git_state(path)
        policy = require_dirty_policy(module.module_id, state["dirty"], dirty_policy)
        modules[module.module_id] = {
            **state, "path": module.path, "kind": module.kind,
            "dirty_policy": policy,
        }
    canonical = json.dumps(modules, sort_keys=True, separators=(",", ":")).encode()
    return {
        "version": 1,
        "snapshot_id": hashlib.sha256(canonical).hexdigest(),
        "workspace_root": str(root.resolve()),
        "modules": modules,
    }


def build_inspector_jobs(snapshot: dict[str, Any], manifest: WorkspaceManifest,
                         run_dir: Path) -> list[dict[str, Any]]:
    jobs = []
    by_id = {module.module_id: module for module in manifest.modules}
    for module_id, state in sorted(snapshot["modules"].items()):
        module = by_id[module_id]
        if module.kind == "load-tests":
            continue
        jobs.append({
            "module_id": module_id,
            "module_path": str(Path(snapshot["workspace_root"]) / module.path),
            "kind": module.kind,
            "revision": state["commit"],
            "dirty_policy": state["dirty_policy"],
            "inspect": list(module.inspect),
            "exclude": list(module.exclude),
            "output": str(run_dir / "modules" / f"{module_id}-evidence.json"),
        })
    return jobs
```

The job envelope contains paths and selectors only; it never includes source
file contents.

- [ ] **Step 3.4: Run tests and commit**

Run: `python tools/workspace_discovery/test_workspace_discovery.py SnapshotTest -v`
Expected: `OK`.

```powershell
git add tools/workspace_discovery
git commit -m "feat: snapshot confirmed methodology modules"
```

### Task 4: CLI, documentation, and full verification

**Files:**
- Create: `tools/workspace_discovery/workspace_discovery.py`
- Create: `tools/workspace_discovery/README.md`
- Create: `docs/METHODOLOGY.md`
- Modify: `tools/workspace_discovery/test_workspace_discovery.py`

**Interfaces:**
- Produces CLI subcommands `preview` and `snapshot`.
- Produces JSON with stable ordering and UTF-8 encoding.

- [ ] **Step 4.1: Write failing CLI tests**

```python
class CliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.out = self.root / "out"
        self.out.mkdir()
        self.manifest = self.root / "workspace.yaml"
        self.manifest.write_text(
            "version: 1\nsystem: SHOP\nworkspace_root: .\n"
            "load_test_module: load-tests\nmodules: []\n"
            "write_policy:\n  allowed_modules: [load-tests]\n  sut_modules: read-only\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_preview_writes_json_without_mutating_manifest(self) -> None:
        before = self.manifest.read_bytes()
        code = workspace_discovery.main([
            "preview", "--manifest", str(self.manifest),
            "--out", str(self.out / "workspace-discovery.json"),
        ])
        self.assertEqual(code, 0)
        self.assertEqual(self.manifest.read_bytes(), before)
        self.assertTrue((self.out / "workspace-discovery.json").is_file())
```

- [ ] **Step 4.2: Verify failure**

Run: `python tools/workspace_discovery/test_workspace_discovery.py CliTest -v`
Expected: FAIL because CLI module is missing.

- [ ] **Step 4.3: Implement CLI**

```python
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Discover methodology workspace modules")
    sub = parser.add_subparsers(dest="command", required=True)
    preview = sub.add_parser("preview")
    preview.add_argument("--manifest", required=True, type=Path)
    preview.add_argument("--out", required=True, type=Path)
    snapshot = sub.add_parser("snapshot")
    snapshot.add_argument("--manifest", required=True, type=Path)
    snapshot.add_argument("--run-dir", required=True, type=Path)
    snapshot.add_argument("--dirty-policy", action="append", default=[],
                          metavar="MODULE=working-tree|HEAD")
    return parser
```

Return `0` on success, `2` on invalid manifest/path/dirty policy, and do not
catch unexpected programming errors. Write JSON atomically via a temporary
sibling file plus `Path.replace`.

- [ ] **Step 4.4: Document operator commands**

`tools/workspace_discovery/README.md` must show:

```powershell
python tools/workspace_discovery/workspace_discovery.py preview `
  --manifest systems/SHOP/workspace.yaml `
  --out systems/SHOP/methodology-runs/RUN-001/workspace-discovery.json

python tools/workspace_discovery/workspace_discovery.py snapshot `
  --manifest systems/SHOP/workspace.yaml `
  --run-dir systems/SHOP/methodology-runs/RUN-001 `
  --dirty-policy orders-backend=HEAD
```

Create `docs/METHODOLOGY.md` with the artifact boundary, workspace layout,
hybrid confirmation rule, and explicit statement that this phase does not read
Confluence or generate MNT text.

- [ ] **Step 4.5: Run full verification and commit**

Run:

```powershell
python tools/workspace_discovery/test_workspace_discovery.py -v
python -m pytest tools/_shared/test_common.py tools/workspace_discovery/test_workspace_discovery.py -q
```

Expected: all tests pass; no SUT file changes.

```powershell
git add tools/workspace_discovery docs/METHODOLOGY.md
git commit -m "docs: add methodology workspace discovery workflow"
```

## Phase 3a completion gate

- `preview` never adds a module to `workspace.yaml`.
- `snapshot` refuses unconfirmed, escaping, missing-required, or dirty-without-policy modules.
- Each confirmed module has its own commit/branch/dirty record and inspector job.
- Tests pass on Windows paths and a non-Git workspace root.
- The tool writes only its requested output paths inside the load-test repository.

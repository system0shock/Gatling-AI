# Methodology MVP Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the MNT MVP with a simple, separately approved Confluence publication flow and no further work on deferred hardening or selective refresh.

**Architecture:** Existing `create` and `update-local` workflows continue to recollect every confirmed source and produce a locally approved `methodology.md`. A small deterministic publish guard prepares the Confluence diff and binds approval to the fixed page version and local MNT hash; a least-privilege publisher performs the host-supplied MCP update only after validation.

**Tech Stack:** Python 3.11+ stdlib, `unittest`, Markdown Gigacode agents/skills, host-supplied Confluence MCP capabilities.

## Global Constraints

- `methodology.md` remains the permanent system-level document; scenarios, concrete test data, and run protocols/results remain separate.
- `create` and `update-local` recollect every confirmed repository and Confluence source; do not implement selective refresh.
- Do not modify or extend `tools/methodology_refresh`, CAS/symlink hardening, the custom diff parser, historical-manifest rules, or extended Confluence recovery.
- Local MNT approval and Confluence publication approval remain separate user actions.
- MVP publication has exactly three required rejection cases: missing approval, changed local MNT, and changed Confluence page version.
- The target page ID comes from the previously confirmed Confluence snapshot; the publisher never searches for or selects another page.
- Only the publisher role receives a host-supplied Confluence write capability; do not invent concrete MCP tool names in the package.
- Add no runtime dependencies.
- Findings outside this scope are recorded in `docs/METHODOLOGY-DEFERRED.md`, not implemented.

---

### Task 1: Minimal Confluence publish guard

**Files:**
- Create: `tools/methodology_publish/__init__.py`
- Create: `tools/methodology_publish/methodology_publish.py`
- Create: `tools/methodology_publish/test_methodology_publish.py`
- Create: `tools/methodology_publish/README.md`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `prepare_publish(methodology: Path, page_snapshot: dict, out_dir: Path) -> PublishDescriptor`.
- Produces: `record_publish_approval(descriptor: PublishDescriptor, approved_by: str, out: Path) -> dict`.
- Produces: `validate_publish(methodology: Path, fresh_page_snapshot: dict, approval_path: Path) -> PublishDescriptor`.
- Produces CLI subcommands `prepare`, `approve`, and `validate`.
- Writes only `confluence.patch`, `publish-descriptor.json`, and `publish-approval.json` under the supplied run directory.

- [ ] **Step 1: Write the four MVP behavior tests**

```python
class PublishGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).parent / ".test-fixtures" / self._testMethodName
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)
        self.methodology = self.root / "methodology.md"
        self.methodology.write_text("# MNT\n", encoding="utf-8")

    def snapshot(self, version: int = 7) -> dict:
        return {
            "page_id": "123",
            "version": version,
            "body_markdown": "# Existing MNT\n",
        }

    def approve(self) -> Path:
        descriptor = publish.prepare_publish(self.methodology, self.snapshot(), self.root)
        approval = self.root / "publish-approval.json"
        publish.record_publish_approval(descriptor, "v.salnikov", approval)
        return approval

    def test_happy_path_validates_fixed_page_and_local_hash(self) -> None:
        approval = self.approve()
        descriptor = publish.validate_publish(self.methodology, self.snapshot(), approval)
        self.assertEqual(descriptor.page_id, "123")
        self.assertTrue((self.root / "confluence.patch").is_file())

    def test_missing_approval_blocks(self) -> None:
        with self.assertRaises(FileNotFoundError):
            publish.validate_publish(self.methodology, self.snapshot(), self.root / "missing.json")

    def test_changed_local_methodology_blocks(self) -> None:
        approval = self.approve()
        self.methodology.write_text("# Changed MNT\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "local methodology changed"):
            publish.validate_publish(self.methodology, self.snapshot(), approval)

    def test_changed_page_version_blocks(self) -> None:
        approval = self.approve()
        with self.assertRaisesRegex(ValueError, "page version changed"):
            publish.validate_publish(self.methodology, self.snapshot(version=8), approval)
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python tools/methodology_publish/test_methodology_publish.py -v`

Expected: FAIL because `tools/methodology_publish` does not exist.

- [ ] **Step 3: Implement the minimal descriptor and three guards**

```python
@dataclass(frozen=True)
class PublishDescriptor:
    page_id: str
    expected_page_version: int
    methodology_sha256: str
    patch_sha256: str


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_string(mapping: dict, key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value


def require_int(mapping: dict, key: str) -> int:
    value = mapping.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{key} must be a positive integer")
    return value


def write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def descriptor_from_mapping(mapping: dict) -> PublishDescriptor:
    return PublishDescriptor(
        page_id=require_string(mapping, "page_id"),
        expected_page_version=require_int(mapping, "expected_page_version"),
        methodology_sha256=require_string(mapping, "methodology_sha256"),
        patch_sha256=require_string(mapping, "patch_sha256"),
    )


def prepare_publish(methodology: Path, page_snapshot: dict, out_dir: Path) -> PublishDescriptor:
    page_id = require_string(page_snapshot, "page_id")
    version = require_int(page_snapshot, "version")
    before = require_string(page_snapshot, "body_markdown")
    after = methodology.read_text(encoding="utf-8")
    patch_text = "".join(difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"confluence:{page_id}@{version}",
        tofile=str(methodology),
    ))
    out_dir.mkdir(parents=True, exist_ok=True)
    patch_path = out_dir / "confluence.patch"
    patch_path.write_text(patch_text, encoding="utf-8")
    descriptor = PublishDescriptor(
        page_id=page_id,
        expected_page_version=version,
        methodology_sha256=sha256_path(methodology),
        patch_sha256=sha256_path(patch_path),
    )
    write_json(out_dir / "publish-descriptor.json", asdict(descriptor))
    return descriptor


def record_publish_approval(descriptor: PublishDescriptor, approved_by: str,
                            out: Path) -> dict:
    if not approved_by.strip():
        raise ValueError("approved_by must be non-empty")
    approval = {
        **asdict(descriptor),
        "approved_by": approved_by,
        "approved_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    write_json(out, approval)
    return approval


def validate_publish(methodology: Path, fresh_page_snapshot: dict,
                     approval_path: Path) -> PublishDescriptor:
    approval = json.loads(approval_path.read_text(encoding="utf-8"))
    descriptor = descriptor_from_mapping(approval)
    if sha256_path(methodology) != descriptor.methodology_sha256:
        raise ValueError("local methodology changed after approval")
    if require_string(fresh_page_snapshot, "page_id") != descriptor.page_id:
        raise ValueError("target page changed")
    if require_int(fresh_page_snapshot, "version") != descriptor.expected_page_version:
        raise ValueError("page version changed after approval")
    return descriptor
```

The CLI parser has three subcommands with the exact flags exercised below:
`prepare --methodology --page-snapshot --out-dir`,
`approve --descriptor --approved-by --out`, and
`validate --methodology --page-snapshot --approval`. `main()` catches
`FileNotFoundError`, `ValueError`, and JSON decoding errors, prints one redacted
error line, and exits `2`; success exits `0`.

- [ ] **Step 4: Add CLI coverage without new rejection classes**

```python
def test_cli_prepare_approve_validate_happy_path(self) -> None:
    page_path = self.root / "page.json"
    page_path.write_text(json.dumps(self.snapshot()), encoding="utf-8")
    self.assertEqual(publish.main([
        "prepare", "--methodology", str(self.methodology),
        "--page-snapshot", str(page_path),
        "--out-dir", str(self.root),
    ]), 0)
    self.assertEqual(publish.main([
        "approve", "--descriptor", str(self.root / "publish-descriptor.json"),
        "--approved-by", "v.salnikov",
        "--out", str(self.root / "publish-approval.json"),
    ]), 0)
    self.assertEqual(publish.main([
        "validate", "--methodology", str(self.methodology),
        "--page-snapshot", str(page_path),
        "--approval", str(self.root / "publish-approval.json"),
    ]), 0)
```

- [ ] **Step 5: Verify and commit Task 1**

Run:

```powershell
python tools/methodology_publish/test_methodology_publish.py -v
python -m py_compile tools/methodology_publish/methodology_publish.py
git diff --check
```

Expected: five tests pass; compilation and diff check exit `0`.

```powershell
git add tools/methodology_publish .gitignore
git commit -m "feat: add minimal methodology publish guard"
```

### Task 2: Least-privilege publisher and MVP workflow

**Files:**
- Create: `.gigacode/agents/mnt-confluence-publisher.md`
- Modify: `.gigacode/skills/manage-methodology/SKILL.md`
- Modify: `.gigacode/commands/manage-methodology.md`
- Modify: `.gigacode/test_gigacode_package.py`
- Modify: `.gigacode/README.md`
- Modify: `GIGACODE.md`
- Modify: `docs/METHODOLOGY.md`

**Interfaces:**
- Adds `publish` to the existing `create|update-local` actions.
- Publisher consumes the final local MNT, the previously confirmed page snapshot, and `publish-approval.json`.
- Publisher returns inline `{status, page_id, page_version}`; it creates no repository artifact.
- Host overlay supplies page-read and page-update capabilities; package files contain no concrete MCP tool names.

- [ ] **Step 1: Add failing package contract tests**

```python
def test_mnt_publisher_is_the_only_confluence_writer(self) -> None:
    path = GIGACODE / "agents" / "mnt-confluence-publisher.md"
    self.assertTrue(path.is_file())
    text = path.read_text(encoding="utf-8").lower()
    for marker in (
        "read final local methodology",
        "fetch the same confirmed page id",
        "validate_publish",
        "stop without update",
        "host-supplied page-update capability",
        "return inline",
    ):
        self.assertIn(marker, text)
    self.assertIn("no concrete confluence mcp tool names", text)


def test_manage_methodology_publish_order_is_explicit(self) -> None:
    text = (GIGACODE / "skills" / "manage-methodology" / "SKILL.md").read_text(
        encoding="utf-8"
    ).lower()
    publish = text[text.index("## publish") :]
    markers = (
        "canonical methodology is green",
        "confirmed page snapshot",
        "prepare publish",
        "show confluence.patch",
        "wait for explicit publish approval",
        "record publish approval",
        "dispatch mnt-confluence-publisher",
    )
    positions = [publish.index(marker) for marker in markers]
    self.assertEqual(positions, sorted(positions))
    self.assertNotIn("selective refresh", publish)
```

- [ ] **Step 2: Run package tests and verify RED**

Run: `python .gigacode/test_gigacode_package.py -v`

Expected: FAIL because `mnt-confluence-publisher.md` and the `publish` action are absent.

- [ ] **Step 3: Define the publisher's exact bounded sequence**

The agent definition contains this sequence and no additional behavior:

```markdown
1. Read final local methodology.
2. Read the confirmed page ID from the supplied page snapshot.
3. Fetch the same confirmed page ID through the host-supplied page-read capability.
4. Run `validate_publish` with the fresh snapshot and supplied approval.
5. On any validation error, stop without update and return inline `blocked`.
6. Invoke the host-supplied page-update capability with that page ID and the exact local MNT body.
7. Return inline `{status: published, page_id, page_version}` from the MCP result.
```

It must state: no page search, no title/parent/label/permission changes, no
repository writes, no retry after an ambiguous update result, and no concrete
Confluence MCP tool names.

- [ ] **Step 4: Extend the skill and slash command with only `publish`**

The `publish` action performs:

```markdown
1. Require canonical methodology is green.
2. Use the confirmed page snapshot; never search for another page.
3. Run `methodology_publish prepare` and show `confluence.patch`.
4. Wait for explicit publish approval.
5. Run `methodology_publish approve` for that descriptor.
6. Dispatch `mnt-confluence-publisher` with the local MNT, snapshot, and approval paths.
7. Display the publisher's inline result.
```

`update-local` remains a full recollection of every confirmed source. Do not add
a `refresh` action and do not invoke `tools/methodology_refresh`.

- [ ] **Step 5: Update concise user documentation**

Document only:

- `create`, `update-local`, and `publish`;
- two separate approvals;
- fixed target page;
- full recollection for updates;
- three publish rejection cases;
- deferred mechanisms link.

- [ ] **Step 6: Verify and commit Task 2**

Run:

```powershell
python .gigacode/test_gigacode_package.py -v
python tools/methodology_publish/test_methodology_publish.py -v
git diff --check
```

Expected: package suite and five publish tests pass; diff check exits `0`.

```powershell
git add .gigacode GIGACODE.md docs/METHODOLOGY.md
git commit -m "feat: publish approved methodologies through host MCP"
```

## MVP Completion Gate

- `update-local` performs a full recollection and never invokes selective refresh.
- The exact Confluence diff is shown before a separate publish approval.
- Missing approval, local MNT drift, or page-version drift causes `blocked` with no MCP update.
- Only `mnt-confluence-publisher` can request the host-supplied page-update capability.
- No deferred mechanism is extended or added to MVP acceptance criteria.

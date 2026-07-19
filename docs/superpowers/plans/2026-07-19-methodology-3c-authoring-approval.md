# Methodology 3c: Authoring, Quality Gate, and Approval-Bound Patch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply content-bound approval to the discovered `workspace.yaml`, then generate, validate, approve, and atomically install an exact local MNT candidate.

**Architecture:** An author subagent receives the template, current MNT, resolved evidence, and manual confirmations—never raw code or Confluence pages. Deterministic tooling computes candidate/patch hashes, creates approval records after user confirmation, validates the MNT quality contract, and atomically installs only the approved candidate. The orchestrator skill owns dialogue and dispatches fresh subagents.

**Tech Stack:** Python 3.11+ stdlib (`difflib`, `hashlib`, `json`, `os`, `tempfile`), jsonschema, `unittest`, Gigacode Markdown skills/agents/commands.

## Global Constraints

- Requires Phase 3b `resolved-evidence.json`, gaps, coverage, and manual confirmations.
- `methodology.md` is the permanent system-level document; scenarios, test data, and run protocols remain separate.
- The author writes only `methodology.candidate.md`, `methodology.patch`, source map, and summary in the run directory.
- Neither `workspace.yaml` nor `methodology.md` changes before explicit approval of its exact diff.
- Workspace-manifest approval happens before module snapshot and collector dispatch.
- Approval is bound to SHA-256 of base file, candidate file, and patch.
- Any change to base, candidate, or patch invalidates approval.
- Patch application writes only inside the load-test repository and is atomic.
- A `blocked` quality report prevents an approval request.
- Confluence publication is not implemented in this phase and requires a later, separate approval.

---

## Final file structure

```text
schemas/methodology-approval.schema.json
schemas/methodology-quality-report.schema.json
tools/methodology_authoring/__init__.py
tools/methodology_authoring/methodology_authoring.py
tools/methodology_authoring/test_methodology_authoring.py
tools/methodology_authoring/README.md
tools/methodology_quality_gate/__init__.py
tools/methodology_quality_gate/fixtures.py
tools/methodology_quality_gate/methodology_quality_gate.py
tools/methodology_quality_gate/test_methodology_quality_gate.py
tools/methodology_quality_gate/README.md
.gigacode/skills/manage-methodology/SKILL.md
.gigacode/skills/manage-methodology/templates/methodology-template.md
.gigacode/agents/mnt-author.md
.gigacode/agents/mnt-validator.md
.gigacode/commands/manage-methodology.md
.gigacode/test_gigacode_package.py
.gigacode/README.md
GIGACODE.md
docs/METHODOLOGY.md
```

### Task 1: Stable MNT template and author subagent

**Files:**
- Create: `.gigacode/skills/manage-methodology/templates/methodology-template.md`
- Create: `.gigacode/agents/mnt-author.md`
- Modify: `.gigacode/test_gigacode_package.py`
- Modify: `docs/METHODOLOGY.md`

**Interfaces:**
- Author consumes `current_methodology`, `resolved_evidence`, `manual_confirmations`, `section_coverage`, and template paths.
- Author produces candidate Markdown, `change-summary.md`, and `methodology-source-map.json`.

- [ ] **Step 1.1: Add failing structural tests**

```python
REQUIRED_METHODOLOGY_HEADINGS = (
    "Паспорт документа", "Назначение и область тестирования",
    "Описание системы и функциональности", "Архитектура",
    "Реестр интеграций", "Реестр тестируемых интерфейсов",
    "Пользовательские и технические потоки", "Модель нагрузки",
    "Виды тестов", "SLA, SLO и критерии приемки",
    "Тестовый стенд", "Требования к тестовым данным",
    "Наблюдаемость и диагностика", "Порядок проведения тестов",
    "Риски, ограничения и допущения", "Артефакты и отчетность",
    "Актуализация методики",
)

def test_methodology_template_has_all_headings(self) -> None:
    template = (GIGACODE / "skills" / "manage-methodology" / "templates" /
                "methodology-template.md").read_text(encoding="utf-8")
    for heading in REQUIRED_METHODOLOGY_HEADINGS:
        self.assertIn(f"## {heading}", template)
```

Also add `mnt-author` to the required agent set and assert its frontmatter
disallows `write_file` and `edit`; it may write candidate artifacts only through
an explicitly scoped run-directory mechanism described in its prompt.

- [ ] **Step 1.2: Verify failure**

Run: `python .gigacode/test_gigacode_package.py -v`
Expected: FAIL for missing template and `mnt-author`.

- [ ] **Step 1.3: Create the template**

The template contains the 17 exact `##` headings above. Under every heading add
a short HTML comment declaring accepted entity types, for example:

```markdown
## Реестр интеграций

<!-- evidence: integration; required-fields: protocol, source, target, strategy -->

| ID | Источник → получатель | Назначение | Протокол | Контракт | Стратегия | Источник |
|---|---|---|---|---|---|---|
```

Do not put `TBD`, `TODO`, guessed SLA values, scenario data, or run results in
the template.

- [ ] **Step 1.4: Create the author agent contract**

The prompt must require:

1. Read only the five supplied input artifacts.
2. Preserve manually curated text unless evidence explicitly changes it.
3. Cite evidence IDs in `methodology-source-map.json`, not as noisy inline IDs.
4. Mark allowed unknowns as limitations; never invent a value.
5. Write outputs only under the run directory.
6. Return a compact envelope and never apply the patch.

The source map shape is:

```json
{
  "version": 1,
  "sections": {
    "Реестр интеграций": ["integration.payment-http.protocol"],
    "SLA, SLO и критерии приемки": ["sla.checkout.threshold"]
  }
}
```

- [ ] **Step 1.5: Run tests and commit**

Run: `python .gigacode/test_gigacode_package.py -v`
Expected: all package tests pass.

```powershell
git add .gigacode/skills/manage-methodology/templates .gigacode/agents/mnt-author.md .gigacode/test_gigacode_package.py docs/METHODOLOGY.md
git commit -m "feat: add methodology template and author agent"
```

### Task 2: Deterministic patch and approval engine

**Files:**
- Create: `schemas/methodology-approval.schema.json`
- Create: `tools/methodology_authoring/__init__.py`
- Create: `tools/methodology_authoring/methodology_authoring.py`
- Create: `tools/methodology_authoring/test_methodology_authoring.py`
- Create: `tools/methodology_authoring/README.md`

**Interfaces:**
- Produces: `prepare(kind: str, base: Path, candidate: Path, patch: Path) -> PatchDescriptor`.
- Produces: `record_approval(descriptor, approved_by, out) -> dict`.
- Produces: `validate_approval(base, candidate, patch, approval) -> None`.
- Produces: `apply_approved_candidate(...) -> None`.
- Produces CLI `prepare`, `record-approval`, and `apply`.

- [ ] **Step 2.1: Write failing hash/approval tests**

```python
class ApprovalTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.base = root / "methodology.md"
        self.candidate = root / "methodology.candidate.md"
        self.patch = root / "methodology.patch"
        self.approval = root / "approval.json"
        self.missing = root / "missing-approval.json"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_patch_is_stable_and_bound_to_base_and_candidate(self) -> None:
        self.base.write_text("# MNT\nold\n", encoding="utf-8")
        self.candidate.write_text("# MNT\nnew\n", encoding="utf-8")
        descriptor = authoring.prepare("methodology-patch", self.base, self.candidate, self.patch)
        self.assertEqual(descriptor.patch_sha256, authoring.sha256_path(self.patch))
        self.assertIn("-old", self.patch.read_text(encoding="utf-8"))
        self.assertIn("+new", self.patch.read_text(encoding="utf-8"))

    def test_changed_base_invalidates_approval(self) -> None:
        self.base.write_text("# MNT\nold\n", encoding="utf-8")
        self.candidate.write_text("# MNT\nnew\n", encoding="utf-8")
        descriptor = authoring.prepare("methodology-patch", self.base, self.candidate, self.patch)
        approval = authoring.record_approval(descriptor, "v.salnikov", self.approval)
        self.base.write_text("concurrent edit", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "base_sha256"):
            authoring.validate_approval(self.base, self.candidate, self.patch, approval)

    def test_apply_without_approval_does_not_change_base(self) -> None:
        before = self.base.read_bytes()
        with self.assertRaises(FileNotFoundError):
            authoring.apply_approved_candidate(self.base, self.candidate, self.patch, self.missing)
        self.assertEqual(self.base.read_bytes(), before)

    def test_workspace_manifest_uses_a_distinct_approval_kind(self) -> None:
        self.base.write_text("modules: []\n", encoding="utf-8")
        self.candidate.write_text("modules:\n  - id: orders\n", encoding="utf-8")
        descriptor = authoring.prepare("workspace-manifest", self.base, self.candidate, self.patch)
        approval = authoring.record_approval(descriptor, "v.salnikov", self.approval)
        self.assertEqual(approval["kind"], "workspace-manifest")
        authoring.apply_approved_candidate(self.base, self.candidate, self.patch, self.approval)
        self.assertEqual(self.base.read_bytes(), self.candidate.read_bytes())
```

- [ ] **Step 2.2: Verify failure**

Run: `python tools/methodology_authoring/test_methodology_authoring.py -v`
Expected: FAIL because module is missing.

- [ ] **Step 2.3: Implement stable preparation and schema**

```python
@dataclass(frozen=True)
class PatchDescriptor:
    kind: str
    base_path: str
    candidate_path: str
    base_sha256: str
    candidate_sha256: str
    patch_sha256: str


def prepare(kind: str, base: Path, candidate: Path, patch: Path) -> PatchDescriptor:
    before = base.read_text(encoding="utf-8").splitlines(keepends=True) if base.exists() else []
    after = candidate.read_text(encoding="utf-8").splitlines(keepends=True)
    diff = "".join(difflib.unified_diff(before, after, fromfile=str(base), tofile=str(candidate)))
    atomic_write_text(patch, diff)
    return PatchDescriptor(kind, str(base), str(candidate), sha256_path(base),
                           sha256_path(candidate), sha256_path(patch))
```

For a missing base use the literal hash of empty bytes. The approval schema
requires `version`, `kind` (`workspace-manifest` or `methodology-patch`), three hashes, `approved_by`, and
UTC `approved_at`.

- [ ] **Step 2.4: Implement exact atomic apply**

```python
def apply_approved_candidate(base: Path, candidate: Path, patch: Path, approval_path: Path) -> None:
    approval = json.loads(approval_path.read_text(encoding="utf-8"))
    validate_approval(base, candidate, patch, approval)
    base.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=base.name + ".", dir=base.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(candidate.read_bytes())
        os.replace(temp_name, base)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
```

Before replacement verify that the unified diff freshly generated from the
current base and candidate has the approved patch hash. Resolve base and
candidate paths and reject writes outside the configured load-test root.

- [ ] **Step 2.5: Add CLI tests, run, and commit**

Run: `python tools/methodology_authoring/test_methodology_authoring.py -v`
Expected: all tests pass, including concurrent-edit and wrong-hash cases.

```powershell
git add schemas/methodology-approval.schema.json tools/methodology_authoring
git commit -m "feat: bind methodology patches to user approval"
```

### Task 3: Deterministic MNT quality gate

**Files:**
- Create: `schemas/methodology-quality-report.schema.json`
- Create: `tools/methodology_quality_gate/__init__.py`
- Create: `tools/methodology_quality_gate/fixtures.py`
- Create: `tools/methodology_quality_gate/methodology_quality_gate.py`
- Create: `tools/methodology_quality_gate/test_methodology_quality_gate.py`
- Create: `tools/methodology_quality_gate/README.md`

**Interfaces:**
- Produces: `run_gate(candidate, evidence, coverage, source_map, patch, base) -> GateReport`.
- Writes `methodology-quality-report.json` and `.md`.
- Exit codes: `0` passed, `1` passed_with_warnings, `2` blocked.

- [ ] **Step 3.1: Write failing required-section, source, and secret tests**

```python
class MethodologyGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def assert_rule(self, report, rule: str, severity: str = "blocking") -> None:
        self.assertTrue(any(item.rule == rule and item.severity == severity for item in report.findings))

    def test_missing_required_section_blocks(self) -> None:
        report = gate.run_gate(**write_gate_fixture(self.root, omit="Архитектура"))
        self.assertEqual(report.status, "blocked")
        self.assert_rule(report, "required-section")

    def test_sla_without_source_map_entry_blocks(self) -> None:
        report = gate.run_gate(**write_gate_fixture(self.root, sla="p95 <= 500 ms", source_map={}))
        self.assert_rule(report, "sla-source")

    def test_secret_like_value_blocks(self) -> None:
        report = gate.run_gate(**write_gate_fixture(self.root, extra="Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig"))
        self.assert_rule(report, "secret-detection")

    def test_scenario_data_section_blocks_scope_leak(self) -> None:
        report = gate.run_gate(**write_gate_fixture(self.root, extra="users.csv: login,password"))
        self.assert_rule(report, "artifact-boundary")
```

Create `tools/methodology_quality_gate/fixtures.py`; import `write_gate_fixture` explicitly in the test:

```python
import json
from pathlib import Path

HEADINGS = (
    "Паспорт документа", "Назначение и область тестирования",
    "Описание системы и функциональности", "Архитектура", "Реестр интеграций",
    "Реестр тестируемых интерфейсов", "Пользовательские и технические потоки",
    "Модель нагрузки", "Виды тестов", "SLA, SLO и критерии приемки",
    "Тестовый стенд", "Требования к тестовым данным", "Наблюдаемость и диагностика",
    "Порядок проведения тестов", "Риски, ограничения и допущения",
    "Артефакты и отчетность", "Актуализация методики",
    )


def write_gate_fixture(root: Path, *, omit: str | None = None, extra: str = "",
                       sla: str | None = None, source_map: dict | None = None) -> dict[str, Path]:
    paths = {name: root / name for name in (
        "candidate.md", "resolved.json", "coverage.json", "source-map.json",
        "methodology.patch", "base.md")}
    body = ["# МНТ"]
    for heading in HEADINGS:
        if heading != omit:
            body.extend(["", f"## {heading}", "", sla if heading.startswith("SLA") and sla else "Нет подтвержденных данных."])
    if extra:
        body.extend(["", extra])
    paths["candidate.md"].write_text("\n".join(body) + "\n", encoding="utf-8")
    paths["base.md"].write_text("# МНТ\n", encoding="utf-8")
    paths["methodology.patch"].write_text("fixture patch\n", encoding="utf-8")
    paths["resolved.json"].write_text(json.dumps({"entities": [], "blocking_gaps": []}), encoding="utf-8")
    paths["coverage.json"].write_text(json.dumps({"sections": {h: "covered" for h in HEADINGS}}), encoding="utf-8")
    mapped = source_map if source_map is not None else {h: ["fact.fixture"] for h in HEADINGS}
    paths["source-map.json"].write_text(json.dumps({"version": 1, "sections": mapped}), encoding="utf-8")
    return {"candidate": paths["candidate.md"], "resolved_evidence": paths["resolved.json"],
            "coverage": paths["coverage.json"], "source_map": paths["source-map.json"],
            "patch": paths["methodology.patch"], "base": paths["base.md"]}
```

- [ ] **Step 3.2: Verify failure**

Run: `python tools/methodology_quality_gate/test_methodology_quality_gate.py -v`
Expected: FAIL.

- [ ] **Step 3.3: Implement explicit checks**

Use the existing `Finding` dataclass. Implement these check IDs:

```python
@dataclass(frozen=True)
class GateReport:
    status: str
    findings: tuple[Finding, ...]
    checks: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class GateContext:
    candidate_path: Path
    candidate_text: str
    resolved_evidence: dict[str, Any]
    coverage: dict[str, Any]
    source_map: dict[str, Any]
    patch_text: str
    base_path: Path
    base_text: str


CHECKS = (
    "required-section", "placeholder-scan", "source-map-schema",
    "sla-source", "endpoint-source", "integration-source",
    "blocking-conflicts", "module-coverage", "secret-detection",
    "artifact-boundary", "patch-scope", "snapshot-freshness",
)


CHECK_FUNCTIONS: dict[str, Callable[[GateContext], tuple[Finding, ...]]] = {
    "required-section": check_required_sections,
    "placeholder-scan": check_placeholders,
    "source-map-schema": check_source_map_schema,
    "sla-source": check_sla_sources,
    "endpoint-source": check_endpoint_sources,
    "integration-source": check_integration_sources,
    "blocking-conflicts": check_blocking_conflicts,
    "module-coverage": check_module_coverage,
    "secret-detection": check_secrets,
    "artifact-boundary": check_artifact_boundaries,
    "patch-scope": check_patch_scope,
    "snapshot-freshness": check_snapshot_freshness,
}


def load_gate_context(candidate: Path, resolved_evidence: Path, coverage: Path,
                      source_map: Path, patch: Path, base: Path) -> GateContext:
    return GateContext(
        candidate_path=candidate,
        candidate_text=candidate.read_text(encoding="utf-8"),
        resolved_evidence=json.loads(resolved_evidence.read_text(encoding="utf-8")),
        coverage=json.loads(coverage.read_text(encoding="utf-8")),
        source_map=json.loads(source_map.read_text(encoding="utf-8")),
        patch_text=patch.read_text(encoding="utf-8"),
        base_path=base,
        base_text=base.read_text(encoding="utf-8") if base.exists() else "",
    )


def run_gate(*, candidate: Path, resolved_evidence: Path, coverage: Path,
             source_map: Path, patch: Path, base: Path) -> GateReport:
    context = load_gate_context(candidate, resolved_evidence, coverage, source_map, patch, base)
    findings: list[Finding] = []
    checks: list[dict[str, Any]] = []
    for check_id in CHECKS:
        check_findings = CHECK_FUNCTIONS[check_id](context)
        findings.extend(check_findings)
        checks.append({"id": check_id, "status": "passed" if not check_findings else "failed",
                       "finding_count": len(check_findings)})
    status = "blocked" if any(f.severity == "blocking" for f in findings) else (
        "passed_with_warnings" if findings else "passed")
    return GateReport(status, tuple(findings), tuple(checks))
```

Implement the checks as pure functions. Section presence is derived from the
validated coverage contract, so the fixture and runtime use the same 17 names:

```python
NO_DATA = "Нет подтвержденных данных."
SECRET_PATTERNS = (
    re.compile(r"(?i)authorization:\s*bearer\s+\S+"),
    re.compile(r"(?i)(password|client_secret|api[_-]?key)\s*[:=]\s*\S+"),
)


def finding(rule: str, message: str, severity: str = "blocking") -> tuple[Finding, ...]:
    return (Finding(rule=rule, message=message, severity=severity),)


def markdown_sections(text: str) -> dict[str, str]:
    matches = list(re.finditer(r"(?m)^##\s+(.+?)\s*$", text))
    return {
        match.group(1): text[match.end():matches[index + 1].start() if index + 1 < len(matches) else len(text)].strip()
        for index, match in enumerate(matches)
    }


def check_required_sections(ctx: GateContext) -> tuple[Finding, ...]:
    actual = markdown_sections(ctx.candidate_text)
    missing = sorted(set(ctx.coverage["sections"]) - set(actual))
    return finding("required-section", f"missing sections: {', '.join(missing)}") if missing else ()


def check_placeholders(ctx: GateContext) -> tuple[Finding, ...]:
    forbidden = re.compile(r"(?i)\b(TBD|TODO|FIXME)\b|\?\?\?|\|\s*\|")
    return finding("placeholder-scan", "candidate contains placeholder content") if forbidden.search(ctx.candidate_text) else ()


def check_source_map_schema(ctx: GateContext) -> tuple[Finding, ...]:
    valid = ctx.source_map.get("version") == 1 and isinstance(ctx.source_map.get("sections"), dict)
    return () if valid else finding("source-map-schema", "source map must contain version 1 and sections")


def check_section_sources(ctx: GateContext, heading_fragment: str, rule: str) -> tuple[Finding, ...]:
    sections = markdown_sections(ctx.candidate_text)
    heading = next((name for name in sections if heading_fragment.casefold() in name.casefold()), None)
    if heading is None:
        return ()
    body = sections[heading]
    has_claim = bool(body and body != NO_DATA)
    mapped = ctx.source_map.get("sections", {}).get(heading, [])
    return finding(rule, f"{heading} contains claims without evidence IDs") if has_claim and not mapped else ()


def check_sla_sources(ctx: GateContext) -> tuple[Finding, ...]:
    return check_section_sources(ctx, "SLA", "sla-source")


def check_endpoint_sources(ctx: GateContext) -> tuple[Finding, ...]:
    return check_section_sources(ctx, "интерфейс", "endpoint-source")


def check_integration_sources(ctx: GateContext) -> tuple[Finding, ...]:
    return check_section_sources(ctx, "интеграц", "integration-source")


def check_blocking_conflicts(ctx: GateContext) -> tuple[Finding, ...]:
    gaps = ctx.resolved_evidence.get("blocking_gaps", [])
    return finding("blocking-conflicts", f"{len(gaps)} blocking evidence gaps") if gaps else ()


def check_module_coverage(ctx: GateContext) -> tuple[Finding, ...]:
    sections = ctx.coverage.get("sections", {})
    incomplete = sorted(name for name, status in sections.items() if status in {"missing", "partial"})
    return finding("module-coverage", f"incomplete sections: {', '.join(incomplete)}") if incomplete else ()


def check_secrets(ctx: GateContext) -> tuple[Finding, ...]:
    hits = []
    for line_number, line in enumerate(ctx.candidate_text.splitlines(), start=1):
        if any(pattern.search(line) for pattern in SECRET_PATTERNS):
            hits.append(Finding("secret-detection", f"secret-like value at line {line_number}", "blocking"))
    return tuple(hits)


def check_artifact_boundaries(ctx: GateContext) -> tuple[Finding, ...]:
    concrete_data = re.search(r"(?im)^\s*(users\.csv:|run[_ -]?id\s*[:=]|protocol[_ -]?id\s*[:=])", ctx.candidate_text)
    return finding("artifact-boundary", "scenario data or run protocol content belongs in a separate artifact") if concrete_data else ()


def check_patch_scope(ctx: GateContext) -> tuple[Finding, ...]:
    headers = [line[4:] for line in ctx.patch_text.splitlines() if line.startswith(("--- ", "+++ "))]
    allowed = {str(ctx.base_path), str(ctx.candidate_path), "/dev/null"}
    invalid = [header for header in headers if header.split("\t", 1)[0] not in allowed]
    return finding("patch-scope", "patch contains a path outside base/candidate") if invalid else ()


def check_snapshot_freshness(ctx: GateContext) -> tuple[Finding, ...]:
    snapshot = ctx.source_map.get("workspace_snapshot", {})
    return finding("snapshot-freshness", "workspace snapshot is stale") if snapshot.get("stale") is True else ()
```

The secret check reports only rule ID and line number; it never echoes the
matched value. The placeholder scan intentionally permits documented path
metavariables `<SYSTEM>`, `<RUN-ID>`, and `<MODULE-ID>`.

- [ ] **Step 3.4: Implement reports and CLI**

The JSON report contains `version`, `status`, `candidate`, `candidate_sha256`,
`checks`, `findings`, and `generated_at`. Markdown lists counts and redacted
findings. CLI:

```powershell
python tools/methodology_quality_gate/methodology_quality_gate.py `
  --candidate systems/SHOP/methodology-runs/RUN-001/methodology.candidate.md `
  --resolved-evidence systems/SHOP/methodology-runs/RUN-001/resolved-evidence.json `
  --coverage systems/SHOP/methodology-runs/RUN-001/section-coverage.json `
  --source-map systems/SHOP/methodology-runs/RUN-001/methodology-source-map.json `
  --base systems/SHOP/methodology.md `
  --patch systems/SHOP/methodology-runs/RUN-001/methodology.patch `
  --out-dir systems/SHOP/methodology-runs/RUN-001
```

- [ ] **Step 3.5: Run tests and commit**

Run: `python tools/methodology_quality_gate/test_methodology_quality_gate.py -v`
Expected: all tests pass.

```powershell
git add schemas/methodology-quality-report.schema.json tools/methodology_quality_gate
git commit -m "feat: add methodology quality gate"
```

### Task 4: Orchestrator skill, validator agent, and command

**Files:**
- Create: `.gigacode/skills/manage-methodology/SKILL.md`
- Create: `.gigacode/agents/mnt-validator.md`
- Create: `.gigacode/commands/manage-methodology.md`
- Modify: `.gigacode/test_gigacode_package.py`
- Modify: `.gigacode/README.md`
- Modify: `GIGACODE.md`
- Modify: `docs/METHODOLOGY.md`

**Interfaces:**
- Skill provides `create` and `update-local` workflows.
- Validator returns `accept|blocked` with report path and evidence.
- Slash command invokes the skill and never skips approval.

- [ ] **Step 4.1: Add failing package tests**

Require skill `manage-methodology`, agent `mnt-validator`, and command
`manage-methodology.md`. Assert the skill contains these ordered gates:

```python
for marker in (
    "workspace preview approval", "gap approval", "quality gate",
    "show exact diff", "record-approval", "apply",
):
    self.assertIn(marker, skill_text.lower())
```

Assert `mnt-validator` disallows `write_file` and `edit`.

- [ ] **Step 4.2: Verify failure**

Run: `python .gigacode/test_gigacode_package.py -v`
Expected: FAIL for missing workflow files.

- [ ] **Step 4.3: Write orchestrator skill**

The skill must execute, in order:

1. Run Phase 3a preview from the bootstrap manifest.
2. Build `workspace.candidate.yaml` from user-confirmed modules and prepare a `workspace-manifest` patch.
3. Show the exact workspace diff; wait for approval; record and apply it.
4. Run Phase 3a snapshot from the now-confirmed manifest.
5. Dispatch the Confluence researcher and per-module inspectors in parallel.
6. Aggregate and reconcile evidence.
7. Ask only blocking gap questions and save manual confirmations.
8. Dispatch `mnt-author` with five artifact paths.
9. Run the deterministic quality gate.
10. Dispatch `mnt-validator`; stop on `blocked`.
11. Show `change-summary.md`, warnings, and the exact MNT patch.
12. Wait for a second explicit approval for `methodology-patch`.
13. Run `record-approval`, then `apply` with the approved identity.
14. Re-run the quality gate on canonical `methodology.md`.
15. State that Confluence remains unchanged in Phase 3c.

The skill must use fresh subagents with narrow prompts and read only envelope
messages unless a blocker needs artifact detail.

- [ ] **Step 4.4: Write validator and command**

`mnt-validator` independently reads candidate, quality reports, gaps, source
map, and patch descriptor. It returns `blocked` if the deterministic report is
missing/non-green or if the candidate makes claims absent from evidence.

Command frontmatter description: “Create or update a system MNT through
workspace discovery, evidence reconciliation, quality review, exact diff, and
explicit local approval.” Its body delegates to `manage-methodology`.

- [ ] **Step 4.5: Verify and commit**

Run:

```powershell
python .gigacode/test_gigacode_package.py -v
python tools/methodology_authoring/test_methodology_authoring.py -v
python tools/methodology_quality_gate/test_methodology_quality_gate.py -v
```

Expected: all tests pass.

```powershell
git add .gigacode docs/METHODOLOGY.md
git commit -m "feat: orchestrate approved local methodology updates"
```

## Phase 3c completion gate

- Author cannot edit canonical MNT and receives no raw source context.
- Quality gate blocks missing sections, unsourced SLA, secrets, and scope leaks.
- Validator is read-only and independent of author.
- Exact diff is shown before approval.
- Missing, stale, or mismatched approval leaves the targeted `workspace.yaml` or `methodology.md` byte-for-byte unchanged.
- Successful apply installs only the approved candidate and passes a post-apply gate.
- Confluence remains unchanged.

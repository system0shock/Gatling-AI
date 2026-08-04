# Methodology quality gate

`methodology_quality_gate.py` performs deterministic checks on a generated MNT candidate before an approval can be requested. It reads only the candidate and its evidence artifacts; it does not modify canonical methodology content or contact Confluence.

```powershell
python tools/methodology_quality_gate/methodology_quality_gate.py `
  --candidate systems/SHOP/methodology-runs/RUN-001/methodology.candidate.md `
  --resolved-evidence systems/SHOP/methodology-runs/RUN-001/resolved-evidence.json `
  --coverage systems/SHOP/methodology-runs/RUN-001/section-coverage.json `
  --source-map systems/SHOP/methodology-runs/RUN-001/methodology-source-map.json `
  --workspace-snapshot systems/SHOP/methodology-runs/RUN-001/workspace-snapshot.json `
  --base systems/SHOP/methodology.md `
  --patch systems/SHOP/methodology-runs/RUN-001/methodology.patch `
  --out-dir systems/SHOP/methodology-runs/RUN-001
```

The output directory receives `methodology-quality-report.json` (validated by `schemas/methodology-quality-report.schema.json`) and a redacted Markdown companion. Secret-like findings contain only their rule and line number, never matched candidate text.

Exit codes are `0` for `passed`, `1` for `passed_with_warnings`, and `2` for `blocked`. Exit code `1` is the expected result when only optional sections are `partial` or `missing`; it is advisory and does not make the report blocked. A blocked report is a terminal gate result: the caller must not ask for approval or apply the patch.

The `module-coverage` check is blocking when any of the five mandatory headings is not `covered`. Sparse optional headings (`partial` or `missing`) produce warning-only `module-coverage` output. A warning-only report returns exit code `1` and still permits workflow steps 11–16 to continue.

The gate imports the mandatory-section contract from reconciliation. Incomplete coverage for any of these five headings is blocking:

- `Пользовательские и технические потоки`
- `Реестр тестируемых интерфейсов`
- `Реестр интеграций`
- `Модель нагрузки`
- `SLA, SLO и критерии приемки`

All other canonical headings are optional for coverage purposes. An optional section marked `missing` may have an empty source-map list; optional `partial` or `covered` sections and every mandatory section still require evidence IDs. Claim-source checks are skipped for sections marked `missing`, while the grounding check continues to block generated content in those sections.

Run the focused tests with:

```powershell
python tools/methodology_quality_gate/test_methodology_quality_gate.py -v
```

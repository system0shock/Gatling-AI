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

Exit codes are `0` for `passed`, `1` for `passed_with_warnings`, and `2` for `blocked`. A blocked report is a terminal gate result: the caller must not ask for approval or apply the patch.

Run the focused tests with:

```powershell
python tools/methodology_quality_gate/test_methodology_quality_gate.py -v
```

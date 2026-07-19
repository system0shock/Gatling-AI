# Methodology refresh planner

`methodology_refresh.py` is an offline, deterministic planner. It compares the immutable Phase 3a workspace snapshots from two methodology runs and writes the smallest safe refresh scope.

```powershell
python tools/methodology_refresh/methodology_refresh.py `
  --previous-run systems/SHOP/methodology-runs/RUN-001 `
  --current-run systems/SHOP/methodology-runs/RUN-002 `
  --workspace systems/SHOP/workspace.yaml `
  --source-map systems/SHOP/methodology-runs/RUN-001/methodology-source-map.json `
  --out systems/SHOP/methodology-runs/RUN-002/methodology-refresh-plan.json
```

The CLI validates the Phase 3a snapshot hash, manifest module IDs/kinds, and that the source-map snapshot identity is the previous run's immutable ID. It uses the existing author source-map envelope (`version`, canonical `sections`, and `workspace_snapshot`). An optional `sources` map may associate `module:<id>` or `confluence:<page-id>` with entity IDs and canonical headings to narrow the default scope further.

Changed and added modules are recollected; removed modules affect reconciliation and sections but are not recollected. Unchanged modules/pages are absent from collector lists. Unknown module kinds or source types fail, while unclassified Confluence roles deliberately broaden to all canonical MNT sections. The tool makes no network or MCP calls and has no runtime dependency beyond Python's standard library.

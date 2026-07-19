# Methodology refresh planner

`methodology_refresh.py` is an offline, deterministic planner. It compares immutable Phase 3a workspace snapshots and writes the smallest safe refresh scope.

```powershell
python tools/methodology_refresh/methodology_refresh.py `
  --previous-run systems/SHOP/methodology-runs/RUN-001 `
  --current-run systems/SHOP/methodology-runs/RUN-002 `
  --workspace systems/SHOP/workspace.yaml `
  --source-map systems/SHOP/methodology-runs/RUN-001/methodology-source-map.json `
  --load-test-root systems/SHOP `
  --out methodology-runs/RUN-002/methodology-refresh-plan.json
```

`--load-test-root` is required. Relative outputs are resolved beneath it; absolute outputs must still resolve beneath it after existing symlinks or Windows reparse points are followed. A path outside the root fails with exit 2 before the planner creates a directory or replaces a file. The tool validates immutable Phase 3a snapshots, current manifest IDs/kinds, and the source-map link to the previous snapshot. Pass optional `--previous-workspace` when a historical manifest is available. Without it, common prior modules must retain the current manifest kind and a removed module must carry a known embedded impact kind.

The existing author source-map envelope is `version`, canonical `sections`, and `workspace_snapshot`. Optional `sources` entries may associate `module:<id>` or `confluence:<page-id>` with unique JSON-array `entity_ids` and canonical `sections` to narrow the default scope. Malformed mappings fail with a controlled domain error.

Changed and added modules are recollected; removed modules affect reconciliation and sections but are not recollected. Unchanged modules/pages are absent from collector lists. Unknown module kinds or source types fail, while unclassified Confluence roles deliberately broaden to all canonical MNT sections. Empty plans use explicit previous/current snapshot IDs, or derive both from a valid source-map identity. A non-empty plan rejects mixed histories or explicit IDs that do not match every change. The tool makes no network or MCP calls and has no runtime dependency beyond Python's standard library.
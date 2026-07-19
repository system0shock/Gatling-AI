# Methodology refresh planner

`methodology_refresh.py` is an offline, deterministic planner. It compares immutable Phase 3a workspace snapshots and writes the smallest safe refresh scope.

```powershell
python tools/methodology_refresh/methodology_refresh.py `
  --previous-run systems/SHOP/methodology-runs/RUN-001 `
  --current-run systems/SHOP/methodology-runs/RUN-002 `
  --workspace systems/SHOP/workspace.yaml `
  --source-map systems/SHOP/methodology-runs/RUN-001/methodology-source-map.json `
  --out methodology-runs/RUN-002/methodology-refresh-plan.json
```

The writable root is never caller supplied. The CLI resolves `workspace_root` relative to the committed manifest, finds the unique `load_test_module` entry, resolves its module path, and requires the manifest itself to be beneath that module. Relative output is resolved beneath this derived root; an absolute output must still resolve beneath it after existing symlinks or Windows reparse points are followed. A path outside the root fails with exit 2 before a directory or file is created.

The CLI validates immutable snapshots, current manifest IDs/kinds, and the source-map link to the previous snapshot. Pass optional `--previous-workspace` when a historical manifest is available. A common module kind change is rejected as manifest identity drift requiring reconfirmation, even when a historical manifest is present. Changed and added modules are recollected. Removed modules use their prior snapshot kind for sections and reconciliation but are never recollected; without a historical manifest, that embedded kind must be supported.

The existing author source-map envelope is `version`, canonical `sections`, and `workspace_snapshot`. Optional `sources` entries may associate `module:<id>` or `confluence:<page-id>` with unique JSON-array `entity_ids` and canonical `sections` to narrow the default scope. Invalid scalar, nested, duplicate, or non-string list elements fail with a controlled domain error.

Empty plans use explicit previous/current snapshot IDs, or derive both from a valid source-map identity. A non-empty plan rejects mixed histories or explicit IDs that do not match every change. The tool makes no network or MCP calls and has no runtime dependency beyond Python's standard library.
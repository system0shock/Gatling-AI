# Workspace discovery

`workspace_discovery.py` prepares bounded, auditable inputs for a methodology run. It never updates `workspace.yaml`: auto-discovery is advisory only, and a candidate becomes analyzable only after the user confirms it and records it in `workspace.yaml`; the later approval workflow controls manifest changes.

Run the commands from the load-test repository. The tool accepts absolute or relative output paths, but resolves every path and symlink target inside the configured load-test module directory (`workspace_root / load_test_module`). Paths in SUT repositories or elsewhere in the workspace are rejected. JSON artifacts are UTF-8, deterministically ordered, and atomically replaced.

## Manifest versions

Version 1 remains supported byte-for-byte at the snapshot boundary. It uses
`modules`, requires one closed `kind` value per module, and defaults an omitted
`required` field to `false`:

```yaml
version: 1
system: SHOP
workspace_root: ../../..
load_test_module: load-tests
modules:
  - id: orders
    path: orders-backend
    kind: backend
write_policy:
  allowed_modules: [load-tests]
  sut_modules: read-only
```

Version 2 describes arbitrary repositories. `roles` is an optional open list
of prioritization hints, `service_id` is an optional stable service identity,
and `required` defaults to `true`. Roles do not authorize or prove discovery
findings; later extractors still select inputs from file and content signatures.

```yaml
version: 2
system: SHOP
workspace_root: ../../..
load_test_module: load-tests
repositories:
  - id: orders-contracts
    path: orders-contracts
    roles: [contracts, team-specific-role]
    service_id: orders

  - id: orders-docs
    path: orders-docs
    roles: [documentation]
    required: false
write_policy:
  allowed_modules: [load-tests]
  sut_modules: read-only
```

Repository IDs and roles must be unique within their respective lists. Both
manifest versions retain `inspect`, `exclude`, and `authoritative_for` hints.
Migrating to v2 means changing `modules` to `repositories`, replacing each
`kind` with zero or more `roles`, and explicitly setting `required: false` for
repositories that should remain optional.

## Preview candidates

```powershell
python tools/workspace_discovery/workspace_discovery.py preview `
  --manifest systems/SHOP/workspace.yaml `
  --out systems/SHOP/methodology-runs/RUN-001/workspace-discovery.json
```

The preview lists only depth-one Git siblings, with advisory classification evidence and `confirmation` status. It does not inspect unconfirmed modules beyond fixed markers and does not change the manifest.

## Capture a snapshot

```powershell
python tools/workspace_discovery/workspace_discovery.py snapshot `
  --manifest systems/SHOP/workspace.yaml `
  --run-dir systems/SHOP/methodology-runs/RUN-001 `
  --dirty-policy orders-backend=HEAD
```

This writes `workspace-snapshot.json` below `--run-dir`. Each confirmed repository has its own commit, branch, remote, dirty state, and dirty policy. A dirty repository is rejected unless supplied exactly one `--dirty-policy MODULE=working-tree|HEAD`; the snapshot also contains the read-only module-inspector job envelopes.

Version 1 snapshots keep the original `modules` shape. Version 2 snapshots use
`repositories`, record normalized roles/service/default fields, and include a
top-level `status`. An unavailable required repository produces `blocked`; an
unavailable optional repository produces a warning record while available
repositories remain usable. Unavailable records stay in the complete
repository mapping used to derive `snapshot_id`.

For a dirty repository accepted with `working-tree`, the v2 record contains a
SHA-256 run guard. It covers raw binary Git diff bytes and sorted untracked
relative paths/content hashes after configured exclusions. Diff bytes are never
stored. The guard detects changes inside one run and is not a cross-run cache
identity. `HEAD` continues to select committed bytes for later discovery.

Expected manifest, path, Git, and dirty-policy errors are reported on stderr and return exit code 2. Unexpected programming errors are not converted into domain errors.

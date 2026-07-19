# Workspace discovery

`workspace_discovery.py` prepares bounded, auditable inputs for a methodology run. It never updates `workspace.yaml`: auto-discovery is advisory only, and a candidate becomes analyzable only after the user confirms it and records it in `workspace.yaml`; the later approval workflow controls manifest changes.

Run the commands from the load-test repository. The tool accepts absolute or relative output paths, but resolves every path and symlink target inside the configured load-test module directory (`workspace_root / load_test_module`). Paths in SUT repositories or elsewhere in the workspace are rejected. JSON artifacts are UTF-8, deterministically ordered, and atomically replaced.

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

Expected manifest, path, Git, and dirty-policy errors are reported on stderr and return exit code 2. Unexpected programming errors are not converted into domain errors.

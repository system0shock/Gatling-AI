# Methodology workspace workflow

Phase 3a establishes the bounded workspace inputs for methodology generation. It does not read Confluence and does not generate, edit, or publish MNT text.

## Workspace layout and artifact boundary

The load-test repository owns the workspace manifest and run artifacts:

```text
systems/<SYSTEM>/
??? methodology.md
??? workspace.yaml
??? methodology-runs/<RUN-ID>/
    ??? workspace-discovery.json
    ??? workspace-snapshot.json
    ??? modules/<MODULE-ID>-evidence.json
```

All module paths in `workspace.yaml` are relative to the resolved `workspace_root`. The workspace root itself is not required to be a Git repository. The load-test module is the only writable module; every SUT module is read-only. Resolved module paths and marker paths must remain within the resolved workspace root. CLI output targets and symlink targets must remain within `workspace_root / load_test_module`; SUT repositories and other workspace locations are rejected.

`workspace-discovery.json` is an advisory preview. `workspace-snapshot.json` is the confirmed per-repository record: commit, branch, remote, dirty state, selected dirty policy, and module-inspector job envelopes. The run directory is the artifact boundary; module inspectors write their evidence only to their assigned artifact paths and do not modify SUT source.

## Hybrid confirmation rule

Auto-discovery is intentionally shallow: it considers depth-one Git siblings and fixed classification markers only. It never adds a module to `workspace.yaml`. A candidate may be analyzed only after a user confirms it and records it in `workspace.yaml`; the later approval workflow controls manifest changes; unconfirmed candidates remain preview data.

Before analysis, snapshot each confirmed module independently. A clean repository receives the `clean` policy. A dirty repository must explicitly select either `working-tree` or `HEAD`; otherwise the snapshot is rejected.

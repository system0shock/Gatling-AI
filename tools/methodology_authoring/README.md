# Methodology authoring approval engine

This tool binds a `workspace.yaml` or permanent `methodology.md` candidate to its exact base file and unified patch before it can be applied. It supports only two independent approval kinds: `workspace-manifest` for `workspace.yaml`, and `methodology-patch` for `methodology.md`.

Every lifecycle command requires `--load-test-root`. `prepare` confines the base, candidate, patch, and descriptor output to that root; `record-approval` confines the descriptor's paths and approval record; and `apply` confines the base, candidate, patch, and approval input. Any base, candidate, or patch change invalidates approval. Patch rendering normalizes CRLF/LF comparison input to LF, emits `\\ No newline at end of file` markers for unterminated lines, and keeps raw base/candidate hashes unchanged. A missing base hashes as SHA-256 of empty bytes; missing candidates and patches are errors.

Apply is a fail-closed transaction. It snapshots and validates candidate and patch bytes into a same-filesystem staged file, atomically moves the current base to a unique sibling backup, validates the captured base, and creates the new target by hard-linking the staged candidate only while the target is absent. A concurrent recreation therefore fails rather than being overwritten; rollback links the backup back only while the target remains absent, preserving any concurrent file. The configured root must be an existing non-link/non-reparse directory and all existing path components are rejected if they are links or reparse points. The transaction requires a filesystem that supports same-directory atomic replace and hard links; otherwise apply fails closed.

```powershell
python tools/methodology_authoring/methodology_authoring.py prepare `
  --kind methodology-patch --base systems/SHOP/methodology.md `
  --candidate systems/SHOP/methodology-runs/RUN-001/methodology.candidate.md `
  --patch systems/SHOP/methodology-runs/RUN-001/methodology.patch `
  --out systems/SHOP/methodology-runs/RUN-001/patch-descriptor.json `
  --load-test-root systems/SHOP

python tools/methodology_authoring/methodology_authoring.py record-approval `
  --descriptor systems/SHOP/methodology-runs/RUN-001/patch-descriptor.json `
  --approved-by v.salnikov `
  --out systems/SHOP/methodology-runs/RUN-001/methodology-approval.json `
  --load-test-root systems/SHOP

python tools/methodology_authoring/methodology_authoring.py apply `
  --base systems/SHOP/methodology.md `
  --candidate systems/SHOP/methodology-runs/RUN-001/methodology.candidate.md `
  --patch systems/SHOP/methodology-runs/RUN-001/methodology.patch `
  --approval systems/SHOP/methodology-runs/RUN-001/methodology-approval.json `
  --load-test-root systems/SHOP
```

The engine does not request approval, generate candidates, dispatch collectors, publish to Confluence, or write to SUT modules. A blocked methodology-quality report must prevent the caller from recording or requesting approval.

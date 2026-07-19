# Methodology authoring approval engine

This tool binds a `workspace.yaml` or permanent `methodology.md` candidate to its exact base file and unified patch before it can be applied. It supports only two independent approval kinds: `workspace-manifest` for `workspace.yaml`, and `methodology-patch` for `methodology.md`.

Every lifecycle command requires `--load-test-root`. `prepare` confines the base, candidate, patch, and descriptor output to that root; `record-approval` confines the descriptor's paths and approval record; and `apply` confines the base, candidate, patch, and approval input. Any base, candidate, or patch change invalidates approval. A missing base hashes as SHA-256 of empty bytes; missing candidates and patches are errors.

The engine rejects symlink and Windows reparse-point components in contained paths and repeats containment checks immediately before atomic replacement. Python does not offer one race-free directory-descriptor replacement primitive on every supported platform, so a hostile actor that swaps a directory after the final check remains outside the portable guarantee; run the tool only in a trusted load-test workspace.

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

# Methodology authoring approval engine

This tool binds a `workspace.yaml` or permanent `methodology.md` candidate to its exact base file and unified patch before it can be applied. It supports only two independent approval kinds: `workspace-manifest` and `methodology-patch`.

`prepare` creates the patch and descriptor; `record-approval` records the explicit approver against its three SHA-256 hashes; `apply` validates all current content, regenerates the diff, confines the base and candidate to the configured load-test root, then atomically replaces the base file. Any changed base, candidate, or patch invalidates the approval. A missing base hashes as SHA-256 of empty bytes.

```powershell
python tools/methodology_authoring/methodology_authoring.py prepare `
  --kind methodology-patch --base systems/SHOP/methodology.md `
  --candidate systems/SHOP/methodology-runs/RUN-001/methodology.candidate.md `
  --patch systems/SHOP/methodology-runs/RUN-001/methodology.patch `
  --out systems/SHOP/methodology-runs/RUN-001/patch-descriptor.json

python tools/methodology_authoring/methodology_authoring.py record-approval `
  --descriptor systems/SHOP/methodology-runs/RUN-001/patch-descriptor.json `
  --approved-by v.salnikov `
  --out systems/SHOP/methodology-runs/RUN-001/methodology-approval.json

python tools/methodology_authoring/methodology_authoring.py apply `
  --base systems/SHOP/methodology.md `
  --candidate systems/SHOP/methodology-runs/RUN-001/methodology.candidate.md `
  --patch systems/SHOP/methodology-runs/RUN-001/methodology.patch `
  --approval systems/SHOP/methodology-runs/RUN-001/methodology-approval.json `
  --load-test-root systems/SHOP
```

The engine does not request approval, generate candidates, dispatch collectors, publish to Confluence, or write to SUT modules. A blocked methodology-quality report must prevent the caller from recording or requesting approval.

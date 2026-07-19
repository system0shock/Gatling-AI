# Methodology evidence tools

`methodology_evidence.py aggregate` verifies repository/OpenAPI evidence against a confirmed `workspace-snapshot.json` and writes the repository, endpoint, and integration evidence artifacts.

`methodology_evidence.py reconcile` joins repository, Confluence, and manual-confirmation evidence by stable entity and field. It writes all of the following artifacts deterministically:

- `resolved-evidence.json` — every candidate record and its provenance, with an explicit status.
- `discrepancies.md` — unresolved conflicting source claims.
- `methodology-gaps.md` — blocking gaps, including unconfirmed SLA and absent production workload evidence.
- `section-coverage.json` — all 17 required MNT headings with `covered`, `partial`, or `missing` status and evidence IDs.

A manual confirmation resolves only its matching entity and field. Repository-only and Confluence-only evidence remain descriptive (`repo_only` and `docs_only`), never business approval. The `reconcile` command exits 2 for any blocking gap, after writing all outputs.

```powershell
python tools/methodology_evidence/methodology_evidence.py reconcile `
  --repository repository-evidence.json `
  --confluence confluence-evidence.json `
  --confirmations manual-confirmations.json `
  --out-dir methodology-reconcile
```
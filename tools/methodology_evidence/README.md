# Methodology evidence tools

`methodology_evidence.py aggregate` verifies repository/OpenAPI evidence against a confirmed `workspace-snapshot.json` and writes the repository, endpoint, and integration evidence artifacts.

`methodology_evidence.py reconcile` processes four ordered sources: repository evidence, Confluence evidence, manual confirmations, and section reviews. It joins records by stable entity and field, then applies explicit review approvals, exclusions, and additions. It writes all of the following artifacts deterministically:

- `resolved-evidence.json` — every candidate record and its provenance, with an explicit status.
- `discrepancies.md` — unresolved conflicting source claims.
- `methodology-gaps.md` — blocking gaps against the five mandatory sections.
- `section-coverage.json` — all 17 required MNT headings with `covered`, `partial`, or `missing` status and evidence IDs.

A manual confirmation resolves only its matching entity and field. Repository-only and Confluence-only evidence remain descriptive (`repo_only` and `docs_only`), never business approval. The mandatory contract requires review-mode completion for `Модель нагрузки`, `Реестр тестируемых интерфейсов`, and `Реестр интеграций`, and entity-level confirmation for the strict sections `SLA, SLO и критерии приемки` and `Пользовательские и технические потоки`.

The `reconcile` command exits 2 for any blocking gap after writing all four deterministic outputs. Exit code 2 means the questionnaire must continue until the required evidence or review action is supplied.

Create an empty review artifact inside each run directory before the first reconciliation:

```powershell
'{"version":1,"reviews":{}}' | Set-Content `
  -Encoding utf8 `
  systems/SHOP/methodology-runs/RUN-001/section-reviews.json
```

Each named list review supports exactly three actions: `approve` an extracted entity, `exclude` an extracted entity that is not applicable, or `add` a missing entity with its fields. Keep the artifact run-scoped and pass it on every reconciliation with the required `--reviews` flag.

```powershell
python tools/methodology_evidence/methodology_evidence.py reconcile `
  --repository repository-evidence.json `
  --confluence confluence-evidence.json `
  --confirmations manual-confirmations.json `
  --reviews section-reviews.json `
  --out-dir methodology-reconcile
```

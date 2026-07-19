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

## Reconciliation and bounded authoring

Phase 3b reconciles the confirmed module and documentation evidence into
`resolved-evidence.json`, `methodology-gaps.md`, `discrepancies.md`, and
`section-coverage.json`. Manual decisions are recorded in
`manual-confirmations.json`; unresolved or unsupported claims remain gaps.

Phase 3c uses the permanent 17-section template at
`.gigacode/skills/manage-methodology/templates/methodology-template.md`. The
MNT author receives only the current methodology, that template, resolved
evidence, manual confirmations, section coverage, and the confirmed workspace snapshot. It may create a candidate,
exact patch, source map (including the immutable workspace `snapshot_id`), and change summary only within the run directory. It
never reads raw code or Confluence, modifies `workspace.yaml` or
`methodology.md`, applies a patch, or publishes to Confluence.

`methodology.md` is the permanent system-level document. Scenario definitions,
concrete test data, and run protocols and results remain separate artifacts.
Before a later local install, the exact diff must be reviewed and explicitly
approved; approval is bound to the base, candidate, and patch hashes, so any
change invalidates it. A blocked quality report prevents an approval request.
Confluence publication is outside this phase and requires a separate later
approval.

## Оркестрация локального обновления МНТ

Команда `/manage-methodology` выполняет только локальное обновление. Сначала
создаётся и показывается точный diff `workspace-manifest`; применение возможно
только после отдельного явного подтверждения, записи `record-approval` и
hash-bound `apply`. После подтверждённого снимка рабочего пространства собираются
и сверяются доказательства, а ответы только на блокирующие пробелы сохраняются в
`manual-confirmations.json`.

Автор получает ровно шесть путей к артефактам, включая независимо проверенный
`workspace-snapshot.json`, и не может изменять каноническую МНТ. Детерминированный
quality gate и независимый read-only `mnt-validator` должны принять кандидата до
показа точного MNT diff. Затем требуется второе отдельное подтверждение
`methodology-patch`; только после него допускаются `record-approval` и `apply`.
Канонический `methodology.md` проходит post-apply quality gate. Confluence остаётся
неизменным: публикация, комментарии и иные операции записи не входят в Phase 3c.

Валидатор `mnt-validator` имеет только доступ на чтение и возвращает inline
`accept|blocked` с ссылками на уже существующие quality-report, descriptor и
source-map; отдельный отчёт валидатора не создаётся.

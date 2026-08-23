# Methodology-first core CLI

This command resolves the versioned profile and scalar answers, renders a
candidate methodology, and produces independent readiness and template
conformance reports. It is deterministic and local: META is not queried. The
engineer checks META separately and records any value and source reference in
`answers.yaml`; explicit user overrides still take precedence.

## Build

```text
python tools/methodology_pipeline/methodology_pipeline.py build \
  --workspace-snapshot <workspace-snapshot.json> \
  --surface-review <surface-review.json> \
  --profile <default-v1.yaml> \
  --questions <questions.yaml> \
  --answers <answers.yaml> \
  --template <methodology-template.md> \
  --template-contract <methodology-template-contract.yaml> \
  --current <methodology.md> \
  [--previous-generation-state <generation-state.json>] \
  [--drift-decisions <managed-drift-decisions.yaml>] \
  --out-dir <run-dir> \
  --load-test-root <load-test-root>
```

If `--current` does not exist, build starts from the permanent template. If it
exists, build uses that exact document and preserves manual blocks and text
outside generated blocks. A changed generated block is a conflict unless an
explicit `keep`, `replace`, or `move-to-manual` decision resolves it. `keep` is
a visible one-run warning; `move-to-manual` is the durable home for manual
prose.

Runtime inputs, optional state/decision files, `--current`, and `--out-dir`
must resolve below `--load-test-root`. Profile, question, template, and
template-contract assets must resolve below the installed
`.gigacode/skills/manage-methodology` directory. Resolved paths are checked so
symlinks cannot escape either boundary.

Build writes these files atomically under `--out-dir`:

- `resolved-profile.yaml`
- `methodology-input.yaml`
- `generation-state.json`
- `methodology.candidate.md`
- `methodology-readiness-report.json`
- `methodology-readiness-report.md`
- `methodology-template-report.json`
- `methodology-template-report.md`

## Check

```text
python tools/methodology_pipeline/methodology_pipeline.py check \
  --candidate <methodology.candidate.md> \
  --methodology-input <methodology-input.yaml> \
  --generation-state <generation-state.json> \
  --template-contract <methodology-template-contract.yaml> \
  --out-dir <run-dir> \
  --load-test-root <load-test-root>
```

Check validates the existing candidate, normalized input, and generation state,
then regenerates only the four JSON/Markdown report files. It does not read the
workspace snapshot, surface review, source repositories, profile, questions,
answers, or current methodology.

Every canonical generated block must be present in both the candidate and
generation state. Check binds the candidate block hash to `sha256` and a fresh
deterministic render from `methodology-input.yaml` to `rendered_sha256`.
`resolution: keep` may bind different actual and rendered bodies; a rendered
entry must bind the same body. A parseable hash/state conflict still emits both
reports, prints a deterministic diagnostic, and exits with code 2.

## Exit codes

| Code | Meaning |
|---:|---|
| `0` | Ready for testing, template complete, and no renderer warning. |
| `1` | Ready for testing, but template completeness or a one-run `keep` decision produced a warning. |
| `2` | Readiness blocked, generated-block conflict unresolved, path unsafe, or input invalid. Parseable blocked/conflict builds still emit the candidate and both reports. |

This tool never applies or overwrites `methodology.md`. It writes only
`methodology.candidate.md` and run artifacts. Approval and application remain a
separate, hash-bound workflow.

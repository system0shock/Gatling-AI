# jmx_parser

Deterministic streaming parser: JMeter `.jmx` → compact IR for the migration
pipeline (Phase 2). The only component in the repo that reads JMX XML; agents
work with its outputs, never with the raw file.

## Usage

```powershell
# parse (out-dir is usually scenarios/<SYSTEM>/<id>-<NNN>/migration/)
python tools/jmx_parser/jmx_parser.py parse path\to\plan.jmx --out-dir <dir> --format json

# agent-facing slices (avoid loading the whole ir.json into context)
python tools/jmx_parser/jmx_parser.py summary <dir>/ir.json
python tools/jmx_parser/jmx_parser.py element <dir>/ir.json e-0042
```

## Outputs

| Artifact | Purpose |
|---|---|
| `ir.json` | Element tree (ids `e-NNNN` in document order), loads, variable index, complexity flags, stats; validated against `schemas/jmx-ir.schema.json` |
| `inventory.md` | Gate 1 review document: counts, unsupported elements, thread groups, curated data-flow findings, complexity flags |
| `bodies/<sha12>.json\|.txt` | Request bodies above `--max-inline-body-bytes` (default 1024), deduplicated by content hash |
| `jsr223/<sha12>.groovy` | Extracted JSR223 scripts, deduplicated, classified `typical`/`complex` |

## Guarantees

- **No silent drop:** every XML test element lands in the IR; unrecognized
  types get `kind: unknown` and an `unsupported` entry.
- **Determinism:** identical input produces byte-identical `ir.json` and
  `inventory.md` (no timestamps, sorted keys, hash-named artifacts).
- **Bounded memory:** iterparse + clear; peak is the largest single element
  (in practice the largest request body), not file size. Budget-tested at
  ~150 MB via `test_jmx_parser_perf.py` (`GATLING_AI_PERF=1`); measured
  ~1 s wall time and ~15 MB traced peak for a 150 MB plan.

## Known limits (by design, surfaced in inventory)

- BeanShell elements are `unknown` (the target park uses JSR223).
- Multi-row Ultimate Thread Group schedules with non-overlapping rows are
  normalized to `profile: stages` (cumulative users per row). Overlapping
  rows (a row starting before the previous row's ramp+hold completes) remain
  `load.normalized: null` + note — they need human review. Shutdown
  ramp-down is always ignored with a note.
- Extractor/timer scope is recorded positionally (where the element sits in
  the tree); JMeter "applies to" subtleties are the conversion skill's job.
- JSR223 classification is conservative: anything outside a small allowlist
  of tokens is `complex`. `props` usage is always `complex` (inter-thread).

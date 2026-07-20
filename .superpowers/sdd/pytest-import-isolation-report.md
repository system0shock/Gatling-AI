# Pytest import-isolation RED/GREEN report

Date: 2026-07-20

## Scope

Test-only import isolation for methodology tool tests. Production modules and fixture content were not changed.

## RED evidence

1. `python -m pytest -q -p no:cacheprovider tools/jmx_parser tools/methodology_evidence`
   - Collection failed because `methodology_evidence` resolved `from fixtures` to `tools/jmx_parser/fixtures.py` (`backend_endpoint` missing).
2. `python -m pytest -q -p no:cacheprovider .gigacode tools examples`
   - Collection failed because `.gigacode` cached `methodology_authoring.py` as top-level `methodology_authoring`, preventing package collection; the quality-gate sibling relative import was also beyond its top-level package.
3. `python -m pytest -q -p no:cacheprovider tools/methodology_publish`
   - 13 tests failed because `import methodology_publish` bound the package rather than its local implementation module.

## Fix

- Package collection now uses relative imports for local modules and fixtures, with direct-script fallbacks retained.
- The evidence test supplies its unchanged standalone fixture with the package-relative `contracts` module during collection.
- Cross-tool package imports use the `tools.*` namespace.
- `.gigacode` imports methodology authoring via `tools.methodology_authoring` rather than adding the implementation directory to `sys.path`.
- The methodology-publish test uses the same package/direct import split.

## GREEN evidence

- Minimal combined run: `109 passed, 1 skipped, 19 subtests passed`.
- Direct touched test files: authoring `54 passed, 1 skipped`; evidence `35 passed`; quality gate `21 passed`; refresh `23 passed, 1 skipped`; workspace discovery `17 passed, 2 skipped`.
- Direct `.gigacode` package test: `26 passed`.
- Focused methodology-publish pytest: `11 passed, 3 subtests passed`; direct script: `11 passed`.
- Full run: `python -m pytest -q -p no:cacheprovider .gigacode tools examples` -> `589 passed, 6 skipped, 73 subtests passed in 10.12s`.

## Notes

- The initial evidence fixture used a legacy top-level `contracts` import; the review follow-up moves package/direct import compatibility into that fixture.
- Direct authoring runs leave ignored fixed-path fixture residue. Before the final full run, only the verified ignored `tools/methodology_authoring/.test-fixtures` directory was removed.

## Review follow-up

- RED: package fixture re-import with a pre-existing sentinel `sys.modules["contracts"]` failed because the legacy fixture import tried to read that top-level module.
- Added a package-collection regression test that restores any pre-existing top-level `contracts` and fixture-module entries after the assertion.
- Moved the package-relative/direct fallback into `fixtures.py` and removed the test module's persistent `sys.modules` alias.
- Targeted regression GREEN: `1 passed`.
- Combined GREEN: `110 passed, 1 skipped, 19 subtests passed`.
- Direct evidence script GREEN: `35 passed, 1 skipped`.
- Full GREEN: `590 passed, 6 skipped, 73 subtests passed in 9.63s`.
- Before the final full run, only the verified ignored authoring fixed-path test-fixture directory was removed.

## Authoring fixture lifecycle follow-up

- RED: a repeated full run failed because fixed per-test authoring fixture paths retained files from a previous run.
- `setUp` now removes only its computed per-test root before creating it, and `tearDown` removes that same `self.root`.
- Two consecutive direct authoring runs pass without manual cleanup: `54 passed, 1 skipped` each.
- Full suite after those runs: `590 passed, 6 skipped, 73 subtests passed in 8.98s`.

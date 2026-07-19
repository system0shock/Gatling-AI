# Task 3a.2 report: Safe hybrid discovery preview

## Implementation

- Added `tools/workspace_discovery/discovery.py` with strict resolved-path containment through `ensure_inside`; symlink targets outside the resolved workspace root are rejected.
- Added a depth-one Git-sibling preview that only reports advisory candidates. It never writes or changes the manifest.
- Classification reads only fixed markers. `package.json` is considered frontend only with a `scripts.build` entry or React, Vue, or Angular dependency evidence; otherwise it is `other`.
- Added path-boundary and unconfirmed-candidate tests.

## RED

Command:

```text
python tools\\workspace_discovery\\test_workspace_discovery.py DiscoveryTest -v
```

Output: `ModuleNotFoundError: No module named 'discovery'` (expected, before production module existed).

## GREEN and verification

Commands:

```text
python tools\\workspace_discovery\\test_workspace_discovery.py DiscoveryTest -v
python tools\\workspace_discovery\\test_workspace_discovery.py -v
git diff --check
```

## Exact verification output

Focused command: `python tools\\workspace_discovery\\test_workspace_discovery.py DiscoveryTest -v`

```text
test_preview_marks_unconfirmed_sibling_without_analyzing_it (__main__.DiscoveryTest.test_preview_marks_unconfirmed_sibling_without_analyzing_it) ... ok
test_symlink_escape_is_rejected (__main__.DiscoveryTest.test_symlink_escape_is_rejected) ... skipped 'symlinks unavailable'

----------------------------------------------------------------------
Ran 2 tests in 0.011s

OK (skipped=1)
```

Full command: `python tools\\workspace_discovery\\test_workspace_discovery.py -v`

```text
test_preview_marks_unconfirmed_sibling_without_analyzing_it (__main__.DiscoveryTest.test_preview_marks_unconfirmed_sibling_without_analyzing_it) ... ok
test_symlink_escape_is_rejected (__main__.DiscoveryTest.test_symlink_escape_is_rejected) ... skipped 'symlinks unavailable'
test_loads_relative_workspace_and_modules (__main__.ManifestLoadTest.test_loads_relative_workspace_and_modules) ... ok
test_rejects_absolute_module_path (__main__.ManifestLoadTest.test_rejects_absolute_module_path) ... ok
test_rejects_windows_non_relative_module_paths (__main__.ManifestLoadTest.test_rejects_windows_non_relative_module_paths) ... ok
test_rejects_windows_non_relative_workspace_roots (__main__.ManifestLoadTest.test_rejects_windows_non_relative_workspace_roots) ... ok
test_rejects_write_policy_that_allows_a_sut_module (__main__.ManifestLoadTest.test_rejects_write_policy_that_allows_a_sut_module) ... ok

----------------------------------------------------------------------
Ran 7 tests in 0.090s

OK (skipped=1)
```

`git diff --check` produced no output (success). Files changed: `tools/workspace_discovery/discovery.py`, `tools/workspace_discovery/test_workspace_discovery.py`, and this report. Commit: `36d0178 feat: preview sibling methodology modules safely`.

Self-review: resolved candidate and symlink target containment precedes preview reporting; the preview reads only fixed markers and does not alter the manifest. Concern: this host cannot create symlinks, hence one expected skipped test.
## Review-fix TDD evidence

RED command: `python tools\\workspace_discovery\\test_workspace_discovery.py DiscoveryTest -v`

```text
test_marker_paths_are_checked_against_workspace_boundary (...) ... ERROR
TypeError: classification_evidence() takes 1 positional argument but 2 were given
Ran 4 tests in 0.019s
FAILED (errors=1, skipped=2)
```

GREEN commands:

```text
python tools\\workspace_discovery\\test_workspace_discovery.py DiscoveryTest -v
python tools\\workspace_discovery\\test_workspace_discovery.py -v
git diff --check
```

Exact GREEN output:

```text
Focused: test_marker_paths_are_checked_against_workspace_boundary ... ok
Focused: test_preview_marks_unconfirmed_sibling_without_analyzing_it ... ok
Focused: test_preview_rejects_marker_symlink_escape ... skipped 'symlinks unavailable'
Focused: test_symlink_escape_is_rejected ... skipped 'symlinks unavailable'
Ran 4 tests in 0.028s
OK (skipped=2)
Full: the four focused tests above plus five ManifestLoadTest tests ... ok

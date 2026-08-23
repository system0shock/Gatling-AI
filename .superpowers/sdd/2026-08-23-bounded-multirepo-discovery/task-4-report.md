# Task 4 report — deterministic bounded API contract extraction

Base: `5718cac`

## Scope

- Added exactly `graphql-core==3.2.11` to `requirements.txt`; the installed
  package reports version `3.2.11`.
- Added bounded OpenAPI 3/Swagger 2, AsyncAPI v2/v3, and GraphQL SDL
  extractors plus their three focused test modules.
- No extractor reads a repository, opens a file, resolves a reference, uses
  the network, or executes GraphQL introspection. OpenAPI and AsyncAPI accept
  a caller-supplied parsed mapping or bounded JSON/YAML text and use
  `yaml.safe_load` only.
- Candidate source provenance copies the context's repository, revision,
  relative path, selection reason, and SHA-256 exactly; only the per-fact
  pointer is derived. Discovery-index-only `size_bytes` is never serialized
  into extractor candidate provenance.

## TDD evidence

Initial RED, before production modules existed:

```text
python -m pytest -p no:cacheprovider tools/methodology_discovery/test_openapi.py tools/methodology_discovery/test_asyncapi.py tools/methodology_discovery/test_graphql_sdl.py -q
exit 1: 3 collection errors (missing openapi, asyncapi, and graphql_sdl)
```

Controller text-parsing ruling RED, after tests were added and before parsing
support:

```text
4 failed, 14 passed, 4 subtests passed
```

Self-review unsupported-version RED, before version gates:

```text
4 failed, 2 passed
```

Focused GREEN:

```text
14 passed, 12 subtests passed in 0.57s
```

## Decisions and boundaries

- The explicit context is `{repo_id, snapshot_identity, service_id, source}`.
  Manifest-only identity uses basis `manifest`; contract-only or an agreeing
  `info.x-service-id` uses `contract`; title-only identity is a normalized
  metadata slug. Conflicts and unknowns receive a repository-scoped temporary
  identity so separate repositories cannot auto-merge.
- OpenAPI canonical keys are
  `http:<service>:<METHOD>:<normalized-path>`. All eight OpenAPI Path Item
  operation keys are covered. Servers, Swagger host/schemes/basePath, response
  codes, tags, operation ID, and summary remain scalar attributes only.
- AsyncAPI `publish`/`send` normalize to `publish`, `subscribe`/`receive` to
  `subscribe`, and missing/unknown action to `unspecified`. No flow candidate
  or application-perspective inference is created.
- GraphQL uses `graphql.parse`, honors explicit schema root mappings plus the
  standard roots when no schema mapping exists, and walks only root object
  definitions/extensions. Arguments and types are sorted deterministic scalar
  arrays.
- JSON Pointers use RFC 6901 escaping only (`~` to `~0`, `/` to `~1`). Remote
  `$ref` values remain unresolved and focused tests patch network/introspection
  entry points to fail if invoked.
- Every returned result is validated against the exact closed
  `methodology-extractor-result` schema. Focused tests also cover mutation
  safety, stable candidate/diagnostic ordering, malformed siblings, invalid
  top-level input, and traceback-free structured errors.

## Verification

```text
python -m pip check
No broken requirements found.

python -m compileall -q tools/methodology_discovery
exit 0

python -m pytest -p no:cacheprovider --ignore-glob=pytest-cache-files-* tools/workspace_discovery tools/methodology_discovery -q
81 passed, 3 skipped, 44 subtests passed in 7.06s

python -m pytest -p no:cacheprovider --ignore-glob=pytest-cache-files-* -q
817 passed, 8 skipped, 166 subtests passed in 32.31s

git diff --check
exit 0
```

The discovery/workspace and full suites ran outside the filesystem sandbox
under the recorded Python 3.14 Windows temporary-directory ACL ruling.
Inaccessible pre-existing `pytest-cache-files-*` directories were ignored and
not modified.

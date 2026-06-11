# Scenario Lint Rules

## Scenario Lint

- `scenario-lint.system-format`: `scenario.system` must be present and match
  `^[A-Z][A-Z0-9]{1,9}$` (one uppercase letter followed by up to nine
  uppercase letters or digits). Blocking.
- `scenario-lint.number-format`: `scenario.number` must be a positive integer
  (≥ 1). Blocking.
- `scenario-lint.unique-step-names`: every `steps[].name` must be unique.
- `scenario-lint.http-request-required`: every HTTP step must include a request
  block with `method` and `path`.
- `check-lint.missing-checks`: every HTTP step must include at least one check.
- `check-lint.mutating-status-check`: mutating HTTP methods (`POST`, `PUT`,
  `PATCH`, `DELETE`) that define checks must include an explicit status check.
- `scenario-lint.positive-load-values`: `load.users`, `load.ramp_seconds`, and
  `load.duration_seconds` must be positive integers.
- `feeder-lint.name-format`: every `scenario.data.feeders[].name` must be
  kebab-case (lowercase ASCII letters, digits, and hyphens only; must start
  with a letter). Blocking.
- `feeder-lint.file-name`: every `scenario.data.feeders[].file` must equal
  `<feeder-name>.csv` — that is, the feeder name followed by `.csv` with no
  path separators. Blocking.
- `feeder-lint.missing-feeder`: variables in request `path`, `headers`, and
  `body` must be backed by an extraction, the exact environment/system variable
  `BASE_URL` or `env`, or a configured feeder column. Feeder columns are resolved
  from an explicit optional `columns` list or the header row of the local CSV
  file referenced by `scenario.data.feeders[].file`. Explicit
  `${feeder.column}` references must use an existing feeder name and column.
  Bare variables such as `${username}` must match a resolved column on at least
  one feeder.
- `feeder-lint.missing-feeder-file`: referenced feeder CSV files that are not
  present emit a warning. Missing files do not define variables.
- `scenario-lint.protocol-supported`: MVP accepts only `protocol: http`.

## Transaction Lint

- `transaction-lint.required`: every step must include a transaction display
  name.
- `transaction-lint.format`: transaction display names must use
  `<NN> <domain>.<action> - <human title>`.
- `transaction-lint.max-length`: transaction display names must be 80
  characters or fewer.
- `transaction-lint.no-secrets`: transaction display names must not include
  secret-looking values.
- `transaction-lint.no-env-names`: transaction display names must not include
  `dev`, `stage`, or `prod`.
- `transaction-lint.duplicate-number`: the two-digit numeric prefix `NN` of
  each transaction display name must be unique across the entire simulation
  (all populations combined). Duplicate prefixes indicate two transactions
  would collide in Gatling reports. Blocking.

## Layout Lint

These rules apply only to files whose basename is exactly `scenario.yaml`.
Draft files with any other name are linted for content rules only.

- `layout-lint.folder-name`: the immediate parent directory of `scenario.yaml`
  must be named `<id>-<NNN>` where `<id>` matches `scenario.id` and `<NNN>`
  is `scenario.number` zero-padded to three digits (e.g. `checkout-mix-001`).
  Blocking.
- `layout-lint.system-folder`: the grandparent directory of `scenario.yaml`
  must be named exactly `scenario.system` (e.g. `SHOP`). Blocking.
- `layout-lint.duplicate-number`: across all `scenario.yaml` files discovered
  in the scenarios tree, the pair `(scenario.system, scenario.number)` must be
  unique. Two scenarios with the same system code and number are a conflict.
  Blocking.

## Secret Scan

- `secret-scan.secret-looking-value`: flags obvious API tokens, passwords,
  bearer tokens, and JDBC credentials.
- `secret-scan.hardcoded-production-url`: flags hardcoded production URLs.

All rules emit blocking findings except documented feeder-file absence warnings.

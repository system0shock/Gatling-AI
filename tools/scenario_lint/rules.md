# Scenario Lint Rules

## Scenario Lint

- `scenario-lint.unique-step-names`: every `steps[].name` must be unique.
- `scenario-lint.http-request-required`: every HTTP step must include a request
  block with `method` and `path`.
- `check-lint.missing-checks`: every HTTP step must include at least one check.
- `check-lint.mutating-status-check`: mutating HTTP methods (`POST`, `PUT`,
  `PATCH`, `DELETE`) must include an explicit status check.
- `scenario-lint.positive-load-values`: `load.users`, `load.ramp_seconds`, and
  `load.duration_seconds` must be positive integers.
- `feeder-lint.missing-feeder`: variables in request `path`, `headers`, and
  `body` must be backed by an extraction, the exact environment/system variable
  `BASE_URL` or `env`, or a configured feeder column. Feeder columns are resolved
  from an explicit optional `columns` list or the header row of the local CSV
  file referenced by `scenario.data.feeders[].file`. Explicit
  `${feeder.column}` references must use an existing feeder name and column.
  Bare variables such as `${username}` must match a resolved column on at least
  one feeder.
- `feeder-lint.missing-feeder-file`: referenced feeder CSV files that are not
  present emit a warning. Missing files do not define arbitrary variables. Phase
  0 keeps a documented test bootstrap fallback for the golden fixture only:
  absent `users.csv` defines `username` and `password` until fixtures can carry
  real CSV files or explicit feeder `columns`.
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

## Secret Scan

- `secret-scan.secret-looking-value`: flags obvious API tokens, passwords,
  bearer tokens, and JDBC credentials.
- `secret-scan.hardcoded-production-url`: flags hardcoded production URLs.

All rules emit blocking findings except documented feeder-file absence warnings.

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
  `body` must be backed by an extraction, env-style variable, or configured
  feeder. Explicit `${feeder.column}` references must use an existing feeder
  name. Bare lower-case variables are accepted when at least one feeder exists
  because the Phase 0 schema does not declare feeder columns.
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

All rules currently emit blocking findings.

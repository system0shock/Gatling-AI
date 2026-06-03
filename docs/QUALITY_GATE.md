# Quality Gate

## Purpose

The quality gate prevents the agent from handing back artifacts that only look finished. It combines deterministic linters, build checks, reports, and read-only subagent validation.

## Statuses

| Status | Meaning |
|---|---|
| `passed` | No blocking errors or warnings that require user action. |
| `passed_with_warnings` | No blocking errors, but warnings or waivers are present. |
| `blocked` | At least one blocking check failed or required evidence is missing. |

## Hook Model

If Gigacode supports hook events equivalent to Claude Code, use these:

| Event | Action |
|---|---|
| `PostToolUse` on `.yaml/.yml` | Run `scenario-lint`, `transaction-lint`, `feeder-lint`, `secret-scan`. |
| `PostToolUse` on `.java` | Run `gatling-style-lint`, `check-lint`, `correlation-lint`, compile check. |
| `PostToolUse` on `pom.xml` / `build.gradle` | Run `dependency-lint` and build-tool detection. |
| `SubagentStop` | Run read-only `validator-subagent` over changed artifacts and reports. |
| `Stop` | Block final "ready" response unless quality gate status exists. |

If hooks are unavailable, expose the same behavior through an explicit `quality-gate` command and require the agent to run it before final handoff.

## MVP Profile

The `mvp` profile is the first implementation target:

- JSON Schema validation.
- `scenario-lint`.
- `transaction-lint`.
- `check-lint`.
- `secret-scan`.
- Java compile check.
- `quality-gate-report.json`.
- `quality-gate-report.md`.

## Engineering Profile

The `engineering` profile is the target after MVP:

- All `mvp` checks.
- `correlation-lint`.
- `feeder-lint`.
- `env-lint`.
- `dependency-lint`.
- Smoke run with one virtual user where safe.
- Validator-subagent evidence review.

## Report Shape

```json
{
  "status": "passed_with_warnings",
  "profile": "mvp",
  "checked_at": "2026-06-03T00:00:00Z",
  "artifacts": [
    "examples/scenarios/login-and-search.yaml",
    "examples/generated/java/LoginAndSearchSimulation.java"
  ],
  "blocking": [],
  "warnings": [
    {
      "rule": "feeder-lint.file-not-yet-created",
      "message": "users.csv is referenced but not present in this documentation-only phase."
    }
  ],
  "waivers": []
}
```

The Markdown report mirrors this data in a compact reviewer-friendly format.


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

Route hook-like events through `tools/hook_router/hook_router.py`. The host hook
system may provide broad event delivery, but matching and quality routing live in
the repository config at `tools/hook_router/hooks.json`, not in Qwen's built-in
hook matcher.

| Event | Action |
|---|---|
| `PostToolUse` on `.yaml/.yml` | Router runs `scenario-lint`, which includes transaction, feeder, check, and secret rules. |
| `PostToolUse` on `.java`, `pom.xml`, or Gradle files | Router runs the MVP quality gate for the golden scenario/project. |
| Prompt containing readiness language | Router runs the MVP quality gate. |
| `SubagentStop` / `Stop` | Router runs the MVP quality gate and **exits non-zero when the gate is blocked** — the host must treat a non-zero router exit as "do not hand off". |

If hooks are unavailable, expose the same behavior through an explicit
`quality-gate` command and require the agent to run it before final handoff.

## MVP Profile

The `mvp` profile is the first implementation target:

- JSON Schema validation.
- `scenario-lint`.
- `transaction-lint`.
- `check-lint`.
- `secret-scan`.
- Java compile check.
- Scenario Markdown render (deterministic, committed docs must match).
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

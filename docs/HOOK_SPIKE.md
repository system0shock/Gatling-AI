# Hook Spike

## Result

Route hook-like events through `tools/hook_router/hook_router.py`.

The Phase 0 correction is that Gatling-AI should not rely on Qwen's built-in hook matcher for quality behavior. Qwen or another shell can still invoke a command when an event occurs, but the event should be passed as JSON to the repository router. The router then normalizes fields, evaluates route rules from `tools/hook_router/hooks.json`, and runs the targeted checks.

## Router Model

The router accepts event JSON from stdin or `--event-json PATH`:

```bash
python tools/hook_router/hook_router.py --event-json event.json
```

It also supports:

- `--config PATH`, defaulting to `tools/hook_router/hooks.json`.
- `--dry-run`, which prints planned matches and commands without executing checks.

The router normalizes common event schemas itself:

- Event name: `event`, `event_name`, `hook_event`
- Tool name: `tool`, `tool_name`, `toolName`
- Prompt text: `prompt`, `user_prompt`, `message`
- Paths: `files`, `changed_files`, `paths`
- Working directory: `cwd`

Rules support exact event/tool matches, prompt regexes, path globs, and simple `any`/`all` nesting. Actions run command argument lists with `shell=False` and support `{repo_root}`, `{scenario}`, and `{project}` placeholders.

## MVP Routes

The default `hooks.json` implements these blocking routes:

| Trigger | Routed Check |
|---|---|
| `PostToolUse` with changed scenario YAML | Run `tools/scenario_lint/scenario_lint.py` for matching scenario files. |
| `PostToolUse` with Java, `pom.xml`, or Gradle path | Run `tools/quality_gate/quality_gate.py` for the golden scenario/project. |
| Prompt containing `quality gate`, `проверить`, `готово`, or `финал` | Run the quality gate. |
| `Stop` or `SubagentStop` | Run the quality gate. |

The router emits a JSON summary with `status`, `matched_rules`, `commands`, and return codes. It exits non-zero when a matched blocking command fails. No-match events exit `0` unless a config marks a route as required.

The `Stop`/`SubagentStop` route is the hard gate from FR5.7.5: a blocked quality
gate makes the router exit non-zero, and the host hook integration must block the
final "ready" response on that exit code. If the host cannot block on hook exit
codes, the explicit `quality-gate` command remains the fallback and the agent
must not report readiness without a `passed`/`passed_with_warnings` report.

## Integration Guidance

Configure the host hook system to call the router broadly and pass the raw event payload. Do not encode quality routing in Qwen matcher rules beyond invoking the router.

Example:

```bash
python tools/hook_router/hook_router.py < qwen-event.json
```

For local handoff, run either the explicit quality gate or a router event that triggers it. The router exists to keep hook policy versioned in the repository alongside the checks it invokes.

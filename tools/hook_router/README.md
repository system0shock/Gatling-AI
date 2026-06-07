# Hook Router

`hook_router.py` is the Gatling-AI hook entry point. It does not rely on Qwen's built-in hook matcher. Instead, it accepts raw event JSON, normalizes the common fields, evaluates local route rules, and runs targeted checks with `subprocess` and `shell=False`.

## Usage

From the repository root:

```bash
python tools/hook_router/hook_router.py --event-json event.json
```

Or pipe an event on stdin:

```bash
python tools/hook_router/hook_router.py < event.json
```

Useful options:

- `--config PATH`: route config, default `tools/hook_router/hooks.json`.
- `--dry-run`: print matched rules and planned commands without running them.
- `--event-json PATH`: read the event from a file instead of stdin.

The command emits a JSON summary:

```json
{
  "status": "passed",
  "matched_rules": ["scenario-lint-yaml-post-tool-use"],
  "commands": [
    {
      "rule": "scenario-lint-yaml-post-tool-use",
      "argv": ["python", ".../tools/scenario_lint/scenario_lint.py", "examples/scenarios/login-and-search.yaml", "--format", "json"],
      "returncode": 0
    }
  ]
}
```

Statuses:

- `passed`: at least one route matched and all blocking commands exited `0`.
- `blocked`: a blocking matched command failed, or a config-required route was missing.
- `no_match`: no route matched. This exits `0` unless a required rule is configured.

## Event Normalization

The router supports multiple event schemas by inspecting the event payload itself:

- Event name: `event`, `event_name`, `hook_event`
- Tool name: `tool`, `tool_name`, `toolName`
- Prompt text: `prompt`, `user_prompt`, `message`
- Paths: `files`, `changed_files`, `paths`
- Working directory: `cwd`

Nested objects are searched too, so a wrapper payload can pass through request or tool data without Qwen pre-filtering it.

## Rule Format

Rules live in `hooks.json`:

```json
{
  "id": "quality-gate-ready-prompt",
  "blocking": true,
  "when": {
    "prompt_regex": ["quality\\s+gate", "готово"]
  },
  "action": {
    "commands": [
      ["python", "{repo_root}/tools/quality_gate/quality_gate.py", "--scenario", "{scenario}", "--project", "{project}"]
    ]
  }
}
```

Supported conditions:

- `events`: exact match against the normalized event name.
- `tools`: exact match against the normalized tool name.
- `prompt_regex`: one regex or a list of regexes matched against prompt text.
- `path_globs`: one or more repository-relative glob patterns.
- `any`: at least one nested condition must match.
- `all`: every nested condition must match.

When top-level conditions are listed together, they are treated as `all`.

Supported placeholders:

- `{repo_root}`: resolved repository root.
- `{scenario}`: matched scenario path for scenario routes, otherwise the configured golden scenario.
- `{project}`: configured generated Java project path.

`{python}` is also available for tests or custom configs that need the current interpreter.

## MVP Routes

The default config includes:

- YAML scenario changes on `PostToolUse` run `tools/scenario_lint/scenario_lint.py` for each matching scenario file.
- Java, `pom.xml`, or Gradle changes on `PostToolUse` run `tools/quality_gate/quality_gate.py` for the golden scenario/project.
- Prompts containing `quality gate`, `проверить`, `готово`, or `финал` run the quality gate.
- `Stop` and `SubagentStop` events run the quality gate.

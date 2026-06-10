#!/usr/bin/env python3
"""Route hook-like event JSON to targeted Gatling-AI checks."""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

FIELD_EVENT = ("event", "event_name", "hook_event")
FIELD_TOOL = ("tool", "tool_name", "toolName")
FIELD_PROMPT = ("prompt", "user_prompt", "message")
FIELD_FILES = ("files", "changed_files", "paths")
FIELD_CWD = ("cwd",)


class ConfigError(ValueError):
    """Raised when a route config cannot be expanded safely."""


@dataclass(frozen=True)
class NormalizedEvent:
    event: str
    tool: str
    prompt: str
    files: list[str]
    cwd: str


def find_repo_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    if current.is_file():
        current = current.parent
    for directory in (current, *current.parents):
        if (directory / ".git").exists():
            return directory
    return Path.cwd().resolve()


def iter_key_values(value: Any) -> Any:
    if isinstance(value, dict):
        for key, child in value.items():
            yield key, child
            yield from iter_key_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_key_values(child)


def first_field(payload: Any, names: tuple[str, ...]) -> Any:
    first_seen: Any = None
    if isinstance(payload, dict):
        for name in names:
            if name in payload:
                value = payload[name]
                if first_seen is None:
                    first_seen = value
                if stringify(value):
                    return value
    for key, value in iter_key_values(payload):
        if key in names:
            if first_seen is None:
                first_seen = value
            if stringify(value):
                return value
    return first_seen


def stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        for key in ("name", "id", "value", "text", "content"):
            if key in value:
                return stringify(value[key])
    return ""


def collect_paths(value: Any) -> list[str]:
    paths: list[str] = []
    if isinstance(value, str):
        paths.append(value)
    elif isinstance(value, dict):
        path_keys = [key for key in ("path", "file", "name") if key in value]
        if path_keys:
            for key in path_keys:
                paths.extend(collect_paths(value[key]))
            return paths
        for child in value.values():
            paths.extend(collect_paths(child))
    elif isinstance(value, list):
        for child in value:
            paths.extend(collect_paths(child))
    return paths


def normalize_path(path: str, repo_root: Path, cwd: str) -> str:
    repo_root = repo_root.resolve()
    cwd_path = Path(cwd) if cwd else repo_root
    cwd_root = cwd_path if cwd_path.is_absolute() else repo_root / cwd_path
    cwd_root = cwd_root.resolve()
    raw = Path(path)
    target = raw if raw.is_absolute() else cwd_root / raw
    target = target.resolve()
    try:
        return target.relative_to(repo_root).as_posix()
    except ValueError:
        return target.as_posix()


def normalize_event(payload: dict[str, Any], repo_root: Path) -> NormalizedEvent:
    cwd = stringify(first_field(payload, FIELD_CWD)) or str(repo_root.resolve())
    files: list[str] = []
    for key, value in iter_key_values(payload):
        if key in FIELD_FILES:
            files.extend(collect_paths(value))
    if isinstance(payload, dict):
        for key in FIELD_FILES:
            if key in payload:
                files.extend(collect_paths(payload[key]))
    normalized_files = sorted(
        {normalize_path(path, repo_root, cwd) for path in files if path and not path.isspace()}
    )
    return NormalizedEvent(
        event=stringify(first_field(payload, FIELD_EVENT)),
        tool=stringify(first_field(payload, FIELD_TOOL)),
        prompt=stringify(first_field(payload, FIELD_PROMPT)),
        files=normalized_files,
        cwd=cwd,
    )


def load_event(args: argparse.Namespace) -> dict[str, Any]:
    if args.event_json:
        return json.loads(Path(args.event_json).read_text(encoding="utf-8-sig"))
    text = sys.stdin.read()
    if not text.strip():
        return {}
    return json.loads(text)


def load_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def values_match(actual: str, expected: list[str]) -> bool:
    return bool(actual) and actual in expected


def regex_matches(text: str, patterns: str | list[str]) -> bool:
    if isinstance(patterns, str):
        patterns = [patterns]
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def glob_matches(files: list[str], patterns: list[str]) -> list[str]:
    matches: list[str] = []
    for path in files:
        normalized = Path(path).as_posix()
        if any(fnmatch.fnmatchcase(normalized, pattern) for pattern in patterns):
            matches.append(normalized)
    return sorted(set(matches))


def match_condition(condition: dict[str, Any], event: NormalizedEvent) -> tuple[bool, list[str]]:
    matched_paths: list[str] = []

    if "any" in condition:
        any_matches = [match_condition(child, event) for child in condition["any"]]
        true_matches = [paths for ok, paths in any_matches if ok]
        if not true_matches:
            return False, []
        for paths in true_matches:
            matched_paths.extend(paths)

    if "all" in condition:
        all_paths: list[str] = []
        for child in condition["all"]:
            ok, paths = match_condition(child, event)
            if not ok:
                return False, []
            all_paths.extend(paths)
        matched_paths.extend(all_paths)

    if "events" in condition and not values_match(event.event, condition["events"]):
        return False, []
    if "tools" in condition and not values_match(event.tool, condition["tools"]):
        return False, []
    if "prompt_regex" in condition and not regex_matches(event.prompt, condition["prompt_regex"]):
        return False, []
    if "path_globs" in condition:
        paths = glob_matches(event.files, condition["path_globs"])
        if not paths:
            return False, []
        matched_paths.extend(paths)

    return True, sorted(set(matched_paths))


def resolve_config_path(path: Path) -> Path:
    if path.is_absolute():
        return path
    return find_repo_root(Path.cwd()) / path


def context_value(
    name: str,
    defaults: dict[str, Any],
    action: dict[str, Any],
    repo_root: Path,
    scenario: str | None,
) -> str:
    if name == "repo_root":
        return str(repo_root)
    if name == "scenario":
        value = scenario or str(action.get("scenario") or defaults.get("scenario") or "")
        if not value:
            raise ConfigError(
                "placeholder {scenario} has no value: set action.scenario or defaults.scenario"
            )
        return value
    if name == "project":
        value = str(action.get("project") or defaults.get("project") or "")
        if not value:
            raise ConfigError(
                "placeholder {project} has no value: set action.project or defaults.project"
            )
        return value
    if name == "python":
        return sys.executable
    raise ConfigError(f"unknown placeholder {{{name}}}")


def expand_arg(
    value: str,
    defaults: dict[str, Any],
    action: dict[str, Any],
    repo_root: Path,
    scenario: str | None,
) -> str:
    def replace(match: re.Match[str]) -> str:
        return context_value(match.group(1), defaults, action, repo_root, scenario)

    return PLACEHOLDER_RE.sub(replace, value)


def command_placeholders(commands: Any) -> set[str]:
    names: set[str] = set()
    if isinstance(commands, list):
        for command in commands:
            if isinstance(command, list):
                for arg in command:
                    if isinstance(arg, str):
                        names.update(PLACEHOLDER_RE.findall(arg))
    return names


def command_scenarios(
    action: dict[str, Any], defaults: dict[str, Any], matched_paths: list[str]
) -> list[str | None]:
    if action.get("foreach") == "matched_paths":
        return matched_paths or [None]
    configured = action.get("scenario") or defaults.get("scenario")
    if (
        "scenario" in command_placeholders(action.get("commands", []))
        and matched_paths
        and not configured
    ):
        return matched_paths
    return [str(configured)] if configured else [None]


def build_commands(
    rule: dict[str, Any],
    defaults: dict[str, Any],
    repo_root: Path,
    matched_paths: list[str],
) -> list[list[str]]:
    action = rule.get("action", {})
    commands = action.get("commands", [])
    built: list[list[str]] = []
    for scenario in command_scenarios(action, defaults, matched_paths):
        for command in commands:
            if not isinstance(command, list) or not all(isinstance(arg, str) for arg in command):
                raise ValueError(f"rule {rule.get('id', '<unnamed>')} command must be a list of strings")
            built.append([expand_arg(arg, defaults, action, repo_root, scenario) for arg in command])
    return built


def run_command(argv: list[str], cwd: Path) -> dict[str, Any]:
    try:
        result = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            shell=False,
        )
        return {
            "argv": argv,
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    except Exception as exc:
        return {"argv": argv, "returncode": 127, "stdout": "", "stderr": str(exc)}


def route_event(event_payload: dict[str, Any], config_path: Path, dry_run: bool = False) -> dict[str, Any]:
    config = load_config(config_path)
    config_root = config_path.parent
    configured_root = config.get("defaults", {}).get("repo_root")
    repo_root = Path(configured_root).resolve() if configured_root else find_repo_root(config_root)
    defaults = dict(config.get("defaults", {}))
    event = normalize_event(event_payload, repo_root)

    matched_rules: list[str] = []
    command_results: list[dict[str, Any]] = []
    blocked = False

    for rule in config.get("rules", []):
        ok, matched_paths = match_condition(rule.get("when", {}), event)
        if not ok:
            continue
        rule_id = str(rule.get("id", "<unnamed>"))
        matched_rules.append(rule_id)
        try:
            commands = build_commands(rule, defaults, repo_root, matched_paths)
        except ConfigError as exc:
            blocked = True
            error_result: dict[str, Any] = {
                "rule": rule_id,
                "returncode": 127,
                "stdout": "",
                "stderr": str(exc),
            }
            if dry_run:
                error_result["dry_run"] = True
            command_results.append(error_result)
            continue
        for argv in commands:
            if dry_run:
                command_results.append(
                    {
                        "rule": rule_id,
                        "argv": argv,
                        "returncode": None,
                        "dry_run": True,
                    }
                )
                continue
            result = run_command(argv, repo_root)
            result["rule"] = rule_id
            command_results.append(result)
            if rule.get("blocking", True) and result["returncode"] != 0:
                blocked = True

    required_rules = [str(rule.get("id", "<unnamed>")) for rule in config.get("rules", []) if rule.get("required")]
    missing_required = sorted(set(required_rules) - set(matched_rules))
    if not matched_rules and required_rules:
        blocked = True

    if not matched_rules:
        status = "blocked" if blocked else "no_match"
    else:
        status = "blocked" if blocked else "passed"

    return {
        "status": status,
        "matched_rules": matched_rules,
        "missing_required_rules": missing_required if blocked else [],
        "commands": command_results,
        "event": {
            "event": event.event,
            "tool": event.tool,
            "prompt": event.prompt,
            "files": event.files,
            "cwd": event.cwd,
        },
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Route hook event JSON to Gatling-AI checks.")
    parser.add_argument("--event-json", type=Path, help="path to event JSON; stdin is used when omitted")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("tools/hook_router/hooks.json"),
        help="route config path",
    )
    parser.add_argument("--dry-run", action="store_true", help="print planned matches without executing")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config_path = resolve_config_path(args.config)
    event_payload = load_event(args)
    summary = route_event(event_payload, config_path, dry_run=args.dry_run)
    print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))
    return 1 if summary["status"] == "blocked" else 0


if __name__ == "__main__":
    sys.exit(main())

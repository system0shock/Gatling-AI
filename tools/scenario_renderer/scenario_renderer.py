#!/usr/bin/env python3
"""Render Gatling-AI scenario YAML into reviewer-friendly Markdown."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _shared.common import find_repo_root, load_yaml, rel_path, variables_in  # noqa: E402


# Contract coverage declarations: every schema field path is either consumed by
# this renderer or explicitly ignored with a reason. Checked by
# tools/test_contract_coverage.py. request.headers/body count as consumed
# because step_variables reads them for the correlations table.
CONSUMED_FIELDS = {
    "scenario",
    "scenario.id",
    "scenario.title",
    "scenario.source",
    "scenario.source.type",
    "scenario.source.ref",
    "scenario.sut",
    "scenario.sut.base_url",
    "scenario.data",
    "scenario.data.feeders",
    "scenario.data.feeders[].name",
    "scenario.data.feeders[].file",
    "scenario.data.feeders[].strategy",
    "scenario.steps",
    "scenario.steps[].name",
    "scenario.steps[].transaction",
    "scenario.steps[].request",
    "scenario.steps[].request.method",
    "scenario.steps[].request.path",
    "scenario.steps[].request.headers",
    "scenario.steps[].request.body",
    "scenario.steps[].pause_seconds",
    "scenario.steps[].checks",
    "scenario.steps[].checks[].status",
    "scenario.steps[].checks[].extract",
    "scenario.steps[].checks[].extract.type",
    "scenario.steps[].checks[].extract.expr",
    "scenario.steps[].checks[].extract.saveAs",
    "scenario.load",
    "scenario.load.model",
    "scenario.load.profile",
    "scenario.load.users",
    "scenario.load.ramp_seconds",
    "scenario.load.duration_seconds",
    "scenario.load.users_per_second",
    "scenario.load.levels",
    "scenario.load.level_duration_seconds",
    "scenario.load.baseline_users",
    "scenario.load.baseline_users_per_second",
    "scenario.load.baseline_seconds",
    "scenario.load.spike_rise_seconds",
    "scenario.load.spike_hold_seconds",
    "scenario.assertions",
    "scenario.assertions[].name",
    "scenario.assertions[].metric",
    "scenario.assertions[].op",
    "scenario.assertions[].value",
}
IGNORED_FIELDS = {
    "scenario.steps[].title",  # transaction is the reviewer-facing label
    "scenario.steps[].protocol",  # MVP is http-only; schema enum guarantees it
    "lint_waivers",  # rendered by the quality gate report, not the doc
    "lint_waivers[].rule",
    "lint_waivers[].reason",
    "lint_waivers[].owner",
    "lint_waivers[].expires",
}


def source_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def md_escape(value: Any) -> str:
    return str(value).replace("|", "\\|")


def checks_summary(step: dict[str, Any]) -> str:
    parts: list[str] = []
    for check in step.get("checks", []) or []:
        if not isinstance(check, dict):
            continue
        if "status" in check:
            parts.append(f"status {check['status']}")
        elif isinstance(check.get("extract"), dict):
            extract = check["extract"]
            parts.append(f"extract `{extract.get('saveAs', '?')}` ({extract.get('type', '?')})")
    return ", ".join(parts) or "—"


def pause_summary(step: dict[str, Any]) -> str:
    pause = step.get("pause_seconds")
    if isinstance(pause, (int, float)) and not isinstance(pause, bool):
        display = int(pause) if float(pause) == int(pause) else pause
        return f"{display} с"
    return "—"


def load_target(load: dict[str, Any]) -> tuple[str, str]:
    """Return (target, unit) for the load model."""
    if load.get("model") == "open":
        return str(load.get("users_per_second", "?")), "запросов/с"
    return str(load.get("users", "?")), "пользователей"


def load_description(load: dict[str, Any]) -> str:
    model = load.get("model", "?")
    profile = load.get("profile", "?")
    target, unit = load_target(load)
    prefix = f"Модель: **{model}**, профиль: **{profile}**. "
    if profile == "ramp":
        return prefix + (
            f"Разгон до **{target} {unit}** за **{load.get('ramp_seconds', '?')} с**, "
            f"полка **{load.get('duration_seconds', '?')} с**."
        )
    if profile in {"constant", "soak"}:
        suffix = " (soak: длительное удержание)" if profile == "soak" else ""
        return prefix + (
            f"Постоянная нагрузка **{target} {unit}** в течение "
            f"**{load.get('duration_seconds', '?')} с**{suffix}."
        )
    if profile == "stress":
        # target intentionally not bolded: "до 10 пользователей" reads as a range endpoint
        return prefix + (
            f"Ступенчатый рост: **{load.get('levels', '?')} уровней по "
            f"{load.get('level_duration_seconds', '?')} с** до {target} {unit}."
        )
    if profile == "spike":
        baseline = (
            load.get("baseline_users_per_second", "?")
            if load.get("model") == "open"
            else load.get("baseline_users", "?")
        )
        return prefix + (
            f"Базлайн **{baseline} {unit}** ({load.get('baseline_seconds', '?')} с) → "
            f"всплеск до **{target} {unit}** за {load.get('spike_rise_seconds', '?')} с, "
            f"удержание {load.get('spike_hold_seconds', '?')} с, симметричный возврат."
        )
    return prefix.rstrip()


def step_variables(step: dict[str, Any]) -> set[str]:
    request = step.get("request") if isinstance(step.get("request"), dict) else {}
    return variables_in(
        {
            "path": request.get("path"),
            "headers": request.get("headers"),
            "body": request.get("body"),
        }
    )


def variable_sources(scenario: dict[str, Any]) -> dict[str, str]:
    sources: dict[str, str] = {}
    data = scenario.get("data") if isinstance(scenario.get("data"), dict) else {}
    feeders = data.get("feeders") if isinstance(data.get("feeders"), list) else []
    for feeder in feeders:
        if isinstance(feeder, dict) and feeder.get("name"):
            sources[str(feeder["name"])] = f"фидер `{feeder.get('file', '?')}`"
    for step in scenario.get("steps", []) or []:
        if not isinstance(step, dict):
            continue
        for check in step.get("checks", []) or []:
            if isinstance(check, dict) and isinstance(check.get("extract"), dict):
                save_as = check["extract"].get("saveAs")
                if isinstance(save_as, str):
                    sources[save_as] = f"извлекается в шаге `{step.get('name', '?')}`"
    return sources


def correlation_rows(scenario: dict[str, Any]) -> list[tuple[str, str, str]]:
    sources = variable_sources(scenario)
    data = scenario.get("data") if isinstance(scenario.get("data"), dict) else {}
    feeders = data.get("feeders") if isinstance(data.get("feeders"), list) else []
    feeder_names = {
        str(feeder.get("name")) for feeder in feeders if isinstance(feeder, dict)
    }
    usage: dict[str, list[str]] = {}
    for step in scenario.get("steps", []) or []:
        if not isinstance(step, dict):
            continue
        for variable in step_variables(step):
            usage.setdefault(variable, []).append(str(step.get("name", "?")))
    rows: list[tuple[str, str, str]] = []
    for variable in sorted(usage):
        base = variable.split(".", 1)[0]
        if base in feeder_names:
            if "." in variable:
                source = f"{sources[base]} (колонка `{variable.split('.', 1)[1]}`)"
            else:
                source = sources[base]
        elif variable in sources:
            source = sources[variable]
        else:
            source = "переменная окружения / feeder-колонка"
        rows.append(
            (
                variable,
                source,
                ", ".join(f"`{name}`" for name in sorted(set(usage[variable]))),
            )
        )
    return rows


def render_markdown(document: dict[str, Any], source_name: str, digest: str) -> str:
    scenario = document["scenario"]
    steps = scenario.get("steps", []) or []
    load = scenario.get("load", {}) or {}
    data = scenario.get("data") if isinstance(scenario.get("data"), dict) else {}
    feeders = data.get("feeders") if isinstance(data.get("feeders"), list) else []
    assertions = scenario.get("assertions", []) or []
    source = scenario.get("source", {}) or {}

    lines = [
        f"# Сценарий: {scenario.get('title', scenario.get('id', '?'))}",
        "",
        f"> Сгенерировано из `{source_name}` (sha256 `{digest}`). Не редактировать вручную.",
        "",
        "## Паспорт",
        "",
        f"- **ID:** `{scenario.get('id', '?')}`",
        f"- **Источник требований:** {source.get('type', '?')} / `{source.get('ref', '?')}`",
        f"- **Базовый URL:** `{scenario.get('sut', {}).get('base_url', '?')}`",
        "",
        "## Шаги",
        "",
        "| # | Транзакция | Метод | Путь | Пауза | Проверки |",
        "|---|---|---|---|---|---|",
    ]
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            continue
        request = step.get("request") if isinstance(step.get("request"), dict) else {}
        lines.append(
            f"| {index} | {md_escape(step.get('transaction', step.get('name', '?')))} "
            f"| {md_escape(str(request.get('method', '?')).upper())} "
            f"| {md_escape(request.get('path', '?'))} "
            f"| {md_escape(pause_summary(step))} "
            f"| {md_escape(checks_summary(step))} |"
        )

    lines.extend(["", "## Тестовые данные", ""])
    if feeders:
        lines.extend(["| Фидер | Файл | Стратегия |", "|---|---|---|"])
        for feeder in feeders:
            if isinstance(feeder, dict):
                lines.append(
                    f"| {md_escape(feeder.get('name', '?'))} | `{feeder.get('file', '?')}` "
                    f"| {md_escape(feeder.get('strategy', '?'))} |"
                )
    else:
        lines.append("Фидеры не используются.")

    lines.extend(
        [
            "",
            "## Профиль нагрузки",
            "",
            load_description(load),
            "",
            "## Корреляции и переменные",
            "",
        ]
    )
    rows = correlation_rows(scenario)
    if rows:
        lines.extend(["| Переменная | Источник | Используется в шагах |", "|---|---|---|"])
        lines.extend(f"| `{name}` | {source} | {used} |" for name, source, used in rows)
    else:
        lines.append("Сессионные переменные не используются.")

    lines.extend(["", "## SLA (assertions)", ""])
    if assertions:
        lines.extend(["| Имя | Метрика | Условие |", "|---|---|---|"])
        for assertion in assertions:
            if isinstance(assertion, dict):
                lines.append(
                    f"| {md_escape(assertion.get('name', '?'))} | `{assertion.get('metric', '?')}` "
                    f"| {md_escape(assertion.get('op', '?'))} {md_escape(assertion.get('value', '?'))} |"
                )
    else:
        lines.append("SLA не заданы.")

    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render scenario YAML to reviewer Markdown")
    parser.add_argument("scenario", type=Path, help="scenario YAML file")
    parser.add_argument("--output", type=Path, help="output .md path; stdout when omitted")
    args = parser.parse_args(argv)

    repo_root = find_repo_root(args.scenario)
    try:
        document = load_yaml(args.scenario)
        if not isinstance(document, dict) or not isinstance(document.get("scenario"), dict):
            raise ValueError("scenario root is required")
        content = render_markdown(
            document, rel_path(args.scenario, repo_root), source_digest(args.scenario)
        )
    except Exception as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 1

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8", newline="\n")
        print(args.output.as_posix())
    else:
        print(content, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Render Gatling-AI scenario YAML into reviewer-friendly Markdown."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _shared.common import find_repo_root, load_yaml, rel_path, scenario_populations, script_ref, variables_in  # noqa: E402


# Contract coverage declarations: every schema field path is either consumed by
# this renderer or explicitly ignored with a reason. Checked by
# tools/test_contract_coverage.py. request.headers/body count as consumed
# because step_variables reads them for the correlations table.
STEP_LOAD_CONSUMED = {
    "steps",
    "steps[].name",
    "steps[].transaction",
    "steps[].protocol",
    "steps[].pause_seconds",
    "steps[].request",
    "steps[].request.method",
    "steps[].request.path",
    "steps[].request.headers",
    "steps[].request.body",
    "steps[].request.body_file",
    "steps[].graphql",
    "steps[].graphql.path",
    "steps[].graphql.query",
    "steps[].graphql.variables",
    "steps[].tags",
    "steps[].checks",
    "steps[].checks[].status",
    "steps[].checks[].extract",
    "steps[].checks[].extract.type",
    "steps[].checks[].extract.expr",
    "steps[].checks[].extract.saveAs",
    "load",
    "load.model",
    "load.profile",
    "load.users",
    "load.users_per_second",
    "load.ramp_seconds",
    "load.duration_seconds",
    "load.levels",
    "load.level_duration_seconds",
    "load.baseline_users",
    "load.baseline_users_per_second",
    "load.baseline_seconds",
    "load.spike_rise_seconds",
    "load.spike_hold_seconds",
    "load.stages",
    "load.stages[].users",
    "load.stages[].users_per_second",
    "load.stages[].ramp_seconds",
    "load.stages[].hold_seconds",
}
STEP_LOAD_IGNORED = {
    "steps[].title",  # transaction is the reviewer-facing label
}


def _expand(prefix: str, fields: set[str]) -> set[str]:
    return {f"{prefix}{field}" for field in fields}


CONSUMED_FIELDS = (
    {
        "scenario",
        "scenario.id",
        "scenario.title",
        "scenario.system",
        "scenario.number",
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
        "scenario.populations",
        "scenario.populations[].name",
        "scenario.assertions",
        "scenario.assertions[].name",
        "scenario.assertions[].metric",
        "scenario.assertions[].op",
        "scenario.assertions[].value",
    }
    | _expand("scenario.", STEP_LOAD_CONSUMED)
    | _expand("scenario.populations[].", STEP_LOAD_CONSUMED)
)
IGNORED_FIELDS = (
    {
        "lint_waivers",  # rendered by the quality gate report, not the doc
        "lint_waivers[].rule",
        "lint_waivers[].reason",
        "lint_waivers[].owner",
        "lint_waivers[].expires",
    }
    | _expand("scenario.", STEP_LOAD_IGNORED)
    | _expand("scenario.populations[].", STEP_LOAD_IGNORED)
)


def source_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def md_escape(value: Any) -> str:
    return str(value).replace("|", "\\|")


def tags_summary(step: dict[str, Any]) -> str:
    tags = step.get("tags")
    if isinstance(tags, list) and tags:
        return ", ".join(str(tag) for tag in tags)
    return "—"


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
    if profile == "stages":
        stages = load.get("stages") if isinstance(load.get("stages"), list) else []
        unit = "запросов/с" if model == "open" else "пользователей"
        parts: list[str] = []
        for stage in stages:
            if not isinstance(stage, dict):
                continue
            target = stage.get("users") if model == "closed" else stage.get("users_per_second")
            if target is None:
                target = "?"
            ramp = stage.get("ramp_seconds", 0)
            hold = stage.get("hold_seconds", 0)
            bits = []
            if ramp:
                bits.append(f"разгон до {target} {unit} за {ramp} с")
            else:
                bits.append(f"скачок до {target} {unit}")
            if hold:
                bits.append(f"полка {hold} с")
            parts.append(", ".join(bits))
        numbered = "; ".join(f"{index}) {part}" for index, part in enumerate(parts, start=1))
        return prefix + f"Ступени: {numbered}."
    return prefix.rstrip()


def step_method_and_path(step: dict[str, Any]) -> tuple[str, str]:
    if step.get("protocol") == "graphql":
        graphql = step.get("graphql") if isinstance(step.get("graphql"), dict) else {}
        return "POST", str(graphql.get("path", "/graphql"))
    request = step.get("request") if isinstance(step.get("request"), dict) else {}
    return str(request.get("method", "?")).upper(), str(request.get("path", "?"))


def graphql_query_lines(steps: list[Any]) -> list[str]:
    lines: list[str] = []
    for step in steps:
        if not isinstance(step, dict) or step.get("protocol") != "graphql":
            continue
        graphql = step.get("graphql") if isinstance(step.get("graphql"), dict) else {}
        lines.extend(
            [
                "",
                f"### GraphQL-запросы: `{step.get('name', '?')}`",
                "",
                "```graphql",
                str(graphql.get("query", "")),
                "```",
            ]
        )
    return lines


def all_steps(scenario: dict[str, Any]) -> list[Any]:
    steps: list[Any] = []
    for population in scenario_populations(scenario):
        population_steps = population.get("steps")
        if isinstance(population_steps, list):
            steps.extend(population_steps)
    return steps


def steps_table_lines(steps: list[Any], heading: str) -> list[str]:
    lines = [
        heading,
        "",
        "| # | Транзакция | Метод | Путь | Пауза | Проверки | Теги |",
        "|---|---|---|---|---|---|---|",
    ]
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            continue
        method, path = step_method_and_path(step)
        lines.append(
            f"| {index} | {md_escape(step.get('transaction', step.get('name', '?')))} "
            f"| {md_escape(method)} "
            f"| {md_escape(path)} "
            f"| {md_escape(pause_summary(step))} "
            f"| {md_escape(checks_summary(step))} "
            f"| {md_escape(tags_summary(step))} |"
        )
    lines.extend(graphql_query_lines(steps))
    lines.extend(body_file_lines(steps))
    return lines


def body_file_lines(steps: list[Any]) -> list[str]:
    rows = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        request = step.get("request") if isinstance(step.get("request"), dict) else {}
        if isinstance(request.get("body_file"), str):
            rows.append((str(step.get("name", "?")), request["body_file"]))
    if not rows:
        return []
    lines = ["", "### Тела запросов", "", "| Шаг | Файл тела |", "|---|---|"]
    lines.extend(f"| `{name}` | `{file}` |" for name, file in rows)
    return lines


def step_variables(step: dict[str, Any]) -> set[str]:
    request = step.get("request") if isinstance(step.get("request"), dict) else {}
    graphql = step.get("graphql") if isinstance(step.get("graphql"), dict) else {}
    return variables_in(
        {
            "path": request.get("path"),
            "headers": request.get("headers"),
            "body": request.get("body"),
            "graphql_path": graphql.get("path"),
            "graphql_query": graphql.get("query"),
            "graphql_variables": graphql.get("variables"),
        }
    )


def variable_sources(scenario: dict[str, Any]) -> dict[str, str]:
    sources: dict[str, str] = {}
    data = scenario.get("data") if isinstance(scenario.get("data"), dict) else {}
    feeders = data.get("feeders") if isinstance(data.get("feeders"), list) else []
    for feeder in feeders:
        if isinstance(feeder, dict) and feeder.get("name"):
            sources[str(feeder["name"])] = f"фидер `{feeder.get('file', '?')}`"
    for step in all_steps(scenario):
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
    for step in all_steps(scenario):
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


def script_ref_display(scenario: dict[str, Any]) -> str:
    system = scenario.get("system")
    number = scenario.get("number")
    scenario_id = scenario.get("id")
    if (
        isinstance(system, str)
        and isinstance(scenario_id, str)
        and isinstance(number, int)
        and not isinstance(number, bool)
        and number >= 1
    ):
        return script_ref(system, scenario_id, number)
    return "?"


def render_markdown(document: dict[str, Any], source_name: str, digest: str) -> str:
    scenario = document["scenario"]
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
        f"- **Скрипт:** `{script_ref_display(scenario)}`",
        f"- **Источник требований:** {source.get('type', '?')} / `{source.get('ref', '?')}`",
        f"- **Базовый URL:** `{scenario.get('sut', {}).get('base_url', '?')}`",
    ]

    populations = (
        scenario.get("populations") if isinstance(scenario.get("populations"), list) else None
    )
    if populations is None:
        steps = scenario.get("steps", []) or []
        lines.extend(["", *steps_table_lines(steps, "## Шаги")])
        lines.extend(["", "## Профиль нагрузки", "", load_description(load)])
    else:
        for population in populations:
            if not isinstance(population, dict):
                continue
            lines.extend(["", f"## Популяция: `{population.get('name', '?')}`"])
            population_steps = (
                population.get("steps") if isinstance(population.get("steps"), list) else []
            )
            lines.extend(["", *steps_table_lines(population_steps, "### Шаги")])
            population_load = (
                population.get("load") if isinstance(population.get("load"), dict) else {}
            )
            lines.extend(["", "### Профиль нагрузки", "", load_description(population_load)])

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
    parser.add_argument(
        "--output",
        type=Path,
        help="output .md path (default: passport.md next to the scenario)",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="print Markdown to stdout instead of writing a file",
    )
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

    if args.stdout:
        print(content, end="")
    else:
        output = args.output if args.output else args.scenario.parent / "passport.md"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content, encoding="utf-8", newline="\n")
        print(output.as_posix())
    return 0


if __name__ == "__main__":
    sys.exit(main())

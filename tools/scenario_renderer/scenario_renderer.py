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
    "steps[].kafka",
    "steps[].kafka.topic",
    "steps[].kafka.key",
    "steps[].kafka.payload",
    "steps[].jdbc",
    "steps[].jdbc.query",
    "steps[].jdbc.saveAs",
    "steps[].tags",
    "steps[].hooks",
    "steps[].hooks.before",
    "steps[].hooks.before[].ref",
    "steps[].hooks.before[].kind",
    "steps[].hooks.before[].snippet",
    "steps[].hooks.before[].summary",
    "steps[].hooks.before[].reads",
    "steps[].hooks.before[].writes",
    "steps[].hooks.after",
    "steps[].hooks.after[].ref",
    "steps[].hooks.after[].kind",
    "steps[].hooks.after[].snippet",
    "steps[].hooks.after[].summary",
    "steps[].hooks.after[].reads",
    "steps[].hooks.after[].writes",
    "steps[].hooks.before[].hints",
    "steps[].hooks.before[].hints[].kind",
    "steps[].hooks.after[].hints",
    "steps[].hooks.after[].hints[].kind",
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
        "scenario.data.feeders[].delimiter",
        "scenario.data.feeders[].ignore_first_line",
        "scenario.data.feeders[].quoted_text",
        "scenario.data.feeders[].share_mode",
        "scenario.data.feeders[].recycle",
        "scenario.data.feeders[].random_order",
        "scenario.populations",
        "scenario.populations[].name",
        "scenario.populations[].start_after_seconds",
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
        "scenario.lifecycle",  # lifecycle gate toggle; not rendered into the doc
        "scenario.protocols",
        "scenario.protocols.kafka",
        "scenario.protocols.kafka.bootstrap_servers",
        "scenario.protocols.kafka.properties",
        "scenario.protocols.jdbc",
        "scenario.protocols.jdbc.url",
        "scenario.protocols.jdbc.username",
        "scenario.protocols.jdbc.password",
        "scenario.protocols.jdbc.maximum_pool_size",
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
    if step.get("protocol") == "kafka":
        kafka = step.get("kafka") if isinstance(step.get("kafka"), dict) else {}
        return "KAFKA", f"topic `{kafka.get('topic', '?')}`"
    if step.get("protocol") == "jdbc":
        jdbc = step.get("jdbc") if isinstance(step.get("jdbc"), dict) else {}
        query = " ".join(str(jdbc.get("query", "?")).split())
        if len(query) > 60:
            query = query[:59] + "…"
        return "JDBC", query
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
    lines.extend(hooks_lines(steps))
    return lines


def _format_hint(hint: dict[str, Any]) -> str:
    kind = hint.get("kind", "?")
    parts = [kind]
    for key in ("var", "expr", "fifo", "save_as", "timeout", "key", "method", "level", "summary", "value"):
        if key in hint and hint[key] is not None:
            val = str(hint[key])
            if len(val) > 40:
                val = val[:37] + "..."
            parts.append(f"{key}={val}")
    return ", ".join(parts)


def hooks_lines(steps: list[Any]) -> list[str]:
    rows: list[tuple[str, str, str, str, str, str, str, str, list[Any] | None]] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        hooks = step.get("hooks") if isinstance(step.get("hooks"), dict) else {}
        for when in ("before", "after"):
            for hook in hooks.get(when) or []:
                if not isinstance(hook, dict):
                    continue
                reads = hook.get("reads")
                writes = hook.get("writes")
                hints = hook.get("hints") if isinstance(hook.get("hints"), list) else None
                rows.append(
                    (
                        str(step.get("name", "?")),
                        when,
                        str(hook.get("kind", "?")),
                        str(hook.get("summary", "?")),
                        ", ".join(reads) if isinstance(reads, list) and reads else "—",
                        ", ".join(writes) if isinstance(writes, list) and writes else "—",
                        str(hook.get("ref", "?")),
                        str(hook.get("snippet")) if hook.get("snippet") else "—",
                        hints,
                    )
                )
    if not rows:
        return []
    lines = [
        "",
        "### JSR223-хуки",
        "",
        "| Шаг | Когда | Тип | Что делает | Читает | Пишет | Оригинал | Сниппет |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, when, kind, summary, reads, writes, ref, snippet, hints in rows:
        snippet_cell = f"`{md_escape(snippet)}`" if snippet != "—" else "—"
        lines.append(
            f"| `{md_escape(name)}` | {when} | {kind} | {md_escape(summary)} | {md_escape(reads)} "
            f"| {md_escape(writes)} | `{md_escape(ref)}` | {snippet_cell} |"
        )
        if hints:
            formatted = "; ".join(_format_hint(h) for h in hints if isinstance(h, dict))
            if formatted:
                lines.append(f"| | | Намерения: {md_escape(formatted)} | | | | | |")
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
    kafka = step.get("kafka") if isinstance(step.get("kafka"), dict) else {}
    jdbc = step.get("jdbc") if isinstance(step.get("jdbc"), dict) else {}
    return variables_in(
        {
            "path": request.get("path"),
            "headers": request.get("headers"),
            "body": request.get("body"),
            "graphql_path": graphql.get("path"),
            "graphql_query": graphql.get("query"),
            "graphql_variables": graphql.get("variables"),
            "kafka_topic": kafka.get("topic"),
            "kafka_key": kafka.get("key"),
            "kafka_payload": kafka.get("payload"),
            "jdbc_query": jdbc.get("query"),
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
    for step in all_steps(scenario):
        if not isinstance(step, dict):
            continue
        hooks = step.get("hooks") if isinstance(step.get("hooks"), dict) else {}
        for when in ("before", "after"):
            for hook in hooks.get(when) or []:
                if isinstance(hook, dict):
                    for written in hook.get("writes") or []:
                        if isinstance(written, str):
                            sources[written] = f"пишется хуком шага `{step.get('name', '?')}`"
    for step in all_steps(scenario):
        if not isinstance(step, dict):
            continue
        jdbc = step.get("jdbc") if isinstance(step.get("jdbc"), dict) else {}
        if isinstance(jdbc.get("saveAs"), str):
            sources[jdbc["saveAs"]] = f"jdbc-шаг `{step.get('name', '?')}` (заглушка)"
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
            start_after = population.get("start_after_seconds")
            if isinstance(start_after, int) and not isinstance(start_after, bool) and start_after > 0:
                lines.append(
                    f"Старт популяции: через **{start_after} с** после начала теста."
                )

    lines.extend(["", "## Тестовые данные", ""])
    if feeders:
        extra_cols: list[str] = []
        for key, label in (
            ("delimiter", "Разделитель"),
            ("ignore_first_line", "Без заголовка"),
            ("quoted_text", "Кавычки"),
            ("share_mode", "Режим доступа"),
            ("recycle", "Цикл"),
            ("random_order", "Случайный порядок"),
        ):
            if any(isinstance(f, dict) and key in f for f in feeders):
                extra_cols.append((key, label))
        header_cells = ["Фидер", "Файл", "Стратегия"] + [label for _, label in extra_cols]
        sep_cells = ["---"] * len(header_cells)
        lines.append("| " + " | ".join(header_cells) + " |")
        lines.append("| " + " | ".join(sep_cells) + " |")
        for feeder in feeders:
            if isinstance(feeder, dict):
                cells = [
                    md_escape(feeder.get("name", "?")),
                    f"`{feeder.get('file', '?')}`",
                    md_escape(feeder.get("strategy", "?")),
                ]
                for key, _ in extra_cols:
                    value = feeder.get(key)
                    if value is None:
                        cells.append("—")
                    elif isinstance(value, bool):
                        cells.append("да" if value else "нет")
                    else:
                        cells.append(md_escape(value))
                lines.append("| " + " | ".join(cells) + " |")
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

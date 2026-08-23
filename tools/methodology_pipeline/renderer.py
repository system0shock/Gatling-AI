"""Deterministic rendering of canonical methodology sections."""

from __future__ import annotations

import posixpath
import re
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

if __package__:
    from .managed_blocks import merge_generated, migrate_legacy, resolve_drift
    from .sections import CANONICAL_HEADINGS, CANONICAL_SECTIONS
else:
    from managed_blocks import merge_generated, migrate_legacy, resolve_drift
    from sections import CANONICAL_HEADINGS, CANONICAL_SECTIONS


NO_DATA = "> Нет подтверждённых данных."
_DIRECTIVE = re.compile(r"^(\s*)(#{1,6}(?:\s|$)|>|```|~~~)")
_LINK_PATH = re.compile(r"[\w@+.,=~/-]+", re.UNICODE)


class _TrustedCell(str):
    """A table cell whose user-controlled fragments are already escaped."""


@dataclass(frozen=True)
class RenderResult:
    markdown: str
    generation_state: dict[str, Any]
    conflicts: tuple[dict[str, str], ...]
    warnings: tuple[dict[str, str], ...]


def _escape_text(value: Any) -> str:
    text = str(value).replace("&", "&amp;").replace("<", "&lt;")
    return "\n".join(
        _DIRECTIVE.sub(r"\1\\\2", line, count=1)
        for line in text.split("\n")
    )


def _cell(value: Any) -> str:
    return _escape_text(value).replace("|", r"\|").replace("\n", "<br>")


def _display(value: Any) -> str:
    if isinstance(value, bool):
        return "да" if value else "нет"
    if isinstance(value, float):
        return f"{value:g}"
    if isinstance(value, list):
        return ", ".join(_display(item) for item in value)
    return str(value)


def _finish(lines: Sequence[str]) -> str:
    return "\n".join(lines) + "\n"


def _construct(name: str) -> str:
    return f"<!-- mnt:construct:{name} -->"


def _entities(value: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    surface = value.get("surface", {})
    if not isinstance(surface, Mapping):
        return []
    result: list[Mapping[str, Any]] = []
    for group in ("included", "added"):
        items = surface.get(group, [])
        if isinstance(items, list):
            result.extend(item for item in items if isinstance(item, Mapping))
    return sorted(
        result,
        key=lambda item: (
            str(item.get("entity_type", "")),
            str(item.get("canonical_key", "")),
        ),
    )


def _selected_entities(
    value: Mapping[str, Any], entity_types: frozenset[str]
) -> list[Mapping[str, Any]]:
    return [
        entity for entity in _entities(value)
        if entity.get("entity_type") in entity_types
    ]


def _safe_relative_path(value: Any) -> str | None:
    if not isinstance(value, str) or not value or "\\" in value:
        return None
    if any(ord(character) < 32 for character in value):
        return None
    if posixpath.isabs(value) or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", value):
        return None
    if posixpath.normpath(value) != value or value in (".", ".."):
        return None
    if any(part in ("", ".", "..") for part in value.split("/")):
        return None
    if _LINK_PATH.fullmatch(value) is None:
        return None
    return value


def _source_labels(entity: Mapping[str, Any]) -> str:
    sources = entity.get("sources", [])
    if not isinstance(sources, list):
        return "—"
    labels: list[str] = []
    sortable = [source for source in sources if isinstance(source, Mapping)]
    sortable.sort(
        key=lambda source: (
            str(source.get("repo_id", "")),
            str(source.get("revision", "")),
            str(source.get("relative_path", "")),
            str(source.get("pointer", "")),
        )
    )
    for source in sortable:
        if source.get("repo_id") == "user":
            labels.append("ручной обзор поверхности")
            continue
        path = _safe_relative_path(source.get("relative_path"))
        if path is None:
            continue
        prefix = "@".join(
            item for item in (
                _cell(source.get("repo_id", "")),
                _cell(source.get("revision", "")),
            ) if item
        )
        pointer = _cell(source.get("pointer", ""))
        label = f"[{path}]({path})"
        if prefix:
            label = f"{prefix}: {label}"
        if pointer and pointer != "#":
            label += f" {pointer}"
        labels.append(label)
    return _TrustedCell("; ".join(labels) if labels else "—")


def _attribute(entity: Mapping[str, Any], *names: str) -> str:
    attributes = entity.get("attributes", {})
    if not isinstance(attributes, Mapping):
        return "—"
    values = [
        _display(attributes[name]) for name in names
        if name in attributes and attributes[name] not in (None, "", [])
    ]
    return "; ".join(values) if values else "—"


def _table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                str(item) if isinstance(item, _TrustedCell) else _cell(item)
                for item in row
            )
            + " |"
        )
    return "\n".join(lines)


def _surface_table(
    value: Mapping[str, Any],
    entity_types: frozenset[str],
    headers: Sequence[str],
    detail_attributes: Sequence[str],
) -> str:
    entities = _selected_entities(value, entity_types)
    if not entities:
        return NO_DATA + "\n"
    rows = [
        (
            entity.get("display_name", entity.get("canonical_key", "—")),
            _attribute(entity, *detail_attributes),
            _source_labels(entity),
        )
        for entity in entities
    ]
    return _table(headers, rows) + "\n"


def _not_applicable(value: Mapping[str, Any], section_id: str) -> str | None:
    items = value.get("not_applicable_sections", [])
    if not isinstance(items, list):
        return None
    for item in items:
        if isinstance(item, Mapping) and item.get("section_id") == section_id:
            return f"> Не применимо: {_escape_text(item.get('reason', ''))}.\n"
    return None


def render_document_passport(value: Mapping[str, Any]) -> str:
    document = value.get("document", {})
    document = document if isinstance(document, Mapping) else {}
    profile = value.get("profile", {})
    profile = profile if isinstance(profile, Mapping) else {}
    snapshot_id = document.get("snapshot_id", value.get("workspace_snapshot_id"))
    profile_id = document.get("profile_id", profile.get("profile_id"))
    profile_version = document.get("profile_version", profile.get("profile_version"))
    return _finish([
        _construct("snapshot-id"),
        f"- Snapshot: {_escape_text(snapshot_id)}",
        _construct("profile-id"),
        f"- Профиль: {_escape_text(profile_id)}",
        _construct("profile-version"),
        f"- Версия профиля: {_escape_text(profile_version)}",
    ])


def render_scope(value: Mapping[str, Any]) -> str:
    surface = value.get("surface", {})
    surface = surface if isinstance(surface, Mapping) else {}
    lines = [
        _construct("confirmed-surface"),
        f"Подтверждённая поверхность: {_escape_text(surface.get('status', '—'))}.",
        _construct("included-entity"),
    ]
    entities = _entities(value)
    if not entities:
        lines.append(NO_DATA)
    else:
        lines.append(_table(
            ("Тип", "Ключ", "Объект", "Источники"),
            [
                (
                    entity.get("entity_type", "—"),
                    entity.get("canonical_key", "—"),
                    entity.get("display_name", "—"),
                    _source_labels(entity),
                )
                for entity in entities
            ],
        ))
    return _finish(lines)


def render_system_description(value: Mapping[str, Any]) -> str:
    return _surface_table(
        value,
        frozenset(("system", "business-capability", "service", "component")),
        ("Компонент", "Описание", "Источники"),
        ("description", "responsibility", "boundary"),
    )


def render_architecture(value: Mapping[str, Any]) -> str:
    return _surface_table(
        value,
        frozenset(("system", "service", "component", "deployment", "data-store")),
        ("Компонент", "Связи", "Источники"),
        ("relationship", "relationships", "dependency", "target"),
    )


def render_integrations(value: Mapping[str, Any]) -> str:
    entities = _selected_entities(value, frozenset(("integration",)))
    if not entities:
        return _not_applicable(value, "integrations") or NO_DATA + "\n"
    return _surface_table(
        value, frozenset(("integration",)),
        ("Интеграция", "Протокол или канал", "Источники"),
        ("protocol", "channel", "source", "target", "strategy"),
    )


def render_interfaces(value: Mapping[str, Any]) -> str:
    if not _selected_entities(value, frozenset(("interface", "endpoint", "contract"))):
        return _not_applicable(value, "interfaces") or NO_DATA + "\n"
    return _surface_table(
        value, frozenset(("interface", "endpoint", "contract")),
        ("Интерфейс", "Операция", "Источники"),
        ("operation", "method", "type", "owner"),
    )


def render_flows(value: Mapping[str, Any]) -> str:
    if not _selected_entities(value, frozenset(("user-flow", "technical-flow", "flow"))):
        return _not_applicable(value, "flows") or NO_DATA + "\n"
    return _surface_table(
        value, frozenset(("user-flow", "technical-flow", "flow")),
        ("Поток", "Описание", "Источники"),
        ("description", "trigger", "steps", "outcome"),
    )


def render_workload(value: Mapping[str, Any]) -> str:
    load = value.get("load", {})
    if not isinstance(load, Mapping) or not load:
        return NO_DATA + "\n"
    labels = (
        ("unit", "Единица нагрузки"),
        ("initial", "Начальная нагрузка"),
        ("step_increment", "Шаг увеличения"),
        ("operation_mix", "Операционный микс"),
    )
    return _finish([
        f"- {label}: {_escape_text(_display(load[key]))}"
        for key, label in labels if key in load
    ])


def render_test_types(value: Mapping[str, Any]) -> str:
    tests = value["profile"]["tests"]
    return (
        "<!-- mnt:construct:test-step-search -->\n"
        "<!-- mnt:construct:test-maximum-confirmation -->\n"
        "<!-- mnt:construct:test-stability -->\n"
        "1. **Ступенчатый поиск максимума.** "
        f"Длительность ступени — {tests['maximum_search']['step_minutes']} минут. "
        "Максимумом считается последняя полностью пройденная ступень.\n"
        "2. **Подтверждение максимума.** "
        f"Нагрузка на найденном максимуме удерживается "
        f"{tests['maximum_confirmation']['duration_minutes'] // 60} часа.\n"
        "3. **Стабильность.** "
        f"Нагрузка {int(tests['stability']['load_factor'] * 100)}% "
        f"подтверждённого максимума удерживается "
        f"{tests['stability']['duration_minutes'] // 60} часов.\n"
    )


def _source(value: Mapping[str, Any], keys: Sequence[str]) -> str:
    profile = value.get("profile", {})
    sources = profile.get("sources", {}) if isinstance(profile, Mapping) else {}
    labels: list[str] = []
    if isinstance(sources, Mapping):
        for key in keys:
            item = sources.get(key)
            if not isinstance(item, Mapping):
                continue
            label = str(item.get("source", ""))
            reference = item.get("source_reference")
            if reference not in (None, ""):
                label += f" ({reference})"
            if label and label not in labels:
                labels.append(label)
    if not labels and isinstance(profile, Mapping) and profile.get("profile_id"):
        labels.append(str(profile["profile_id"]))
    return "; ".join(labels) if labels else "—"


def render_sla_slo(value: Mapping[str, Any]) -> str:
    profile = value["profile"]
    criteria = profile["criteria"]
    response = criteria["response_time"]
    errors = criteria["technical_errors"]
    cpu = criteria["cpu"]
    memory = criteria["memory"]
    observability = value.get("observability", {})
    observability = observability if isinstance(observability, Mapping) else {}
    cpu_scope = str(cpu["scope"])
    if "cpu_signal" in observability:
        cpu_scope += f"; сигнал: {observability['cpu_signal']}"
    memory_scope = ""
    if "memory_signal" in observability:
        memory_scope = f"сигнал: {observability['memory_signal']}"
    if "memory_growth_window" in observability:
        window = f"окно контроля: {_display(observability['memory_growth_window'])} минут"
        memory_scope = f"{memory_scope}; {window}" if memory_scope else window
    memory_criterion = f"≤ {_display(memory['max_percent'])}%"
    if memory["no_sustained_growth"]:
        memory_criterion += "; без устойчивого роста"
    rows = [
        ("RT", "Время ответа", f"{response['percentile']} ≤ {response['threshold_ms']} мс", "тестируемые операции", _source(value, ("criteria.response_time.percentile", "criteria.response_time.threshold_ms"))),
        ("ERR", "Технические ошибки", f"≤ {_display(errors['max_percent'])}%", "все запросы", _source(value, ("criteria.technical_errors.max_percent", "criteria.technical_errors.exclusions"))),
        ("CPU", "CPU", f"≤ {_display(cpu['max_percent'])}%", cpu_scope, _source(value, ("criteria.cpu.max_percent", "criteria.cpu.scope"))),
        ("MEM", "Память", memory_criterion, memory_scope or "тестовый стенд", _source(value, ("criteria.memory.max_percent", "criteria.memory.no_sustained_growth"))),
    ]
    return _finish([
        _construct("response-time-criterion"),
        _construct("technical-errors-criterion"),
        _construct("cpu-criterion"),
        _construct("memory-criterion"),
        _construct("criterion-sources"),
        _table(("ID", "Метрика", "Критерий", "Область действия", "Нормативный источник"), rows),
    ])


def render_environment(value: Mapping[str, Any]) -> str:
    environment = value.get("environment", {})
    if not isinstance(environment, Mapping) or not environment:
        return NO_DATA + "\n"
    return _finish([f"- Стенд: {_escape_text(_display(environment['name']))}"])


def render_test_data(value: Mapping[str, Any]) -> str:
    test_data = value.get("test_data", {})
    if not isinstance(test_data, Mapping) or "ready" not in test_data:
        return NO_DATA + "\n"
    return _finish([f"- Тестовые данные готовы: {_escape_text(_display(test_data['ready']))}."])


def render_observability(value: Mapping[str, Any]) -> str:
    observability = value.get("observability", {})
    if not isinstance(observability, Mapping) or not observability:
        return NO_DATA + "\n"
    labels = (
        ("cpu_signal", "Сигнал CPU"),
        ("memory_signal", "Сигнал памяти"),
        ("memory_growth_window", "Окно контроля роста памяти, минут"),
        ("dashboard", "Дашборд"),
    )
    return _table(
        ("Параметр", "Значение"),
        [(label, _display(observability[key])) for key, label in labels if key in observability],
    ) + "\n"


def render_procedure(value: Mapping[str, Any]) -> str:
    tests = value["profile"]["tests"]
    return _finish([
        _construct("stage-step-search"),
        f"1. Выполнять ступени по {tests['maximum_search']['step_minutes']} минут до первого непройденного уровня.",
        _construct("stage-maximum-confirmation"),
        f"2. Подтвердить последний пройденный максимум в течение {tests['maximum_confirmation']['duration_minutes'] // 60} часа.",
        _construct("stage-stability"),
        f"3. Проверить стабильность при {int(tests['stability']['load_factor'] * 100)}% максимума в течение {tests['stability']['duration_minutes'] // 60} часов.",
    ])


def render_risks(value: Mapping[str, Any]) -> str:
    entities = _selected_entities(
        value, frozenset(("risk", "limitation", "assumption"))
    )
    if not entities:
        return _not_applicable(value, "risks") or NO_DATA + "\n"
    rows = []
    for entity in entities:
        measure = _cell(_attribute(entity, "mitigation", "impact", "statement"))
        source = _source_labels(entity)
        rows.append((
            entity.get("display_name", entity.get("canonical_key", "—")),
            _TrustedCell(f"{measure}; источники: {source}"),
        ))
    return _table(("Риск", "Мера"), rows) + "\n"


def render_artifacts(value: Mapping[str, Any]) -> str:
    return _finish([
        _construct("readiness-artifact"),
        "- Отчёт готовности входных данных.",
        _construct("template-artifact"),
        "- Отчёт полноты шаблона методики.",
        _construct("gatling-artifact"),
        "- Сценарии и журнал запуска Gatling.",
        _construct("monitoring-artifact"),
        "- Снимки мониторинга за период теста.",
        _construct("test-result-artifact"),
        "- Итоговый отчёт с результатами и выводами.",
    ])


def render_methodology_update(value: Mapping[str, Any]) -> str:
    profile = value.get("profile", {})
    profile = profile if isinstance(profile, Mapping) else {}
    return _finish([
        _construct("profile-id-version"),
        f"- Основа: профиль {_escape_text(profile.get('profile_id', '—'))}, версия {_escape_text(profile.get('profile_version', '—'))}.",
        _construct("regeneration-rule"),
        "- Generated-блоки обновляются детерминированно; ручные дополнения сохраняются в manual-блоках.",
    ])


SectionRenderer = Callable[[Mapping[str, Any]], str]
RENDERERS: OrderedDict[str, SectionRenderer] = OrderedDict((
    ("document-passport", render_document_passport),
    ("scope", render_scope),
    ("system-description", render_system_description),
    ("architecture", render_architecture),
    ("integrations", render_integrations),
    ("interfaces", render_interfaces),
    ("flows", render_flows),
    ("workload", render_workload),
    ("test-types", render_test_types),
    ("sla-slo", render_sla_slo),
    ("environment", render_environment),
    ("test-data", render_test_data),
    ("observability", render_observability),
    ("procedure", render_procedure),
    ("risks", render_risks),
    ("artifacts", render_artifacts),
    ("methodology-update", render_methodology_update),
))

if tuple(RENDERERS) != tuple(section_id for section_id, _ in CANONICAL_SECTIONS):
    raise RuntimeError("renderer registry does not match canonical sections")


def render_generated_sections(
    methodology_input: Mapping[str, Any],
) -> OrderedDict[str, str]:
    return OrderedDict(
        (section_id, section_renderer(methodology_input))
        for section_id, section_renderer in RENDERERS.items()
    )


def render_candidate(
    current_markdown: str,
    methodology_input: Mapping[str, Any],
    previous_state: Mapping[str, Any],
    drift_decisions: Mapping[str, str] | None = None,
) -> RenderResult:
    migrated = migrate_legacy(current_markdown, CANONICAL_HEADINGS)
    generated = render_generated_sections(methodology_input)
    result = merge_generated(migrated, generated, previous_state)
    if result.conflicts and drift_decisions is not None:
        result = resolve_drift(
            migrated, generated, previous_state, drift_decisions
        )
    return RenderResult(
        result.markdown,
        result.generation_state,
        result.conflicts,
        result.warnings,
    )

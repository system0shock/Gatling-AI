"""Canonical methodology document section ordering."""

CANONICAL_SECTIONS = (
    ("document-passport", "Паспорт документа"),
    ("scope", "Назначение и область тестирования"),
    ("system-description", "Описание системы и функциональности"),
    ("architecture", "Архитектура"),
    ("integrations", "Реестр интеграций"),
    ("interfaces", "Реестр тестируемых интерфейсов"),
    ("flows", "Пользовательские и технические потоки"),
    ("workload", "Модель нагрузки"),
    ("test-types", "Виды тестов"),
    ("sla-slo", "SLA, SLO и критерии приемки"),
    ("environment", "Тестовый стенд"),
    ("test-data", "Требования к тестовым данным"),
    ("observability", "Наблюдаемость и диагностика"),
    ("procedure", "Порядок проведения тестов"),
    ("risks", "Риски, ограничения и допущения"),
    ("artifacts", "Артефакты и отчетность"),
    ("methodology-update", "Актуализация методики"),
)

CANONICAL_HEADINGS = tuple(heading for _, heading in CANONICAL_SECTIONS)

SURFACE_ENTITY_TYPES_BY_SECTION = {
    "integrations": frozenset(("integration",)),
    "interfaces": frozenset((
        "interface",
        "endpoint",
        "contract",
        "http-interface",
        "async-interface",
    )),
    "flows": frozenset(("user-flow", "technical-flow", "flow")),
}

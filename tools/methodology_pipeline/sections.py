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

class _CanonicalHeadings(tuple[str, ...]):
    """Immutable headings that compare naturally with renderer-produced lists."""

    def __eq__(self, other: object) -> bool:
        if isinstance(other, list):
            return tuple(self) == tuple(other)
        return super().__eq__(other)


CANONICAL_HEADINGS = _CanonicalHeadings(heading for _, heading in CANONICAL_SECTIONS)

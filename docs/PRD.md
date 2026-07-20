# PRD — Gatling-AI Workflow для Gigacode

**Документ:** Product Requirements Document
**Версия:** 0.1 (черновик для согласования)
**Дата:** 2026-06-03
**Автор:** v.salnikov.k@gmail.com + Claude
**Статус:** на согласовании

---

## 1. Краткое описание (Executive Summary)

Gatling-AI Workflow — это набор скиллов, команд и субагентов для **Gigacode** (корпоративный форк Qwen Code), который превращает агента в специализированного инженера по нагрузочному тестированию на **Gatling (open-source, не Enterprise)**.

Воркфлоу решает пять задач:

1. **Документация → машиночитаемый сценарий.** Перевод требований из Confluence, текстовых файлов и диалога с пользователем в формализованный сценарий по единому шаблону.
2. **JMeter → Gatling.** Автоматическая конвертация существующих `.jmx`-планов в симуляции Gatling на Java.
3. **Документирование легаси.** Генерация человекочитаемой документации по существующим (в т.ч. недокументированным) скриптам JMeter.
4. **Сценарий → код.** Генерация компилируемых, запускаемых симуляций Gatling и сложных нагрузочных профилей на основе машиночитаемого сценария.
5. **Линтеры и самопроверки.** Автоматический контур качества в петле имплементации: хуки запускают линтеры, schema/semantic checks, сборку, smoke-прогоны и субагента-валидатора до отдачи результата человеку.

Дополнительно: **отладка скриптов агентом** при наличии доступа к репозиторию кода тестируемой системы (SUT) — для корреляций, контрактов API, путей запросов.

Методологическая основа — **Claude Superpowers** (`brainstorm → plan → subagent-driven development → systematic debugging`). Доменные скиллы берутся и адаптируются из официального репозитория **gatling/gatling-ai-extensions**.

---

## 2. Контекст и обоснование

### 2.1. Источники, на которых строится проект

| Источник | Что берём | Ограничение |
|---|---|---|
| [obra/superpowers](https://github.com/obra/superpowers) | Методология и каркас workflow: фазы brainstorm/plan/execute/debug, дисциплина "skills как обязательные процессы", subagent-driven development | Заточен под Claude Code → требует адаптации под механику Gigacode/Qwen |
| [gatling/gatling-ai-extensions](https://github.com/gatling/gatling-ai-extensions) | Доменные скиллы: bootstrap, build-tools, convert-from-jmeter, convert-from-loadrunner, detect-existing-project | Часть функций (MCP-сервер, configuration-as-code) завязана на **Gatling Enterprise** — **исключается из scope** |

### 2.2. Источники для hook-driven quality loop

| Источник | Что берём | Как адаптируем |
|---|---|---|
| [disler/claude-code-hooks-mastery](https://github.com/disler/claude-code-hooks-mastery) | Практика жизненного цикла хуков, SubagentStart/SubagentStop, PostToolUse, валидаторы, structured logging, team-based validation | Переносим идею hook-driven проверок и роли read-only validator-subagent; Claude-специфичные пути заменяются на Gigacode/Qwen |
| [ChrisWiles/claude-code-showcase](https://github.com/ChrisWiles/claude-code-showcase) | Пример комплексной конфигурации hooks/skills/agents/commands/GitHub Actions | Используем как reference для структуры расширения и интеграции проверок |
| [rohitg00/awesome-claude-code-toolkit](https://github.com/rohitg00/awesome-claude-code-toolkit), [davepoon/buildwithclaude](https://github.com/davepoon/buildwithclaude) | Каталоги агентов, команд, хуков, правил и marketplace-подхода | Используем для discovery паттернов, но в продукт включаем только минимальный набор проверок |
| [anthropics/claude-code](https://github.com/anthropics/claude-code) и Claude Code docs | Официальная модель hooks/subagents/settings как базовая терминология | Не считаем прямой совместимостью; нужен spike на Gigacode |
| [PacktPublishing/Agentic-Coding-with-Claude-Code](https://github.com/PacktPublishing/Agentic-Coding-with-Claude-Code), [JMCodes-Studio/remindcc](https://github.com/JMCodes-Studio/remindcc) | Идеи reminder/checklist-driven поведения агента | Адаптируем в виде self-check reminders перед завершением имплементационной петли |

### 2.3. Целевая платформа: Gigacode (форк Qwen Code)

**Gigacode во многом аналогичен последней версии Qwen Code; под капотом — модель `qwen3-coder-next 480b`.** Соответственно поддерживается:
- **Skills** — формат `SKILL.md` в `~/.qwen/skills/` (личные) и `.qwen/skills/` (проектные, в git, доступны команде);
- **Custom Commands** — пользовательские команды;
- **Custom Extensions** — связки команд + агентов;
- **Subagents** — для делегирования.

→ Скиллы Superpowers и Gatling **переносимы** в формате `SKILL.md`. Адаптация сводится к:
- замене Claude-специфичных вызовов субагентов на механику Qwen-субагентов;
- проверке синтаксиса front-matter и путей ресурсов;
- учёту особенностей `qwen3-coder-next 480b` (длина контекста, function-calling протокол).

> Совместимость с upstream Qwen Code высокая → риск платформы понижен. Контрольный spike на 1 скилле всё равно остаётся в плане фазы 0 как страховка.

---

## 3. Цели и не-цели

### 3.1. Цели (Goals)

- G1. Снизить порог входа в Gatling для инженеров без Scala/Java-опыта в нагрузке.
- G2. Сократить время «требование → запускаемый тест» с дней до часов.
- G3. Обеспечить **единый машиночитаемый формат сценария** как контракт между этапами.
- G4. Автоматизировать миграцию легаси JMeter → Gatling с сохранением логики.
- G5. Гарантировать, что сгенерированный код **компилируется и запускается** локально (`mvn gatling:test`) и готов к запуску в CI (Jenkins) / на удалённых агентах.
- G6. Встроить **детерминированный контур качества** в агентскую петлю: сгенерированный сценарий, документация и код проходят линтеры, самопроверки и независимую валидацию субагентом до финального ответа.

### 3.2. Не-цели (Non-Goals)

- N1. Поддержка Gatling **Enterprise** (MCP-деплой, cloud-оркестрация, configuration-as-code Enterprise) — **вне scope** (возможен задел на будущее).
- N2. Замена анализа результатов человеком / автоматический performance-вердикт по SLA (на первой фазе — только сбор отчёта).
- N3. Конвертация из LoadRunner (скилл существует, но не входит в 4 заявленных задачи; опционально).
- N4. Поддержка языков Gatling кроме **Java** на первой фазе (Scala/Kotlin — будущее).

---

## 4. Пользователи и сценарии использования

| Персона | Потребность | Ключевая задача |
|---|---|---|
| **Перформанс-инженер** | Быстро собрать тест из требований | #1, #4 |
| **Инженер миграции** | Перевести парк JMeter-скриптов на Gatling | #2, #3 |
| **Новый член команды** | Понять, что делает легаси-скрипт | #3 |
| **QA/разработчик SUT** | Получить тест без глубокого знания Gatling | #1, #4, отладка |

**Типовой поток (happy path):**
> Инженер указывает страницу Confluence с требованиями → агент извлекает её через API/MCP → формирует машиночитаемый сценарий по шаблону → инженер ревьюит/правит сценарий → агент генерирует Java-симуляцию Gatling → компилирует, запускает локально, чинит ошибки → отдаёт готовый скрипт + отчёт + (опц.) Jenkins-конфиг.

---

## 5. Функциональные требования

### 5.1. Фича 1 — Документация → машиночитаемый сценарий

- FR1.1. Источники ввода: **Confluence (штатный Atlassian MCP)**, локальные текстовые/markdown/PDF файлы, интерактивный диалог с пользователем.
- FR1.2. Извлечение из Confluence через **штатный MCP-сервер Atlassian** (поиск страниц, чтение контента); нормализация HTML/таблиц в текст.
- FR1.3. Извлечение сущностей нагрузочного теста: endpoints, методы, заголовки, тело, параметры, ожидаемые статусы, профиль нагрузки (users/ramp/duration), think time, тестовые данные (feeders), корреляции, проверки (checks/assertions), окружения.
- FR1.4. На фазе brainstorm (по Superpowers) агент **задаёт уточняющие вопросы** при неоднозначности, а не угадывает.
- FR1.5. Вывод — файл сценария по **единому шаблону** (см. §6), помещаемый в проект и пригодный для ревью человеком.

### 5.2. Фича 2 — JMeter → Gatling

- FR2.1. Сканирование проекта на `.jmx` (на базе `gatling-convert-from-jmeter`).
- FR2.2. Маппинг элементов JMeter (Thread Group, HTTP Request, Config Elements, Assertions, Timers, CSV Data Set, Extractors) → эквиваленты Gatling на Java. Поддерживаемые HTTP-методы: `GET/POST/PUT/PATCH/DELETE/HEAD/OPTIONS`. Расширенные элементы: `fifo_put_post`, `fifo_pop_pre` (JP@GC Inter-Thread Communication), `http_raw_sampler`. Cross-thread FIFO не имеет эквивалента в Gatling (сессии per-VU) и представляется как `todo`-хук с флагом сложности `fifo-cross-thread`, без автоматической конвертации.
- FR2.3. Генерация **компилируемой** симуляции; неподдерживаемые элементы — явные TODO-комментарии с пояснением.
- FR2.4. Отчёт о конвертации: что сконвертировано, что требует ручной доводки.

### 5.3. Фича 3 — Документирование легаси JMeter

- FR3.1. Парсинг `.jmx` и (при наличии) связанных CSV/properties. **Скрипты документации не имеют — источник истины это сам `.jmx` + код/контракты SUT.**
- FR3.2. Генерация человекочитаемой документации: назначение скрипта, бизнес-сценарий, шаги/транзакции, параметры, тестовые данные, профиль нагрузки, корреляции, зависимости от окружения, **используемые протоколы (HTTP/Kafka/GraphQL/JDBC)**.
- FR3.3. Формат документации согласуется с машиночитаемым шаблоном сценария (§6) для последующей переконвертации.
- FR3.4. **Публикация в Confluence через Atlassian MCP** (создание/обновление страниц) — приводит «разноплановые страницы без нормальной документации» к единому шаблону. Локальный Markdown — как промежуточный артефакт и fallback.

### 5.4. Фича 4 — Сценарий → код Gatling

- FR4.1. Генерация Java-симуляции из машиночитаемого сценария (§6).
- FR4.2. Поддержка сложных профилей: несколько scenario/population, open/closed workload model, ramp/stress/soak, feeders, чекпойнты, корреляции (`saveAs`/`jsonPath`/regex), pause/pace.
- FR4.3. Использование `gatling-bootstrap-project` для скаффолда нового проекта при отсутствии и `gatling-detect-existing-project` для встраивания в существующий.
- FR4.4. Сборка/запуск через `gatling-build-tools` (адаптировано под локальный Maven).
- FR4.5. Целевой стек строго: **Gatling core 3.12**, **gatling-maven-plugin 4.21.7**, **Java**.

### 5.5. Доп. фича — Отладка с доступом к репозиторию SUT

- FR5.1. При предоставлении пути/доступа к репозиторию тестируемой системы агент анализирует контракты API (OpenAPI/контроллеры/DTO) для уточнения endpoints, схем тел, кодов ответов.
- FR5.2. Итеративный цикл **systematic debugging** (Superpowers): запуск → анализ ошибок/несоответствий → правка → повторный запуск, до зелёного прогона.
- FR5.3. Корреляция фактических ответов SUT с проверками сценария.

---

### 5.6. Поддержка протоколов (HTTP + легаси: Kafka, GraphQL, PostgreSQL)

Легаси использует не только HTTP: **Kafka**, **GraphQL** (редко), **запросы в PostgreSQL (JDBC)**. Gatling OSS core 3.12 нативно покрывает HTTP/JMS; остальное — через community-плагины или кастомный код. Поскольку таргет — **Java**, а большинство плагинов ориентированы на Scala 2.13, для каждого протокола заложен прагматичный путь:

| Протокол | Подход в Gatling 3.12 (Java, OSS) | Риск / примечание |
|---|---|---|
| **HTTP** | Нативный `HttpDsl` | Базовый, без ограничений |
| **GraphQL** | Поверх HTTP: `POST` с JSON-телом `{query, variables}` + checks по `jsonPath` | Плагин не нужен; тривиально |
| **Kafka** | Community-плагин ([galax-io](https://github.com/galax-io/gatling-kafka-plugin) / [Tinkoff](https://github.com/Tinkoff/gatling-kafka-plugin)) — **проверить совместимость с 3.12 и доступность из Java DSL** | Плагины Scala-ориентированы; при нерабочем Java DSL — обёртка через кастомный action |
| **PostgreSQL (JDBC)** | Tinkoff JDBC-плагин таргетит 3.9.x/Scala → **вероятно несовместим**. Прагматичный путь: **кастомный action** (`exec(session -> ...)`), вызывающий JDBC напрямую (HikariCP/драйвер PG) | Требует spike; вынести в фазу 2 |

- FR5.6.1. Машиночитаемый сценарий (§6) описывает протокол шага декларативно (поле `protocol`), генератор выбирает соответствующий путь.
- FR5.6.2. Для Kafka/JDBC агент при первой генерации фиксирует выбранный плагин/версию в `pom.xml`/`build.gradle` и в документации проекта.
- FR5.6.3. Если рабочий вариант для протокола не найден — генерируется заглушка с явным TODO, а не «молчаливо неверный» код.

### 5.7. Контур линтеров, самопроверок и hook-driven validation

Петля имплементации должна быть не только agentic, но и проверяемой. После генерации или изменения артефактов агент не полагается на собственную уверенность: хуки запускают детерминированные проверки, а отдельный субагент-валидатор делает read-only ревью результата.

- FR5.7.1. В workflow вводится `quality-gate` как обязательный этап после `EXECUTE` и перед финальным ответом пользователю.
- FR5.7.2. При наличии поддержки hooks в Gigacode используются события, эквивалентные Claude Code `PostToolUse`, `PostToolUseFailure`, `SubagentStart`, `SubagentStop`, `Stop`. Если прямой поддержки нет — реализуется fallback-команда quality gate, вызываемая агентом явно.
- FR5.7.3. `PostToolUse` после записи файлов запускает scoped-проверки по типу изменённого артефакта:
  - YAML-сценарий: `scenario.schema.json`, semantic linter, проверка секретов и PII, проверка поддерживаемости протоколов.
  - Java/Gatling: форматирование, компиляция, `mvn compile`/`gradle compileTestJava`, проверка dependency pinning, `script-style-lint`.
  - JMeter conversion: отчёт покрытия элементов, список partial/TODO, проверка отсутствия silent drop.
  - Markdown/Confluence-документация: проверка структуры шаблона, битых ссылок, обязательных секций.
- FR5.7.4. `SubagentStop` для implementation-субагента запускает read-only `validator-subagent`, который проверяет: соответствие PRD/плану, полноту артефактов, результаты линтеров, наличие TODO и риски ручной доводки.
- FR5.7.5. `Stop` hook не должен позволять финальный ответ "готово", если quality gate не выполнен или имеет blocking-ошибки. Разрешённые статусы: `passed`, `passed_with_warnings`, `blocked`.
- FR5.7.6. Все проверки пишут структурированный отчёт `quality-gate-report.json` и краткий человекочитаемый `quality-gate-report.md`.
- FR5.7.7. Проверки должны быть идемпотентными и локальными по умолчанию: они не запускают реальную нагрузку на SUT без явного разрешения пользователя.
- FR5.7.8. Для MVP quality gate покрывает HTTP-only сценарии, YAML schema/semantic lint, Java compile и smoke-run с минимальным профилем. Kafka/JDBC проверки добавляются после соответствующих spike.

### 5.8. Hook-проверки оформления Gatling-скрипта и доменные линтеры

`script-style-lint` проверяет, что сгенерированный Gatling-скрипт удобен для эксплуатации, анализа отчётов и сопровождения, а не просто компилируется. Проверки запускаются хуком после генерации Java/YAML и повторяются полным quality gate перед финальным ответом.

#### 5.8.1. Соглашения об именовании

- FR5.8.1. `scenario.id`, `steps[].name`, `feeders[].name`, `assertions[].name` используют стабильный `kebab-case` ASCII без пробелов, случайных суффиксов, UUID, дат и окружений.
- FR5.8.2. Gatling class name (script ref) генерируется по шаблону `<SYSTEM>_<PascalCase(id)>_<NNN>` из полей `scenario.system`, `scenario.id` и `scenario.number`, например `SHOP_LoginAndSearch_002`.
- FR5.8.3. Имена Gatling requests и transaction groups должны быть уникальны в пределах симуляции и стабильны между регенерациями.
- FR5.8.4. Для отчётов Gatling используется гибридный формат имени транзакции: `<NN> <domain>.<action> - <human title>`, например `01 auth.login - Submit credentials`.
- FR5.8.5. Для converted JMeter сохраняется трассируемость: если есть Transaction Controller, его имя маппится в `group(...)`; если имени нет — агент создаёт имя по шаблону и фиксирует это в conversion report.
- FR5.8.6. Максимальная длина имени request/group — 80 символов; запрещены секреты, PII, URL query со значениями, имена окружений (`dev`, `stage`, `prod`) и динамические session-переменные в display name.

#### 5.8.2. Линтеры сценария и кода

- FR5.8.7. `scenario-lint` проверяет YAML сверх JSON Schema: уникальность имён, наличие `title`, `source`, `sut.base_url`, корректные ссылки на feeders, положительные значения нагрузки, совместимость `protocol` и блока шага.
- FR5.8.8. `transaction-lint` проверяет, что каждый бизнес-шаг имеет понятное имя, а составные операции обёрнуты в `group(...)` для читаемых отчётов Gatling.
- FR5.8.9. `check-lint` проверяет, что каждый HTTP-запрос имеет хотя бы один базовый check (`status` или эквивалент), а mutating-запросы (`POST/PUT/PATCH/DELETE`) имеют explicit status/check.
- FR5.8.10. `correlation-lint` проверяет пары `extract/saveAs` → использование переменной, отсутствие undefined session variables, отсутствие overwrite критичных переменных без явного разрешения.
- FR5.8.11. `feeder-lint` проверяет существование CSV/properties-файлов, совпадение заголовков feeder с используемыми переменными, отсутствие очевидных секретов и PII в тестовых данных.
- FR5.8.12. `env-lint` запрещает хардкод `baseUrl`, токенов, логинов, паролей и JDBC/Kafka credentials в Java-коде; всё должно приходить из env/system properties/secret storage.
- FR5.8.13. `gatling-style-lint` запрещает `Thread.sleep`, произвольные `System.out.println` для секретных данных, неограниченные циклы, raw JSON/body без шаблонизации там, где используются feeders.
- FR5.8.14. `dependency-lint` проверяет закрепление версий Gatling/plugin/dependencies и отсутствие случайного подключения Enterprise-зависимостей.

#### 5.8.3. Hook lifecycle

- FR5.8.15. `PostToolUse` после изменения `.yaml/.yml` запускает `scenario-lint`, `transaction-lint`, `feeder-lint`, `secret-scan`.
- FR5.8.16. `PostToolUse` после изменения `.java`, `pom.xml`, `build.gradle` запускает `gatling-style-lint`, `dependency-lint`, compile-check и targeted smoke compile.
- FR5.8.17. `SubagentStop` implementation-субагента запускает `validator-subagent`, который проверяет отчёт линтеров и запрещает статус `passed`, если есть blocking-нарушения.
- FR5.8.18. `Stop` hook формирует итоговый раздел отчёта: `blocking`, `warnings`, `style`, `manual_review_required`, `accepted_exceptions`.
- FR5.8.19. Исключения из правил допускаются только через явный `lint waivers` блок в YAML/отчёте с причиной, сроком действия и владельцем.

#### 5.8.4. Варианты глубины внедрения

| Вариант | Состав | Плюсы | Минусы | Рекомендация |
|---|---|---|---|---|
| **A. MVP Guardrails** | schema, transaction naming, checks, compile, secret scan | Быстро внедряется, мало шума | Не ловит все проблемы корреляций и feeders | Лучший старт для фазы 1 |
| **B. Engineering Quality Gate** | Вариант A + correlation/feeder/env/dependency lint + smoke-run | Хороший баланс качества и скорости | Требует больше fixtures и правил исключений | Рекомендуемый целевой вариант |
| **C. Strict Regulated Mode** | Вариант B + mandatory waivers, Confluence publish lint, JMeter coverage thresholds, CI policy | Максимальная управляемость и аудит | Может замедлять эксперименты и генерировать шум | Для зрелой фазы 3-4 и критичных проектов |

## 6. Артефакт: машиночитаемый шаблон сценария (проектируется)

Единый формат — **контракт** между всеми фичами (1→4, 3→4, 2 нормализуется к нему). Предлагаемый формат: **YAML** (читаемость + структурность + поддержка комментариев).

Черновик схемы (детализируется на этапе brainstorm):

```yaml
scenario:
  id: "login-and-search"
  title: "Логин и поиск товара"
  source: { type: confluence, ref: "PAGE-12345" }   # или file / manual
  sut:
    base_url: "https://${env}.example.com"
    environments: { dev: "...", stage: "..." }
  data:
    feeders:
      - name: users
        file: "users.csv"
        strategy: circular
  steps:
    - name: "open-login"
      protocol: http              # http | graphql | kafka | jdbc  (default: http)
      request: { method: GET, path: "/login" }
      checks:
        - status: 200
        - extract: { type: css, expr: "input[name=csrf]", saveAs: csrf }
    # --- примеры не-HTTP шагов (легаси) ---
    # - name: "publish-event"
    #   protocol: kafka
    #   kafka: { topic: "orders", key: "${orderId}", payload: '{"id":"${orderId}"}' }
    # - name: "check-balance"
    #   protocol: jdbc
    #   jdbc: { query: "SELECT balance FROM accounts WHERE id=${accId}", saveAs: balance }
    # - name: "gql-search"
    #   protocol: graphql
    #   graphql: { query: "query($q:String){search(q:$q){id}}", variables: { q: "${term}" } }
    - name: "do-login"
      request:
        method: POST
        path: "/login"
        headers: { Content-Type: "application/x-www-form-urlencoded" }
        body: "user=${username}&pass=${password}&csrf=${csrf}"
      checks:
        - status: 302
  load:
    model: closed            # open | closed
    profile: ramp            # ramp | constant | stress | soak | spike
    users: 100
    ramp_seconds: 60
    duration_seconds: 600
  assertions:
    - { metric: global.responseTime.p95, op: "<", value: 800 }
    - { metric: global.successfulRequests.percent, op: ">", value: 99 }
```

Артефакты этапа: `scenario.schema.json` (валидация), примеры, документация формата.

---

## 7. Архитектура воркфлоу

### 7.1. Методологический каркас (из Superpowers)

```
[1 BRAINSTORM] → [2 PLAN] → [3 EXECUTE (subagent-driven)] → [4 DEBUG/VERIFY]
```
- Скиллы — **обязательные процессы**, агент проверяет наличие релевантного скилла перед задачей.
- Перед написанием кода — уточнение требований и согласование дизайна.
- Реализация делегируется субагентам с ревью.

### 7.2. Карта скиллов

| Скилл | Происхождение | Действие |
|---|---|---|
| `gatling-bootstrap-project` | gatling-ai-extensions | взять как есть (Java/Maven) |
| `gatling-detect-existing-project` | gatling-ai-extensions | взять как есть |
| `gatling-build-tools` | gatling-ai-extensions | **адаптировать**: локальные Maven и Gradle, без Enterprise-деплоя |
| `gatling-convert-from-jmeter` | gatling-ai-extensions | взять + закрепить таргет Java/3.12 |
| `scenario-from-docs` | **новый** | Confluence/файлы/диалог → YAML-сценарий |
| `document-legacy-jmeter` | **новый** | `.jmx` → человекочитаемая документация |
| `scenario-to-gatling` | **новый** | YAML-сценарий → Java-симуляция |
| `debug-with-sut` | **новый** | отладка по репозиторию SUT |
| `gatling-configuration-as-code`, MCP-сервер | gatling-ai-extensions | **исключены** (Enterprise) |

### 7.3. Сборка, запуск и CI

- **Сборка:** поддержка **Maven и Gradle** (в целевых проектах встречаются оба). Агент детектит систему сборки и использует соответствующий путь:
  - Maven: `gatling-maven-plugin 4.21.7` → `mvn gatling:test -Dgatling.simulationClass=...`
  - Gradle: `io.gatling.gradle` plugin (версия, совместимая с core 3.12) → `gradle gatlingRun`
- **Отчёты:** `target/gatling` (Maven) / `build/reports/gatling` (Gradle).
- **Задел под Jenkins / удалённые агенты:** генерация `Jenkinsfile`/job-шаблона и параметризованного запуска (env, профиль нагрузки), запуск на удалённой машине агентов — архитектура расширяемая; реализация — фаза 4.

---

## 8. Нефункциональные требования

- NFR1. **Корректность:** сгенерированный код компилируется (`mvn compile`) и запускается без ручных правок в типовых случаях.
- NFR2. **Воспроизводимость:** фиксированные версии (Gatling 3.12, maven-plugin 4.21.7, Java).
- NFR3. **Переносимость:** скиллы работают в Gigacode без зависимостей от Claude-специфичных API.
- NFR4. **Прозрачность:** каждый этап оставляет ревьюируемый артефакт (сценарий, отчёт конвертации, документация).
- NFR5. **Безопасность:** токены Confluence/доступ к репо SUT — через переменные окружения/секреты, не хардкодятся.
- NFR6. **Идемпотентность конвертации:** повторный прогон не ломает ручные правки без предупреждения.
- NFR7. **Quality gate как контракт:** агент не сообщает о готовности результата без явного статуса проверок и ссылок на отчёты.
- NFR8. **Минимизация шума:** хуки запускают только релевантные проверки для изменённых файлов; полный прогон выполняется перед завершением задачи или по явной команде.
- NFR9. **Fail closed для критичных проверок:** schema validation, compile, secret/PII scan и destructive-command guard являются blocking; style warnings не блокируют MVP, но фиксируются в отчёте.
- NFR10. **Единая таксономия отчётов:** имена сценариев, транзакций, групп и запросов должны быть стабильными, читаемыми и пригодными для сравнения Gatling-отчётов между прогонами.
- NFR11. **Управляемые исключения:** любое отклонение от style/transaction/check lint фиксируется как waiver с причиной; silent ignore запрещён.

---

## 9. Дорожная карта (фазы)

| Фаза | Содержание | Результат |
|---|---|---|
| **0. Фундамент** | Структура репо, адаптация каркаса Superpowers под Gigacode, схема сценария | Шаблон + 1 сквозной пример |
| **1. MVP** | `scenario-from-docs` (ручной ввод + файлы) + `scenario-to-gatling` + локальный запуск + базовый `quality-gate` | Требование → запускаемый Java-тест + отчёт самопроверки |
| **2. Миграция** | `gatling-convert-from-jmeter` + `document-legacy-jmeter` | JMeter → Gatling + документация |
| **3. Интеграции** | Confluence API/MCP, `debug-with-sut` | Автоввод + отладка по SUT |
| **4. CI/Remote** | Jenkins job / удалённые агенты | Параметризованный запуск в CI |

---

## 10. Метрики успеха

- M1. Доля сгенерированных симуляций, компилирующихся с первого раза, ≥ 90%.
- M2. Доля JMeter-элементов, сконвертированных автоматически (без TODO), ≥ 80%.
- M3. Время «требование → зелёный локальный прогон» ≤ 1 час для типового сценария.
- M4. Машиночитаемый сценарий принимается ревьюером без структурных правок в ≥ 70% случаев.
- M5. Доля задач имплементации, завершённых со статусом `quality-gate: passed` или `passed_with_warnings`, ≥ 95%.
- M6. Доля blocking-дефектов, найденных quality gate до финального ответа агентом, ≥ 80% от дефектов, найденных человеком при ревью.
- M7. Среднее время базового quality gate для MVP-сценария ≤ 3 минуты локально.
- M8. Доля сгенерированных Gatling-скриптов без blocking-нарушений `script-style-lint`, ≥ 95%.
- M9. Доля транзакций/групп с корректным именованием и трассируемостью к YAML/JMeter source, ≥ 98%.

---

## 11. Риски и допущения

| Риск | Влияние | Митигация |
|---|---|---|
| **Kafka/JDBC-плагины Scala-ориентированы и могут не работать из Java DSL / с 3.12** | **Высокое** | Spike в фазе 2: проверить galax-io Kafka на 3.12+Java; для JDBC — кастомный action поверх JDBC-драйвера; заглушки с TODO при провале |
| Механика subagents в Gigacode отличается от Claude | Среднее | Контрольный spike на 1 скилле в фазе 0 (риск понижен — Gigacode ≈ Qwen Code) |
| Официальные скиллы предполагают Enterprise/MCP | Среднее | Изолировать Enterprise-части, запуск только локальный Maven/Gradle |
| Сложные/нестандартные элементы JMeter | Среднее | Явные TODO + ручная доводка, отчёт конвертации |
| Поддержка двух систем сборки (Maven + Gradle) | Среднее | Детект сборки в `gatling-build-tools`, два пути запуска |
| Расхождение версий Gatling в скиллах vs 3.12 | Среднее | Закрепить версии в bootstrap и проверках сборки |
| Хуки Gigacode могут отличаться от Claude Code или отсутствовать | Высокое | В фазе 0 провести spike на hook lifecycle; предусмотреть fallback через явную команду `quality-gate` |
| Линтеры могут создавать шум и тормозить агентскую петлю | Среднее | Scoped-проверки после изменений, полный прогон только перед финалом; разделение blocking/warning |
| Субагент-валидатор может формально подтверждать результат без реальной проверки | Среднее | Валидатор read-only, обязан ссылаться на артефакты и вывод команд; без отчёта quality gate статус не принимается |

---

## 12. Открытые вопросы

**Закрыто (уточнено 2026-06-03):**
- ✅ Платформа: Gigacode ≈ последняя Qwen Code, модель `qwen3-coder-next 480b`.
- ✅ Confluence: штатный **Atlassian MCP** (чтение требований + публикация документации легаси).
- ✅ Сборка: **и Maven, и Gradle**.
- ✅ Протоколы легаси: **Kafka, GraphQL (редко), PostgreSQL/JDBC** (+ HTTP).
- ✅ Документация легаси: нет нормальной → источник истины `.jmx`+код SUT, цель — единый шаблон, публикуемый в Confluence.

**Остаётся уточнить:**
1. Версии: Java (17/21?), Scala-версия для community-плагинов (2.13), версия Gradle-плагина Gatling под core 3.12.
2. Confluence: Cloud или Server/Data Center (влияет на возможности Atlassian MCP)?
3. Формат хранения **тестовых данных** (feeders) и требования к **маскированию** чувствительных данных (пароли, PII)?
4. Какой **JDBC/Kafka-стек** уже используется (драйвер PG, клиент Kafka, схемы топиков) — для выбора пути генерации?
5. Структура целевого Confluence-space для публикации документации (родительские страницы, шаблон, права)?
6. Какие hook-события реально доступны в Gigacode/Qwen Code и можно ли блокировать финальный ответ через Stop/SubagentStop-equivalent?
7. Какой минимальный набор линтеров утверждаем для MVP: только schema+compile+smoke или сразу secret scan/Markdown/JMeter coverage?
8. Какой формат имён транзакций утверждаем как корпоративный стандарт: гибридный `<NN> <domain>.<action> - <title>` или более короткий `domain.action`?
9. Нужны ли разные профили линтинга: `mvp`, `strict`, `ci`, `migration`, или достаточно одного рекомендуемого профиля?

---

## Приложение A. Стек (зафиксировано)

- Gatling core: **3.12**
- gatling-maven-plugin: **4.21.7** (+ Gradle-плагин Gatling, версия под core 3.12)
- Язык симуляций: **Java**
- Сборка/запуск: **локальные Maven и Gradle** + задел под Jenkins/удалённые агенты
- Протоколы: HTTP (нативно), GraphQL (поверх HTTP), Kafka/JDBC (community-плагин или кастомный action)
- Confluence: **штатный Atlassian MCP** (чтение + публикация)
- Gatling Enterprise: **не используется**
- Платформа агента: **Gigacode** (форк Qwen Code, модель `qwen3-coder-next 480b`)
- Контур качества: **hook-driven quality gate** + `script-style-lint` + read-only `validator-subagent` + отчёты `quality-gate-report.json/md`

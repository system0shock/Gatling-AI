# Фаза 1 (MVP) — дизайн

**Дата:** 2026-06-10
**Статус:** согласован в брейншторме, готов к планированию
**Контекст:** PRD §9 фаза 1 — `scenario-from-docs` + `scenario-to-gatling` + локальный запуск + базовый quality-gate. Большая часть quality-gate уже построена в фазе 0 (schema, lint+waivers, генератор, рендерер, гейт, hook router).

## Цель

Замкнуть цикл «требование → запускаемый Java-тест Gatling + отчёт самопроверки» на инструментах этого репозитория и двух новых агентских скиллах.

## Зафиксированные решения

| Вопрос | Решение |
|---|---|
| Входы scenario-from-docs | Диалог + локальные Markdown/текст файлы. PDF и Confluence — вне фазы (Confluence — фаза 3) |
| Объём генератора | HTTP + GraphQL; все профили нагрузки (open/closed × ramp/constant/stress/soak/spike); pause; css/jsonPath/regex экстракторы |
| Несколько скриптов в симуляции | `populations` внутри одного файла сценария (вариант A); манифест-сборка нескольких файлов — позже, аддитивно |
| SUT для smoke | Локальный детерминированный mock-сервер (stdlib Python, декларативный конфиг маршрутов); реальный SUT — по `BASE_URL` |
| Сборка | Только Maven (Gatling 3.12, gatling-maven-plugin 4.21.7); Gradle — следующие фазы |
| Scaffold | Bootstrap нового Maven-проекта из шаблона + встраивание в существующий (детект `pom.xml`) |
| Приёмка фазы | E2E-прогон в этом репозитории (агент-прокси); перенос в Gigacode — отдельный шаг вне фазы |

## Архитектурный подход: contract-first

`scenario.yaml` остаётся единственным контрактом. Порядок работ: расширение схемы → синхронное обновление всех потребителей (lint → генератор → рендерер → contract-coverage-тест → гейт) → mock-сервер и scaffold → скиллы поверх готовых инструментов → E2E. Contract-coverage-тест из фазы 0 — принудительный синхронизатор: новое поле схемы без поддержки в генераторе и рендерере роняет тест.

Отвергнутые альтернативы: skill-first (скиллы переписывались бы после каждого расширения контракта; главный риск фазы — выразительность контракта, а не процесс); «умные инструменты» (детерминированный парсер прозы — хрупко и противоречит FR1.4: неоднозначность решается вопросами агента, не эвристиками).

## 1. Контракт: `scenario.schema.json` v0.2

### 1.1. Протоколы шага

`protocol: http | graphql`. В схеме `oneOf`: `protocol: http` + блок `request`, либо `protocol: graphql` + блок `graphql`:

```yaml
- name: "search-products"
  protocol: graphql
  graphql:
    path: "/graphql"          # опционально, default /graphql
    query: "query($q:String){ search(q:$q){ id } }"
    variables: { q: "${term}" }
  checks:
    - status: 200
    - extract: { type: jsonPath, expr: "$.data.search[0].id", saveAs: productId }
```

GraphQL реализуется поверх HttpDsl как POST с JSON-телом `{query, variables}` — без плагинов (PRD §5.6). Kafka/JDBC — вне фазы (фаза 2, после spike).

### 1.2. Экстракторы

`extract.type` — enum `css | jsonPath | regex` (было: свободная строка).

### 1.3. Think time

Опциональное поле шага `pause_seconds` (число > 0) → `pause(Duration.ofSeconds(n))` после запроса. Рандомизированные паузы (min/max) — позже, расширение аддитивно.

### 1.4. Профили нагрузки

`load.model: open | closed`, `load.profile: ramp | constant | stress | soak | spike` (enum вместо свободных строк). Каждая комбинация — своя ветка `oneOf` со строго своим набором полей; лишние поля отвергаются схемой.

| profile | общие поля | closed (доп.) | open (доп.) | семантика Gatling |
|---|---|---|---|---|
| `ramp` | `ramp_seconds`, `duration_seconds` | `users` | `users_per_second` | разгон 0→target, затем полка |
| `constant` | `duration_seconds` | `users` | `users_per_second` | сразу полка |
| `soak` | `duration_seconds` | `users` | `users_per_second` | как constant; отдельное имя — намерение и отчёт; lint-warning при duration < 1800 с |
| `stress` | `levels`, `level_duration_seconds` | `users` (пик) | `users_per_second` (пик) | ступени `incrementConcurrentUsers` / `incrementUsersPerSec` до пика |
| `spike` | `baseline_seconds`, `spike_rise_seconds`, `spike_hold_seconds` | `users` (пик), `baseline_users` | `users_per_second` (пик), `baseline_users_per_second` | полка-базлайн → резкий всплеск → возврат к базлайну |

Выбраны **именованные профили с фиксированными параметрами**, а не компонуемый список injection-шагов: именованный профиль — язык требований и ревью; произвольную композицию агент может собрать неверно, и lint её не проверит. Компонуемость — возможное аддитивное расширение позже.

### 1.5. Populations (несколько скриптов в одной симуляции)

В `scenario` — `oneOf`: либо текущая форма `steps` + `load` (сахар для одной популяции), либо `populations` (minItems 1), каждая со своими `name`, `steps`, `load`. Фидеры (`data`), `sut` и `assertions` — общие на сценарий:

```yaml
scenario:
  id: "checkout-mix"
  sut: { base_url: "${BASE_URL}" }
  data: { feeders: [...] }
  populations:
    - name: main-checkout
      steps: [...]
      load: { model: closed, profile: ramp, users: 100, ramp_seconds: 60, duration_seconds: 600 }
    - name: background-search
      steps: [...]
      load: { model: open, profile: constant, users_per_second: 5, duration_seconds: 600 }
  assertions: [...]
```

Маппинг: одна популяция → один `ScenarioBuilder`; общий `setUp(...)` собирает инжекции всех популяций. При миграции JMeter (фаза 2) Thread Group ложится в population один к одному.

### 1.6. Без изменений

`assertions` (грамматика `global.*`), `lint_waivers`, `source`, `sut` — как в фазе 0.

## 2. Генератор, scaffold, mock-сервер

### 2.1. Генератор (`tools/gatling_generator`)

- Вход нормализуется к списку популяций (`steps`+`load` → одна популяция).
- GraphQL-шаг → `http(...).post(path).body(StringBody(...)).asJson()`; сериализация JSON-тела детерминированная (sort_keys) — drift-check не ломается.
- Экстракторы css/jsonPath/regex → соответствующий DSL; `pause_seconds` → `pause(...)`.
- Профили — по таблице 1.4; неизвестная комбинация/поле → `ValueError` со структурированным finding (`--format json`, механика фазы 0); «молчаливо неверный» код запрещён (FR5.6.3).
- Детерминизм генерации сохраняется (гейт прогоняет дважды и сравнивает).

### 2.2. Scaffold (bootstrap + встраивание)

- Нет `pom.xml` в `--output` → bootstrap: проект из шаблона `tools/gatling_generator/templates/pom.xml` (пины Gatling 3.12 / plugin 4.21.7 / Java) + `src/test/java`, `src/test/resources`.
- Есть `pom.xml` → встраивание: пишутся только симуляция и ресурсы; гейт проверяет пины Gatling в pom (block при расхождении).
- Шаблон — отдельный файл (ревьюируемый, доступен drift-проверке), не строка в коде.

### 2.3. Mock-сервер (`tools/mock_sut`)

Python stdlib, без зависимостей. Поведение — декларативный конфиг маршрутов:

```json
{ "routes": [
  { "method": "GET",  "path": "/login",   "status": 200, "body_file": "login.html" },
  { "method": "POST", "path": "/login",   "status": 302, "headers": { "Location": "/home" } },
  { "method": "POST", "path": "/graphql", "status": 200, "body_file": "search.json" }
] }
```

Конфиги golden-примеров коммитятся в `examples/mock/`. Автогенерации ответов из сценария нет — рукописный конфиг прозрачнее и не дрейфует. Служебный `GET /__health` — readiness.

### 2.4. Локальный запуск в гейте

`--smoke` расширяется: при `--mock-routes PATH` гейт поднимает mock на свободном порту, ждёт `/__health`, запускает `mvn gatling:test -Dgatling.simulationClass=...` с `BASE_URL=http://127.0.0.1:<port>`, глушит mock, разбирает результат (exit code Maven + assertions из вывода Gatling) в findings. Без `--smoke` поведение прежнее: реальная нагрузка не запускается без явного разрешения (FR5.7.7).

## 3. Скиллы

Оба — `SKILL.md` в `skills/`, переносимые в Gigacode копированием в `.qwen/skills/`; без Claude-специфичных API (NFR3). Проверяемая логика — в инструментах; скиллы описывают процесс.

### 3.1. `scenario-from-docs`

1. Сбор входа: чтение указанных .md/.txt + диалог.
2. Извлечение сущностей по чек-листу FR1.3 (endpoints, методы, заголовки/тела, статусы, профиль, think time, фидеры, корреляции, проверки, окружения); каждой сущности статус `известно / выведено (требует подтверждения) / неизвестно`.
3. Уточняющие вопросы — по одному; угадывать запрещено (FR1.4). Минимум для продолжения: `base_url`-плейсхолдер, шаги с checks, профиль нагрузки, ≥1 SLA assertion. Неразрешённое — `# TODO:`-комментарии в YAML.
4. Самопроверка: `scenario_lint` → починка blocking → рендер Markdown-паспорта пользователю на ревью.
5. Выход: lint-чистый `scenario.yaml` + рендер + открытые вопросы. К генерации кода — только после подтверждения сценария пользователем.

### 3.2. `scenario-to-gatling`

1. Прекондиция: lint `passed` (иначе — назад в scenario-from-docs).
2. Детект проекта: `pom.xml` есть → встраивание; нет → bootstrap (генератор делает сам).
3. Генерация `gatling_generator --format json`; ошибки чинятся правкой **сценария**, не Java (Java — одноразовый артефакт, источник истины — YAML).
4. `mvn compile`; затем — с явного разрешения пользователя — smoke против mock или реального SUT (`BASE_URL`). Цикл «запуск → разбор → правка → повтор» по дисциплине systematic debugging до зелёного.
5. Финал — обязательный quality gate: `passed`/`passed_with_warnings` + отчёты; `blocked` — не отдаём (FR5.7.5, NFR7).

### 3.3. Существующие скиллы

`quality-gate` SKILL.md дополняется `--smoke`/`--mock-routes` и populations. Установка скиллов и сквозной пример — в `docs/GETTING_STARTED.md`.

## 4. Контур качества и приёмка

### 4.1. `scenario_lint` — новые правила

- populations: уникальность `name` (kebab-case, FR5.8.1); уникальность транзакций через всю симуляцию; у каждой популяции валидный собственный `load`.
- Профили: значения > 0; `stress.levels ≥ 2`; spike: baseline < пика; soak: warning при `duration_seconds < 1800`.
- GraphQL: непустой `query`; обязательный `status`-check (всегда POST → правило mutating FR5.8.9); `variables` участвуют в correlation-lint как тело HTTP.
- `pause_seconds > 0`.

### 4.2. Рендерер

Подсекции для каждой популяции (шаги + профиль); graphql-query код-блоком; пауза в таблице шагов; человекочитаемое описание профиля («ступени: 5 уровней по 60 с до 100 пользователей»).

### 4.3. Contract-coverage

Тест расширяется на все новые поля схемы: поле без поддержки в генераторе и рендерере роняет тест.

### 4.4. Quality gate

Жизненный цикл mock в `--smoke` (2.4); проверка пинов в `pom.xml` для встраивания; **второй golden-пример `checkout-mix`** (populations + graphql + open model + stress + pause) с mock-конфигом. Гейт гоняет оба golden-сценария; invalid-fixtures — на новые правила lint.

### 4.5. Тестирование

Как в фазе 0: TDD, юнит-тесты рядом с каждым инструментом (запускаются напрямую), детерминизм и drift-check golden-артефактов (Java + Markdown).

### 4.6. Критерий приёмки фазы (E2E)

В репо добавляется `examples/requirements/checkout-mix.md` — реалистичный документ требований. Прогон агентом-прокси: требования → диалог → `scenario.yaml` (lint passed) → bootstrap чистого Maven-проекта → компиляция → smoke против mock зелёный → `quality-gate: passed`. Эталонный walkthrough фиксируется в `docs/GETTING_STARTED.md`. Перенос и проверка в Gigacode — отдельный шаг вне фазы.

## Вне фазы 1

Kafka/JDBC (фаза 2, после spike), Confluence MCP (фаза 3), Gradle, PDF-входы, манифест simulation.yaml, рандомизированные паузы, per-transaction assertions, Jenkins/CI (фаза 4).

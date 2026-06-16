# Дизайн: упаковка решения под Gigacode (`.gigacode/`)

Дата: 2026-06-16. Статус: утверждён пользователем (диалог), ожидает ревью спеки.

## Цель

Собрать все агент-фейсинговые артефакты проекта в канонический каталог
конфигурации `.gigacode/` по конвенциям Qwen Code (Gigacode = корпоративный
форк Qwen, отличие только в имени каталога и переменных окружения), закоммитить
его в этот репозиторий и закрыть разрывы соответствия, найденные при ревью.

Эталон конвенций — официальная документация Qwen Code:
[settings](https://github.com/QwenLM/qwen-code/blob/main/docs/users/configuration/settings.md),
[skills](https://github.com/QwenLM/qwen-code/blob/main/docs/users/features/skills.md),
[sub-agents](https://github.com/QwenLM/qwen-code/blob/main/docs/users/features/sub-agents.md),
[commands](https://github.com/QwenLM/qwen-code/blob/main/docs/users/features/commands.md),
[hooks](https://github.com/QwenLM/qwen-code/blob/main/docs/users/features/hooks.md).

## Контекст: результаты ревью на соответствие Qwen Code

- 4 из 5 скиллов соответствуют формату (валидный `name` + `description`).
- **Баг:** `skills/quality-gate/SKILL.md` без YAML-фронтматтера → Qwen его не
  зарегистрирует (нет обязательных `name`/`description`).
- Claude-специфики в телах скиллов нет (NFR3 соблюдён); Atlassian MCP — ОК
  (Qwen поддерживает `mcpServers`).
- `settings.json` под Qwen отсутствует; `.claude/settings.local.json` —
  Claude-специфичен и непереносим.
- `validator-subagent`, hooks, commands, контекст-файл — описаны в доках, но не
  реализованы.
- Нюансы: инструменты `tools/` зовутся по относительному пути (project-only,
  не self-contained в скилле); примеры команд с bash-переносом `\` на Windows
  не копируются as-is.

## Решения

### 1. Каталог `.gigacode/` — единый дом, single-source

```
.gigacode/
├── settings.json                 # Qwen-схема: context, hooks, (опц.) permissions/mcp
├── skills/                       # перенос из корня; корневой skills/ удаляется
│   ├── scenario-from-docs/SKILL.md
│   ├── scenario-to-gatling/SKILL.md
│   ├── quality-gate/SKILL.md      # + новый фронтматтер (фикс)
│   ├── convert-from-jmeter/SKILL.md
│   └── document-legacy-jmeter/SKILL.md
├── agents/
│   └── validator-subagent.md     # read-only ревьюер
├── commands/
│   └── quality-gate.md           # команда /quality-gate
├── hooks/
│   ├── lint_scenario.py          # PostToolUse: авто-линт правки scenario.yaml
│   └── gate_reminder.py          # Stop: нудж по quality-gate-отчёту
└── README.md                     # назначение, install, confirm-items

GIGACODE.md                       # корень репо: working rules + карта (агент-контекст)
```

`tools/`, `schemas/`, `examples/` остаются в корне и зовутся по относительному
пути. `.claude/` остаётся как dev-тулинг для работы над репо (не часть продукта).

Скиллы переносятся в `.gigacode/skills/` как **единственный источник истины**;
корневой `skills/` удаляется. Код на путь `skills/` не завязан (единственное
вхождение в `gatling_generator.py` — строка-комментарий). Правятся только
install-инструкции в доках.

### 2. `settings.json` (схема Qwen, минимально)

Имя модели Gigacode НЕ хардкодится. Состав:

| Ключ | Назначение |
|---|---|
| `context.fileName: ["GIGACODE.md"]` | Явно подключить контекст-файл, не полагаясь на дефолт Gigacode |
| `hooks` | Слоёный блок (раздел 3) |
| `permissions` *(опц.)* | Пре-аллоу на `python tools/...`, чтобы убрать постоянные запросы. Точный синтаксис матчеров сверяется по доке Qwen `permissions` на этапе реализации |

Atlassian MCP для Confluence (`document-legacy-jmeter`) **не** кладётся в
`settings.json` (JSON не допускает комментариев, а реальных кред у нас нет) —
пример конфигурации `mcpServers` документируется в `.gigacode/README.md`; в
`settings.json` ключ опускается.

### 3. Hooks — слоёные, деградируют мягко

| Событие | Скрипт | Поведение |
|---|---|---|
| `PostToolUse` (matcher на запись файлов) | `lint_scenario.py` | Читает stdin-JSON; если правился `*/scenario.yaml` — гоняет `scenario_lint.py` на нём. Дёшево, контекст проекта не нужен |
| `Stop` | `gate_reminder.py` | Детерминированно по mtime: если самый свежий `scenario.yaml` (под `scenarios/` и `examples/scenarios/`) новее `quality-gate-report.json` или отчёт отсутствует — **advisory** напоминание (exit 0, не блок) |

- Полный гейт (`--project`, compile, smoke) — только явная команда/скилл.
- Скрипты на Python (кросс-платформенно). Запуск с CWD = корень проекта;
  относительные пути вместо опоры на env-var проекта.
- Блокирующий режим `Stop` возможен, но дефолт — мягкий нудж.
- Если Gigacode не поддерживает хуки — команда `/quality-gate` и скилл работают
  без них.

### 4. Subagent `validator-subagent.md`

Фронтматтер Qwen: `name`, `description`, `model: inherit`, `approvalMode`,
`tools` (read-only allowlist), `disallowedTools` (запрет инструментов записи).
Системный промпт — read-only ревьюер, проверяющий перед хэндоффом:

- lint целевого `scenario.yaml` = `passed`;
- `quality-gate-report.json` существует и статус `passed`/`passed_with_warnings`;
- паспорт (`passport.md`) в синхроне со сценарием;
- вердикт `accept` / `blocked` с путём к отчёту и кратким обоснованием.

Совпадает с ролью read-only валидатора из `ARCHITECTURE.md`.

### 5. Command `/quality-gate`

`commands/quality-gate.md` с фронтматтером `description`; тело — промпт,
инструктирующий вызвать скилл `quality-gate` для текущего scenario/project и
честно отчитаться по статусу. UX-ярлык к уже существующему скиллу; каталог —
дом для будущих команд.

### 6. Фикс `quality-gate/SKILL.md`

Добавляется фронтматтер (как часть переноса):

```yaml
---
name: quality-gate
description: Use before handing back any Gatling-AI scenario or generated Java change. Runs the local quality gate (schema, lint, generator, passport sync, Maven compile, optional smoke) and interprets the report status — never report work done without a passed/passed_with_warnings gate.
---
```

### 7. `GIGACODE.md` (контекст-файл, корень репо)

Всегда-в-контексте working rules + карта проекта: Gatling OSS only, Java only,
Maven-first, не отчитываться без quality-gate; где лежат `scenarios/` / `tools/`
/ `schemas/`; ссылки на ключевые доки. Переносит «Working Rules» из
`GETTING_STARTED.md` в загружаемый агентом слой (источник правил — по-прежнему
доки; `GIGACODE.md` — компактная выжимка с указателями).

### 8. Правки документации

- `GETTING_STARTED.md` §6: install `skills/` → `.gigacode/skills/`; personal —
  `~/.gigacode/skills/`.
- `ARCHITECTURE.md`: обновить структуру, добавить раздел про `.gigacode/`.
- `README.md`: упомянуть `.gigacode/` как пакет конфигурации.

## Confirm-items (спайк Gigacode — известные неизвестные, не блокеры)

1. Имя каталога `.gigacode/` и что схема `settings.json` байт-в-байт как Qwen.
2. Дефолтное имя контекст-файла (подстраховано `context.fileName`).
3. Env-var проекта в хуках (`$QWEN_PROJECT_DIR` ↔ Gigacode-аналог) — обходится
   относительным путём от CWD.
4. Сохранил ли Gigacode механизм хуков (слоёный дизайн работает и без них).

Эти пункты документируются в `.gigacode/README.md` для проверки при появлении
доступа к Gigacode.

## Проверка (verification)

- Все 5 `SKILL.md` имеют валидный фронтматтер (`name` + непустой `description`),
  `name` соответствует паттерну Qwen `/^[\p{L}\p{N}_:.-]+$/u`.
- `lint_scenario.py` на правке `scenario.yaml` запускает существующий
  `scenario_lint.py` и возвращает его статус; на правке постороннего файла —
  no-op (exit 0).
- `gate_reminder.py` корректно определяет «отчёт старее правок / отсутствует» и
  печатает напоминание, exit 0.
- `validator-subagent.md` и `commands/quality-gate.md` парсятся как валидные
  Qwen-артефакты (фронтматтер по схеме).
- `settings.json` — валидный JSON по схеме Qwen; `context.fileName` указывает на
  `GIGACODE.md`.
- Существующий quality-gate прогон в репозитории остаётся зелёным; ни один тест
  не ссылается на старый путь `skills/` (проверить грепом перед удалением).

## Вне scope

- Реальная интеграция/спайк на живом Gigacode (отдельный шаг при появлении
  доступа) — здесь только подготовка артефактов и фиксация confirm-items.
- Изменение логики инструментов (`tools/`) и схем (`schemas/`).
- Доп. слэш-команды сверх `/quality-gate` (каталог `commands/` — задел).

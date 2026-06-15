# Фаза 2c: скиллы миграции + golden e2e — дизайн

> Тонкий дизайн-док инкремента 2c. Опирается на утверждённую спеку Фазы 2
> (`2026-06-11-phase-2-migration-design.md`, §5–§10) и фиксирует то, что та
> оставила эскизно: архитектуру конвертера, конкретные mapping-правила,
> сходимость диспозиции и шаблоны. Контракт сценария — расширения Фазы 2b
> (PR #5): `stages`, `start_after_seconds`, `body_file`, `tags`, `hooks`,
> `protocol: kafka|jdbc`.

## 1. Объём инкремента

В 2c входит: два скилла (`document-legacy-jmeter`, `convert-from-jmeter`),
один новый детерминированный тул (`ir_to_scenario`), два golden `.jmx` с
end-to-end-прогоном и юнит-тесты.

**Вне объёма:** спайк Kafka/JDBC (спека Фазы 2 §9) — отдельный поздний
инкремент; здесь kafka/jdbc остаются стабами Фазы 2b.

## 2. Позиционирование относительно официального конвертера Gatling

Gatling выпустил официальный OSS-скилл `gatling-convert-from-jmeter`
(`gatling/gatling-ai-extensions`, Apache-2.0): prompt-driven, LLM читает `.jmx`
и пишет Gatling-код напрямую; нет паспорта, контракт-first-промежутка, lint/gate,
сходимости диспозиции, нормализации всех flavors TG, сверки с Confluence,
глубокого перевода JSR223. Наша линия — **contract-first с ревью-гейтами** —
не дублирует его. Из их `SKILL.md` (Apache-2.0) **заимствуем mapping-правила**
(функции, экстракторы, redirects, feeder `shareMode`, правило EL-side-effect)
с атрибуцией в нашем коде/доке.

## 3. Поток и компоненты

```
.jmx ──[jmx_parser (2a)]──► ir.json + inventory.md + bodies/ + jsr223/*.groovy
                                      │
            ┌─────────────────────────┴─────────────────────────┐
            ▼                                                     ▼
[skill: document-legacy-jmeter]                      [tool: ir_to_scenario (НОВЫЙ)]
  парсер → inventory (Гейт 1) →                        ir.json → scenario.yaml
  срезы + Confluence → passport.md (Гейт 2)            + conversion-report.md
            │                                                     ▲
            └──────────── паспорт — предусловие ───────────────────┘
                                      ▼
[skill: convert-from-jmeter]  оркестрирует ir_to_scenario (проход 1) →
  Гейт 3 (scenario-lint + ревью отчёта) → JSR223 проход 2 (агент переводит) →
  передача в существующий scenario-to-gatling → quality gate
```

**Защита контекста агента (NFR из диалога Фазы 2):** полный граф — в `ir.json`;
его читает **тул** `ir_to_scenario`. Агент работает с курируемыми срезами —
`inventory.md`, `passport.md`, `conversion-report.md` и CLI-срезами парсера
(`--summary`, `--element <id>`). Прямое чтение `ir.json`/полного дерева агенту
запрещено скиллами.

## 4. Тул `ir_to_scenario` (детерминированные ~90%)

- **Вход:** путь к `ir.json` (+ папка миграции с `bodies/`); **выход:**
  `scenario.yaml` + `conversion-report.md`.
- **Владеет:** load (из `normalized`), шаги (sampler→step), checks
  (assertions+экстракторы), feeders (CSV), env (UDV), `body_file`, `tags`,
  стабы `kafka`/`jdbc`, и **таблица диспозиции**.
- **Чистый и тестируемый**, культура репо: юнит-тесты на маппинг + контрактные
  проверки. **Идемпотентность (NFR6):** не перезаписывает молча — показывает
  дифф и просит подтверждение; ручные правки (`scenario.yaml` после Гейта 3,
  `snippets/`) не трогает без явного согласия.
- **Граница тул/агент:** тул не делает суждений. Бизнес-имена транзакций тул
  только *засевает* по маске из имён TransactionController/семплеров; финально
  уточняет агент (в паспорте/на Гейте 3). JSR223 complex и неоднозначности —
  всегда агент.

## 5. Mapping-правила (наши + заимствованные у Gatling, с атрибуцией)

| JMeter | → scenario.yaml |
|---|---|
| TG (5 flavors) | `load` из `normalized` парсера; `normalized=None` → **блокирующий** finding с причиной |
| Sampler | `step` (method/path/headers); тело → `body_file` |
| Имя TransactionController/семплера | тул засевает маску `NN domain.action - Title`; агент уточняет |
| ResponseAssertion / regex·jsonPath·jmesPath·xpath·boundary | `checks` (status/substring + `extract.saveAs`); нюансы JMESPath (matchNumber, типизация `.ofInt/.ofList`) — у Gatling |
| CSVDataSet | `feeder`; `shareMode` → strategy/scope (у Gatling) |
| UDV | env `${VAR}` / `sut.base_url` |
| `${__UUID/__time/__Random}`, changeCase/digest/url(en/de)code/escape | typical → переводы (у Gatling; escape через `unbescape`); `${__P}` → env; неизвестные → todo-хук |
| JSR223 typical (классификатор 2a) | Java-сниппет сразу (Session-immutable; правило «EL не сохраняет side-effect → `exec`-блок» у Gatling) |
| JSR223 complex / любое `props` | `hooks: kind: todo` → **проход 2**, перевод агентом с ревью |
| kafka-via-proxy | HTTP-шаг + тег `kafka-via-proxy` |
| Kafka-producer / JDBC-семплер | `protocol: kafka`/`jdbc` стаб (2b) |
| redirects (`follow_redirects=false`) | `disableFollowRedirect` (у Gatling) |

**Зафиксированные решения дизайна:**
- Нагрузка всегда эмитится как `profile: stages` (парсер уже даёт stages-форму) —
  ради точности и детерминизма; упрощение до `ramp` не делаем.
- Имена транзакций: тул засевает, агент уточняет (не чистый авто, не чистый агент).

## 6. Сходимость диспозиции (анти-silent-drop)

`conversion-report.md` перечисляет **каждый** элемент IR со статусом
`converted | partial | todo | skipped-disabled`. **Сумма обязана сойтись со
счётчиками `inventory.md`** — проверяется юнит-тестом И quality-gate. Это
метрика M2 (≥80% auto) и гарантия отсутствия молчаливых потерь (которой нет у
скилла Gatling).

## 7. Скилл `document-legacy-jmeter`

Без изменений к спеке Фазы 2 §5. Запуск парсера → `inventory.md` (Гейт 1; при
флагах сложности — явно «внимательный путь»). Опционально Confluence (через
Atlassian MCP или экспорт файлом) как контекст; **источник истины — IR**,
расхождения «доки vs скрипт» → отдельная секция паспорта, не разрешаются молча.
`passport.md` по шаблону (стиль паспорта сценария + легаси-секции: бизнес-процесс;
таблица транзакций оригинал→маска; потоки данных по шагам; таблица JSR223
typical/complex; профиль словами; env из UDV; зависимости; расхождения;
неподдержанное). Неоднозначность бизнес-смысла → вопрос (FR1.4). Скилл
самодостаточен (документация без конвертации). Гейт 2 — утверждение паспорта.

## 8. Скилл `convert-from-jmeter`

Без изменений к §6, уточнено разделением тул/агент:
- **Предусловие:** утверждённый паспорт (иначе → `document-legacy-jmeter`).
- **Шаг 0:** вопрос `system`/`id`/`number`; папка по layout.
- **Проход 1 (типовое):** скилл запускает `ir_to_scenario` → `scenario.yaml` +
  `conversion-report.md`.
- **Гейт 3:** `scenario-lint` + ревью YAML и отчёта (диспозиция сошлась).
- **Проход 2 (доводка JSR223):** по каждому `todo`-хуку: оригинал Groovy +
  контекст (vars in/out, описание из паспорта) → предложенный Java-перевод →
  пользователь утверждает/правит → сниппет сохраняется, `kind`→`translated`,
  отчёт обновляется. Остановка на любом блоке допустима — остальные остаются TODO.
- **Финал:** передача в существующий `scenario-to-gatling` (bootstrap, генерация,
  компиляция, smoke, quality gate). Оставшиеся `todo`-хуки →
  `manual_review_required` (механизм 2b) → статус `passed_with_warnings`.

## 9. Тестирование

- Юнит-тесты на `ir_to_scenario`: маппинг по типам элементов, сходимость
  диспозиции, нормализация load из `normalized`, перевод функций, классификация
  JSR223 typical/complex.
- **Два golden `.jmx`** в `examples/jmx/`:
  1. *простой бэкенд* — одна TG, транзакции, regex/jsonPath, CSV, UDV, типовые
     JSR223, крупное тело → полный путь до `gate passed` (smoke на mock);
  2. *сложный этапный* — две TG со сдвигом, передача через `props`, complex
     JSR223, kafka-via-proxy, JDBC-семплер → ожидаемые флаги сложности,
     конвертация с TODO, `passed_with_warnings`.
- Реальные скрипты пользователь прогоняет локально (гибрид), обратная связь —
  через `conversion-report.md`.

## 10. Критерии приёмки 2c

- Оба golden проходят свои пути с ожидаемыми статусами гейта.
- Диспозиция сходится на 100% (silent drop отсутствует) — тест + гейт.
- `document-legacy-jmeter` работает автономно (только документация).
- Атрибуция заимствованных у Gatling (Apache-2.0) mapping-правил присутствует
  в коде/доке тула.

## 11. Открытые вопросы (на проход реализации)

- Точный формат таблицы диспозиции в `conversion-report.md` (колонки, как
  ссылаться на элементы IR) — фиксируется в плане.
- Полнота набора переводов JMeter-функций на старте vs «неизвестное → todo» —
  стартовый набор из скилла Gatling, остальное в todo.

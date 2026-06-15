# Сценарий: Test Plan

> Сгенерировано из `examples/scenarios/SHOP/legacy-staged-011/scenario.yaml` (sha256 `c813fa42aff9`). Не редактировать вручную.

## Паспорт

- **ID:** `legacy-staged`
- **Скрипт:** `SHOP_LegacyStaged_011`
- **Источник требований:** jmeter / `staged-pipeline.jmx`
- **Базовый URL:** `${BASE_URL}`

## Популяция: `stage-a-producer`

### Шаги

| # | Транзакция | Метод | Путь | Пауза | Проверки | Теги |
|---|---|---|---|---|---|---|
| 1 | 01 legacy-staged.login - post login | POST | /login | — | extract `token` (jsonPath), status 200 | — |
| 2 | 02 legacy-staged.kafka-publish - produce event | POST | /kafka/produce?topic=orders | — | status 202 | kafka-via-proxy |

### JSR223-хуки

| Шаг | Когда | Тип | Что делает | Читает | Пишет | Оригинал | Сниппет |
|---|---|---|---|---|---|---|---|
| `post-login` | after | todo | share token | token | — | `migration/jsr223/a217d7ffb617.groovy` | — |

### Профиль нагрузки

Модель: **closed**, профиль: **stages**. Ступени: 1) разгон до 10 пользователей за 30 с, полка 570 с.

## Популяция: `stage-b-consumer`

### Шаги

| # | Транзакция | Метод | Путь | Пауза | Проверки | Теги |
|---|---|---|---|---|---|---|
| 1 | 03 legacy-staged.settle - post settle | POST | /settle | — | status 200 | — |
| 2 | 04 legacy-staged.check-ledger - check ledger | JDBC | SELECT balance FROM ledger WHERE id = ${productId} | — | — | — |

### JSR223-хуки

| Шаг | Когда | Тип | Что делает | Читает | Пишет | Оригинал | Сниппет |
|---|---|---|---|---|---|---|---|
| `post-settle` | before | todo | take token | — | authSig | `migration/jsr223/fb7284c37e60.groovy` | — |

### Профиль нагрузки

Модель: **closed**, профиль: **stages**. Ступени: 1) разгон до 5 пользователей за 30 с, полка 570 с.
Старт популяции: через **1200 с** после начала теста.

## Тестовые данные

| Фидер | Файл | Стратегия |
|---|---|---|
| products | `products.csv` | circular |

## Корреляции и переменные

| Переменная | Источник | Используется в шагах |
|---|---|---|
| `productId` | переменная окружения / feeder-колонка | `check-ledger`, `produce-event` |

## SLA (assertions)

| Имя | Метрика | Условие |
|---|---|---|
| p95-latency | `global.responseTime.p95` | < 1000 |
| success-rate | `global.successfulRequests.percent` | > 99 |

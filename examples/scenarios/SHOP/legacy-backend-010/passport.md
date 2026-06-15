# Сценарий: Test Plan

> Сгенерировано из `examples/scenarios/SHOP/legacy-backend-010/scenario.yaml` (sha256 `684c0418df4b`). Не редактировать вручную.

## Паспорт

- **ID:** `legacy-backend`
- **Скрипт:** `SHOP_LegacyBackend_010`
- **Источник требований:** jmeter / `simple-backend.jmx`
- **Базовый URL:** `${BASE_URL}`

## Шаги

| # | Транзакция | Метод | Путь | Пауза | Проверки | Теги |
|---|---|---|---|---|---|---|
| 1 | 01 legacy-backend.catalog-list - get catalog | GET | /catalog | — | extract `productId` (jsonPath), extract `price` (jsonPath), status 200 | — |
| 2 | 02 legacy-backend.catalog-search - search | GET | /search?q=${term} | 1 с | extract `csrf` (regex), status 200 | — |
| 3 | 03 legacy-backend.checkout-submit - post checkout | POST | /checkout | — | status 200 | — |

### Тела запросов

| Шаг | Файл тела |
|---|---|
| `post-checkout` | `bodies/b807328d3e37.json` |

### JSR223-хуки

| Шаг | Когда | Тип | Что делает | Читает | Пишет | Оригинал | Сниппет |
|---|---|---|---|---|---|---|---|
| `post-checkout` | before | translated | make request id | — | requestId | `migration/jsr223/0692b2c52e4c.groovy` | `snippets/MakeRequestId.java` |

## Профиль нагрузки

Модель: **closed**, профиль: **stages**. Ступени: 1) разгон до 50 пользователей за 120 с, полка 600 с.

## Тестовые данные

| Фидер | Файл | Стратегия |
|---|---|---|
| search-terms | `search-terms.csv` | circular |

## Корреляции и переменные

| Переменная | Источник | Используется в шагах |
|---|---|---|
| `term` | переменная окружения / feeder-колонка | `search` |

## SLA (assertions)

| Имя | Метрика | Условие |
|---|---|---|
| p95-latency | `global.responseTime.p95` | < 1000 |
| success-rate | `global.successfulRequests.percent` | > 99 |

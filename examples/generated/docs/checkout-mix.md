# Сценарий: Checkout with background search

> Сгенерировано из `examples/scenarios/checkout-mix.yaml` (sha256 `c7b2b9599446`). Не редактировать вручную.

## Паспорт

- **ID:** `checkout-mix`
- **Скрипт:** `?`
- **Источник требований:** file / `examples/requirements/checkout-mix.md`
- **Базовый URL:** `${BASE_URL}`

## Популяция: `main-checkout`

### Шаги

| # | Транзакция | Метод | Путь | Пауза | Проверки |
|---|---|---|---|---|---|
| 1 | 01 catalog.open-products - Open product list | GET | /products | 1 с | status 200, extract `productId` (jsonPath) |
| 2 | 02 catalog.gql-price - Fetch price via GraphQL | POST | /graphql | — | status 200 |
| 3 | 03 checkout.submit - Submit checkout | POST | /checkout | — | status 200 |

### GraphQL-запросы: `gql-price`

```graphql
query($id:ID!){ price(id:$id){ amount } }
```

### Профиль нагрузки

Модель: **closed**, профиль: **stress**. Ступенчатый рост: **2 уровней по 30 с** до 10 пользователей.

## Популяция: `background-search`

### Шаги

| # | Транзакция | Метод | Путь | Пауза | Проверки |
|---|---|---|---|---|---|
| 1 | 01 search.query - Search products | GET | /search?q=${term} | — | status 200 |

### Профиль нагрузки

Модель: **open**, профиль: **constant**. Постоянная нагрузка **2 запросов/с** в течение **60 с**.

## Тестовые данные

| Фидер | Файл | Стратегия |
|---|---|---|
| products | `products.csv` | circular |

## Корреляции и переменные

| Переменная | Источник | Используется в шагах |
|---|---|---|
| `productId` | извлекается в шаге `open-products` | `gql-price`, `submit-checkout` |
| `term` | переменная окружения / feeder-колонка | `search-products` |

## SLA (assertions)

| Имя | Метрика | Условие |
|---|---|---|
| p95-under-800ms | `global.responseTime.p95` | < 800 |
| ok-rate-above-99 | `global.successfulRequests.percent` | > 99 |

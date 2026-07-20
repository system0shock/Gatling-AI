# Сценарий: Checkout under stepped load with background catalog search

> Сгенерировано из `e2e/checkout-mix.yaml` (sha256 `15b6cf41b22f`). Не редактировать вручную.

## Паспорт

- **ID:** `checkout-mix`
- **Источник требований:** file / `examples/requirements/checkout-mix.md`
- **Базовый URL:** `${BASE_URL}`

## Популяция: `checkout`

### Шаги

| # | Транзакция | Метод | Путь | Пауза | Проверки |
|---|---|---|---|---|---|
| 1 | 01 catalog.list - Open product list | GET | /products | 1 с | status 200, extract `productId` (jsonPath) |
| 2 | 02 catalog.price - Get product price | POST | /graphql | — | status 200 |
| 3 | 03 checkout.submit - Submit checkout | POST | /checkout | — | status 200 |

### GraphQL-запросы: `get-price`

```graphql
query Price($id: ID!) {
  price(id: $id)
}

```

### Профиль нагрузки

Модель: **closed**, профиль: **stress**. Ступенчатый рост: **2 уровней по 30 с** до 10 пользователей.

## Популяция: `search`

### Шаги

| # | Транзакция | Метод | Путь | Пауза | Проверки |
|---|---|---|---|---|---|
| 1 | 04 catalog.search - Search catalog | GET | /search?q=${term} | — | status 200 |

### Профиль нагрузки

Модель: **open**, профиль: **constant**. Постоянная нагрузка **2 запросов/с** в течение **60 с**.

## Тестовые данные

| Фидер | Файл | Стратегия |
|---|---|---|
| terms | `search-terms.csv` | circular |

## Корреляции и переменные

| Переменная | Источник | Используется в шагах |
|---|---|---|
| `productId` | извлекается в шаге `open-products` | `get-price`, `submit-checkout` |
| `term` | переменная окружения / feeder-колонка | `search-catalog` |

## SLA (assertions)

| Имя | Метрика | Условие |
|---|---|---|
| p95-under-800ms | `global.responseTime.p95` | < 800 |
| success-rate-above-99 | `global.successfulRequests.percent` | > 99 |

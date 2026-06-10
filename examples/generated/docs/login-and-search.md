# Сценарий: Login and search product

> Сгенерировано из `examples/scenarios/login-and-search.yaml` (sha256 `89588d094d0c`). Не редактировать вручную.

## Паспорт

- **ID:** `login-and-search`
- **Источник требований:** manual / `initial-example`
- **Базовый URL:** `${BASE_URL}`

## Шаги

| # | Транзакция | Метод | Путь | Пауза | Проверки |
|---|---|---|---|---|---|
| 1 | 01 auth.open-login - Open login page | GET | /login | — | status 200, extract `csrf` (css) |
| 2 | 02 auth.login - Submit credentials | POST | /login | — | status 302 |

## Профиль нагрузки

Модель: **closed**, профиль: **ramp**. Разгон до **10 пользователей** за **30 с**, полка **120 с**.

## Тестовые данные

| Фидер | Файл | Стратегия |
|---|---|---|
| users | `users.csv` | circular |

## Корреляции и переменные

| Переменная | Источник | Используется в шагах |
|---|---|---|
| `csrf` | извлекается в шаге `open-login` | `submit-login` |
| `password` | переменная окружения / feeder-колонка | `submit-login` |
| `username` | переменная окружения / feeder-колонка | `submit-login` |

## SLA (assertions)

| Имя | Метрика | Условие |
|---|---|---|
| p95-under-800ms | `global.responseTime.p95` | < 800 |

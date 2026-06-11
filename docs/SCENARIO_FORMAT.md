# Scenario Format

## Purpose

The scenario YAML is the contract between requirement extraction, JMeter normalization, Gatling code generation, documentation, and quality gate checks.

The format must be readable by engineers and strict enough for automated generation.

## Minimal Valid Scenario

```yaml
scenario:
  id: login-and-search
  system: SHOP
  number: 1
  title: Login and search product
  source:
    type: manual
    ref: initial-example
  sut:
    base_url: "${BASE_URL}"
  data:
    feeders:
      - name: users
        file: users.csv
        strategy: circular
  steps:
    - name: open-login
      title: Open login page
      transaction: "01 auth.open-login - Open login page"
      protocol: http
      request:
        method: GET
        path: /login
      checks:
        - status: 200
        - extract:
            type: css
            expr: "input[name=csrf]"
            saveAs: csrf
    - name: submit-login
      title: Submit credentials
      transaction: "02 auth.login - Submit credentials"
      protocol: http
      request:
        method: POST
        path: /login
        headers:
          Content-Type: application/x-www-form-urlencoded
        body: "user=${username}&pass=${password}&csrf=${csrf}"
      checks:
        - status: 302
  load:
    model: closed
    profile: ramp
    users: 10
    ramp_seconds: 30
    duration_seconds: 120
  assertions:
    - name: p95-under-800ms
      metric: global.responseTime.p95
      op: "<"
      value: 800
```

## Naming Rules

| Field | Rule | Example |
|---|---|---|
| `scenario.id` | `kebab-case`, ASCII, stable | `login-and-search` |
| `scenario.system` | system code, `^[A-Z][A-Z0-9]{1,9}$` | `SHOP` |
| `scenario.number` | integer ≥ 1, unique within the system | `1` |
| `steps[].name` | `kebab-case`, unique | `submit-login` |
| `steps[].transaction` | `<NN> <domain>.<action> - <human title>` | `02 auth.login - Submit credentials` |
| Script-ref / Java class | `<SYSTEM>_<PascalCase(id)>_<NNN>` (produced by the generator) | `SHOP_CheckoutMix_001` |
| Feeder file | must be `<feeder-name>.csv`, co-located with `scenario.yaml` | `terms.csv` |
| Assertions | `kebab-case`, describes intent | `p95-under-800ms` |

Transaction names are report-facing labels. They must not include secrets, environment names, UUIDs, timestamps, full URLs, query values, or session-variable values.

## Folder Layout

Канонический сценарий живёт в папке `scenarios/<SYSTEM>/<id>-<NNN>/`:

```
scenarios/
  SHOP/
    checkout-mix-001/
      scenario.yaml        # источник правды (фиксированное имя)
      passport.md          # рендер-паспорт (генерируется, фиксированное имя)
      terms.csv            # фидеры рядом со сценарием
      mock.routes.json     # опционально: конфиг mock-SUT для smoke
```

Для файлов с каноническим именем `scenario.yaml` lint дополнительно проверяет: имя папки `<id>-<NNN>`, имя папки системы `<SYSTEM>`, уникальность пары `(system, number)` по всему дереву. Файлы с другими именами (черновики) линтуются без layout-правил. Значения `system`/`id`/`number` задаёт пользователь — агент предлагает только заготовки с подтверждением.

## Blocking Validation Rules

- `scenario.id`, `title`, `source`, `sut.base_url`, `steps`, and `load` are required.
- `scenario.system` соответствует `^[A-Z][A-Z0-9]{1,9}$`; `scenario.number` — целое ≥ 1.
- Every step name is unique.
- Every HTTP step has a request method and path.
- Every HTTP step has at least one check.
- Mutating HTTP methods have explicit status checks.
- Feeders referenced by variables exist.
- Имя фидера — kebab-case; файл фидера — строго `<имя>.csv`.
- Extracted variables are used or explicitly marked as intentionally captured.
- Used session variables are defined by feeders, extraction, or environment.
- `base_url` and credentials are not hardcoded production values.
- Нумерация `NN` транзакций сквозная по всей симуляции (без повторов между популяциями).

## Lint Waivers

Temporary exceptions use a dedicated block:

```yaml
lint_waivers:
  - rule: check-lint.missing-body-check
    reason: Endpoint returns only status and redirects in this system.
    owner: perf-team
    expires: 2026-07-01
```

Waivers are reviewed by `validator-subagent` and reported in `quality-gate-report.md`.


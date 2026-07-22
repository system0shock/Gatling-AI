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
- Mutating HTTP methods have explicit status checks (`check-lint.mutating-status-check`).
- Feeders referenced by variables exist.
- Имя фидера — kebab-case; файл фидера — строго `<имя>.csv`.
- Extracted variables are used or explicitly marked as intentionally captured.
- Used session variables are defined by feeders, extraction, or environment.
- `base_url` and credentials are not hardcoded production values.
- Нумерация `NN` транзакций сквозная по всей симуляции (без повторов между популяциями).
- `scenario-lint.body-file-missing` — `body_file` указывает на несуществующий файл.
- `scenario-lint.body-file-conflict` — одновременно указаны `body` и `body_file`.
- `scenario-lint.snippet-missing` — `translated`-хук ссылается на отсутствующий snippet-файл.
- `scenario-lint.stage-values` — значение `users`/`users_per_second`/`ramp_seconds`/`hold_seconds` в ступени невалидно.
- `scenario-lint.stage-no-duration` — ступень имеет нулевые `ramp_seconds` и `hold_seconds`.
- `correlation-lint.hook-read-undefined` — хук читает переменную, не определённую фидером, извлечением или окружением.
- `scenario-lint.kafka-block-required` — шаг с `protocol: kafka` не содержит блока `kafka`.
- `scenario-lint.jdbc-block-required` — шаг с `protocol: jdbc` не содержит блока `jdbc`.
- `scenario-lint.kafka-protocol-config-required` — шаг с `protocol: kafka` существует, но `scenario.protocols.kafka` отсутствует.
- `scenario-lint.jdbc-protocol-config-required` — шаг с `protocol: jdbc` существует, но `scenario.protocols.jdbc` отсутствует.

### Предупреждения (Warnings)

- `feeder-lint.queue-data-volume` — очередь-фидер (`strategy: queue`) содержит меньше строк, чем пиковое число пользователей; при исчерпании данных прогон остановится.
- `scenario-lint.hook-ref-missing` — оригинальный файл хука (`ref`) не найден (влияет только на трассировку).

## Lint Waivers

Temporary exceptions use a dedicated block:

```yaml
lint_waivers:
  - rule: check-lint.mutating-status-check
    reason: "Легаси-эндпоинт отвечает нестабильным статусом; явная проверка добавится после фикса SUT."
    owner: perf-team
    expires: 2026-07-01
```

Waivers are reviewed by `validator-subagent` and reported in `quality-gate-report.md`.

## Расширения Фазы 2 (миграция)

Следующие поля добавлены в рамках Фазы 2b для поддержки миграции JMeter-сценариев.

### `tags` (шаг)

Произвольные метки шага — используются навыками и отчётами; не влияют на кодогенерацию.

```yaml
steps:
  - name: submit-checkout
    title: Submit checkout
    transaction: "03 checkout.submit - Submit checkout"
    protocol: http
    tags:
      - auth
      - critical-path
    request:
      method: POST
      path: /checkout
    checks:
      - status: 200
```

### `body_file` (шаг, HTTP)

Путь к файлу тела запроса относительно папки `scenario.yaml`. Взаимоисключает с полем `body`; использование обоих одновременно является блокирующей ошибкой (`scenario-lint.body-file-conflict`).

```yaml
request:
  method: POST
  path: /checkout
  headers:
    Content-Type: application/json
  body_file: checkout-payload.json
```

Поведение при копировании:
- Расширения `.json`, `.txt`, `.xml` — файл копируется с преобразованием `${var}` → `#{var}` (Gatling EL) и подключается как `ElFileBody`.
- Любые другие расширения — файл копируется без изменений как `RawFileBody`.

**Важно:** любой литерал `${...}` в файлах `.json`/`.txt`/`.xml` будет преобразован в `#{...}`. Если тело содержит литеральный `${...}`, который не является сессионной переменной, используйте расширение, отличное от EL-расширений (например, `.bin`), — такой файл будет скопирован через `RawFileBody` без изменений.

### `profile: stages` (нагрузка)

Многоступенчатый профиль нагрузки с явным управлением каждой ступенью.

```yaml
load:
  model: closed
  profile: stages
  stages:
    - users: 5
      ramp_seconds: 30
      hold_seconds: 60
    - users: 20
      ramp_seconds: 60
      hold_seconds: 120
```

Для модели `open` используется `users_per_second` вместо `users`.

### `populations[].start_after_seconds`

Задержка старта популяции относительно начала теста. Генерируется как `nothingFor(Duration.ofSeconds(...))` первым инъекционным шагом.

```yaml
populations:
  - name: background-search
    start_after_seconds: 30
    steps:
      - name: search-products
        title: Search products
        transaction: "04 search.query - Search products"
        protocol: http
        request:
          method: GET
          path: "/search?q=${term}"
        checks:
          - status: 200
    load:
      model: open
      profile: constant
      users_per_second: 2
      duration_seconds: 60
```

### `hooks.before` / `hooks.after` (JSR223-хуки)

Хуки выполняются до или после HTTP/GraphQL-запроса шага. Поддерживаются два вида:

- `kind: translated` — хук переведён в Java-сниппет; генератор подключает его как `exec(ClassName::apply)`.
- `kind: todo` — хук ещё не переведён; генерируется как TODO-комментарий; quality gate сообщает `manual_review_required`.

```yaml
steps:
  - name: submit-checkout
    title: Submit checkout
    transaction: "03 checkout.submit - Submit checkout"
    protocol: http
    hooks:
      before:
        - ref: jmx/preprocessors/SignRequest.groovy
          kind: translated
          snippet: snippets/SignRequest.java
          summary: "Sign request with HMAC-SHA256"
          reads:
            - user
            - key
          writes:
            - signature
      after:
        - ref: jmx/postprocessors/LogResult.groovy
          kind: todo
          summary: "Log result to external audit service"
          reads:
            - responseCode
    request:
      method: POST
      path: /checkout
    checks:
      - status: 200
```

Обязательные поля хука: `ref`, `kind`, `summary`. Для `kind: translated` дополнительно обязателен `snippet`.

### Контракт Java-сниппета (translated-хук)

Файл `snippets/<ClassName>.java` в папке сценария; имя файла = PascalCase-имя класса. Содержимое:

```java
import io.gatling.javaapi.core.Session;

public final class SignRequest {
  public static Session apply(Session session) {
    String signature = sign(session.getString("user"), session.getString("key"));
    return session.set("signature", signature); // ОБЯЗАТЕЛЬНО вернуть НОВУЮ Session
  }
}
```

Gatling Session immutable: `session.set(...)` возвращает копию. Сниппет, который не возвращает результат `set`, молча теряет данные — генератор подключает сниппет как `exec(SignRequest::apply)`, поэтому сигнатура `Session -> Session` обязательна.

### `protocols` (scenario-level, optional)

Connection configuration for non-HTTP protocols. Credentials are env-var references only (NFR5).

```yaml
scenario:
  protocols:
    kafka:
      bootstrap_servers: "${KAFKA_BOOTSTRAP_SERVERS}"
      properties:          # optional extra Kafka producer props
        acks: "1"
    jdbc:
      url: "${JDBC_URL}"
      username: "${JDBC_USERNAME}"
      password: "${JDBC_PASSWORD}"
      maximum_pool_size: 10   # optional, default 10
```

`protocols.kafka` is REQUIRED when any step has `protocol: kafka`. `protocols.jdbc` is REQUIRED when any step has `protocol: jdbc`.

### `protocol: kafka` / `protocol: jdbc`

Steps with these protocols generate real Java code using galax-io plugins (`org.galaxio:gatling-kafka-plugin_2.13:1.0.6` and `org.galaxio:gatling-jdbc-plugin_2.13:1.3.1`).

```yaml
steps:
  - name: publish-order-event
    title: Publish order event to Kafka
    transaction: "05 order.publish - Publish order event"
    protocol: kafka
    kafka:
      topic: orders
      key: "${orderId}"
      payload: '{"orderId":"${orderId}","status":"submitted"}'

  - name: load-user-profile
    title: Load user profile from DB
    transaction: "06 profile.load - Load user profile"
    protocol: jdbc
    jdbc:
      query: "SELECT * FROM users WHERE id = '${userId}'"
      saveAs: userProfile
```

Generated Kafka action (galax-io Java DSL):

```java
.exec(
    kafka("05 order.publish - Publish order event")
        .topic("orders")
        .send("#{orderId}", "{\"orderId\":\"#{orderId}\",\"status\":\"submitted\"}")
)
```

Generated JDBC action:

```java
.exec(
    jdbc("06 profile.load - Load user profile")
        .query("SELECT * FROM users WHERE id = '#{userId}'")
        .check(simpleCheck(simpleCheckType.NonEmpty))
        .allResults().saveAs("userProfile")
)
```

When `jdbc.saveAs` is absent, the `.check(...)` and `.allResults().saveAs(...)` clauses are omitted.

**Важно:** значения `topic`, `key`, `payload` (Kafka) и `query` (JDBC) подставляются в генерируемый Java-код с преобразованием `${var}` → `#{var}` (Gatling EL). Не указывайте в этих полях секреты в открытом виде — используйте ссылки на переменные окружения (`${ENV_VAR}`). Это требование NFR5.

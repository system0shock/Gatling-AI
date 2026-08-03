# Spec: Kafka & JDBC Protocol Support via galax-io Plugins

**Date:** 2026-07-22
**Status:** Approved
**Author:** v.salnikov.k@gmail.com + Claude

## 1. Problem

The Gatling-AI workflow currently generates TODO-stub code for `protocol: kafka` and
`protocol: jdbc` steps (FR5.6.3). The PRD identifies the risk that community plugins
are Scala-oriented and may not work with Gatling 3.12+ from Java DSL.

Research confirmed:
- **Tinkoff plugins** (original): archived, target Gatling 3.9.5, unmaintained since May 2023.
- **galax-io plugins** (active forks): actively maintained, target Gatling 3.13.x,
  full Java DSL support, published to Maven Central.

## 2. Decision

Upgrade Gatling from 3.12.0 to **3.13.5** and integrate:
- `org.galaxio:gatling-kafka-plugin_2.13:1.0.6` — Kafka produce, request-reply, checks
- `org.galaxio:gatling-jdbc-plugin_2.13:1.3.1` — JDBC queries, batch, stored procedures, HikariCP

Both plugins have Java DSL wrappers and target Gatling 3.13.x.

## 3. New Scenario Contract: `protocols` Block

A new optional `scenario.protocols` block holds connection-level configuration for
non-HTTP protocols. Credentials are env-var references only (NFR5).

```yaml
scenario:
  protocols:
    kafka:
      bootstrap_servers: "${KAFKA_BOOTSTRAP_SERVERS}"
      properties:          # optional extra Kafka producer/consumer props
        acks: "1"
    jdbc:
      url: "${JDBC_URL}"
      username: "${JDBC_USERNAME}"
      password: "${JDBC_PASSWORD}"
      maximum_pool_size: 10   # optional, default 10
```

### Rules

- `protocols.kafka` is REQUIRED when any step has `protocol: kafka`.
- `protocols.jdbc` is REQUIRED when any step has `protocol: jdbc`.
- `protocols` is optional when no kafka/jdbc steps exist.
- `bootstrap_servers`, `url`, `username`, `password` must be `${ENV_VAR}`
  references (enforced by `env-lint`).

## 4. Generated Java Code

### 4.1 Kafka — galax-io 1.0.x Java DSL

Protocol builder (generated as a field when kafka steps exist):

```java
import static org.galaxio.gatling.kafka.javaapi.KafkaDsl.*;
import java.util.Map;

private final KafkaProtocolBuilder kafkaProtocol = kafka()
    .properties(Map.of(
        "bootstrap.servers", requiredEnv("KAFKA_BOOTSTRAP_SERVERS"),
        "acks", "1"
    ));
```

Action (produce-only, the currently supported scenario step):

```java
.exec(
    kafka("02 orders.publish - Publish order event")
        .topic("orders")
        .send("#{orderId}", "{\"id\":\"#{orderId}\"}")
)
```

EL conversion: `${orderId}` in YAML → `#{orderId}` in generated Java (existing
`gatling_el_string()` helper).

### 4.2 JDBC — galax-io 1.x Java DSL

Protocol builder (generated as a field when jdbc steps exist):

```java
import static org.galaxio.gatling.javaapi.JdbcDsl.*;

private final JdbcProtocolBuilder jdbcProtocol = DB()
    .url(requiredEnv("JDBC_URL"))
    .username(requiredEnv("JDBC_USERNAME"))
    .password(requiredEnv("JDBC_PASSWORD"))
    .maximumPoolSize(10)
    .protocolBuilder();
```

Action:

```java
.exec(
    jdbc("03 orders.check-balance - Check balance")
        .query("SELECT balance FROM a WHERE id=#{orderId}")
        .check(simpleCheck(simpleCheckType.NonEmpty))
        .allResults().saveAs("balance")
)
```

When `jdbc.saveAs` is absent, omit `.allResults().saveAs(...)`.

### 4.3 Protocol Registration

All active protocol builders are passed to `setUp(...).protocols(...)`:

```java
setUp(...)
    .protocols(httpProtocol, kafkaProtocol, jdbcProtocol)
    .assertions(...);
```

Only include protocol builders that are actually used by steps in the scenario.

## 5. POM Dependencies

When the scenario contains kafka steps, inject into generated `pom.xml`:

```xml
<dependency>
  <groupId>org.galaxio</groupId>
  <artifactId>gatling-kafka-plugin_2.13</artifactId>
  <version>1.0.6</version>
  <scope>test</scope>
</dependency>
```

When the scenario contains jdbc steps, inject:

```xml
<dependency>
  <groupId>org.galaxio</groupId>
  <artifactId>gatling-jdbc-plugin_2.13</artifactId>
  <version>1.3.1</version>
  <scope>test</scope>
</dependency>
<dependency>
  <groupId>org.postgresql</groupId>
  <artifactId>postgresql</artifactId>
  <version>42.7.11</version>
  <scope>test</scope>
</dependency>
```

## 6. Lint Changes

- **Remove:** `scenario-lint.protocol-stub` warning (kafka/jdbc are no longer stubs).
- **Add (blocking):** `scenario-lint.kafka-protocol-config-required` — kafka step
  exists but `scenario.protocols.kafka` is missing.
- **Add (blocking):** `scenario-lint.jdbc-protocol-config-required` — jdbc step
  exists but `scenario.protocols.jdbc` is missing.
- **Keep:** `scenario-lint.kafka-block-required`, `scenario-lint.jdbc-block-required`
  (per-step `kafka`/`jdbc` block still required).

## 7. Version Updates

| Artifact | Old | New |
|---|---|---|
| Gatling core | 3.12.0 | 3.13.5 |
| gatling-maven-plugin | 4.21.7 | 4.21.7 (unchanged) |
| gatling-kafka-plugin | (none) | 1.0.6 (galax-io) |
| gatling-jdbc-plugin | (none) | 1.3.1 (galax-io) |
| postgresql driver | (none) | 42.7.11 |

## 8. Scope

### In scope

- Schema: `protocols` block (kafka, jdbc).
- Generator: real Kafka/JDBC codegen replacing stubs.
- POM: conditional dependency injection.
- Lint: remove `protocol-stub`, add protocol-config validation.
- Docs: SCENARIO_FORMAT.md, PRD.md updates.
- Example scenario with HTTP + Kafka + JDBC steps.

### Out of scope

- Kafka request-reply (consume + correlate) — future iteration.
- JDBC batch operations, stored procedures — future iteration.
- Avro / Schema Registry — future iteration.
- Actual compile verification against live Kafka/PostgreSQL — requires Docker,
  deferred to integration test phase.

# Kafka & JDBC Protocol Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Kafka/JDBC TODO-stubs with real code generation using galax-io plugins, upgrading Gatling to 3.13.5.

**Architecture:** New `scenario.protocols` block holds connection config (env-var references). Generator emits galax-io Java DSL protocol builders + real action calls. Lint drops `protocol-stub` warning and validates protocol config presence.

**Tech Stack:** Gatling 3.13.5, `org.galaxio:gatling-kafka-plugin_2.13:1.0.6`, `org.galaxio:gatling-jdbc-plugin_2.13:1.3.1`, HikariCP, PostgreSQL driver 42.7.11, Python 3.11 generator.

**Spec:** `docs/superpowers/specs/2026-07-22-kafka-jdbc-protocol-support.md`

## Global Constraints

- Gatling **3.13.5**, gatling-maven-plugin **4.21.7**, Java **17**
- Credentials/secrets **never hardcoded** — only `${ENV_VAR}` references (NFR5)
- Generated code must compile with `mvn compile` (NFR1)
- Follow existing code style: no comments unless asked, kebab-case step names, `script_ref()` class naming
- Tests: `python -m pytest tools/gatling_generator/ tools/scenario_lint/ -v`
- Pin plugin versions: kafka `1.0.6`, jdbc `1.3.1`, postgresql `42.7.11`

---

### Task 1: Upgrade Gatling 3.12 → 3.13.5 in pom.xml template

**Files:**
- Modify: `tools/gatling_generator/templates/pom.xml`

**Interfaces:**
- Produces: pom.xml template with `gatling.version=3.13.5`

- [ ] **Step 1: Change version**

In `tools/gatling_generator/templates/pom.xml`, change:
```
<gatling.version>3.12.0</gatling.version>
```
to:
```
<gatling.version>3.13.5</gatling.version>
```

- [ ] **Step 2: Run existing generator tests**

Run: `python -m pytest tools/gatling_generator/ -v`
Expected: All existing tests PASS (generator is Python, version-agnostic).

- [ ] **Step 3: Commit**

```bash
git add tools/gatling_generator/templates/pom.xml
git commit -m "chore: upgrade Gatling template to 3.13.5"
```

---

### Task 2: Extend scenario schema with `protocols` block

**Files:**
- Modify: `schemas/scenario.schema.json`
- Modify: `docs/SCENARIO_FORMAT.md`

**Interfaces:**
- Produces: schema accepts optional `scenario.protocols` with `kafka` and `jdbc` sub-objects

- [ ] **Step 1: Add `protocols` definition to `$defs` in schema**

Add to `schemas/scenario.schema.json` under `"$defs"` (after `"assertions"` or at end of `$defs`):

```json
"protocols": {
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "kafka": {
      "type": "object",
      "additionalProperties": false,
      "required": ["bootstrap_servers"],
      "properties": {
        "bootstrap_servers": { "type": "string", "minLength": 1 },
        "properties": { "type": "object", "additionalProperties": { "type": "string" } }
      }
    },
    "jdbc": {
      "type": "object",
      "additionalProperties": false,
      "required": ["url", "username", "password"],
      "properties": {
        "url": { "type": "string", "minLength": 1 },
        "username": { "type": "string", "minLength": 1 },
        "password": { "type": "string", "minLength": 1 },
        "maximum_pool_size": { "type": "integer", "exclusiveMinimum": 0 }
      }
    }
  }
}
```

- [ ] **Step 2: Register `protocols` in both scenario `oneOf` branches**

In the `properties` of both `oneOf` branches under `"scenario"` (the steps-based and the populations-based), add:

```json
"protocols": { "$ref": "#/$defs/protocols" }
```

- [ ] **Step 3: Update SCENARIO_FORMAT.md**

Add a new section documenting the `protocols` block with the example from the spec. Also update the kafka/jdbc step examples to remove "TODO-заглушки" language and show real usage with `protocols`.

- [ ] **Step 4: Run schema validation tests**

Run: `python -m pytest tools/scenario_lint/ -v -k "schema or valid"`
Expected: All schema-validation tests PASS.

- [ ] **Step 5: Commit**

```bash
git add schemas/scenario.schema.json docs/SCENARIO_FORMAT.md
git commit -m "feat(schema): add protocols block for kafka/jdbc config"
```

---

### Task 3: Kafka code generation

**Files:**
- Modify: `tools/gatling_generator/gatling_generator.py`
- Modify: `tools/gatling_generator/test_gatling_generator.py`

**Interfaces:**
- Consumes: `scenario.protocols.kafka` (bootstrap_servers, properties) from parsed YAML
- Produces: `kafka_action_chain(step)` function replacing `kafka_stub_chain()`, `render_kafka_protocol()` for protocol builder field

**Generated Java target (galax-io 1.0.x Java DSL):**

Protocol field (when kafka steps exist):
```java
import static org.galaxio.gatling.kafka.javaapi.KafkaDsl.*;
import org.galaxio.gatling.kafka.javaapi.protocol.KafkaProtocolBuilder;
import java.util.Map;
import java.util.HashMap;

private final KafkaProtocolBuilder kafkaProtocol = kafka()
    .properties(new HashMap<String, Object>() {{
        put("bootstrap.servers", requiredEnv("KAFKA_BOOTSTRAP_SERVERS"));
        put("acks", "1");
    }});
```

Action (replaces kafka_stub_chain):
```java
.exec(
    kafka("02 orders.publish - Publish order event")
        .topic("orders")
        .send("#{orderId}", "{\"id\":\"#{orderId}\"}")
)
```

EL conversion: `${orderId}` in YAML → `#{orderId}` in generated Java (use existing `gatling_el_string()` helper).

- [ ] **Step 1: Write failing tests**

In `tools/gatling_generator/test_gatling_generator.py`, replace the `ProtocolStubGeneratorTest` class with a new `KafkaGeneratorTest` class (or add to it). Write these tests:

```python
class KafkaGeneratorTest(unittest.TestCase):
    def _document(self):
        document = minimal_scenario()
        document["scenario"]["protocols"] = {
            "kafka": {"bootstrap_servers": "${KAFKA_BOOTSTRAP_SERVERS}"},
        }
        document["scenario"]["steps"][0]["checks"] = [
            {"status": 200},
            {"extract": {"type": "jsonPath", "expr": "$.id", "saveAs": "orderId"}},
        ]
        document["scenario"]["steps"].append({
            "name": "publish-event",
            "title": "Publish event",
            "transaction": "02 orders.publish - Publish order event",
            "protocol": "kafka",
            "kafka": {"topic": "orders", "key": "${orderId}", "payload": '{"id":"${orderId}"}'},
        })
        return document

    def test_kafka_produces_real_action(self):
        _, content = gatling_generator.render_simulation(self._document())
        self.assertIn("kafka(", content)
        self.assertIn('.topic("orders")', content)
        self.assertIn(".send(", content)
        self.assertNotIn("TODO(kafka-stub)", content)

    def test_kafka_protocol_builder_generated(self):
        _, content = gatling_generator.render_simulation(self._document())
        self.assertIn("kafkaProtocol", content)
        self.assertIn("import static org.galaxio.gatling.kafka.javaapi.KafkaDsl.*;", content)
        self.assertIn("requiredEnv(\"KAFKA_BOOTSTRAP_SERVERS\")", content)

    def test_kafka_requires_protocols_block(self):
        document = self._document()
        del document["scenario"]["protocols"]
        with self.assertRaisesRegex(ValueError, "protocols.*kafka"):
            gatling_generator.render_simulation(document)

    def test_kafka_el_in_key_and_payload(self):
        _, content = gatling_generator.render_simulation(self._document())
        self.assertIn("#{orderId}", content)
        self.assertNotIn("${orderId}", content)

    def test_kafka_with_hook_chains_correctly(self):
        document = self._document()
        document["scenario"]["steps"][1]["hooks"] = {
            "before": [{
                "ref": "migration/jsr223/setup.groovy",
                "kind": "translated",
                "snippet": "snippets/Setup.java",
                "summary": "prep",
            }]
        }
        _, content = gatling_generator.render_simulation(document)
        self.assertIn("exec(Setup::apply)", content)
        idx_hook = content.index("exec(Setup::apply)")
        idx_kafka = content.index("kafka(")
        self.assertLess(idx_hook, idx_kafka)
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `python -m pytest tools/gatling_generator/test_gatling_generator.py::KafkaGeneratorTest -v`
Expected: FAIL (old `kafka_stub_chain` produces TODO comments, tests assert real code).

- [ ] **Step 3: Implement Kafka codegen**

In `tools/gatling_generator/gatling_generator.py`:

1. Add a function `has_kafka_steps(document)` → bool (checks if any step has `protocol: kafka`).

2. Add `render_kafka_protocol(protocols_config)` → list[str]: emits the `kafkaProtocol` field. Extract `bootstrap_servers` env var name from `${VAR}` pattern. Build a `HashMap<String, Object>` with `bootstrap.servers` and any extra `properties`. Use `requiredEnv("VAR_NAME")` for the bootstrap servers value.

3. Replace `kafka_stub_chain(step)` with `kafka_action_chain(step)`:
   - Get `kafka` block (topic, key, payload)
   - Apply `gatling_el_string()` to key and payload
   - Emit: `kafka("{transaction}").topic("{topic}").send({key}, {payload})`
   - If no key: `.send({payload})` (galax-io supports keyless send)
   - The action is wrapped in `exec(...)` — note: galax-io's `kafka(...)` returns an action builder, so the chain is `exec(kafka("...").topic("...").send(...))`

4. In `render_simulation()`:
   - Detect kafka steps; if present, validate `protocols.kafka` exists
   - Add kafka imports
   - Add `kafkaProtocol` field
   - Pass `kafkaProtocol` to `.protocols(...)` in setUp
   - Route `protocol == "kafka"` to `kafka_action_chain` in `render_chain_field`

5. Update `CONSUMED_FIELDS` to include `scenario.protocols`, `scenario.protocols.kafka`, `scenario.protocols.kafka.bootstrap_servers`, `scenario.protocols.kafka.properties`.

- [ ] **Step 4: Run tests, verify pass**

Run: `python -m pytest tools/gatling_generator/test_gatling_generator.py::KafkaGeneratorTest -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/gatling_generator/gatling_generator.py tools/gatling_generator/test_gatling_generator.py
git commit -m "feat(generator): real Kafka code generation via galax-io plugin"
```

---

### Task 4: JDBC code generation

**Files:**
- Modify: `tools/gatling_generator/gatling_generator.py`
- Modify: `tools/gatling_generator/test_gatling_generator.py`

**Interfaces:**
- Consumes: `scenario.protocols.jdbc` (url, username, password, maximum_pool_size)
- Produces: `jdbc_action_chain(step)` replacing `jdbc_stub_chain()`, `render_jdbc_protocol()` for protocol builder field

**Generated Java target (galax-io 1.x Java DSL):**

Protocol field (when jdbc steps exist):
```java
import static org.galaxio.gatling.javaapi.JdbcDsl.*;
import org.galaxio.gatling.javaapi.protocol.JdbcProtocolBuilder;

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

When `jdbc.saveAs` is absent, omit `.allResults().saveAs(...)` and omit `.check(...)`.

- [ ] **Step 1: Write failing tests**

```python
class JdbcGeneratorTest(unittest.TestCase):
    def _document(self):
        document = minimal_scenario()
        document["scenario"]["protocols"] = {
            "jdbc": {
                "url": "${JDBC_URL}",
                "username": "${JDBC_USERNAME}",
                "password": "${JDBC_PASSWORD}",
                "maximum_pool_size": 20,
            },
        }
        document["scenario"]["steps"][0]["checks"] = [
            {"status": 200},
            {"extract": {"type": "jsonPath", "expr": "$.id", "saveAs": "orderId"}},
        ]
        document["scenario"]["steps"].append({
            "name": "check-balance",
            "title": "Check balance",
            "transaction": "03 orders.check-balance - Check balance",
            "protocol": "jdbc",
            "jdbc": {"query": "SELECT balance FROM a WHERE id=${orderId}", "saveAs": "balance"},
        })
        return document

    def test_jdbc_produces_real_action(self):
        _, content = gatling_generator.render_simulation(self._document())
        self.assertIn("jdbc(", content)
        self.assertIn(".query(", content)
        self.assertNotIn("TODO(jdbc-stub)", content)

    def test_jdbc_protocol_builder_generated(self):
        _, content = gatling_generator.render_simulation(self._document())
        self.assertIn("jdbcProtocol", content)
        self.assertIn("import static org.galaxio.gatling.javaapi.JdbcDsl.*;", content)
        self.assertIn("requiredEnv(\"JDBC_URL\")", content)
        self.assertIn("requiredEnv(\"JDBC_USERNAME\")", content)
        self.assertIn("requiredEnv(\"JDBC_PASSWORD\")", content)
        self.assertIn("maximumPoolSize(20)", content)

    def test_jdbc_requires_protocols_block(self):
        document = self._document()
        del document["scenario"]["protocols"]
        with self.assertRaisesRegex(ValueError, "protocols.*jdbc"):
            gatling_generator.render_simulation(document)

    def test_jdbc_save_as_generates_all_results(self):
        _, content = gatling_generator.render_simulation(self._document())
        self.assertIn('.allResults().saveAs("balance")', content)

    def test_jdbc_without_save_as_no_all_results(self):
        document = self._document()
        del document["scenario"]["steps"][1]["jdbc"]["saveAs"]
        _, content = gatling_generator.render_simulation(document)
        self.assertNotIn("allResults", content)

    def test_jdbc_el_in_query(self):
        _, content = gatling_generator.render_simulation(self._document())
        self.assertIn("#{orderId}", content)
```

- [ ] **Step 2: Run tests, verify fail**

Run: `python -m pytest tools/gatling_generator/test_gatling_generator.py::JdbcGeneratorTest -v`
Expected: FAIL.

- [ ] **Step 3: Implement JDBC codegen**

In `tools/gatling_generator/gatling_generator.py`:

1. Add `has_jdbc_steps(document)` → bool.

2. Add `render_jdbc_protocol(protocols_config)` → list[str]: emits `jdbcProtocol` field. Extract env var names from `${VAR}` patterns for url, username, password. Default `maximum_pool_size` to 10 if absent.

3. Replace `jdbc_stub_chain(step)` with `jdbc_action_chain(step)`:
   - Get `jdbc` block (query, saveAs)
   - Apply `gatling_el_string()` to query
   - Emit: `jdbc("{transaction}").query("{query}")`
   - If `saveAs` present: `.check(simpleCheck(simpleCheckType.NonEmpty)).allResults().saveAs("{saveAs}")`
   - If no `saveAs`: no check clause (JDBC action without check is valid in galax-io)
   - Wrap in `exec(...)`

4. In `render_simulation()`:
   - Detect jdbc steps; if present, validate `protocols.jdbc` exists
   - Add jdbc imports
   - Add `jdbcProtocol` field
   - Pass `jdbcProtocol` to `.protocols(...)` in setUp
   - Route `protocol == "jdbc"` to `jdbc_action_chain` in `render_chain_field`

5. Update `CONSUMED_FIELDS` for jdbc protocol fields.

- [ ] **Step 4: Run tests, verify pass**

Run: `python -m pytest tools/gatling_generator/test_gatling_generator.py::JdbcGeneratorTest -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/gatling_generator/gatling_generator.py tools/gatling_generator/test_gatling_generator.py
git commit -m "feat(generator): real JDBC code generation via galax-io plugin"
```

---

### Task 5: Conditional pom.xml dependencies

**Files:**
- Modify: `tools/gatling_generator/gatling_generator.py`
- Modify: `tools/gatling_generator/test_gatling_generator.py`

**Interfaces:**
- Consumes: `has_kafka_steps()`, `has_jdbc_steps()` from Tasks 3-4
- Produces: generated `pom.xml` with injected dependencies when kafka/jdbc steps present

- [ ] **Step 1: Write failing test**

```python
class PomDependenciesTest(unittest.TestCase):
    def test_kafka_step_injects_kafka_plugin_dep(self):
        document = minimal_scenario()
        document["scenario"]["protocols"] = {
            "kafka": {"bootstrap_servers": "${KAFKA_BOOTSTRAP_SERVERS}"},
        }
        document["scenario"]["steps"].append({
            "name": "publish-event", "title": "Publish", "transaction": "02 t - T",
            "protocol": "kafka",
            "kafka": {"topic": "t", "key": "${k}", "payload": "{}"},
        })
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            gatling_generator.write_simulation(
                Path("scenarios/SHOP/checkout-mix-003/scenario.yaml"), out
            )
            # This won't work — need to call write_simulation with a real scenario file.
            # Instead test bootstrap_project + dependency injection directly.
```

Actually, test the dependency injection function directly:

```python
    def test_kafka_dep_injected_when_kafka_steps(self):
        deps = gatling_generator.inject_plugin_deps(
            has_kafka=True, has_jdbc=False, pom_content=TEMPLATE_POM_CONTENT
        )
        self.assertIn("gatling-kafka-plugin", deps)
        self.assertIn("1.0.6", deps)

    def test_jdbc_dep_injected_when_jdbc_steps(self):
        deps = gatling_generator.inject_plugin_deps(
            has_kafka=False, has_jdbc=True, pom_content=TEMPLATE_POM_CONTENT
        )
        self.assertIn("gatling-jdbc-plugin", deps)
        self.assertIn("1.3.1", deps)
        self.assertIn("postgresql", deps)
        self.assertIn("42.7.11", deps)

    def test_no_deps_injected_when_http_only(self):
        deps = gatling_generator.inject_plugin_deps(
            has_kafka=False, has_jdbc=False, pom_content=TEMPLATE_POM_CONTENT
        )
        self.assertNotIn("galaxio", deps)
```

- [ ] **Step 2: Run tests, verify fail**

- [ ] **Step 3: Implement**

Add function `inject_plugin_deps(has_kafka, has_jdbc, pom_content)` that inserts `<dependency>` blocks before `</dependencies>` in the pom XML string. Pin versions:
- kafka: `org.galaxio:gatling-kafka-plugin_2.13:1.0.6`
- jdbc: `org.galaxio:gatling-jdbc-plugin_2.13:1.3.1`
- postgresql: `org.postgresql:postgresql:42.7.11`

In `write_simulation()` / `bootstrap_project()`, after copying the template pom, call `inject_plugin_deps()` if the scenario has kafka/jdbc steps and write the modified pom.

- [ ] **Step 4: Run tests, verify pass**

- [ ] **Step 5: Commit**

```bash
git add tools/gatling_generator/gatling_generator.py tools/gatling_generator/test_gatling_generator.py
git commit -m "feat(generator): inject galax-io plugin deps into generated pom.xml"
```

---

### Task 6: Update scenario_lint

**Files:**
- Modify: `tools/scenario_lint/scenario_lint.py`
- Modify: `tools/scenario_lint/test_scenario_lint.py`

- [ ] **Step 1: Write failing tests**

In `test_scenario_lint.py`:

```python
def test_kafka_and_jdbc_no_longer_warn_stub(self):
    document = kafka_jdbc_document()
    document["scenario"]["protocols"] = {
        "kafka": {"bootstrap_servers": "${KAFKA_BOOTSTRAP_SERVERS}"},
        "jdbc": {"url": "${JDBC_URL}", "username": "${U}", "password": "${P}"},
    }
    findings = lint(document)
    stub = [f for f in findings if f.rule == "scenario-lint.protocol-stub"]
    self.assertEqual(stub, [])

def test_kafka_protocol_config_required(self):
    document = kafka_jdbc_document()
    # no protocols block
    findings = lint(document)
    blocking = [f for f in findings if f.rule == "scenario-lint.kafka-protocol-config-required"]
    self.assertTrue(blocking)

def test_jdbc_protocol_config_required(self):
    document = kafka_jdbc_document()
    document["scenario"]["protocols"] = {
        "kafka": {"bootstrap_servers": "${KAFKA_BOOTSTRAP_SERVERS}"},
    }
    findings = lint(document)
    blocking = [f for f in findings if f.rule == "scenario-lint.jdbc-protocol-config-required"]
    self.assertTrue(blocking)
```

- [ ] **Step 2: Run tests, verify fail**

- [ ] **Step 3: Implement**

In `scenario_lint.py`:
1. Remove the `is_stub` logic and `scenario-lint.protocol-stub` warning for kafka/jdbc.
2. Keep `kafka-block-required` and `jdbc-block-required` (per-step block).
3. After step validation, if any kafka step exists but `scenario.protocols.kafka` is missing, add blocking `scenario-lint.kafka-protocol-config-required`.
4. Same for jdbc: `scenario-lint.jdbc-protocol-config-required`.
5. Keep `is_stub = False` — kafka/jdbc steps now require checks like http/graphql (but allow no checks for jdbc without saveAs — the JDBC action may not need checks if it's just a query).

Actually, looking at the current code: `is_stub` also skips the check requirement. Since kafka/jdbc are no longer stubs, we need to decide: do they require checks?
- Kafka: checks are optional (produce doesn't have a response to check)
- JDBC: checks are optional if no saveAs; if saveAs, a check like `simpleCheck(NonEmpty)` is auto-generated

So: **kafka/jdbc steps should NOT require checks** (unlike http/graphql). Keep the `is_stub` skip for check requirement, but remove the `protocol-stub` warning. Rename `is_stub` to `is_non_http` or similar.

- [ ] **Step 4: Run tests, verify pass**

- [ ] **Step 5: Commit**

```bash
git add tools/scenario_lint/scenario_lint.py tools/scenario_lint/test_scenario_lint.py
git commit -m "feat(lint): replace protocol-stub with protocol-config validation"
```

---

### Task 7: Contract coverage + documentation

**Files:**
- Modify: `tools/gatling_generator/gatling_generator.py` (CONSUMED_FIELDS)
- Modify: `docs/SCENARIO_FORMAT.md`
- Modify: `docs/PRD.md`

- [ ] **Step 1: Update CONSUMED_FIELDS**

Add to `CONSUMED_FIELDS` in `gatling_generator.py`:
```python
"scenario.protocols",
"scenario.protocols.kafka",
"scenario.protocols.kafka.bootstrap_servers",
"scenario.protocols.kafka.properties",
"scenario.protocols.jdbc",
"scenario.protocols.jdbc.url",
"scenario.protocols.jdbc.username",
"scenario.protocols.jdbc.password",
"scenario.protocols.jdbc.maximum_pool_size",
```

- [ ] **Step 2: Run contract coverage test**

Run: `python -m pytest tools/test_contract_coverage.py -v`
Expected: PASS.

- [ ] **Step 3: Update SCENARIO_FORMAT.md**

- Document `protocols` block with examples
- Update kafka/jdbc step examples: remove "TODO-заглушки" language, show real generated code
- Update the warnings section: remove `scenario-lint.protocol-stub`, add `kafka-protocol-config-required` and `jdbc-protocol-config-required`

- [ ] **Step 4: Update PRD.md**

- §5.6: Update protocol table — Kafka: galax-io 1.0.x (3.13), JDBC: galax-io 1.3.x (3.13)
- §11 Risks: Update the Kafka/JDBC risk row → "Mitigated: galax-io plugins 1.0.x/1.3.x, Java DSL, Gatling 3.13.5"
- Appendix A: Gatling 3.13.5, add galax-io plugin versions
- FR5.6.3: Mark as implemented (no longer "protocol spike")

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest tools/ -v`
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add tools/gatling_generator/gatling_generator.py docs/SCENARIO_FORMAT.md docs/PRD.md
git commit -m "docs: update for kafka/jdbc protocol support, Gatling 3.13.5"
```

---

### Task 8: E2E example scenario

**Files:**
- Create: `scenarios/SHOP/order-events-004/scenario.yaml`

- [ ] **Step 1: Create scenario YAML**

```yaml
scenario:
  id: order-events
  system: SHOP
  number: 4
  title: Order flow with Kafka event and DB verification
  source:
    type: manual
    ref: e2e-example
  sut:
    base_url: "${BASE_URL}"
  protocols:
    kafka:
      bootstrap_servers: "${KAFKA_BOOTSTRAP_SERVERS}"
      properties:
        acks: "1"
    jdbc:
      url: "${JDBC_URL}"
      username: "${JDBC_USERNAME}"
      password: "${JDBC_PASSWORD}"
      maximum_pool_size: 10
  steps:
    - name: create-order
      title: Create order via HTTP
      transaction: "01 orders.create - Create order"
      protocol: http
      request:
        method: POST
        path: /orders
        headers:
          Content-Type: application/json
        body: '{"product":"widget","qty":1}'
      checks:
        - status: 201
        - extract:
            type: jsonPath
            expr: "$.orderId"
            saveAs: orderId
    - name: publish-order-event
      title: Publish order event to Kafka
      transaction: "02 orders.publish - Publish order event"
      protocol: kafka
      kafka:
        topic: orders
        key: "${orderId}"
        payload: '{"orderId":"${orderId}","status":"created"}'
    - name: verify-order-in-db
      title: Verify order in database
      transaction: "03 orders.verify - Verify order in DB"
      protocol: jdbc
      jdbc:
        query: "SELECT status FROM orders WHERE id = ${orderId}"
        saveAs: orderStatus
  load:
    model: closed
    profile: ramp
    users: 5
    ramp_seconds: 10
    duration_seconds: 60
  assertions:
    - name: p95-under-500ms
      metric: global.responseTime.p95
      op: "<"
      value: 500
    - name: success-rate-above-95
      metric: global.successfulRequests.percent
      op: ">"
      value: 95
```

- [ ] **Step 2: Run generator**

Run: `python tools/gatling_generator/gatling_generator.py scenarios/SHOP/order-events-004/scenario.yaml .tmp/e2e-output`
Expected: Generates Java file + pom.xml with galax-io deps.

- [ ] **Step 3: Run lint**

Run: `python tools/scenario_lint/scenario_lint.py scenarios/SHOP/order-events-004/scenario.yaml`
Expected: No blocking findings.

- [ ] **Step 4: Commit**

```bash
git add scenarios/SHOP/order-events-004/scenario.yaml
git commit -m "feat(example): add order-events-004 with kafka+jdbc steps"
```

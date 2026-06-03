# Phase 0 Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the smallest working foundation for Gatling-AI: scenario schema, one HTTP example, Java Gatling generation, and a local quality gate.

**Architecture:** Start with scenario YAML as the central contract. Build small tools around it: schema validation, semantic lint, generator, and quality gate report aggregation. Keep Gigacode hook integration behind a fallback command until hook support is verified.

**Tech Stack:** YAML, JSON Schema, Java 17, Gatling OSS 3.12, Maven, command-line quality gate tooling.

---

## File Structure

- Create `schemas/scenario.schema.json` for structural validation.
- Create `examples/scenarios/login-and-search.yaml` as the golden valid example.
- Create `examples/scenarios/invalid/missing-check.yaml` as a blocking lint fixture.
- Create `tools/scenario_lint/` for semantic scenario checks.
- Create `tools/gatling_generator/` for Java simulation generation.
- Create `tools/quality_gate/` for report aggregation.
- Create `skills/quality-gate/SKILL.md` for the agent-facing verification workflow.

## Task 1: Scenario Schema And Examples

**Files:**
- Create: `schemas/scenario.schema.json`
- Create: `examples/scenarios/login-and-search.yaml`
- Create: `examples/scenarios/invalid/missing-check.yaml`

- [ ] **Step 1: Create the schema with required top-level fields**

The schema must require `scenario.id`, `scenario.title`, `scenario.source`, `scenario.sut.base_url`, `scenario.steps`, `scenario.load`, and `scenario.assertions`.

- [ ] **Step 2: Add the valid example**

Use the scenario shown in `docs/SCENARIO_FORMAT.md` as the exact first golden example.

- [ ] **Step 3: Add the invalid fixture**

Create the same scenario with one HTTP step missing `checks`; this fixture must fail `check-lint`.

- [ ] **Step 4: Verify schema validation**

Run the future schema command against both examples. Expected result: valid example passes structural validation; invalid fixture may pass schema but must fail semantic lint in Task 2.

- [ ] **Step 5: Commit**

```bash
git add schemas examples
git commit -m "feat: add scenario schema and fixtures"
```

## Task 2: Scenario Semantic Lint

**Files:**
- Create: `tools/scenario_lint/README.md`
- Create: `tools/scenario_lint/rules.md`
- Create: implementation files selected by the developer after choosing the runtime.

- [ ] **Step 1: Implement `scenario-lint` rules**

Rules: unique step names, required checks for HTTP steps, positive load values, feeder references exist, protocol block matches protocol.

- [ ] **Step 2: Implement `transaction-lint` rules**

Rules: transaction names use `<NN> <domain>.<action> - <human title>`, max 80 characters, no secret-looking values, no environment names.

- [ ] **Step 3: Implement `secret-scan` minimum rules**

Rules: flag obvious tokens, passwords, bearer tokens, JDBC credentials, and hardcoded production URLs.

- [ ] **Step 4: Verify red and green fixtures**

Expected result: `login-and-search.yaml` passes; `invalid/missing-check.yaml` fails with a blocking `check-lint` finding.

- [ ] **Step 5: Commit**

```bash
git add tools/scenario_lint examples
git commit -m "feat: add scenario lint rules"
```

## Task 3: Java Gatling Generator

**Files:**
- Create: `tools/gatling_generator/README.md`
- Create: generator implementation files selected by the developer.
- Create: `examples/generated/java/LoginAndSearchSimulation.java`

- [ ] **Step 1: Generate class name from scenario id**

`login-and-search` must generate `LoginAndSearchSimulation`.

- [ ] **Step 2: Generate HTTP requests and checks**

Each scenario step must generate one Gatling request with stable request/group names and explicit status checks.

- [ ] **Step 3: Generate load profile**

For the first slice, support closed ramp with users, ramp seconds, and duration seconds.

- [ ] **Step 4: Verify generated Java is stable**

Run generation twice. Expected result: no diff after the second run.

- [ ] **Step 5: Commit**

```bash
git add tools/gatling_generator examples/generated
git commit -m "feat: generate Java Gatling simulation"
```

## Task 4: Maven Compile Path

**Files:**
- Create: `examples/generated/java/pom.xml`
- Modify: `examples/generated/java/LoginAndSearchSimulation.java`

- [ ] **Step 1: Add Maven project metadata**

Use Gatling OSS 3.12 and `gatling-maven-plugin` 4.21.7 as pinned versions from the PRD.

- [ ] **Step 2: Compile generated simulation**

Run:

```bash
mvn compile
```

Expected result: exit code 0.

- [ ] **Step 3: Commit**

```bash
git add examples/generated/java
git commit -m "feat: add Maven compile path"
```

## Task 5: Quality Gate Command

**Files:**
- Create: `tools/quality_gate/README.md`
- Create: quality gate implementation files selected by the developer.
- Create: `skills/quality-gate/SKILL.md`

- [ ] **Step 1: Aggregate checks**

Quality gate runs schema validation, scenario lint, transaction lint, secret scan, generator stability check, and Maven compile check.

- [ ] **Step 2: Produce JSON report**

Write `quality-gate-report.json` with `status`, `profile`, `checked_at`, `artifacts`, `blocking`, `warnings`, and `waivers`.

- [ ] **Step 3: Produce Markdown report**

Write `quality-gate-report.md` with status, checked artifacts, blocking findings, warnings, and accepted waivers.

- [ ] **Step 4: Verify blocked status**

Run quality gate against `examples/scenarios/invalid/missing-check.yaml`. Expected result: status `blocked`.

- [ ] **Step 5: Verify passed status**

Run quality gate against `examples/scenarios/login-and-search.yaml`. Expected result: status `passed` or `passed_with_warnings` if local Maven dependencies are unavailable.

- [ ] **Step 6: Commit**

```bash
git add tools/quality_gate skills/quality-gate quality-gate-report.json quality-gate-report.md
git commit -m "feat: add quality gate command"
```

## Task 6: Hook Spike

**Files:**
- Create: `docs/HOOK_SPIKE.md`

- [ ] **Step 1: Document available Gigacode hook events**

Record whether Gigacode supports equivalents of `PostToolUse`, `SubagentStop`, and `Stop`.

- [ ] **Step 2: Document fallback behavior**

If hooks are unavailable, require the explicit `quality-gate` command before final handoff.

- [ ] **Step 3: Commit**

```bash
git add docs/HOOK_SPIKE.md
git commit -m "docs: record hook spike results"
```

## Self-Review Checklist

- Every Phase 0 PRD requirement maps to a task above.
- The plan avoids Confluence, Kafka, JDBC, Jenkins, and full JMeter conversion.
- The plan leaves a runnable quality gate artifact.
- The plan allows hook support to be verified without blocking MVP tooling.


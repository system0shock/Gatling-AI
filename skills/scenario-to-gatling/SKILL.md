---
name: scenario-to-gatling
description: Use when turning an approved scenario.yaml into a runnable Java Gatling simulation (Gatling 3.12, gatling-maven-plugin 4.21.7, Maven). Covers project bootstrap/embedding, generation, compile, smoke run, and the mandatory quality gate.
---

# Scenario To Gatling

Generate and verify a Java Gatling simulation from `scenario.yaml`. The YAML is
the source of truth: fix problems by editing the scenario and regenerating —
never by hand-editing generated Java.

## Preconditions

- The scenario is approved by the user (scenario-from-docs output).
- `python tools/scenario_lint/scenario_lint.py scenarios/<SYSTEM>/<id>-<NNN>/scenario.yaml --format text`
  reports `passed`. Otherwise go back to scenario-from-docs.

## Process

1. **Pick the target project directory.**
   - No `pom.xml` there → the generator bootstraps a pinned Maven project
     (Gatling 3.12 / plugin 4.21.7) from its template automatically.
   - `pom.xml` exists → embedding mode; the quality gate blocks if the Gatling
     pins in the pom diverge.
2. **Generate:**
   `python tools/gatling_generator/gatling_generator.py scenarios/<SYSTEM>/<id>-<NNN>/scenario.yaml <project> --format json`
   On failure, read the structured finding, fix the YAML, regenerate.
3. **Render the reviewer doc** (kept in sync by the gate):
   `python tools/scenario_renderer/scenario_renderer.py scenarios/<SYSTEM>/<id>-<NNN>/scenario.yaml`
   (writes `passport.md` co-located next to the scenario).
4. **Compile:** `mvn -q compile` in the project (the gate also runs this).
5. **Smoke run — only with explicit user permission** (it loads a system):
   - Local mock: write/extend a route config (see `tools/mock_sut/README.md`),
     then `python tools/quality_gate/quality_gate.py --scenario scenarios/<SYSTEM>/<id>-<NNN>/scenario.yaml
     --project <project> --smoke --mock-routes scenarios/<SYSTEM>/<id>-<NNN>/mock.routes.json`
   - Real SUT: user sets `BASE_URL`, then the same command without
     `--mock-routes`.
   On failures, follow systematic debugging: read `target/gatling/` reports,
   form a hypothesis, fix the scenario (or the mock config), regenerate, rerun.
6. **Mandatory final step — quality gate** (see the quality-gate skill). Do not
   report the work as done unless the report status is `passed` or
   `passed_with_warnings`; `blocked` means not ready, say so explicitly with
   the report path.

## Output

- Generated Java class named by script-ref `<SYSTEM>_<PascalCaseId>_<NNN>.java`
  (e.g. `SHOP_CheckoutMix_001.java`) (+ feeders under `src/test/resources`),
  bootstrapped pom when the project is new
- Co-located `passport.md` rendered next to the scenario
- `quality-gate-report.json` / `.md` with a passing status

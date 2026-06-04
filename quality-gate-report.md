# Quality Gate Report

- Status: `passed`
- Profile: `mvp`
- Checked at: `2026-06-04T13:35:36Z`

## Checked Artifacts
- `examples/generated/java/pom.xml`
- `examples/generated/java/src/test/java/LoginAndSearchSimulation.java`
- `examples/generated/java/src/test/resources/users.csv`
- `examples/scenarios/login-and-search.yaml`
- `schemas/scenario.schema.json`
- `tools/gatling_generator/gatling_generator.py`
- `tools/scenario_lint/scenario_lint.py`

## Checks
- `schema`: `passed`
- `scenario-lint`: `passed` (`python tools/scenario_lint/scenario_lint.py examples/scenarios/login-and-search.yaml --format json`)
- `generator`: `passed` (`python tools/gatling_generator/gatling_generator.py examples/scenarios/login-and-search.yaml <temp-project>`)
- `maven-compile`: `passed` (`mvn -q compile`)

## Blocking Findings
- None

## Warnings
- None

## Accepted Waivers
- None

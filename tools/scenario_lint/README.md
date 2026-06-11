# Scenario Lint

`scenario_lint.py` performs deterministic semantic linting for Gatling-AI
scenario YAML files. It is intentionally local and dependency-light for Phase 0:
the only runtime dependency is PyYAML, which is already available in the current
verification environment.

## Usage

```bash
python tools/scenario_lint/scenario_lint.py examples/scenarios/SHOP/login-and-search-002/scenario.yaml
python tools/scenario_lint/scenario_lint.py --format text examples/scenarios/invalid/missing-check.yaml
```

The default JSON output includes these finding fields:

- `rule`
- `severity`
- `path`
- `message`

The command exits `0` when there are no blocking findings and non-zero when at
least one blocking finding exists.

If PyYAML is unavailable, the command emits a blocking
`scenario-lint.load-failed` finding so later quality-gate tooling can report the
environment issue clearly.

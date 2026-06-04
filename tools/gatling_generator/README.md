# Gatling Generator

`gatling_generator.py` reads a Gatling-AI scenario YAML file and writes a Java
Gatling simulation. It is intentionally small and deterministic for Phase 0.

## Usage

```bash
python tools/gatling_generator/gatling_generator.py examples/scenarios/login-and-search.yaml examples/generated/java
```

The generated class name is derived from `scenario.id` by converting kebab-case
to PascalCase and appending `Simulation`.
Invalid `scenario.id` values block generation; IDs must start with a lowercase
letter and use lowercase letters/digits separated by single hyphens.

## Supported Phase 0 Surface

- HTTP `GET` and `POST` steps
- Stable request and group names from `steps[].transaction`
- Explicit `status` checks
- CSS and JSONPath extraction checks with `saveAs`
- CSV feeders with `circular`, `random`, and `queue` strategies
- Closed ramp load profiles using `users`, `ramp_seconds`, and
  `duration_seconds`

PyYAML is required. If PyYAML is unavailable, generation is blocked rather than
falling back to an ad hoc parser.

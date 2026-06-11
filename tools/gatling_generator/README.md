# Gatling Generator

`gatling_generator.py` reads a Gatling-AI scenario YAML file and writes a Java
Gatling simulation. It is intentionally small and deterministic for Phase 0.

## Usage

```bash
python tools/gatling_generator/gatling_generator.py examples/scenarios/SHOP/login-and-search-002/scenario.yaml examples/generated/java
```

The output directory is treated as a Maven project root. The generated Java
simulation is written under `src/test/java`, and referenced CSV feeder files are
copied from the scenario directory into `src/test/resources`.

The generated class name is the script reference
`<SYSTEM>_<PascalCaseId>_<NNN>` built from `scenario.system`, `scenario.id`,
and `scenario.number` (e.g. `SHOP_LoginAndSearch_002`).
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

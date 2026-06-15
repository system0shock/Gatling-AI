# JMX Inventory — simple-backend.jmx

- Size: 8822 bytes (sha256 `5c05e7266924`)
- Test plan: Test Plan
- Elements: 18 total, 0 disabled
- Bodies externalized: 1
- JSR223: 1 typical, 0 complex

## Elements

| Kind | Count |
|---|---|
| constant_timer | 1 |
| csv_data_set | 1 |
| header_manager | 1 |
| http_defaults | 1 |
| http_sampler | 3 |
| jsonpath_extractor | 1 |
| jsr223_pre | 1 |
| regex_extractor | 1 |
| response_assertion | 3 |
| thread_group | 1 |
| transaction | 3 |
| user_defined_variables | 1 |

## Unsupported elements

- None

## Thread groups

| Name | Flavor | Model | Stages | Start after | Note |
|---|---|---|---|---|---|
| Backend load | ultimate | closed | 50u ramp 120s hold 600s | 0s | shutdown ramp-down not representable in stages; ignored |

## Data flow findings

- `${BASE_URL}` is produced but never consumed (elements: e-0017) — dead correlation?
- `${csrf}` is produced but never consumed (elements: e-0010) — dead correlation?
- `${price}` is produced but never consumed (elements: e-0006) — dead correlation?

## Complexity flags

- None

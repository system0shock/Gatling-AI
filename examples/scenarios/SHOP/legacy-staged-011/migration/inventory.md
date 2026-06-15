# JMX Inventory — staged-pipeline.jmx

- Size: 7282 bytes (sha256 `114eebf23c53`)
- Test plan: Test Plan
- Elements: 19 total, 0 disabled
- Bodies externalized: 0
- JSR223: 0 typical, 2 complex

## Elements

| Kind | Count |
|---|---|
| csv_data_set | 1 |
| http_defaults | 2 |
| http_sampler | 3 |
| jdbc_sampler | 1 |
| jsonpath_extractor | 1 |
| jsr223_post | 1 |
| jsr223_pre | 1 |
| response_assertion | 3 |
| thread_group | 2 |
| transaction | 3 |
| user_defined_variables | 1 |

## Unsupported elements

- None

## Thread groups

| Name | Flavor | Model | Stages | Start after | Note |
|---|---|---|---|---|---|
| Stage A - producer | standard | closed | 10u ramp 30s hold 570s | 0s |  |
| Stage B - consumer | standard | closed | 5u ramp 30s hold 570s | 1200s |  |

## Data flow findings

- `${BASE_URL}` is produced but never consumed (elements: e-0001) — dead correlation?
- `${authSig}` is produced but never consumed (elements: e-0017) — dead correlation?
- prop `sharedToken`: writers e-0009; readers e-0017

## Complexity flags

- **inter-thread-props**: props: sharedToken
- **props-usage**: props: sharedToken
- **staged-thread-groups**: 2 thread groups with time offsets

# Отчёт о конвертации

Элементов в IR: **19**.
Сводка диспозиции: converted: 18, partial: 1.

| ID | Тип | Имя | Статус | Примечание |
|---|---|---|---|---|
| e-0003 | thread_group | Stage A - producer | converted |  |
| e-0013 | thread_group | Stage B - consumer | converted |  |
| e-0004 | http_defaults | Defaults | converted |  |
| e-0005 | transaction | login | converted |  |
| e-0007 | jsonpath_extractor | get token | converted |  |
| e-0008 | response_assertion | status 200 | converted |  |
| e-0009 | jsr223_post | share token | converted | captured as todo hook; agent translates later |
| e-0006 | http_sampler | post login | converted |  |
| e-0010 | transaction | kafka publish | converted |  |
| e-0012 | response_assertion | status 202 | converted |  |
| e-0011 | http_sampler | produce event | converted |  |
| e-0014 | http_defaults | Defaults | converted |  |
| e-0015 | transaction | settle | converted |  |
| e-0017 | jsr223_pre | take token | converted | captured as todo hook; agent translates later |
| e-0018 | response_assertion | status 200 | converted |  |
| e-0016 | http_sampler | post settle | converted |  |
| e-0019 | jdbc_sampler | check ledger | partial | jdbc stub until protocol spike |
| e-0001 | user_defined_variables | Env | converted | UDV mapped to env/base_url (values are env-backed; never inlined per NFR5) |
| e-0002 | csv_data_set | products | converted |  |

## Предупреждения

- `convert.default-sla-emitted` — default SLA assertions emitted (p95 < 1000 ms, success > 99%); tune to your targets

# Отчёт о конвертации

Элементов в IR: **18**.
Сводка диспозиции: converted: 18.

| ID | Тип | Имя | Статус | Примечание |
|---|---|---|---|---|
| e-0001 | thread_group | Backend load | converted |  |
| e-0002 | http_defaults | Defaults | converted |  |
| e-0003 | header_manager | Headers | converted |  |
| e-0004 | transaction | catalog list | converted |  |
| e-0006 | jsonpath_extractor | ids | converted |  |
| e-0007 | response_assertion | status 200 | converted |  |
| e-0005 | http_sampler | get catalog | converted |  |
| e-0008 | transaction | catalog search | converted |  |
| e-0010 | regex_extractor | get csrf | converted |  |
| e-0011 | response_assertion | status 200 | converted |  |
| e-0009 | http_sampler | search | converted |  |
| e-0012 | constant_timer | think | converted | timer mapped to pause_seconds=1 on preceding step |
| e-0013 | transaction | checkout submit | converted |  |
| e-0015 | jsr223_pre | make request id | converted | captured as todo hook; agent translates later |
| e-0016 | response_assertion | status 200 | converted |  |
| e-0014 | http_sampler | post checkout | converted |  |
| e-0017 | user_defined_variables | Env | converted | UDV mapped to env/base_url (values are env-backed; never inlined per NFR5) |
| e-0018 | csv_data_set | search terms | converted |  |

## Предупреждения

- `convert.default-sla-emitted` — default SLA assertions emitted (p95 < 1000 ms, success > 99%); tune to your targets

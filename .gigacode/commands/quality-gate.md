---
description: Run the local quality gate on the current scenario + generated project and report the status honestly.
---

Invoke the `quality-gate` skill for the scenario and generated Maven project
currently under review.

If a scenario path and/or project path are provided in {{args}}, use them.
Otherwise ask the user which `scenario.yaml` and which generated project
directory to gate (do not guess).

Run the gate, then report the resulting status (`passed`,
`passed_with_warnings`, or `blocked`) together with the path to
`quality-gate-report.md`. Never claim the work is done unless the status is
`passed` or `passed_with_warnings`.

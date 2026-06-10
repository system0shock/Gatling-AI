# scenario_renderer

Renders a Gatling-AI scenario YAML into reviewer-friendly Markdown (паспорт,
шаги, тестовые данные, профиль нагрузки, корреляции, SLA).

The output is a **generated, one-way artifact**: the header records the source
file and its SHA-256; never edit the .md by hand — edit the scenario YAML and
re-render. The quality gate re-renders the golden scenario and blocks when the
committed document drifts.

## Usage

    python tools/scenario_renderer/scenario_renderer.py examples/scenarios/login-and-search.yaml \
        --output examples/generated/docs/login-and-search.md

Without `--output` the Markdown is printed to stdout. Exit code 1 with a
`BLOCKED:` stderr line when the scenario cannot be rendered.

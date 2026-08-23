# Methodology-First Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Build a deterministic methodology core that resolves default-v1 plus user answers, renders all 17 sections, preserves manual Markdown, and emits separate readiness and template-completeness reports.

**Architecture:** A small methodology_pipeline package consumes a confirmed surface review, a versioned profile, a minimal question catalog, and answers. It builds one validated methodology-input model, renders managed blocks into the current Markdown document, and evaluates readiness and template structure without an author or validator agent.

**Tech Stack:** Python 3.11+, PyYAML 6.0.3, jsonschema 4.26.0, unittest/pytest, Markdown text processing.

**Spec:** docs/superpowers/specs/2026-08-23-methodology-first-generation-design.md

## Global Constraints

- Keep all 17 headings from .gigacode/skills/manage-methodology/templates/methodology-template.md.
- default-v1 uses p95 <= 1 second, technical errors <= 5%, CPU <= 40%, and memory <= 80% without sustained growth.
- Maximum-search steps last 20 minutes; maximum confirmation lasts 2 hours; stability lasts 8 hours at 0.8 of confirmed maximum.
- META is a user reminder and source reference only; this plan performs no network call.
- ready_for_test is blocking; template_complete is advisory.
- Manual blocks and text outside generated blocks are preserved byte-for-byte.
- No agent is invoked by rendering or output control.
- Write only under the load-test repository/run directory.
- Preserve existing methodology_authoring approval and apply behavior.

---

## Planned File Structure

    schemas/methodology-profile.schema.json
        Validates a versioned default or future class-specific profile.
    schemas/methodology-questions.schema.json
        Validates the minimal question catalog.
    schemas/methodology-answers.schema.json
        Validates profile review, overrides, and scalar answers.
    schemas/methodology-surface-review.schema.json
        Shared contract for a confirmed surface; discovery will produce it later.
    schemas/methodology-input.schema.json
        Canonical structured input for readiness and rendering.
    schemas/methodology-generation-state.schema.json
        Stores hashes of last generated blocks.
    schemas/methodology-drift-decisions.schema.json
        Records explicit keep, replace, or move-to-manual decisions for changed generated blocks.
    schemas/methodology-readiness-report.schema.json
        Blocking execution-readiness report.
    schemas/methodology-template-report.schema.json
        Advisory 17-section structural report.
    schemas/methodology-template-contract.schema.json
        Declares the canonical sections and their structural expectations.
    .gigacode/skills/manage-methodology/profiles/default-v1.yaml
        The approved default tests and guardrails.
    .gigacode/skills/manage-methodology/questions.yaml
        Stable scalar questions for unresolved inputs.
    .gigacode/skills/manage-methodology/templates/methodology-template-contract.yaml
        Structural rules for the 17 headings.
    tools/methodology_pipeline/contracts.py
        Schema/YAML/JSON loading and deterministic atomic writers.
    tools/methodology_pipeline/sections.py
        One ordered source of truth for the 17 canonical IDs and headings.
    tools/methodology_pipeline/paths.py
        Nested target get/set helpers shared by profile and questionnaire code.
    tools/methodology_pipeline/profiles.py
        Resolves default profile, manual META values, and explicit overrides.
    tools/methodology_pipeline/questionnaire.py
        Applies answers and returns unresolved questions.
    tools/methodology_pipeline/assembler.py
        Builds and validates methodology-input.yaml.
    tools/methodology_pipeline/readiness.py
        Computes ready_for_test and missing critical inputs.
    tools/methodology_pipeline/managed_blocks.py
        Migrates, hashes, merges, and detects drift in Markdown blocks.
    tools/methodology_pipeline/renderer.py
        Renders deterministic generated content for all 17 headings.
    tools/methodology_pipeline/conformance.py
        Computes complete/partial/missing/not_applicable per section.
    tools/methodology_pipeline/methodology_pipeline.py
        build and check CLI entry point.
    tools/methodology_pipeline/fixtures.py
        Reusable valid test artifacts.
    tools/methodology_pipeline/test_*.py
        Focused unit, contract, and end-to-end tests.
    tools/methodology_pipeline/README.md
        CLI and artifact documentation.

### Task 1: Add contracts and approved configuration assets

**Files:**
- Create: schemas/methodology-profile.schema.json
- Create: schemas/methodology-questions.schema.json
- Create: schemas/methodology-answers.schema.json
- Create: schemas/methodology-surface-review.schema.json
- Create: schemas/methodology-input.schema.json
- Create: schemas/methodology-generation-state.schema.json
- Create: schemas/methodology-drift-decisions.schema.json
- Create: schemas/methodology-readiness-report.schema.json
- Create: schemas/methodology-template-report.schema.json
- Create: schemas/methodology-template-contract.schema.json
- Create: .gigacode/skills/manage-methodology/profiles/default-v1.yaml
- Create: .gigacode/skills/manage-methodology/questions.yaml
- Create: .gigacode/skills/manage-methodology/templates/methodology-template-contract.yaml
- Create: tools/methodology_pipeline/__init__.py
- Create: tools/methodology_pipeline/contracts.py
- Create: tools/methodology_pipeline/sections.py
- Create: tools/methodology_pipeline/fixtures.py
- Create: tools/methodology_pipeline/test_contracts.py

**Interfaces:**
- Produces: load_schema(name: str) -> dict[str, Any]
- Produces: load_yaml_mapping(path: Path, schema_name: str) -> dict[str, Any]
- Produces: validate_artifact(value: Mapping[str, Any], schema_name: str) -> None
- Produces: write_json_atomic(path: Path, value: Mapping[str, Any]) -> None
- Produces: write_yaml_atomic(path: Path, value: Mapping[str, Any]) -> None
- Produces: CANONICAL_SECTIONS: tuple[tuple[str, str], ...]
- Produces: CANONICAL_HEADINGS: tuple[str, ...]

`sections.py` defines the order before any renderer exists:

    CANONICAL_SECTIONS = (
        ("document-passport", "Паспорт документа"),
        ("scope", "Назначение и область тестирования"),
        ("system-description", "Описание системы и функциональности"),
        ("architecture", "Архитектура"),
        ("integrations", "Реестр интеграций"),
        ("interfaces", "Реестр тестируемых интерфейсов"),
        ("flows", "Пользовательские и технические потоки"),
        ("workload", "Модель нагрузки"),
        ("test-types", "Виды тестов"),
        ("sla-slo", "SLA, SLO и критерии приемки"),
        ("environment", "Тестовый стенд"),
        ("test-data", "Требования к тестовым данным"),
        ("observability", "Наблюдаемость и диагностика"),
        ("procedure", "Порядок проведения тестов"),
        ("risks", "Риски, ограничения и допущения"),
        ("artifacts", "Артефакты и отчетность"),
        ("methodology-update", "Актуализация методики"),
    )
    CANONICAL_HEADINGS = tuple(heading for _, heading in CANONICAL_SECTIONS)

- [ ] **Step 1: Write failing asset and schema tests**

    class MethodologyAssetContractTest(unittest.TestCase):
        def setUp(self) -> None:
            self.package = REPO_ROOT / ".gigacode" / "skills" / "manage-methodology"

        def test_default_profile_contains_approved_values(self) -> None:
            profile = contracts.load_yaml_mapping(
                self.package / "profiles" / "default-v1.yaml",
                "methodology-profile.schema.json",
            )
            self.assertEqual(profile["profile_id"], "default-v1")
            self.assertEqual(profile["profile_version"], 1)
            self.assertEqual(profile["tests"]["maximum_search"]["step_minutes"], 20)
            self.assertEqual(profile["tests"]["maximum_confirmation"]["duration_minutes"], 120)
            self.assertEqual(profile["tests"]["stability"]["duration_minutes"], 480)
            self.assertEqual(profile["tests"]["stability"]["load_factor"], 0.8)
            self.assertEqual(profile["criteria"]["response_time"]["percentile"], "p95")
            self.assertEqual(profile["criteria"]["response_time"]["threshold_ms"], 1000)
            self.assertEqual(profile["criteria"]["technical_errors"]["max_percent"], 5)
            self.assertEqual(profile["criteria"]["cpu"]["max_percent"], 40)
            self.assertEqual(profile["criteria"]["memory"]["max_percent"], 80)

        def test_question_ids_and_targets_are_unique(self) -> None:
            catalog = contracts.load_yaml_mapping(
                self.package / "questions.yaml",
                "methodology-questions.schema.json",
            )
            ids = [item["id"] for item in catalog["questions"]]
            targets = [item["target"] for item in catalog["questions"]]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertEqual(len(targets), len(set(targets)))

        def test_template_contract_matches_all_canonical_headings(self) -> None:
            contract = contracts.load_yaml_mapping(
                self.package / "templates" / "methodology-template-contract.yaml",
                "methodology-template-contract.schema.json",
            )
            self.assertEqual(
                [item["heading"] for item in contract["sections"]],
                CANONICAL_HEADINGS,
            )

- [ ] **Step 2: Run tests and confirm the missing assets fail**

Run:

    python tools/methodology_pipeline/test_contracts.py -v

Expected: FAIL because contracts.py and the configuration assets do not exist.

- [ ] **Step 3: Implement exact profile and question assets**

default-v1.yaml:

    version: 1
    profile_id: default-v1
    profile_version: 1
    tests:
      maximum_search:
        step_minutes: 20
      maximum_confirmation:
        duration_minutes: 120
        load_factor: 1.0
      stability:
        duration_minutes: 480
        load_factor: 0.8
    criteria:
      response_time:
        percentile: p95
        threshold_ms: 1000
      technical_errors:
        max_percent: 5
        exclusions: []
      cpu:
        max_percent: 40
        scope: one-openshift-arm
      memory:
        max_percent: 80
        no_sustained_growth: true

questions.yaml must define these stable IDs and targets:

    version: 1
    questions:
      - id: load.unit
        section: Модель нагрузки
        prompt: В какой единице задаётся нагрузка?
        target: load.unit
        type: choice
        choices: [rps, users_per_second, messages_per_second]
        required: true
        applies_to: []
      - id: load.initial
        section: Модель нагрузки
        prompt: С какой нагрузки начать ступенчатый поиск?
        target: load.initial
        type: number
        required: true
        applies_to: []
      - id: load.step_increment
        section: Модель нагрузки
        prompt: На сколько увеличивать нагрузку на каждой ступени?
        target: load.step_increment
        type: number
        required: true
        applies_to: []
      - id: load.operation_mix
        section: Модель нагрузки
        prompt: Укажите операции или потоки и их доли в процентах.
        target: load.operation_mix
        type: text
        required: true
        applies_to: []
      - id: environment.name
        section: Тестовый стенд
        prompt: На каком стенде будут проводиться испытания?
        target: environment.name
        type: text
        required: true
        applies_to: []
      - id: observability.cpu_signal
        section: Наблюдаемость и диагностика
        prompt: Какая метрика и агрегация используются для контроля CPU?
        target: observability.cpu_signal
        type: text
        required: true
        applies_to: []
      - id: observability.memory_signal
        section: Наблюдаемость и диагностика
        prompt: Какая метрика и агрегация используются для контроля памяти?
        target: observability.memory_signal
        type: text
        required: true
        applies_to: []
      - id: observability.memory_growth_window
        section: Наблюдаемость и диагностика
        prompt: На каком окне оценивается устойчивый рост памяти, в минутах?
        target: observability.memory_growth_window
        type: number
        required: true
        applies_to: []
      - id: observability.dashboard
        section: Наблюдаемость и диагностика
        prompt: Где отслеживать CPU, память и время отклика?
        target: observability.dashboard
        type: text
        required: true
        applies_to: []
      - id: test_data.ready
        section: Требования к тестовым данным
        prompt: Подготовлены ли тестовые данные для выбранных операций?
        target: test_data.ready
        type: boolean
        required: true
        applies_to: []

A newly initialized run uses this editable `answers.yaml` shape:

    version: 1
    profile:
      accepted: false
      meta_values: {}
      overrides: {}
    questions: {}
    not_applicable_sections: []

`methodology-template-contract.yaml` uses one record per item in
`CANONICAL_SECTIONS`. Each record has `id`, `heading`,
`allow_not_applicable`, `required_input_targets`, `required_literals`, optional
`table_columns`, `minimum_data_rows`, and `related_question_ids`. Use this exact
MVP matrix:

| Section ID | Structural requirement | N/A legal | Related questions |
|---|---|---:|---|
| document-passport | snapshot ID, profile ID, profile version | no | none |
| scope | confirmed surface and at least one included entity | no | none |
| system-description | `Компонент / Описание / Источники` table with one row | no | none |
| architecture | `Компонент / Связи / Источники` table with one row | no | none |
| integrations | `Интеграция / Протокол или канал / Источники` table with one row | yes | none |
| interfaces | `Интерфейс / Операция / Источники` table with one row | yes | none |
| flows | `Поток / Описание / Источники` table with one row | yes | none |
| workload | load unit, initial load, step increment, operation mix | no | load.unit, load.initial, load.step_increment, load.operation_mix |
| test-types | literals for stepwise maximum, maximum confirmation, stability | no | none |
| sla-slo | response, technical errors, CPU, memory criteria and their sources | no | observability.cpu_signal, observability.memory_signal, observability.memory_growth_window |
| environment | target environment | no | environment.name |
| test-data | explicit ready/not-ready value | no | test_data.ready |
| observability | CPU signal definition, memory signal definition, growth window, dashboard | no | observability.cpu_signal, observability.memory_signal, observability.memory_growth_window, observability.dashboard |
| procedure | ordered search, confirmation, and stability stages | no | none |
| risks | `Риск / Мера` table with one row | yes | none |
| artifacts | readiness, template, Gatling, monitoring, and test-result artifacts | no | none |
| methodology-update | profile ID/version and regeneration rule | no | none |

For a table requirement, `table_columns` stores the exact header labels and
`minimum_data_rows` is 1. For literal requirements, store stable ASCII construct
IDs rendered as HTML comments such as `<!-- mnt:construct:test-step-search -->`;
the human Russian wording may evolve without weakening the structural check.

The schemas must set additionalProperties to false at every closed object and require version 1. Unresolved questionnaire targets are absent from the assembled input until answered; the profile never invents null monitoring semantics. The profile schema accepts optional resolved-only `accepted` and `sources` fields so both the shipped base and `resolved-profile.yaml` validate against one contract. The dynamic `answers.questions`, `profile.meta_values`, `profile.overrides`, and resolved profile `sources` maps use `patternProperties` for stable dotted IDs/targets, while each map value remains a closed object; catalog lookup rejects an answer ID that is not currently declared. Questionnaire values remain scalar, while built-in profile review values may also be arrays of scalars (for example technical-error exclusions); final profile validation enforces the target's real type. This lets an ordinary catalog question for an existing target work without changing the answers schema or orchestration. methodology-surface-review.schema.json must accept version, snapshot_id, status confirmed, and included/excluded/added arrays of entities with entity_type, canonical_key, display_name, attributes, and sources. Each source contains repo_id, revision, relative path, pointer, selection_reason, and SHA-256; user additions use repo_id user and path surface-review. methodology-drift-decisions.schema.json must accept a unique decision per section with action keep, replace, or move-to-manual. Each generation-state block requires actual `sha256`, deterministic `rendered_sha256`, and resolution `rendered` or `keep`; the two hashes may differ only for an explicit one-run keep. The readiness report requires the boolean `ready_for_test`; the template report requires the independent boolean `template_complete` and exactly 17 section records.

Profile numeric constraints are explicit: durations and thresholds are positive,
percent limits are from 0 through 100, stability load factor is greater than 0
and at most 1, and percentile strings start with `p` followed by a numeric value
greater than 0 and at most 100 (including values such as `p99.9`).

- [ ] **Step 4: Implement schema loading and atomic writers**

contracts.py:

    from __future__ import annotations

    import json
    import os
    import tempfile
    from collections.abc import Mapping
    from pathlib import Path
    from typing import Any

    import jsonschema
    import yaml

    SCHEMA_ROOT = Path(__file__).resolve().parents[2] / "schemas"


    def load_schema(name: str) -> dict[str, Any]:
        value = json.loads((SCHEMA_ROOT / name).read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError(f"{name}: schema must be an object")
        return value


    def validate_artifact(value: Mapping[str, Any], schema_name: str) -> None:
        try:
            jsonschema.validate(dict(value), load_schema(schema_name))
        except jsonschema.ValidationError as exc:
            raise ValueError(f"{schema_name}: {exc.message}") from exc


    def load_yaml_mapping(path: Path, schema_name: str) -> dict[str, Any]:
        try:
            value = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
            raise ValueError(f"{path}: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{path}: expected a mapping")
        validate_artifact(value, schema_name)
        return value


    def _atomic_write(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
            os.replace(temporary, path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise


    def write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
        _atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


    def write_yaml_atomic(path: Path, value: Mapping[str, Any]) -> None:
        _atomic_write(path, yaml.safe_dump(dict(value), allow_unicode=True, sort_keys=True))

`fixtures.py` starts with builders for a valid default profile, question catalog,
individual question lookup, answers, and confirmed surface review. Later tasks
extend the same file; no task imports a fixture module that has not yet been
created.

- [ ] **Step 5: Run contract tests**

Run:

    python tools/methodology_pipeline/test_contracts.py -v

Expected: PASS.

- [ ] **Step 6: Commit contracts and assets**

    git add schemas/methodology-profile.schema.json schemas/methodology-questions.schema.json schemas/methodology-answers.schema.json schemas/methodology-surface-review.schema.json schemas/methodology-input.schema.json schemas/methodology-generation-state.schema.json schemas/methodology-drift-decisions.schema.json schemas/methodology-readiness-report.schema.json schemas/methodology-template-report.schema.json schemas/methodology-template-contract.schema.json .gigacode/skills/manage-methodology/profiles/default-v1.yaml .gigacode/skills/manage-methodology/questions.yaml .gigacode/skills/manage-methodology/templates/methodology-template-contract.yaml tools/methodology_pipeline
    git commit -m "feat: add methodology-first contracts and defaults"

### Task 2: Resolve profile values and minimal questions

**Files:**
- Create: tools/methodology_pipeline/paths.py
- Create: tools/methodology_pipeline/profiles.py
- Create: tools/methodology_pipeline/questionnaire.py
- Modify: tools/methodology_pipeline/fixtures.py
- Create: tools/methodology_pipeline/test_profiles.py
- Create: tools/methodology_pipeline/test_questionnaire.py

**Interfaces:**
- Consumes: validated profile, answers, and question mappings from Task 1.
- Produces: get_target(root: Mapping[str, Any], dotted: str) -> Any
- Produces: set_target(root: dict[str, Any], dotted: str, value: Any) -> None
- Produces: resolve_profile(default_profile: Mapping[str, Any], answers: Mapping[str, Any]) -> dict[str, Any]
- Produces: validate_answer(question: Mapping[str, Any], value: Any) -> None
- Produces: apply_scalar_answers(base: Mapping[str, Any], catalog: Mapping[str, Any], answers: Mapping[str, Any]) -> dict[str, Any]
- Produces: unresolved_questions(model: Mapping[str, Any], catalog: Mapping[str, Any], capabilities: Collection[str]) -> list[dict[str, Any]]

- [ ] **Step 1: Write failing precedence and question-selection tests**

    class ProfileResolutionTest(unittest.TestCase):
        def test_user_override_wins_over_manual_meta_and_default(self) -> None:
            resolved = profiles.resolve_profile(
                fixtures.default_profile(),
                {
                    "version": 1,
                    "profile": {
                        "accepted": True,
                        "meta_values": {
                            "criteria.response_time.threshold_ms": {
                                "value": 800,
                                "source_reference": "META-42",
                            }
                        },
                        "overrides": {
                            "criteria.response_time.threshold_ms": {"value": 650}
                        },
                    },
                    "questions": {},
                    "not_applicable_sections": [],
                },
            )
            self.assertEqual(resolved["criteria"]["response_time"]["threshold_ms"], 650)
            self.assertEqual(
                resolved["sources"]["criteria.response_time.threshold_ms"]["source"],
                "user",
            )

    class QuestionnaireTest(unittest.TestCase):
        def test_only_missing_applicable_required_questions_are_returned(self) -> None:
            model = {"load": {"unit": "rps"}, "environment": {}, "observability": {}}
            pending = questionnaire.unresolved_questions(
                model,
                fixtures.question_catalog(),
                {"http"},
            )
            ids = [item["id"] for item in pending]
            self.assertNotIn("load.unit", ids)
            self.assertIn("environment.name", ids)

        def test_scalar_types_and_choices_are_catalog_driven(self) -> None:
            with self.assertRaisesRegex(ValueError, "load.unit"):
                questionnaire.validate_answer(
                    fixtures.question("load.unit"), "unsupported-unit"
                )
            with self.assertRaisesRegex(ValueError, "load.initial"):
                questionnaire.validate_answer(
                    fixtures.question("load.initial"), True
                )

- [ ] **Step 2: Run focused tests and verify failure**

Run:

    python -m unittest tools.methodology_pipeline.test_profiles tools.methodology_pipeline.test_questionnaire -v

Expected: FAIL because the resolver modules do not exist.

- [ ] **Step 3: Implement nested target helpers**

paths.py:

    from __future__ import annotations

    from collections.abc import Mapping
    from typing import Any

    MISSING = object()


    def get_target(root: Mapping[str, Any], dotted: str) -> Any:
        current: Any = root
        for part in dotted.split("."):
            if not isinstance(current, Mapping) or part not in current:
                return MISSING
            current = current[part]
        return current


    def set_target(root: dict[str, Any], dotted: str, value: Any) -> None:
        parts = dotted.split(".")
        current = root
        for part in parts[:-1]:
            child = current.setdefault(part, {})
            if not isinstance(child, dict):
                raise ValueError(f"{dotted}: {part} is not an object")
            current = child
        current[parts[-1]] = value

- [ ] **Step 4: Implement deterministic profile precedence**

profiles.py must deep-copy the base, initialize sources for every scalar leaf as default-v1, apply profile.meta_values in sorted target order with source meta-manual and source_reference, then apply profile.overrides in sorted target order with source user. Missing acceptance resolves to false; the resolver validates the boolean and the readiness check, rather than parsing, blocks until it is true.
Validate the resolved mapping against `methodology-profile.schema.json` after all
overrides so wrong types, unknown targets that create extra fields, and invalid
percent/rate ranges fail before assembly.

Core implementation:

    def resolve_profile(
        default_profile: Mapping[str, Any],
        answers: Mapping[str, Any],
    ) -> dict[str, Any]:
        resolved = copy.deepcopy(dict(default_profile))
        resolved["sources"] = _default_sources(resolved)
        profile_answers = answers.get("profile", {})
        for target, item in sorted(profile_answers.get("meta_values", {}).items()):
            set_target(resolved, target, item["value"])
            resolved["sources"][target] = {
                "source": "meta-manual",
                "source_reference": item["source_reference"],
            }
        for target, item in sorted(profile_answers.get("overrides", {}).items()):
            set_target(resolved, target, item["value"])
            resolved["sources"][target] = {
                "source": "user",
                "source_reference": item.get("source_reference"),
            }
        resolved["accepted"] = profile_answers.get("accepted") is True
        return resolved

- [ ] **Step 5: Implement scalar answer application and pending selection**

questionnaire.py:

    def validate_answer(question: Mapping[str, Any], value: Any) -> None:
        question_id = question["id"]
        kind = question["type"]
        valid = (
            (kind == "text" and isinstance(value, str))
            or (kind == "number" and isinstance(value, (int, float)) and not isinstance(value, bool))
            or (kind == "boolean" and isinstance(value, bool))
            or (kind == "choice" and value in question["choices"])
        )
        if not valid:
            raise ValueError(f"invalid answer for {question_id}")

    def apply_scalar_answers(
        base: Mapping[str, Any],
        catalog: Mapping[str, Any],
        answers: Mapping[str, Any],
    ) -> dict[str, Any]:
        result = copy.deepcopy(dict(base))
        by_id = {item["id"]: item for item in catalog["questions"]}
        for question_id, answer in sorted(answers.get("questions", {}).items()):
            if question_id not in by_id:
                raise ValueError(f"unknown question id: {question_id}")
            validate_answer(by_id[question_id], answer["value"])
            set_target(result, by_id[question_id]["target"], answer["value"])
        return result


    def unresolved_questions(
        model: Mapping[str, Any],
        catalog: Mapping[str, Any],
        capabilities: Collection[str],
    ) -> list[dict[str, Any]]:
        pending = []
        capability_set = set(capabilities)
        for question in catalog["questions"]:
            applies_to = set(question.get("applies_to", []))
            if applies_to and applies_to.isdisjoint(capability_set):
                continue
            value = get_target(model, question["target"])
            if question["required"] and (value is MISSING or value is None or value == ""):
                pending.append(dict(question))
        return pending

- [ ] **Step 6: Run focused tests**

Run:

    python -m unittest tools.methodology_pipeline.test_profiles tools.methodology_pipeline.test_questionnaire -v

Expected: PASS.

- [ ] **Step 7: Commit profile and questionnaire resolution**

    git add tools/methodology_pipeline/paths.py tools/methodology_pipeline/profiles.py tools/methodology_pipeline/questionnaire.py tools/methodology_pipeline/fixtures.py tools/methodology_pipeline/test_profiles.py tools/methodology_pipeline/test_questionnaire.py
    git commit -m "feat: resolve methodology profile and questions"

### Task 3: Assemble canonical input and readiness

**Files:**
- Create: tools/methodology_pipeline/assembler.py
- Create: tools/methodology_pipeline/readiness.py
- Modify: tools/methodology_pipeline/fixtures.py
- Create: tools/methodology_pipeline/test_assembler.py
- Create: tools/methodology_pipeline/test_readiness.py

**Interfaces:**
- Consumes: surface review, workspace snapshot, resolved profile, catalog, and answers.
- Produces: build_input(snapshot, surface_review, resolved_profile, catalog, answers) -> dict[str, Any]
- Produces: readiness_report(methodology_input, pending_questions) -> dict[str, Any]

- [ ] **Step 1: Write failing assembly and readiness tests**

    class AssemblyTest(unittest.TestCase):
        def test_build_input_binds_snapshot_surface_profile_and_answers(self) -> None:
            result = assembler.build_input(
                fixtures.workspace_snapshot(),
                fixtures.surface_review(),
                fixtures.resolved_profile(),
                fixtures.question_catalog(),
                fixtures.complete_answers(),
            )
            self.assertEqual(result["workspace_snapshot_id"], "a" * 64)
            self.assertEqual(result["profile"]["profile_id"], "default-v1")
            self.assertEqual(result["surface"]["status"], "confirmed")
            self.assertEqual(result["load"]["unit"], "rps")

    class ReadinessTest(unittest.TestCase):
        def test_missing_environment_blocks_but_template_fields_do_not(self) -> None:
            value = fixtures.methodology_input()
            del value["environment"]["name"]
            report = readiness.readiness_report(
                value,
                [{"id": "environment.name", "target": "environment.name"}],
            )
            self.assertEqual(report["status"], "blocked")
            self.assertFalse(report["ready_for_test"])
            self.assertEqual(report["missing"][0]["question_id"], "environment.name")

        def test_confirmed_but_empty_surface_blocks(self) -> None:
            value = fixtures.methodology_input()
            value["surface"]["included"] = []
            value["surface"]["added"] = []
            report = readiness.readiness_report(value, [])
            self.assertEqual(report["status"], "blocked")
            self.assertIn("surface.entities", {item["target"] for item in report["missing"]})

- [ ] **Step 2: Run focused tests and verify failure**

Run:

    python -m unittest tools.methodology_pipeline.test_assembler tools.methodology_pipeline.test_readiness -v

Expected: FAIL because assembler.py and readiness.py do not exist.

- [ ] **Step 3: Implement canonical input assembly**

The input artifact must contain version, workspace_snapshot_id, surface, profile, load, environment, observability, test_data, document, and not_applicable_sections. The group objects are required, but unresolved execution fields inside them are optional and type-checked only when present; this is what allows a valid draft input to produce a blocked readiness report instead of a schema crash. The assembler first validates the three input artifacts, copies only confirmed surface entries, applies scalar answers, derives capabilities from included surface protocols, and validates methodology-input.schema.json.

Core implementation:

    def build_input(
        snapshot: Mapping[str, Any],
        surface_review: Mapping[str, Any],
        resolved_profile: Mapping[str, Any],
        catalog: Mapping[str, Any],
        answers: Mapping[str, Any],
    ) -> dict[str, Any]:
        if surface_review["snapshot_id"] != snapshot["snapshot_id"]:
            raise ValueError("surface review does not match workspace snapshot")
        base = {
            "version": 1,
            "workspace_snapshot_id": snapshot["snapshot_id"],
            "surface": copy.deepcopy(dict(surface_review)),
            "profile": copy.deepcopy(dict(resolved_profile)),
            "load": {},
            "environment": {},
            "observability": {},
            "test_data": {},
            "document": {},
            "not_applicable_sections": list(answers.get("not_applicable_sections", [])),
        }
        result = apply_scalar_answers(base, catalog, answers)
        validate_artifact(result, "methodology-input.schema.json")
        return result

- [ ] **Step 4: Implement deterministic readiness**

readiness.py:

    CRITICAL_TARGETS = (
        "profile.accepted",
        "load.unit",
        "load.initial",
        "load.step_increment",
        "load.operation_mix",
        "environment.name",
        "observability.cpu_signal",
        "observability.memory_signal",
        "observability.memory_growth_window",
        "observability.dashboard",
        "test_data.ready",
    )


    def readiness_report(
        methodology_input: Mapping[str, Any],
        pending_questions: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        by_target = {item["target"]: item["id"] for item in pending_questions}
        missing = []
        surface = methodology_input.get("surface", {})
        if (
            surface.get("status") != "confirmed"
            or not (surface.get("included", []) or surface.get("added", []))
        ):
            missing.append({
                "target": "surface.entities",
                "question_id": None,
                "message": "confirmed test surface must contain at least one entity",
            })
        for target in CRITICAL_TARGETS:
            value = get_target(methodology_input, target)
            if value is MISSING or value is None or value == "" or value is False:
                missing.append({
                    "target": target,
                    "question_id": by_target.get(target),
                    "message": f"required execution input is missing: {target}",
                })
        return {
            "version": 1,
            "status": "ready" if not missing else "blocked",
            "ready_for_test": not missing,
            "workspace_snapshot_id": methodology_input["workspace_snapshot_id"],
            "missing": missing,
        }

- [ ] **Step 5: Run assembly and readiness tests**

Run:

    python -m unittest tools.methodology_pipeline.test_assembler tools.methodology_pipeline.test_readiness -v

Expected: PASS.

- [ ] **Step 6: Commit the canonical input path**

    git add tools/methodology_pipeline/assembler.py tools/methodology_pipeline/readiness.py tools/methodology_pipeline/fixtures.py tools/methodology_pipeline/test_assembler.py tools/methodology_pipeline/test_readiness.py
    git commit -m "feat: assemble methodology input and readiness"

### Task 4: Preserve manual Markdown and detect managed drift

**Files:**
- Create: tools/methodology_pipeline/managed_blocks.py
- Create: tools/methodology_pipeline/test_managed_blocks.py

**Interfaces:**
- Produces: parse_sections(markdown: str) -> OrderedDict[str, str]
- Produces: migrate_legacy(markdown: str, headings: Sequence[str]) -> str
- Produces: BlockMergeResult(markdown, generation_state, conflicts, warnings)
- Produces: merge_generated(current, generated_by_id, previous_state) -> BlockMergeResult
- Produces: resolve_drift(current, generated_by_id, previous_state, decisions) -> BlockMergeResult
- Produces: sha256_text(text: str) -> str

- [ ] **Step 1: Write failing preservation, migration, and drift tests**

    class ManagedBlocksTest(unittest.TestCase):
        def test_merge_replaces_generated_and_preserves_manual_bytes(self) -> None:
            current = fixtures.document_with_blocks(manual="ручной текст\r\n")
            result = managed_blocks.merge_generated(
                current,
                {"test-types": "новый generated\n"},
                fixtures.generation_state(current),
            )
            self.assertIn("новый generated\n", result.markdown)
            self.assertIn("ручной текст\r\n", result.markdown)
            self.assertEqual(result.conflicts, ())
            self.assertEqual(result.warnings, ())
            self.assertIn("test-types", result.generation_state["blocks"])

        def test_changed_generated_block_is_a_conflict(self) -> None:
            original = fixtures.document_with_blocks(generated="исходный\n")
            changed = original.replace("исходный", "ручная правка внутри generated")
            result = managed_blocks.merge_generated(
                changed,
                {"test-types": "новый\n"},
                fixtures.generation_state(original),
            )
            self.assertEqual(result.conflicts[0]["rule"], "managed-block-drift")
            self.assertEqual(result.markdown, changed)

        def test_nonempty_generated_block_without_prior_state_is_not_overwritten(self) -> None:
            current = fixtures.document_with_blocks(generated="неизвестный источник\n")
            result = managed_blocks.merge_generated(
                current, {"test-types": "новый\n"}, {"version": 1, "blocks": {}}
            )
            self.assertEqual(result.conflicts[0]["rule"], "generation-state-missing")
            self.assertEqual(result.markdown, current)

        def test_legacy_section_body_moves_to_manual_block(self) -> None:
            migrated = managed_blocks.migrate_legacy(
                "# Методика\n\n## Виды тестов\n\nСуществующий текст\n",
                ["Виды тестов"],
            )
            self.assertIn("mnt:manual:start id=test-types", migrated)
            self.assertIn("Существующий текст", migrated)

        def test_explicit_drift_actions_have_distinct_results(self) -> None:
            changed = fixtures.document_with_blocks(
                generated="ручная правка\n", manual="существующий manual\n"
            )
            state = fixtures.generation_state(
                fixtures.document_with_blocks(generated="исходный\n")
            )
            keep = managed_blocks.resolve_drift(
                changed, {"test-types": "новый\n"}, state,
                {"test-types": "keep"},
            )
            replace = managed_blocks.resolve_drift(
                changed, {"test-types": "новый\n"}, state,
                {"test-types": "replace"},
            )
            moved = managed_blocks.resolve_drift(
                changed, {"test-types": "новый\n"}, state,
                {"test-types": "move-to-manual"},
            )
            self.assertIn("ручная правка", keep.markdown)
            self.assertEqual(keep.warnings[0]["rule"], "user-kept-generated-block")
            self.assertEqual(
                keep.generation_state["blocks"]["test-types"]["resolution"],
                "keep",
            )
            self.assertNotIn("ручная правка", replace.markdown)
            self.assertIn("ручная правка", moved.markdown)
            self.assertIn("новый", moved.markdown)

- [ ] **Step 2: Run the test and verify failure**

Run:

    python tools/methodology_pipeline/test_managed_blocks.py -v

Expected: FAIL because managed_blocks.py does not exist.

- [ ] **Step 3: Implement strict marker parsing**

Use these exact marker forms:

    <!-- mnt:generated:start id=<section-id> -->
    <!-- mnt:generated:end -->
    <!-- mnt:manual:start id=<section-id> -->
    <!-- mnt:manual:end -->

The parser must reject duplicate canonical headings, nested markers, mismatched IDs, duplicate generated/manual IDs, and an unterminated marker. It preserves the original newline sequences around manual content.

Core hash helper:

    def sha256_text(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

Use one immutable result type for both paths:

    @dataclass(frozen=True)
    class BlockMergeResult:
        markdown: str
        generation_state: dict[str, Any]
        conflicts: tuple[dict[str, str], ...]
        warnings: tuple[dict[str, str], ...]

- [ ] **Step 4: Implement legacy migration and merge**

For each canonical section without markers, migrate the complete existing body into a manual block and insert an empty generated block before it. An empty generated block with no previous hash is safe first generation. A non-empty generated block with no previous hash produces `generation-state-missing` and is handled by the same explicit drift decisions. Otherwise, compare the current generated body hash with previous_state.blocks[id].sha256. On mismatch, append this conflict and keep the current complete document unchanged:

    {
        "rule": "managed-block-drift",
        "section_id": section_id,
        "message": f"generated block changed outside the renderer: {section_id}",
    }

On a clean match, replace only the generated body and emit:

    {
        "version": 1,
        "blocks": {
            section_id: {
                "sha256": sha256_text(new_generated_body),
                "rendered_sha256": sha256_text(new_generated_body),
                "resolution": "rendered",
            }
        },
    }

`resolve_drift` first validates `methodology-drift-decisions.schema.json`, then
requires a decision for every detected conflict:

- `keep` preserves the changed generated body for this run, records its actual
  hash, the different deterministic renderer hash, resolution `keep`, and a
  visible `user-kept-generated-block` warning;
- `replace` discards the changed generated body and installs the deterministic
  renderer output;
- `move-to-manual` appends the changed generated body to the existing manual
  block with one blank-line separator, then installs the deterministic renderer
  output.

All three remove the resolved conflict. `keep` is a one-run exception: a later
regeneration may replace that body once it still matches the recorded baseline.
The durable fallback for prose is `move-to-manual`.

- [ ] **Step 5: Run managed-block tests**

Run:

    python tools/methodology_pipeline/test_managed_blocks.py -v

Expected: PASS.

- [ ] **Step 6: Commit managed-block support**

    git add tools/methodology_pipeline/managed_blocks.py tools/methodology_pipeline/test_managed_blocks.py
    git commit -m "feat: preserve manual methodology blocks"

### Task 5: Render all 17 generated sections deterministically

**Files:**
- Create: tools/methodology_pipeline/renderer.py
- Create: tools/methodology_pipeline/test_renderer.py
- Modify: .gigacode/skills/manage-methodology/templates/methodology-template.md

**Interfaces:**
- Consumes: methodology input and current/migrated Markdown.
- Produces: render_generated_sections(methodology_input) -> OrderedDict[str, str]
- Produces: render_candidate(current_markdown, methodology_input, previous_state) -> RenderResult

- [ ] **Step 1: Write failing renderer tests**

    class RendererTest(unittest.TestCase):
        def test_renders_all_headings_and_approved_profile_values(self) -> None:
            result = renderer.render_candidate(
                fixtures.empty_methodology_template(),
                fixtures.methodology_input(),
                {"version": 1, "blocks": {}},
            )
            for heading in fixtures.canonical_headings():
                self.assertEqual(result.markdown.count(f"## {heading}"), 1)
            self.assertIn("20 минут", result.markdown)
            self.assertIn("2 часа", result.markdown)
            self.assertIn("8 часов", result.markdown)
            self.assertIn("80% подтверждённого максимума", result.markdown)
            self.assertIn("p95", result.markdown)
            self.assertIn("5%", result.markdown)
            self.assertEqual(result.conflicts, ())

        def test_same_input_produces_identical_bytes(self) -> None:
            first = renderer.render_candidate(
                fixtures.empty_methodology_template(),
                fixtures.methodology_input(),
                {"version": 1, "blocks": {}},
            )
            second = renderer.render_candidate(
                first.markdown,
                fixtures.methodology_input(),
                first.generation_state,
            )
            self.assertEqual(second.markdown.encode("utf-8"), first.markdown.encode("utf-8"))

- [ ] **Step 2: Run renderer tests and verify failure**

Run:

    python tools/methodology_pipeline/test_renderer.py -v

Expected: FAIL because renderer.py does not exist.

- [ ] **Step 3: Add managed/manual markers to the permanent template**

For each of the existing 17 headings, add one generated and one manual block with a stable kebab-case ID. Keep the current evidence comments only in legacy documentation, not inside the new generated blocks. The first heading IDs are document-passport, scope, system-description, architecture, integrations, interfaces, flows, workload, test-types, sla-slo, environment, test-data, observability, procedure, risks, artifacts, and methodology-update.

- [ ] **Step 4: Implement section renderers**

renderer.py must define one function per section and an ordered registry matching the template. Each function returns only the body inside its generated block. Values must be formatted from methodology_input; absent non-critical values render the exact marker:

    > Нет подтверждённых данных.

Each renderer also emits the stable `mnt:construct` comments declared for that
section in the template contract. Conformance checks these comments and table
shapes; the comments do not substitute for required input values or data rows.
Escape user text before interpolation: replace `&` and `<` with HTML entities,
prefix lines beginning with Markdown headings, block quotes, or code fences with
a backslash, and replace table-cell `|` with `\|` plus embedded newlines with
`<br>`. Source paths are rendered only from validated relative source records.

The fixed test-types renderer must emit:

    def render_test_types(value: Mapping[str, Any]) -> str:
        tests = value["profile"]["tests"]
        return (
            "1. **Ступенчатый поиск максимума.** "
            f"Длительность ступени — {tests['maximum_search']['step_minutes']} минут. "
            "Максимумом считается последняя полностью пройденная ступень.\n"
            "2. **Подтверждение максимума.** "
            f"Нагрузка на найденном максимуме удерживается "
            f"{tests['maximum_confirmation']['duration_minutes'] // 60} часа.\n"
            "3. **Стабильность.** "
            f"Нагрузка {int(tests['stability']['load_factor'] * 100)}% "
            f"подтверждённого максимума удерживается "
            f"{tests['stability']['duration_minutes'] // 60} часов.\n"
        )

The SLA renderer must include response percentile/threshold, technical errors, CPU, memory, source labels, and user-supplied monitoring semantics. The registries must sort included surface items by entity_type and canonical_key. User-entered free text is inserted as text, never interpreted as Markdown directives or filesystem paths.

- [ ] **Step 5: Implement render_candidate**

    @dataclass(frozen=True)
    class RenderResult:
        markdown: str
        generation_state: dict[str, Any]
        conflicts: tuple[dict[str, str], ...]
        warnings: tuple[dict[str, str], ...]


    def render_candidate(
        current_markdown: str,
        methodology_input: Mapping[str, Any],
        previous_state: Mapping[str, Any],
        drift_decisions: Mapping[str, str] | None = None,
    ) -> RenderResult:
        migrated = migrate_legacy(current_markdown, CANONICAL_HEADINGS)
        generated = render_generated_sections(methodology_input)
        result = merge_generated(migrated, generated, previous_state)
        if result.conflicts and drift_decisions is not None:
            result = resolve_drift(
                migrated, generated, previous_state, drift_decisions
            )
        return RenderResult(
            result.markdown,
            result.generation_state,
            result.conflicts,
            result.warnings,
        )

- [ ] **Step 6: Run renderer and managed-block tests**

Run:

    python -m unittest tools.methodology_pipeline.test_managed_blocks tools.methodology_pipeline.test_renderer -v

Expected: PASS.

- [ ] **Step 7: Commit deterministic rendering**

    git add .gigacode/skills/manage-methodology/templates/methodology-template.md tools/methodology_pipeline/renderer.py tools/methodology_pipeline/test_renderer.py
    git commit -m "feat: render methodology-first document"

### Task 6: Produce readiness and 17-section conformance reports

**Files:**
- Create: tools/methodology_pipeline/conformance.py
- Create: tools/methodology_pipeline/test_conformance.py

**Interfaces:**
- Consumes: candidate Markdown, template contract, input, readiness report, and explicit not-applicable decisions.
- Produces: template_report(markdown, contract, methodology_input) -> dict[str, Any]
- Produces: render_readiness_markdown(report) -> str
- Produces: render_template_markdown(report) -> str

- [ ] **Step 1: Write failing conformance tests**

    class ConformanceTest(unittest.TestCase):
        def test_missing_optional_section_is_advisory(self) -> None:
            report = conformance.template_report(
                fixtures.rendered_methodology(missing="Архитектура"),
                fixtures.template_contract(),
                fixtures.methodology_input(),
            )
            section = next(item for item in report["sections"] if item["heading"] == "Архитектура")
            self.assertEqual(section["status"], "missing")
            self.assertEqual(report["status"], "incomplete")
            self.assertFalse(report["template_complete"])

        def test_not_applicable_requires_explicit_reason(self) -> None:
            value = fixtures.methodology_input()
            value["not_applicable_sections"] = [
                {"section_id": "integrations", "reason": "Система не имеет внешних интеграций."}
            ]
            report = conformance.template_report(
                fixtures.rendered_methodology(missing="Реестр интеграций"),
                fixtures.template_contract(),
                value,
            )
            section = next(item for item in report["sections"] if item["id"] == "integrations")
            self.assertEqual(section["status"], "not_applicable")

        def test_manual_text_does_not_make_readiness_green(self) -> None:
            value = fixtures.methodology_input()
            del value["environment"]["name"]
            readiness_result = readiness.readiness_report(value, [])
            self.assertEqual(readiness_result["status"], "blocked")

- [ ] **Step 2: Run conformance tests and verify failure**

Run:

    python tools/methodology_pipeline/test_conformance.py -v

Expected: FAIL because conformance.py does not exist.

- [ ] **Step 3: Implement structural section classification**

For every contract section:

- missing: heading absent, empty body, or body contains only the no-data marker;
- not_applicable: the section allows it and methodology_input contains a non-empty explicit reason;
- partial: heading exists but a required table has no data row or a required generated marker is absent;
- complete: all declared structural checks pass.

The report status is complete and `template_complete` is true only when every
section is complete or explicitly not_applicable. Otherwise status is incomplete
and `template_complete` is false. It never changes ready_for_test.

- [ ] **Step 4: Implement deterministic Markdown summaries**

Readiness summary starts with:

    # Methodology readiness

    Status: READY

or:

    # Methodology readiness

    Status: BLOCKED

Template summary starts with the count:

    # Methodology template conformance

    Complete: 14/17

and groups partial and missing sections with their related question IDs.

- [ ] **Step 5: Run conformance and schema tests**

Run:

    python -m unittest tools.methodology_pipeline.test_contracts tools.methodology_pipeline.test_readiness tools.methodology_pipeline.test_conformance -v

Expected: PASS.

- [ ] **Step 6: Commit deterministic output control**

    git add tools/methodology_pipeline/conformance.py tools/methodology_pipeline/test_conformance.py
    git commit -m "feat: report methodology readiness and completeness"

### Task 7: Add the core build/check CLI and end-to-end fixture

**Files:**
- Create: tools/methodology_pipeline/methodology_pipeline.py
- Create: tools/methodology_pipeline/test_methodology_pipeline.py
- Create: tools/methodology_pipeline/README.md

**Interfaces:**
- Produces CLI command build.
- Produces CLI command check.
- Produces run artifacts resolved-profile.yaml, methodology-input.yaml, generation-state.json, methodology.candidate.md, readiness JSON/Markdown, and template JSON/Markdown.

- [ ] **Step 1: Write failing CLI end-to-end test**

    class MethodologyPipelineCliTest(unittest.TestCase):
        def test_build_is_deterministic_and_emits_both_reports(self) -> None:
            paths = fixtures.write_core_cli_fixture(self.root)
            args = fixtures.core_build_args(paths)
            first = subprocess.run(args, capture_output=True, text=True, check=False)
            self.assertEqual(first.returncode, 0, first.stderr)
            candidate = paths["out_dir"] / "methodology.candidate.md"
            first_bytes = candidate.read_bytes()
            second = subprocess.run(args, capture_output=True, text=True, check=False)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(candidate.read_bytes(), first_bytes)
            readiness_value = json.loads(
                (paths["out_dir"] / "methodology-readiness-report.json").read_text(encoding="utf-8")
            )
            template_value = json.loads(
                (paths["out_dir"] / "methodology-template-report.json").read_text(encoding="utf-8")
            )
            self.assertEqual(readiness_value["status"], "ready")
            self.assertTrue(readiness_value["ready_for_test"])
            self.assertIn(template_value["status"], {"complete", "incomplete"})
            self.assertEqual(
                template_value["template_complete"],
                template_value["status"] == "complete",
            )

- [ ] **Step 2: Run CLI test and verify failure**

Run:

    python tools/methodology_pipeline/test_methodology_pipeline.py -v

Expected: FAIL because methodology_pipeline.py does not exist.

- [ ] **Step 3: Implement build arguments and orchestration**

build arguments:

    --workspace-snapshot <workspace-snapshot.json>
    --surface-review <surface-review.json>
    --profile <default-v1.yaml>
    --questions <questions.yaml>
    --answers <answers.yaml>
    --template <methodology-template.md>
    --template-contract <methodology-template-contract.yaml>
    --current <methodology.md>
    --previous-generation-state <generation-state.json>
    --drift-decisions <managed-drift-decisions.yaml>
    --out-dir <run-dir>
    --load-test-root <load-test-root>

`--previous-generation-state` and `--drift-decisions` are optional on first
generation. The build command resolves profile, builds input, computes pending
questions, renders the candidate, applies only explicit drift decisions, writes
all artifacts atomically, and returns:

- when `--current` does not exist, initialize from the supplied permanent
  template (create mode);
- when `--current` exists, migrate or merge that exact content (update mode);
- require current, snapshot, review, answers, prior state/decisions, and out-dir
  paths to resolve under the configured load-test root; shipped profile,
  questions, template, and template contract are read-only package assets and
  must resolve under the installed manage-methodology skill directory.

- 0 when ready with no template or renderer warnings;
- 1 when ready with template warnings or an explicit one-run keep warning;
- 2 when readiness is blocked, a managed block conflicts, or an input is invalid.

It writes reports even for return code 2 when inputs are parseable.

- [ ] **Step 4: Implement check command**

check reads an existing candidate/input/state plus template contract and regenerates only the two reports. It must not read a repository, surface source, profile source, or current methodology:

    methodology_pipeline.py check
      --candidate <methodology.candidate.md>
      --methodology-input <methodology-input.yaml>
      --generation-state <generation-state.json>
      --template-contract <methodology-template-contract.yaml>
      --out-dir <run-dir>
      --load-test-root <load-test-root>

- [ ] **Step 5: Document exact CLI behavior**

README.md must include the build/check commands, exit-code table, generated artifacts, META reminder behavior, manual-block conflict behavior, and the statement that this tool never applies methodology.md.

- [ ] **Step 6: Run the complete core suite**

Run:

    python -m unittest discover -s tools/methodology_pipeline -p "test_*.py" -v

Expected: all tests PASS.

- [ ] **Step 7: Run repository regression tests**

Run:

    python -m unittest discover -s tools -p "test_*.py" -v

Expected: all existing and new tool tests PASS.

- [ ] **Step 8: Commit the core CLI**

    git add tools/methodology_pipeline
    git commit -m "feat: add methodology-first core CLI"

## Plan 1 Completion Evidence

Before moving to the discovery plan, run:

    python -m unittest discover -s tools/methodology_pipeline -p "test_*.py" -v
    python -m unittest discover -s tools -p "test_*.py" -v
    git status --short

Expected: both suites exit 0; only pre-existing unrelated working-tree entries remain.

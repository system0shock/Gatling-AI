# Naming Conventions & Folder Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ввести `system`/`number` в контракт сценария, скрипт-реф `<SYSTEM>_<PascalCase(id)>_<NNN>` как имя Java-класса, lint-правила (фидеры, сквозной NN, layout) и ко-локационную структуру `scenarios/<SYSTEM>/<id>-<NNN>/` с `passport.md` рядом со сценарием.

**Architecture:** Источник правды — `scenario.yaml` (новые поля `system`, `number`); все производные имена строит `tools/_shared/common.py::script_ref` и проверяет lint. Quality gate и renderer переходят на ко-локацию доки (`passport.md` рядом со сценарием, `--docs-dir` остаётся как override). Golden-примеры мигрируют в `examples/scenarios/SHOP/<id>-<NNN>/`.

**Tech Stack:** Python 3 (stdlib + PyYAML + jsonschema), unittest, JSON Schema 2020-12, Maven/Gatling 3.12 (генерируемые артефакты).

**Спека:** `docs/superpowers/specs/2026-06-10-naming-and-layout-design.md`.

**Как запускать тесты** (из корня репо; pytest из корня не работает, импорты per-directory):

```powershell
python tools/_shared/test_common.py
python tools/scenario_lint/test_scenario_lint.py
python tools/gatling_generator/test_gatling_generator.py
python tools/scenario_renderer/test_scenario_renderer.py
python tools/quality_gate/test_quality_gate.py
python tools/test_contract_coverage.py
python tools/hook_router/test_hook_router.py
python tools/mock_sut/test_mock_sut.py
```

---

### Task 1: `script_ref` в shared-хелперах

**Files:**
- Modify: `tools/_shared/common.py` (после `pascal_case`/`camel_case`, ~строка 101)
- Test: `tools/_shared/test_common.py`

- [ ] **Step 1: Write the failing test**

Добавить в `tools/_shared/test_common.py` (после `CamelCaseTest`):

```python
class ScriptRefTest(unittest.TestCase):
    def test_mask_shape(self) -> None:
        self.assertEqual(common.script_ref("SHOP", "checkout-mix", 1), "SHOP_CheckoutMix_001")
        self.assertEqual(common.script_ref("CRM", "login-flow", 42), "CRM_LoginFlow_042")

    def test_numbers_beyond_999_keep_all_digits(self) -> None:
        self.assertEqual(common.script_ref("SHOP", "demo", 1234), "SHOP_Demo_1234")

    def test_system_re_accepts_codes_and_rejects_garbage(self) -> None:
        self.assertTrue(common.SYSTEM_RE.fullmatch("SHOP"))
        self.assertTrue(common.SYSTEM_RE.fullmatch("A1"))
        for bad in ("shop", "S", "1SHOP", "SHOP_X", "ABCDEFGHIJK"):
            self.assertIsNone(common.SYSTEM_RE.fullmatch(bad), bad)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python tools/_shared/test_common.py`
Expected: FAIL/ERROR — `module 'common' has no attribute 'script_ref'`

- [ ] **Step 3: Write minimal implementation**

В `tools/_shared/common.py` после `camel_case` добавить:

```python
SYSTEM_RE = re.compile(r"^[A-Z][A-Z0-9]{1,9}$")


def script_number(number: int) -> str:
    """1 -> '001'; beyond 999 all digits are kept."""
    return f"{number:03d}"


def script_ref(system: str, scenario_id: str, number: int) -> str:
    """User-approved script mask: ('SHOP', 'checkout-mix', 1) -> 'SHOP_CheckoutMix_001'."""
    return f"{system}_{pascal_case(scenario_id)}_{script_number(number)}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python tools/_shared/test_common.py`
Expected: PASS (OK)

- [ ] **Step 5: Commit**

```bash
git add tools/_shared/common.py tools/_shared/test_common.py
git commit -m "feat: add script_ref mask helper (SYSTEM_PascalCaseId_NNN)"
```

---

### Task 2: Схема — обязательные `system`/`number` + декларации contract coverage

Схема и декларации CONSUMED меняются в одном коммите, иначе `test_contract_coverage.py` красный между шагами.

**Files:**
- Modify: `schemas/scenario.schema.json` (обе ветки `properties.scenario.oneOf`)
- Modify: `tools/gatling_generator/gatling_generator.py:74-94` (`CONSUMED_FIELDS`)
- Modify: `tools/scenario_renderer/scenario_renderer.py:65-90` (`CONSUMED_FIELDS`)
- Test: `tools/scenario_lint/test_scenario_lint.py` (класс `SchemaContractTest`)

- [ ] **Step 1: Write the failing test**

В `SchemaContractTest` добавить:

```python
    def test_schema_requires_system_and_number(self) -> None:
        schema = json.loads(
            (REPO_ROOT / "schemas" / "scenario.schema.json").read_text(encoding="utf-8")
        )
        for variant in schema["properties"]["scenario"]["oneOf"]:
            self.assertIn("system", variant["required"])
            self.assertIn("number", variant["required"])
            self.assertEqual(
                variant["properties"]["system"]["pattern"], "^[A-Z][A-Z0-9]{1,9}$"
            )
            self.assertEqual(variant["properties"]["number"]["minimum"], 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python tools/scenario_lint/test_scenario_lint.py`
Expected: FAIL — `'system' not found in ['id', 'title', ...]`

- [ ] **Step 3: Implement schema change**

В `schemas/scenario.schema.json` в ОБЕИХ ветках `properties.scenario.oneOf`:

1. В `required` добавить `"system", "number"`:
   - первая ветка: `"required": ["id", "title", "system", "number", "source", "sut", "steps", "load", "assertions"]`
   - вторая ветка: `"required": ["id", "title", "system", "number", "source", "sut", "populations", "assertions"]`
2. В `properties` обеих веток после `"title"` добавить:

```json
            "system": { "type": "string", "pattern": "^[A-Z][A-Z0-9]{1,9}$" },
            "number": { "type": "integer", "minimum": 1 },
```

- [ ] **Step 4: Declare the new fields in both schema consumers**

В `tools/gatling_generator/gatling_generator.py` в литерал `CONSUMED_FIELDS` (множество в скобках, строки ~75-91) добавить два элемента:

```python
        "scenario.system",
        "scenario.number",
```

То же самое в `tools/scenario_renderer/scenario_renderer.py` в `CONSUMED_FIELDS` (строки ~66-87).

- [ ] **Step 5: Run tests to verify they pass**

Run: `python tools/scenario_lint/test_scenario_lint.py; python tools/test_contract_coverage.py`
Expected: оба PASS (contract coverage видит новые поля задекларированными)

- [ ] **Step 6: Commit**

```bash
git add schemas/scenario.schema.json tools/gatling_generator/gatling_generator.py tools/scenario_renderer/scenario_renderer.py tools/scenario_lint/test_scenario_lint.py
git commit -m "feat: require scenario.system and scenario.number in the schema"
```

---

### Task 3: Lint — формат `system`/`number`

**Files:**
- Modify: `tools/scenario_lint/scenario_lint.py` (`lint_scenario`, после блока feeders ~строка 331)
- Test: `tools/scenario_lint/test_scenario_lint.py`

- [ ] **Step 1: Обновить ВСЕ фикстуры тестов** (новые правила сделают их «грязными»)

В `tools/scenario_lint/test_scenario_lint.py` в каждый словарь `"scenario": {` фикстур добавить две строки сразу после `"id": ...`:

```python
            "system": "DEMO",
            "number": 1,
```

Затронутые места: `waived_document()` (~строка 36), `LoadProfileLintTest.lint()` (~105), `GraphqlLintTest.document_with()` (~169), `populations_document()` (~211), `minimal_document()` (~355).

- [ ] **Step 2: Write the failing tests**

Добавить в конец файла перед `if __name__`:

```python
class SystemNumberLintTest(unittest.TestCase):
    def rules(self, document: dict) -> list[str]:
        return [f.rule for f in scenario_lint.lint_document(document)]

    def test_missing_system_blocks(self) -> None:
        document = minimal_document(http_step("GET"))
        del document["scenario"]["system"]
        self.assertIn("scenario-lint.system-format", self.rules(document))

    def test_lowercase_system_blocks(self) -> None:
        document = minimal_document(http_step("GET"))
        document["scenario"]["system"] = "shop"
        self.assertIn("scenario-lint.system-format", self.rules(document))

    def test_missing_number_blocks(self) -> None:
        document = minimal_document(http_step("GET"))
        del document["scenario"]["number"]
        self.assertIn("scenario-lint.number-format", self.rules(document))

    def test_zero_and_bool_number_block(self) -> None:
        for bad in (0, -1, True, "1"):
            document = minimal_document(http_step("GET"))
            document["scenario"]["number"] = bad
            self.assertIn("scenario-lint.number-format", self.rules(document), repr(bad))

    def test_valid_system_and_number_pass(self) -> None:
        document = minimal_document(http_step("GET"))
        rules = self.rules(document)
        self.assertNotIn("scenario-lint.system-format", rules)
        self.assertNotIn("scenario-lint.number-format", rules)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python tools/scenario_lint/test_scenario_lint.py`
Expected: FAIL — `'scenario-lint.system-format' not found in [...]`

- [ ] **Step 4: Implement**

В `tools/scenario_lint/scenario_lint.py`:

1. Импорт: в блок `from _shared.common import (...)` добавить `SYSTEM_RE,`.
2. В `lint_scenario`, сразу после строки `scenario = document["scenario"]`:

```python
    system = scenario.get("system")
    if not isinstance(system, str) or not SYSTEM_RE.fullmatch(system):
        add(
            findings,
            "scenario-lint.system-format",
            BLOCKING,
            "$.scenario.system",
            "scenario.system is required and must match ^[A-Z][A-Z0-9]{1,9}$ (e.g. SHOP)",
        )
    number = scenario.get("number")
    if isinstance(number, bool) or not isinstance(number, int) or number < 1:
        add(
            findings,
            "scenario-lint.number-format",
            BLOCKING,
            "$.scenario.number",
            "scenario.number is required and must be a positive integer (unique within the system)",
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python tools/scenario_lint/test_scenario_lint.py`
Expected: PASS (включая обновлённые старые фикстуры)

- [ ] **Step 6: Commit**

```bash
git add tools/scenario_lint/scenario_lint.py tools/scenario_lint/test_scenario_lint.py
git commit -m "feat: lint scenario.system and scenario.number format"
```

---

### Task 4: Lint — имя фидера и имя файла

**Files:**
- Modify: `tools/scenario_lint/scenario_lint.py` (`lint_scenario`)
- Test: `tools/scenario_lint/test_scenario_lint.py`

- [ ] **Step 1: Write the failing tests**

```python
class FeederNamingLintTest(unittest.TestCase):
    def rules(self, feeder: dict) -> list[str]:
        document = minimal_document(http_step("GET"))
        document["scenario"]["data"] = {"feeders": [feeder]}
        return [f.rule for f in scenario_lint.lint_document(document)]

    def test_valid_feeder_passes(self) -> None:
        rules = self.rules({"name": "terms", "file": "terms.csv", "strategy": "circular"})
        self.assertNotIn("feeder-lint.name-format", rules)
        self.assertNotIn("feeder-lint.file-name", rules)

    def test_non_kebab_name_blocks(self) -> None:
        rules = self.rules({"name": "Terms", "file": "Terms.csv", "strategy": "circular"})
        self.assertIn("feeder-lint.name-format", rules)

    def test_file_must_match_feeder_name(self) -> None:
        rules = self.rules({"name": "terms", "file": "search-terms.csv", "strategy": "circular"})
        self.assertIn("feeder-lint.file-name", rules)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python tools/scenario_lint/test_scenario_lint.py`
Expected: FAIL — `'feeder-lint.name-format' not found`

- [ ] **Step 3: Implement**

В `lint_scenario`, сразу после строки `feeders = data.get("feeders") ...` (до `resolve_feeders`):

```python
    for index, feeder in enumerate(feeders):
        if not isinstance(feeder, dict):
            continue
        feeder_name = feeder.get("name")
        feeder_path = f"$.scenario.data.feeders[{index}]"
        if not isinstance(feeder_name, str) or not POPULATION_NAME_RE.fullmatch(feeder_name):
            add(
                findings,
                "feeder-lint.name-format",
                BLOCKING,
                f"{feeder_path}.name",
                "feeder name must be kebab-case (a short plural noun, e.g. users, terms)",
            )
        elif feeder.get("file") != f"{feeder_name}.csv":
            add(
                findings,
                "feeder-lint.file-name",
                BLOCKING,
                f"{feeder_path}.file",
                f"feeder file must be named '{feeder_name}.csv' and live next to the scenario",
            )
```

Примечание: `POPULATION_NAME_RE` объявлен выше в этом же файле (строка ~132) — определение `lint_scenario` находится ниже, форвард-ссылки не нужны.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python tools/scenario_lint/test_scenario_lint.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/scenario_lint/scenario_lint.py tools/scenario_lint/test_scenario_lint.py
git commit -m "feat: lint feeder naming (kebab-case name, file = <name>.csv)"
```

---

### Task 5: Lint — сквозная нумерация NN транзакций

**Files:**
- Modify: `tools/scenario_lint/scenario_lint.py` (`lint_transactions`)
- Test: `tools/scenario_lint/test_scenario_lint.py`

- [ ] **Step 1: Поправить фикстуру `populations_document()`** — сейчас обе популяции начинаются с `01`, по новому правилу это дубль. В `populations_document()` заменить транзакцию фоновой популяции:

```python
                            "transaction": "03 bg.open - Bg open",
```

(`03`, а не `02`, потому что `test_same_population_variable_is_fine` добавляет шаг `02 demo.use-token`.)

- [ ] **Step 2: Write the failing test**

```python
class TransactionNumberingLintTest(unittest.TestCase):
    def test_duplicate_number_across_populations_blocks(self) -> None:
        document = populations_document()
        document["scenario"]["populations"][1]["steps"][0]["transaction"] = (
            "01 bg.open - Bg open"
        )
        rules = [f.rule for f in scenario_lint.lint_document(document)]
        self.assertIn("transaction-lint.duplicate-number", rules)

    def test_through_numbering_passes(self) -> None:
        rules = [f.rule for f in scenario_lint.lint_document(populations_document())]
        self.assertNotIn("transaction-lint.duplicate-number", rules)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python tools/scenario_lint/test_scenario_lint.py`
Expected: FAIL — `'transaction-lint.duplicate-number' not found`

- [ ] **Step 4: Implement**

В `lint_transactions` добавить словарь рядом с `seen` и проверку внутри цикла (после блока `transaction-lint.format`):

```python
    seen: dict[str, str] = {}
    seen_numbers: dict[str, str] = {}
```

```python
        number_prefix = transaction[:2]
        if number_prefix.isdigit():
            if number_prefix in seen_numbers:
                add(
                    findings,
                    "transaction-lint.duplicate-number",
                    BLOCKING,
                    path,
                    f"transaction number '{number_prefix}' is reused (first seen at "
                    f"{seen_numbers[number_prefix]}); numbering is through the whole simulation",
                )
            else:
                seen_numbers[number_prefix] = path
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python tools/scenario_lint/test_scenario_lint.py`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tools/scenario_lint/scenario_lint.py tools/scenario_lint/test_scenario_lint.py
git commit -m "feat: lint through-numbering of transaction NN across the simulation"
```

---

### Task 6: Lint — layout-проверки и уникальность `(system, number)`

Layout-проверки срабатывают ТОЛЬКО для файлов с каноническим именем `scenario.yaml` — ad-hoc файлы (`e2e/checkout-mix.yaml`) продолжают линтоваться без них.

**Files:**
- Modify: `tools/scenario_lint/scenario_lint.py` (новая функция `lint_layout`, параметр в `lint_with_waivers`, вызов в `main`)
- Test: `tools/scenario_lint/test_scenario_lint.py`

- [ ] **Step 1: Write the failing tests**

```python
class LayoutLintTest(unittest.TestCase):
    def make_doc(self, system: str = "SHOP", number: int = 1, scenario_id: str = "demo") -> dict:
        document = minimal_document(http_step("GET"))
        document["scenario"]["id"] = scenario_id
        document["scenario"]["system"] = system
        document["scenario"]["number"] = number
        return document

    def write_scenario(self, root: Path, system_dir: str, folder: str, document: dict) -> Path:
        directory = root / system_dir / folder
        directory.mkdir(parents=True)
        path = directory / "scenario.yaml"
        path.write_text(json.dumps(document), encoding="utf-8")  # YAML is a JSON superset
        return path

    def rules(self, document: dict, path: Path) -> list[str]:
        return [f.rule for f in scenario_lint.lint_layout(document, path)]

    def test_canonical_layout_passes(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_scenario(Path(tmp), "SHOP", "demo-001", self.make_doc())
            self.assertEqual(self.rules(self.make_doc(), path), [])

    def test_wrong_folder_name_blocks(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_scenario(Path(tmp), "SHOP", "demo-1", self.make_doc())
            self.assertIn("layout-lint.folder-name", self.rules(self.make_doc(), path))

    def test_wrong_system_dir_blocks(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_scenario(Path(tmp), "CRM", "demo-001", self.make_doc())
            self.assertIn("layout-lint.system-folder", self.rules(self.make_doc(), path))

    def test_duplicate_number_in_system_blocks(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self.write_scenario(
                Path(tmp), "SHOP", "other-001", self.make_doc(scenario_id="other")
            )
            path = self.write_scenario(Path(tmp), "SHOP", "demo-001", self.make_doc())
            self.assertIn("layout-lint.duplicate-number", self.rules(self.make_doc(), path))

    def test_non_canonical_filename_skips_layout(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "whatever.yaml"
            path.write_text(json.dumps(self.make_doc()), encoding="utf-8")
            self.assertEqual(self.rules(self.make_doc(), path), [])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python tools/scenario_lint/test_scenario_lint.py`
Expected: ERROR — `module 'scenario_lint' has no attribute 'lint_layout'`

- [ ] **Step 3: Implement**

В `tools/scenario_lint/scenario_lint.py` после `lint_secrets` добавить (импорт `script_number` добавить в блок `from _shared.common import`):

```python
def lint_layout(document: Any, scenario_path: Path) -> list[Finding]:
    """Layout rules for canonical scenario.yaml files: folder names and number uniqueness."""
    findings: list[Finding] = []
    if scenario_path.name != "scenario.yaml":
        return findings
    scenario = document.get("scenario", {}) if isinstance(document, dict) else {}
    scenario_id = scenario.get("id")
    system = scenario.get("system")
    number = scenario.get("number")
    if (
        not isinstance(scenario_id, str)
        or not isinstance(system, str)
        or isinstance(number, bool)
        or not isinstance(number, int)
        or number < 1
    ):
        return findings  # field-level problems are reported by lint_scenario
    folder = scenario_path.resolve().parent
    expected_folder = f"{scenario_id}-{script_number(number)}"
    if folder.name != expected_folder:
        add(
            findings,
            "layout-lint.folder-name",
            BLOCKING,
            "$.scenario",
            f"scenario folder must be named '{expected_folder}', found '{folder.name}'",
        )
    system_dir = folder.parent
    if system_dir.name != system:
        add(
            findings,
            "layout-lint.system-folder",
            BLOCKING,
            "$.scenario.system",
            f"scenario must live under a '{system}' system folder, found '{system_dir.name}'",
        )
        return findings
    scenarios_root = system_dir.parent
    for other in sorted(scenarios_root.glob("*/*/scenario.yaml")):
        if other.resolve() == scenario_path.resolve():
            continue
        try:
            other_scenario = load_yaml(other).get("scenario", {})
        except Exception:
            continue  # unreadable siblings are their own lint problem
        if other_scenario.get("system") == system and other_scenario.get("number") == number:
            add(
                findings,
                "layout-lint.duplicate-number",
                BLOCKING,
                "$.scenario.number",
                f"script number {number} in system '{system}' is already used by "
                f"{other.as_posix()}",
            )
    return findings
```

Интеграция: `lint_with_waivers` получает параметр и включает layout-находки до применения вэйверов —

```python
def lint_with_waivers(
    document: Any,
    base_dir: Path | None = None,
    today: date | None = None,
    scenario_path: Path | None = None,
) -> LintResult:
    today = today or datetime.now(UTC).date()
    findings = lint_document(document, base_dir)
    if scenario_path is not None:
        findings.extend(lint_layout(document, scenario_path))
```

В `main()` строку вызова заменить на:

```python
        result = lint_with_waivers(document, args.scenario.parent, scenario_path=args.scenario)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python tools/scenario_lint/test_scenario_lint.py`
Expected: PASS (InvalidFixturesTest не затронут: фикстуры лежат в `invalid/*.yaml`, не `scenario.yaml`)

- [ ] **Step 5: Commit**

```bash
git add tools/scenario_lint/scenario_lint.py tools/scenario_lint/test_scenario_lint.py
git commit -m "feat: lint canonical scenarios/<SYSTEM>/<id>-<NNN>/ layout and number uniqueness"
```

---

### Task 7: Генератор — имя класса = скрипт-реф

**Files:**
- Modify: `tools/gatling_generator/gatling_generator.py` (`render_simulation:529-533`, импорты)
- Test: `tools/gatling_generator/test_gatling_generator.py`

- [ ] **Step 1: Обновить фикстуру** — в `minimal_scenario()` (~строка 18) после `"id": "demo-flow",` добавить:

```python
        "system": "DEMO",
        "number": 7,
```

- [ ] **Step 2: Write the failing tests**

```python
class ClassNamingTest(unittest.TestCase):
    def test_class_name_is_script_ref(self) -> None:
        class_name, content = gatling_generator.render_simulation(minimal_scenario())
        self.assertEqual(class_name, "DEMO_DemoFlow_007")
        self.assertIn("public class DEMO_DemoFlow_007 extends Simulation {", content)

    def test_missing_system_is_rejected(self) -> None:
        document = minimal_scenario()
        del document["scenario"]["system"]
        with self.assertRaisesRegex(ValueError, "scenario.system"):
            gatling_generator.render_simulation(document)

    def test_bad_number_is_rejected(self) -> None:
        document = minimal_scenario(number=0)
        with self.assertRaisesRegex(ValueError, "scenario.number"):
            gatling_generator.render_simulation(document)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python tools/gatling_generator/test_gatling_generator.py`
Expected: FAIL — `'DemoFlowSimulation' != 'DEMO_DemoFlow_007'`

- [ ] **Step 4: Implement**

1. Импорт: в блок `from _shared.common import` добавить `SYSTEM_RE, script_ref,` (импорт `pascal_case` оставить — используется нигде больше? проверить: после правки `pascal_case` в генераторе не используется — удалить из импорта).
2. После `validate_population_name` добавить:

```python
def validate_system(system: Any) -> str:
    if not isinstance(system, str) or not SYSTEM_RE.fullmatch(system):
        raise ValueError("scenario.system must match ^[A-Z][A-Z0-9]{1,9}$ (e.g. SHOP)")
    return system


def validate_number(number: Any) -> int:
    if isinstance(number, bool) or not isinstance(number, int) or number < 1:
        raise ValueError("scenario.number must be a positive integer")
    return number
```

3. В `render_simulation` заменить строку `class_name = f"{pascal_case(scenario_id)}Simulation"` на:

```python
    class_name = script_ref(
        validate_system(scenario.get("system")),
        scenario_id,
        validate_number(scenario.get("number")),
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python tools/gatling_generator/test_gatling_generator.py`
Expected: PASS (BootstrapTest сравнивает только pom-ы — не затронут)

- [ ] **Step 6: Commit**

```bash
git add tools/gatling_generator/gatling_generator.py tools/gatling_generator/test_gatling_generator.py
git commit -m "feat: name generated simulation class by the script ref mask"
```

---

### Task 8: Рендерер — строка «Скрипт», `--stdout`, дефолтный `passport.md`

**Files:**
- Modify: `tools/scenario_renderer/scenario_renderer.py` (`render_markdown:310-320`, `main:384-408`, импорты)
- Modify: `tools/quality_gate/quality_gate.py` (`run_renderer_check:376-384` — только добавить `--stdout` в вызов рендерера, иначе gate-тест красный до Task 9)
- Test: `tools/scenario_renderer/test_scenario_renderer.py`
- Regenerate: `examples/generated/docs/login-and-search.md`, `examples/generated/docs/checkout-mix.md` (чтобы gate-тест на golden-доки остался зелёным до миграции)

- [ ] **Step 1: Write the failing tests**

```python
class ScriptRefLineTest(unittest.TestCase):
    def test_passport_shows_script_ref(self) -> None:
        document = {
            "scenario": {
                "id": "demo",
                "title": "Demo",
                "system": "SHOP",
                "number": 1,
                "source": {"type": "manual", "ref": "t"},
                "sut": {"base_url": "${BASE_URL}"},
                "steps": [
                    {
                        "name": "open",
                        "title": "Open",
                        "transaction": "01 demo.open - Open",
                        "protocol": "http",
                        "request": {"method": "GET", "path": "/"},
                        "checks": [{"status": 200}],
                    }
                ],
                "load": {"model": "closed", "profile": "constant", "users": 1,
                         "duration_seconds": 60},
                "assertions": [
                    {"name": "a", "metric": "global.responseTime.p95", "op": "<", "value": 1}
                ],
            }
        }
        content = scenario_renderer.render_markdown(document, "demo.yaml", "abc")
        self.assertIn("- **Скрипт:** `SHOP_Demo_001`", content)

    def test_missing_fields_render_question_mark(self) -> None:
        document = scenario_renderer.load_yaml(GOLDEN_SCENARIO)
        document["scenario"].pop("system", None)
        content = scenario_renderer.render_markdown(document, "x.yaml", "abc")
        self.assertIn("- **Скрипт:** `?`", content)


class DefaultOutputTest(unittest.TestCase):
    def test_default_writes_passport_next_to_scenario(self) -> None:
        import shutil
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            scenario = Path(tmp) / "scenario.yaml"
            shutil.copyfile(GOLDEN_SCENARIO, scenario)
            code = scenario_renderer.main([str(scenario)])
            self.assertEqual(code, 0)
            self.assertTrue((Path(tmp) / "passport.md").is_file())

    def test_stdout_flag_prints_instead_of_writing(self) -> None:
        import io
        import shutil
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            scenario = Path(tmp) / "scenario.yaml"
            shutil.copyfile(GOLDEN_SCENARIO, scenario)
            stdout = io.StringIO()
            with patch.object(sys, "stdout", stdout):
                code = scenario_renderer.main([str(scenario), "--stdout"])
            self.assertEqual(code, 0)
            self.assertIn("## Паспорт", stdout.getvalue())
            self.assertFalse((Path(tmp) / "passport.md").exists())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python tools/scenario_renderer/test_scenario_renderer.py`
Expected: FAIL — нет строки `Скрипт`, `--stdout` не распознан

- [ ] **Step 3: Implement**

1. Импорт: добавить `script_ref` в `from _shared.common import ...`.
2. Перед `render_markdown` добавить:

```python
def script_ref_display(scenario: dict[str, Any]) -> str:
    system = scenario.get("system")
    number = scenario.get("number")
    scenario_id = scenario.get("id")
    if (
        isinstance(system, str)
        and isinstance(scenario_id, str)
        and isinstance(number, int)
        and not isinstance(number, bool)
        and number >= 1
    ):
        return script_ref(system, scenario_id, number)
    return "?"
```

3. В `render_markdown` после строки `f"- **ID:** ..."` вставить:

```python
        f"- **Скрипт:** `{script_ref_display(scenario)}`",
```

4. В `main()`:

```python
    parser.add_argument(
        "--output",
        type=Path,
        help="output .md path (default: passport.md next to the scenario)",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="print Markdown to stdout instead of writing a file",
    )
```

и блок вывода:

```python
    if args.stdout:
        print(content, end="")
    else:
        output = args.output if args.output else args.scenario.parent / "passport.md"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content, encoding="utf-8", newline="\n")
        print(output.as_posix())
    return 0
```

5. В `tools/quality_gate/quality_gate.py::run_renderer_check` добавить `--stdout` в обе команды,
   иначе gate начнёт писать `passport.md` рядом с golden-сценарием и сравнивать пути вместо контента:

```python
    command = command_text(
        [
            sys.executable,
            "tools/scenario_renderer/scenario_renderer.py",
            rel_path(ctx.scenario, ctx.repo_root),
            "--stdout",
        ]
    )

    args = [sys.executable, str(script), str(ctx.scenario), "--stdout"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python tools/scenario_renderer/test_scenario_renderer.py`
Expected: PASS

- [ ] **Step 5: Перегенерировать закоммиченные golden-доки** (в них появится строка `Скрипт: ?` — это временно, до миграции в Task 10):

```powershell
python tools/scenario_renderer/scenario_renderer.py examples/scenarios/login-and-search.yaml --output examples/generated/docs/login-and-search.md
python tools/scenario_renderer/scenario_renderer.py examples/scenarios/checkout-mix.yaml --output examples/generated/docs/checkout-mix.md
```

- [ ] **Step 6: Run the full gate test to confirm goldens stay in sync**

Run: `python tools/quality_gate/test_quality_gate.py`
Expected: PASS (тест `test_fresh_docs_pass` сравнивает свежий рендер с только что перегенерированной докой)

- [ ] **Step 7: Commit**

```bash
git add tools/scenario_renderer tools/quality_gate/quality_gate.py examples/generated/docs
git commit -m "feat: renderer writes co-located passport.md by default and shows the script ref"
```

---

### Task 9: Quality gate — ко-локация доки и смоук по скрипт-рефу

**Files:**
- Modify: `tools/quality_gate/quality_gate.py` (`GateContext:63`, `run_renderer_check:371-446`, `run_smoke_check:615-635`, `parse_args:837-842`, `main:868`, импорты)
- Test: `tools/quality_gate/test_quality_gate.py`

- [ ] **Step 1: Write the failing tests** — переписать golden-зависимые тесты на tmp-фикстуры. В начало `test_quality_gate.py` после `REPO_ROOT` добавить:

```python
SCENARIO_YAML = """scenario:
  id: demo-flow
  title: Demo flow
  system: SHOP
  number: 7
  source:
    type: manual
    ref: test
  sut:
    base_url: "${BASE_URL}"
  steps:
    - name: open-home
      title: Open home
      transaction: "01 demo.open-home - Open home"
      protocol: http
      request:
        method: GET
        path: /
      checks:
        - status: 200
  load:
    model: closed
    profile: constant
    users: 1
    duration_seconds: 60
  assertions:
    - name: p95
      metric: global.responseTime.p95
      op: "<"
      value: 800
"""


def write_demo_scenario(tmp: Path) -> Path:
    scenario = tmp / "demo.yaml"
    scenario.write_text(SCENARIO_YAML, encoding="utf-8")
    return scenario
```

`make_ctx` заменить на:

```python
def make_ctx(
    tmp: Path, scenario: Path | None = None, docs_dir: Path | None = None
) -> quality_gate.GateContext:
    return quality_gate.GateContext(
        repo_root=REPO_ROOT,
        scenario=scenario or REPO_ROOT / "examples" / "scenarios" / "login-and-search.yaml",
        project=REPO_ROOT / "examples" / "generated" / "java",
        schema=REPO_ROOT / "schemas" / "scenario.schema.json",
        profile="mvp",
        json_report=tmp / "report.json",
        md_report=tmp / "report.md",
        docs_dir=docs_dir,
    )
```

`RendererCheckTest` заменить целиком:

```python
class RendererCheckTest(unittest.TestCase):
    def test_fresh_colocated_passport_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scenario = write_demo_scenario(Path(tmp))
            subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "tools" / "scenario_renderer" / "scenario_renderer.py"),
                    str(scenario),
                ],
                check=True,
                cwd=REPO_ROOT,
            )
            ctx = make_ctx(Path(tmp), scenario=scenario)
            quality_gate.run_renderer_check(ctx)
            self.assertEqual(ctx.checks[-1].status, quality_gate.PASSED)
            self.assertEqual(ctx.blocking, [])

    def test_stale_colocated_passport_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scenario = write_demo_scenario(Path(tmp))
            (Path(tmp) / "passport.md").write_text("outdated\n", encoding="utf-8")
            ctx = make_ctx(Path(tmp), scenario=scenario)
            quality_gate.run_renderer_check(ctx)
            self.assertEqual(ctx.checks[-1].status, quality_gate.BLOCKED)
            self.assertEqual(ctx.blocking[-1].rule, "renderer.docs-stale")

    def test_docs_dir_override_keeps_id_named_doc(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scenario = write_demo_scenario(Path(tmp))
            docs = Path(tmp) / "docs"
            docs.mkdir()
            (docs / "demo.md").write_text("outdated\n", encoding="utf-8")
            ctx = make_ctx(Path(tmp), scenario=scenario, docs_dir=docs)
            quality_gate.run_renderer_check(ctx)
            self.assertEqual(ctx.blocking[-1].rule, "renderer.docs-stale")
            self.assertIn("docs", ctx.blocking[-1].artifact)
```

В `SmokeCheckTest.test_smoke_runs_simulation_class` использовать tmp-сценарий и новый класс:

```python
    def test_smoke_runs_simulation_class(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scenario = write_demo_scenario(Path(tmp))
            ctx = make_ctx(Path(tmp), scenario=scenario)
            completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            with patch.object(
                quality_gate, "resolve_maven_executable", return_value="mvn"
            ), patch.object(quality_gate, "run_command", return_value=completed) as run:
                quality_gate.run_smoke_check(ctx, None)
            argv = run.call_args.args[0]
            self.assertIn("gatling:test", argv)
            self.assertIn("-Dgatling.simulationClass=SHOP_DemoFlow_007", argv)
            self.assertEqual(ctx.checks[-1].status, quality_gate.PASSED)
```

В `test_smoke_failure_blocks` тоже заменить создание контекста на `scenario = write_demo_scenario(Path(tmp)); ctx = make_ctx(Path(tmp), scenario=scenario)`. В `SkipLateChecksTest` оба вызова `make_ctx(Path(tmp), REPO_ROOT / ...)` заменить на `make_ctx(Path(tmp))`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python tools/quality_gate/test_quality_gate.py`
Expected: FAIL — renderer ищет `<stem>.md` в `examples/generated/docs`, смоук строит `DemoFlowSimulation`

- [ ] **Step 3: Implement**

1. `GateContext`: `docs_dir: Path | None = None`.
2. Импорт: заменить `pascal_case` на `script_ref` в `from _shared.common import ...`.
3. `run_renderer_check`: заменить вычисление `committed` (флаг `--stdout` в командах уже добавлен в Task 8):

```python
    if ctx.docs_dir is not None:
        committed = ctx.docs_dir / f"{ctx.scenario.stem}.md"
    else:
        committed = ctx.scenario.parent / "passport.md"
```

4. `run_smoke_check`: заменить блок чтения id (строки ~620-635) на:

```python
    try:
        document = load_yaml(ctx.scenario)
        scenario_data = document["scenario"]
        simulation_class = script_ref(
            str(scenario_data["system"]),
            str(scenario_data["id"]),
            int(scenario_data["number"]),
        )
    except Exception as exc:
        ctx.blocking.append(
            Finding(
                check="smoke",
                rule="smoke.scenario-unreadable",
                artifact=rel_path(ctx.scenario, ctx.repo_root),
                message=str(exc),
            )
        )
        ctx.checks.append(CheckResult("smoke", BLOCKED, artifacts))
        return

    command = f"mvn -q gatling:test -Dgatling.simulationClass={simulation_class}"
```

5. `parse_args`: `--docs-dir` → `default=None`, help: `"directory with committed rendered scenario docs (default: passport.md next to the scenario)"`.
6. `main()`: `docs_dir = resolve_arg_path(args.docs_dir, repo_root) if args.docs_dir else None`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python tools/quality_gate/test_quality_gate.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/quality_gate
git commit -m "feat: gate checks co-located passport.md and smokes by script ref"
```

---

### Task 10: Миграция golden-примеров в новую структуру

**Files:**
- Move+Modify: `examples/scenarios/checkout-mix.yaml` → `examples/scenarios/SHOP/checkout-mix-001/scenario.yaml`
- Move: `examples/scenarios/products.csv` → `examples/scenarios/SHOP/checkout-mix-001/terms.csv`
- Move: `examples/scenarios/login-and-search.yaml` → `examples/scenarios/SHOP/login-and-search-002/scenario.yaml`
- Move: `examples/scenarios/users.csv` → `examples/scenarios/SHOP/login-and-search-002/users.csv`
- Move: `examples/mock/checkout-mix.routes.json` → `examples/scenarios/SHOP/checkout-mix-001/mock.routes.json`; `examples/mock/bodies/*` → `examples/scenarios/SHOP/checkout-mix-001/bodies/*`
- Delete: `examples/generated/docs/` (доки переезжают в `passport.md`)
- Regenerate: `examples/generated/java/`, `examples/generated/checkout-java/`
- Modify: `tools/scenario_renderer/test_scenario_renderer.py:13`, `tools/quality_gate/test_quality_gate.py` (MockLifecycleTest), `tools/hook_router/hooks.json:3-4`, `tools/hook_router/test_configs/prompt_hooks.json:3-4`
- Не трогать: `examples/scenarios/invalid/` (фикстуры лжесценариев остаются на месте; файлы не называются `scenario.yaml`, layout-правила на них не действуют)

- [ ] **Step 1: Переместить файлы** (git mv не создаёт каталоги — сначала создать их):

```powershell
New-Item -ItemType Directory -Force examples/scenarios/SHOP/checkout-mix-001/bodies
New-Item -ItemType Directory -Force examples/scenarios/SHOP/login-and-search-002
git mv examples/scenarios/checkout-mix.yaml examples/scenarios/SHOP/checkout-mix-001/scenario.yaml
git mv examples/scenarios/products.csv examples/scenarios/SHOP/checkout-mix-001/terms.csv
git mv examples/mock/checkout-mix.routes.json examples/scenarios/SHOP/checkout-mix-001/mock.routes.json
git mv examples/mock/bodies/products.json examples/scenarios/SHOP/checkout-mix-001/bodies/products.json
git mv examples/mock/bodies/graphql-price.json examples/scenarios/SHOP/checkout-mix-001/bodies/graphql-price.json
git mv examples/mock/bodies/checkout-ok.json examples/scenarios/SHOP/checkout-mix-001/bodies/checkout-ok.json
git mv examples/mock/bodies/search.json examples/scenarios/SHOP/checkout-mix-001/bodies/search.json
git mv examples/scenarios/login-and-search.yaml examples/scenarios/SHOP/login-and-search-002/scenario.yaml
git mv examples/scenarios/users.csv examples/scenarios/SHOP/login-and-search-002/users.csv
git rm -r examples/generated/docs
```

(`mock.routes.json` ссылается на `bodies/...` относительно себя — относительные пути сохраняются.)

- [ ] **Step 2: Обновить содержимое `examples/scenarios/SHOP/checkout-mix-001/scenario.yaml`**

Три правки: добавить `system`/`number` после `title`, переименовать фидер, перенумеровать транзакцию фоновой популяции:

```yaml
scenario:
  id: checkout-mix
  title: Checkout with background search
  system: SHOP
  number: 1
```

```yaml
  data:
    feeders:
      - name: terms
        file: terms.csv
        strategy: circular
```

```yaml
        - name: search-products
          title: Search products
          transaction: "04 search.query - Search products"
```

Остальное содержимое без изменений.

- [ ] **Step 3: Обновить `examples/scenarios/SHOP/login-and-search-002/scenario.yaml`** — добавить после `title`:

```yaml
  system: SHOP
  number: 2
```

(Фидер `users`/`users.csv` и транзакции `01`/`02` уже соответствуют правилам.)

- [ ] **Step 4: Прогнать lint по обоим сценариям**

```powershell
python tools/scenario_lint/scenario_lint.py examples/scenarios/SHOP/checkout-mix-001/scenario.yaml --format text
python tools/scenario_lint/scenario_lint.py examples/scenarios/SHOP/login-and-search-002/scenario.yaml --format text
```

Expected: оба `passed` (layout-правила и уникальность (SHOP,1)/(SHOP,2) включаются — файлы называются `scenario.yaml`)

- [ ] **Step 5: Перегенерировать golden Java-проекты**

```powershell
git rm examples/generated/java/src/test/java/LoginAndSearchSimulation.java
git rm examples/generated/checkout-java/src/test/java/CheckoutMixSimulation.java
git rm examples/generated/checkout-java/src/test/resources/products.csv
python tools/gatling_generator/gatling_generator.py examples/scenarios/SHOP/login-and-search-002/scenario.yaml examples/generated/java --format json
python tools/gatling_generator/gatling_generator.py examples/scenarios/SHOP/checkout-mix-001/scenario.yaml examples/generated/checkout-java --format json
```

Expected: созданы `examples/generated/java/src/test/java/SHOP_LoginAndSearch_002.java` и `examples/generated/checkout-java/src/test/java/SHOP_CheckoutMix_001.java`, в ресурсы checkout-java скопирован `terms.csv`.

- [ ] **Step 6: Срендерить ко-локационные паспорта**

```powershell
python tools/scenario_renderer/scenario_renderer.py examples/scenarios/SHOP/checkout-mix-001/scenario.yaml
python tools/scenario_renderer/scenario_renderer.py examples/scenarios/SHOP/login-and-search-002/scenario.yaml
```

Expected: появились `passport.md` в обеих папках сценариев.

- [ ] **Step 7: Обновить пути в тестах и конфигах**

1. `tools/scenario_renderer/test_scenario_renderer.py:13`:

```python
GOLDEN_SCENARIO = (
    REPO_ROOT / "examples" / "scenarios" / "SHOP" / "login-and-search-002" / "scenario.yaml"
)
```

2. `tools/quality_gate/test_quality_gate.py` — `make_ctx` дефолтный scenario и `MockLifecycleTest`:

```python
        scenario=scenario or REPO_ROOT / "examples" / "scenarios" / "SHOP"
        / "login-and-search-002" / "scenario.yaml",
```

```python
        routes = (
            REPO_ROOT / "examples" / "scenarios" / "SHOP" / "checkout-mix-001"
            / "mock.routes.json"
        )
```

(в `test_start_mock_server_yields_reachable_base_url` убрать ставший невозможным `skipTest`-блок `if not routes.is_file()`).

3. `tools/hook_router/hooks.json` и `tools/hook_router/test_configs/prompt_hooks.json` — поле `scenario`:

```json
    "scenario": "examples/scenarios/SHOP/login-and-search-002/scenario.yaml",
```

(`project: examples/generated/java` не меняется; глобы `examples/scenarios/**/*.yaml` уже покрывают новую вложенность.)

- [ ] **Step 8: Прогнать quality gate по обоим golden (финальная сверка миграции)**

```powershell
python tools/quality_gate/quality_gate.py --scenario examples/scenarios/SHOP/login-and-search-002/scenario.yaml --project examples/generated/java
python tools/quality_gate/quality_gate.py --scenario examples/scenarios/SHOP/checkout-mix-001/scenario.yaml --project examples/generated/checkout-java --smoke --mock-routes examples/scenarios/SHOP/checkout-mix-001/mock.routes.json
python tools/quality_gate/quality_gate.py --scenario examples/scenarios/invalid/missing-check.yaml --project examples/generated/java
```

Expected: первые два `"status": "passed"`, третий `"status": "blocked"`.

- [ ] **Step 9: Прогнать все тест-сьюты**

```powershell
python tools/_shared/test_common.py; python tools/scenario_lint/test_scenario_lint.py; python tools/gatling_generator/test_gatling_generator.py; python tools/scenario_renderer/test_scenario_renderer.py; python tools/quality_gate/test_quality_gate.py; python tools/test_contract_coverage.py; python tools/hook_router/test_hook_router.py; python tools/mock_sut/test_mock_sut.py
```

Expected: все PASS.

- [ ] **Step 10: Commit**

```bash
git add -A examples tools/scenario_renderer/test_scenario_renderer.py tools/quality_gate/test_quality_gate.py tools/hook_router
git commit -m "feat: migrate golden examples to scenarios/<SYSTEM>/<id>-<NNN>/ layout"
```

---

### Task 11: Документация

**Files:**
- Modify: `docs/SCENARIO_FORMAT.md`
- Modify: `docs/GETTING_STARTED.md:74-121`
- Modify: `docs/QUALITY_GATE.md:67-68`
- Modify: `tools/scenario_lint/README.md`, `tools/gatling_generator/README.md`, `tools/scenario_renderer/README.md`, `tools/quality_gate/README.md`, `tools/mock_sut/README.md`

- [ ] **Step 1: `docs/SCENARIO_FORMAT.md`**

1. В Minimal Valid Scenario после `title:` добавить `system: SHOP` и `number: 1`; пути фидера привести к правилу (`file: users.csv`, имя `users` уже совпадает).
2. В таблицу Naming Rules добавить строки:

```markdown
| `scenario.system` | код системы, `^[A-Z][A-Z0-9]{1,9}$` | `SHOP` |
| `scenario.number` | целое ≥ 1, уникально в рамках системы | `1` |
| Скрипт-реф / Java-класс | `<SYSTEM>_<PascalCase(id)>_<NNN>` (порождается генератором) | `SHOP_CheckoutMix_001` |
| Feeder file | строго `<имя-фидера>.csv` рядом со scenario.yaml | `terms.csv` |
```

и заменить строку про Generated class (`PascalCase + Simulation`) на скрипт-реф.
3. После Naming Rules добавить раздел `## Folder Layout` со следующим содержанием (дерево оформить fenced-блоком):

> Канонический сценарий живёт в папке `scenarios/<SYSTEM>/<id>-<NNN>/`:
>
> ```
> scenarios/
>   SHOP/
>     checkout-mix-001/
>       scenario.yaml        # источник правды (фиксированное имя)
>       passport.md          # рендер-паспорт (генерируется, фиксированное имя)
>       terms.csv            # фидеры рядом со сценарием
>       mock.routes.json     # опционально: конфиг mock-SUT для smoke
> ```
>
> Для файлов с каноническим именем `scenario.yaml` lint дополнительно проверяет:
> имя папки `<id>-<NNN>`, имя папки системы `<SYSTEM>`, уникальность пары
> `(system, number)` по всему дереву. Файлы с другими именами (черновики)
> линтуются без layout-правил. Значения `system`/`id`/`number` задаёт
> пользователь — агент предлагает только заготовки с подтверждением.

4. В Blocking Validation Rules добавить пункты:

```markdown
- `scenario.system` соответствует `^[A-Z][A-Z0-9]{1,9}$`; `scenario.number` — целое ≥ 1.
- Имя фидера — kebab-case; файл фидера — строго `<имя>.csv`.
- Нумерация `NN` транзакций сквозная по всей симуляции (без повторов между популяциями).
```

- [ ] **Step 2: `docs/GETTING_STARTED.md`** — заменить все пути и имена:

- `examples/scenarios/checkout-mix.yaml` → `examples/scenarios/SHOP/checkout-mix-001/scenario.yaml`
- шаг рендера: команда без `--output` (пишет `passport.md` рядом), упоминание `examples/generated/docs/checkout-mix.md` → `examples/scenarios/SHOP/checkout-mix-001/passport.md`
- `--mock-routes examples/mock/checkout-mix.routes.json` → `--mock-routes examples/scenarios/SHOP/checkout-mix-001/mock.routes.json`
- упоминания класса `CheckoutMixSimulation` (если есть) → `SHOP_CheckoutMix_001`

- [ ] **Step 3: `docs/QUALITY_GATE.md:67-68`** — пример артефактов:

```json
    "examples/scenarios/SHOP/login-and-search-002/scenario.yaml",
    "examples/generated/java/src/test/java/SHOP_LoginAndSearch_002.java"
```

- [ ] **Step 4: README инструментов** — обновить пути примеров:

- `tools/scenario_lint/README.md:11-12` → `examples/scenarios/SHOP/login-and-search-002/scenario.yaml` (invalid-путь не меняется)
- `tools/gatling_generator/README.md:9` → новый путь сценария; упомянуть имя класса по маске
- `tools/scenario_renderer/README.md:13-14` → команда без `--output` + примечание про дефолтный `passport.md` и `--stdout`
- `tools/quality_gate/README.md:9,23,39,42` → новые пути; описание `--docs-dir`: «по умолчанию gate сверяет `passport.md` рядом со сценарием; `--docs-dir` — override для централизованных док»
- `tools/mock_sut/README.md:8` → `--routes examples/scenarios/SHOP/checkout-mix-001/mock.routes.json`

- [ ] **Step 5: Verify**

Run: `python tools/quality_gate/test_quality_gate.py` (smoke-проверка, что доки не сломали ничего исполняемого)
Expected: PASS. Глазами перечитать изменённые doc-файлы на согласованность путей.

- [ ] **Step 6: Commit**

```bash
git add docs tools/scenario_lint/README.md tools/gatling_generator/README.md tools/scenario_renderer/README.md tools/quality_gate/README.md tools/mock_sut/README.md
git commit -m "docs: naming mask, system/number and co-located layout"
```

---

### Task 12: Скиллы

**Files:**
- Modify: `skills/scenario-from-docs/SKILL.md`
- Modify: `skills/scenario-to-gatling/SKILL.md`
- Modify: `skills/quality-gate/SKILL.md`

- [ ] **Step 1: `skills/scenario-from-docs/SKILL.md`**

1. В чек-лист Extract entities (после строки про endpoints) добавить пункт:

```markdown
   - system code, scenario id, script number → ask the user; NEVER invent them.
     You may PROPOSE defaults (id from the requirements file name, the next free
     number from scanning `scenarios/<SYSTEM>/`) but only as a question to confirm.
```

2. Шаг 4 (Write the scenario) заменить на:

```markdown
4. **Write the scenario** to `scenarios/<SYSTEM>/<id>-<NNN>/scenario.yaml`
   (NNN = zero-padded number; feeders as `<feeder-name>.csv` in the same
   folder). Naming rules (lint enforces them): kebab-case ids/names,
   `system` matches `^[A-Z][A-Z0-9]{1,9}$`, transactions
   `<NN> <domain>.<action> - <Title>` with through-numbering across the whole
   simulation, unique `(system, number)` per repository.
```

3. Шаг 6 (Render for review):

```markdown
6. **Render for review:**
   `python tools/scenario_renderer/scenario_renderer.py <dir>/scenario.yaml`
   (writes `passport.md` next to the scenario). Show the rendered passport to
   the user together with the open questions list. Iterate until approval.
```

- [ ] **Step 2: `skills/scenario-to-gatling/SKILL.md`**

1. В Output и тексте процесса заменить `<ClassName>Simulation.java` на «класс по скрипт-рефу `<SYSTEM>_<PascalCaseId>_<NNN>.java` (например `SHOP_CheckoutMix_001.java`)».
2. В шаге smoke пример mock-роутов: `scenarios/<SYSTEM>/<id>-<NNN>/mock.routes.json`.
3. В шаге Render the reviewer doc: команда без `--output` (ко-локационный `passport.md`).

- [ ] **Step 3: `skills/quality-gate/SKILL.md`** — обновить пути примеров (строки 9, 15, 44, 55, 59, 63):

- `examples/scenarios/login-and-search.yaml` → `examples/scenarios/SHOP/login-and-search-002/scenario.yaml`
- `examples/scenarios/checkout-mix.yaml` → `examples/scenarios/SHOP/checkout-mix-001/scenario.yaml`
- `--mock-routes examples/mock/<id>.routes.json` → `--mock-routes scenarios/<SYSTEM>/<id>-<NNN>/mock.routes.json`
- строку 59 про `examples/generated/docs` → «committed `passport.md` рядом со сценарием (или `--docs-dir`) must match a fresh render»

- [ ] **Step 4: Commit**

```bash
git add skills
git commit -m "docs: align skills with naming mask and co-located layout"
```

---

### Task 13: Финальная верификация

- [ ] **Step 1: Все тест-сьюты**

```powershell
python tools/_shared/test_common.py; python tools/scenario_lint/test_scenario_lint.py; python tools/gatling_generator/test_gatling_generator.py; python tools/scenario_renderer/test_scenario_renderer.py; python tools/quality_gate/test_quality_gate.py; python tools/test_contract_coverage.py; python tools/hook_router/test_hook_router.py; python tools/mock_sut/test_mock_sut.py
```

Expected: 8/8 PASS.

- [ ] **Step 2: Gate по golden-примерам** (см. Task 10 Step 8 — повторить те же три команды)

Expected: `passed`, `passed`, `blocked`.

- [ ] **Step 3: Негативная проверка layout-правил вручную**

```powershell
Copy-Item examples/scenarios/SHOP/login-and-search-002/scenario.yaml -Destination examples/scenarios/SHOP/login-and-search-002/draft.yaml
python tools/scenario_lint/scenario_lint.py examples/scenarios/SHOP/login-and-search-002/draft.yaml --format text
Remove-Item examples/scenarios/SHOP/login-and-search-002/draft.yaml
```

Expected: `passed` (не-каноническое имя файла — layout-правила не применяются; это путь для черновиков).

- [ ] **Step 4: Чистота дерева и коммит-лог**

```powershell
git status --short
git log --oneline master..HEAD
```

Expected: рабочее дерево чистое (кроме нетрекаемых `e2e/`, отчётов gate), в логе ~12 коммитов задач.

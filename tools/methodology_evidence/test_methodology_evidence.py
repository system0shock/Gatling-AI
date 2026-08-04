#!/usr/bin/env python3
"""Evidence schema contract tests."""

from __future__ import annotations

import json
import importlib
import jsonschema
import subprocess
import sys
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

if __package__:
    from . import contracts
    from . import aggregate, reconcile
    from .fixtures import (
        backend_endpoint,
        confluence_doc,
        confluence_sla,
        empty_section_reviews,
        evidence_doc,
        evidence_file,
        manual_confirmation,
        openapi_endpoint,
        record,
        repo_doc,
        same_endpoint_from_backend,
        same_endpoint_from_openapi,
    )
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

    import aggregate
    import contracts
    import reconcile
    from fixtures import (
        backend_endpoint,
        confluence_doc,
        confluence_sla,
        empty_section_reviews,
        evidence_doc,
        evidence_file,
        manual_confirmation,
        openapi_endpoint,
        record,
        repo_doc,
        same_endpoint_from_backend,
        same_endpoint_from_openapi,
    )


class SectionReviewContractTest(unittest.TestCase):
    def test_loads_utf8_bom_written_by_windows_powershell_5_1(self) -> None:
        payload = {"version": 1, "reviews": {}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "section-reviews.json"
            path.write_text(json.dumps(payload), encoding="utf-8-sig")
            try:
                loaded = contracts.load_section_reviews(path)
            except json.JSONDecodeError as error:
                self.fail(f"BOM-prefixed section reviews must load: {error}")

        self.assertEqual(loaded, contracts.SectionReviewsDocument(reviews={}))

    def test_loads_named_review_with_approve_exclude_and_add(self) -> None:
        payload = {
            "version": 1,
            "reviews": {
                "Реестр тестируемых интерфейсов": {
                    "reviewed_by": "Иван Петров",
                    "approved": ["endpoint.orders.GET-/orders/{id}"],
                    "excluded": ["endpoint.legacy.GET-/v1/old"],
                    "added": [{
                        "entity_type": "endpoint",
                        "entity_id": "orders.GET-/v2/new",
                        "fields": {"identifier": "GET /v2/new", "type": "REST"},
                    }],
                }
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "section-reviews.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            loaded = contracts.load_section_reviews(path)
        review = loaded.reviews["Реестр тестируемых интерфейсов"]
        self.assertEqual(review.reviewed_by, "Иван Петров")
        self.assertEqual(review.approved, ("endpoint.orders.GET-/orders/{id}",))
        self.assertEqual(review.added[0].fields["type"], "REST")

    def test_rejects_review_for_strict_or_optional_section(self) -> None:
        payload = {
            "version": 1,
            "reviews": {
                "SLA, SLO и критерии приемки": {
                    "reviewed_by": "Иван Петров", "approved": [],
                    "excluded": [], "added": [],
                }
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "section-reviews.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(jsonschema.ValidationError):
                contracts.load_section_reviews(path)

    def test_rejects_unnamed_or_ambiguous_review_actions(self) -> None:
        payload = {
            "version": 1,
            "reviews": {
                "Модель нагрузки": {
                    "reviewed_by": "",
                    "approved": ["workload.checkout", "workload.checkout"],
                    "excluded": ["workload.checkout"],
                    "added": [],
                }
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "section-reviews.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises((jsonschema.ValidationError, ValueError)):
                contracts.load_section_reviews(path)

    def test_section_review_is_valid_evidence_provenance(self) -> None:
        source = contracts.SourceRef(
            source_type="section-review", ref="section-review:Иван Петров"
        )
        self.assertEqual(source.source_type, "section-review")


class EvidenceContractTest(unittest.TestCase):
    def test_package_fixture_import_does_not_replace_top_level_contracts_module(self) -> None:
        if not __package__:
            self.skipTest("package import check only applies under pytest collection")

        fixture_name = f"{__package__}.fixtures"
        missing = object()
        original_fixture = sys.modules.pop(fixture_name, missing)
        original_contracts = sys.modules.get("contracts", missing)
        sentinel = object()
        sys.modules["contracts"] = sentinel
        try:
            fixture_module = importlib.import_module(fixture_name)
            self.assertIs(sys.modules["contracts"], sentinel)
            self.assertIs(fixture_module.EvidenceDocument, contracts.EvidenceDocument)
        finally:
            sys.modules.pop(fixture_name, None)
            if original_fixture is not missing:
                sys.modules[fixture_name] = original_fixture
            if original_contracts is missing:
                sys.modules.pop("contracts", None)
            else:
                sys.modules["contracts"] = original_contracts

    def test_round_trip_preserves_exact_repository_provenance(self) -> None:
        record = contracts.EvidenceRecord(
            entity_type="endpoint",
            entity_id="orders.get-order",
            section="interfaces",
            field="method_path",
            statement="GET /orders/{id}",
            source=contracts.SourceRef(
                source_type="repository",
                module_id="orders-backend",
                ref="src/main/java/OrdersController.java:42",
                revision="abc123",
            ),
            confidence="confirmed",
            freshness="current",
        )
        doc = contracts.EvidenceDocument(
            producer="mnt-module-inspector",
            records=(record,),
            generated_at="2026-07-19T12:00:00+00:00",
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "evidence.json"
            contracts.write_evidence(doc, path)
            self.assertEqual(contracts.load_evidence(path), doc)

    def test_repository_source_requires_module_and_revision(self) -> None:
        with self.assertRaisesRegex(ValueError, "module_id.*revision"):
            contracts.SourceRef(source_type="repository", ref="x.py:1")

    def test_confluence_source_requires_page_id_and_version(self) -> None:
        with self.assertRaisesRegex(ValueError, "page_id.*page_version"):
            contracts.SourceRef(source_type="confluence", ref="https://wiki/page")

    def test_records_are_immutable_and_documents_preserve_tuple_records(self) -> None:
        source = contracts.SourceRef(source_type="manual-confirmation", ref="ticket:MNT-42")
        record = contracts.EvidenceRecord(
            entity_type="workload",
            entity_id="checkout",
            section="workload",
            field="rps",
            statement="250 rps",
            source=source,
            confidence="confirmed",
            freshness="current",
        )
        document = contracts.EvidenceDocument(producer="test", records=(record,))
        with self.assertRaises(FrozenInstanceError):
            record.statement = "300 rps"  # type: ignore[misc]
        self.assertIsInstance(document.records, tuple)

    def test_write_is_deterministic_utf8_sorted_json(self) -> None:
        record = contracts.EvidenceRecord(
            entity_type="endpoint",
            entity_id="orders.get-order",
            section="интерфейсы",
            field="method_path",
            statement="GET /orders/{id}",
            source=contracts.SourceRef(
                source_type="openapi",
                ref="openapi/orders.yaml:10",
                module_id="api-contracts",
                revision="abc123",
            ),
            confidence="confirmed",
            freshness="current",
        )
        document = contracts.EvidenceDocument(
            producer="test", records=(record,), generated_at="2026-07-19T12:00:00+00:00"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "evidence.json"
            contracts.write_evidence(document, path)
            first = path.read_bytes()
            contracts.write_evidence(document, path)
            self.assertEqual(path.read_bytes(), first)
            self.assertIn("интерфейсы".encode("utf-8"), first)
            self.assertEqual(json.loads(first), contracts.document_to_dict(document))

    def test_monitoring_source_preserves_ref_without_optional_observed_at(self) -> None:
        source = contracts.SourceRef(source_type="monitoring", ref="dashboard:checkout-latency")
        record = contracts.EvidenceRecord(
            entity_type="sla",
            entity_id="checkout",
            section="performance",
            field="threshold",
            statement="p95 <= 500ms",
            source=source,
            confidence="confirmed",
            freshness="current",
        )
        document = contracts.EvidenceDocument(
            producer="monitor", records=(record,), generated_at="2026-07-19T12:00:00+00:00"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "monitoring.json"
            contracts.write_evidence(document, path)
            self.assertEqual(contracts.load_evidence(path), document)
    def test_schema_accepts_monitoring_ref_without_observed_at(self) -> None:
        source = contracts.SourceRef(source_type="monitoring", ref="dashboard:checkout-latency")
        record = contracts.EvidenceRecord(
            entity_type="sla",
            entity_id="checkout",
            section="performance",
            field="threshold",
            statement="p95 <= 500ms",
            source=source,
            confidence="confirmed",
            freshness="current",
        )
        document = contracts.EvidenceDocument(
            producer="monitor", records=(record,), generated_at="2026-07-19T12:00:00+00:00"
        )
        data = contracts.document_to_dict(document)
        data["records"][0]["source"].pop("observed_at")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "monitoring-no-observation.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            self.assertEqual(contracts.load_evidence(path), document)
    def test_load_validates_schema_before_dataclass_construction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "invalid.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "producer": "test",
                        "generated_at": "2026-07-19T12:00:00+00:00",
                        "records": [{"entity_type": "endpoint"}],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(Exception, "entity_id"):
                contracts.load_evidence(path)

    def test_schema_rejects_null_repository_and_openapi_provenance(self) -> None:
        for source_type in ("repository", "openapi"):
            with self.subTest(source_type=source_type):
                document = self._document_with_source(
                    contracts.SourceRef(source_type=source_type, ref="src/App.java:10", module_id="orders", revision="abc")
                )
                data = contracts.document_to_dict(document)
                data["records"][0]["source"]["module_id"] = None
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / f"{source_type}-null.json"
                    path.write_text(json.dumps(data), encoding="utf-8")
                    with self.assertRaises(jsonschema.ValidationError):
                        contracts.load_evidence(path)

    def test_schema_rejects_null_confluence_provenance(self) -> None:
        document = self._document_with_source(
            contracts.SourceRef(source_type="confluence", ref="https://wiki/page", page_id="42", page_version=3)
        )
        for key in ("page_id", "page_version"):
            with self.subTest(key=key):
                data = contracts.document_to_dict(document)
                data["records"][0]["source"][key] = None
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / f"confluence-{key}-null.json"
                    path.write_text(json.dumps(data), encoding="utf-8")
                    with self.assertRaises(jsonschema.ValidationError):
                        contracts.load_evidence(path)

    def test_source_ref_rejects_wrong_repository_provenance_types(self) -> None:
        for values in ({"module_id": 42, "revision": "abc"}, {"module_id": "orders", "revision": True}):
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    contracts.SourceRef(source_type="repository", ref="src/App.java:10", **values)

    def test_source_ref_rejects_wrong_confluence_provenance_types(self) -> None:
        cases = (
            {"page_id": 42, "page_version": 3},
            {"page_id": "42", "page_version": True},
            {"page_id": "42", "page_version": "3"},
        )
        for values in cases:
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    contracts.SourceRef(source_type="confluence", ref="https://wiki/page", **values)

    def test_load_rejects_malformed_datetime_values(self) -> None:
        generated = self._document_with_source(contracts.SourceRef(source_type="manual-confirmation", ref="ticket:MNT-42"))
        generated_data = contracts.document_to_dict(generated)
        generated_data["generated_at"] = "not-a-date"
        observed = self._document_with_source(
            contracts.SourceRef(source_type="monitoring", ref="dashboard:checkout", observed_at="2026-07-19T12:00:00+00:00")
        )
        observed_data = contracts.document_to_dict(observed)
        observed_data["records"][0]["source"]["observed_at"] = "not-a-date"
        for name, data in (("generated", generated_data), ("observed", observed_data)):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / f"{name}-datetime.json"
                path.write_text(json.dumps(data), encoding="utf-8")
                with self.assertRaises(jsonschema.ValidationError):
                    contracts.load_evidence(path)

    def test_constructors_reject_malformed_datetime_values(self) -> None:
        with self.assertRaises(ValueError):
            contracts.EvidenceDocument(producer="test", records=(), generated_at="not-a-date")
        with self.assertRaises(ValueError):
            contracts.SourceRef(source_type="monitoring", ref="dashboard:checkout", observed_at="not-a-date")

    def test_write_rejects_malformed_generated_at_with_format_checker(self) -> None:
        document = self._document_with_source(contracts.SourceRef(source_type="manual-confirmation", ref="ticket:MNT-42"))
        object.__setattr__(document, "generated_at", "not-a-date")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(jsonschema.ValidationError):
                contracts.write_evidence(document, Path(tmp) / "invalid-write.json")

    def test_source_ref_rejects_wrong_inactive_optional_metadata_types(self) -> None:
        cases = (
            {"module_id": 42},
            {"revision": True},
            {"page_id": 42},
            {"page_version": True},
        )
        for values in cases:
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    contracts.SourceRef(source_type="manual-confirmation", ref="ticket:MNT-42", **values)

    def test_schema_rejects_wrong_inactive_optional_metadata_types(self) -> None:
        document = self._document_with_source(
            contracts.SourceRef(source_type="manual-confirmation", ref="ticket:MNT-42")
        )
        cases = (
            ("module_id", 42),
            ("revision", True),
            ("page_id", 42),
            ("page_version", True),
        )
        for key, value in cases:
            with self.subTest(key=key):
                data = contracts.document_to_dict(document)
                data["records"][0]["source"][key] = value
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / f"inactive-{key}.json"
                    path.write_text(json.dumps(data), encoding="utf-8")
                    with self.assertRaises(jsonschema.ValidationError):
                        contracts.load_evidence(path)

    def test_schema_and_load_reject_boolean_version(self) -> None:
        document = self._document_with_source(
            contracts.SourceRef(source_type="manual-confirmation", ref="ticket:MNT-42")
        )
        data = contracts.document_to_dict(document)
        data["version"] = True
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "boolean-version.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(jsonschema.ValidationError):
                contracts.load_evidence(path)

    def test_document_rejects_boolean_version(self) -> None:
        with self.assertRaises(ValueError):
            contracts.EvidenceDocument(producer="test", records=(), version=True)
    @staticmethod
    def _document_with_source(source: contracts.SourceRef) -> contracts.EvidenceDocument:
        return contracts.EvidenceDocument(
            producer="test",
            generated_at="2026-07-19T12:00:00+00:00",
            records=(
                contracts.EvidenceRecord(
                    entity_type="endpoint",
                    entity_id="orders.get-order",
                    section="interfaces",
                    field="method_path",
                    statement="GET /orders/{id}",
                    source=source,
                    confidence="confirmed",
                    freshness="current",
                ),
            ),
        )


class AggregateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_rejects_evidence_revision_different_from_snapshot(self) -> None:
        snapshot = {"modules": {"orders": {"commit": "abc", "dirty": False}}}
        evidence = evidence_file(self.root, module="orders", revision="def")

        with self.assertRaisesRegex(ValueError, "snapshot revision"):
            aggregate.aggregate_modules(snapshot, [evidence])

    def test_groups_identical_facts_but_keeps_all_sources(self) -> None:
        result = aggregate.aggregate_records(
            [same_endpoint_from_openapi(), same_endpoint_from_backend()]
        )

        item = result.entities[("endpoint", "orders.get-order")]
        self.assertEqual(len(item.candidates["method_path"]), 2)
        self.assertEqual(
            {record.source.source_type for record in item.candidates["method_path"]},
            {"openapi", "repository"},
        )

    def test_rejects_repository_evidence_from_an_unconfirmed_module(self) -> None:
        snapshot = {"modules": {"orders": {"commit": "abc", "dirty": False}}}
        evidence = evidence_file(self.root, module="unconfirmed", revision="abc")

        with self.assertRaisesRegex(ValueError, "snapshot revision"):
            aggregate.aggregate_modules(snapshot, [evidence])

    def test_writes_reconcilable_inventory_documents_from_aggregate(self) -> None:
        endpoint_records = [same_endpoint_from_openapi(), same_endpoint_from_backend()]
        integration_record = contracts.EvidenceRecord(
            entity_type="integration",
            entity_id="orders.inventory",
            section="integrations",
            field="target",
            statement="inventory-service",
            source=contracts.SourceRef(
                source_type="repository",
                ref="src/InventoryClient.java:20",
                module_id="orders-backend",
                revision="abc",
            ),
            confidence="confirmed",
            freshness="current",
        )
        source_path = self.root / "modules.json"
        contracts.write_evidence(evidence_doc(*endpoint_records, integration_record), source_path)
        snapshot = {
            "modules": {
                "api-contracts": {"commit": "abc", "dirty": False},
                "orders-backend": {"commit": "abc", "dirty": False},
            }
        }

        document = aggregate.aggregate_modules(snapshot, [source_path])
        outputs = aggregate.write_aggregation_outputs(document, self.root / "output")

        self.assertEqual(
            set(outputs),
            {"endpoint-inventory.json", "integration-inventory.json", "repository-evidence.json"},
        )
        self.assertEqual(len(contracts.load_evidence(outputs["endpoint-inventory.json"]).records), 2)
        self.assertEqual(len(contracts.load_evidence(outputs["integration-inventory.json"]).records), 1)
        self.assertEqual(contracts.load_evidence(outputs["repository-evidence.json"]), document)



class ReconcileTest(unittest.TestCase):
    def test_different_openapi_and_backend_paths_are_conflict(self) -> None:
        result = reconcile.reconcile_documents(
            evidence_doc(openapi_endpoint("GET /orders/{id}"), backend_endpoint("GET /order/{id}")),
            evidence_doc(), evidence_doc(), empty_section_reviews(),
        )
        self.assertEqual(result.entity("endpoint", "orders.get-order").status, "conflict")

    def test_confluence_only_sla_is_blocking_until_normative_confirmation(self) -> None:
        result = reconcile.reconcile_documents(evidence_doc(), evidence_doc(confluence_sla("p95 <= 500ms")), evidence_doc(), empty_section_reviews())
        self.assertIn("SLA requires normative confirmation", result.blocking_gaps[0].message)

    def test_manual_confirmation_resolves_only_matching_entity_and_field(self) -> None:
        confirmation = manual_confirmation("sla", "checkout", "threshold", "p95 <= 800ms")
        result = reconcile.reconcile_documents(repo_doc(), confluence_doc(), evidence_doc(confirmation), empty_section_reviews())
        self.assertEqual(result.entity("sla", "checkout").status, "confirmed")

    def test_manual_confirmation_does_not_resolve_another_field_conflict(self) -> None:
        repo = evidence_doc(
            contracts.EvidenceRecord("endpoint", "orders.get-order", "interfaces", "method_path", "GET /orders/{id}", contracts.SourceRef("repository", "src/Orders.java:10", module_id="orders", revision="abc"), "confirmed", "current"),
            contracts.EvidenceRecord("endpoint", "orders.get-order", "interfaces", "authentication", "oauth2", contracts.SourceRef("repository", "src/Orders.java:11", module_id="orders", revision="abc"), "confirmed", "current"),
        )
        docs = evidence_doc(contracts.EvidenceRecord("endpoint", "orders.get-order", "interfaces", "authentication", "api-key", contracts.SourceRef("confluence", "https://wiki/orders", page_id="42", page_version=3), "confirmed", "current"))
        confirmation = evidence_doc(manual_confirmation("endpoint", "orders.get-order", "method_path", "GET /orders/{id}"))
        result = reconcile.reconcile_documents(repo, docs, confirmation, empty_section_reviews())
        self.assertEqual(result.entity("endpoint", "orders.get-order").status, "conflict")

    def test_writes_deterministic_artifacts_even_with_blocking_gaps(self) -> None:
        result = reconcile.reconcile_documents(evidence_doc(), evidence_doc(confluence_sla("p95 <= 500ms")), evidence_doc(), empty_section_reviews())
        with tempfile.TemporaryDirectory() as tmp:
            paths = reconcile.write_reconciliation_outputs(result, Path(tmp))
            self.assertEqual(set(paths), {"resolved-evidence.json", "discrepancies.md", "methodology-gaps.md", "section-coverage.json"})
            self.assertTrue(all(path.is_file() for path in paths.values()))
            self.assertEqual(json.loads(paths["resolved-evidence.json"].read_text(encoding="utf-8"))["entities"][0]["status"], "docs_only")
            self.assertEqual(len(json.loads(paths["section-coverage.json"].read_text(encoding="utf-8"))["sections"]), 17)

    def test_reconcile_cli_writes_outputs_and_returns_two_for_blocking_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); repository = root / "repository.json"; confluence = root / "confluence.json"; confirmations = root / "confirmations.json"; reviews = root / "reviews.json"; output = root / "out"
            contracts.write_evidence(evidence_doc(), repository); contracts.write_evidence(evidence_doc(confluence_sla("p95 <= 500ms")), confluence); contracts.write_evidence(evidence_doc(), confirmations)
            reviews.write_text(json.dumps({"version": 1, "reviews": {}}), encoding="utf-8")
            completed = subprocess.run([sys.executable, "tools/methodology_evidence/methodology_evidence.py", "reconcile", "--repository", str(repository), "--confluence", str(confluence), "--confirmations", str(confirmations), "--reviews", str(reviews), "--out-dir", str(output)], cwd=Path(__file__).resolve().parents[2], text=True, capture_output=True, check=False)
            self.assertEqual(completed.returncode, 2, completed.stderr)
            self.assertEqual({path.name for path in output.iterdir()}, {"resolved-evidence.json", "discrepancies.md", "methodology-gaps.md", "section-coverage.json"})


    def test_resolved_output_contains_deterministic_structured_blocking_gaps(self) -> None:
        result = reconcile.reconcile_documents(evidence_doc(), evidence_doc(confluence_sla("p95 <= 500ms")), evidence_doc(), empty_section_reviews())
        with tempfile.TemporaryDirectory() as tmp:
            output = reconcile.write_reconciliation_outputs(result, Path(tmp))["resolved-evidence.json"]
            data = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(
            [gap["rule"] for gap in data["blocking_gaps"]],
            [
                "mandatory-entity-unconfirmed",
                "mandatory-section-missing",
                "mandatory-section-missing",
                "mandatory-section-missing",
                "mandatory-section-missing",
                "sla-normative-source",
            ],
        )
        self.assertEqual(data["blocking_gaps"][5], {"entity_id": "checkout", "entity_type": "sla", "message": "SLA requires normative confirmation", "rule": "sla-normative-source", "severity": "blocking"})

    def test_coverage_uses_exact_heading_keyed_contract_with_evidence_ids(self) -> None:
        result = reconcile.reconcile_documents(evidence_doc(same_endpoint_from_backend()), evidence_doc(), evidence_doc(), empty_section_reviews())
        with tempfile.TemporaryDirectory() as tmp:
            coverage = json.loads(reconcile.write_reconciliation_outputs(result, Path(tmp))["section-coverage.json"].read_text(encoding="utf-8"))
        expected_headings = {
            "\u041f\u0430\u0441\u043f\u043e\u0440\u0442 \u0434\u043e\u043a\u0443\u043c\u0435\u043d\u0442\u0430", "\u041d\u0430\u0437\u043d\u0430\u0447\u0435\u043d\u0438\u0435 \u0438 \u043e\u0431\u043b\u0430\u0441\u0442\u044c \u0442\u0435\u0441\u0442\u0438\u0440\u043e\u0432\u0430\u043d\u0438\u044f", "\u041e\u043f\u0438\u0441\u0430\u043d\u0438\u0435 \u0441\u0438\u0441\u0442\u0435\u043c\u044b \u0438 \u0444\u0443\u043d\u043a\u0446\u0438\u043e\u043d\u0430\u043b\u044c\u043d\u043e\u0441\u0442\u0438", "\u0410\u0440\u0445\u0438\u0442\u0435\u043a\u0442\u0443\u0440\u0430", "\u0420\u0435\u0435\u0441\u0442\u0440 \u0438\u043d\u0442\u0435\u0433\u0440\u0430\u0446\u0438\u0439", "\u0420\u0435\u0435\u0441\u0442\u0440 \u0442\u0435\u0441\u0442\u0438\u0440\u0443\u0435\u043c\u044b\u0445 \u0438\u043d\u0442\u0435\u0440\u0444\u0435\u0439\u0441\u043e\u0432", "\u041f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c\u0441\u043a\u0438\u0435 \u0438 \u0442\u0435\u0445\u043d\u0438\u0447\u0435\u0441\u043a\u0438\u0435 \u043f\u043e\u0442\u043e\u043a\u0438", "\u041c\u043e\u0434\u0435\u043b\u044c \u043d\u0430\u0433\u0440\u0443\u0437\u043a\u0438", "\u0412\u0438\u0434\u044b \u0442\u0435\u0441\u0442\u043e\u0432", "SLA, SLO \u0438 \u043a\u0440\u0438\u0442\u0435\u0440\u0438\u0438 \u043f\u0440\u0438\u0435\u043c\u043a\u0438", "\u0422\u0435\u0441\u0442\u043e\u0432\u044b\u0439 \u0441\u0442\u0435\u043d\u0434", "\u0422\u0440\u0435\u0431\u043e\u0432\u0430\u043d\u0438\u044f \u043a \u0442\u0435\u0441\u0442\u043e\u0432\u044b\u043c \u0434\u0430\u043d\u043d\u044b\u043c", "\u041d\u0430\u0431\u043b\u044e\u0434\u0430\u0435\u043c\u043e\u0441\u0442\u044c \u0438 \u0434\u0438\u0430\u0433\u043d\u043e\u0441\u0442\u0438\u043a\u0430", "\u041f\u043e\u0440\u044f\u0434\u043e\u043a \u043f\u0440\u043e\u0432\u0435\u0434\u0435\u043d\u0438\u044f \u0442\u0435\u0441\u0442\u043e\u0432", "\u0420\u0438\u0441\u043a\u0438, \u043e\u0433\u0440\u0430\u043d\u0438\u0447\u0435\u043d\u0438\u044f \u0438 \u0434\u043e\u043f\u0443\u0449\u0435\u043d\u0438\u044f", "\u0410\u0440\u0442\u0435\u0444\u0430\u043a\u0442\u044b \u0438 \u043e\u0442\u0447\u0435\u0442\u043d\u043e\u0441\u0442\u044c", "\u0410\u043a\u0442\u0443\u0430\u043b\u0438\u0437\u0430\u0446\u0438\u044f \u043c\u0435\u0442\u043e\u0434\u0438\u043a\u0438",
        }
        self.assertEqual(set(coverage), {"version", "sections", "evidence_ids"})
        self.assertEqual(set(coverage["sections"]), expected_headings)
        self.assertEqual(set(coverage["evidence_ids"]), expected_headings)
        self.assertTrue(set(coverage["sections"].values()) <= {"covered", "partial", "missing"})
        self.assertEqual(coverage["evidence_ids"]["\u0420\u0435\u0435\u0441\u0442\u0440 \u0442\u0435\u0441\u0442\u0438\u0440\u0443\u0435\u043c\u044b\u0445 \u0438\u043d\u0442\u0435\u0440\u0444\u0435\u0439\u0441\u043e\u0432"], ["endpoint.orders.get-order.method_path"])

    def test_sla_confirmation_for_owner_does_not_clear_threshold_gap(self) -> None:
        result = reconcile.reconcile_documents(repo_doc(), evidence_doc(), evidence_doc(manual_confirmation("sla", "checkout", "owner", "team-a")), empty_section_reviews())
        self.assertTrue(any(gap.rule == "sla-normative-source" for gap in result.blocking_gaps))

    def test_sla_confirmation_for_threshold_clears_threshold_gap(self) -> None:
        result = reconcile.reconcile_documents(repo_doc(), evidence_doc(), evidence_doc(manual_confirmation("sla", "checkout", "threshold", "p95 <= 800ms")), empty_section_reviews())
        self.assertFalse(any(gap.rule == "sla-normative-source" for gap in result.blocking_gaps))

    def test_repository_only_inferred_fact_is_inferred(self) -> None:
        record = contracts.EvidenceRecord("workload", "checkout", "workload", "rps", "250 rps", contracts.SourceRef("repository", "src/workload.py:1", module_id="orders", revision="abc"), "inferred", "current")
        result = reconcile.reconcile_documents(evidence_doc(record), evidence_doc(), evidence_doc(), empty_section_reviews())
        self.assertEqual(result.entity("workload", "checkout").status, "inferred")

    def test_confluence_only_inferred_fact_is_inferred(self) -> None:
        record = contracts.EvidenceRecord("workload", "checkout", "workload", "rps", "250 rps", contracts.SourceRef("confluence", "https://wiki/workload", page_id="42", page_version=3), "inferred", "current")
        result = reconcile.reconcile_documents(evidence_doc(), evidence_doc(record), evidence_doc(), empty_section_reviews())
        self.assertEqual(result.entity("workload", "checkout").status, "inferred")

    def test_review_approve_exclude_and_add_changes_entity_status_and_provenance(self) -> None:
        extracted = evidence_doc(
            record("repository", "GET /orders/{id}", entity_type="endpoint", entity_id="orders.get"),
            record("repository", "GET /legacy", entity_type="endpoint", entity_id="legacy.get"),
        )
        review = contracts.SectionReviewsDocument(reviews={
            "Реестр тестируемых интерфейсов": contracts.SectionReview(
                reviewed_by="Иван Петров",
                approved=("endpoint.orders.get",),
                excluded=("endpoint.legacy.get",),
                added=(contracts.ReviewAddition(
                    entity_type="endpoint", entity_id="orders.health",
                    fields={"method_path": "GET /health"},
                ),),
            )
        })
        result = reconcile.reconcile_documents(extracted, evidence_doc(), evidence_doc(), review)
        self.assertEqual(result.entity("endpoint", "orders.get").status, "confirmed")
        self.assertEqual(result.entity("endpoint", "legacy.get").status, "not_applicable")
        added = result.entity("endpoint", "orders.health")
        self.assertEqual(added.status, "confirmed")
        self.assertEqual(added.fields["method_path"][0].source.source_type, "section-review")

    def test_stale_review_reference_is_blocking(self) -> None:
        review = contracts.SectionReviewsDocument(reviews={
            "Реестр интеграций": contracts.SectionReview(
                reviewed_by="Иван Петров", approved=("integration.removed",),
                excluded=(), added=(),
            )
        })
        result = reconcile.reconcile_documents(evidence_doc(), evidence_doc(), evidence_doc(), review)
        self.assertTrue(any(gap.rule == "review-stale-reference" for gap in result.blocking_gaps))

    def test_conflict_wins_over_review_approval(self) -> None:
        review = contracts.SectionReviewsDocument(reviews={
            "Реестр тестируемых интерфейсов": contracts.SectionReview(
                reviewed_by="Иван Петров", approved=("endpoint.orders.get-order",),
                excluded=(), added=(),
            )
        })
        result = reconcile.reconcile_documents(
            evidence_doc(openapi_endpoint("GET /orders/{id}"), backend_endpoint("GET /order/{id}")),
            evidence_doc(), evidence_doc(), review,
        )
        self.assertEqual(result.entity("endpoint", "orders.get-order").status, "conflict")
        self.assertTrue(any(gap.rule == "evidence-conflict" for gap in result.blocking_gaps))

    def test_review_addition_type_must_belong_to_its_section(self) -> None:
        review = contracts.SectionReviewsDocument(reviews={
            "Реестр тестируемых интерфейсов": contracts.SectionReview(
                reviewed_by="Иван Петров", approved=(), excluded=(),
                added=(contracts.ReviewAddition(
                    entity_type="integration", entity_id="orders.inventory",
                    fields={"target": "inventory-service"},
                ),),
            )
        })
        with self.assertRaisesRegex(ValueError, "entity type does not belong to review section"):
            reconcile.reconcile_documents(evidence_doc(), evidence_doc(), evidence_doc(), review)

    def test_empty_evidence_emits_five_mandatory_section_missing_gaps(self) -> None:
        result = reconcile.reconcile_documents(
            evidence_doc(), evidence_doc(), evidence_doc(), empty_section_reviews()
        )
        gaps = [gap for gap in result.blocking_gaps if gap.rule == "mandatory-section-missing"]
        self.assertEqual(len(gaps), 5)

    def test_strict_section_emits_one_unconfirmed_gap_per_entity(self) -> None:
        flows = evidence_doc(
            record("repository", "checkout", entity_type="flow", entity_id="checkout"),
            record("repository", "refund", entity_type="flow", entity_id="refund"),
        )
        result = reconcile.reconcile_documents(flows, evidence_doc(), evidence_doc(), empty_section_reviews())
        ids = {
            gap.entity_id for gap in result.blocking_gaps
            if gap.rule == "mandatory-entity-unconfirmed" and gap.entity_type == "flow"
        }
        self.assertEqual(ids, {"checkout", "refund"})

    def test_review_section_emits_one_list_gap_for_all_unreviewed_entities(self) -> None:
        endpoints = evidence_doc(
            record("repository", "GET /a", entity_type="endpoint", entity_id="a"),
            record("repository", "GET /b", entity_type="endpoint", entity_id="b"),
        )
        result = reconcile.reconcile_documents(endpoints, evidence_doc(), evidence_doc(), empty_section_reviews())
        gaps = [gap for gap in result.blocking_gaps if gap.rule == "registry-review-required"]
        self.assertEqual(sum(gap.entity_type == "endpoint" for gap in gaps), 1)

    def test_excluded_entities_do_not_count_toward_coverage_or_gaps(self) -> None:
        endpoints = evidence_doc(record("repository", "GET /legacy", entity_type="endpoint", entity_id="legacy"))
        reviews = contracts.SectionReviewsDocument(reviews={
            "Реестр тестируемых интерфейсов": contracts.SectionReview(
                reviewed_by="Иван Петров", approved=(), excluded=("endpoint.legacy",), added=(),
            )
        })
        result = reconcile.reconcile_documents(endpoints, evidence_doc(), evidence_doc(), reviews)
        with tempfile.TemporaryDirectory() as tmp:
            coverage = json.loads(
                reconcile.write_reconciliation_outputs(result, Path(tmp))["section-coverage.json"].read_text(encoding="utf-8")
            )
        heading = "Реестр тестируемых интерфейсов"
        self.assertEqual(coverage["sections"][heading], "missing")
        self.assertEqual(coverage["evidence_ids"][heading], [])
        self.assertTrue(any(gap.rule == "mandatory-section-missing" for gap in result.blocking_gaps))

    def test_production_workload_rule_is_removed(self) -> None:
        result = reconcile.reconcile_documents(
            evidence_doc(), evidence_doc(), evidence_doc(), empty_section_reviews()
        )
        self.assertFalse(any(gap.rule == "production-workload" for gap in result.blocking_gaps))

if __name__ == "__main__":
    unittest.main()

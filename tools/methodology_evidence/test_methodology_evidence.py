#!/usr/bin/env python3
"""Evidence schema contract tests."""

from __future__ import annotations

import json
import jsonschema
import sys
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import contracts
import aggregate
from fixtures import (
    evidence_doc,
    evidence_file,
    same_endpoint_from_backend,
    same_endpoint_from_openapi,
)


class EvidenceContractTest(unittest.TestCase):
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

if __name__ == "__main__":
    unittest.main()

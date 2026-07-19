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

if __name__ == "__main__":
    unittest.main()

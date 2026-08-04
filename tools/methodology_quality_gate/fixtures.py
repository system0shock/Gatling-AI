"""Small UTF-8 fixture builder used by the methodology quality-gate tests."""

from __future__ import annotations

import difflib
import hashlib
import json
from pathlib import Path

from methodology_evidence.contracts import (
    EvidenceDocument,
    EvidenceRecord,
    ReviewAddition,
    SectionReview,
    SectionReviewsDocument,
    SourceRef,
)
from methodology_evidence.reconcile import (
    MANDATORY_MNT_SECTIONS,
    NO_DATA,
    REQUIRED_MNT_SECTIONS,
    reconcile_documents,
    write_reconciliation_outputs,
)


HEADINGS = tuple(heading for heading, _ in REQUIRED_MNT_SECTIONS)
MANDATORY_HEADINGS = frozenset(heading for heading, _ in MANDATORY_MNT_SECTIONS)
FIXTURE_GENERATED_AT = "2026-08-04T00:00:00+00:00"


def _write_snapshot(path: Path) -> str:
    modules = {
        "fixture": {
            "commit": "abc",
            "path": "fixture",
            "kind": "backend",
            "dirty": False,
            "dirty_policy": "clean",
        }
    }
    snapshot_id = hashlib.sha256(
        json.dumps(modules, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "snapshot_id": snapshot_id,
                "workspace_root": "fixture",
                "modules": modules,
            }
        ),
        encoding="utf-8",
    )
    return snapshot_id


def _write_patch(path: Path, base: Path, candidate: Path, base_text: str, candidate_text: str) -> None:
    patch = "".join(
        difflib.unified_diff(
            base_text.splitlines(keepends=True),
            candidate_text.splitlines(keepends=True),
            fromfile=str(base),
            tofile=str(candidate),
        )
    )
    path.write_text(patch, encoding="utf-8")


def write_gate_fixture(
    root: Path,
    *,
    omit: str | None = None,
    extra: str = "",
    sla: str | None = None,
    source_map: dict | None = None,
) -> dict[str, Path]:
    """Write a complete, contract-valid candidate and companions beneath *root*."""
    paths = {
        name: root / name
        for name in (
            "candidate.md", "resolved.json", "coverage.json", "source-map.json",
            "methodology.patch", "base.md", "workspace-snapshot.json",
        )
    }
    body = ["# РњРќРў"]
    for heading in HEADINGS:
        if heading != omit:
            body.extend(["", f"## {heading}", "", sla if heading.startswith("SLA") and sla else NO_DATA])
    if extra:
        body.extend(["", extra])
    candidate_text = "\n".join(body) + "\n"
    base_text = "# РњРќРў\n"
    paths["candidate.md"].write_text(candidate_text, encoding="utf-8")
    paths["base.md"].write_text(base_text, encoding="utf-8")
    evidence_ids = {heading: [f"fact.section-{index}.value"] for index, heading in enumerate(HEADINGS, start=1)}
    entities = [
        {"entity_type": "fact", "entity_id": f"section-{index}", "status": "confirmed", "fields": {"value": [{"entity_type": "fact", "entity_id": f"section-{index}", "field": "value", "statement": "fixture", "source": {"source_type": "repository", "ref": "fixture.md", "module_id": "fixture", "revision": "abc"}, "confidence": "confirmed", "freshness": "current"}]}}
        for index, _ in enumerate(HEADINGS, start=1)
    ]
    paths["resolved.json"].write_text(json.dumps({"version": 1, "entities": entities, "blocking_gaps": []}), encoding="utf-8")
    paths["coverage.json"].write_text(json.dumps({
        "version": 1,
        "sections": {heading: "covered" for heading in HEADINGS},
        "evidence_ids": evidence_ids,
    }), encoding="utf-8")
    mapped = source_map if source_map is not None else evidence_ids
    snapshot_id = _write_snapshot(paths["workspace-snapshot.json"])
    paths["source-map.json"].write_text(json.dumps({
        "version": 1,
        "sections": mapped,
        "workspace_snapshot": {"version": 1, "snapshot_id": snapshot_id, "fresh": True},
    }), encoding="utf-8")
    _write_patch(
        paths["methodology.patch"], paths["base.md"], paths["candidate.md"], base_text, candidate_text
    )
    return {"candidate": paths["candidate.md"], "resolved_evidence": paths["resolved.json"],
            "coverage": paths["coverage.json"], "source_map": paths["source-map.json"],
            "patch": paths["methodology.patch"], "base": paths["base.md"], "workspace_snapshot": paths["workspace-snapshot.json"]}


def _document(*records: EvidenceRecord) -> EvidenceDocument:
    return EvidenceDocument(
        producer="RUN-001-fixture",
        records=records,
        generated_at=FIXTURE_GENERATED_AT,
    )


def _record(
    *,
    entity_type: str,
    entity_id: str,
    section: str,
    field: str,
    statement: str,
    source: SourceRef,
) -> EvidenceRecord:
    return EvidenceRecord(
        entity_type=entity_type,
        entity_id=entity_id,
        section=section,
        field=field,
        statement=statement,
        source=source,
        confidence="confirmed",
        freshness="current",
    )


def write_run_001_fixture(root: Path, *, closed: bool) -> dict[str, Path]:
    """Write deterministic open or reviewed RUN-001 gate inputs beneath *root*."""
    root.mkdir(parents=True, exist_ok=True)
    optional_sections = [
        (heading, entity_types)
        for heading, entity_types in REQUIRED_MNT_SECTIONS
        if heading not in MANDATORY_HEADINGS
    ]
    repository = _document(
        *(
            _record(
                entity_type=sorted(entity_types)[0],
                entity_id=f"optional-{index:02d}",
                section=heading,
                field="value",
                statement="Подтвержденный факт.",
                source=SourceRef(
                    source_type="repository",
                    ref=f"fixture.md:{index}",
                    module_id="fixture",
                    revision="abc",
                ),
            )
            for index, (heading, entity_types) in enumerate(optional_sections, start=1)
        )
    )

    confirmations = _document()
    reviews = SectionReviewsDocument(reviews={})
    if closed:
        confirmations = _document(
            _record(
                entity_type="flow",
                entity_id="checkout",
                section="Пользовательские и технические потоки",
                field="name",
                statement="checkout",
                source=SourceRef(source_type="manual-confirmation", ref="RUN-001:flow-confirmation"),
            ),
            _record(
                entity_type="sla",
                entity_id="checkout",
                section="SLA, SLO и критерии приемки",
                field="threshold",
                statement="p95 <= 800 ms",
                source=SourceRef(source_type="manual-confirmation", ref="RUN-001:sla-confirmation"),
            ),
        )
        review_additions = {
            "Модель нагрузки": ReviewAddition("workload", "checkout", {"profile": "250 rps"}),
            "Реестр тестируемых интерфейсов": ReviewAddition(
                "endpoint", "checkout", {"method_path": "GET /checkout"}
            ),
            "Реестр интеграций": ReviewAddition(
                "integration", "checkout", {"protocol": "HTTP"}
            ),
        }
        reviews = SectionReviewsDocument(
            reviews={
                heading: SectionReview(
                    reviewed_by="RUN-001 reviewer",
                    approved=(),
                    excluded=(),
                    added=(addition,),
                )
                for heading, addition in review_additions.items()
            }
        )

    result = reconcile_documents(repository, _document(), confirmations, reviews)
    reconciliation_paths = write_reconciliation_outputs(result, root)
    coverage_path = reconciliation_paths["section-coverage.json"]
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))

    candidate_path = root / "methodology.candidate.md"
    base_path = root / "methodology.md"
    patch_path = root / "methodology.patch"
    snapshot_path = root / "workspace-snapshot.json"
    source_map_path = root / "methodology-source-map.json"
    body = ["# МНТ"]
    for heading in HEADINGS:
        statement = NO_DATA if coverage["sections"][heading] == "missing" else "Подтвержденный факт."
        body.extend(["", f"## {heading}", "", statement])
    candidate_text = "\n".join(body) + "\n"
    base_text = "# МНТ\n"
    candidate_path.write_text(candidate_text, encoding="utf-8")
    base_path.write_text(base_text, encoding="utf-8")

    snapshot_id = _write_snapshot(snapshot_path)
    source_map_path.write_text(
        json.dumps(
            {
                "version": 1,
                "sections": {
                    heading: coverage["evidence_ids"][heading]
                    if status in {"partial", "covered"}
                    else []
                    for heading, status in coverage["sections"].items()
                },
                "workspace_snapshot": {
                    "version": 1,
                    "snapshot_id": snapshot_id,
                    "fresh": True,
                },
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    _write_patch(patch_path, base_path, candidate_path, base_text, candidate_text)
    return {
        "candidate": candidate_path,
        "resolved_evidence": reconciliation_paths["resolved-evidence.json"],
        "coverage": coverage_path,
        "source_map": source_map_path,
        "patch": patch_path,
        "base": base_path,
        "workspace_snapshot": snapshot_path,
    }

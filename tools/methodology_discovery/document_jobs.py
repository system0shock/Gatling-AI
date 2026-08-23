"""Immutable bounded-document job materialization and final-result validation."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tempfile
from typing import Any

if __package__:
    from . import contracts
    from .models import Candidate, ExtractorResult, SourceRecord
    from .source_views import DiscoveryError, SourceView, normalize_source_path
else:
    import contracts
    from models import Candidate, ExtractorResult, SourceRecord
    from source_views import DiscoveryError, SourceView, normalize_source_path


_DOCUMENT_REASONS = frozenset(
    {
        "user-supplied-document",
        "readme-document",
        "architecture-document",
        "adr-document",
        "endpoint-document",
        "flow-document",
    }
)
_ALLOWED_FACT_TYPES = ["component", "interface", "integration", "flow"]
_CANDIDATE_NAME = "bounded-document-v1.candidate.json"
_FINAL_NAME = "bounded-document-v1.json"


def _safe_repo_id(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("document job repo_id must be a string")
    normalized = normalize_source_path(value)
    if "/" in normalized:
        raise ValueError("document job repo_id must be one path segment")
    return normalized


def _resolved_directory(path: Path) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError(f"run directory is unavailable: {path}") from exc
    if not resolved.is_dir():
        raise ValueError(f"run directory is not a directory: {path}")
    return resolved


def _inside(root: Path, relative: str) -> Path:
    normalize_source_path(relative)
    candidate = root.joinpath(*PurePosixPath(relative).parts)
    try:
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError(f"artifact path escapes the resolved run directory: {relative!r}") from exc
    return candidate


def _mkdir_inside(root: Path, relative: str) -> Path:
    path = _inside(root, relative)
    path.mkdir(parents=True, exist_ok=True)
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError(f"artifact directory escapes the resolved run directory: {relative!r}") from exc
    return resolved


def _atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError(f"materialized input path is a symlink: {path.name}")
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _snapshot_state(snapshot: Mapping[str, Any], repo_id: str) -> Mapping[str, Any]:
    repositories = snapshot.get("repositories") if isinstance(snapshot, Mapping) else None
    if not isinstance(repositories, Mapping):
        repositories = snapshot.get("modules") if isinstance(snapshot, Mapping) else None
    if isinstance(repositories, Mapping):
        state = repositories.get(repo_id)
        if not isinstance(state, Mapping):
            raise ValueError("workspace snapshot has no matching repository state")
        return state
    if not isinstance(snapshot, Mapping):
        raise ValueError("snapshot must be a mapping")
    declared_repo = snapshot.get("repo_id")
    if declared_repo is not None and declared_repo != repo_id:
        raise ValueError("snapshot repo_id does not match discovery index")
    return snapshot


def _validate_snapshot_agreement(
    index: Mapping[str, Any], snapshot: Mapping[str, Any], source_view: SourceView
) -> None:
    if index["snapshot_identity"] != source_view.snapshot_identity:
        raise ValueError("discovery index snapshot identity does not match SourceView")
    if index["source_mode"] != source_view.source_mode:
        raise ValueError("discovery index source mode does not match SourceView")
    state = _snapshot_state(snapshot, index["repo_id"])
    commit = state.get("commit")
    if not isinstance(commit, str) or commit != source_view.revision:
        raise ValueError("snapshot commit does not match SourceView revision")
    policy = state.get("dirty_policy")
    if policy in {"clean", "HEAD"}:
        expected = f"commit:{commit}"
    elif policy == "working-tree":
        fingerprint = state.get("working_tree_fingerprint")
        if not isinstance(fingerprint, str) or not fingerprint:
            raise ValueError("working-tree snapshot requires a fingerprint")
        prefix = source_view.snapshot_identity.split(":", 2)
        if len(prefix) != 3 or prefix[0] != "working-tree" or prefix[2] != fingerprint:
            raise ValueError("working-tree snapshot fingerprint does not match SourceView")
        expected = source_view.snapshot_identity
    else:
        raise ValueError("snapshot dirty_policy is invalid")
    if index["snapshot_identity"] != expected:
        raise ValueError("snapshot state does not match discovery index identity")


def build_document_jobs(
    index: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    source_view: SourceView,
    run_dir: Path,
) -> dict[str, Any]:
    """Materialize selected documents and write one closed repository job artifact."""
    if not isinstance(index, Mapping):
        raise ValueError("discovery index must be a mapping")
    contracts.validate_artifact(index, "methodology-discovery-index.schema.json")
    repo_id = _safe_repo_id(index["repo_id"])
    _validate_snapshot_agreement(index, snapshot, source_view)
    root = _resolved_directory(Path(run_dir))
    input_relative = f"discovery/{repo_id}/document-inputs"
    _mkdir_inside(root, input_relative)
    _mkdir_inside(root, f"discovery/{repo_id}/extractor-results")
    candidate_output = f"discovery/{repo_id}/extractor-results/{_CANDIDATE_NAME}"
    final_output = f"discovery/{repo_id}/extractor-results/{_FINAL_NAME}"

    selected = [
        record
        for record in index["selected_files"]
        if record["selection_reason"] in _DOCUMENT_REASONS
    ][:20]
    source_keys: set[tuple[str, str]] = set()
    jobs: list[dict[str, Any]] = []
    try:
        for ordinal, record in enumerate(selected, 1):
            if record["repo_id"] != repo_id or record["revision"] != source_view.revision:
                raise ValueError("selected document provenance does not match repository snapshot")
            key = (record["path"], record["sha256"])
            if key in source_keys:
                raise ValueError("document job contains duplicate selected source coverage")
            source_keys.add(key)
            content = source_view.read_bytes(record["path"], record["size_bytes"])
            if len(content) != record["size_bytes"]:
                raise DiscoveryError("indexed-source-size-mismatch", "selected document size does not match discovery index", path=record["path"])
            digest = hashlib.sha256(content).hexdigest()
            if digest != record["sha256"]:
                raise DiscoveryError("indexed-source-hash-mismatch", "selected document hash does not match discovery index", path=record["path"])
            materialized = f"{input_relative}/{ordinal:03d}-{digest}.txt"
            target = _inside(root, materialized)
            _atomic_bytes(target, content)
            if target.resolve(strict=True).parent != _inside(root, input_relative).resolve(strict=True):
                raise ValueError("materialized document escaped its assigned directory")
            jobs.append(
                {
                    "source_path": record["path"],
                    "materialized_path": materialized,
                    "allowed_fact_types": list(_ALLOWED_FACT_TYPES),
                    "candidate_output_path": candidate_output,
                    "final_output_path": final_output,
                    "size_bytes": record["size_bytes"],
                    "sha256": digest,
                    "selection_reason": record["selection_reason"],
                }
            )
        source_view.verify_run_guard()
        artifact = {
            "version": 1,
            "repo_id": repo_id,
            "snapshot_identity": index["snapshot_identity"],
            "jobs": jobs,
        }
        contracts.validate_artifact(artifact, "methodology-document-jobs.schema.json")
        job_path = _inside(root, f"discovery/{repo_id}/document-jobs.json")
        contracts.write_json_atomic(job_path, artifact)
        return artifact
    finally:
        source_view.verify_run_guard()


def _read_mapping(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError(f"{label} is not valid bounded UTF-8 JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    return value


def _model_result(value: Mapping[str, Any]) -> ExtractorResult:
    candidates = tuple(
        sorted(
            (
                Candidate(
                    entity_type=item["entity_type"],
                    canonical_key=item["canonical_key"],
                    display_name=item["display_name"],
                    service_identity_value=item["service_identity"]["value"],
                    service_identity_basis=item["service_identity"]["basis"],
                    attributes=dict(item["attributes"]),
                    source=SourceRecord(**item["source"]),
                    confidence=item["confidence"],
                )
                for item in value["candidates"]
            ),
            key=lambda item: (
                item.canonical_key,
                item.source.pointer,
                item.display_name,
            ),
        )
    )
    diagnostic_key = lambda item: (item["code"], item.get("path", ""), item["message"])
    return ExtractorResult(
        extractor_id=value["extractor_id"],
        extractor_version=value["extractor_version"],
        repo_id=value["repo_id"],
        snapshot_identity=value["snapshot_identity"],
        candidates=candidates,
        warnings=tuple(sorted((dict(item) for item in value["warnings"]), key=diagnostic_key)),
        errors=tuple(sorted((dict(item) for item in value["errors"]), key=diagnostic_key)),
        limit_reached=value["limit_reached"],
    )


def _job_bindings(job_artifact: Mapping[str, Any], run_root: Path) -> dict[tuple[str, str, str], Mapping[str, Any]]:
    repo_id = _safe_repo_id(job_artifact["repo_id"])
    expected_candidate = f"discovery/{repo_id}/extractor-results/{_CANDIDATE_NAME}"
    expected_final = f"discovery/{repo_id}/extractor-results/{_FINAL_NAME}"
    bindings: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    materialized_paths: set[str] = set()
    source_paths: set[str] = set()
    if not job_artifact["jobs"]:
        raise ValueError("document job has no selected document coverage")
    if len(job_artifact["jobs"]) > 20:
        raise ValueError("document job may contain at most 20 selected documents")
    for ordinal, job in enumerate(job_artifact["jobs"], 1):
        if job["candidate_output_path"] != expected_candidate or job["final_output_path"] != expected_final:
            raise ValueError("document job output is not the assigned bounded-document path")
        if job["allowed_fact_types"] != _ALLOWED_FACT_TYPES:
            raise ValueError("document job allowed fact types must use the fixed order")
        if job["selection_reason"] not in _DOCUMENT_REASONS:
            raise ValueError("document job must retain a document selection reason")
        expected_materialized = (
            f"discovery/{repo_id}/document-inputs/{ordinal:03d}-{job['sha256']}.txt"
        )
        if job["materialized_path"] != expected_materialized:
            raise ValueError("document job materialized input is not its assigned document-inputs path")
        key = (job["source_path"], job["sha256"], job["selection_reason"])
        if key in bindings:
            raise ValueError("document job contains duplicate selected source coverage")
        if job["source_path"] in source_paths:
            raise ValueError("document job contains duplicate selected source coverage")
        if job["materialized_path"] in materialized_paths:
            raise ValueError("document job reuses one materialized input path")
        bindings[key] = job
        source_paths.add(job["source_path"])
        materialized_paths.add(job["materialized_path"])
        materialized = _inside(run_root, job["materialized_path"])
        try:
            content = materialized.read_bytes()
        except OSError as exc:
            raise ValueError("document job materialized input is missing") from exc
        if len(content) != job["size_bytes"] or hashlib.sha256(content).hexdigest() != job["sha256"]:
            raise ValueError("document job materialized input no longer matches its assigned bytes")
    return bindings


def load_document_results(paths: Iterable[Path | str]) -> tuple[ExtractorResult, ...]:
    """Load final results only when each fact is bound to its sibling closed job."""
    path_list = [Path(path) for path in paths]
    resolved_keys = [str(path.resolve(strict=False)) for path in path_list]
    if len(resolved_keys) != len(set(resolved_keys)):
        raise ValueError("duplicate document result path")
    loaded: list[tuple[str, ExtractorResult]] = []
    for path in sorted(path_list, key=lambda item: item.as_posix()):
        try:
            final = path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ValueError(f"document result is unavailable: {path}") from exc
        if final.name != _FINAL_NAME or final.parent.name != "extractor-results" or final.parent.parent.parent.name != "discovery":
            raise ValueError("document result path is not an assigned final output")
        repo_dir = final.parent.parent
        run_root = repo_dir.parent.parent.resolve(strict=True)
        try:
            final.relative_to(run_root)
        except ValueError as exc:
            raise ValueError("document result escapes its run directory") from exc
        job_path = repo_dir / "document-jobs.json"
        job_artifact = _read_mapping(job_path, "document job")
        contracts.validate_artifact(job_artifact, "methodology-document-jobs.schema.json")
        if job_artifact["repo_id"] != repo_dir.name:
            raise ValueError("document job repo_id does not match its repository directory")
        bindings = _job_bindings(job_artifact, run_root)
        assigned = _inside(run_root, f"discovery/{job_artifact['repo_id']}/extractor-results/{_FINAL_NAME}").resolve(strict=True)
        if final != assigned:
            raise ValueError("document result path is not the assigned final output")

        value = _read_mapping(final, "document result")
        contracts.validate_artifact(value, "methodology-extractor-result.schema.json")
        if value["extractor_id"] != "bounded-document" or value["extractor_version"] != 1:
            raise ValueError("document result extractor must be bounded-document v1")
        if value["repo_id"] != job_artifact["repo_id"] or value["snapshot_identity"] != job_artifact["snapshot_identity"]:
            raise ValueError("document result repository or snapshot does not match its job")
        covered: set[tuple[str, str, str]] = set()
        for candidate in value["candidates"]:
            source = candidate["source"]
            if source["repo_id"] != job_artifact["repo_id"]:
                raise ValueError("document result source repository does not match its job")
            if job_artifact["snapshot_identity"].startswith("commit:"):
                expected_revision = job_artifact["snapshot_identity"][len("commit:") :]
                if source["revision"] != expected_revision:
                    raise ValueError("document result source revision does not match its snapshot")
            key = (source["path"], source["sha256"], source["selection_reason"])
            job = bindings.get(key)
            if job is None:
                raise ValueError("document result source path/hash/selection is absent from its job")
            if candidate["entity_type"] not in job["allowed_fact_types"]:
                raise ValueError("document result entity type is not allowed by its job")
            covered.add(key)
        diagnostic_paths = {
            item["path"]
            for collection in (value["warnings"], value["errors"])
            for item in collection
            if "path" in item
        }
        missing = [key[0] for key in bindings if key not in covered and key[0] not in diagnostic_paths]
        if missing:
            raise ValueError(f"document result omits selected document coverage: {', '.join(sorted(missing))}")
        result = _model_result(value)
        if result.to_dict() != value:
            raise ValueError("document result is not deterministically normalized")
        loaded.append((final.as_posix(), result))
    return tuple(result for _path, result in sorted(loaded, key=lambda item: item[0]))

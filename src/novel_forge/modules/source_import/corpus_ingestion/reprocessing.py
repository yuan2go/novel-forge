from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from novel_forge.modules.authority_handler_runtime.runtime import require_current_fence
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.source_authority.corpus import CorpusUse, corpus_hash
from novel_forge.modules.source_import.domain import SourceImportPolicy
from novel_forge.modules.source_import.profiling import SourceIntelligencePolicy
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.source_authority_repositories import SourceAuthorityRepository
from novel_forge.storage.source_import_repositories import SourceImportRepository
from .contracts import IngestionManifest, ParserProfile
from .parsers import compile_work_index
from .safety import spool_json


def admit_reprocessing(
    runtime: Any,
    *,
    project_id: str,
    edition_id: str,
    parser: ParserProfile,
    run_key: str,
    principal: Any,
) -> dict[str, Any]:
    principal.require("source.authority.execute", project_id)
    if not run_key or len(run_key) > 200 or parser.normalization is None:
        raise ValueError(
            "reprocess needs a run key and an explicit v2 normalization contract"
        )
    app = runtime.app
    app._register_definitions()
    with AuthorityUnitOfWork(app.database_url, coordinate_nested=True) as uow:
        repository = SourceAuthorityRepository(uow.cursor)
        repository.corpus_authorization_lock(project_id, write=True)
        permission = repository.require_corpus_edition_use(
            project_id, edition_id, CorpusUse.LOCAL_PROCESSING, require_bridge=False
        )
        key = f"corpus-reprocess:{project_id}:{edition_id}:{run_key}"
        uow.cursor.execute(
            "SELECT operation_id,command_payload FROM authority_operation WHERE project_id=%s AND idempotency_key=%s",
            [project_id, key],
        )
        previous = uow.cursor.fetchone()
        if previous:
            if previous[1]["payload"]["reprocess"]["parser"] != parser.model_dump(
                mode="json"
            ):
                raise KernelError(
                    "IDEMPOTENCY_PAYLOAD_CONFLICT",
                    "reprocess key binds another profile",
                )
            return {
                "operation_id": previous[0],
                "import_job_id": f"source-import:{previous[0]}",
                "replayed": True,
            }
        uow.cursor.execute(
            """SELECT b.source_work_asset_version_id,o.command_payload,p.processing_id,r.review_id,COALESCE(r.assessment,p.assessment),o.operation_id
            FROM authority_corpus_bridge b JOIN authority_source_work_version w ON w.asset_version_id=b.source_work_asset_version_id AND w.status='ACTIVE'
            JOIN authority_operation o ON o.operation_id=b.created_by_operation_id
            LEFT JOIN authority_corpus_processing p ON p.source_work_asset_version_id=b.source_work_asset_version_id
            LEFT JOIN authority_corpus_review r ON r.processing_id=p.processing_id AND NOT EXISTS(SELECT 1 FROM authority_corpus_review n WHERE n.previous_id=r.review_id)
            WHERE b.project_id=%s AND b.edition_id=%s""",
            [project_id, edition_id],
        )
        row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "CORPUS_BRIDGE_MISSING", "ingest verified content before reprocessing"
            )
        payload = dict(row[1]["payload"])
        payload["reprocess"] = {
            "parser": parser.model_dump(mode="json"),
            "parent_id": row[2],
            "parent_work": row[0],
            "review_id": row[3],
            "assessment": row[4],
        }
        workspace = row[1]["workspace_id"]
        operation = app._admit_child(
            definition_name="source.import.corpus.work",
            project_id=project_id,
            workspace_id=workspace,
            actor_id=principal.principal_id,
            idempotency_key=key,
            trace_id=key,
            correlation_id=key,
            causation_id=row[0],
            parent_operation_id=row[5],
            payload=payload,
            input_assets=(),
            ready=False,
        )
        policy, intelligence = SourceImportPolicy(), SourceIntelligencePolicy()
        imports = SourceImportRepository(uow.cursor)
        job = f"source-import:{operation}"
        imports.register_job(
            {
                "import_job_id": job,
                "project_id": project_id,
                "workspace_id": workspace,
                "source_type": "corpus_content",
                "source_locator": {"manifest": payload["manifest"]},
                "requested_ref": corpus_hash(payload),
                "corpus_snapshot_id": permission["snapshot_id"],
                "import_policy": asdict(policy),
                "import_policy_hash": policy.policy_hash,
                "intelligence_policy": asdict(intelligence),
                "intelligence_policy_hash": intelligence.policy_hash,
                "analysis_override": {},
                "mode": "IMPORT",
                "status": "ADMITTED",
                "discovery_operation_id": operation,
            }
        )
        imports.register_work(
            {
                "work_id": str(uuid4()),
                "import_job_id": job,
                "project_id": project_id,
                "work_kind": "WORK",
                "stable_key": key,
                "source_path": edition_id,
                "target_asset_version_id": None,
                "operation_id": operation,
                "status": "PLANNED",
                "result": {},
                "failure": {},
            }
        )
        uow.commit()
    app._ready_child(
        operation_id=operation,
        project_id=project_id,
        actor_id=principal.principal_id,
        trace_id=key,
        correlation_id=key,
        causation_id=key,
        reason="exact acquisition reprocessing ready",
    )
    return {"operation_id": operation, "import_job_id": job, "replayed": False}


def prepare_reprocessing(
    runtime: Any, worker: Any, payload: dict[str, Any]
) -> dict[str, Any]:
    app = runtime.app
    revision = payload["reprocess"]
    parser = ParserProfile.model_validate(revision["parser"])
    manifest = IngestionManifest.model_validate(payload["manifest"])
    with AuthorityUnitOfWork(app.database_url) as uow:
        require_current_fence(uow, worker)
        repository = SourceAuthorityRepository(uow.cursor)
        repository.require_corpus_edition_use(
            worker.project_id,
            payload["edition_id"],
            CorpusUse.LOCAL_PROCESSING,
            require_bridge=False,
        )
        require_reprocessing_baseline(repository, payload)
        if revision["parent_id"] and not revision["review_id"]:
            current = repository.corpus_processing(
                worker.project_id, revision["parent_id"]
            )
            if current["profile"] == parser.model_dump(mode="json"):
                uow.cursor.execute(
                    "SELECT result FROM authority_source_import_work WHERE operation_id=%s AND project_id=%s",
                    [current["created_by_operation_id"], worker.project_id],
                )
                original = uow.cursor.fetchone()
                if original and original[0]:
                    return {**payload, "reuse_result": original[0]}
        blob = uow.repositories.asset_blobs.blob_for_update(payload["parsed_blob_id"])
    old = json.loads(
        app.object_store_reader.read(
            object_key=blob["actual_object_key"],
            expected_hash=blob["actual_hash"],
            expected_size=blob["actual_size"],
        )
    )
    identities = {
        r["raw_blob_id"]: (r["source_locator"], r["raw_file_hash"])
        for r in old["units"]
    }
    root = (
        app.corpus_adapter.root
        / "reprocessing"
        / hashlib.sha256(worker.causation_id.encode()).hexdigest()
    )
    files = []
    for blob_id, (locator, checksum) in sorted(identities.items()):
        with AuthorityUnitOfWork(app.database_url) as uow:
            blob = uow.repositories.asset_blobs.blob_for_update(blob_id)
        if blob["actual_size"] > min(
            manifest.budget.max_file_bytes, manifest.budget.memory_bytes // 8
        ):
            raise KernelError(
                "CORPUS_REPROCESS_RESOURCE_LIMIT",
                "verified file exceeds bounded reader budget",
            )
        raw = app.object_store_reader.read(
            object_key=blob["actual_object_key"],
            expected_hash=checksum,
            expected_size=blob["actual_size"],
        )
        path = root / "inputs" / hashlib.sha256(blob_id.encode()).hexdigest()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        files.append(
            {
                "path": locator["path"],
                "container_path": locator.get("container_path"),
                "cache_path": str(path),
                "checksum": checksum,
                "blob_id": blob_id,
                "size_bytes": len(raw),
            }
        )
    compiled = compile_work_index(files, parser, manifest.budget, root / "index")
    candidates = [
        p
        for p in compiled["works"]
        if p["work_id"] == old["work_id"] and p["edition_id"] == old["edition_id"]
    ]
    if len(candidates) != 1:
        raise KernelError(
            "CORPUS_REPROCESS_IDENTITY_CHANGED",
            "parser cannot change acquired book/edition identity",
        )
    pointer = candidates[0]
    document = json.loads(Path(pointer["cache_path"]).read_text())
    review = revision.get("assessment")
    if review and parser.version == "corpus-parser.v3":
        from .review_replay import carry_review

        carry_review(
            document,
            review,
            parser=parser,
            boundary_repair=lambda finding: _boundary_repair(
                finding, parser, identities
            ),
        )
    elif review:
        excluded = {
            e["unit_id"]: r
            for r in review.get("resolutions", [])
            if r["resolution"] == "MARK_NON_BODY"
            for e in r["evidence"]
        }
        for unit in document["units"]:
            if unit["chapter_id"] in excluded:
                evidence = next(
                    e
                    for e in excluded[unit["chapter_id"]]["evidence"]
                    if e["unit_id"] == unit["chapter_id"]
                )
                if evidence["content_hash"] != unit["normalized_content_hash"]:
                    raise KernelError(
                        "CORPUS_REVIEW_EVIDENCE_CHANGED", "reviewed unit bytes changed"
                    )
                unit["excluded_from_analysis"] = True
        document["integrity"]["resolutions"] = review.get("resolutions", [])
        resolved = {r["issue_id"]: r for r in review.get("resolutions", [])}
        for finding in document["integrity"]["issues"]:
            if finding["issue_id"] in resolved:
                finding["resolution"] = resolved[finding["issue_id"]]
                finding["blocking"] = (
                    resolved[finding["issue_id"]]["resolution"] == "REJECT_CORRUPT"
                )
        known = {i["issue_id"] for i in document["integrity"]["issues"]}
        for finding in review["issues"]:
            if finding["blocking"] and finding["issue_id"] not in known:
                if _boundary_repair(finding, parser, identities):
                    document["integrity"]["resolutions"].append(
                        {
                            "issue_id": finding["issue_id"],
                            "resolution": "RESEGMENTED_EXACT_SOURCE",
                            "evidence": finding["evidence"],
                            "profile_hash": corpus_hash(parser.model_dump(mode="json")),
                        }
                    )
                else:
                    document["integrity"]["issues"].append(finding)
        document["integrity"]["structure_usable"] = not any(
            i["blocking"] for i in document["integrity"]["issues"]
        )
        if any(r["resolution"] == "CONFIRM_EXCERPT" for r in resolved.values()):
            document["integrity"]["coverage"] = "EXCERPT"
    if (
        document["integrity"]["structure_usable"]
        and document["integrity"]["coverage"] == "REVIEW_REQUIRED"
    ):
        document["integrity"]["coverage"] = (
            "COMPLETE" if document["integrity"]["toc_matches"] else "UNKNOWN"
        )
    if document["integrity"]["structure_usable"]:
        document["completeness"] = (
            document["integrity"]["coverage"]
            if document["integrity"]["coverage"] != "REVIEW_REQUIRED"
            else "UNKNOWN"
        )
    document["processing_parent"] = revision["parent_id"]
    document["review_id"] = revision["review_id"]
    pointer = spool_json(document, root / "reviewed", manifest.budget)
    blob_id = app._put_blob(
        worker,
        content=Path(pointer["cache_path"]),
        content_hash=pointer["checksum"],
        media_type="application/json",
        purpose="corpus-reprocessed-work",
    )
    runtime._content(
        worker,
        payload["snapshot_id"],
        payload["edition_id"],
        payload["acquisition_effect_id"],
        blob_id,
        "PARSED_WORK",
        payload["edition_id"],
        pointer,
        {"parser_version": parser.version, "review_id": revision["review_id"]},
    )
    return {
        **payload,
        "parsed_blob_id": blob_id,
        "parsed_hash": pointer["checksum"],
        "parsed_size": pointer["size_bytes"],
        "manifest": manifest.model_copy(
            update={"parser": parser, "analyze": False}
        ).model_dump(mode="json"),
    }


def require_reprocessing_baseline(repository: Any, payload: dict[str, Any]) -> None:
    revision = payload["reprocess"]
    repository.cursor.execute(
        """SELECT w.asset_version_id,r.review_id FROM authority_source_work_version w
        LEFT JOIN authority_corpus_processing p ON p.source_work_asset_version_id=w.asset_version_id
        LEFT JOIN authority_corpus_review r ON r.processing_id=p.processing_id
          AND NOT EXISTS(SELECT 1 FROM authority_corpus_review n WHERE n.previous_id=r.review_id)
        WHERE w.corpus_edition_id=%s AND w.status='ACTIVE'""",
        [payload["edition_id"]],
    )
    active = repository.cursor.fetchone()
    if active is None or tuple(active) != (
        revision["parent_work"],
        revision["review_id"],
    ):
        raise KernelError(
            "CORPUS_REPROCESS_STALE_FAILED_FINAL",
            "processing or review changed; admit a new request against the current revision",
        )


def _boundary_repair(
    finding: dict[str, Any], parser: ParserProfile, identities: dict
) -> bool:
    if finding.get("resolution") or finding["code"] not in {
        "RELIABLE_BOUNDARIES_MISSING",
        "SHORT_OR_TOC_UNIT",
        "NON_BODY_UNIT",
    }:
        return False
    profile = parser.normalization
    assert profile is not None
    checksums = {locator["path"]: checksum for locator, checksum in identities.values()}
    for evidence in finding["evidence"]:
        locator = evidence["locator"]
        start, end = (
            locator.get("original_byte_offset"),
            locator.get("original_byte_end"),
        )
        if start is None or end is None:
            return False
        spans = sorted(
            (b.start, b.end)
            for b in profile.boundaries
            if b.path == locator["path"]
            and b.checksum == checksums.get(b.path)
            and start <= b.start < b.end <= end
            and b.kind in {"CHAPTER", "EXTRA"}
        )
        if (
            not spans
            or spans[0][0] != start
            or spans[-1][1] != end
            or any(a[1] != b[0] for a, b in zip(spans, spans[1:]))
        ):
            return False
    return bool(finding["evidence"])

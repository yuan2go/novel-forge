from __future__ import annotations

from dataclasses import asdict
from typing import Any
from uuid import uuid4
from pydantic import Field, model_serializer
from .reading_scope import ChapterReadingScope, freeze_reading_scope
from novel_forge.modules.source_authority.corpus import (
    CorpusContract,
    Text,
    corpus_hash,
)
from novel_forge.modules.source_authority.curation import (
    curated_availability,
    require_curated_operation_current,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.authority_handler_runtime.runtime import require_current_fence
from novel_forge.modules.source_import.domain import SourceImportPolicy
from novel_forge.modules.source_import.profiling import SourceIntelligencePolicy
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.source_authority_repositories import SourceAuthorityRepository
from novel_forge.storage.source_import_repositories import SourceImportRepository

OPERATION = "source.import.corpus.analysis"


class CuratedAnalysisRequest(CorpusContract):
    project_id: Text
    revision_id: Text
    run_key: Text
    max_members: int = Field(default=5, ge=1, le=100)
    max_calls: int = Field(ge=1, le=10000)
    max_tokens: int = Field(ge=1, le=100000000)
    authorization_ref: Text
    intelligence_policy: dict[str, Any] = Field(default_factory=dict)
    reading_scopes: tuple[ChapterReadingScope, ...] = Field(default=(), max_length=100)

    @model_serializer(mode="wrap")
    def preserve_frozen_request(self, handler: Any) -> dict:
        result = handler(self)
        if not self.reading_scopes:
            result.pop("reading_scopes", None)
        return result


def admit_curated_analysis(
    app: Any, request: CuratedAnalysisRequest, principal: Any
) -> dict[str, Any]:
    principal.require("source.authority.execute", request.project_id)
    app._register_definitions()
    policy = SourceIntelligencePolicy(**request.intelligence_policy)
    frozen = request.model_dump(mode="json")
    runtime_identity = (
        app._require_execution_port().frozen_reading_runtime()
        if request.reading_scopes
        else None
    )
    key = "curated-analysis:" + corpus_hash(
        {"project": request.project_id, "key": request.run_key}
    )
    with AuthorityUnitOfWork(app.database_url, coordinate_nested=True) as uow:
        repository = SourceAuthorityRepository(uow.cursor)
        repository.corpus_authorization_lock(request.project_id, write=True)
        imports = SourceImportRepository(uow.cursor)
        old = repository.catalog_analysis_previous(request.project_id, key)
        if old:
            if old["requested_manifest"] != frozen:
                raise KernelError(
                    "IDEMPOTENCY_PAYLOAD_CONFLICT",
                    "analysis run key binds another request",
                )
            return {
                "import_job_id": old["import_job_id"],
                "operation_id": old["discovery_operation_id"],
                "replayed": True,
            }
        corpus = repository.catalog_current(
            "curated", request.project_id, request.revision_id, revision=True
        )
        if not corpus or corpus["manifest"]["state"] != "FROZEN":
            raise KernelError(
                "CURATED_CORPUS_NOT_FROZEN",
                "inspect and freeze a usable explicit subset",
            )
        current = repository.catalog_current(
            "curated", request.project_id, corpus["corpus_id"]
        )
        if current["revision_id"] != request.revision_id:
            raise KernelError(
                "CURATED_REVISION_STALE",
                "new dispatch requires current frozen selection",
            )
        selected = [m for m in corpus["members"] if m["evidence"]["selected"]]
        if not selected or len(selected) > request.max_members:
            raise KernelError(
                "CURATED_MEMBER_BUDGET", "selected subset exceeds request bound"
            )
        availability = curated_availability(repository, request.project_id, selected)
        if any(not r["available"] for r in availability):
            raise KernelError("CURATED_MEMBERS_UNAVAILABLE", str(availability))
        reading_plans = (
            freeze_reading_scope(
                repository, request.project_id, selected, request.reading_scopes
            )
            if request.reading_scopes
            else {}
        )
        from novel_forge.modules.command_kernel.budget_runtime import provider_project_usage

        spent = provider_project_usage(uow.cursor, request.project_id)
        payload = {
            "requested_manifest": frozen,
            "manifest": {"curated_revision_id": request.revision_id},
            "curated_revision_id": request.revision_id,
            "members": selected,
            "intelligence_policy": asdict(policy),
            "budget": {
                "project_call_ceiling": spent["calls_used_or_reserved"] + request.max_calls,
                "project_token_ceiling": spent["conservative_tokens"] + request.max_tokens,
                "authorization_ref": request.authorization_ref,
                "accounting_scope": "PROJECT_TOTAL_CONSERVATIVE_SHARED_CEILING",
            },
        }
        if reading_plans:
            payload["reading_plans"] = reading_plans
            payload["budget"]["reading_runtime"] = runtime_identity
        operation = app._admit_child(
            definition_name=OPERATION,
            project_id=request.project_id,
            workspace_id=corpus["workspace_id"],
            actor_id=principal.principal_id,
            idempotency_key=key,
            trace_id=key,
            correlation_id=key,
            causation_id=request.revision_id,
            parent_operation_id=corpus["created_by_operation_id"],
            payload=payload,
            input_assets=(),
            ready=False,
        )
        job = "source-import:" + operation
        import_policy = SourceImportPolicy()
        imports.register_job(
            {
                "import_job_id": job,
                "project_id": request.project_id,
                "workspace_id": corpus["workspace_id"],
                "source_type": "corpus_content",
                "source_locator": {"manifest": payload["manifest"]},
                "requested_ref": corpus_hash(payload),
                "corpus_snapshot_id": None,
                "import_policy": asdict(import_policy),
                "import_policy_hash": import_policy.policy_hash,
                "intelligence_policy": asdict(policy),
                "intelligence_policy_hash": policy.policy_hash,
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
                "project_id": request.project_id,
                "work_kind": "WORK",
                "stable_key": key,
                "source_path": "curated:" + request.revision_id,
                "target_asset_version_id": None,
                "operation_id": operation,
                "status": "PLANNED",
                "result": {},
                "failure": {},
            }
        )
        app._ready_child(
            operation_id=operation,
            project_id=request.project_id,
            actor_id=principal.principal_id,
            trace_id=key,
            correlation_id=key,
            causation_id=key,
            reason="frozen curated analysis ready",
        )
        uow.commit()
    return {
        "import_job_id": job,
        "operation_id": operation,
        "replayed": False,
        "selected_members": len(selected),
        "model_calls": 0,
        "budget": payload["budget"],
        **({"reading_plans": reading_plans} if reading_plans else {}),
    }


def execute_curated_analysis(runtime: Any, worker: Any) -> dict[str, Any]:
    work, job, payload = runtime._load(worker)
    if work["status"] in {"SUCCEEDED", "REUSED"}:
        return work["result"]
    if payload.get("reading_expansion_repair"):
        from .reading_recovery import execute_expansion_repair

        return execute_expansion_repair(runtime, worker, job, payload)
    app = runtime.app
    with AuthorityUnitOfWork(app.database_url, coordinate_nested=True) as uow:
        require_current_fence(uow, worker)
        repository = SourceAuthorityRepository(uow.cursor)
        repository.corpus_authorization_lock(worker.project_id, write=True)
        ensure_selection_active(repository, worker.project_id, payload)
        members = payload["members"]
        member_id = payload.get("member_processing_id")
        selected = [
            m for m in members if not member_id or m["processing_id"] == member_id
        ]
        if member_id:
            availability = curated_availability(repository, worker.project_id, selected)
            if len(selected) != 1 or any(not r["available"] for r in availability):
                raise KernelError(
                    "CURATED_MEMBER_NO_LONGER_AVAILABLE", str(availability)
                )
            source = repository.catalog_processings(worker.project_id, [member_id])[
                member_id
            ]
            app._admit_profiling_child(
                worker,
                job,
                source,
                source_paths=(),
                reading_plan=payload.get("reading_plans", {}).get(member_id),
            )
            result = {
                "stage": "SOURCE_ANALYSIS_SCHEDULED",
                "processing_id": member_id,
                "curated_revision_id": payload["curated_revision_id"],
                "knowledge_approved": False,
            }
        else:
            children = []
            for member in selected:
                key = "curated-member:" + corpus_hash(
                    {"job": job["import_job_id"], "processing": member["processing_id"]}
                )
                child = app._admit_child(
                    definition_name=OPERATION,
                    project_id=worker.project_id,
                    workspace_id=job["workspace_id"],
                    actor_id=app.worker_id,
                    idempotency_key=key,
                    trace_id=worker.trace_id,
                    correlation_id=worker.correlation_id,
                    causation_id=worker.causation_id,
                    parent_operation_id=worker.causation_id,
                    payload={
                        **payload,
                        "member_processing_id": member["processing_id"],
                    },
                    input_assets=(),
                    ready=False,
                )
                SourceImportRepository(uow.cursor).register_work(
                    {
                        "work_id": str(uuid4()),
                        "import_job_id": job["import_job_id"],
                        "project_id": worker.project_id,
                        "work_kind": "WORK",
                        "stable_key": key,
                        "source_path": member["edition_id"],
                        "target_asset_version_id": None,
                        "operation_id": child,
                        "status": "PLANNED",
                        "result": {},
                        "failure": {},
                    }
                )
                app._ready_child(
                    operation_id=child,
                    project_id=worker.project_id,
                    actor_id=app.worker_id,
                    trace_id=worker.trace_id,
                    correlation_id=worker.correlation_id,
                    causation_id=worker.causation_id,
                    reason="frozen curated member ready",
                )
                children.append(
                    {
                        "processing_id": member["processing_id"],
                        "operation_id": child,
                        "status": "QUEUED",
                    }
                )
            result = {
                "stage": "CURATED_MEMBERS_QUEUED",
                "children": children,
                "knowledge_approved": False,
            }
        result = runtime._finish(worker, job, result)
        uow.commit()
        return result


def curated_provider_gate(database_url: str, worker: Any) -> dict[str, Any]:
    with AuthorityUnitOfWork(database_url) as uow:
        require_current_fence(uow, worker)
        repository = SourceAuthorityRepository(uow.cursor)
        return require_curated_operation_current(
            repository, worker.project_id, worker.causation_id
        )


def capped_usage(existing: dict[str, int], bound: int | None) -> dict[str, int]:
    result = dict(existing)
    if bound is not None:
        result["project_total"] = min(result.get("project_total", bound), bound)
    return result


def ensure_selection_active(
    repository: Any, project: str, payload: dict[str, Any]
) -> None:
    frozen = repository.catalog_current(
        "curated", project, payload["curated_revision_id"], revision=True
    )
    current = (
        repository.catalog_current("curated", project, frozen["corpus_id"])
        if frozen
        else None
    )
    if (
        not current
        or current["revision_id"] != payload["curated_revision_id"]
        or current["manifest"]["state"] != "FROZEN"
    ):
        raise KernelError(
            "CURATED_SELECTION_CHANGED",
            "frozen history remains readable; new execution requires current explicit selection",
        )

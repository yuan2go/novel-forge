from __future__ import annotations

from uuid import uuid4

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.source_authority.corpus import corpus_hash
from novel_forge.modules.source_authority.curation import (
    require_curated_operation_current,
)
from novel_forge.storage.source_authority_repositories import SourceAuthorityRepository
from novel_forge.storage.source_import_repositories import SourceImportRepository


def admit_expansion_repairs(app, uow, job, actor):
    repository = SourceImportRepository(uow.cursor)
    gaps = repository.missing_reading_expansions(
        job["project_id"], job["import_job_id"]
    )
    if gaps and job["status"] in {"CANCELLED", "PAUSED", "FAILED_FINAL"}:
        raise KernelError(
            "READING_RECOVERY_JOB_BLOCKED", "job does not permit expansion recovery"
        )
    operations = []
    for gap in gaps:
        parent = gap["planning_operation_id"]
        require_curated_operation_current(
            SourceAuthorityRepository(uow.cursor), job["project_id"], parent
        )
        key = "reading-expansion-repair:" + corpus_hash(
            {"job": job["import_job_id"], **gap}
        )
        operation = app._admit_child(
            definition_name="source.import.corpus.analysis",
            project_id=job["project_id"],
            workspace_id=job["workspace_id"],
            actor_id=actor,
            idempotency_key=key,
            trace_id=key,
            correlation_id=key,
            causation_id=parent,
            parent_operation_id=parent,
            payload={
                "import_job_id": job["import_job_id"],
                "reading_expansion_repair": gap,
            },
            input_assets=(
                {
                    "asset_version_id": gap["analysis_plan_asset_version_id"],
                    "role": "source_analysis_plan",
                },
            ),
            ready=False,
        )
        repository.register_work(
            {
                "work_id": str(uuid4()),
                "project_id": job["project_id"],
                "import_job_id": job["import_job_id"],
                "work_kind": "WORK",
                "stable_key": key,
                "source_path": "reading-recovery:" + gap["processing_id"],
                "target_asset_version_id": gap["analysis_plan_asset_version_id"],
                "operation_id": operation,
                "status": "PLANNED",
                "result": {},
                "failure": {},
            }
        )
        app._ready_child(
            operation_id=operation,
            project_id=job["project_id"],
            actor_id=actor,
            trace_id=key,
            correlation_id=key,
            causation_id=parent,
            reason="reconcile missing frozen reading expansion",
        )
        operations.append(operation)
    if operations and job["status"] != "PROCESSING":
        repository.transition_job(
            project_id=job["project_id"],
            import_job_id=job["import_job_id"],
            expected=(job["status"],),
            target="PROCESSING",
        )
    return operations


def execute_expansion_repair(runtime, worker, job, payload):
    from novel_forge.modules.authority_handler_runtime.runtime import (
        require_current_fence,
    )
    from novel_forge.modules.source_import.analysis_profiles import (
        analysis_strategy_from_dict,
    )
    from novel_forge.modules.source_import.profiling import LogicalDocumentScope
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork
    from .narrative_execution import initial_reading_payload, _queue

    app = runtime.app
    gap = payload["reading_expansion_repair"]
    with AuthorityUnitOfWork(app.database_url, coordinate_nested=True) as uow:
        require_current_fence(uow, worker)
        require_curated_operation_current(
            SourceAuthorityRepository(uow.cursor),
            worker.project_id,
            worker.causation_id,
        )
        repository = SourceImportRepository(uow.cursor)
        original = repository.frozen_operation(
            worker.project_id, gap["planning_operation_id"]
        )["payload"]
        work = repository.work_by_operation(
            project_id=worker.project_id,
            operation_id=gap["planning_operation_id"],
            for_update=True,
        )
        if (
            work["status"] not in {"SUCCEEDED", "REUSED"}
            or work["result"].get("analysis_plan_asset_version_id")
            != gap["analysis_plan_asset_version_id"]
        ):
            raise KernelError(
                "READING_RECOVERY_PLAN_CHANGED",
                "repair requires the exact completed planning fact",
            )
        strategy = analysis_strategy_from_dict(
            original["analysis_strategy"],
            expected_fingerprint=original["analysis_strategy_fingerprint"],
        )
        child = _queue(
            app,
            uow,
            worker,
            job,
            initial_reading_payload(
                gap["planning_operation_id"],
                job,
                original["reading_plan"],
                LogicalDocumentScope(**original["logical_document_scope"]),
                strategy,
                gap["analysis_plan_asset_version_id"],
            ),
        )
        result = runtime._finish(
            worker,
            job,
            {
                "stage": "READING_EXPANSION_REPAIRED",
                "repaired_planning_operation_id": gap["planning_operation_id"],
                "first_reading_operation_id": child,
                "historical_result_unchanged": True,
                "model_calls": 0,
            },
        )
        uow.commit()
        return result

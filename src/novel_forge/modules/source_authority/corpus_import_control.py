from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.cancellation import (
    CancelCommand,
    request_cancellation,
    resolve_cancellation,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.source_import_repositories import SourceImportRepository


def control_corpus_import(
    repository: Any,
    action: Any,
    *,
    project_id: str,
    workspace_id: str,
    operation_id: str,
    database_url: str,
) -> dict[str, Any]:
    imports = SourceImportRepository(repository.cursor)
    job = imports.job_for_update(
        project_id=project_id, import_job_id=action.import_job_id
    )
    if job["source_type"] != "corpus_content" or job["workspace_id"] != workspace_id:
        raise KernelError(
            "CORPUS_IMPORT_SCOPE_INVALID",
            "control requires this workspace's Corpus content job",
        )
    if job["status"] != action.expected_status:
        raise KernelError(
            "CORPUS_IMPORT_CONTROL_CONFLICT",
            "job status changed; inspect and submit a new decision",
        )
    if action.control == "RESUME":
        if job["status"] != "PAUSED":
            raise KernelError(
                "CORPUS_IMPORT_NOT_PAUSED",
                "resume control only reopens a paused coordinator",
            )
        target = "PROCESSING"
    else:
        if job["status"] in {"IMPORTED", "CANCELLED", "FAILED_FINAL", "PREVIEWED"}:
            raise KernelError(
                "CORPUS_IMPORT_TERMINAL", "completed facts remain immutable"
            )
        target = "PAUSED" if action.control == "PAUSE" else "CANCELLED"
    imports.transition_job(
        project_id=project_id,
        import_job_id=job["import_job_id"],
        expected=(job["status"],),
        target=target,
    )
    cancellations = []
    if action.control == "CANCEL":
        repository.cursor.execute(
            """SELECT o.operation_id,o.version,o.status FROM authority_source_import_work w
            JOIN authority_operation o USING(operation_id) WHERE w.import_job_id=%s AND w.project_id=%s ORDER BY o.operation_id FOR UPDATE OF o""",
            [job["import_job_id"], project_id],
        )
        operations = repository.cursor.fetchall()
        for identity, version, status in operations:
            if status not in {
                "READY",
                "EXECUTING",
                "WAITING_CHILDREN",
                "WAITING_EXTERNAL_RESULT",
                "WAITING_GATE",
                "FAILED_RETRYABLE",
            }:
                continue
            result = request_cancellation(
                database_url,
                CancelCommand(
                    operation_id=identity,
                    project_id=project_id,
                    actor_id="source-authority",
                    reason=action.reason,
                    expected_version=int(version),
                    idempotency_key=f"corpus-cancel:{operation_id}:{identity}",
                    trace_id=operation_id,
                    correlation_id=operation_id,
                    causation_id=operation_id,
                ),
            )
            repository.cursor.execute(
                "SELECT version,status FROM authority_operation WHERE operation_id=%s",
                [identity],
            )
            current_version, current_status = repository.cursor.fetchone()
            repository.cursor.execute(
                "SELECT EXISTS(SELECT 1 FROM authority_attempt WHERE operation_id=%s AND status IN ('RUNNING','LEASED','QUEUED')), EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=%s )",
                [identity, identity],
            )
            active, has_effect = repository.cursor.fetchone()
            if (
                current_status == "CANCELLATION_REQUESTED"
                and not active
                and not has_effect
            ):
                resolve_cancellation(
                    database_url,
                    operation_id=identity,
                    project_id=project_id,
                    expected_version=int(current_version),
                    resolution="no_external_effect",
                    actor_id="source-authority",
                    reason=action.reason,
                    trace_id=operation_id,
                    correlation_id=operation_id,
                )
                imports.update_work(
                    project_id=project_id,
                    operation_id=identity,
                    expected=("PLANNED", "RUNNING", "FAILED_RETRYABLE"),
                    status="CANCELLED",
                )
            cancellations.append({"operation_id": identity, **result})
    return {
        "import_job_id": job["import_job_id"],
        "control": action.control,
        "previous_status": job["status"],
        "status": target,
        "reason": action.reason,
        "cancellations": cancellations,
        "pause_boundary": "CURRENT_STAGE_MAY_FINISH; NO_NEW_STAGE_STARTS",
    }

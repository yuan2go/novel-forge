"""INVARIANT: Retention-aware orphan discovery for authoritative object references.

The scanner only marks candidates. Physical deletion remains an explicit
``object_store.delete`` External Effect through ``release_blob`` so a database
scan can never silently remove an object.
"""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from novel_forge.modules.command_kernel.asset_runtime import AssetCommandContext
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


def detect_object_store_orphans(
    database_url: str,
    context: AssetCommandContext,
    *,
    minimum_age_seconds: int = 24 * 60 * 60,
    gc_grace_seconds: int = 7 * 24 * 60 * 60,
) -> dict[str, Any]:
    if minimum_age_seconds < 0 or gc_grace_seconds <= 0:
        raise KernelError("OBJECT_LIFECYCLE_POLICY_INVALID", "orphan/GC windows are invalid")
    with AuthorityUnitOfWork(database_url) as uow:
        repository = uow.repositories.asset_blobs
        repository.require_executing_operation(context.operation_id, context.project_id)
        resolved = repository.clear_resolved_orphans(project_id=context.project_id)
        detected = repository.detect_orphans(
            project_id=context.project_id,
            operation_id=context.operation_id,
            minimum_age_seconds=minimum_age_seconds,
            gc_grace_seconds=gc_grace_seconds,
        )
        repository.record_event(
            {
                "event_id": str(uuid4()),
                "audit_id": str(uuid4()),
                "outbox_id": str(uuid4()),
                "aggregate_type": "object_store_lifecycle",
                "aggregate_id": context.project_id,
                "operation_id": context.operation_id,
                "project_id": context.project_id,
                "event_type": "object_store.orphan_scan.completed",
                "correlation_id": context.correlation_id,
                "causation_id": context.causation_id,
                "payload": {
                    "schema_version": "object-store-orphan-scan.v1",
                    "trace_id": context.trace_id,
                    "operation_id": context.operation_id,
                    "minimum_age_seconds": minimum_age_seconds,
                    "gc_grace_seconds": gc_grace_seconds,
                    "detected_blob_ids": detected,
                    "resolved_blob_ids": resolved,
                    "physical_deletion_scheduled": False,
                },
            }
        )
        uow.commit()
    return {
        "schema_version": "object-store-orphan-scan.v1",
        "operation_id": context.operation_id,
        "detected_blob_ids": detected,
        "resolved_blob_ids": resolved,
        "physical_deletion_scheduled": False,
    }


def list_object_store_gc_candidates(
    database_url: str, *, project_id: str, limit: int = 100
) -> list[dict[str, Any]]:
    if not project_id or limit <= 0 or limit > 1000:
        raise KernelError("OBJECT_LIFECYCLE_QUERY_INVALID", "project_id/limit is invalid")
    with AuthorityUnitOfWork(database_url) as uow:
        return uow.repositories.asset_blobs.gc_candidates(
            project_id=project_id,
            limit=limit,
        )


__all__ = ["detect_object_store_orphans", "list_object_store_gc_candidates"]

"""Read-only evidence manifest for the bounded PostgreSQL chapter proof."""
from __future__ import annotations

from typing import Any

from novel_forge.modules.chapter_authority.contracts import ChapterNode
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


def build_chapter_slice_evidence_manifest(
    database_url: str,
    *,
    project_id: str,
    root_operation_id: str,
) -> dict[str, Any]:
    by_definition = {node.definition_name: node.value for node in ChapterNode}
    with AuthorityUnitOfWork(database_url) as uow:
        cursor = uow.cursor
        cursor.execute(
            """
            SELECT operation_id, definition_name, definition_version, status,
                   version, trace_id, correlation_id, input_asset_snapshot
            FROM authority_operation
            WHERE project_id = %s AND root_operation_id = %s
            ORDER BY created_at, operation_id
            """,
            [project_id, root_operation_id],
        )
        operations = [
            {
                "operation_id": row[0],
                "definition_name": row[1],
                "definition_version": row[2],
                "status": row[3],
                "version": row[4],
                "trace_id": row[5],
                "correlation_id": row[6],
                "input_asset_snapshot": row[7],
            }
            for row in cursor.fetchall()
        ]
        if not operations:
            raise KernelError("CHAPTER_SLICE_NOT_FOUND", "chapter root evidence does not exist")
        root = next(
            (item for item in operations if item["operation_id"] == root_operation_id),
            None,
        )
        if root is None:
            raise KernelError("CHAPTER_SLICE_ROOT_INVALID", "operation is not the requested root")
        cursor.execute(
            """
            SELECT saga_id, status, coordinator_fencing_token,
                   forward_recovery_attempts
            FROM authority_saga WHERE root_operation_id = %s
            """,
            [root_operation_id],
        )
        saga_row = cursor.fetchone()
        if saga_row is None:
            raise KernelError("CHAPTER_SLICE_SAGA_MISSING", "chapter Saga evidence is missing")
        saga = {
            "saga_id": saga_row[0],
            "status": saga_row[1],
            "coordinator_fencing_token": saga_row[2],
            "forward_recovery_attempts": saga_row[3],
        }
        cursor.execute(
            """
            SELECT binding.operation_id, operation.definition_name, asset.asset_type,
                   binding.asset_version_id, binding.output_key, binding.role,
                   binding.content_hash
            FROM authority_operation_output_asset AS binding
            JOIN authority_operation AS operation
              ON operation.operation_id = binding.operation_id
            JOIN authority_asset AS asset ON asset.asset_id = binding.asset_id
            WHERE operation.root_operation_id = %s
            ORDER BY operation.created_at
            """,
            [root_operation_id],
        )
        outputs = [
            {
                "operation_id": row[0],
                "node": by_definition.get(row[1], row[1]),
                "asset_type": row[2],
                "asset_version_id": row[3],
                "output_key": row[4],
                "role": row[5],
                "content_hash": row[6],
            }
            for row in cursor.fetchall()
        ]
        cursor.execute(
            """
            SELECT operation.definition_name, COUNT(attempt.attempt_id),
                   (ARRAY_AGG(attempt.status ORDER BY attempt.attempt_number DESC))[1]
            FROM authority_operation AS operation
            JOIN authority_attempt AS attempt ON attempt.operation_id = operation.operation_id
            WHERE operation.root_operation_id = %s
            GROUP BY operation.definition_name
            """,
            [root_operation_id],
        )
        attempts = cursor.fetchall()
        cursor.execute(
            """
            SELECT DISTINCT ON (operation.definition_name)
                   operation.definition_name, qualification.decision
            FROM authority_operation AS operation
            JOIN authority_operation_output_asset AS binding
              ON binding.operation_id = operation.operation_id
            JOIN authority_asset_qualification AS qualification
              ON qualification.asset_version_id = binding.asset_version_id
            WHERE operation.root_operation_id = %s
            ORDER BY operation.definition_name, qualification.created_at DESC,
                     qualification.qualification_id DESC
            """,
            [root_operation_id],
        )
        qualifications = cursor.fetchall()
        cursor.execute(
            """
            SELECT blob.status, effect.status, dispatch.status, receipt.status,
                   blob.blob_id, effect.external_effect_id, dispatch.dispatch_id
            FROM authority_operation AS operation
            JOIN authority_operation_output_asset AS binding
              ON binding.operation_id = operation.operation_id
            JOIN authority_asset_version_blob_reference AS reference
              ON reference.asset_version_id = binding.asset_version_id
             AND reference.role = 'content'
            JOIN authority_blob AS blob ON blob.blob_id = reference.blob_id
            JOIN authority_external_effect AS effect
              ON effect.external_effect_id = blob.upload_effect_id
            JOIN authority_external_effect_dispatch AS dispatch
              ON dispatch.external_effect_id = effect.external_effect_id
            JOIN authority_external_receipt AS receipt
              ON receipt.dispatch_id = dispatch.dispatch_id
            WHERE operation.root_operation_id = %s
              AND operation.definition_name = %s
            ORDER BY dispatch.generation DESC
            LIMIT 1
            """,
            [root_operation_id, ChapterNode.EXPORT.definition_name],
        )
        export_row = cursor.fetchone()
        if export_row is None:
            raise KernelError("CHAPTER_EXPORT_EVIDENCE_MISSING", "verified Export evidence is missing")
        counts: dict[str, int] = {}
        for table in ("state_event", "audit_log", "outbox_event"):
            cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE project_id = %s", [project_id])
            counts[table] = int(cursor.fetchone()[0])

    return {
        "project_id": project_id,
        "root": root,
        "saga": saga,
        "operations": operations,
        "outputs": outputs,
        "operation_statuses": {
            by_definition[item["definition_name"]]: item["status"]
            for item in operations
            if item["definition_name"] in by_definition
        },
        "attempt_counts": {
            by_definition[row[0]]: int(row[1]) for row in attempts if row[0] in by_definition
        },
        "attempt_terminal_statuses": {
            by_definition[row[0]]: row[2] for row in attempts if row[0] in by_definition
        },
        "qualification_decisions": {
            by_definition[row[0]]: row[1]
            for row in qualifications
            if row[0] in by_definition
        },
        "export": {
            "blob_status": export_row[0],
            "effect_status": export_row[1],
            "dispatch_status": export_row[2],
            "receipt_status": export_row[3],
            "blob_id": export_row[4],
            "external_effect_id": export_row[5],
            "dispatch_id": export_row[6],
        },
        "evidence_counts": counts,
    }

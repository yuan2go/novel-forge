from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.content_authority.codecs import CONTENT_CODECS
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


class ContentAuthorityQuery:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def list_operations(self, *, project_id: str, limit: int = 100, idempotency_key: str = "") -> list[dict[str, Any]]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT operation_id, definition_name, definition_version, status,
                       actor_id, trace_id, correlation_id, created_at, updated_at
                FROM authority_operation
                WHERE project_id = %s AND definition_name = ANY(%s)
                  AND (%s='' OR idempotency_key=%s)
                ORDER BY created_at DESC LIMIT %s
                """,
                [project_id, list(CONTENT_CODECS), idempotency_key, idempotency_key, limit],
            )
            rows = uow.cursor.fetchall()
        keys = (
            "operation_id", "definition_name", "definition_version", "status",
            "actor_id", "trace_id", "correlation_id", "created_at", "updated_at",
        )
        return [dict(zip(keys, row, strict=True)) for row in rows]

    def require_operation(self, *, project_id: str, operation_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT operation_id, definition_name, definition_version, status,
                       actor_id, command_payload, input_asset_snapshot,
                       trace_id, correlation_id, created_at, updated_at
                FROM authority_operation
                WHERE operation_id = %s AND project_id = %s
                  AND definition_name = ANY(%s)
                """,
                [operation_id, project_id, list(CONTENT_CODECS)],
            )
            operation = uow.cursor.fetchone()
            if operation is None:
                raise KernelError("CONTENT_OPERATION_NOT_FOUND", "Content Operation is missing")
            uow.cursor.execute(
                """
                SELECT asset_id, asset_version_id, output_key, role, content_hash
                FROM authority_operation_output_asset
                WHERE operation_id = %s ORDER BY role, output_key
                """,
                [operation_id],
            )
            outputs = uow.cursor.fetchall()
            uow.cursor.execute(
                """
                SELECT attempt_id, attempt_number, status, worker_id, started_at, finished_at
                FROM authority_attempt WHERE operation_id = %s ORDER BY attempt_number
                """,
                [operation_id],
            )
            attempts = uow.cursor.fetchall()
        keys = (
            "operation_id", "definition_name", "definition_version", "status",
            "actor_id", "command_payload", "input_asset_snapshot", "trace_id",
            "correlation_id", "created_at", "updated_at",
        )
        return {
            **dict(zip(keys, operation, strict=True)),
            "outputs": [
                dict(zip(("asset_id", "asset_version_id", "output_key", "role", "content_hash"), row, strict=True))
                for row in outputs
            ],
            "attempts": [
                dict(zip(("attempt_id", "attempt_number", "status", "worker_id", "started_at", "finished_at"), row, strict=True))
                for row in attempts
            ],
        }


__all__ = ["ContentAuthorityQuery"]

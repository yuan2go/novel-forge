"""Strong PostgreSQL projections over the shared Command Kernel runtime."""
from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.project_authority.query import ProjectAuthorityQuery
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.worker_health import runtime_health_report


RECOVERY_STATUSES = (
    "FAILED_RETRYABLE",
    "DEAD_LETTER",
    "EXECUTING",
    "WAITING_EXTERNAL_RESULT",
    "WAITING_GATE",
    "WAITING_APPROVAL",
    "RECONCILIATION_REQUIRED",
    "COMPENSATION_REQUIRED",
    "CANCELLATION_REQUESTED",
)


class AuthorityTaskQuery:
    """Task/health views whose only source is PostgreSQL Authority state."""

    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("PostgreSQL database_url is required")
        self.database_url = database_url

    def list_tasks(
        self,
        *,
        project_id: str = "",
        operation_id: str = "",
        status: str = "",
        definition_name: str = "",
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        _validate_window(offset, limit)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT operation.operation_id, operation.root_operation_id,
                       operation.parent_operation_id, operation.project_id,
                       operation.workspace_id, operation.definition_name,
                       operation.definition_version, operation.step_key,
                       operation.status, operation.version, operation.actor_id,
                       operation.trace_id, operation.correlation_id,
                       operation.created_at, operation.updated_at,
                       attempt.attempt_id, attempt.attempt_number,
                       attempt.status, attempt.worker_id, attempt.error,
                       lease.fencing_token, lease.owner, lease.expires_at,
                       saga.saga_id, saga.status
                FROM authority_operation AS operation
                LEFT JOIN LATERAL (
                    SELECT attempt_id, attempt_number, status, worker_id, error
                    FROM authority_attempt
                    WHERE operation_id = operation.operation_id
                    ORDER BY attempt_number DESC LIMIT 1
                ) AS attempt ON TRUE
                LEFT JOIN LATERAL (
                    SELECT fencing_token, owner, expires_at
                    FROM authority_lease_acquisition
                    WHERE attempt_id = attempt.attempt_id AND status = 'HELD'
                    ORDER BY fencing_token DESC LIMIT 1
                ) AS lease ON TRUE
                LEFT JOIN authority_saga AS saga
                  ON saga.root_operation_id = operation.root_operation_id
                WHERE (%s = '' OR operation.project_id = %s)
                  AND (%s = '' OR operation.operation_id = %s)
                  AND (%s = '' OR operation.status = %s)
                  AND (%s = '' OR operation.definition_name = %s)
                ORDER BY operation.updated_at DESC, operation.operation_id
                OFFSET %s LIMIT %s
                """,
                [
                    project_id, project_id, operation_id, operation_id, status, status,
                    definition_name, definition_name, offset, limit,
                ],
            )
            rows = uow.cursor.fetchall()
            uow.cursor.execute(
                """
                SELECT COUNT(*) FROM authority_operation AS operation
                WHERE (%s = '' OR operation.project_id = %s)
                  AND (%s = '' OR operation.operation_id = %s)
                  AND (%s = '' OR operation.status = %s)
                  AND (%s = '' OR operation.definition_name = %s)
                """,
                [
                    project_id, project_id, operation_id, operation_id,
                    status, status, definition_name, definition_name,
                ],
            )
            total = int(uow.cursor.fetchone()[0])
        items = [_task_row(row) for row in rows]
        by_status: dict[str, int] = {}
        by_step: dict[str, int] = {}
        for item in items:
            by_status[item["status"]] = by_status.get(item["status"], 0) + 1
            step = item["step"] or item["task_type"]
            by_step[step] = by_step.get(step, 0) + 1
        return {
            "items": items,
            "tasks": items,
            "latest": items,
            "total": total,
            "offset": offset,
            "limit": limit,
            "summary": {
                "task_count": total,
                "workflow_run_count": len(
                    {item["root_operation_id"] for item in items}
                ),
                "by_status": by_status,
                "by_step": by_step,
            },
            "timeline": {"events": [], "summary": {"source": "state_event"}},
            "recovery": [],
            "page": {"offset": offset, "limit": limit, "total": total},
            "pagination": {
                "offset": offset,
                "limit": limit,
                "next_offset": offset + limit if offset + limit < total else None,
            },
            "authority": "postgresql",
        }

    def require_task(self, *, project_id: str, operation_id: str) -> dict[str, Any]:
        result = self.list_tasks(
            project_id=project_id, operation_id=operation_id, limit=1
        )
        if result["items"]:
            return result["items"][0]
        raise KernelError("OPERATION_NOT_FOUND", "authoritative task does not exist")

    def timeline(
        self, *, project_id: str = "", operation_id: str = "", limit: int = 200
    ) -> list[dict[str, Any]]:
        _validate_window(0, limit)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT event_id, aggregate_type, aggregate_id, project_id,
                       event_type, event_version, sequence_number,
                       correlation_id, causation_id, payload, created_at
                FROM state_event
                WHERE (%s = '' OR project_id = %s)
                  AND (%s = '' OR aggregate_id = %s
                       OR payload->>'operation_id' = %s)
                ORDER BY created_at DESC, event_id DESC LIMIT %s
                """,
                [project_id, project_id, operation_id, operation_id, operation_id, limit],
            )
            rows = uow.cursor.fetchall()
        keys = (
            "event_id", "aggregate_type", "aggregate_id", "project_id",
            "event_type", "event_version", "sequence_number", "correlation_id",
            "causation_id", "payload", "created_at",
        )
        return [dict(zip(keys, row, strict=True)) for row in rows]

    def recovery_workbench(
        self, *, project_id: str = "", limit: int = 100
    ) -> dict[str, Any]:
        _validate_window(0, limit)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT operation_id, root_operation_id, project_id, workspace_id,
                       definition_name, status, version, trace_id, correlation_id,
                       metadata, updated_at
                FROM authority_operation
                WHERE status = ANY(%s)
                  AND (%s = '' OR project_id = %s)
                ORDER BY updated_at DESC LIMIT %s
                """,
                [list(RECOVERY_STATUSES), project_id, project_id, limit],
            )
            operations = [
                dict(zip(
                    (
                        "operation_id", "root_operation_id", "project_id",
                        "workspace_id", "definition_name", "status", "version",
                        "trace_id", "correlation_id", "metadata", "updated_at",
                    ),
                    row,
                    strict=True,
                ))
                for row in uow.cursor.fetchall()
            ]
            uow.cursor.execute(
                """
                SELECT external_effect_id, operation_id, project_id, effect_type,
                       capability, provider, status, stable_idempotency_key,
                       reconciliation, created_at
                FROM authority_external_effect
                WHERE status = 'UNKNOWN'
                  AND (%s = '' OR project_id = %s)
                ORDER BY created_at DESC LIMIT %s
                """,
                [project_id, project_id, limit],
            )
            unknown_effects = [
                dict(zip(
                    (
                        "external_effect_id", "operation_id", "project_id",
                        "effect_type", "capability", "provider", "status",
                        "stable_idempotency_key", "reconciliation", "created_at",
                    ),
                    row,
                    strict=True,
                ))
                for row in uow.cursor.fetchall()
            ]
            uow.cursor.execute(
                """
                SELECT outbox_id, event_id, project_id, topic, status,
                       attempt_count, last_error, dead_letter_at, updated_at
                FROM outbox_event
                WHERE status = 'dead_letter'
                  AND (%s = '' OR project_id = %s)
                ORDER BY updated_at DESC LIMIT %s
                """,
                [project_id, project_id, limit],
            )
            outbox_dead_letters = [
                dict(zip(
                    (
                        "outbox_id", "event_id", "project_id", "topic", "status",
                        "attempt_count", "last_error", "dead_letter_at", "updated_at",
                    ),
                    row,
                    strict=True,
                ))
                for row in uow.cursor.fetchall()
            ]
            uow.cursor.execute(
                """
                SELECT recovery_command_id, operation_id, project_id, actor_id,
                       expected_version, recovery_action, reason, trace_id,
                       correlation_id, created_at
                FROM authority_recovery_command
                WHERE (%s = '' OR project_id = %s)
                ORDER BY created_at DESC LIMIT %s
                """,
                [project_id, project_id, limit],
            )
            operation_recovery_commands = [
                dict(zip(
                    (
                        "recovery_command_id", "operation_id", "project_id",
                        "actor_id", "expected_version", "recovery_action", "reason",
                        "trace_id", "correlation_id", "created_at",
                    ),
                    row,
                    strict=True,
                ))
                for row in uow.cursor.fetchall()
            ]
            uow.cursor.execute(
                """
                SELECT recovery_command_id, outbox_id, replacement_outbox_id,
                       project_id, actor_id, expected_attempt_count,
                       recovery_action, reason, trace_id, correlation_id, created_at
                FROM authority_outbox_recovery_command
                WHERE (%s = '' OR project_id = %s)
                ORDER BY created_at DESC LIMIT %s
                """,
                [project_id, project_id, limit],
            )
            outbox_recovery_commands = [
                dict(zip(
                    (
                        "recovery_command_id", "outbox_id", "replacement_outbox_id",
                        "project_id", "actor_id", "expected_attempt_count",
                        "recovery_action", "reason", "trace_id", "correlation_id",
                        "created_at",
                    ),
                    row,
                    strict=True,
                ))
                for row in uow.cursor.fetchall()
            ]
        return {
            "operations": operations,
            "unknown_external_effects": unknown_effects,
            "outbox_dead_letters": outbox_dead_letters,
            "operation_recovery_commands": operation_recovery_commands,
            "outbox_recovery_commands": outbox_recovery_commands,
            "authority": "postgresql",
        }

    def system_health(self, *, project_id: str = "") -> dict[str, Any]:
        runtime = runtime_health_report(self.database_url)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT status, COUNT(*) FROM authority_operation
                WHERE (%s = '' OR project_id = %s) GROUP BY status
                """,
                [project_id, project_id],
            )
            operation_counts = {str(row[0]): int(row[1]) for row in uow.cursor.fetchall()}
            uow.cursor.execute(
                """
                SELECT status, health, COUNT(*) FROM authority_project
                WHERE (%s = '' OR project_id = %s) GROUP BY status, health
                """,
                [project_id, project_id],
            )
            project_counts = [
                {"status": row[0], "health": row[1], "count": int(row[2])}
                for row in uow.cursor.fetchall()
            ]
            uow.cursor.execute(
                """
                SELECT COUNT(*) FROM authority_asset
                WHERE (%s = '' OR project_id = %s)
                """,
                [project_id, project_id],
            )
            asset_count = int(uow.cursor.fetchone()[0])
            uow.cursor.execute(
                """
                SELECT COUNT(*) FROM outbox_event
                WHERE status = 'dead_letter'
                  AND (%s = '' OR project_id = %s)
                """,
                [project_id, project_id],
            )
            outbox_dead_letter_count = int(uow.cursor.fetchone()[0])
        failed = self.list_tasks(
            project_id=project_id, status="FAILED_FINAL", limit=100
        )["items"]
        dead = self.list_tasks(
            project_id=project_id, status="DEAD_LETTER", limit=100
        )["items"]
        scope = ProjectAuthorityQuery(self.database_url).scope_audit(
            project_id=project_id or None
        )
        task_count = sum(operation_counts.values())
        dead_letter_count = len(dead) + outbox_dead_letter_count
        return {
            **runtime,
            "operation_counts": operation_counts,
            "project_counts": project_counts,
            "project_id": project_id,
            "storage_authority": "postgresql",
            "filesystem_authority": False,
            "legacy_task_authority": False,
            "heartbeat": runtime["generated_at"],
            "dead_letter_count": dead_letter_count,
            "summary": {
                "asset_count": asset_count,
                "task_count": task_count,
                "failed_task_count": len(failed),
                "pending_handoff_count": 0,
                "scope_issue_count": len(scope["findings"]),
                "dead_letter_count": dead_letter_count,
            },
            "scope_audit": scope,
            "postgres": {
                "status": "ready",
                "strict": True,
                "authority": "postgresql",
            },
            "embedding": {
                "status": "advisory",
                "authority": False,
                "rebuildable_index": True,
            },
            "task_control": {
                "scheduler": "authority_worker",
            },
            "queue_trend": [],
            "recent_failures": [*failed, *dead][:100],
            "handoffs": [],
            "backups": [],
        }


def _validate_window(offset: int, limit: int) -> None:
    if offset < 0 or limit < 1 or limit > 500:
        raise ValueError("offset must be non-negative and limit must be between 1 and 500")


def _task_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "operation_id": row[0],
        "path": f"authority://operation/{row[0]}",
        "id": row[0],
        "root_operation_id": row[1],
        "run_id": row[1],
        "parent_operation_id": row[2] or "",
        "project_id": row[3],
        "workspace_id": row[4],
        "definition_name": row[5],
        "task_type": row[5],
        "definition_version": row[6],
        "step_key": row[7] or "",
        "step": row[7] or row[5],
        "status": row[8],
        "version": int(row[9]),
        "actor_id": row[10],
        "trace_id": row[11],
        "correlation_id": row[12],
        "created_at": row[13],
        "updated_at": row[14],
        "recorded_at": row[14],
        "error_message": str((row[19] or {}).get("message") or ""),
        "message": str((row[19] or {}).get("message") or ""),
        "attempt": {
            "attempt_id": row[15],
            "attempt_number": int(row[16]) if row[16] is not None else None,
            "status": row[17],
            "worker_id": row[18],
            "error": row[19] or {},
        } if row[15] else {},
        "lease": {
            "fencing_token": int(row[20]),
            "owner": row[21],
            "expires_at": row[22],
        } if row[20] is not None else {},
        "saga": {"saga_id": row[23], "status": row[24]} if row[23] else {},
    }


__all__ = ["AuthorityTaskQuery", "RECOVERY_STATUSES"]

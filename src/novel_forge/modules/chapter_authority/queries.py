"""Strong PostgreSQL queries for authoritative chapter runs."""
from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


class ChapterAuthorityQuery:
    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("PostgreSQL database_url is required")
        self.database_url = database_url

    def list_runs(self, *, project_id: str, limit: int = 100) -> list[dict[str, Any]]:
        if not project_id:
            raise ValueError("project_id is required for chapter run queries")
        if limit < 1 or limit > 500:
            raise ValueError("chapter run query limit must be between 1 and 500")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT root.operation_id, root.status, root.version, root.workspace_id,
                       root.trace_id, root.correlation_id, root.command_payload,
                       root.created_at, root.updated_at, saga.saga_id, saga.status,
                       COUNT(child.operation_id) FILTER (
                           WHERE child.operation_id <> root.operation_id
                       ) AS child_count,
                       COUNT(child.operation_id) FILTER (
                           WHERE child.operation_id <> root.operation_id
                             AND child.status = 'SUCCEEDED'
                       ) AS succeeded_child_count
                FROM authority_operation AS root
                LEFT JOIN authority_saga AS saga
                  ON saga.root_operation_id = root.operation_id
                LEFT JOIN authority_operation AS child
                  ON child.root_operation_id = root.operation_id
                WHERE root.project_id = %s
                  AND root.definition_name = 'chapter.slice.run'
                  AND root.operation_id = root.root_operation_id
                GROUP BY root.operation_id, saga.saga_id, saga.status
                ORDER BY root.created_at DESC, root.operation_id
                LIMIT %s
                """,
                [project_id, limit],
            )
            rows = uow.cursor.fetchall()
        return [
            {
                "root_operation_id": row[0],
                "project_id": project_id,
                "status": row[1],
                "version": int(row[2]),
                "workspace_id": row[3],
                "trace_id": row[4],
                "correlation_id": row[5],
                "chapter": int((row[6] or {}).get("chapter") or 0),
                "title": str((row[6] or {}).get("title") or ""),
                "created_at": str(row[7]),
                "updated_at": str(row[8]),
                "saga_id": row[9] or "",
                "saga_status": row[10] or "",
                "child_count": int(row[11]),
                "succeeded_child_count": int(row[12]),
            }
            for row in rows
        ]

    def require_run(
        self,
        *,
        project_id: str,
        root_operation_id: str,
    ) -> dict[str, Any]:
        if not project_id or not root_operation_id:
            raise ValueError("project_id and root_operation_id are required")
        with AuthorityUnitOfWork(self.database_url) as uow:
            cursor = uow.cursor
            cursor.execute(
                """
                SELECT operation_id, status, version, workspace_id, trace_id,
                       correlation_id, command_payload, created_at, updated_at
                FROM authority_operation
                WHERE operation_id = %s AND root_operation_id = %s
                  AND project_id = %s AND definition_name = 'chapter.slice.run'
                """,
                [root_operation_id, root_operation_id, project_id],
            )
            root = cursor.fetchone()
            if root is None:
                raise KernelError("CHAPTER_RUN_NOT_FOUND", "authoritative chapter run does not exist")
            cursor.execute(
                """
                SELECT operation_id, definition_name, definition_version, status,
                       version, parent_operation_id, step_key, created_at, updated_at
                FROM authority_operation
                WHERE root_operation_id = %s AND project_id = %s
                ORDER BY created_at, operation_id
                """,
                [root_operation_id, project_id],
            )
            operations = [
                {
                    "operation_id": row[0],
                    "definition_name": row[1],
                    "definition_version": row[2],
                    "status": row[3],
                    "version": int(row[4]),
                    "parent_operation_id": row[5] or "",
                    "step_key": row[6] or "",
                    "created_at": str(row[7]),
                    "updated_at": str(row[8]),
                }
                for row in cursor.fetchall()
            ]
            operation_ids = [row["operation_id"] for row in operations]
            cursor.execute(
                """
                SELECT binding.operation_id, binding.output_key, binding.role,
                       binding.asset_id, binding.asset_version_id, binding.content_hash,
                       asset.asset_type, version.lifecycle, version.eligibility,
                       version.governance
                FROM authority_operation_output_asset AS binding
                JOIN authority_asset AS asset ON asset.asset_id = binding.asset_id
                JOIN authority_asset_version AS version
                  ON version.asset_version_id = binding.asset_version_id
                WHERE binding.operation_id = ANY(%s) AND binding.role = 'primary'
                ORDER BY binding.created_at, binding.operation_id
                """,
                [operation_ids],
            )
            primary_outputs = [
                {
                    "operation_id": row[0],
                    "output_key": row[1],
                    "role": row[2],
                    "asset_id": row[3],
                    "asset_version_id": row[4],
                    "content_hash": row[5],
                    "asset_type": row[6],
                    "lifecycle": row[7],
                    "eligibility": row[8],
                    "governance": row[9],
                }
                for row in cursor.fetchall()
            ]
            cursor.execute(
                """
                SELECT external_effect_id, operation_id, capability, provider,
                       status, completion_policy, stable_idempotency_key,
                       created_at
                FROM authority_external_effect
                WHERE operation_id = ANY(%s) AND effect_type = 'model.invoke'
                ORDER BY created_at, external_effect_id
                """,
                [operation_ids],
            )
            model_effects = [
                {
                    "external_effect_id": row[0],
                    "operation_id": row[1],
                    "capability": row[2],
                    "provider": row[3],
                    "status": row[4],
                    "completion_policy": row[5],
                    "stable_idempotency_key": row[6],
                    "created_at": str(row[7]),
                }
                for row in cursor.fetchall()
            ]
            cursor.execute(
                """
                SELECT saga_id, status, coordinator_owner,
                       coordinator_fencing_token, created_at, updated_at
                FROM authority_saga
                WHERE root_operation_id = %s AND project_id = %s
                """,
                [root_operation_id, project_id],
            )
            saga = cursor.fetchone()
        return {
            "root_operation_id": root[0],
            "project_id": project_id,
            "status": root[1],
            "version": int(root[2]),
            "workspace_id": root[3],
            "trace_id": root[4],
            "correlation_id": root[5],
            "command": root[6],
            "created_at": str(root[7]),
            "updated_at": str(root[8]),
            "saga": (
                {
                    "saga_id": saga[0],
                    "status": saga[1],
                    "coordinator_owner": saga[2],
                    "coordinator_fencing_token": int(saga[3]),
                    "created_at": str(saga[4]),
                    "updated_at": str(saga[5]),
                }
                if saga is not None
                else {}
            ),
            "operations": operations,
            "primary_outputs": primary_outputs,
            "model_effects": model_effects,
        }

    def require_acceptance_evidence(
        self,
        *,
        project_id: str,
        root_operation_id: str,
    ) -> dict[str, Any]:
        """Return immutable Chapter outputs and settlement state for Book acceptance."""
        run = self.require_run(
            project_id=project_id,
            root_operation_id=root_operation_id,
        )
        operation_ids = [item["operation_id"] for item in run["operations"]]
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT asset.asset_type, binding.output_key, binding.role,
                       version.asset_version_id, version.content_hash,
                       version.content, version.lifecycle, version.eligibility,
                       version.governance
                FROM authority_operation_output_asset AS binding
                JOIN authority_asset AS asset
                  ON asset.asset_id=binding.asset_id
                 AND asset.project_id=%s
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=binding.asset_version_id
                WHERE binding.operation_id = ANY(%s)
                ORDER BY binding.created_at, binding.output_key
                """,
                [project_id, operation_ids],
            )
            outputs = [
                {
                    "asset_type": row[0],
                    "output_key": row[1],
                    "role": row[2],
                    "asset_version_id": row[3],
                    "content_hash": row[4],
                    "content": row[5],
                    "lifecycle": row[6],
                    "eligibility": row[7],
                    "governance": row[8],
                }
                for row in uow.cursor.fetchall()
            ]
            uow.cursor.execute(
                """
                SELECT reservation_id, status, settled_amount, actual_tokens,
                       provider, evidence
                FROM authority_budget_reservation
                WHERE project_id=%s AND operation_id = ANY(%s)
                ORDER BY created_at, reservation_id
                """,
                [project_id, operation_ids],
            )
            budgets = [
                {
                    "reservation_id": row[0],
                    "status": row[1],
                    "settled_amount": str(row[2]),
                    "actual_tokens": int(row[3]),
                    "provider": row[4],
                    "evidence": row[5],
                }
                for row in uow.cursor.fetchall()
            ]
            uow.cursor.execute(
                """
                SELECT cost_evidence_id
                FROM authority_operation_cost_evidence
                WHERE operation_id = ANY(%s)
                ORDER BY recorded_at, cost_evidence_id
                """,
                [operation_ids],
            )
            cost_receipt_refs = tuple(str(row[0]) for row in uow.cursor.fetchall())
        return {
            **run,
            "outputs": outputs,
            "budgets": budgets,
            "cost_receipt_refs": cost_receipt_refs,
        }


__all__ = ["ChapterAuthorityQuery"]

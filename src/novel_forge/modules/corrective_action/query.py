from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


_FIELDS = (
    "issue_id",
    "project_id",
    "source_operation_id",
    "source_asset_version_id",
    "issue_type",
    "severity",
    "evidence_refs",
    "action_id",
    "action_type",
    "target_scope",
    "required_authority",
    "reevaluation_gate",
    "action_asset_version_id",
    "execution_operation_id",
    "execution_attempt_id",
    "result_asset_version_ids",
    "evaluation_operation_id",
    "evaluation_asset_version_id",
    "gate_result",
    "resolution",
    "status",
    "created_at",
)


class CorrectiveActionQuery:

    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("PostgreSQL database_url is required")
        self.database_url = database_url

    def list(
        self,
        *,
        project_id: str,
        status: str = "",
        issue_type: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if not project_id or not 1 <= limit <= 500:
            raise ValueError("project_id and a limit between 1 and 500 are required")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                f"""
                SELECT {", ".join(_FIELDS)}
                FROM authority_corrective_action_lineage_projection
                WHERE project_id=%s
                  AND (%s='' OR status=%s)
                  AND (%s='' OR issue_type=%s)
                ORDER BY created_at DESC, issue_id
                LIMIT %s
                """,
                [project_id, status, status, issue_type, issue_type, limit],
            )
            rows = uow.cursor.fetchall()
        return [_row(row) for row in rows]

    def require(self, *, project_id: str, issue_id: str) -> dict[str, Any]:
        if not project_id or not issue_id:
            raise ValueError("project_id and issue_id are required")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                f"""
                SELECT {", ".join(_FIELDS)}
                FROM authority_corrective_action_lineage_projection
                WHERE project_id=%s AND issue_id=%s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                [project_id, issue_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "CORRECTIVE_ISSUE_NOT_FOUND",
                "Corrective Issue does not exist in Authority lineage",
            )
        return _row(row)


def _row(row: tuple[Any, ...]) -> dict[str, Any]:
    result = dict(zip(_FIELDS, row, strict=True))
    result["lifecycle"] = _lifecycle(str(result["status"]))
    return result


def _lifecycle(status: str) -> list[str]:
    states = ["OPEN", "ADMITTED"]
    if status == "OPEN":
        return states[:1]
    if status in {"IN_PROGRESS", "APPLIED", "REEVALUATION_PENDING"}:
        states.append("IN_PROGRESS")
    if status in {"APPLIED", "REEVALUATION_PENDING"}:
        states.append("APPLIED")
    if status == "REEVALUATION_PENDING":
        states.append("REEVALUATION_PENDING")
    if status in {"RESOLVED", "FAILED", "ESCALATED", "SUPERSEDED", "CANCELLED"}:
        states.extend(["IN_PROGRESS", "APPLIED", "REEVALUATION_PENDING", status])
    return states


__all__ = ["CorrectiveActionQuery"]

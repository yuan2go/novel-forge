from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_execution.execution_template import verify_book_template


def proposed_validation(cursor: Any, *, project_id: str, book_id: str, asset_version_id: str) -> dict[str, Any] | None:
    cursor.execute("""SELECT op.command_payload #> '{payload,_creative_validation}'
        FROM authority_book_design_candidate c JOIN authority_operation op ON op.operation_id=c.created_by_operation_id
        WHERE c.project_id=%s AND c.book_id=%s AND c.asset_version_id=%s AND op.status='SUCCEEDED'""",
        [project_id, book_id, asset_version_id])
    row = cursor.fetchone()
    if not row or not row[0]:
        return None
    admission = dict(row[0])
    verify_book_template(cursor, admission)
    if (admission["project_id"], admission["book_id"]) != (project_id, book_id):
        raise KernelError("CREATIVE_BOOK_SCOPE_INVALID", asset_version_id)
    return admission


def approved_validation_book(cursor: Any, *, project_id: str, book_id: str, asset_version_id: str) -> dict[str, Any] | None:
    admission = proposed_validation(cursor, project_id=project_id, book_id=book_id, asset_version_id=asset_version_id)
    if admission is None:
        return None
    cursor.execute("""SELECT d.decision_id,d.evidence,v.content_hash,c.status,op.operation_id
        FROM authority_asset_decision d JOIN authority_operation op ON op.operation_id=d.decided_by_operation_id
        JOIN authority_asset_version v ON v.asset_version_id=d.asset_version_id
        JOIN authority_book_design_candidate c ON c.asset_version_id=v.asset_version_id
        WHERE d.project_id=%s AND d.book_id=%s AND d.asset_version_id=%s AND d.decision='APPROVE'
          AND op.status='SUCCEEDED' ORDER BY d.created_at DESC LIMIT 1""", [project_id, book_id, asset_version_id])
    row = cursor.fetchone()
    if not row or row[1].get("creative_validation") != admission or row[1].get("content_hash") != row[2] or row[3] not in {"APPROVED", "ACTIVE"}:
        raise KernelError("CREATIVE_BOOK_APPROVAL_REQUIRED", asset_version_id)
    return {**admission, "asset_version_id": asset_version_id, "content_hash": row[2],
            "decision_id": row[0], "decision_operation_id": row[4], "lifecycle": row[3]}

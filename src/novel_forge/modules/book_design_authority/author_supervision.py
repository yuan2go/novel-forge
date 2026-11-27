from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_execution.author_supervision import verify_book_supervision


def proposed_supervision(cursor: Any, *, project_id: str, book_id: str, asset_version_id: str) -> dict[str, Any] | None:
    cursor.execute("""SELECT op.command_payload #> '{payload,_author_supervision}'
        FROM authority_book_design_candidate c JOIN authority_operation op ON op.operation_id=c.created_by_operation_id
        WHERE c.project_id=%s AND c.book_id=%s AND c.asset_version_id=%s AND op.status='SUCCEEDED'""",
        [project_id, book_id, asset_version_id])
    row = cursor.fetchone()
    if not row or not row[0]:
        return None
    supervision = dict(row[0])
    verify_book_supervision(cursor, supervision)
    if (supervision["project_id"], supervision["book_id"]) != (project_id, book_id):
        raise KernelError("AUTHOR_SUPERVISION_BOOK_SCOPE", "Proposed design differs from frozen Book scope")
    return supervision


def approved_book_design_receipt(cursor: Any, *, project_id: str, book_id: str, asset_version_id: str) -> dict[str, Any] | None:
    supervision = proposed_supervision(cursor, project_id=project_id, book_id=book_id, asset_version_id=asset_version_id)
    if supervision is None:
        return None
    cursor.execute("""SELECT d.decision_id,d.decided_by,d.evidence,v.content_hash,c.status,op.operation_id
        FROM authority_asset_decision d JOIN authority_operation op ON op.operation_id=d.decided_by_operation_id
        JOIN authority_asset_version v ON v.asset_version_id=d.asset_version_id
        JOIN authority_book_design_candidate c ON c.asset_version_id=v.asset_version_id
        WHERE d.project_id=%s AND d.book_id=%s AND d.asset_version_id=%s AND d.decision='APPROVE'
          AND op.status='SUCCEEDED' ORDER BY d.created_at DESC""", [project_id, book_id, asset_version_id])
    row = cursor.fetchone()
    if (row is None or row[1] != supervision["author_id"] or row[2].get("author_supervision") != supervision
            or row[2].get("content_hash") != row[3] or row[4] not in {"APPROVED", "ACTIVE"}):
        raise KernelError("AUTHOR_SUPERVISION_APPROVAL_REQUIRED", "BookDesign requires exact native author approval")
    return {"mode": "AUTHOR_SUPERVISED", "asset_version_id": asset_version_id, "content_hash": row[3],
            "decision_id": row[0], "author_id": row[1], "decision_operation_id": row[5],
            "lifecycle": row[4], "literary_qualification": "NOT_PROVEN"}

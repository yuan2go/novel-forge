from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


def require_arc_recap_change_evidence(
    database_url: str, command: Any, asset_version_id: str, content: dict[str, Any]
) -> None:
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """SELECT recap_version.content FROM authority_operation_output_asset request
            JOIN authority_operation operation USING(operation_id)
            JOIN authority_operation_output_asset recap ON recap.operation_id=operation.operation_id
            JOIN authority_asset_version recap_version ON recap_version.asset_version_id=recap.asset_version_id
            WHERE request.asset_version_id=%s AND request.output_key='longform.recap.replan_request'
              AND recap.output_key='longform.recap.report' AND recap.asset_version_id=ANY(%s)
              AND operation.definition_name='longform.recap' AND operation.status='SUCCEEDED'
              AND operation.project_id=%s""",
            [asset_version_id, list(command.change_evidence_version_ids), command.project_id],
        )
        row = uow.cursor.fetchone()
    recap = dict(row[0]) if row else {}
    chapter_range = recap.get("chapter_range")
    impact = content.get("impact_scope")
    if (
        not row
        or recap.get("book_id") != command.book_id
        or content.get("type") != "ArcRevisionCandidate"
        or content.get("contract_version") != "arc-revision-candidate-v1"
        or content.get("candidate_only") is not True
        or content.get("plan_mutation_allowed") is not False
        or content.get("affected_scope") != "ARC"
        or not isinstance(impact, dict)
        or impact.get("future_only") is not True
        or not isinstance(chapter_range, list)
        or len(chapter_range) != 2
        or any(type(chapter) is not int for chapter in chapter_range)
        or not 0 < chapter_range[0] <= chapter_range[1]
        or type(content.get("future_from_chapter")) is not int
        or content["future_from_chapter"] != chapter_range[1] + 1
    ):
        raise KernelError(
            "PLANNING_GENERATION_CHANGE_EVIDENCE_INVALID",
            "Arc proposal requires its exact successful same-Book Recap and future-only scope",
        )

from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


def require_arc_recap_change_evidence(
    database_url: str, command: Any, asset_version_id: str, content: dict[str, Any]
) -> None:
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """SELECT recap_version.content,operation.definition_version,operation.actor_id
            FROM authority_operation_output_asset request
            JOIN authority_operation operation USING(operation_id)
            JOIN authority_operation_output_asset recap ON recap.operation_id=operation.operation_id
            JOIN authority_asset_version recap_version ON recap_version.asset_version_id=recap.asset_version_id
            WHERE request.asset_version_id=%s AND request.output_key='longform.recap.replan_request'
              AND recap.output_key='longform.recap.report' AND recap.asset_version_id=ANY(%s)
              AND operation.definition_name='longform.recap' AND operation.status='SUCCEEDED'
              AND operation.definition_version IN ('1.1.0','1.2.0')
              AND operation.project_id=%s AND operation.workspace_id=%s""",
            [asset_version_id, list(command.change_evidence_version_ids), command.project_id, command.workspace_id],
        )
        row = uow.cursor.fetchone()
        if row and row[1] == "1.2.0":
            from novel_forge.modules.book_followup_authority.accepted_realization import read_accepted_realization_deviations
            from .domain import canonical_hash
            recap = dict(row[0])
            observation = (recap.get("observation_snapshot") or {}).get("accepted_realization_deviations")
            if recap.get("contract_version") != "longform-recap-v2" or not isinstance(observation, dict):
                raise KernelError("PLANNING_GENERATION_CHANGE_EVIDENCE_INVALID", "Current Recap requires its exact accepted observation")
            actual = read_accepted_realization_deviations(uow.cursor, project_id=command.project_id,
                workspace_id=command.workspace_id, book_id=command.book_id,
                chapter_request_id=str(observation.get("chapter_request_id") or ""), actor_id=str(row[2]))
            if canonical_hash(actual) != canonical_hash(observation):
                raise KernelError("PLANNING_GENERATION_CHANGE_EVIDENCE_INVALID", "Current Recap observation differs from immutable accepted owner evidence")
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

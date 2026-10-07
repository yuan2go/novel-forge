from __future__ import annotations

from psycopg.types.json import Jsonb
from novel_forge.modules.command_kernel.budget_runtime import require_known_cli_lineage
from novel_forge.modules.command_kernel.errors import KernelError


def require_replan_retirement(
    cursor,
    *,
    project_id: str,
    payload,
    current_operation_id: str = "",
    retirement_operation_id: str = "",
):
    cursor.execute(
        """SELECT to_jsonb(owned),book.root_operation_id,book.book_id,impact.impact_id,proposal.proposal_id,
        proposal.approval_operation_id,proposal.activation_operation_id
        FROM authority_chapter_group_production owned JOIN authority_book_production book USING(book_run_id)
        JOIN authority_book_replan replan ON replan.book_run_id=book.book_run_id AND replan.replan_id=%s
        JOIN authority_plan_change_proposal proposal ON proposal.proposal_id=replan.plan_change_proposal_id
        JOIN authority_plan_change_impact impact ON impact.proposal_id=proposal.proposal_id
        JOIN story_plan_binding binding ON binding.project_id=impact.project_id AND binding.asset_version_id=impact.impacted_asset_version_id
        WHERE owned.group_run_id=%s AND owned.project_id=%s AND replan.project_id=%s AND proposal.project_id=%s
          AND owned.group_plan_version_id=%s AND impact.impacted_asset_version_id=owned.group_plan_version_id
          AND proposal.book_id=book.book_id AND proposal.status='ACTIVE'
          AND proposal.approval_operation_id IS NOT NULL AND proposal.activation_operation_id IS NOT NULL
          AND impact.target_freshness IN ('IMPACTED','STALE') AND binding.freshness IN ('IMPACTED','STALE')
          AND binding.execution_scope<>'EXECUTED' AND book.state NOT IN ('CANCELLED','ABORTED')
          AND owned.active_chapter_request_id IS NULL AND owned.version=%s
        FOR UPDATE OF owned,book""",
        [
            payload["replan_id"],
            payload["group_run_id"],
            project_id,
            project_id,
            project_id,
            payload["retired_group_plan_version_id"],
            payload["expected_group_version"],
        ],
    )
    row = cursor.fetchone()
    if not row:
        raise KernelError(
            "CHAPTER_GROUP_REPLAN_IMPACT_REQUIRED",
            "Retirement requires the exact approved same-run future impact and idle current group",
        )
    owned_step = retirement_operation_id or current_operation_id
    owned_actor = ""
    if owned_step:
        cursor.execute(
            """SELECT actor_id FROM authority_operation
            WHERE operation_id=%s AND project_id=%s AND root_operation_id=%s
              AND definition_name='chapter_group.production.supersede' AND definition_version='1.1.0'
              AND command_payload->'payload'=%s AND status=ANY(%s)""",
            [
                owned_step,
                project_id,
                row[0]["root_operation_id"],
                Jsonb(dict(payload)),
                ["SUCCEEDED"] if retirement_operation_id else ["RUNNING"],
            ],
        )
        owner = cursor.fetchone()
        if not owner:
            raise KernelError(
                "CHAPTER_GROUP_REPLAN_RETIREMENT_OWNER_INVALID",
                "Only the exact native retirement step can exempt its own lease or cancellation",
            )
        owned_actor = str(owner[0])
    require_known_cli_lineage(cursor, project_id=project_id, operation_id=row[1])
    cursor.execute(
        """SELECT EXISTS(SELECT 1 FROM authority_cancellation_command WHERE operation_id=%s)
        OR EXISTS(SELECT 1 FROM authority_cancellation_command cancellation WHERE operation_id=%s
            AND (%s=FALSE OR cancellation.actor_id<>%s OR cancellation.reason<>%s OR cancellation.project_id<>%s))
        OR EXISTS(SELECT 1 FROM authority_budget_reservation reservation JOIN authority_operation operation USING(operation_id)
            WHERE operation.root_operation_id=%s AND operation.operation_id<>%s AND reservation.status<>'SETTLED')
        OR EXISTS(SELECT 1 FROM authority_lease_acquisition lease JOIN authority_attempt attempt USING(attempt_id)
            JOIN authority_operation operation USING(operation_id) WHERE operation.root_operation_id=%s AND operation.operation_id<>%s
              AND lease.released_at IS NULL AND lease.expires_at>NOW())""",
        [
            row[1],
            row[0]["root_operation_id"],
            bool(retirement_operation_id),
            owned_actor,
            str(payload.get("reason") or ""),
            project_id,
            row[0]["root_operation_id"],
            owned_step,
            row[0]["root_operation_id"],
            owned_step,
        ],
    )
    if cursor.fetchone()[0]:
        raise KernelError(
            "CHAPTER_GROUP_REPLAN_UNSETTLED",
            "Preserve cancelled, uncertain, held or leased original work",
        )
    return tuple(str(value) for value in row[3:])

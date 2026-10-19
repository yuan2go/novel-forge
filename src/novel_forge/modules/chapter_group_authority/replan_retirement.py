from __future__ import annotations

from psycopg.types.json import Jsonb
from novel_forge.modules.command_kernel.budget_runtime import require_known_cli_lineage
from novel_forge.modules.command_kernel.errors import KernelError


def lock_replan_roots(cursor, *, project_id: str, book_root: str, group_root: str = ""):
    cursor.execute(
        """SELECT formation.formation_run_id FROM authority_story_formation_run formation
        JOIN authority_book_production book ON book.stable_idempotency_key=formation.formation_run_id||':production'
        AND book.project_id=formation.project_id AND book.book_id=formation.book_id
        WHERE book.project_id=%s AND book.root_operation_id=%s FOR UPDATE OF formation""",
        [project_id, book_root],
    )
    formations = [row[0] for row in cursor.fetchall()]
    cursor.execute("SELECT EXISTS(SELECT 1 FROM authority_story_creation_cancellation WHERE formation_run_id=ANY(%s))", [formations])
    if cursor.fetchone()[0]:
        raise KernelError("BOOK_REPLAN_CANCELLED", "Cancelled Creation cannot activate replacement input")
    for root in dict.fromkeys((book_root, group_root)):
        if root:
            cursor.execute(
                "SELECT operation_id FROM authority_operation WHERE operation_id=%s AND project_id=%s FOR UPDATE",
                [root, project_id],
            )
            if cursor.fetchone() is None:
                raise KernelError("CHAPTER_GROUP_REPLAN_OWNER_MISSING", "Replan execution root is missing")


def require_replan_activation(cursor, *, project_id: str, proposal_id: str):
    if not proposal_id:
        return
    cursor.execute(
        """SELECT book.book_run_id,book.root_operation_id,owned.group_run_id,owned.root_operation_id,replan.status
        FROM authority_book_replan replan
        JOIN authority_book_production book USING(book_run_id)
        LEFT JOIN authority_chapter_group_production owned
          ON owned.book_run_id=book.book_run_id AND owned.group_plan_version_id=replan.target_asset_version_id
        WHERE replan.project_id=%s AND replan.plan_change_proposal_id=%s AND replan.affected_scope='CHAPTER_GROUP'""",
        [project_id, proposal_id],
    )
    rows = cursor.fetchall()
    for book_run, book_root, group_run, group_root, replan_status in rows:
        lock_replan_roots(cursor, project_id=project_id, book_root=book_root, group_root=group_root)
        cursor.execute(
            "SELECT state,active_chapter_request_id FROM authority_book_production WHERE book_run_id=%s AND project_id=%s FOR UPDATE",
            [book_run, project_id],
        )
        book = cursor.fetchone()
        if not book or book[0] != 'REPLAN_GENERATING' or book[1] is not None or replan_status not in {'ACTIVE','REGENERATING'}:
            raise KernelError("CHAPTER_GROUP_REPLAN_ACTIVE_CHILD", "Activation requires the idle Book replan checkpoint")
        if group_run:
            cursor.execute(
                "SELECT active_chapter_request_id,state FROM authority_chapter_group_production WHERE group_run_id=%s AND project_id=%s FOR UPDATE",
                [group_run, project_id],
            )
            group = cursor.fetchone()
            if not group or group[0] is not None or group[1] not in {'PREPARING','READY','CLOSURE_PENDING','PAUSED'}:
                raise KernelError("CHAPTER_GROUP_REPLAN_ACTIVE_CHILD", "Activation requires the idle current ChapterGroup")
        require_known_cli_lineage(cursor, project_id=project_id, operation_id=book_root)
        cursor.execute(
            """SELECT EXISTS(SELECT 1 FROM authority_cancellation_command WHERE operation_id=ANY(%s))
            OR EXISTS(SELECT 1 FROM authority_worker_cancel_signal WHERE operation_id=ANY(%s) AND acknowledged_at IS NULL)
            OR EXISTS(SELECT 1 FROM authority_budget_reservation reservation JOIN authority_operation operation USING(operation_id)
                WHERE operation.root_operation_id=%s AND reservation.status<>'SETTLED')
            OR EXISTS(SELECT 1 FROM authority_lease_acquisition lease JOIN authority_attempt attempt USING(attempt_id)
                JOIN authority_operation operation USING(operation_id) WHERE operation.root_operation_id=%s
                  AND lease.released_at IS NULL AND lease.expires_at>NOW())""",
            [[book_root, group_root or book_root], [book_root, group_root or book_root], group_root, group_root],
        )
        if cursor.fetchone()[0]:
            raise KernelError("CHAPTER_GROUP_REPLAN_UNSETTLED", "Preserve cancelled, uncertain, held or leased original work")
    return bool(rows)


def require_replan_retirement(
    cursor,
    *,
    project_id: str,
    payload,
    current_operation_id: str = "",
    retirement_operation_id: str = "",
):
    cursor.execute(
        """SELECT book.root_operation_id,owned.root_operation_id
        FROM authority_chapter_group_production owned JOIN authority_book_production book USING(book_run_id)
        WHERE owned.group_run_id=%s AND owned.project_id=%s""",
        [payload["group_run_id"], project_id],
    )
    roots = cursor.fetchone()
    if roots:
        lock_replan_roots(cursor, project_id=project_id, book_root=roots[0], group_root=roots[1])
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
          AND owned.active_chapter_request_id IS NULL AND book.active_chapter_request_id IS NULL AND owned.version=%s
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
                ["SUCCEEDED"] if retirement_operation_id else ["EXECUTING"],
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

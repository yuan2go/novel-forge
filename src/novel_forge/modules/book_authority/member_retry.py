from __future__ import annotations

from time import monotonic, sleep

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.step_successor import require_live_chapter_frontier
from novel_forge.modules.production_execution.execution_template import (
    selected_book_template,
    selected_template,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


def wait_settled_member_retry(authority, *, book_run_id, root_id, principal, deadline):
    if monotonic() >= deadline:
        return False
    book = authority.require(book_run_id)
    principal.require("book.authority.execute", book["project_id"])
    principal.require("chapter.authority.execute", book["project_id"])
    with AuthorityUnitOfWork(authority.database_url) as uow:
        c = uow.cursor
        require_live_chapter_frontier(c, root_id=root_id, project_id=book["project_id"], book_run_id=book_run_id)
        c.execute("""SELECT o.actor_id,o.workspace_id,
            EXISTS(SELECT 1 FROM authority_external_effect e JOIN authority_operation sibling USING(operation_id)
                LEFT JOIN authority_budget_reservation budget USING(external_effect_id)
                WHERE sibling.root_operation_id=o.operation_id AND (e.status IN ('UNKNOWN','DISPATCHING','RECONCILIATION_REQUIRED','INTENT_RECORDED')
                    OR budget.status IS DISTINCT FROM 'SETTLED'))
            OR EXISTS(SELECT 1 FROM authority_operation sibling WHERE sibling.root_operation_id=o.operation_id
                AND (sibling.status IN ('UNKNOWN','RECONCILIATION_REQUIRED','CANCELLATION_REQUESTED','RUNNING','WAITING_EXTERNAL_RESULT')
                    OR sibling.project_id<>o.project_id OR sibling.workspace_id<>o.workspace_id OR sibling.actor_id<>o.actor_id))
            OR EXISTS(SELECT 1 FROM authority_attempt attempt JOIN authority_operation sibling USING(operation_id)
                WHERE sibling.root_operation_id=o.operation_id AND attempt.status IN ('UNKNOWN','RUNNING','WAITING_EXTERNAL_RESULT','RECONCILIATION_REQUIRED')),
            EXISTS(SELECT 1 FROM authority_budget_reservation budget JOIN authority_operation sibling USING(operation_id)
                WHERE sibling.root_operation_id=o.operation_id AND budget.status IS DISTINCT FROM 'SETTLED'),
            EXISTS(SELECT 1 FROM authority_lease_acquisition lease JOIN authority_attempt attempt USING(attempt_id)
                JOIN authority_operation sibling USING(operation_id) WHERE sibling.root_operation_id=o.operation_id
                    AND lease.released_at IS NULL AND lease.expires_at>NOW())
            FROM authority_operation o WHERE o.operation_id=%s AND o.project_id=%s""", [root_id,book["project_id"]])
        graph = c.fetchone()
        if not graph or graph[0] != principal.principal_id or graph[1] != book["workspace_id"]:
            raise KernelError("MEMBER_RETRY_SCOPE_INVALID", "Retain the original Book actor and Chapter workspace")
        if any(graph[2:]):
            return False
        admission = selected_book_template(
            c, project_id=book["project_id"], book_id=book["book_id"]
        )
        template = (
            selected_template(admission["policy_snapshot"]["policy"], book["book_id"])
            if admission
            else None
        )
        if (
            not template
            or template["version"]
            not in {"creative-execution-template.v9", "creative-execution-template.v10", "creative-execution-template.v11"}
            or template["mode"] != "CREATIVE_VALIDATION"
        ):
            return False
        rows = settled_retry_rows(c, project_id=book["project_id"], root_id=root_id)
    if len(rows) != 1 or not eligible_retry(
        rows[0], principal.principal_id, template["member_authorization_ref"]
    ):
        return False
    if (
        rows[0][3] != "MODEL_EFFECT_RETRYABLE_PROCESS_EXIT_FAILURE"
        and template["version"] not in {"creative-execution-template.v10", "creative-execution-template.v11"}
    ):
        return False
    sleep(max(0, min(30, deadline - monotonic())))
    return True


def eligible_retry(row, actor_id, authorization_ref):
    actor, maximum, number, error, grant, *contract = row
    version = contract[0] if contract else None
    name = contract[1] if len(contract) == 2 else None
    return (
        actor == actor_id
        and 0 < number < maximum
        and grant == authorization_ref
        and (
            error == "MODEL_EFFECT_RETRYABLE_PROCESS_EXIT_FAILURE"
            or (version == "3.9.26" or version == "3.10.0" and name == "chapter.revision.apply")
            and error == "CHAPTER_LENGTH_REPAIR_INCOMPLETE"
            or (version in {"3.9.29", "3.9.30"} or version == "3.10.0" and name == "chapter.canon.extract")
            and error == "CANON_QUOTE_LOCALIZATION_INVALID"
        )
    )


def settled_retry_rows(cursor, *, project_id, root_id):
    cursor.execute(
        """SELECT o.actor_id,(o.definition_snapshot #>> '{retry_policy,max_attempts}')::int,a.attempt_number,a.result->>'error_code',
    r.evidence->>'cost_authorization_ref',o.definition_version,o.definition_name
    FROM authority_operation o JOIN authority_attempt a USING(operation_id)
    JOIN authority_external_effect e ON e.operation_id=o.operation_id AND e.request_payload #>> '{_production_execution,attempt_id}'=a.attempt_id
    JOIN authority_budget_reservation r USING(external_effect_id)
    WHERE o.project_id=%s AND o.root_operation_id=%s AND o.status='FAILED_RETRYABLE'
    AND a.status='FAILED_RETRYABLE' AND e.provider='codex-cli'
    AND (e.status='FAILED_RETRYABLE' AND a.result->>'error_code'='MODEL_EFFECT_RETRYABLE_PROCESS_EXIT_FAILURE'
    OR e.status='SUCCEEDED' AND ((o.definition_version='3.9.26' OR o.definition_version='3.10.0' AND o.definition_name='chapter.revision.apply')
        AND a.result->>'error_code'='CHAPTER_LENGTH_REPAIR_INCOMPLETE'
    OR (o.definition_version IN ('3.9.29','3.9.30') OR o.definition_version='3.10.0' AND o.definition_name='chapter.canon.extract')
        AND a.result->>'error_code'='CANON_QUOTE_LOCALIZATION_INVALID'))
    AND r.status='SETTLED' AND r.accounting_basis='ACCOUNT_ENTITLEMENT'
    AND a.attempt_number=(SELECT max(attempt_number) FROM authority_attempt WHERE operation_id=o.operation_id)
    AND NOT EXISTS(SELECT 1 FROM authority_external_effect pending JOIN authority_operation sibling USING(operation_id)
    WHERE sibling.root_operation_id=%s AND pending.status IN ('UNKNOWN','DISPATCHING','RECONCILIATION_REQUIRED'))
    AND EXISTS(SELECT 1 FROM authority_operation root WHERE root.operation_id=%s AND root.status='WAITING_CHILDREN')""",
        [project_id, root_id, root_id, root_id],
    )
    return cursor.fetchall()

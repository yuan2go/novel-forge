from __future__ import annotations

from typing import Any, Mapping


def output_capacity_contract_failure(decision: Mapping[str, Any]) -> bool:
    task = decision.get("task") or {}
    candidates = decision.get("candidates") or []
    if (
        decision.get("status") != "BLOCKED"
        or decision.get("selected") is not None
        or not isinstance(task, Mapping)
        or not isinstance(candidates, list)
        or not candidates
        or any(
            not isinstance(row, Mapping)
            or not isinstance(row.get("candidate"), Mapping)
            for row in candidates
        )
    ):
        return False
    values = [task.get("input_tokens"), task.get("output_tokens")]
    if any(type(value) is not int or value < 0 for value in values):
        return False
    return any(
        row.get("rejected_reasons") == ["CONTEXT_CAPACITY_EXCEEDED"]
        and type((row.get("candidate") or {}).get("output_limit")) is int
        and type((row.get("candidate") or {}).get("context_limit")) is int
        and task["output_tokens"] > row["candidate"]["output_limit"] > 0
        and task["input_tokens"] + row["candidate"]["output_limit"]
        <= row["candidate"]["context_limit"]
        for row in candidates
    )


def read_reader_recovery_source(
    cursor, operation_id: str, project_id: str
) -> dict[str, Any] | None:
    cursor.execute(
        """SELECT to_jsonb(operation),attempt.result->>'error_code',
        EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=operation.operation_id)
        OR EXISTS(SELECT 1 FROM authority_budget_reservation WHERE operation_id=operation.operation_id AND status<>'SETTLED')
        OR EXISTS(SELECT 1 FROM authority_lease_acquisition lease JOIN authority_attempt owned USING(attempt_id)
            WHERE owned.operation_id=operation.operation_id AND lease.released_at IS NULL AND lease.expires_at>NOW())
        OR EXISTS(SELECT 1 FROM authority_cancellation_command WHERE operation_id=operation.operation_id)
        FROM authority_operation operation JOIN LATERAL (SELECT result FROM authority_attempt
            WHERE operation_id=operation.operation_id ORDER BY attempt_number DESC LIMIT 1) attempt ON TRUE
        WHERE operation.operation_id=%s AND operation.project_id=%s FOR SHARE OF operation""",
        [operation_id, project_id],
    )
    row = cursor.fetchone()
    if not row or row[2]:
        return None
    source = dict(row[0])
    if source.get("definition_name") != "reader_outcome.evaluate":
        return None
    if (
        source.get("definition_version") == "1.1.0"
        and source.get("status") == "FAILED_FINAL"
        and row[1] == "READER_OUTCOME_PROVIDER_CONTEXT_VIEW_INVALID"
    ):
        return source
    if (
        source.get("definition_version") != "1.2.0"
        or source.get("status") != "DEAD_LETTER"
        or row[1] != "PROVIDER_ROUTING_BLOCKED"
    ):
        return None
    cursor.execute(
        """SELECT version.content FROM authority_operation_output_asset output
        JOIN authority_asset_version version USING(asset_version_id) JOIN authority_asset asset USING(asset_id)
        WHERE output.operation_id=%s AND asset.project_id=%s AND asset.asset_type='routing_decision'
        AND version.content #>> '{task,operation_id}'=%s""",
        [operation_id, project_id, operation_id],
    )
    decisions = [dict(item[0]) for item in cursor.fetchall()]
    return (
        source
        if decisions
        and all(output_capacity_contract_failure(item) for item in decisions)
        else None
    )


def require_reader_book_scope(
    cursor,
    *,
    project_id: str,
    workspace_id: str,
    actor_id: str,
    payload: Mapping[str, Any],
    source_operation_id: str = "",
) -> None:
    from novel_forge.modules.book_authority.reader_pack import (
        require_current_reader_template,
    )
    from novel_forge.modules.command_kernel.budget_runtime import (
        require_known_cli_lineage,
    )
    from novel_forge.modules.command_kernel.errors import KernelError

    book_id = str(payload.get("book_id") or "")
    require_current_reader_template(cursor, project_id=project_id, book_id=book_id)
    cursor.execute(
        """SELECT book.book_run_id,book.root_operation_id,acceptance.chapter_request_id
        FROM authority_book_chapter_acceptance acceptance
        JOIN authority_book_production book USING(book_run_id)
        JOIN authority_operation accepted ON accepted.operation_id=acceptance.acceptance_operation_id
        WHERE acceptance.acceptance_operation_id=%s AND acceptance.project_id=%s
          AND acceptance.status='COMMITTED' AND acceptance.chapter_number=%s
          AND book.project_id=%s AND book.workspace_id=%s AND book.book_id=%s
          AND book.state NOT IN ('ABORTED','CANCELLED') AND accepted.status='SUCCEEDED'
          AND accepted.actor_id=%s AND NOT EXISTS(SELECT 1 FROM authority_cancellation_command cancel
            WHERE cancel.operation_id=book.root_operation_id)
        FOR SHARE OF book,acceptance""",
        [
            str(payload.get("acceptance_operation_id") or ""),
            project_id,
            payload.get("chapter_number"),
            project_id,
            workspace_id,
            book_id,
            actor_id,
        ],
    )
    row = cursor.fetchone()
    if not row:
        raise KernelError(
            "READER_ACCEPTED_BOOK_SCOPE_INVALID",
            "Reader requires the exact committed acceptance and uncancelled original actor/Book",
        )
    require_known_cli_lineage(cursor, project_id=project_id, operation_id=str(row[1]))
    if source_operation_id:
        cursor.execute(
            """SELECT operation_id FROM authority_book_followup_operation
            WHERE chapter_request_id=%s AND book_run_id=%s AND project_id=%s
              AND followup_type='READER_OUTCOME' AND operation_id=%s FOR SHARE""",
            [row[2], row[0], project_id, source_operation_id],
        )
        if not cursor.fetchone():
            raise KernelError(
                "READER_SUCCESSOR_LINK_INVALID",
                "Recovery source must remain the original accepted Book follow-up",
            )

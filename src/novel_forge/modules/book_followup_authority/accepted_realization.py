from __future__ import annotations

from novel_forge.modules.command_kernel.budget_runtime import require_known_cli_lineage
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.hierarchical_planning.realization_domain import (
    realization_hash,
)


def read_accepted_realization_deviations(
    cursor,
    *,
    project_id: str,
    workspace_id: str,
    book_id: str,
    chapter_request_id: str,
    actor_id: str,
) -> dict:
    cursor.execute(
        """SELECT acceptance.acceptance_id,acceptance.chapter_number,acceptance.acceptance_operation_id,
        request.book_run_id,book.root_operation_id,acceptance.followup_snapshot
        FROM authority_book_chapter_acceptance acceptance
        JOIN authority_book_chapter_request request USING(chapter_request_id)
        JOIN authority_book_production book ON book.book_run_id=acceptance.book_run_id
        JOIN authority_operation owner ON owner.operation_id=acceptance.acceptance_operation_id
        WHERE acceptance.chapter_request_id=%s AND acceptance.project_id=%s AND acceptance.book_id=%s
          AND book.project_id=%s AND book.workspace_id=%s AND book.book_id=%s
          AND owner.project_id=%s AND owner.workspace_id=%s AND owner.actor_id=%s AND owner.status='SUCCEEDED'
          AND acceptance.status='COMMITTED' AND book.state NOT IN ('ABORTED','CANCELLED')
          AND NOT EXISTS(SELECT 1 FROM authority_cancellation_command WHERE operation_id=book.root_operation_id)
        FOR SHARE OF acceptance,book""",
        [
            chapter_request_id,
            project_id,
            book_id,
            project_id,
            workspace_id,
            book_id,
            project_id,
            workspace_id,
            actor_id,
        ],
    )
    accepted = cursor.fetchone()
    if not accepted:
        raise KernelError(
            "RECAP_ACCEPTED_REALIZATION_SCOPE_INVALID",
            "Recap requires the exact successful committed acceptance owner",
        )
    snapshot = accepted[5] if isinstance(accepted[5], dict) else {}
    snapshot_id = snapshot.get("book_production_input_snapshot_id")
    if not snapshot_id:
        raise KernelError(
            "RECAP_ACCEPTED_REALIZATION_SCOPE_INVALID",
            "Current Recap requires the original accepted input snapshot",
        )
    require_known_cli_lineage(cursor, project_id=project_id, operation_id=accepted[4])
    cursor.execute(
        """SELECT deviation_id,deviation_kind,realization_id,evidence_hash,
        affected_future_from_chapter,evidence FROM authority_narrative_realization_deviation
        WHERE acceptance_id=%s ORDER BY deviation_kind,deviation_id""",
        [accepted[0]],
    )
    deviations = []
    for row in cursor.fetchall():
        if (
            not isinstance(row[5], dict)
            or realization_hash(row[5]) != row[3]
            or int(row[4]) != int(accepted[1]) + 1
        ):
            raise KernelError(
                "RECAP_ACCEPTED_REALIZATION_EVIDENCE_INVALID",
                "Preserve exact accepted deviation hash and future boundary",
            )
        deviations.append(
            dict(
                zip(
                    (
                        "deviation_id",
                        "deviation_kind",
                        "realization_id",
                        "evidence_hash",
                        "future_from_chapter",
                        "evidence",
                    ),
                    row,
                    strict=True,
                )
            )
        )
    return {
        "contract_version": "accepted-realization-deviations.v2",
        "project_id": project_id,
        "workspace_id": workspace_id,
        "book_id": book_id,
        "book_run_id": str(accepted[3]),
        "chapter_request_id": chapter_request_id,
        "acceptance_id": str(accepted[0]),
        "acceptance_operation_id": str(accepted[2]),
        "book_production_input_snapshot_id": str(snapshot_id),
        "chapter_number": int(accepted[1]),
        "deviations": deviations,
        "accepted_history_mutation_allowed": False,
    }

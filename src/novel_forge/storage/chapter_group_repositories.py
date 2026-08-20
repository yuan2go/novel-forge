"""PostgreSQL mutations for ChapterGroup checkpoints and references."""
from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError


class ChapterGroupRepository:
    def __init__(self, cursor: Any) -> None:
        self.cursor = cursor

    def create(self, row: dict[str, Any]) -> None:
        self.cursor.execute(
            """
            INSERT INTO authority_chapter_group_production(
                group_run_id, project_id, book_id, book_run_id,
                group_plan_version_id, volume_plan_version_id,
                root_operation_id, saga_id, stable_idempotency_key,
                chapter_start, chapter_end, accepted_through_chapter, state
            ) VALUES (
                %(group_run_id)s, %(project_id)s, %(book_id)s,
                %(book_run_id)s, %(group_plan_version_id)s,
                %(volume_plan_version_id)s, %(root_operation_id)s,
                %(saga_id)s, %(stable_idempotency_key)s,
                %(chapter_start)s, %(chapter_end)s,
                %(accepted_through_chapter)s, 'PREPARING'
            )
            ON CONFLICT(project_id, stable_idempotency_key) DO NOTHING
            """,
            row,
        )

    def set_state(
        self,
        group_run_id: str,
        *,
        expected: tuple[str, ...],
        target: str,
        failure_reason: str = "",
    ) -> None:
        self.cursor.execute(
            """
            UPDATE authority_chapter_group_production
            SET state=%s, failure_reason=%s, version=version+1,
                updated_at=NOW()
            WHERE group_run_id=%s AND state=ANY(%s)
            """,
            [target, failure_reason, group_run_id, list(expected)],
        )
        if self.cursor.rowcount != 1:
            raise KernelError(
                "CHAPTER_GROUP_STATE_CONFLICT",
                f"cannot transition ChapterGroup to {target}",
            )

    def link_chapter(
        self,
        *,
        group_run_id: str,
        project_id: str,
        chapter_number: int,
        chapter_plan_version_id: str,
        chapter_request_id: str,
        child_root_operation_id: str,
        child_delegation_id: str,
    ) -> None:
        self.cursor.execute(
            """
            INSERT INTO authority_chapter_group_chapter(
                group_run_id, project_id, chapter_number,
                chapter_plan_version_id, chapter_request_id,
                child_root_operation_id, child_delegation_id, status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'DISPATCHED')
            ON CONFLICT(group_run_id, chapter_number) DO NOTHING
            """,
            [
                group_run_id,
                project_id,
                chapter_number,
                chapter_plan_version_id,
                chapter_request_id,
                child_root_operation_id,
                child_delegation_id,
            ],
        )
        self.cursor.execute(
            """
            UPDATE authority_chapter_group_production
            SET active_chapter_number=%s, active_chapter_request_id=%s,
                state='CHAPTER_RUNNING', version=version+1, updated_at=NOW()
            WHERE group_run_id=%s AND state='READY'
              AND active_chapter_request_id IS NULL
            """,
            [chapter_number, chapter_request_id, group_run_id],
        )
        if self.cursor.rowcount != 1:
            raise KernelError(
                "CHAPTER_GROUP_ACTIVE_CHILD_CONFLICT",
                "ChapterGroup already has an active Chapter",
            )

    def record_child_status(
        self,
        *,
        group_run_id: str,
        chapter_number: int,
        status: str,
    ) -> None:
        mapped = {
            "ADMITTED": "DISPATCHED",
            "RUNNING": "RUNNING",
            "WAITING_RETRY": "RUNNING",
            "SUCCEEDED": "SUCCEEDED",
            "FAILED_RETRYABLE": "FAILED_RETRYABLE",
            "FAILED_TERMINAL": "FAILED_TERMINAL",
            "CANCELLED": "CANCELLED",
        }.get(status, "RUNNING")
        self.cursor.execute(
            """
            UPDATE authority_chapter_group_chapter
            SET status=%s, updated_at=NOW()
            WHERE group_run_id=%s AND chapter_number=%s
              AND status <> 'ACCEPTED'
            """,
            [mapped, group_run_id, chapter_number],
        )

    def accept_chapter(
        self,
        *,
        group_run_id: str,
        chapter_number: int,
        acceptance_operation_id: str,
        chapter_outcome_version_id: str,
        target_state: str,
    ) -> None:
        self.cursor.execute(
            """
            UPDATE authority_chapter_group_chapter
            SET status='ACCEPTED', acceptance_operation_id=%s,
                chapter_outcome_version_id=%s,
                accepted_at=COALESCE(accepted_at, NOW()), updated_at=NOW()
            WHERE group_run_id=%s AND chapter_number=%s
              AND status IN ('SUCCEEDED', 'ACCEPTED')
            """,
            [
                acceptance_operation_id,
                chapter_outcome_version_id,
                group_run_id,
                chapter_number,
            ],
        )
        if self.cursor.rowcount != 1:
            raise KernelError(
                "CHAPTER_GROUP_ACCEPTANCE_CONFLICT",
                "Chapter child is not terminal and accepted",
            )
        self.cursor.execute(
            """
            UPDATE authority_chapter_group_production
            SET accepted_through_chapter=GREATEST(
                    accepted_through_chapter, %s
                ),
                active_chapter_number=NULL,
                active_chapter_request_id=NULL,
                state=%s, version=version+1, updated_at=NOW()
            WHERE group_run_id=%s
              AND accepted_through_chapter IN (%s, %s)
            """,
            [
                chapter_number,
                target_state,
                group_run_id,
                chapter_number - 1,
                chapter_number,
            ],
        )
        if self.cursor.rowcount != 1:
            raise KernelError(
                "CHAPTER_GROUP_CURSOR_CONFLICT",
                "ChapterGroup cursor cannot skip a Chapter",
            )

    def close(
        self,
        *,
        group_run_id: str,
    ) -> None:
        self.cursor.execute(
            """
            UPDATE authority_chapter_group_production
            SET state='COMPLETED', version=version+1, updated_at=NOW()
            WHERE group_run_id=%s AND state='CLOSURE_PENDING'
              AND accepted_through_chapter=chapter_end
            """,
            [group_run_id],
        )
        if self.cursor.rowcount != 1:
            raise KernelError(
                "CHAPTER_GROUP_CLOSURE_NOT_READY",
                "ChapterGroup cannot close before every Chapter is accepted",
            )

    def require(self, group_run_id: str) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT group_run_id, project_id, book_id, book_run_id,
                   group_plan_version_id, volume_plan_version_id,
                   root_operation_id, saga_id, stable_idempotency_key,
                   chapter_start, chapter_end, accepted_through_chapter,
                   active_chapter_number, active_chapter_request_id, state,
                   recap_operation_id, plan_adjustment_proposal_version_id,
                   failure_reason, version
            FROM authority_chapter_group_production
            WHERE group_run_id=%s
            """,
            [group_run_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "CHAPTER_GROUP_NOT_FOUND",
                "ChapterGroup Authority run does not exist",
            )
        fields = (
            "group_run_id",
            "project_id",
            "book_id",
            "book_run_id",
            "group_plan_version_id",
            "volume_plan_version_id",
            "root_operation_id",
            "saga_id",
            "stable_idempotency_key",
            "chapter_start",
            "chapter_end",
            "accepted_through_chapter",
            "active_chapter_number",
            "active_chapter_request_id",
            "state",
            "recap_operation_id",
            "plan_adjustment_proposal_version_id",
            "failure_reason",
            "version",
        )
        return dict(zip(fields, row, strict=True))


__all__ = ["ChapterGroupRepository"]

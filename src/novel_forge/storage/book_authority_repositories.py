"""Mutation repository for the persistent Book Authority aggregate."""
from __future__ import annotations

from typing import Any, Callable

from psycopg.types.json import Jsonb


class BookAuthorityRepository:
    def __init__(self, cursor: Any) -> None:
        self.cursor = cursor

    def create_run(self, row: dict[str, Any]) -> None:
        self.cursor.execute(
            """
            INSERT INTO authority_book_production (
                book_run_id, project_id, workspace_id, book_id,
                book_design_version, book_plan_version,
                production_profile_version, longform_context_versions,
                root_operation_id, saga_id,
                stable_idempotency_key, state, target_chapter_count,
                light_recap_cadence, formal_recap_cadence
            ) VALUES (
                %(book_run_id)s, %(project_id)s, %(workspace_id)s, %(book_id)s,
                %(book_design_version)s, %(book_plan_version)s,
                %(production_profile_version)s, %(longform_context_versions)s,
                %(root_operation_id)s,
                %(saga_id)s, %(stable_idempotency_key)s, 'READY',
                %(target_chapter_count)s, %(light_recap_cadence)s,
                %(formal_recap_cadence)s
            )
            ON CONFLICT (project_id, stable_idempotency_key) DO NOTHING
            """,
            {
                **row,
                "longform_context_versions": Jsonb(
                    row["longform_context_versions"]
                ),
            },
        )

    def create_chapter_request(self, row: dict[str, Any]) -> None:
        self.cursor.execute(
            """
            INSERT INTO authority_book_chapter_request (
                chapter_request_id, book_run_id, project_id, chapter_number,
                chapter_plan_version, chapter_plan_content_hash,
                parent_group_version_id,
                production_profile_version, stable_idempotency_key,
                command_payload, status_reference
            ) VALUES (
                %(chapter_request_id)s, %(book_run_id)s, %(project_id)s,
                %(chapter_number)s, %(chapter_plan_version)s,
                %(chapter_plan_content_hash)s, NULLIF(%(parent_group_version_id)s, ''),
                %(production_profile_version)s,
                %(stable_idempotency_key)s, %(command_payload)s, 'SUBMITTING'
            )
            ON CONFLICT (project_id, stable_idempotency_key) DO NOTHING
            """,
            {**row, "command_payload": Jsonb(row["command_payload"])},
        )

    def reserve_chapter(
        self,
        *,
        book_run_id: str,
        chapter_request_id: str,
        chapter_number: int,
    ) -> bool:
        self.cursor.execute(
            """
            UPDATE authority_book_production
            SET active_chapter_request_id=%s, state='CHAPTER_SUBMITTED',
                version=version+1, updated_at=NOW()
            WHERE book_run_id=%s AND state='READY'
              AND current_chapter=%s
            """,
            [chapter_request_id, book_run_id, chapter_number - 1],
        )
        return self.cursor.rowcount == 1

    def link_chapter(
        self,
        *,
        chapter_request_id: str,
        book_run_id: str,
        project_id: str,
        chapter_number: int,
        chapter_plan_version: str,
        stable_idempotency_key: str,
        delegation_id: str,
        root_operation_id: str,
        saga_id: str,
    ) -> None:
        self.cursor.execute(
            """
            UPDATE authority_book_chapter_request
            SET chapter_root_operation_id=%s, chapter_saga_id=%s,
                status_reference='ADMITTED', updated_at=NOW()
            WHERE chapter_request_id=%s AND chapter_root_operation_id IS NULL
            """,
            [root_operation_id, saga_id, chapter_request_id],
        )
        self.cursor.execute(
            """
            INSERT INTO authority_child_delegation(
                delegation_id, project_id, owner_authority, owner_id,
                child_authority, chapter_request_id, chapter_number,
                plan_version_id, child_root_operation_id, child_saga_id,
                stable_idempotency_key, status
            ) VALUES (
                %s, %s, 'BOOK', %s, 'CHAPTER', %s, %s, %s, %s, %s, %s,
                'DISPATCHED'
            )
            ON CONFLICT (project_id, stable_idempotency_key) DO NOTHING
            """,
            [
                delegation_id,
                project_id,
                book_run_id,
                chapter_request_id,
                chapter_number,
                chapter_plan_version,
                root_operation_id,
                saga_id,
                stable_idempotency_key,
            ],
        )
        self.cursor.execute(
            """
            UPDATE authority_book_production
            SET active_chapter_request_id=%s, active_child_delegation_id=%s,
                active_chapter_number=%s, active_plan_version_id=%s,
                state='CHAPTER_SUBMITTED', version=version+1, updated_at=NOW()
            WHERE book_run_id=%s
            """,
            [
                chapter_request_id,
                delegation_id,
                chapter_number,
                chapter_plan_version,
                book_run_id,
            ],
        )

    def record_chapter_status(
        self,
        *,
        chapter_request_id: str,
        book_run_id: str,
        request_status: str,
        book_state: str,
    ) -> None:
        self.cursor.execute(
            """
            UPDATE authority_book_chapter_request
            SET status_reference=%s, updated_at=NOW()
            WHERE chapter_request_id=%s
            """,
            [request_status, chapter_request_id],
        )
        self.cursor.execute(
            """
            UPDATE authority_book_production
            SET state=%s, version=version+1, updated_at=NOW()
            WHERE book_run_id=%s
            """,
            [book_state, book_run_id],
        )
        self.cursor.execute(
            """
            UPDATE authority_child_delegation
            SET status=%s, version=version+1, updated_at=NOW()
            WHERE chapter_request_id=%s
              AND status <> 'ACCEPTED'
            """,
            [
                {
                    "ADMITTED": "DISPATCHED",
                    "RUNNING": "RUNNING",
                    "WAITING_RETRY": "WAITING_RETRY",
                    "SUCCEEDED": "SUCCEEDED",
                    "FAILED_RETRYABLE": "FAILED_RETRYABLE",
                    "FAILED_TERMINAL": "FAILED_TERMINAL",
                    "CANCELLED": "CANCELLED",
                    "UNKNOWN": "UNKNOWN",
                }.get(request_status, "UNKNOWN"),
                chapter_request_id,
            ],
        )

    def commit_chapter_acceptance(
        self,
        *,
        acceptance_id: str,
        project_id: str,
        book_run_id: str,
        chapter_request_id: str,
        delegation_id: str,
        acceptance_operation_id: str,
        chapter_number: int,
        chapter_outcome_asset_version_id: str,
        story_state_asset_version_id: str,
        canon_snapshot_asset_version_id: str,
        evidence: dict[str, Any],
        before_cursor_advance: Callable[[], None] | None = None,
    ) -> bool:
        self.cursor.execute(
            """
            INSERT INTO authority_book_chapter_acceptance(
                acceptance_id, project_id, book_run_id, chapter_request_id,
                delegation_id, acceptance_operation_id, chapter_number,
                chapter_outcome_asset_version_id, story_state_asset_version_id,
                canon_snapshot_asset_version_id, evidence, status
            ) VALUES (
                %(acceptance_id)s, %(project_id)s, %(book_run_id)s,
                %(chapter_request_id)s, %(delegation_id)s,
                %(acceptance_operation_id)s, %(chapter_number)s,
                %(chapter_outcome_asset_version_id)s,
                %(story_state_asset_version_id)s,
                %(canon_snapshot_asset_version_id)s, %(evidence)s, 'COMMITTED'
            )
            ON CONFLICT (chapter_request_id) DO NOTHING
            """,
            {
                "acceptance_id": acceptance_id,
                "project_id": project_id,
                "book_run_id": book_run_id,
                "chapter_request_id": chapter_request_id,
                "delegation_id": delegation_id,
                "acceptance_operation_id": acceptance_operation_id,
                "chapter_number": chapter_number,
                "chapter_outcome_asset_version_id": chapter_outcome_asset_version_id,
                "story_state_asset_version_id": story_state_asset_version_id,
                "canon_snapshot_asset_version_id": canon_snapshot_asset_version_id,
                "evidence": Jsonb(evidence),
            },
        )
        inserted = self.cursor.rowcount == 1
        if before_cursor_advance is not None:
            before_cursor_advance()
        self.cursor.execute(
            """
            UPDATE authority_child_delegation
            SET status='ACCEPTED', accepted_at=COALESCE(accepted_at, NOW()),
                version=version+1, updated_at=NOW()
            WHERE delegation_id=%s
              AND status IN ('SUCCEEDED', 'ACCEPTED')
            """,
            [delegation_id],
        )
        self.cursor.execute(
            """
            UPDATE authority_book_production
            SET current_chapter=GREATEST(current_chapter, %s),
                accepted_through_chapter=GREATEST(accepted_through_chapter, %s),
                active_chapter_request_id=NULL,
                active_child_delegation_id=NULL,
                active_chapter_number=NULL,
                active_plan_version_id=NULL,
                active_story_state_version_id=%s,
                active_canon_snapshot_version_id=%s,
                last_chapter_outcome_version_id=%s,
                state=CASE
                    WHEN %s >= target_chapter_count THEN 'COMPLETED'
                    ELSE 'READY'
                END,
                version=version+1, updated_at=NOW()
            WHERE book_run_id=%s
              AND accepted_through_chapter IN (%s, %s)
            """,
            [
                chapter_number,
                chapter_number,
                story_state_asset_version_id,
                canon_snapshot_asset_version_id,
                chapter_outcome_asset_version_id,
                chapter_number,
                book_run_id,
                chapter_number - 1,
                chapter_number,
            ],
        )
        if self.cursor.rowcount != 1:
            raise ValueError("Book cursor cannot accept a non-sequential Chapter")
        return inserted

    def abort(self, *, book_run_id: str, reason: str) -> None:
        self.cursor.execute(
            """
            UPDATE authority_child_delegation
            SET status=CASE
                    WHEN status IN ('DISPATCHED', 'RUNNING', 'WAITING_RETRY',
                                    'SUCCEEDED', 'UNKNOWN')
                    THEN 'CANCELLATION_REQUESTED'
                    ELSE status
                END,
                version=version+1, updated_at=NOW()
            WHERE owner_id=%s AND status <> 'ACCEPTED'
            """,
            [book_run_id],
        )
        self.cursor.execute(
            """
            UPDATE authority_book_production
            SET state='ABORTED', failure_reason=%s, paused_reason=%s,
                version=version+1, updated_at=NOW()
            WHERE book_run_id=%s AND state <> 'COMPLETED'
            """,
            [reason, reason, book_run_id],
        )

    def link_followup(
        self,
        *,
        followup_id: str,
        book_run_id: str,
        chapter_request_id: str,
        project_id: str,
        followup_type: str,
        operation_id: str,
        stable_idempotency_key: str,
    ) -> None:
        self.cursor.execute(
            """
            INSERT INTO authority_book_followup_operation (
                followup_id, book_run_id, chapter_request_id, project_id,
                followup_type, operation_id, stable_idempotency_key
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (project_id, stable_idempotency_key) DO NOTHING
            """,
            [
                followup_id,
                book_run_id,
                chapter_request_id,
                project_id,
                followup_type,
                operation_id,
                stable_idempotency_key,
            ],
        )
        column = (
            "last_reader_outcome_operation_id"
            if followup_type == "READER_OUTCOME"
            else "last_recap_operation_id"
        )
        self.cursor.execute(
            f"""
            UPDATE authority_book_production
            SET {column}=%s, version=version+1, updated_at=NOW()
            WHERE book_run_id=%s
            """,
            [operation_id, book_run_id],
        )

    def advance(
        self,
        *,
        book_run_id: str,
        chapter_number: int,
        state: str,
    ) -> None:
        self.cursor.execute(
            """
            UPDATE authority_book_production
            SET state=%s, current_chapter=GREATEST(current_chapter, %s),
                version=version+1, updated_at=NOW()
            WHERE book_run_id=%s
            """,
            [state, chapter_number, book_run_id],
        )

    def set_gate_state(
        self, *, book_run_id: str, state: str, reason: str = ""
    ) -> None:
        self.cursor.execute(
            """
            UPDATE authority_book_production
            SET state=%s, paused_reason=%s, version=version+1,
                updated_at=NOW()
            WHERE book_run_id=%s
            """,
            [state, reason, book_run_id],
        )


__all__ = ["BookAuthorityRepository"]

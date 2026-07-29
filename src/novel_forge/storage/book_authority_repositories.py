"""Mutation repository for the persistent Book Authority aggregate."""
from __future__ import annotations

from typing import Any

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
                production_profile_version, stable_idempotency_key,
                command_payload, status_reference
            ) VALUES (
                %(chapter_request_id)s, %(book_run_id)s, %(project_id)s,
                %(chapter_number)s, %(chapter_plan_version)s,
                %(chapter_plan_content_hash)s, %(production_profile_version)s,
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
            UPDATE authority_book_production
            SET active_chapter_request_id=%s, state='CHAPTER_SUBMITTED',
                version=version+1, updated_at=NOW()
            WHERE book_run_id=%s
            """,
            [chapter_request_id, book_run_id],
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
        book_state: str,
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
            SET state=%s, {column}=%s, version=version+1, updated_at=NOW()
            WHERE book_run_id=%s
            """,
            [book_state, operation_id, book_run_id],
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

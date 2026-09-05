from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from novel_forge.modules.book_authority.completion import (
    COMPLETION_CONTRACT,
    assess_whole_book_completion,
    completion_content_hash,
)
from novel_forge.modules.command_kernel.errors import KernelError


class BookCompletionRepository:
    def __init__(self, cursor: Any) -> None:
        self.cursor = cursor

    def assess_terminal_boundary(
        self, *, book_run_id: str, chapter_number: int, operation_id: str
    ) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT book.project_id, book.book_id, book.target_chapter_count,
                   acceptance.acceptance_id, projection.projection_set_id,
                   projection.chapter_outcome_asset_version_id,
                   projection.story_state_asset_version_id,
                   projection.canon_snapshot_asset_version_id,
                   projection.projection_hash, projection.arc_state,
                   projection.obligation_state, acceptance.evidence,
                   book.book_design_version, book.book_plan_version
            FROM authority_book_production AS book
            JOIN authority_book_chapter_acceptance AS acceptance
              ON acceptance.book_run_id=book.book_run_id
             AND acceptance.project_id=book.project_id
             AND acceptance.chapter_number=book.accepted_through_chapter
             AND acceptance.status='COMMITTED'
            JOIN authority_book_narrative_projection_set AS projection
              ON projection.projection_set_id=acceptance.longform_projection_set_id
             AND projection.acceptance_id=acceptance.acceptance_id
             AND projection.status='COMPLETE'
             AND projection.projection_set_id=book.active_longform_projection_set_id
             AND projection.chapter_outcome_asset_version_id=book.last_chapter_outcome_version_id
             AND projection.story_state_asset_version_id=book.active_story_state_version_id
             AND projection.canon_snapshot_asset_version_id=book.active_canon_snapshot_version_id
            WHERE book.book_run_id=%s
              AND book.accepted_through_chapter=%s
              AND book.target_chapter_count=%s
            FOR UPDATE OF book
            """,
            [book_run_id, chapter_number, chapter_number],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "BOOK_COMPLETION_ACCEPTED_BOUNDARY_REQUIRED",
                "Cursor exhaustion requires the complete exact terminal accepted projection",
            )
        snapshot = {
            "project_id": row[0],
            "book_id": row[1],
            "book_run_id": book_run_id,
            "target_chapter_count": row[2],
            "book_design_version": row[12],
            "book_plan_version": row[13],
            "accepted_boundary": {
                "chapter_number": chapter_number,
                "acceptance_id": row[3],
                "projection_set_id": row[4],
                "chapter_outcome_asset_version_id": row[5],
                "story_state_asset_version_id": row[6],
                "canon_snapshot_asset_version_id": row[7],
                "projection_hash": row[8],
            },
            "arc_state": row[9],
            "obligation_state": row[10],
            "chapter_gate_evidence": row[11],
        }
        report = assess_whole_book_completion(snapshot)
        digest = completion_content_hash(report)
        case_id = "book-completion:" + digest.removeprefix("sha256:")
        self.cursor.execute(
            """
            INSERT INTO authority_book_completion_case(
                completion_case_id, book_run_id, project_id, book_id,
                acceptance_id, projection_set_id, chapter_number,
                operation_id, contract_version, content_hash, decision, report
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'BLOCKED',%s)
            ON CONFLICT (completion_case_id) DO NOTHING
            """,
            [
                case_id,
                book_run_id,
                row[0],
                row[1],
                row[3],
                row[4],
                chapter_number,
                operation_id,
                COMPLETION_CONTRACT,
                digest,
                Jsonb(report),
            ],
        )
        return {"completion_case_id": case_id, "content_hash": digest, **report}

    def latest(self, book_run_id: str) -> dict[str, Any] | None:
        self.cursor.execute(
            """
            SELECT completion_case_id, content_hash, report
            FROM authority_book_completion_case
            WHERE book_run_id=%s
            ORDER BY created_at DESC, completion_case_id DESC LIMIT 1
            """,
            [book_run_id],
        )
        row = self.cursor.fetchone()
        return (
            {"completion_case_id": row[0], "content_hash": row[1], **row[2]}
            if row
            else None
        )

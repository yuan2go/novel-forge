from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.review.diagnostics import prose_hash
from novel_forge.modules.review.prose_window import (
    digest,
    validate_source_snapshot,
    window_policy,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


def freeze_accepted_prose(
    uow: AuthorityUnitOfWork,
    *,
    book: dict[str, Any],
    chapter: int,
    policy: dict[str, Any],
) -> dict[str, Any]:
    policy = window_policy(policy)
    uow.cursor.execute(
        "SELECT accepted_through_chapter FROM authority_book_production WHERE book_run_id=%s AND project_id=%s FOR UPDATE",
        [book["book_run_id"], book["project_id"]],
    )
    row = uow.cursor.fetchone()
    if row is None or int(row[0]) != chapter - 1:
        raise KernelError(
            "CROSS_CHAPTER_REVIEW_FRONTIER_STALE",
            "Book accepted frontier differs from Chapter admission",
        )
    uow.cursor.execute(
        """
        SELECT chapter_number, chapter_outcome_asset_version_id, acceptance_operation_id
        FROM authority_book_acceptance_lineage(%s)
        WHERE project_id=%s AND status='COMMITTED'
          AND chapter_number >= %s AND chapter_number < %s
        ORDER BY chapter_number
        """,
        [
            book["book_run_id"],
            book["project_id"],
            max(1, chapter - policy["maximum_previous_chapters"]),
            chapter,
        ],
    )
    rows = uow.cursor.fetchall()
    scope = {
        key: book[key]
        for key in ("project_id", "workspace_id", "book_id", "book_run_id")
    }
    sources = []
    for number, outcome_id, acceptance_id in rows:
        outcome = uow.repositories.asset_documents.require(
            project_id=book["project_id"], asset_version_id=outcome_id
        )
        version = str(outcome.content.get("accepted_draft_asset_version_id") or "")
        candidate = uow.repositories.asset_documents.require(
            project_id=book["project_id"], asset_version_id=version
        )
        if (
            candidate.asset_type != "best_draft_candidate"
            or int(candidate.content.get("chapter") or 0) != number
        ):
            raise KernelError(
                "CROSS_CHAPTER_REVIEW_SOURCE_INVALID",
                "accepted outcome does not identify its exact Chapter manuscript",
            )
        text = str(candidate.content.get("text") or "")
        sources.append(
            {
                **scope,
                "chapter_number": number,
                "asset_version_id": version,
                "content_hash": candidate.content_hash,
                "text_hash": prose_hash(text),
                "text": text,
                "acceptance_operation_id": acceptance_id,
                "acceptance_status": "COMMITTED",
            }
        )
    snapshot = {
        **scope,
        "contract_version": "accepted-prose-snapshot.v1",
        "target_chapter_number": chapter,
        "accepted_through_chapter": chapter - 1,
        "sources": sources,
        "window_policy": policy,
    }
    snapshot["snapshot_hash"] = digest(snapshot)
    validate_source_snapshot(snapshot)
    return snapshot


def require_frozen_prose_frontier(
    database_url: str,
    *,
    snapshot: dict[str, Any],
    project_id: str,
    workspace_id: str,
    chapter: int,
) -> None:
    validate_source_snapshot(snapshot)
    if (
        snapshot["project_id"],
        snapshot["workspace_id"],
        snapshot["target_chapter_number"],
    ) != (project_id, workspace_id, chapter):
        raise KernelError(
            "CROSS_CHAPTER_REVIEW_SOURCE_INVALID",
            "frozen source scope differs from current candidate",
        )
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """
            SELECT book.accepted_through_chapter, request.command_payload
            FROM authority_book_production book
            JOIN authority_book_chapter_request request USING(book_run_id)
            WHERE book.book_run_id=%s AND book.project_id=%s AND book.workspace_id=%s
              AND book.book_id=%s AND request.chapter_number=%s
            """,
            [
                snapshot["book_run_id"],
                project_id,
                workspace_id,
                snapshot["book_id"],
                chapter,
            ],
        )
        rows = uow.cursor.fetchall()
    if not any(row[1].get("accepted_prose_snapshot") == snapshot for row in rows):
        raise KernelError(
            "CROSS_CHAPTER_REVIEW_SOURCE_INVALID",
            "window is not the Book-owned Chapter reservation snapshot",
        )
    if any(int(row[0]) != snapshot["accepted_through_chapter"] for row in rows):
        raise KernelError(
            "CROSS_CHAPTER_REVIEW_FRONTIER_STALE",
            "frozen frontier changed; readmission required",
        )

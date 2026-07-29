"""Read-only PostgreSQL projections for governed post-chapter results."""
from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


class BookFollowupProjectionQuery:
    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("PostgreSQL database URL is required")
        self.database_url = database_url

    def reader_outcome(self, *, project_id: str, operation_id: str) -> dict[str, Any]:
        return self._require(
            "authority_reader_outcome_projection",
            "reader_outcome_report_asset_version",
            "reader_outcome_report",
            project_id,
            operation_id,
        )

    def longform_recap(self, *, project_id: str, operation_id: str) -> dict[str, Any]:
        return self._require(
            "authority_longform_recap_projection",
            "longform_recap_asset_version",
            "longform_recap",
            project_id,
            operation_id,
        )

    def _require(
        self,
        view: str,
        version_column: str,
        content_column: str,
        project_id: str,
        operation_id: str,
    ) -> dict[str, Any]:
        # View and column names are private constants, never request data.
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                f"""
                SELECT book_run_id, chapter_request_id, operation_id, project_id,
                       status, {version_column}, {content_column}, updated_at
                FROM {view}
                WHERE project_id=%s AND operation_id=%s
                """,
                [project_id, operation_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "BOOK_FOLLOWUP_PROJECTION_NOT_FOUND",
                "governed follow-up projection does not exist",
            )
        return {
            "book_run_id": row[0],
            "chapter_request_id": row[1],
            "operation_id": row[2],
            "project_id": row[3],
            "status": row[4],
            "asset_version_id": row[5] or "",
            "content": dict(row[6] or {}),
            "updated_at": str(row[7]),
            "authoritative": False,
            "rebuildable": True,
        }


__all__ = ["BookFollowupProjectionQuery"]

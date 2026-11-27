from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


class BookDesignAuthorityQuery:
    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("PostgreSQL database_url is required")
        self.database_url = database_url

    def require_book(self, *, project_id: str, book_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT book.book_id, book.project_id, book.workspace_id,
                       book.principal_id, book.service_identity, book.book_scope,
                       book.production_profile, book.runtime_policy,
                       book.release_identity, book.status, book.version,
                       book.current_book_asset_version_id,
                       COALESCE(book.current_book_design_asset_version_id, ''),
                       COALESCE(design.content->>'title', record.content->>'title')
                FROM authority_book AS book
                JOIN authority_asset_version record ON record.asset_version_id=book.current_book_asset_version_id
                LEFT JOIN authority_asset_version design ON design.asset_version_id=book.current_book_design_asset_version_id
                WHERE book.project_id = %s AND book.book_id = %s
                """,
                [project_id, book_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("BOOK_NOT_FOUND", "Book read model does not exist")
        return {
            "schema_version": "book-read-model.v1",
            "book_id": row[0], "project_id": row[1], "workspace_id": row[2],
            "principal": row[3], "service_identity": row[4], "book_scope": row[5],
            "production_profile": row[6], "runtime_policy": row[7],
            "release_identity": row[8], "status": row[9], "version": int(row[10]),
            "book_asset_version_id": row[11], "active_book_design_version_id": row[12],
            "title": row[13], "title_source_asset_version_id": row[12] or row[11],
        }

    def list_design_versions(self, *, project_id: str, book_id: str) -> list[dict[str, Any]]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT candidate.asset_version_id, version.version_number,
                       candidate.schema_version, candidate.content_hash,
                       candidate.status, version.lifecycle, version.content,
                       decision.decision_id, decision.decision,
                       activation.activation_id,
                       dependency.target_asset_version_id,
                       candidate.created_at
                FROM authority_book_design_candidate AS candidate
                JOIN authority_asset_version AS version
                  ON version.asset_version_id = candidate.asset_version_id
                LEFT JOIN LATERAL (
                    SELECT decision_id, decision
                    FROM authority_asset_decision
                    WHERE asset_version_id = candidate.asset_version_id
                    ORDER BY created_at DESC LIMIT 1
                ) AS decision ON TRUE
                LEFT JOIN authority_asset_activation AS activation
                  ON activation.asset_version_id = candidate.asset_version_id
                LEFT JOIN authority_asset_dependency AS dependency
                  ON dependency.source_asset_version_id = candidate.asset_version_id
                 AND dependency.dependency_type = 'REQUIRED'
                WHERE candidate.project_id = %s AND candidate.book_id = %s
                ORDER BY version.version_number
                """,
                [project_id, book_id],
            )
            rows = uow.cursor.fetchall()
        return [
            {
                "schema_version": "book-design-read-model.v1",
                "asset_version_id": row[0], "version_number": int(row[1]),
                "payload_schema_version": row[2], "content_hash": row[3],
                "status": row[4], "lifecycle": row[5], "content": row[6],
                "decision_id": row[7] or "", "decision": row[8] or "",
                "activation_id": row[9] or "",
                "book_dependency_version_id": row[10] or "", "created_at": str(row[11]),
            }
            for row in rows
        ]

    def outbox_projection(self, *, project_id: str, book_id: str) -> list[dict[str, Any]]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT outbox_id, topic, status, payload, created_at
                FROM outbox_event
                WHERE project_id = %s AND payload->>'book_id' = %s
                  AND topic LIKE 'authority.%%'
                ORDER BY created_at, outbox_id
                """,
                [project_id, book_id],
            )
            rows = uow.cursor.fetchall()
        return [
            {"outbox_id": row[0], "topic": row[1], "delivery_status": row[2], "payload": row[3], "created_at": str(row[4])}
            for row in rows
        ]


__all__ = ["BookDesignAuthorityQuery"]

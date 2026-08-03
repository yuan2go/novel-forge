"""PostgreSQL SourceDocument governance projection."""
from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


class SourceAuthorityQuery:
    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("PostgreSQL database_url is required")
        self.database_url = database_url

    def list_documents(
        self,
        *,
        project_id: str,
        governance_status: str = "",
        source_document_id: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if not project_id or limit < 1 or limit > 500:
            raise ValueError("project_id and a limit between 1 and 500 are required")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT source.source_document_id, source.project_id,
                       source.workspace_id, source.asset_version_id,
                       source.blob_id, source.source_content_hash,
                       source.source_size, source.media_type, source.title,
                       source.source_kind, source.source_uri,
                       source.rights_authorization, source.license_name,
                       source.copyright_boundary, source.governance_status,
                       source.created_by_operation_id, version.lifecycle,
                       version.eligibility, version.governance, version.content,
                       source.created_at
                FROM authority_source_document AS source
                JOIN authority_asset_version AS version
                  ON version.asset_version_id = source.asset_version_id
                WHERE source.project_id = %s
                  AND (%s = '' OR source.governance_status = %s)
                  AND (%s = '' OR source.source_document_id = %s)
                ORDER BY source.created_at DESC, source.source_document_id
                LIMIT %s
                """,
                [
                    project_id,
                    governance_status,
                    governance_status,
                    source_document_id,
                    source_document_id,
                    limit,
                ],
            )
            rows = uow.cursor.fetchall()
        keys = (
            "source_document_id",
            "project_id",
            "workspace_id",
            "asset_version_id",
            "blob_id",
            "source_content_hash",
            "source_size",
            "media_type",
            "title",
            "source_kind",
            "source_uri",
            "rights_authorization",
            "license_name",
            "copyright_boundary",
            "governance_status",
            "created_by_operation_id",
            "lifecycle",
            "eligibility",
            "governance",
            "content",
            "created_at",
        )
        return [dict(zip(keys, row, strict=True)) for row in rows]

    def require_document(
        self, *, project_id: str, source_document_id: str
    ) -> dict[str, Any]:
        rows = self.list_documents(
            project_id=project_id,
            source_document_id=source_document_id,
            limit=1,
        )
        if not rows:
            raise KernelError(
                "SOURCE_DOCUMENT_NOT_FOUND",
                "SourceDocument does not exist in the Authority project",
            )
        return rows[0]

    def list_transforms(
        self,
        *,
        project_id: str,
        source_document_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if not project_id or not source_document_id or limit < 1 or limit > 500:
            raise ValueError("project/source identity and a valid limit are required")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT transform.source_transform_id, transform.project_id,
                       transform.workspace_id, transform.source_document_id,
                       transform.source_asset_version_id,
                       transform.asset_version_id,
                       transform.created_by_operation_id,
                       transform.normalization_version,
                       transform.chunking_version,
                       transform.chunking_policy_hash,
                       transform.manifest_hash, transform.chunk_count,
                       transform.total_chunk_bytes, transform.status,
                       version.lifecycle, version.eligibility,
                       version.governance, version.content,
                       operation.status, transform.created_at
                FROM authority_source_transform AS transform
                JOIN authority_asset_version AS version
                  ON version.asset_version_id = transform.asset_version_id
                JOIN authority_operation AS operation
                  ON operation.operation_id = transform.created_by_operation_id
                WHERE transform.project_id = %s
                  AND transform.source_document_id = %s
                ORDER BY transform.created_at DESC, transform.source_transform_id
                LIMIT %s
                """,
                [project_id, source_document_id, limit],
            )
            rows = uow.cursor.fetchall()
        keys = (
            "source_transform_id",
            "project_id",
            "workspace_id",
            "source_document_id",
            "source_asset_version_id",
            "asset_version_id",
            "created_by_operation_id",
            "normalization_version",
            "chunking_version",
            "chunking_policy_hash",
            "manifest_hash",
            "chunk_count",
            "total_chunk_bytes",
            "transform_status",
            "lifecycle",
            "eligibility",
            "governance",
            "content",
            "operation_status",
            "created_at",
        )
        return [dict(zip(keys, row, strict=True)) for row in rows]

    def list_chunks(
        self,
        *,
        project_id: str,
        source_transform_id: str,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        if not project_id or not source_transform_id or limit < 1 or limit > 10_000:
            raise ValueError("project/transform identity and a valid limit are required")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT chunk.source_chunk_id, chunk.project_id,
                       chunk.workspace_id, chunk.source_transform_id,
                       chunk.source_document_id, chunk.asset_version_id,
                       chunk.blob_id, chunk.chunk_index, chunk.content_hash,
                       chunk.byte_size, chunk.character_count,
                       chunk.token_count, chunk.source_byte_start,
                       chunk.source_byte_end, chunk.created_by_operation_id,
                       version.lifecycle, version.eligibility,
                       version.governance, version.content, chunk.created_at
                FROM authority_source_chunk AS chunk
                JOIN authority_asset_version AS version
                  ON version.asset_version_id = chunk.asset_version_id
                WHERE chunk.project_id = %s
                  AND chunk.source_transform_id = %s
                ORDER BY chunk.chunk_index
                LIMIT %s
                """,
                [project_id, source_transform_id, limit],
            )
            rows = uow.cursor.fetchall()
        keys = (
            "source_chunk_id",
            "project_id",
            "workspace_id",
            "source_transform_id",
            "source_document_id",
            "asset_version_id",
            "blob_id",
            "chunk_index",
            "content_hash",
            "byte_size",
            "character_count",
            "token_count",
            "source_byte_start",
            "source_byte_end",
            "created_by_operation_id",
            "lifecycle",
            "eligibility",
            "governance",
            "content",
            "created_at",
        )
        return [dict(zip(keys, row, strict=True)) for row in rows]


__all__ = ["SourceAuthorityQuery"]

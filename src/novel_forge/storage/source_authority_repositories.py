from __future__ import annotations

from novel_forge.storage.corpus_records import CorpusRecords

from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError


class SourceAuthorityRepository(CorpusRecords):
    def __init__(self, cursor: Any) -> None:
        self.cursor = cursor

    def require_scope(self, *, project_id: str, workspace_id: str) -> None:
        self.cursor.execute(
            """
            SELECT project.status, workspace.status
            FROM authority_project AS project
            JOIN authority_workspace AS workspace
              ON workspace.workspace_id = %s
             AND workspace.project_id = project.project_id
            WHERE project.project_id = %s
            FOR SHARE OF project, workspace
            """,
            [workspace_id, project_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "SOURCE_PROJECT_SCOPE_INVALID",
                "Source workspace does not belong to the Authority project",
            )
        if "DELETED" in row or "ARCHIVED" in row:
            raise KernelError(
                "SOURCE_PROJECT_LIFECYCLE_BLOCKED",
                "archived or deleted Project/Workspace cannot accept sources",
            )

    def existing_by_hash(
        self, *, project_id: str, source_content_hash: str
    ) -> dict[str, Any] | None:
        self.cursor.execute(
            """
            SELECT source.source_document_id, source.asset_version_id,
                   source.blob_id, source.governance_status,
                   source.created_by_operation_id, operation.status
            FROM authority_source_document AS source
            JOIN authority_operation AS operation
              ON operation.operation_id = source.created_by_operation_id
            WHERE source.project_id = %s AND source.source_content_hash = %s
            """,
            [project_id, source_content_hash],
        )
        row = self.cursor.fetchone()
        if row is None:
            return None
        return {
            "source_document_id": row[0],
            "asset_version_id": row[1],
            "blob_id": row[2],
            "governance_status": row[3],
            "operation_id": row[4],
            "status": row[5],
        }

    def register(self, row: dict[str, Any]) -> None:
        self.cursor.execute(
            """
            INSERT INTO authority_source_document (
                source_document_id, project_id, workspace_id,
                asset_version_id, blob_id, source_content_hash,
                source_size, media_type, title, source_kind, source_uri,
                rights_authorization, license_name, copyright_boundary,
                governance_status, created_by_operation_id
            ) VALUES (
                %(source_document_id)s, %(project_id)s, %(workspace_id)s,
                %(asset_version_id)s, %(blob_id)s, %(source_content_hash)s,
                %(source_size)s, %(media_type)s, %(title)s, %(source_kind)s,
                %(source_uri)s, %(rights_authorization)s, %(license_name)s,
                %(copyright_boundary)s, %(governance_status)s,
                %(created_by_operation_id)s
            )
            """,
            row,
        )

    def source_for_transform(
        self, *, project_id: str, source_document_id: str
    ) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT source.source_document_id, source.project_id,
                   source.workspace_id, source.asset_version_id,
                   source.blob_id, source.source_content_hash,
                   source.source_size, source.governance_status,
                   version.lifecycle, version.eligibility, version.governance,
                   version.content_hash, source.created_by_operation_id
            FROM authority_source_document AS source
            JOIN authority_asset_version AS version
              ON version.asset_version_id = source.asset_version_id
            WHERE source.source_document_id = %s AND source.project_id = %s
            FOR SHARE OF source, version
            """,
            [source_document_id, project_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "SOURCE_DOCUMENT_NOT_FOUND",
                "SourceDocument does not exist in the Authority project",
            )
        keys = (
            "source_document_id",
            "project_id",
            "workspace_id",
            "asset_version_id",
            "blob_id",
            "source_content_hash",
            "source_size",
            "governance_status",
            "lifecycle",
            "eligibility",
            "governance",
            "asset_content_hash",
            "created_by_operation_id",
        )
        return dict(zip(keys, row, strict=True))

    def chunk_blobs_for_update(self, blob_ids: tuple[str, ...]) -> dict[str, dict[str, Any]]:
        self.cursor.execute(
            """
            SELECT blob_id, project_id, provider, object_key, expected_hash,
                   expected_size, media_type, actual_object_key, actual_hash,
                   actual_size, receipt_provider, status
            FROM authority_blob
            WHERE blob_id = ANY(%s)
            ORDER BY blob_id
            FOR UPDATE
            """,
            [list(blob_ids)],
        )
        keys = (
            "blob_id",
            "project_id",
            "provider",
            "object_key",
            "expected_hash",
            "expected_size",
            "media_type",
            "actual_object_key",
            "actual_hash",
            "actual_size",
            "receipt_provider",
            "status",
        )
        return {
            str(row[0]): dict(zip(keys, row, strict=True))
            for row in self.cursor.fetchall()
        }

    def existing_transform(
        self,
        *,
        source_asset_version_id: str,
        chunking_policy_hash: str,
        manifest_hash: str,
    ) -> dict[str, Any] | None:
        self.cursor.execute(
            """
            SELECT transform.source_transform_id, transform.asset_version_id,
                   transform.created_by_operation_id, transform.status,
                   operation.status
            FROM authority_source_transform AS transform
            JOIN authority_operation AS operation
              ON operation.operation_id = transform.created_by_operation_id
            WHERE transform.source_asset_version_id = %s
              AND transform.chunking_policy_hash = %s
              AND transform.manifest_hash = %s
            """,
            [source_asset_version_id, chunking_policy_hash, manifest_hash],
        )
        row = self.cursor.fetchone()
        if row is None:
            return None
        return {
            "source_transform_id": row[0],
            "asset_version_id": row[1],
            "operation_id": row[2],
            "status": row[3],
            "operation_status": row[4],
        }

    def register_transform(self, row: dict[str, Any]) -> None:
        self.cursor.execute(
            """
            INSERT INTO authority_source_transform (
                source_transform_id, project_id, workspace_id,
                source_document_id, source_asset_version_id,
                asset_version_id, created_by_operation_id,
                normalization_version, chunking_version,
                chunking_policy_hash, manifest_hash, chunk_count,
                total_chunk_bytes, normalized_blob_id,
                normalized_content_hash, normalized_byte_size, status
            ) VALUES (
                %(source_transform_id)s, %(project_id)s, %(workspace_id)s,
                %(source_document_id)s, %(source_asset_version_id)s,
                %(asset_version_id)s, %(created_by_operation_id)s,
                %(normalization_version)s, %(chunking_version)s,
                %(chunking_policy_hash)s, %(manifest_hash)s,
                %(chunk_count)s, %(total_chunk_bytes)s,
                %(normalized_blob_id)s, %(normalized_content_hash)s,
                %(normalized_byte_size)s, 'ACTIVE'
            )
            """,
            row,
        )

    def register_chunk(self, row: dict[str, Any]) -> None:
        self.cursor.execute(
            """
            INSERT INTO authority_source_chunk (
                source_chunk_id, project_id, workspace_id,
                source_transform_id, source_document_id,
                asset_version_id, blob_id, chunk_index, content_hash,
                byte_size, character_count, token_count,
                source_byte_start, source_byte_end,
                created_by_operation_id
            ) VALUES (
                %(source_chunk_id)s, %(project_id)s, %(workspace_id)s,
                %(source_transform_id)s, %(source_document_id)s,
                %(asset_version_id)s, %(blob_id)s, %(chunk_index)s,
                %(content_hash)s, %(byte_size)s, %(character_count)s,
                %(token_count)s, %(source_byte_start)s,
                %(source_byte_end)s, %(created_by_operation_id)s
            )
            """,
            row,
        )


__all__ = ["SourceAuthorityRepository"]

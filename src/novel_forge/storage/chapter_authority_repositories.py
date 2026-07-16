"""Focused repository for fenced chapter-handler input and output evidence."""
from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.errors import KernelError


class ChapterAuthorityRepository:
    def __init__(self, cursor: Any) -> None:
        self.cursor = cursor

    def operation_execution(self, operation_id: str, project_id: str) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT operation_id, project_id, workspace_id, status, definition_name,
                   definition_version, definition_snapshot, command_payload,
                   input_asset_snapshot, trace_id, correlation_id
            FROM authority_operation
            WHERE operation_id = %s AND project_id = %s
            """,
            [operation_id, project_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError("OPERATION_NOT_FOUND", "chapter operation does not exist")
        fields = (
            "operation_id",
            "project_id",
            "workspace_id",
            "status",
            "definition_name",
            "definition_version",
            "definition_snapshot",
            "command_payload",
            "input_asset_snapshot",
            "trace_id",
            "correlation_id",
        )
        return dict(zip(fields, row, strict=True))

    def frozen_inputs(
        self,
        project_id: str,
        snapshots: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        resolved: list[dict[str, Any]] = []
        for snapshot in snapshots:
            asset_version_id = str(snapshot.get("asset_version_id") or "")
            content_hash = str(snapshot.get("content_hash") or "")
            self.cursor.execute(
                """
                SELECT version.asset_version_id, asset.asset_type,
                       version.content_hash, version.content
                FROM authority_asset_version AS version
                JOIN authority_asset AS asset ON asset.asset_id = version.asset_id
                WHERE version.asset_version_id = %s
                  AND asset.project_id = %s
                  AND version.content_hash = %s
                """,
                [asset_version_id, project_id, content_hash],
            )
            row = self.cursor.fetchone()
            if row is None:
                raise KernelError(
                    "CHAPTER_INPUT_SNAPSHOT_STALE",
                    f"frozen chapter input is missing or changed: {asset_version_id}",
                )
            resolved.append(
                {
                    "asset_version_id": row[0],
                    "asset_type": row[1],
                    "content_hash": row[2],
                    "content": row[3],
                }
            )
        return resolved

    def materialize_output(
        self,
        *,
        operation_id: str,
        project_id: str,
        asset_id: str,
        asset_version_id: str,
        qualification_id: str,
        asset_type: str,
        output_key: str,
        role: str,
        content: dict[str, Any],
        content_hash: str,
        qualification_policy: str,
        qualification_evidence: dict[str, Any],
    ) -> bool:
        self.cursor.execute(
            """
            INSERT INTO authority_asset (asset_id, project_id, asset_type)
            VALUES (%s, %s, %s)
            ON CONFLICT (asset_id) DO NOTHING
            """,
            [asset_id, project_id, asset_type],
        )
        self.cursor.execute(
            "SELECT project_id, asset_type FROM authority_asset WHERE asset_id = %s",
            [asset_id],
        )
        asset = self.cursor.fetchone()
        if asset != (project_id, asset_type):
            raise KernelError(
                "CHAPTER_OUTPUT_REPLAY_CONFLICT",
                "stable chapter Asset identity belongs to different content scope",
            )
        self.cursor.execute(
            """
            INSERT INTO authority_asset_version (
                asset_version_id, asset_id, version_number, lifecycle,
                eligibility, governance, content, content_hash
            ) VALUES (%s, %s, 1, 'ACTIVE', 'ELIGIBLE', 'CLEAR', %s, %s)
            ON CONFLICT (asset_version_id) DO NOTHING
            RETURNING asset_version_id
            """,
            [asset_version_id, asset_id, Jsonb(content), content_hash],
        )
        created = self.cursor.fetchone() is not None
        self.cursor.execute(
            """
            SELECT asset_id, content_hash, content, lifecycle, eligibility, governance
            FROM authority_asset_version WHERE asset_version_id = %s
            """,
            [asset_version_id],
        )
        version = self.cursor.fetchone()
        expected = (asset_id, content_hash, content, "ACTIVE", "ELIGIBLE", "CLEAR")
        if version != expected:
            raise KernelError(
                "CHAPTER_OUTPUT_REPLAY_CONFLICT",
                "stable chapter AssetVersion identity has different content",
            )
        self.cursor.execute(
            """
            INSERT INTO authority_asset_qualification (
                qualification_id, asset_version_id, policy_version, decision, evidence
            ) VALUES (%s, %s, %s, 'ELIGIBLE', %s)
            ON CONFLICT (qualification_id) DO NOTHING
            """,
            [
                qualification_id,
                asset_version_id,
                qualification_policy,
                Jsonb(qualification_evidence),
            ],
        )
        self.cursor.execute(
            """
            INSERT INTO authority_operation_output_asset (
                operation_id, asset_id, asset_version_id,
                output_key, role, content_hash
            ) VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (operation_id, output_key, role, asset_version_id) DO NOTHING
            """,
            [operation_id, asset_id, asset_version_id, output_key, role, content_hash],
        )
        return created

"""Focused PostgreSQL repositories for authoritative Asset and Blob commands."""
from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.errors import KernelError


class AssetBlobRepository:
    def __init__(self, cursor: Any) -> None:
        self.cursor = cursor

    def require_executing_operation(self, operation_id: str, project_id: str) -> None:
        self.cursor.execute(
            """
            SELECT status
            FROM authority_operation
            WHERE operation_id = %s AND project_id = %s
            FOR UPDATE
            """,
            [operation_id, project_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError("OPERATION_NOT_FOUND", "handler operation does not exist")
        if row[0] != "EXECUTING":
            raise KernelError(
                "OPERATION_STATUS_CONFLICT",
                f"asset handler requires EXECUTING operation, current status {row[0]}",
            )

    def create_asset(self, asset_id: str, project_id: str, asset_type: str) -> None:
        self.cursor.execute(
            """
            INSERT INTO authority_asset (asset_id, project_id, asset_type)
            VALUES (%s, %s, %s)
            """,
            [asset_id, project_id, asset_type],
        )

    def asset_for_update(self, asset_id: str, project_id: str) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT asset_id, project_id, asset_type
            FROM authority_asset
            WHERE asset_id = %s
            FOR UPDATE
            """,
            [asset_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError("ASSET_NOT_FOUND", "asset does not exist")
        if row[1] != project_id:
            raise KernelError("CROSS_PROJECT_REFERENCE", "asset belongs to another project")
        return {"asset_id": row[0], "project_id": row[1], "asset_type": row[2]}

    def next_version_number(self, asset_id: str) -> int:
        self.cursor.execute(
            """
            SELECT COALESCE(MAX(version_number), 0) + 1
            FROM authority_asset_version
            WHERE asset_id = %s
            """,
            [asset_id],
        )
        return int(self.cursor.fetchone()[0])

    def create_version(self, row: dict[str, Any]) -> None:
        self.cursor.execute(
            """
            INSERT INTO authority_asset_version (
                asset_version_id, asset_id, version_number,
                lifecycle, eligibility, governance, content, content_hash, schema_version
            )
            VALUES (
                %(asset_version_id)s, %(asset_id)s, %(version_number)s,
                'DRAFT', 'PENDING_EVALUATION', 'CLEAR', %(content)s, %(content_hash)s,
                %(schema_version)s
            )
            """,
            {**row, "content": Jsonb(row["content"])},
        )

    def version_for_update(self, asset_version_id: str) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT version.asset_version_id, version.asset_id, asset.project_id,
                   version.lifecycle, version.eligibility, version.governance,
                   version.content_hash
            FROM authority_asset_version AS version
            JOIN authority_asset AS asset ON asset.asset_id = version.asset_id
            WHERE version.asset_version_id = %s
            FOR UPDATE OF version, asset
            """,
            [asset_version_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError("ASSET_VERSION_NOT_FOUND", "asset version does not exist")
        fields = (
            "asset_version_id",
            "asset_id",
            "project_id",
            "lifecycle",
            "eligibility",
            "governance",
            "content_hash",
        )
        return dict(zip(fields, row, strict=True))

    def active_version(self, asset_id: str) -> str | None:
        self.cursor.execute(
            """
            SELECT asset_version_id
            FROM authority_asset_version
            WHERE asset_id = %s AND lifecycle = 'ACTIVE'
            """,
            [asset_id],
        )
        row = self.cursor.fetchone()
        return row[0] if row else None

    def activate_version(self, asset_version_id: str) -> None:
        self.cursor.execute(
            """
            UPDATE authority_asset_version
            SET lifecycle = 'ACTIVE'
            WHERE asset_version_id = %s AND lifecycle = 'DRAFT'
            """,
            [asset_version_id],
        )
        if self.cursor.rowcount != 1:
            raise KernelError(
                "ASSET_VERSION_STATUS_CONFLICT",
                "only a DRAFT asset version can be activated",
            )

    def bind_operation_output(
        self,
        *,
        operation_id: str,
        asset_id: str,
        asset_version_id: str,
        output_key: str,
        role: str,
        content_hash: str,
    ) -> bool:
        self.cursor.execute(
            """
            INSERT INTO authority_operation_output_asset (
                operation_id, asset_id, asset_version_id,
                output_key, role, content_hash
            ) VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (operation_id, output_key, role, asset_version_id) DO NOTHING
            RETURNING operation_id
            """,
            [operation_id, asset_id, asset_version_id, output_key, role, content_hash],
        )
        return self.cursor.fetchone() is not None

    def qualify_version(
        self,
        qualification_id: str,
        asset_version_id: str,
        policy_version: str,
        decision: str,
        evidence: dict[str, Any],
    ) -> None:
        self.cursor.execute(
            """
            INSERT INTO authority_asset_qualification (
                qualification_id, asset_version_id, policy_version, decision, evidence
            )
            VALUES (%s, %s, %s, %s, %s)
            """,
            [qualification_id, asset_version_id, policy_version, decision, Jsonb(evidence)],
        )
        self.cursor.execute(
            """
            UPDATE authority_asset_version
            SET eligibility = %s
            WHERE asset_version_id = %s
            """,
            [decision, asset_version_id],
        )

    def reserve_blob(self, row: dict[str, Any]) -> bool:
        parameters = {
            **row,
            "retention_class": str(row.get("retention_class") or "STANDARD"),
            "encryption_metadata": Jsonb(dict(row.get("encryption_metadata") or {})),
        }
        self.cursor.execute(
            """
            INSERT INTO authority_blob (
                blob_id, project_id, provider, object_key, expected_hash,
                expected_size, media_type, status, retention_class,
                encryption_metadata
            )
            VALUES (
                %(blob_id)s, %(project_id)s, %(provider)s, %(object_key)s,
                %(expected_hash)s, %(expected_size)s, %(media_type)s, 'PENDING_UPLOAD',
                %(retention_class)s, %(encryption_metadata)s
            )
            ON CONFLICT (blob_id) DO NOTHING
            RETURNING blob_id
            """,
            parameters,
        )
        return self.cursor.fetchone() is not None

    def blob_for_update(self, blob_id: str) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT blob_id, project_id, provider, object_key, expected_hash,
                   expected_size, media_type, actual_object_key, actual_hash,
                   actual_size, receipt_provider, status, legal_hold, upload_effect_id,
                   retention_class, encryption_metadata, retention_until,
                   orphan_detected_at, gc_eligible_at, gc_operation_id
            FROM authority_blob
            WHERE blob_id = %s
            FOR UPDATE
            """,
            [blob_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError("BLOB_NOT_FOUND", "blob does not exist")
        fields = (
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
            "legal_hold",
            "upload_effect_id",
            "retention_class",
            "encryption_metadata",
            "retention_until",
            "orphan_detected_at",
            "gc_eligible_at",
            "gc_operation_id",
        )
        return dict(zip(fields, row, strict=True))

    def detect_orphans(
        self,
        *,
        project_id: str,
        operation_id: str,
        minimum_age_seconds: int,
        gc_grace_seconds: int,
    ) -> list[str]:
        self.cursor.execute(
            """
            UPDATE authority_blob AS blob
            SET orphan_detected_at = COALESCE(blob.orphan_detected_at, NOW()),
                gc_eligible_at = COALESCE(
                    blob.gc_eligible_at,
                    NOW() + (%s * INTERVAL '1 second')
                ),
                gc_operation_id = %s
            WHERE blob.project_id = %s
              AND blob.status IN ('AVAILABLE', 'FAILED', 'ABANDONED', 'QUARANTINED')
              AND blob.legal_hold = FALSE
              AND blob.retention_class <> 'LEGAL_HOLD'
              AND (blob.retention_until IS NULL OR blob.retention_until <= NOW())
              AND blob.created_at <= NOW() - (%s * INTERVAL '1 second')
              AND NOT EXISTS (
                    SELECT 1
                    FROM authority_asset_version_blob_reference AS reference
                    WHERE reference.blob_id = blob.blob_id
              )
            RETURNING blob.blob_id
            """,
            [gc_grace_seconds, operation_id, project_id, minimum_age_seconds],
        )
        return [str(row[0]) for row in self.cursor.fetchall()]

    def clear_resolved_orphans(self, *, project_id: str) -> list[str]:
        self.cursor.execute(
            """
            UPDATE authority_blob AS blob
            SET orphan_detected_at = NULL,
                gc_eligible_at = NULL,
                gc_operation_id = NULL
            WHERE blob.project_id = %s
              AND blob.orphan_detected_at IS NOT NULL
              AND EXISTS (
                    SELECT 1
                    FROM authority_asset_version_blob_reference AS reference
                    WHERE reference.blob_id = blob.blob_id
              )
            RETURNING blob.blob_id
            """,
            [project_id],
        )
        return [str(row[0]) for row in self.cursor.fetchall()]

    def gc_candidates(self, *, project_id: str, limit: int) -> list[dict[str, Any]]:
        self.cursor.execute(
            """
            SELECT blob_id, provider, object_key, expected_hash, expected_size,
                   retention_class, orphan_detected_at, gc_eligible_at,
                   gc_operation_id
            FROM authority_blob AS blob
            WHERE project_id = %s
              AND orphan_detected_at IS NOT NULL
              AND gc_eligible_at <= NOW()
              AND legal_hold = FALSE
              AND retention_class <> 'LEGAL_HOLD'
              AND status IN ('AVAILABLE', 'FAILED', 'ABANDONED', 'QUARANTINED')
              AND NOT EXISTS (
                    SELECT 1
                    FROM authority_asset_version_blob_reference AS reference
                    WHERE reference.blob_id = blob.blob_id
              )
            ORDER BY gc_eligible_at, blob_id
            LIMIT %s
            FOR UPDATE SKIP LOCKED
            """,
            [project_id, limit],
        )
        fields = (
            "blob_id", "provider", "object_key", "content_hash", "size",
            "retention_class", "orphan_detected_at", "gc_eligible_at",
            "gc_operation_id",
        )
        return [dict(zip(fields, row, strict=True)) for row in self.cursor.fetchall()]

    def attach_upload_effect(self, blob_id: str, external_effect_id: str) -> None:
        self.cursor.execute(
            """
            UPDATE authority_blob
            SET upload_effect_id = %s, status = 'UPLOADING'
            WHERE blob_id = %s
              AND (upload_effect_id IS NULL OR upload_effect_id = %s)
              AND status IN ('PENDING_UPLOAD', 'UPLOADING')
            """,
            [external_effect_id, blob_id, external_effect_id],
        )
        if self.cursor.rowcount != 1:
            raise KernelError("BLOB_STATUS_CONFLICT", "blob is not uploadable")

    def update_blob_status(self, blob_id: str, expected: tuple[str, ...], target: str) -> None:
        self.cursor.execute(
            """
            UPDATE authority_blob
            SET status = %s
            WHERE blob_id = %s AND status = ANY(%s)
            """,
            [target, blob_id, list(expected)],
        )
        if self.cursor.rowcount != 1:
            raise KernelError("BLOB_STATUS_CONFLICT", f"blob cannot transition to {target}")

    def accept_generic_upload_receipt(
        self,
        *,
        blob_id: str,
        project_id: str,
        provider: str,
        object_key: str,
        actual_hash: str,
        actual_size: int,
    ) -> None:
        self.cursor.execute(
            """
            UPDATE authority_blob
            SET status = 'UPLOADED', actual_object_key = %s,
                actual_hash = %s, actual_size = %s, receipt_provider = %s
            WHERE blob_id = %s AND project_id = %s
              AND provider = %s
              AND status IN ('UPLOADING', 'RECONCILIATION_REQUIRED')
            """,
            [
                object_key,
                actual_hash,
                actual_size,
                provider,
                blob_id,
                project_id,
                provider,
            ],
        )
        if self.cursor.rowcount != 1:
            raise KernelError(
                "BLOB_STATUS_CONFLICT",
                "Blob cannot accept the generic ExternalEffect receipt",
            )

    def bind_blob(
        self,
        reference_id: str,
        asset_version_id: str,
        blob_id: str,
        role: str,
        ordinal: int,
        media_type: str,
        content_hash: str,
    ) -> None:
        self.cursor.execute(
            """
            INSERT INTO authority_asset_version_blob_reference (
                reference_id, asset_version_id, blob_id, role,
                ordinal, media_type, content_hash
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            [
                reference_id,
                asset_version_id,
                blob_id,
                role,
                ordinal,
                media_type,
                content_hash,
            ],
        )

    def set_legal_hold(self, blob_id: str, enabled: bool) -> None:
        self.cursor.execute(
            "UPDATE authority_blob SET legal_hold = %s WHERE blob_id = %s",
            [enabled, blob_id],
        )

    def reference_count(self, blob_id: str) -> int:
        self.cursor.execute(
            "SELECT COUNT(*) FROM authority_asset_version_blob_reference WHERE blob_id = %s",
            [blob_id],
        )
        return int(self.cursor.fetchone()[0])

    def mark_upload_unknown(self, blob_id: str, project_id: str) -> None:
        self.cursor.execute(
            """
            UPDATE authority_blob
            SET status = 'RECONCILIATION_REQUIRED'
            WHERE blob_id = %s AND project_id = %s AND status = 'UPLOADING'
            """,
            [blob_id, project_id],
        )
        if self.cursor.rowcount != 1:
            raise KernelError("BLOB_STATUS_CONFLICT", "Blob is not awaiting upload result")

    def record_event(self, row: dict[str, Any]) -> None:
        self.cursor.execute(
            """
            SELECT COALESCE(MAX(sequence_number), 0) + 1
            FROM state_event
            WHERE aggregate_type = %(aggregate_type)s AND aggregate_id = %(aggregate_id)s
            """,
            row,
        )
        sequence = self.cursor.fetchone()[0]
        payload = Jsonb(row["payload"])
        params = {**row, "sequence_number": sequence, "payload": payload}
        self.cursor.execute(
            """
            INSERT INTO state_event (
                event_id, aggregate_type, aggregate_id, project_id, event_type,
                event_version, sequence_number, correlation_id, causation_id, payload
            )
            VALUES (
                %(event_id)s, %(aggregate_type)s, %(aggregate_id)s, %(project_id)s,
                %(event_type)s, 1, %(sequence_number)s,
                %(correlation_id)s, %(causation_id)s, %(payload)s
            )
            """,
            params,
        )
        self.cursor.execute(
            """
            INSERT INTO audit_log (audit_id, project_id, operation_id, action, payload)
            VALUES (%(audit_id)s, %(project_id)s, %(operation_id)s, %(event_type)s, %(payload)s)
            """,
            params,
        )
        self.cursor.execute(
            """
            INSERT INTO outbox_event (outbox_id, event_id, project_id, topic, status, payload)
            VALUES (
                %(outbox_id)s, %(event_id)s, %(project_id)s,
                %(event_type)s, 'PENDING', %(payload)s
            )
            """,
            params,
        )

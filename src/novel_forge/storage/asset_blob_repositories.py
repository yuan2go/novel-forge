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
                lifecycle, eligibility, governance, content, content_hash
            )
            VALUES (
                %(asset_version_id)s, %(asset_id)s, %(version_number)s,
                'DRAFT', 'PENDING_EVALUATION', 'CLEAR', %(content)s, %(content_hash)s
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

    def reserve_blob(self, row: dict[str, Any]) -> None:
        self.cursor.execute(
            """
            INSERT INTO authority_blob (
                blob_id, project_id, provider, object_key, expected_hash,
                expected_size, media_type, status
            )
            VALUES (
                %(blob_id)s, %(project_id)s, %(provider)s, %(object_key)s,
                %(expected_hash)s, %(expected_size)s, %(media_type)s, 'PENDING_UPLOAD'
            )
            """,
            row,
        )

    def blob_for_update(self, blob_id: str) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT blob_id, project_id, provider, object_key, expected_hash,
                   expected_size, media_type, actual_object_key, actual_hash,
                   actual_size, receipt_provider, status, legal_hold, upload_effect_id
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
        )
        return dict(zip(fields, row, strict=True))

    def plan_effect(self, row: dict[str, Any]) -> dict[str, Any]:
        self.cursor.execute(
            """
            INSERT INTO authority_external_effect (
                external_effect_id, operation_id, effect_type,
                stable_idempotency_key, status, request_hash, request_payload
            )
            VALUES (
                %(external_effect_id)s, %(operation_id)s, %(effect_type)s,
                %(stable_idempotency_key)s, 'DISPATCHABLE', %(request_hash)s,
                %(request_payload)s
            )
            ON CONFLICT (effect_type, stable_idempotency_key) DO NOTHING
            RETURNING external_effect_id
            """,
            {**row, "request_payload": Jsonb(row["request_payload"])},
        )
        inserted = self.cursor.fetchone()
        if inserted:
            return {"external_effect_id": inserted[0], "replayed": False}
        self.cursor.execute(
            """
            SELECT external_effect_id, request_hash
            FROM authority_external_effect
            WHERE effect_type = %s AND stable_idempotency_key = %s
            FOR UPDATE
            """,
            [row["effect_type"], row["stable_idempotency_key"]],
        )
        existing = self.cursor.fetchone()
        if existing is None or existing[1] != row["request_hash"]:
            raise KernelError(
                "EFFECT_DISPATCH_CONFLICT",
                "stable external-effect key belongs to another request payload",
            )
        return {"external_effect_id": existing[0], "replayed": True}

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

    def effect_for_update(self, effect_id: str) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT effect.external_effect_id, effect.operation_id, operation.project_id,
                   effect.effect_type, effect.status, effect.request_hash,
                   effect.request_payload
            FROM authority_external_effect AS effect
            JOIN authority_operation AS operation
              ON operation.operation_id = effect.operation_id
            WHERE effect.external_effect_id = %s
            FOR UPDATE OF effect
            """,
            [effect_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError("EXTERNAL_EFFECT_NOT_FOUND", "external effect does not exist")
        fields = (
            "external_effect_id",
            "operation_id",
            "project_id",
            "effect_type",
            "status",
            "request_hash",
            "request_payload",
        )
        return dict(zip(fields, row, strict=True))

    def begin_dispatch(
        self,
        dispatch_id: str,
        effect_id: str,
        provider: str,
        payload_hash: str,
    ) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT dispatch_id, provider
            FROM authority_external_effect_dispatch
            WHERE external_effect_id = %s AND generation = 1
            FOR UPDATE
            """,
            [effect_id],
        )
        existing = self.cursor.fetchone()
        if existing:
            if existing[1] != provider:
                raise KernelError(
                    "EFFECT_DISPATCH_CONFLICT",
                    "dispatch generation is already bound to another provider",
                )
            return {"dispatch_id": existing[0], "generation": 1, "replayed": True}
        self.cursor.execute(
            """
            INSERT INTO authority_external_effect_dispatch (
                dispatch_id, external_effect_id, generation, status,
                provider, payload_hash, evidence
            )
            VALUES (%s, %s, 1, 'SENT', %s, %s, '{}'::jsonb)
            """,
            [dispatch_id, effect_id, provider, payload_hash],
        )
        self.cursor.execute(
            """
            UPDATE authority_external_effect
            SET status = 'IN_FLIGHT'
            WHERE external_effect_id = %s AND status = 'DISPATCHABLE'
            """,
            [effect_id],
        )
        if self.cursor.rowcount != 1:
            raise KernelError("EFFECT_STATUS_CONFLICT", "effect is not dispatchable")
        return {"dispatch_id": dispatch_id, "generation": 1, "replayed": False}

    def dispatch_for_update(self, dispatch_id: str) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT dispatch.dispatch_id, dispatch.external_effect_id,
                   dispatch.generation, dispatch.status, dispatch.provider,
                   effect.effect_type, effect.status, effect.request_payload,
                   operation.project_id
            FROM authority_external_effect_dispatch AS dispatch
            JOIN authority_external_effect AS effect
              ON effect.external_effect_id = dispatch.external_effect_id
            JOIN authority_operation AS operation
              ON operation.operation_id = effect.operation_id
            WHERE dispatch.dispatch_id = %s
            FOR UPDATE OF dispatch, effect
            """,
            [dispatch_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError("EFFECT_DISPATCH_NOT_FOUND", "dispatch does not exist")
        fields = (
            "dispatch_id",
            "external_effect_id",
            "generation",
            "status",
            "provider",
            "effect_type",
            "effect_status",
            "request_payload",
            "project_id",
        )
        return dict(zip(fields, row, strict=True))

    def record_inbox(
        self,
        consumer_name: str,
        message_id: str,
        payload_hash: str,
        outcome: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        self.cursor.execute(
            """
            SELECT disposition, stored_outcome
            FROM authority_record_inbox_message(%s, %s, %s, %s)
            """,
            [consumer_name, message_id, payload_hash, Jsonb(outcome)],
        )
        row = self.cursor.fetchone()
        return row[0], row[1]

    def insert_receipt(
        self,
        provider: str,
        receipt_id: str,
        dispatch_id: str,
        payload_hash: str,
        payload: dict[str, Any],
    ) -> None:
        self.cursor.execute(
            """
            INSERT INTO authority_external_receipt (
                provider, receipt_id, dispatch_id, payload_hash, payload
            )
            VALUES (%s, %s, %s, %s, %s)
            """,
            [provider, receipt_id, dispatch_id, payload_hash, Jsonb(payload)],
        )

    def accept_upload_receipt(
        self,
        dispatch_id: str,
        receipt_id: str,
        blob_id: str,
        provider: str,
        object_key: str,
        actual_hash: str,
        actual_size: int,
    ) -> None:
        self.cursor.execute(
            """
            UPDATE authority_external_effect_dispatch
            SET status = 'ACKNOWLEDGED', receipt_id = %s
            WHERE dispatch_id = %s AND status IN ('SENT', 'UNKNOWN', 'TIMED_OUT')
            """,
            [receipt_id, dispatch_id],
        )
        if self.cursor.rowcount != 1:
            raise KernelError("EFFECT_DISPATCH_CONFLICT", "dispatch cannot accept receipt")
        self.cursor.execute(
            """
            UPDATE authority_external_effect
            SET status = 'SUCCEEDED'
            WHERE external_effect_id = (
                SELECT external_effect_id
                FROM authority_external_effect_dispatch
                WHERE dispatch_id = %s
            )
              AND status IN ('IN_FLIGHT', 'UNKNOWN', 'RECONCILIATION_REQUIRED')
            """,
            [dispatch_id],
        )
        if self.cursor.rowcount != 1:
            raise KernelError("EFFECT_STATUS_CONFLICT", "effect cannot accept receipt")
        self.cursor.execute(
            """
            UPDATE authority_blob
            SET status = 'UPLOADED',
                actual_object_key = %s,
                actual_hash = %s,
                actual_size = %s,
                receipt_provider = %s
            WHERE blob_id = %s
              AND status IN ('UPLOADING', 'RECONCILIATION_REQUIRED')
            """,
            [object_key, actual_hash, actual_size, provider, blob_id],
        )
        if self.cursor.rowcount != 1:
            raise KernelError("BLOB_STATUS_CONFLICT", "blob cannot accept upload receipt")

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

    def mark_unknown(
        self,
        dispatch_id: str,
        effect_id: str,
        blob_id: str,
        evidence: dict[str, Any],
    ) -> None:
        self.cursor.execute(
            """
            UPDATE authority_external_effect_dispatch
            SET status = 'UNKNOWN', evidence = evidence || %s
            WHERE dispatch_id = %s AND status = 'SENT'
            """,
            [Jsonb(evidence), dispatch_id],
        )
        if self.cursor.rowcount != 1:
            raise KernelError("EFFECT_DISPATCH_CONFLICT", "dispatch is not awaiting result")
        self.cursor.execute(
            """
            UPDATE authority_external_effect
            SET status = 'RECONCILIATION_REQUIRED', reconciliation = %s
            WHERE external_effect_id = %s AND status = 'IN_FLIGHT'
            """,
            [Jsonb(evidence), effect_id],
        )
        self.cursor.execute(
            """
            UPDATE authority_blob
            SET status = 'RECONCILIATION_REQUIRED'
            WHERE blob_id = %s AND status = 'UPLOADING'
            """,
            [blob_id],
        )

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

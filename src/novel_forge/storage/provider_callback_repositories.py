from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.errors import KernelError


class ProviderCallbackRepository:
    def __init__(self, cursor: Any) -> None:
        self.cursor = cursor

    def effect_binding_for_update(
        self, provider: str, provider_request_id: str
    ) -> dict[str, Any] | None:
        self.cursor.execute(
            """
            SELECT effect.external_effect_id, effect.operation_id, effect.project_id,
                   effect.status, dispatch.dispatch_id, dispatch.generation,
                   effect.provider, effect.stable_idempotency_key
            FROM authority_external_effect AS effect
            JOIN authority_external_effect_dispatch AS dispatch USING(external_effect_id)
            LEFT JOIN authority_generation_isolation AS isolation USING(external_effect_id)
            WHERE (isolation.external_effect_id IS NULL
                AND effect.provider_request_id = %s
                AND dispatch.generation = (SELECT max(generation) FROM authority_external_effect_dispatch WHERE external_effect_id=effect.external_effect_id)
                AND (effect.provider = %s OR (effect.provider = 'production_execution_gateway'
                    AND effect.request_payload #>> '{_production_execution,route_provider}' = %s)))
              OR (isolation.external_effect_id IS NOT NULL
                AND dispatch.evidence #>> '{production_execution,execution_handle,provider_request_id}' = %s
                AND dispatch.evidence #>> '{production_execution,route_snapshot,model_provider}' = %s
                AND isolation.proof->'dispatch_ids' ? dispatch.dispatch_id)
            FOR UPDATE OF effect
            """,
            [provider_request_id, provider, provider, provider_request_id, provider],
        )
        rows = self.cursor.fetchall()
        if not rows:
            return None
        if len(rows) != 1:
            raise KernelError("PROVIDER_CALLBACK_BINDING_AMBIGUOUS", "Bind one immutable original dispatch; never select another Book or generation")
        row = rows[0]
        fields = (
            "external_effect_id", "operation_id", "project_id", "status",
            "dispatch_id", "generation", "effect_provider",
            "stable_idempotency_key",
        )
        return dict(zip(fields, row, strict=True))

    def record_receipt(self, row: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        self.cursor.execute(
            """
            SELECT callback_receipt_id, payload_hash, provider_request_id,
                   outcome, processing_status, project_id, external_effect_id, dispatch_id
            FROM authority_provider_callback_receipt
            WHERE provider=%s AND (provider_message_id=%s
                OR (provider_request_id=%s AND payload_hash=%s))
            ORDER BY (provider_message_id=%s) DESC LIMIT 1
            FOR UPDATE
            """,
            [row["provider"], row["provider_message_id"], row["provider_request_id"],
             row["payload_hash"], row["provider_message_id"]],
        )
        existing = self.cursor.fetchone()
        if existing is not None:
            stored = {
                "callback_receipt_id": existing[0], "payload_hash": existing[1],
                "provider_request_id": existing[2], "outcome": existing[3],
                "processing_status": existing[4], "project_id": existing[5],
                "external_effect_id": existing[6], "dispatch_id": existing[7],
            }
            same = (
                stored["payload_hash"] == row["payload_hash"]
                and stored["provider_request_id"] == row["provider_request_id"]
                and stored["outcome"] == row["outcome"]
            )
            return ("REPLAY" if same else "CONFLICT"), stored
        self.cursor.execute(
            """
            INSERT INTO authority_provider_callback_receipt (
                callback_receipt_id, project_id, provider, provider_request_id,
                provider_message_id, external_effect_id, dispatch_id, payload_hash,
                signature_status, outcome, raw_metadata, normalized_receipt,
                processing_status, trace_id, correlation_id
            ) VALUES (
                %(callback_receipt_id)s, %(project_id)s, %(provider)s,
                %(provider_request_id)s, %(provider_message_id)s,
                %(external_effect_id)s, %(dispatch_id)s, %(payload_hash)s,
                %(signature_status)s, %(outcome)s, %(raw_metadata)s,
                %(normalized_receipt)s, %(processing_status)s, %(trace_id)s,
                %(correlation_id)s
            )
            """,
            {
                **row,
                "raw_metadata": Jsonb(row["raw_metadata"]),
                "normalized_receipt": Jsonb(row["normalized_receipt"]),
            },
        )
        return "INSERTED", dict(row)

    def begin_attempt(
        self, callback_receipt_id: str, project_id: str, worker_id: str, attempt_id: str
    ) -> int:
        self.cursor.execute(
            """
            UPDATE authority_provider_callback_receipt
            SET attempt_count=attempt_count+1, processing_status='PROCESSING', updated_at=NOW()
            WHERE callback_receipt_id=%s AND project_id=%s
              AND processing_status IN ('PENDING','PROCESSING','FAILED_RETRYABLE')
            RETURNING attempt_count
            """,
            [callback_receipt_id, project_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError("CALLBACK_RECEIPT_NOT_FOUND", "callback receipt is not project-bound")
        attempt_number = int(row[0])
        self.cursor.execute(
            """
            INSERT INTO authority_provider_callback_attempt (
                callback_attempt_id, callback_receipt_id, project_id,
                attempt_number, status, worker_id
            ) VALUES (%s,%s,%s,%s,'RUNNING',%s)
            """,
            [attempt_id, callback_receipt_id, project_id, attempt_number, worker_id],
        )
        return attempt_number

    def finish_attempt(
        self,
        callback_receipt_id: str,
        project_id: str,
        attempt_id: str,
        *,
        status: str,
        error_code: str = "",
        error_detail: str = "",
    ) -> None:
        attempt_status = "SUCCEEDED" if status == "PROCESSED" else status
        self.cursor.execute(
            """
            UPDATE authority_provider_callback_attempt
            SET status=%s, error_code=%s, error_detail=%s, finished_at=NOW()
            WHERE callback_attempt_id=%s AND project_id=%s AND status='RUNNING'
            """,
            [attempt_status, error_code, error_detail, attempt_id, project_id],
        )
        self.cursor.execute(
            """
            UPDATE authority_provider_callback_receipt
            SET processing_status=%s, processed_at=CASE WHEN %s='PROCESSED' THEN NOW() ELSE processed_at END,
                last_error=%s, updated_at=NOW()
            WHERE callback_receipt_id=%s AND project_id=%s
              AND processing_status='PROCESSING'
              AND attempt_count=(SELECT attempt_number FROM authority_provider_callback_attempt
                  WHERE callback_attempt_id=%s AND project_id=%s)
            """,
            [status, status, error_detail, callback_receipt_id, project_id, attempt_id, project_id],
        )


__all__ = ["ProviderCallbackRepository"]

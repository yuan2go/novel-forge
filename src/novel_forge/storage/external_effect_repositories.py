"""PostgreSQL repository for generic ExternalEffect dispatch and reconciliation."""
from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.errors import KernelError


class ExternalEffectRepository:
    def __init__(self, cursor: Any) -> None:
        self.cursor = cursor

    def require_operation(self, operation_id: str, project_id: str) -> None:
        self.cursor.execute(
            """
            SELECT status FROM authority_operation
            WHERE operation_id = %s AND project_id = %s
            FOR UPDATE
            """,
            [operation_id, project_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError("OPERATION_NOT_FOUND", "effect operation does not exist")
        if row[0] != "EXECUTING":
            raise KernelError("OPERATION_STATUS_CONFLICT", "effect operation is not EXECUTING")

    def plan(self, row: dict[str, Any]) -> dict[str, Any]:
        self.cursor.execute(
            """
            INSERT INTO authority_external_effect (
                external_effect_id, operation_id, effect_type, stable_idempotency_key,
                status, request_hash, request_payload, provider, capability,
                max_attempts, reversible
            )
            VALUES (
                %(external_effect_id)s, %(operation_id)s, %(effect_type)s,
                %(stable_idempotency_key)s, 'READY', %(request_hash)s,
                %(request_payload)s, %(provider)s, %(capability)s,
                %(max_attempts)s, %(reversible)s
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
                "stable effect key belongs to another request payload",
            )
        return {"external_effect_id": existing[0], "replayed": True}

    def get_for_update(self, effect_id: str) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT effect.external_effect_id, effect.operation_id, operation.project_id,
                   effect.effect_type, effect.status, effect.stable_idempotency_key,
                   effect.request_hash, effect.request_payload, effect.provider,
                   effect.capability, effect.max_attempts, effect.reversible
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
            "stable_idempotency_key",
            "request_hash",
            "request_payload",
            "provider",
            "capability",
            "max_attempts",
            "reversible",
        )
        return dict(zip(fields, row, strict=True))

    def prepare_dispatch(self, effect: dict[str, Any], dispatch_id: str) -> dict[str, Any]:
        if effect["status"] in {"UNKNOWN", "RECONCILIATION_REQUIRED"}:
            raise KernelError(
                "EFFECT_RECONCILIATION_REQUIRED",
                "unknown external outcome must be reconciled before retry",
            )
        if effect["status"] not in {"READY", "FAILED_RETRYABLE"}:
            raise KernelError("EFFECT_STATUS_CONFLICT", "effect is not dispatchable")
        self.cursor.execute(
            """
            SELECT dispatch_id, generation, status
            FROM authority_external_effect_dispatch
            WHERE external_effect_id = %s
            ORDER BY generation DESC
            LIMIT 1
            FOR UPDATE
            """,
            [effect["external_effect_id"]],
        )
        latest = self.cursor.fetchone()
        if latest and latest[2] in {"CREATED", "LEASED", "DISPATCHING"}:
            return {"dispatch_id": latest[0], "generation": latest[1], "replayed": True}
        generation = int(latest[1]) + 1 if latest else 1
        if generation > effect["max_attempts"]:
            raise KernelError("EFFECT_RETRY_EXHAUSTED", "effect retry policy is exhausted")
        self.cursor.execute(
            """
            INSERT INTO authority_external_effect_dispatch (
                dispatch_id, external_effect_id, generation, status,
                provider, payload_hash, evidence
            )
            VALUES (%s, %s, %s, 'CREATED', %s, %s, '{}'::jsonb)
            """,
            [
                dispatch_id,
                effect["external_effect_id"],
                generation,
                effect["provider"],
                effect["request_hash"],
            ],
        )
        self.cursor.execute(
            "UPDATE authority_external_effect SET status = 'READY' WHERE external_effect_id = %s",
            [effect["external_effect_id"]],
        )
        return {"dispatch_id": dispatch_id, "generation": generation, "replayed": False}

    def dispatch_for_update(self, dispatch_id: str) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT dispatch.dispatch_id, dispatch.external_effect_id,
                   dispatch.generation, dispatch.status, dispatch.provider,
                   effect.status, effect.max_attempts, operation.project_id
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
            raise KernelError("EFFECT_DISPATCH_NOT_FOUND", "effect dispatch does not exist")
        fields = (
            "dispatch_id",
            "external_effect_id",
            "generation",
            "status",
            "provider",
            "effect_status",
            "max_attempts",
            "project_id",
        )
        return dict(zip(fields, row, strict=True))

    def acquire_lease(
        self,
        lease_id: str,
        dispatch_id: str,
        worker_id: str,
        lease_seconds: int,
    ) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT lease_id, fencing_token, acquired_at, expires_at
            FROM authority_acquire_effect_dispatch_lease(%s, %s, %s, %s)
            """,
            [lease_id, dispatch_id, worker_id, lease_seconds],
        )
        row = self.cursor.fetchone()
        return {
            "lease_id": row[0],
            "fencing_token": row[1],
            "acquired_at": row[2],
            "expires_at": row[3],
        }

    def current_fence(
        self,
        dispatch_id: str,
        worker_id: str,
        fencing_token: int,
    ) -> tuple[bool, int | None]:
        self.cursor.execute(
            """
            UPDATE authority_effect_dispatch_lease
            SET status = 'EXPIRED', released_at = NOW(), release_reason = 'lease_expired'
            WHERE dispatch_id = %s AND status = 'HELD' AND expires_at <= NOW()
            """,
            [dispatch_id],
        )
        self.cursor.execute(
            """
            SELECT COALESCE(MAX(fencing_token), 0),
                   BOOL_OR(
                       status = 'HELD' AND owner = %s AND fencing_token = %s
                       AND expires_at > NOW()
                   )
            FROM authority_effect_dispatch_lease
            WHERE dispatch_id = %s
            """,
            [worker_id, fencing_token, dispatch_id],
        )
        row = self.cursor.fetchone()
        return bool(row[1]), int(row[0]) if row[0] else None

    def heartbeat_lease(
        self,
        dispatch_id: str,
        worker_id: str,
        fencing_token: int,
        lease_seconds: int,
    ) -> Any:
        self.cursor.execute(
            """
            UPDATE authority_effect_dispatch_lease
            SET heartbeat_at = NOW(),
                expires_at = NOW() + make_interval(secs => %s)
            WHERE dispatch_id = %s
              AND owner = %s
              AND fencing_token = %s
              AND status = 'HELD'
              AND expires_at > NOW()
            RETURNING expires_at
            """,
            [lease_seconds, dispatch_id, worker_id, fencing_token],
        )
        row = self.cursor.fetchone()
        return row[0] if row else None

    def reject_stale(self, row: dict[str, Any]) -> None:
        self.cursor.execute(
            """
            INSERT INTO authority_effect_command_rejection (
                rejection_id, external_effect_id, dispatch_id, worker_id,
                presented_fencing_token, current_fencing_token, command_type,
                payload, trace_id, correlation_id
            )
            VALUES (
                %(rejection_id)s, %(external_effect_id)s, %(dispatch_id)s,
                %(worker_id)s, %(presented_fencing_token)s,
                %(current_fencing_token)s, %(command_type)s,
                %(payload)s, %(trace_id)s, %(correlation_id)s
            )
            """,
            {**row, "payload": Jsonb(row["payload"])},
        )

    def submit_result(
        self,
        dispatch: dict[str, Any],
        outcome: str,
        evidence: dict[str, Any],
        provider_correlation_id: str,
    ) -> str:
        if outcome == "retryable_failure" and dispatch["generation"] >= dispatch["max_attempts"]:
            accepted_outcome = "final_failure"
            dispatch_status = "DEAD_LETTER"
            effect_status = "FAILED_FINAL"
        else:
            accepted_outcome = outcome
            dispatch_status, effect_status = {
                "success": ("SUCCEEDED", "SUCCEEDED"),
                "retryable_failure": ("FAILED_RETRYABLE", "FAILED_RETRYABLE"),
                "final_failure": ("FAILED_FINAL", "FAILED_FINAL"),
                "unknown": ("UNKNOWN", "UNKNOWN"),
            }[outcome]
        self.cursor.execute(
            """
            UPDATE authority_external_effect_dispatch
            SET status = %s,
                provider_correlation_id = %s,
                evidence = evidence || %s,
                updated_at = NOW(),
                finished_at = NOW()
            WHERE dispatch_id = %s AND status = 'DISPATCHING'
            """,
            [dispatch_status, provider_correlation_id, Jsonb(evidence), dispatch["dispatch_id"]],
        )
        if self.cursor.rowcount != 1:
            raise KernelError("EFFECT_DISPATCH_CONFLICT", "dispatch no longer accepts results")
        self.cursor.execute(
            """
            UPDATE authority_external_effect
            SET status = %s, last_error = %s
            WHERE external_effect_id = %s
              AND status IN ('READY', 'DISPATCHING', 'DISPATCHED', 'FAILED_RETRYABLE')
            """,
            [
                effect_status,
                Jsonb({} if accepted_outcome == "success" else evidence),
                dispatch["external_effect_id"],
            ],
        )
        if self.cursor.rowcount != 1:
            raise KernelError("EFFECT_STATUS_CONFLICT", "effect no longer accepts results")
        return accepted_outcome

    def release_lease(
        self,
        dispatch_id: str,
        worker_id: str,
        fencing_token: int,
        reason: str,
    ) -> None:
        self.cursor.execute(
            """
            UPDATE authority_effect_dispatch_lease
            SET status = 'RELEASED', released_at = NOW(), release_reason = %s
            WHERE dispatch_id = %s AND owner = %s AND fencing_token = %s AND status = 'HELD'
            """,
            [reason, dispatch_id, worker_id, fencing_token],
        )

    def record_inbox(
        self,
        consumer: str,
        message_id: str,
        payload_hash: str,
        outcome: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        self.cursor.execute(
            "SELECT disposition, stored_outcome FROM authority_record_inbox_message(%s, %s, %s, %s)",
            [consumer, message_id, payload_hash, Jsonb(outcome)],
        )
        row = self.cursor.fetchone()
        return row[0], row[1]

    def accept_receipt(self, row: dict[str, Any]) -> None:
        self.cursor.execute(
            """
            INSERT INTO authority_external_receipt (
                provider, receipt_id, dispatch_id, payload_hash, payload
            )
            VALUES (%(provider)s, %(receipt_id)s, %(dispatch_id)s, %(payload_hash)s, %(payload)s)
            """,
            {**row, "payload": Jsonb(row["payload"])},
        )
        target_dispatch, target_effect = {
            "success": ("SUCCEEDED", "SUCCEEDED"),
            "retryable_failure": ("FAILED_RETRYABLE", "FAILED_RETRYABLE"),
            "final_failure": ("FAILED_FINAL", "FAILED_FINAL"),
            "cancelled": ("CANCELLED", "CANCELLED"),
            "compensated": ("SUCCEEDED", "COMPENSATED"),
        }[row["outcome"]]
        self.cursor.execute(
            """
            UPDATE authority_external_effect_dispatch
            SET status = %s, receipt_id = %s,
                provider_correlation_id = %s, evidence = evidence || %s,
                updated_at = NOW(), finished_at = NOW()
            WHERE dispatch_id = %s
              AND generation = %s
              AND status IN ('CREATED', 'DISPATCHING', 'SENT', 'UNKNOWN', 'TIMED_OUT')
            """,
            [
                target_dispatch,
                row["receipt_id"],
                row["provider_correlation_id"],
                Jsonb(row["evidence"]),
                row["dispatch_id"],
                row["generation"],
            ],
        )
        if self.cursor.rowcount != 1:
            raise KernelError("EFFECT_DISPATCH_CONFLICT", "receipt generation is stale")
        self.cursor.execute(
            """
            UPDATE authority_external_effect
            SET status = %s
            WHERE external_effect_id = %s
              AND status NOT IN ('SUCCEEDED', 'FAILED_FINAL', 'CANCELLED', 'COMPENSATED')
            """,
            [target_effect, row["external_effect_id"]],
        )
        if self.cursor.rowcount != 1:
            raise KernelError("EFFECT_STATUS_CONFLICT", "receipt cannot change terminal effect")

    def record_reconciliation(self, row: dict[str, Any]) -> None:
        self.cursor.execute(
            """
            INSERT INTO authority_effect_reconciliation_evidence (
                reconciliation_id, external_effect_id, provider,
                stable_idempotency_key, outcome, evidence, trace_id, correlation_id
            )
            VALUES (
                %(reconciliation_id)s, %(external_effect_id)s, %(provider)s,
                %(stable_idempotency_key)s, %(outcome)s, %(evidence)s,
                %(trace_id)s, %(correlation_id)s
            )
            """,
            {**row, "evidence": Jsonb(row["evidence"])},
        )
        target = {
            "success": "SUCCEEDED",
            "not_found": "FAILED_RETRYABLE",
            "ambiguous": "RECONCILIATION_REQUIRED",
            "failed_final": "FAILED_FINAL",
        }[row["outcome"]]
        self.cursor.execute(
            """
            UPDATE authority_external_effect
            SET status = %s, reconciliation = %s
            WHERE external_effect_id = %s
              AND status IN ('UNKNOWN', 'RECONCILIATION_REQUIRED')
            """,
            [target, Jsonb(row["evidence"]), row["external_effect_id"]],
        )
        if self.cursor.rowcount != 1:
            raise KernelError("EFFECT_STATUS_CONFLICT", "effect is not reconcilable")

    def cancel(self, effect: dict[str, Any]) -> str:
        self.cursor.execute(
            """
            SELECT status FROM authority_external_effect_dispatch
            WHERE external_effect_id = %s
            ORDER BY generation DESC LIMIT 1
            FOR UPDATE
            """,
            [effect["external_effect_id"]],
        )
        dispatch = self.cursor.fetchone()
        if dispatch is None or dispatch[0] == "CREATED":
            target = "CANCELLED"
        elif effect["reversible"]:
            target = "COMPENSATION_REQUIRED"
        else:
            target = "RECONCILIATION_REQUIRED"
        self.cursor.execute(
            "UPDATE authority_external_effect SET status = %s WHERE external_effect_id = %s",
            [target, effect["external_effect_id"]],
        )
        if target == "CANCELLED" and dispatch is not None:
            self.cursor.execute(
                """
                UPDATE authority_external_effect_dispatch
                SET status = 'CANCELLED', updated_at = NOW(), finished_at = NOW()
                WHERE external_effect_id = %s AND status = 'CREATED'
                """,
                [effect["external_effect_id"]],
            )
        return target

    def record_event(self, row: dict[str, Any]) -> None:
        self.cursor.execute(
            """
            SELECT COALESCE(MAX(sequence_number), 0) + 1 FROM state_event
            WHERE aggregate_type = %(aggregate_type)s AND aggregate_id = %(aggregate_id)s
            """,
            row,
        )
        sequence = self.cursor.fetchone()[0]
        params = {**row, "sequence_number": sequence, "payload": Jsonb(row["payload"])}
        self.cursor.execute(
            """
            INSERT INTO state_event (
                event_id, aggregate_type, aggregate_id, project_id, event_type,
                event_version, sequence_number, correlation_id, causation_id, payload
            ) VALUES (
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
            VALUES (%(outbox_id)s, %(event_id)s, %(project_id)s, %(event_type)s, 'PENDING', %(payload)s)
            """,
            params,
        )

"""Focused repositories for PostgreSQL Command Kernel authority."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.errors import KernelError


DEFINITION_HASH_FIELDS = (
    "name",
    "definition_version",
    "family",
    "command_schema",
    "result_schema",
    "handler_key",
    "handler_contract_version",
    "execution_mode",
    "permissions",
    "approval_policy",
    "idempotency_scope",
    "concurrency_key_template",
    "retry_policy",
    "timeout_policy",
    "cancellation_policy",
    "compensation_policy",
    "irreversible_effect_policy",
    "external_capabilities",
    "policy",
    "completion_contract",
)


class IdempotencyConflictError(KernelError):
    def __init__(self, message: str) -> None:
        super().__init__("IDEMPOTENCY_CONFLICT", message)


def definition_hash(row: dict[str, Any]) -> str:
    semantic_definition = {field: row[field] for field in DEFINITION_HASH_FIELDS}
    encoded = json.dumps(
        semantic_definition,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


class OperationDefinitionRepository:
    def __init__(self, cursor: Any) -> None:
        self.cursor = cursor

    def get(self, name: str, version: str) -> dict[str, Any] | None:
        self.cursor.execute(
            """
            SELECT
                name,
                definition_version,
                family,
                enabled,
                definition_hash,
                command_schema,
                result_schema,
                handler_key,
                handler_contract_version,
                application_build_id,
                commit_sha,
                execution_mode,
                permissions,
                approval_policy,
                idempotency_scope,
                concurrency_key_template,
                retry_policy,
                timeout_policy,
                cancellation_policy,
                compensation_policy,
                irreversible_effect_policy,
                external_capabilities,
                policy,
                completion_contract
            FROM authority_operation_definition
            WHERE name = %s AND definition_version = %s
            """,
            [name, version],
        )
        row = self.cursor.fetchone()
        if row is None:
            return None
        fields = (
            "name",
            "definition_version",
            "family",
            "enabled",
            "definition_hash",
            "command_schema",
            "result_schema",
            "handler_key",
            "handler_contract_version",
            "application_build_id",
            "commit_sha",
            "execution_mode",
            "permissions",
            "approval_policy",
            "idempotency_scope",
            "concurrency_key_template",
            "retry_policy",
            "timeout_policy",
            "cancellation_policy",
            "compensation_policy",
            "irreversible_effect_policy",
            "external_capabilities",
            "policy",
            "completion_contract",
        )
        return dict(zip(fields, row, strict=True))

    def get_release(
        self,
        name: str,
        version: str,
        *,
        application_build_id: str,
        commit_sha: str,
    ) -> dict[str, Any] | None:
        definition = self.get(name, version)
        if definition is None:
            return None
        self.cursor.execute(
            """
            SELECT definition_hash
            FROM authority_operation_definition_release
            WHERE name=%s AND definition_version=%s
              AND application_build_id=%s AND commit_sha=%s
            """,
            [name, version, application_build_id, commit_sha],
        )
        release = self.cursor.fetchone()
        if release is None:
            return None
        if str(release[0]) != str(definition["definition_hash"]):
            raise KernelError(
                "OPERATION_DEFINITION_RELEASE_INTEGRITY_ERROR",
                "release binding differs from its semantic OperationDefinition",
            )
        return {
            **definition,
            "application_build_id": application_build_id,
            "commit_sha": commit_sha,
        }

    def register(self, row: dict[str, Any]) -> dict[str, Any]:
        digest = definition_hash(row)
        parameters = {
            **row,
            "definition_hash": digest,
            **{
                field: Jsonb(row[field])
                for field in (
                    "command_schema",
                    "result_schema",
                    "permissions",
                    "approval_policy",
                    "retry_policy",
                    "timeout_policy",
                    "cancellation_policy",
                    "compensation_policy",
                    "irreversible_effect_policy",
                    "external_capabilities",
                    "policy",
                    "completion_contract",
                )
            },
        }
        self.cursor.execute(
            """
            INSERT INTO authority_operation_definition (
                name,
                definition_version,
                family,
                enabled,
                definition_hash,
                command_schema,
                result_schema,
                handler_key,
                handler_contract_version,
                application_build_id,
                commit_sha,
                execution_mode,
                permissions,
                approval_policy,
                idempotency_scope,
                concurrency_key_template,
                retry_policy,
                timeout_policy,
                cancellation_policy,
                compensation_policy,
                irreversible_effect_policy,
                external_capabilities,
                policy,
                completion_contract
            )
            VALUES (
                %(name)s,
                %(definition_version)s,
                %(family)s,
                %(enabled)s,
                %(definition_hash)s,
                %(command_schema)s,
                %(result_schema)s,
                %(handler_key)s,
                %(handler_contract_version)s,
                %(application_build_id)s,
                %(commit_sha)s,
                %(execution_mode)s,
                %(permissions)s,
                %(approval_policy)s,
                %(idempotency_scope)s,
                %(concurrency_key_template)s,
                %(retry_policy)s,
                %(timeout_policy)s,
                %(cancellation_policy)s,
                %(compensation_policy)s,
                %(irreversible_effect_policy)s,
                %(external_capabilities)s,
                %(policy)s,
                %(completion_contract)s
            )
            ON CONFLICT (name, definition_version) DO NOTHING
            RETURNING definition_hash
            """,
            parameters,
        )
        inserted = self.cursor.fetchone()
        registered = inserted is not None
        if not registered:
            existing = self.get(row["name"], row["definition_version"])
            if existing is None or existing["definition_hash"] != digest:
                raise KernelError(
                    "OPERATION_DEFINITION_VERSION_CONFLICT",
                    "operation definition name/version is already bound to different content",
                )
        self.cursor.execute(
            """
            INSERT INTO authority_operation_definition_release(
              name, definition_version, application_build_id, commit_sha,
              definition_hash
            ) VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT DO NOTHING
            """,
            [
                row["name"],
                row["definition_version"],
                row["application_build_id"],
                row["commit_sha"],
                digest,
            ],
        )
        return {"registered": registered, "definition_hash": digest}


class OperationRepository:
    def __init__(self, cursor: Any) -> None:
        self.cursor = cursor

    def get_idempotency(self, scope: str, key: str) -> tuple[str, str] | None:
        self.cursor.execute(
            """
            SELECT operation_id, request_digest
            FROM authority_operation
            WHERE idempotency_scope = %s AND idempotency_key = %s
            """,
            [scope, key],
        )
        return self.cursor.fetchone()

    def try_create(self, row: dict[str, Any]) -> bool:
        self.cursor.execute(
            """
            INSERT INTO authority_operation (
                operation_id,
                definition_name,
                definition_version,
                project_id,
                status,
                parent_operation_id,
                root_operation_id,
                causation_operation_id,
                idempotency_scope,
                idempotency_key,
                request_digest,
                definition_snapshot,
                completion_contract_snapshot,
                policy_snapshot,
                actor_id,
                workspace_id,
                concurrency_key,
                trace_id,
                span_id,
                correlation_id,
                causation_id,
                command_payload,
                approval_requirement_snapshot,
                input_asset_snapshot,
                metadata,
                business_deadline_at
            )
            VALUES (
                %(operation_id)s,
                %(definition_name)s,
                %(definition_version)s,
                %(project_id)s,
                'ADMITTED',
                %(parent_operation_id)s,
                %(root_operation_id)s,
                %(causation_operation_id)s,
                %(idempotency_scope)s,
                %(idempotency_key)s,
                %(request_digest)s,
                %(definition_snapshot)s,
                %(completion_contract_snapshot)s,
                %(policy_snapshot)s,
                %(actor_id)s,
                %(workspace_id)s,
                %(concurrency_key)s,
                %(trace_id)s,
                %(span_id)s,
                %(correlation_id)s,
                %(causation_id)s,
                %(command_payload)s,
                %(approval_requirement_snapshot)s,
                %(input_asset_snapshot)s,
                %(metadata)s,
                NOW() + make_interval(secs => GREATEST(
                    1,
                    COALESCE(
                        (%(definition_snapshot)s->'timeout_policy'->>'operation_timeout_seconds')::int,
                        300
                    )
                ))
            )
            ON CONFLICT (idempotency_scope, idempotency_key) DO NOTHING
            RETURNING operation_id
            """,
            {
                **row,
                "definition_snapshot": Jsonb(row["definition_snapshot"]),
                "completion_contract_snapshot": Jsonb(
                    row["completion_contract_snapshot"]
                ),
                "policy_snapshot": Jsonb(row["policy_snapshot"]),
                "command_payload": Jsonb(row["command_payload"]),
                "approval_requirement_snapshot": Jsonb(
                    row["approval_requirement_snapshot"]
                ),
                "input_asset_snapshot": Jsonb(row["input_asset_snapshot"]),
                "metadata": Jsonb(row.get("metadata", {})),
            },
        )
        return self.cursor.fetchone() is not None

    def transaction_result(self, operation_id: str, project_id: str) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT status, COALESCE(metadata->'transaction_result', '{}'::jsonb)
            FROM authority_operation
            WHERE operation_id = %s AND project_id = %s
            """,
            [operation_id, project_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "OPERATION_NOT_FOUND",
                "transaction command Operation does not exist in the requested project",
            )
        return {"status": row[0], "result": dict(row[1] or {})}


class AdmissionEvidenceRepository:
    def __init__(self, cursor: Any) -> None:
        self.cursor = cursor

    def record(self, row: dict[str, Any]) -> None:
        self.cursor.execute(
            """
            INSERT INTO authority_idempotency_record (
                idempotency_scope,
                idempotency_key,
                request_digest,
                operation_id
            )
            VALUES (
                %(idempotency_scope)s,
                %(idempotency_key)s,
                %(request_digest)s,
                %(operation_id)s
            )
            """,
            row,
        )
        self.cursor.execute(
            """
            INSERT INTO state_event (
                event_id,
                aggregate_type,
                aggregate_id,
                project_id,
                event_type,
                event_version,
                sequence_number,
                correlation_id,
                causation_id,
                payload
            )
            VALUES (
                %(event_id)s,
                'authority_operation',
                %(operation_id)s,
                %(project_id)s,
                'authority.operation.admitted',
                1,
                1,
                %(correlation_id)s,
                %(causation_id)s,
                %(event_payload)s
            )
            """,
            {**row, "event_payload": Jsonb(row["event_payload"])},
        )
        self.cursor.execute(
            """
            INSERT INTO audit_log (
                audit_id,
                project_id,
                operation_id,
                action,
                payload
            )
            VALUES (
                %(audit_id)s,
                %(project_id)s,
                %(operation_id)s,
                'authority.operation.admitted',
                %(audit_payload)s
            )
            """,
            {**row, "audit_payload": Jsonb(row["audit_payload"])},
        )
        self.cursor.execute(
            """
            INSERT INTO outbox_event (
                outbox_id,
                event_id,
                project_id,
                topic,
                status,
                payload
            )
            VALUES (
                %(outbox_id)s,
                %(event_id)s,
                %(project_id)s,
                'authority.operation.admitted',
                'PENDING',
                %(outbox_payload)s
            )
            """,
            {**row, "outbox_payload": Jsonb(row["outbox_payload"])},
        )


class OperationLifecycleRepository:
    def __init__(self, cursor: Any) -> None:
        self.cursor = cursor

    def compare_and_set(self, row: dict[str, Any]) -> dict[str, Any]:
        self.cursor.execute(
            """
            UPDATE authority_operation
            SET status = %(target_status)s,
                version = version + 1,
                updated_at = NOW()
            WHERE operation_id = %(operation_id)s
              AND project_id = %(project_id)s
              AND version = %(expected_version)s
              AND status = %(expected_status)s
            RETURNING status, version
            """,
            row,
        )
        updated = self.cursor.fetchone()
        if updated is not None:
            return {"status": updated[0], "version": updated[1]}

        self.cursor.execute(
            """
            SELECT status, version
            FROM authority_operation
            WHERE operation_id = %s AND project_id = %s
            """,
            [row["operation_id"], row["project_id"]],
        )
        current = self.cursor.fetchone()
        if current is None:
            raise KernelError(
                "OPERATION_NOT_FOUND",
                "operation does not exist in the requested project",
            )
        if current[1] != row["expected_version"]:
            raise KernelError(
                "OPERATION_VERSION_CONFLICT",
                f"expected version {row['expected_version']}, current version {current[1]}",
            )
        raise KernelError(
            "OPERATION_STATUS_CONFLICT",
            f"expected status {row['expected_status']}, current status {current[0]}",
        )

    def complete_transaction_command(self, row: dict[str, Any]) -> dict[str, Any]:
        self.cursor.execute(
            """
            UPDATE authority_operation
            SET status = 'SUCCEEDED',
                version = version + 1,
                metadata = jsonb_set(
                    jsonb_set(metadata, '{transaction_result}', %s, TRUE),
                    '{execution_classification}',
                    '"transaction_command"'::jsonb,
                    TRUE
                ),
                updated_at = NOW()
            WHERE operation_id = %s
              AND project_id = %s
              AND version = %s
              AND status = 'ADMITTED'
              AND definition_snapshot->>'execution_mode' = 'transactional'
              AND policy_snapshot->>'execution_classification' = 'transaction_command'
            RETURNING status, version
            """,
            [
                Jsonb(row["result"]),
                row["operation_id"],
                row["project_id"],
                row["expected_version"],
            ],
        )
        completed = self.cursor.fetchone()
        if completed is None:
            raise KernelError(
                "EXECUTION_CLASSIFICATION_CONFLICT",
                "Operation is not an admitted transaction command at the expected version",
            )
        return {"status": completed[0], "version": int(completed[1])}


class AttemptRuntimeRepository:
    def __init__(self, cursor: Any) -> None:
        self.cursor = cursor

    def operation_state(self, operation_id: str, project_id: str) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT status, version
            FROM authority_operation
            WHERE operation_id = %s AND project_id = %s
            FOR UPDATE
            """,
            [operation_id, project_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError("OPERATION_NOT_FOUND", "operation does not exist")
        return {"status": row[0], "version": row[1]}

    def next_attempt_number(self, operation_id: str) -> int:
        self.cursor.execute(
            "SELECT COALESCE(MAX(attempt_number), 0) + 1 FROM authority_attempt WHERE operation_id = %s",
            [operation_id],
        )
        return int(self.cursor.fetchone()[0])

    def create(self, row: dict[str, Any]) -> None:
        self.cursor.execute(
            """
            INSERT INTO authority_attempt (
                attempt_id,
                operation_id,
                attempt_number,
                max_attempts,
                status
                , business_deadline_at
            )
            VALUES (
                %(attempt_id)s,
                %(operation_id)s,
                %(attempt_number)s,
                %(max_attempts)s,
                'CREATED',
                (SELECT business_deadline_at FROM authority_operation WHERE operation_id = %(operation_id)s)
            )
            """,
            row,
        )

    def get_for_update(self, attempt_id: str, project_id: str) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT operation.operation_id
            FROM authority_operation AS operation
            JOIN authority_attempt AS attempt
              ON attempt.operation_id = operation.operation_id
            WHERE attempt.attempt_id = %s AND operation.project_id = %s
            FOR UPDATE OF operation
            """,
            [attempt_id, project_id],
        )
        if self.cursor.fetchone() is None:
            raise KernelError(
                "ATTEMPT_NOT_FOUND",
                "attempt does not exist in the requested project",
            )
        self.cursor.execute(
            """
            SELECT
                attempt.attempt_id,
                attempt.operation_id,
                attempt.status,
                attempt.attempt_number,
                attempt.max_attempts,
                operation.project_id,
                operation.status,
                operation.version
            FROM authority_attempt AS attempt
            JOIN authority_operation AS operation
              ON operation.operation_id = attempt.operation_id
            WHERE attempt.attempt_id = %s AND operation.project_id = %s
            FOR UPDATE OF attempt
            """,
            [attempt_id, project_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError("ATTEMPT_NOT_FOUND", "attempt disappeared while locked")
        fields = (
            "attempt_id",
            "operation_id",
            "status",
            "attempt_number",
            "max_attempts",
            "project_id",
            "operation_status",
            "operation_version",
        )
        return dict(zip(fields, row, strict=True))

    def submitted_for_operation(
        self,
        operation_id: str,
        project_id: str,
    ) -> dict[str, Any] | None:
        self.cursor.execute(
            """
            SELECT attempt.attempt_id, attempt.operation_id, attempt.status,
                   attempt.worker_id, operation.project_id
            FROM authority_attempt AS attempt
            JOIN authority_operation AS operation
              ON operation.operation_id = attempt.operation_id
            WHERE attempt.operation_id = %s
              AND operation.project_id = %s
              AND attempt.status = 'RESULT_SUBMITTED'
            ORDER BY attempt.attempt_number DESC
            LIMIT 1
            FOR UPDATE OF attempt
            """,
            [operation_id, project_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            return None
        fields = ("attempt_id", "operation_id", "status", "worker_id", "project_id")
        return dict(zip(fields, row, strict=True))

    def transition(
        self,
        attempt_id: str,
        expected_status: str,
        target_status: str,
        *,
        worker_id: str = "",
        checkpoint: dict[str, Any] | None = None,
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> None:
        self.cursor.execute(
            """
            UPDATE authority_attempt
            SET status = %s,
                worker_id = CASE WHEN %s = '' THEN worker_id ELSE %s END,
                queued_at = CASE WHEN %s = 'QUEUED' THEN NOW() ELSE queued_at END,
                started_at = CASE WHEN %s = 'RUNNING' AND started_at IS NULL THEN NOW() ELSE started_at END,
                checkpoint = CASE WHEN %s THEN %s ELSE checkpoint END,
                checkpointed_at = CASE WHEN %s = 'CHECKPOINTED' THEN NOW() ELSE checkpointed_at END,
                result_submitted_at = CASE WHEN %s = 'RESULT_SUBMITTED' THEN NOW() ELSE result_submitted_at END,
                finished_at = CASE WHEN %s IN ('SUCCEEDED', 'FAILED_RETRYABLE', 'FAILED_FINAL', 'TIMED_OUT', 'LEASE_LOST', 'SUPERSEDED', 'LATE_RESULT_REJECTED', 'CANCELLED') THEN NOW() ELSE finished_at END,
                result = CASE WHEN %s THEN %s ELSE result END,
                error = CASE WHEN %s THEN %s ELSE error END
            WHERE attempt_id = %s AND status = %s
            """,
            [
                target_status,
                worker_id,
                worker_id,
                target_status,
                target_status,
                checkpoint is not None,
                Jsonb(checkpoint or {}),
                target_status,
                target_status,
                target_status,
                result is not None,
                Jsonb(result or {}),
                error is not None,
                Jsonb(error or {}),
                attempt_id,
                expected_status,
            ],
        )
        if self.cursor.rowcount != 1:
            raise KernelError(
                "ATTEMPT_STATUS_CONFLICT",
                f"attempt is no longer {expected_status}",
            )

    def acquire_lease(
        self,
        lease_id: str,
        attempt_id: str,
        worker_id: str,
        lease_seconds: int,
    ) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT lease_id, fencing_token, acquired_at, expires_at
            FROM authority_acquire_attempt_lease(%s, %s, %s, %s)
            """,
            [lease_id, attempt_id, worker_id, lease_seconds],
        )
        row = self.cursor.fetchone()
        return {
            "lease_id": row[0],
            "fencing_token": row[1],
            "acquired_at": row[2],
            "expires_at": row[3],
        }

    def assign_worker(self, attempt_id: str, expected_status: str, worker_id: str) -> None:
        self.cursor.execute(
            """
            UPDATE authority_attempt
            SET worker_id = %s
            WHERE attempt_id = %s AND status = %s
            """,
            [worker_id, attempt_id, expected_status],
        )
        if self.cursor.rowcount != 1:
            raise KernelError(
                "ATTEMPT_STATUS_CONFLICT",
                f"attempt is no longer {expected_status}",
            )

    def current_lease(self, attempt_id: str) -> dict[str, Any] | None:
        self.cursor.execute(
            """
            SELECT lease_id, owner, fencing_token
            FROM authority_lease_acquisition
            WHERE attempt_id = %s AND status = 'HELD' AND expires_at > NOW()
            """,
            [attempt_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            return None
        return {"lease_id": row[0], "worker_id": row[1], "fencing_token": row[2]}

    def current_fence(
        self,
        attempt_id: str,
        worker_id: str,
        fencing_token: int,
    ) -> tuple[bool, int | None]:
        self.cursor.execute(
            """
            UPDATE authority_lease_acquisition
            SET status = 'EXPIRED',
                released_at = NOW(),
                release_reason = 'lease_expired'
            WHERE attempt_id = %s
              AND status = 'HELD'
              AND expires_at <= NOW()
            """,
            [attempt_id],
        )
        self.cursor.execute(
            """
            SELECT
                COALESCE(MAX(fencing_token), 0),
                BOOL_OR(
                    status = 'HELD'
                    AND owner = %s
                    AND fencing_token = %s
                    AND expires_at > NOW()
                )
            FROM authority_lease_acquisition
            WHERE attempt_id = %s
            """,
            [worker_id, fencing_token, attempt_id],
        )
        row = self.cursor.fetchone()
        return bool(row[1]), int(row[0]) if row[0] else None

    def heartbeat(
        self,
        attempt_id: str,
        worker_id: str,
        fencing_token: int,
        lease_seconds: int,
    ) -> None:
        self.cursor.execute(
            """
            UPDATE authority_lease_acquisition
            SET heartbeat_at = NOW(),
                expires_at = NOW() + make_interval(secs => %s)
            WHERE attempt_id = %s
              AND owner = %s
              AND fencing_token = %s
              AND status = 'HELD'
              AND expires_at > NOW()
            """,
            [lease_seconds, attempt_id, worker_id, fencing_token],
        )
        if self.cursor.rowcount != 1:
            raise KernelError("ATTEMPT_LEASE_LOST", "attempt lease is no longer held")

    def release(self, attempt_id: str, worker_id: str, fencing_token: int, reason: str) -> None:
        self.cursor.execute(
            """
            UPDATE authority_lease_acquisition
            SET status = 'RELEASED',
                released_at = NOW(),
                release_reason = %s
            WHERE attempt_id = %s
              AND owner = %s
              AND fencing_token = %s
              AND status = 'HELD'
            """,
            [reason, attempt_id, worker_id, fencing_token],
        )

    def reject_stale(self, row: dict[str, Any]) -> None:
        self.cursor.execute(
            """
            INSERT INTO authority_late_result_evidence (
                evidence_id,
                attempt_id,
                operation_id,
                project_id,
                command_type,
                worker_id,
                presented_fencing_token,
                current_fencing_token,
                payload,
                authoritative_attempt_status,
                current_worker_id,
                current_lease_id,
                trace_id,
                correlation_id,
                causation_id
            )
            VALUES (
                %(evidence_id)s,
                %(attempt_id)s,
                %(operation_id)s,
                %(project_id)s,
                %(command_type)s,
                %(worker_id)s,
                %(presented_fencing_token)s,
                %(current_fencing_token)s,
                %(payload)s,
                %(authoritative_attempt_status)s,
                %(current_worker_id)s,
                %(current_lease_id)s,
                %(trace_id)s,
                %(correlation_id)s,
                %(causation_id)s
            )
            """,
            {**row, "payload": Jsonb(row["payload"])},
        )

    def assert_lease_consistency(self, attempt_id: str) -> None:
        self.cursor.execute(
            """
            SELECT attempt.status, COUNT(lease.lease_id) FILTER (WHERE lease.status = 'HELD')
            FROM authority_attempt AS attempt
            LEFT JOIN authority_lease_acquisition AS lease
              ON lease.attempt_id = attempt.attempt_id
            WHERE attempt.attempt_id = %s
            GROUP BY attempt.status
            """,
            [attempt_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError("ATTEMPT_NOT_FOUND", "attempt does not exist")
        terminal = {
            "SUCCEEDED",
            "FAILED_RETRYABLE",
            "FAILED_FINAL",
            "TIMED_OUT",
            "LEASE_LOST",
            "SUPERSEDED",
            "LATE_RESULT_REJECTED",
            "CANCELLED",
        }
        if row[0] in terminal and row[1] != 0:
            raise KernelError(
                "ATTEMPT_LEASE_INVARIANT_VIOLATION",
                "terminal attempt cannot retain a held lease",
            )
        if row[1] > 1:
            raise KernelError(
                "ATTEMPT_LEASE_INVARIANT_VIOLATION",
                "attempt cannot have more than one held lease",
            )


class CancellationRepository:
    def __init__(self, cursor: Any) -> None:
        self.cursor = cursor

    def try_record(self, row: dict[str, Any]) -> bool:
        self.cursor.execute(
            """
            INSERT INTO authority_cancellation_command (
                cancel_command_id, operation_id, project_id, command_version,
                actor_id, reason, expected_operation_version, idempotency_key,
                request_digest, trace_id, correlation_id, causation_id
            )
            VALUES (
                %(cancel_command_id)s, %(operation_id)s, %(project_id)s, 1,
                %(actor_id)s, %(reason)s, %(expected_operation_version)s,
                %(idempotency_key)s, %(request_digest)s, %(trace_id)s,
                %(correlation_id)s, %(causation_id)s
            )
            ON CONFLICT (operation_id, idempotency_key) DO NOTHING
            RETURNING cancel_command_id
            """,
            row,
        )
        return self.cursor.fetchone() is not None

    def existing(self, operation_id: str, idempotency_key: str) -> tuple[str, str]:
        self.cursor.execute(
            """
            SELECT cancel_command_id, request_digest
            FROM authority_cancellation_command
            WHERE operation_id = %s AND idempotency_key = %s
            """,
            [operation_id, idempotency_key],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError("CANCEL_COMMAND_NOT_FOUND", "cancel command was not recorded")
        return row

    def active_attempt(self, operation_id: str) -> tuple[str, int | None] | None:
        self.cursor.execute(
            """
            SELECT attempt.attempt_id, lease.fencing_token
            FROM authority_attempt AS attempt
            LEFT JOIN LATERAL (
                SELECT fencing_token
                FROM authority_lease_acquisition
                WHERE attempt_id = attempt.attempt_id AND status = 'HELD'
                ORDER BY fencing_token DESC
                LIMIT 1
            ) AS lease ON TRUE
            WHERE attempt.operation_id = %s
              AND attempt.status IN (
                  'CREATED', 'QUEUED', 'LEASED', 'RUNNING',
                  'CHECKPOINTED', 'RESULT_SUBMITTED'
              )
            FOR UPDATE OF attempt
            """,
            [operation_id],
        )
        return self.cursor.fetchone()

    def signal_worker_cancel(
        self,
        signal_id: str,
        operation_id: str,
        attempt_id: str,
        fencing_token: int | None,
        payload: dict[str, Any],
    ) -> None:
        self.cursor.execute(
            """
            INSERT INTO authority_worker_cancel_signal (
                signal_id, operation_id, attempt_id, fencing_token, status, payload
            )
            VALUES (%s, %s, %s, %s, 'REQUESTED', %s)
            ON CONFLICT (attempt_id) DO NOTHING
            """,
            [signal_id, operation_id, attempt_id, fencing_token, Jsonb(payload)],
        )

    def acknowledge_worker_cancel(
        self,
        attempt_id: str,
        worker_id: str,
        fencing_token: int,
    ) -> None:
        self.cursor.execute(
            """
            UPDATE authority_worker_cancel_signal
            SET status = 'ACKNOWLEDGED',
                acknowledged_at = NOW(),
                acknowledged_worker_id = %s,
                acknowledged_fencing_token = %s
            WHERE attempt_id = %s
              AND status = 'REQUESTED'
            """,
            [worker_id, fencing_token, attempt_id],
        )
        if self.cursor.rowcount != 1:
            raise KernelError(
                "CANCEL_SIGNAL_NOT_FOUND",
                "worker cancel signal is unavailable for this fencing token",
            )

    def compensation_parent_for_update(
        self,
        parent_operation_id: str,
        project_id: str,
    ) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT status, version, root_operation_id, workspace_id
            FROM authority_operation
            WHERE operation_id = %s AND project_id = %s
            FOR UPDATE
            """,
            [parent_operation_id, project_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "OPERATION_NOT_FOUND",
                "compensation parent does not exist in the requested project",
            )
        return {
            "status": row[0],
            "version": row[1],
            "root_operation_id": row[2],
            "workspace_id": row[3],
        }

    def require_compensation_child(
        self,
        child_operation_id: str,
        parent_operation_id: str,
        project_id: str,
    ) -> None:
        self.cursor.execute(
            """
            SELECT 1
            FROM authority_operation
            WHERE operation_id = %s
              AND parent_operation_id = %s
              AND project_id = %s
              AND metadata->>'operation_role' = 'compensation'
            """,
            [child_operation_id, parent_operation_id, project_id],
        )
        if self.cursor.fetchone() is None:
            raise KernelError(
                "COMPENSATION_CHILD_CONFLICT",
                "idempotency record does not identify this compensation child",
            )

    def compensation_parent(self, child_operation_id: str, project_id: str) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT parent.operation_id, parent.status, parent.version, child.status
            FROM authority_operation AS child
            JOIN authority_operation AS parent
              ON parent.operation_id = child.parent_operation_id
            WHERE child.operation_id = %s AND child.project_id = %s
              AND parent.project_id = %s
              AND child.metadata->>'operation_role' = 'compensation'
            FOR UPDATE OF parent, child
            """,
            [child_operation_id, project_id, project_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError("COMPENSATION_CHILD_NOT_FOUND", "compensation child is invalid")
        return {
            "parent_operation_id": row[0],
            "parent_status": row[1],
            "parent_version": row[2],
            "child_status": row[3],
        }


class RuntimeEvidenceRepository:
    def __init__(self, cursor: Any) -> None:
        self.cursor = cursor

    def record_operation_transition(self, row: dict[str, Any]) -> None:
        self.cursor.execute(
            """
            SELECT COALESCE(MAX(sequence_number), 0) + 1
            FROM state_event
            WHERE aggregate_type = 'authority_operation'
              AND aggregate_id = %s
            """,
            [row["operation_id"]],
        )
        sequence_number = self.cursor.fetchone()[0]
        event_payload = Jsonb(
            {
                "expected_status": row["expected_status"],
                "target_status": row["target_status"],
                "version": row["version"],
                "reason": row["reason"],
                "trace_id": row["trace_id"],
            }
        )
        self.cursor.execute(
            """
            INSERT INTO state_event (
                event_id,
                aggregate_type,
                aggregate_id,
                project_id,
                event_type,
                event_version,
                sequence_number,
                correlation_id,
                causation_id,
                payload
            )
            VALUES (
                %(event_id)s,
                'authority_operation',
                %(operation_id)s,
                %(project_id)s,
                'authority.operation.status_changed',
                1,
                %(sequence_number)s,
                %(correlation_id)s,
                %(causation_id)s,
                %(payload)s
            )
            """,
            {**row, "sequence_number": sequence_number, "payload": event_payload},
        )
        self.cursor.execute(
            """
            INSERT INTO audit_log (
                audit_id,
                project_id,
                operation_id,
                action,
                payload
            )
            VALUES (
                %(audit_id)s,
                %(project_id)s,
                %(operation_id)s,
                'authority.operation.status_changed',
                %(payload)s
            )
            """,
            {**row, "payload": event_payload},
        )
        self.cursor.execute(
            """
            INSERT INTO outbox_event (
                outbox_id,
                event_id,
                project_id,
                topic,
                status,
                payload
            )
            VALUES (
                %(outbox_id)s,
                %(event_id)s,
                %(project_id)s,
                'authority.operation.status_changed',
                'PENDING',
                %(payload)s
            )
            """,
            {**row, "payload": event_payload},
        )

    def record_attempt_transition(self, row: dict[str, Any]) -> None:
        self.cursor.execute(
            """
            SELECT COALESCE(MAX(sequence_number), 0) + 1
            FROM state_event
            WHERE aggregate_type = 'authority_attempt' AND aggregate_id = %s
            """,
            [row["attempt_id"]],
        )
        sequence_number = self.cursor.fetchone()[0]
        payload = Jsonb(
            {
                "expected_status": row["expected_status"],
                "target_status": row["target_status"],
                "worker_id": row.get("worker_id", ""),
                "fencing_token": row.get("fencing_token"),
            }
        )
        self.cursor.execute(
            """
            INSERT INTO state_event (
                event_id, aggregate_type, aggregate_id, project_id, event_type,
                event_version, sequence_number, correlation_id, causation_id, payload
            )
            VALUES (
                %(event_id)s, 'authority_attempt', %(attempt_id)s, %(project_id)s,
                'authority.attempt.status_changed', 1, %(sequence_number)s,
                %(correlation_id)s, %(causation_id)s, %(payload)s
            )
            """,
            {**row, "sequence_number": sequence_number, "payload": payload},
        )
        self.cursor.execute(
            """
            INSERT INTO audit_log (audit_id, project_id, operation_id, action, payload)
            VALUES (
                %(audit_id)s, %(project_id)s, %(operation_id)s,
                'authority.attempt.status_changed', %(payload)s
            )
            """,
            {**row, "payload": payload},
        )
        self.cursor.execute(
            """
            INSERT INTO outbox_event (outbox_id, event_id, project_id, topic, status, payload)
            VALUES (
                %(outbox_id)s, %(event_id)s, %(project_id)s,
                'authority.attempt.status_changed', 'PENDING', %(payload)s
            )
            """,
            {**row, "payload": payload},
        )

    def record_attempt_runtime_event(self, row: dict[str, Any]) -> None:
        self.cursor.execute(
            """
            SELECT COALESCE(MAX(sequence_number), 0) + 1
            FROM state_event
            WHERE aggregate_type = 'authority_attempt' AND aggregate_id = %s
            """,
            [row["attempt_id"]],
        )
        sequence_number = self.cursor.fetchone()[0]
        payload = Jsonb(row["payload"])
        self.cursor.execute(
            """
            INSERT INTO state_event (
                event_id, aggregate_type, aggregate_id, project_id, event_type,
                event_version, sequence_number, correlation_id, causation_id, payload
            )
            VALUES (
                %(event_id)s, 'authority_attempt', %(attempt_id)s, %(project_id)s,
                %(event_type)s, 1, %(sequence_number)s,
                %(correlation_id)s, %(causation_id)s, %(payload)s
            )
            """,
            {**row, "sequence_number": sequence_number, "payload": payload},
        )
        self.cursor.execute(
            """
            INSERT INTO audit_log (audit_id, project_id, operation_id, action, payload)
            VALUES (%(audit_id)s, %(project_id)s, %(operation_id)s, %(event_type)s, %(payload)s)
            """,
            {**row, "payload": payload},
        )
        self.cursor.execute(
            """
            INSERT INTO outbox_event (outbox_id, event_id, project_id, topic, status, payload)
            VALUES (
                %(outbox_id)s, %(event_id)s, %(project_id)s,
                %(event_type)s, 'PENDING', %(payload)s
            )
            """,
            {**row, "payload": payload},
        )


class AssetReferenceRepository:
    def __init__(self, cursor: Any) -> None:
        self.cursor = cursor

    def resolve_for_admission(
        self,
        project_id: str,
        references: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        resolved: list[dict[str, str]] = []
        for reference in references:
            asset_version_id = str(reference.get("asset_version_id") or "")
            self.cursor.execute(
                """
                SELECT
                    version.asset_version_id,
                    version.content_hash,
                    asset.project_id,
                    asset.project_id = %s AS same_project
                FROM authority_asset_version AS version
                JOIN authority_asset AS asset ON asset.asset_id = version.asset_id
                WHERE version.asset_version_id = %s
                """,
                [project_id, asset_version_id],
            )
            row = self.cursor.fetchone()
            if row is None:
                raise KernelError(
                    "INPUT_ASSET_NOT_FOUND",
                    f"input asset version does not exist: {asset_version_id}",
                )
            if not row[3]:
                raise KernelError(
                    "CROSS_PROJECT_REFERENCE",
                    f"input asset version belongs to another project: {asset_version_id}",
                )
            expected_hash = str(reference.get("content_hash") or "")
            if row[1] != expected_hash:
                raise KernelError(
                    "INPUT_ASSET_HASH_MISMATCH",
                    f"input asset hash mismatch: {asset_version_id}",
                )
            resolved.append(
                {
                    "asset_version_id": row[0],
                    "content_hash": row[1],
                    "project_id": row[2],
                }
            )
        return resolved


class AuthorityRepositories:
    def __init__(self, cursor: Any) -> None:
        from novel_forge.storage.asset_blob_repositories import AssetBlobRepository
        from novel_forge.storage.authority_asset_store import AuthorityAssetDocumentRepository
        from novel_forge.storage.chapter_authority_repositories import (
            ChapterAuthorityRepository,
        )
        from novel_forge.storage.external_effect_repositories import ExternalEffectRepository
        from novel_forge.storage.operation_graph_repositories import (
            CompletionContractRepository,
            OperationGraphRepository,
        )
        from novel_forge.storage.provider_callback_repositories import (
            ProviderCallbackRepository,
        )
        from novel_forge.storage.agent_collaboration_repositories import (
            PostgresAgentCollaborationRepository,
        )
        from novel_forge.modules.agent_runtime.repository import (
            PostgresAgentRuntimeRepository,
        )
        from novel_forge.storage.book_authority_repositories import (
            BookAuthorityRepository,
        )
        from novel_forge.storage.story_state_repositories import (
            StoryStateRepository,
        )
        from novel_forge.storage.story_design_repositories import (
            StoryDesignRepository,
        )
        from novel_forge.storage.chapter_group_repositories import (
            ChapterGroupRepository,
        )
        from novel_forge.storage.plan_change_repositories import (
            PlanChangeRepository,
        )
        from novel_forge.storage.capability_pack_authority_repositories import (
            CapabilityPackAuthorityRepository,
        )

        self.definitions = OperationDefinitionRepository(cursor)
        self.operations = OperationRepository(cursor)
        self.admission_evidence = AdmissionEvidenceRepository(cursor)
        self.operation_lifecycle = OperationLifecycleRepository(cursor)
        self.attempt_runtime = AttemptRuntimeRepository(cursor)
        self.cancellations = CancellationRepository(cursor)
        self.runtime_evidence = RuntimeEvidenceRepository(cursor)
        self.asset_references = AssetReferenceRepository(cursor)
        self.asset_blobs = AssetBlobRepository(cursor)
        self.asset_documents = AuthorityAssetDocumentRepository(cursor)
        self.chapter_authority = ChapterAuthorityRepository(cursor)
        self.external_effects = ExternalEffectRepository(cursor)
        self.operation_graph = OperationGraphRepository(cursor)
        self.completion_contracts = CompletionContractRepository(cursor)
        self.provider_callbacks = ProviderCallbackRepository(cursor)
        self.agent_collaboration = PostgresAgentCollaborationRepository(cursor)
        self.agent_runtime = PostgresAgentRuntimeRepository(cursor)
        self.book_authority = BookAuthorityRepository(cursor)
        self.story_state = StoryStateRepository(cursor)
        self.story_design = StoryDesignRepository(cursor)
        self.chapter_group = ChapterGroupRepository(cursor)
        self.plan_change = PlanChangeRepository(cursor)
        self.capability_packs = CapabilityPackAuthorityRepository(cursor)

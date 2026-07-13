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
        if inserted is not None:
            return {"registered": True, "definition_hash": inserted[0]}

        existing = self.get(row["name"], row["definition_version"])
        if existing is None or existing["definition_hash"] != digest:
            raise KernelError(
                "OPERATION_DEFINITION_VERSION_CONFLICT",
                "operation definition name/version is already bound to different content",
            )
        return {"registered": False, "definition_hash": digest}


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
                root_operation_id,
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
                metadata
            )
            VALUES (
                %(operation_id)s,
                %(definition_name)s,
                %(definition_version)s,
                %(project_id)s,
                'ADMITTED',
                %(root_operation_id)s,
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
                %(metadata)s
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
        self.definitions = OperationDefinitionRepository(cursor)
        self.operations = OperationRepository(cursor)
        self.admission_evidence = AdmissionEvidenceRepository(cursor)
        self.operation_lifecycle = OperationLifecycleRepository(cursor)
        self.runtime_evidence = RuntimeEvidenceRepository(cursor)
        self.asset_references = AssetReferenceRepository(cursor)

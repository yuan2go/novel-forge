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

    def create(self, row: dict[str, Any]) -> None:
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
                %(metadata)s
            )
            """,
            {
                **row,
                "definition_snapshot": Jsonb(row["definition_snapshot"]),
                "completion_contract_snapshot": Jsonb(
                    row["completion_contract_snapshot"]
                ),
                "policy_snapshot": Jsonb(row["policy_snapshot"]),
                "metadata": Jsonb(row.get("metadata", {})),
            },
        )


class AuthorityRepositories:
    def __init__(self, cursor: Any) -> None:
        self.definitions = OperationDefinitionRepository(cursor)
        self.operations = OperationRepository(cursor)

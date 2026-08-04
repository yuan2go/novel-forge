"""Independent, operation-backed migration approval boundary."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.authority_security import Principal
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.service import (
    AdmissionContext,
    TransactionCheckpoint,
    execute_transaction_command,
)
from novel_forge.modules.legacy_migration.state_machine import MigrationDecision
from novel_forge.modules.legacy_migration.validation import (
    load_validation_snapshot,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


MIGRATION_DECISION_VERSION = "2.0.1"
MIGRATION_DECISION_HANDLER = "novel_forge.legacy_migration.item_decision"
MIGRATION_DECISION_OPERATIONS = {
    MigrationDecision.APPROVE: "migration.item.approve",
    MigrationDecision.REJECT: "migration.item.reject",
}


@dataclass(frozen=True, slots=True)
class LegacyMigrationDecisionCommand:
    migration_run_id: str
    migration_item_id: str
    project_id: str
    workspace_id: str
    actor_id: str
    decision: MigrationDecision
    reason: str
    expected_item_version: int
    source_hash: str
    target_asset_version_id: str
    migration_validation_id: str
    idempotency_key: str
    trace_id: str
    correlation_id: str

    def __post_init__(self) -> None:
        for field in (
            "migration_run_id",
            "migration_item_id",
            "project_id",
            "workspace_id",
            "actor_id",
            "reason",
            "source_hash",
            "target_asset_version_id",
            "idempotency_key",
            "trace_id",
            "correlation_id",
        ):
            if not str(getattr(self, field)).strip():
                raise ValueError(f"{field} is required")
        if self.expected_item_version < 0:
            raise ValueError("expected_item_version cannot be negative")
        if not self.source_hash.startswith("sha256:"):
            raise ValueError("source_hash must be canonical SHA-256")
        if self.decision is MigrationDecision.APPROVE and not str(
            self.migration_validation_id
        ).strip():
            raise ValueError("approval requires migration_validation_id")


def migration_decision_definitions(
    *, application_build_id: str, commit_sha: str
) -> tuple[dict[str, Any], ...]:
    schema = {
        "type": "object",
        "required": [
            "migration_run_id",
            "migration_item_id",
            "project_id",
            "workspace_id",
            "decision",
            "reason",
            "expected_item_version",
            "source_hash",
            "target_asset_version_id",
            "migration_validation_id",
            "client_idempotency_key",
        ],
        "properties": {
            "migration_run_id": {"type": "string"},
            "migration_item_id": {"type": "string"},
            "project_id": {"type": "string"},
            "workspace_id": {"type": "string"},
            "decision": {"type": "string", "enum": ["APPROVE", "REJECT"]},
            "reason": {"type": "string"},
            "expected_item_version": {"type": "integer", "minimum": 0},
            "source_hash": {"type": "string"},
            "target_asset_version_id": {"type": "string"},
            "migration_validation_id": {"type": "string"},
            "client_idempotency_key": {"type": "string"},
        },
        "additionalProperties": False,
    }
    return tuple(
        {
            "name": name,
            "definition_version": MIGRATION_DECISION_VERSION,
            "family": "legacy_migration_authority",
            "enabled": True,
            "definition_status": "release_candidate",
            "command_schema_version": "migration-item-decision-v2",
            "result_schema_version": "migration-item-decision-result-v2",
            "command_schema": schema,
            "result_schema": {"type": "object"},
            "input_contract": schema,
            "output_contract": {
                "asset_type": "migration_decision",
                "output_key": "migration.item.decision",
            },
            "handler_key": MIGRATION_DECISION_HANDLER,
            "handler_contract_version": MIGRATION_DECISION_VERSION,
            "application_build_id": application_build_id,
            "commit_sha": commit_sha,
            "execution_mode": "transactional",
            "permissions": ["legacy_migration.approve"],
            "approval_policy": {"required": False},
            "policy": {
                "execution_classification": "transaction_command",
                "independent_decision": True,
                "legacy_status_is_evidence_only": True,
                "validation_binding": "server_record_id_only",
                "client_validation_evidence_forbidden": True,
                "decision": decision.value,
                "activation_is_separate": True,
            },
            "idempotency_scope": "migration:item-decision",
            "concurrency_key_template": "migration-item:{migration_item_id}",
            "retry_policy": {"max_attempts": 1, "mode": "client_replay_only"},
            "timeout_policy": {"operation_timeout_seconds": 60},
            "cancellation_policy": {"mode": "not_applicable_atomic_transaction"},
            "compensation_policy": {
                "supported": False,
                "reason": "append-only decision with item CAS",
            },
            "irreversible_effect_policy": {"allowed": False},
            "external_capabilities": [],
            "completion_contract": {
                "version": "migration.item.decision.completion.v2",
                "required_asset_selectors": [],
                "required_qualifications": [],
                "required_evidence": ["trace", "audit"],
                "required_outbox_events": ["legacy_migration.item.decided"],
            },
        }
        for decision, name in MIGRATION_DECISION_OPERATIONS.items()
    )


class LegacyMigrationApprovalApplication:
    def __init__(
        self,
        database_url: str,
        *,
        application_build_id: str,
        commit_sha: str,
    ) -> None:
        if not database_url or not application_build_id or len(commit_sha) != 40:
            raise ValueError(
                "Legacy migration approval requires PostgreSQL and build identity"
            )
        self.database_url = database_url
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha

    def execute(
        self,
        command: LegacyMigrationDecisionCommand,
        *,
        principal: Principal | None = None,
    ) -> dict[str, Any]:
        actor_id = command.actor_id
        if principal is not None:
            principal.require("legacy_migration.approve", command.project_id)
            actor_id = principal.principal_id
            if actor_id != command.actor_id:
                raise KernelError(
                    "ACTOR_IDENTITY_INVALID",
                    "migration decision actor does not match authenticated principal",
                )
        self._register_definitions()
        operation_name = MIGRATION_DECISION_OPERATIONS[command.decision]
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT version.content_hash
                FROM authority_asset_version AS version
                JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                WHERE version.asset_version_id=%s AND asset.project_id=%s
                """,
                [command.target_asset_version_id, command.project_id],
            )
            target = uow.cursor.fetchone()
            if command.decision is MigrationDecision.APPROVE:
                uow.cursor.execute(
                    """
                    SELECT validation.target_asset_version_id,
                           validation.status, validation.result_hash
                    FROM authority_legacy_migration_validation AS validation
                    JOIN authority_asset AS asset
                      ON asset.asset_id=validation.target_asset_id
                    WHERE validation.migration_validation_id=%s
                      AND asset.project_id=%s
                    """,
                    [command.migration_validation_id, command.project_id],
                )
                validation_target = uow.cursor.fetchone()
                if (
                    validation_target is None
                    or str(validation_target[0]) != command.target_asset_version_id
                ):
                    raise KernelError(
                        "MIGRATION_VALIDATION_SCOPE_CONFLICT",
                        "validation is absent, outside Project scope, or targets another version",
                    )
        if target is None:
            raise KernelError(
                "MIGRATION_DECISION_TARGET_INVALID",
                "decision target is absent or outside Project scope",
            )
        return execute_transaction_command(
            self.database_url,
            {
                "definition_name": operation_name,
                "definition_version": MIGRATION_DECISION_VERSION,
                "project_id": command.project_id,
                "workspace_id": command.workspace_id,
                "migration_run_id": command.migration_run_id,
                "migration_item_id": command.migration_item_id,
                "actor_id": actor_id,
                "idempotency_scope": "migration:item-decision",
                "idempotency_key": command.idempotency_key,
                "trace_id": command.trace_id,
                "span_id": str(uuid4()),
                "correlation_id": command.correlation_id,
                "causation_id": command.migration_item_id,
                "input": {
                    "migration_run_id": command.migration_run_id,
                    "migration_item_id": command.migration_item_id,
                    "project_id": command.project_id,
                    "workspace_id": command.workspace_id,
                    "decision": command.decision.value,
                    "reason": command.reason,
                    "expected_item_version": command.expected_item_version,
                    "source_hash": command.source_hash,
                    "target_asset_version_id": command.target_asset_version_id,
                    "migration_validation_id": command.migration_validation_id,
                    "client_idempotency_key": command.idempotency_key,
                },
                "input_assets": [
                    {
                        "asset_version_id": command.target_asset_version_id,
                        "content_hash": str(target[0]),
                    }
                ],
            },
            context=AdmissionContext(
                actor_id=actor_id,
                permissions=frozenset({"legacy_migration.approve"}),
                available_handlers=frozenset({MIGRATION_DECISION_HANDLER}),
                application_build_id=self.application_build_id,
                commit_sha=self.commit_sha,
            ),
            handler=self._execute_transaction,
        )

    def _register_definitions(self) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            for definition in migration_decision_definitions(
                application_build_id=self.application_build_id,
                commit_sha=self.commit_sha,
            ):
                uow.repositories.definitions.register(definition)
            uow.commit()

    @staticmethod
    def _execute_transaction(
        uow: AuthorityUnitOfWork,
        operation_id: str,
        checkpoint: TransactionCheckpoint,
    ) -> dict[str, Any]:
        uow.cursor.execute(
            """
            SELECT project_id, workspace_id, actor_id, command_payload,
                   trace_id, correlation_id
            FROM authority_operation
            WHERE operation_id=%s
            """,
            [operation_id],
        )
        operation = uow.cursor.fetchone()
        if operation is None:
            raise KernelError(
                "MIGRATION_DECISION_OPERATION_MISSING",
                "admitted migration decision Operation disappeared",
            )
        payload = dict(operation[3])
        item_id = str(payload["migration_item_id"])
        expected_version = int(payload["expected_item_version"])
        uow.cursor.execute(
            """
            SELECT migration_run_id, project_id, workspace_id, source_hash,
                   target_asset_version_id, item_version, status
            FROM authority_legacy_migration_item
            WHERE migration_item_id=%s
            FOR UPDATE
            """,
            [item_id],
        )
        item = uow.cursor.fetchone()
        if item is None:
            raise KernelError(
                "MIGRATION_ITEM_NOT_FOUND", "migration decision item does not exist"
            )
        expected = (
            str(payload["migration_run_id"]),
            str(operation[0]),
            str(operation[1]),
            str(payload["source_hash"]),
            str(payload["target_asset_version_id"]),
        )
        actual = tuple(str(value or "") for value in item[:5])
        if actual != expected:
            raise KernelError(
                "MIGRATION_DECISION_SCOPE_CONFLICT",
                "migration decision scope, hash, or target changed",
            )
        if int(item[5]) != expected_version:
            raise KernelError(
                "MIGRATION_ITEM_VERSION_CONFLICT",
                "migration decision expected item version is stale",
            )
        if str(item[6]) not in {"NEEDS_REVIEW", "QUALIFIED"}:
            raise KernelError(
                "MIGRATION_ITEM_NOT_REVIEWABLE",
                "migration item is not awaiting an independent decision",
            )
        decision = MigrationDecision(str(payload["decision"]))
        validation_id = str(payload.get("migration_validation_id") or "")
        validation_result_hash = ""
        server_validation_evidence: dict[str, Any] = {
            "status": "NOT_REQUIRED",
            "server_authoritative": True,
        }
        if decision is MigrationDecision.APPROVE:
            uow.cursor.execute(
                """
                SELECT migration_run_id, migration_item_id,
                       validation_version, item_version, source_hash,
                       target_asset_id, target_asset_version_id,
                       target_materialization_level, domain_adapter,
                       validator_name, validator_version,
                       validator_implementation_hash, input_hash, result_hash,
                       reference_snapshot_hash, dependency_projection_hash,
                       status, evidence
                FROM authority_legacy_migration_validation
                WHERE migration_validation_id=%s
                FOR SHARE
                """,
                [validation_id],
            )
            validation = uow.cursor.fetchone()
            if validation is None:
                raise KernelError(
                    "MIGRATION_VALIDATION_NOT_FOUND",
                    "approval validation record does not exist",
                )
            validation_scope = (
                str(validation[0]),
                str(validation[1]),
                str(validation[4]),
                str(validation[6]),
                str(validation[8]),
            )
            snapshot = load_validation_snapshot(
                uow,
                item_id,
                bound_item_version=int(validation[3]),
            )
            expected_validation_scope = (
                str(payload["migration_run_id"]),
                item_id,
                str(payload["source_hash"]),
                str(payload["target_asset_version_id"]),
                snapshot["validator_descriptor"].domain_adapter,
            )
            if validation_scope != expected_validation_scope:
                raise KernelError(
                    "MIGRATION_VALIDATION_SCOPE_CONFLICT",
                    "validation no longer matches run, item, source, target, or adapter",
                )
            if int(validation[3]) != expected_version:
                raise KernelError(
                    "MIGRATION_VALIDATION_STALE",
                    "validation item version no longer matches the approval item",
                )
            if str(validation[16]) != "PASS":
                raise KernelError(
                    "MIGRATION_VALIDATION_NOT_PASSING",
                    "approval requires a non-revoked PASS validation",
                )
            uow.cursor.execute(
                """
                SELECT MAX(validation_version)
                FROM authority_legacy_migration_validation
                WHERE migration_item_id=%s AND status='PASS'
                """,
                [item_id],
            )
            if int(uow.cursor.fetchone()[0] or 0) != int(validation[2]):
                raise KernelError(
                    "MIGRATION_VALIDATION_STALE",
                    "approval validation is not the latest PASS version",
                )
            current_descriptor = snapshot["validator_descriptor"]
            if (
                str(validation[11])
                != current_descriptor.validator_implementation_hash
                or str(validation[10]) != current_descriptor.validator_version
                or str(validation[9]) != current_descriptor.validator_name
                or str(validation[12]) != snapshot["input_hash"]
                or str(validation[14]) != snapshot["reference_snapshot_hash"]
                or str(validation[15]) != snapshot["dependency_projection_hash"]
            ):
                raise KernelError(
                    "MIGRATION_VALIDATION_STALE",
                    "validator implementation or validation inputs changed",
                )
            validation_result_hash = str(validation[13])
            server_validation_evidence = dict(validation[17])
        checkpoint("after_domain_validation")
        uow.cursor.execute(
            """
            SELECT COALESCE(MAX(decision_version), 0) + 1
            FROM authority_legacy_migration_decision
            WHERE migration_item_id=%s
            """,
            [item_id],
        )
        decision_version = int(uow.cursor.fetchone()[0])
        decision_id = str(uuid4())
        uow.cursor.execute(
            """
            INSERT INTO authority_legacy_migration_decision(
                migration_decision_id, migration_run_id, migration_item_id,
                decision_version, actor_id, decision, reason,
                expected_item_version, source_hash, target_asset_version_id,
                domain_validation_evidence, idempotency_key, operation_id,
                migration_validation_id, validation_result_hash
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s
            )
            """,
            [
                decision_id,
                payload["migration_run_id"],
                item_id,
                decision_version,
                operation[2],
                decision.value,
                payload["reason"],
                expected_version,
                payload["source_hash"],
                payload["target_asset_version_id"],
                Jsonb(server_validation_evidence),
                payload["client_idempotency_key"],
                operation_id,
                validation_id or None,
                validation_result_hash,
            ],
        )
        target_status = (
            "QUALIFIED"
            if decision is MigrationDecision.APPROVE
            else "INELIGIBLE"
        )
        uow.cursor.execute(
            """
            UPDATE authority_legacy_migration_item
            SET status=%s,
                domain_state=CASE
                    WHEN validation_scope='DOMAIN' THEN %s
                    ELSE domain_state
                END,
                item_version=item_version+1,
                evidence=evidence || %s, updated_at=NOW()
            WHERE migration_item_id=%s AND item_version=%s
            """,
            [
                target_status,
                (
                    "DOMAIN_ACTIVATION_PENDING"
                    if decision is MigrationDecision.APPROVE
                    else "DOMAIN_REJECTED"
                ),
                Jsonb(
                    {
                        "independent_decision_id": decision_id,
                        "independent_decision": decision.value,
                        "migration_validation_id": validation_id,
                        "validation_result_hash": validation_result_hash,
                        "activation_pending": decision is MigrationDecision.APPROVE,
                    }
                ),
                item_id,
                expected_version,
            ],
        )
        if uow.cursor.rowcount != 1:
            raise KernelError(
                "MIGRATION_ITEM_VERSION_CONFLICT",
                "migration item changed during decision compare-and-set",
            )
        checkpoint("after_business_projection_update")
        uow.repositories.operation_graph.record_event(
            {
                "event_id": str(uuid4()),
                "audit_id": str(uuid4()),
                "outbox_id": str(uuid4()),
                "aggregate_type": "authority_legacy_migration_item",
                "aggregate_id": item_id,
                "operation_id": operation_id,
                "project_id": str(operation[0]),
                "event_type": "legacy_migration.item.decided",
                "correlation_id": str(operation[5]),
                "causation_id": item_id,
                "payload": {
                    "operation_id": operation_id,
                    "migration_run_id": payload["migration_run_id"],
                    "migration_item_id": item_id,
                    "decision_id": decision_id,
                    "decision": decision.value,
                    "migration_validation_id": validation_id,
                    "validation_result_hash": validation_result_hash,
                    "target_status": target_status,
                    "expected_item_version": expected_version,
                    "new_item_version": expected_version + 1,
                },
            }
        )
        checkpoint("after_outbox_insert")
        return {
            "migration_item_id": item_id,
            "migration_decision_id": decision_id,
            "decision": decision.value,
            "migration_validation_id": validation_id,
            "validation_result_hash": validation_result_hash,
            "status": target_status,
            "item_version": expected_version + 1,
            "activation_pending": decision is MigrationDecision.APPROVE,
        }


__all__ = [
    "LegacyMigrationApprovalApplication",
    "LegacyMigrationDecisionCommand",
    "MIGRATION_DECISION_OPERATIONS",
]

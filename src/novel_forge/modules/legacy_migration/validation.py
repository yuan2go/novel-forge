"""Server-authoritative, operation-backed Legacy domain validation."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
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
from novel_forge.modules.legacy_migration.domain_adapters import (
    DomainMigrationAdapterRegistry,
    DomainMigrationContext,
    ResolvedMigrationReference,
)
from novel_forge.modules.legacy_migration.state_machine import (
    MigrationMaterializationLevel,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


MIGRATION_VALIDATION_OPERATION = "migration.item.validate"
MIGRATION_VALIDATION_HANDLER = "novel_forge.legacy_migration.item_validate"
MIGRATION_VALIDATION_DEFINITION_VERSION = "1.1.0"


class MigrationValidationStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    STALE = "STALE"
    REVOKED = "REVOKED"


@dataclass(frozen=True, slots=True)
class DomainValidatorDescriptor:
    domain_adapter: str
    adapter_version: str
    validator_name: str
    validator_version: str
    validator_implementation_hash: str


_VALIDATOR_NAMES = {
    "novel_forge.legacy_migration.archival_asset_version.v1": "archival-native-asset-envelope-validator",
    "novel_forge.legacy_migration.project_authority.v1": "project-workspace-domain-validator",
    "novel_forge.legacy_migration.book_design_authority.v1": "book-design-domain-validator",
    "novel_forge.legacy_migration.story_design_authority.v1": "story-design-domain-validator",
    "novel_forge.legacy_migration.hierarchical_planning.v1": "hierarchical-planning-domain-validator",
    "novel_forge.legacy_migration.source_authority.v1": "source-document-domain-validator",
    "novel_forge.legacy_migration.mkaos_authority.v1": "mkaos-domain-validator",
}

_COMMON_VALIDATOR_DEPENDENCIES = (
    "modules/legacy_migration/validation.py",
    "modules/legacy_migration/domain_adapters.py",
)
_VALIDATOR_DEPENDENCIES = {
    "novel_forge.legacy_migration.archival_asset_version.v1": (),
    "novel_forge.legacy_migration.project_authority.v1": (
        "modules/project_authority/domain.py",
        "modules/project_authority/query.py",
    ),
    "novel_forge.legacy_migration.book_design_authority.v1": (
        "modules/book_design_authority/domain.py",
        "modules/book_design_authority/query.py",
    ),
    "novel_forge.legacy_migration.story_design_authority.v1": (
        "modules/story_design_authority/domain.py",
        "modules/story_design_authority/validators.py",
    ),
    "novel_forge.legacy_migration.hierarchical_planning.v1": (
        "modules/hierarchical_planning/domain.py",
    ),
    "novel_forge.legacy_migration.source_authority.v1": (
        "modules/source_authority/domain.py",
        "modules/source_authority/query.py",
        "storage/asset_blob_repositories.py",
    ),
    "novel_forge.legacy_migration.mkaos_authority.v1": (
        "modules/mkaos_authority/application.py",
        "modules/mkaos_authority/domain.py",
        "modules/mkaos_authority/query.py",
    ),
}


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def validator_descriptor(
    domain_adapter: str,
    *,
    application_build_id: str,
    commit_sha: str,
) -> DomainValidatorDescriptor:
    if not application_build_id or len(commit_sha) != 40:
        raise ValueError("validator descriptor requires tested build identity")
    try:
        validator_name = _VALIDATOR_NAMES[domain_adapter]
    except KeyError as exc:
        raise KernelError(
            "DOMAIN_MIGRATION_ADAPTER_NOT_IMPLEMENTED",
            f"domain migration adapter is not implemented: {domain_adapter}",
        ) from exc
    marker, separator, adapter_version = domain_adapter.rpartition(".v")
    if not marker or separator != ".v" or not adapter_version.isdigit():
        raise KernelError(
            "DOMAIN_VALIDATOR_VERSION_INVALID",
            f"domain adapter has no frozen version: {domain_adapter}",
        )
    package_root = Path(__file__).parents[2]
    dependency_paths = (
        *_COMMON_VALIDATOR_DEPENDENCIES,
        *_VALIDATOR_DEPENDENCIES[domain_adapter],
    )
    implementation_inputs = {
        relative_path: hashlib.sha256(
            (package_root / relative_path).read_bytes()
        ).hexdigest()
        for relative_path in dependency_paths
    }
    implementation_hash = canonical_hash(
        {
            "domain_adapter": domain_adapter,
            "validator_version": MIGRATION_VALIDATION_DEFINITION_VERSION,
            "dependency_manifest_version": "legacy-migration-validator-dependencies-v1",
            "dependencies": implementation_inputs,
        }
    )
    return DomainValidatorDescriptor(
        domain_adapter=domain_adapter,
        adapter_version=adapter_version,
        validator_name=validator_name,
        validator_version=MIGRATION_VALIDATION_DEFINITION_VERSION,
        validator_implementation_hash=implementation_hash,
    )


@dataclass(frozen=True, slots=True)
class LegacyMigrationValidationCommand:
    migration_run_id: str
    migration_item_id: str
    project_id: str
    workspace_id: str
    actor_id: str
    expected_item_version: int
    source_hash: str
    target_asset_version_id: str
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


def migration_validation_definition(
    *, application_build_id: str, commit_sha: str
) -> dict[str, Any]:
    schema = {
        "type": "object",
        "required": [
            "migration_run_id",
            "migration_item_id",
            "project_id",
            "workspace_id",
            "expected_item_version",
            "source_hash",
            "target_asset_version_id",
            "client_idempotency_key",
        ],
        "properties": {
            "migration_run_id": {"type": "string"},
            "migration_item_id": {"type": "string"},
            "project_id": {"type": "string"},
            "workspace_id": {"type": "string"},
            "expected_item_version": {"type": "integer", "minimum": 0},
            "source_hash": {"type": "string"},
            "target_asset_version_id": {"type": "string"},
            "client_idempotency_key": {"type": "string"},
        },
        "additionalProperties": False,
    }
    return {
        "name": MIGRATION_VALIDATION_OPERATION,
        "definition_version": MIGRATION_VALIDATION_DEFINITION_VERSION,
        "family": "legacy_migration_authority",
        "enabled": True,
        "definition_status": "release_candidate",
        "command_schema_version": "migration-item-validation-v1",
        "result_schema_version": "migration-item-validation-result-v1",
        "command_schema": schema,
        "result_schema": {"type": "object"},
        "input_contract": schema,
        "output_contract": {
            "asset_type": "migration_validation",
            "output_key": "migration.item.validation",
        },
        "handler_key": MIGRATION_VALIDATION_HANDLER,
        "handler_contract_version": MIGRATION_VALIDATION_DEFINITION_VERSION,
        "application_build_id": application_build_id,
        "commit_sha": commit_sha,
        "execution_mode": "transactional",
        "permissions": ["legacy_migration.validate"],
        "approval_policy": {"required": False},
        "policy": {
            "execution_classification": "transaction_command",
            "server_authoritative_validation": True,
            "client_validation_evidence_forbidden": True,
            "adapter_and_validator_frozen": True,
        },
        "idempotency_scope": "migration:item-validation",
        "concurrency_key_template": "migration-item:{migration_item_id}",
        "retry_policy": {"max_attempts": 1, "mode": "client_replay_only"},
        "timeout_policy": {"operation_timeout_seconds": 120},
        "cancellation_policy": {"mode": "not_applicable_atomic_transaction"},
        "compensation_policy": {
            "supported": False,
            "reason": "append-only validation with item CAS",
        },
        "irreversible_effect_policy": {"allowed": False},
        "external_capabilities": [],
        "completion_contract": {
            "version": "migration.item.validation.completion.v1",
            "required_asset_selectors": [],
            "required_qualifications": [],
            "required_evidence": ["trace", "audit"],
            "required_outbox_events": ["legacy_migration.item.validated"],
        },
        "projection_consumers": [
            "authority_legacy_migration_validation",
            "authority_legacy_migration_item",
        ],
        "migration_owner": "legacy-migration-authority",
    }


class LegacyMigrationValidationApplication:
    def __init__(
        self,
        database_url: str,
        *,
        application_build_id: str,
        commit_sha: str,
    ) -> None:
        if not database_url or not application_build_id or len(commit_sha) != 40:
            raise ValueError(
                "Legacy migration validation requires PostgreSQL and build identity"
            )
        self.database_url = database_url
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha

    def execute(
        self,
        command: LegacyMigrationValidationCommand,
        *,
        principal: Principal | None = None,
    ) -> dict[str, Any]:
        actor_id = command.actor_id
        if principal is not None:
            principal.require("legacy_migration.validate", command.project_id)
            actor_id = principal.principal_id
            if actor_id != command.actor_id:
                raise KernelError(
                    "ACTOR_IDENTITY_INVALID",
                    "migration validator does not match authenticated principal",
                )
        self._register_definition()
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
        if target is None:
            raise KernelError(
                "MIGRATION_VALIDATION_TARGET_INVALID",
                "validation target is absent or outside Project scope",
            )
        return execute_transaction_command(
            self.database_url,
            {
                "definition_name": MIGRATION_VALIDATION_OPERATION,
                "definition_version": MIGRATION_VALIDATION_DEFINITION_VERSION,
                "project_id": command.project_id,
                "workspace_id": command.workspace_id,
                "migration_run_id": command.migration_run_id,
                "migration_item_id": command.migration_item_id,
                "actor_id": actor_id,
                "idempotency_scope": "migration:item-validation",
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
                    "expected_item_version": command.expected_item_version,
                    "source_hash": command.source_hash,
                    "target_asset_version_id": command.target_asset_version_id,
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
                permissions=frozenset({"legacy_migration.validate"}),
                available_handlers=frozenset({MIGRATION_VALIDATION_HANDLER}),
                application_build_id=self.application_build_id,
                commit_sha=self.commit_sha,
            ),
            handler=self._execute_transaction,
        )

    def _register_definition(self) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.repositories.definitions.register(
                migration_validation_definition(
                    application_build_id=self.application_build_id,
                    commit_sha=self.commit_sha,
                )
            )
            uow.commit()

    def _execute_transaction(
        self,
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
                "MIGRATION_VALIDATION_OPERATION_MISSING",
                "admitted migration validation Operation disappeared",
            )
        payload = dict(operation[3])
        item_id = str(payload["migration_item_id"])
        expected_version = int(payload["expected_item_version"])
        uow.cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            [str(payload["migration_run_id"])],
        )
        snapshot = load_validation_snapshot(
            uow,
            item_id,
            bound_item_version=expected_version + 1,
            lock_item=True,
            application_build_id=self.application_build_id,
            commit_sha=self.commit_sha,
        )
        item = snapshot["item"]
        expected_scope = (
            str(payload["migration_run_id"]),
            str(operation[0]),
            str(operation[1]),
            str(payload["source_hash"]),
            str(payload["target_asset_version_id"]),
        )
        actual_scope = (
            item["migration_run_id"],
            item["project_id"],
            item["workspace_id"],
            item["source_hash"],
            item["target_asset_version_id"],
        )
        if actual_scope != expected_scope:
            raise KernelError(
                "MIGRATION_VALIDATION_SCOPE_CONFLICT",
                "migration validation scope, hash, or target changed",
            )
        if item["item_version"] != expected_version:
            raise KernelError(
                "MIGRATION_ITEM_VERSION_CONFLICT",
                "migration validation expected item version is stale",
            )
        revalidating_activated_item = item["status"] == "ACTIVATED"
        if item["status"] not in {"NEEDS_REVIEW", "ACTIVATED"}:
            raise KernelError(
                "MIGRATION_ITEM_NOT_VALIDATABLE",
                "migration item is neither awaiting validation nor an activated projection",
            )
        if (
            revalidating_activated_item
            and item["target_materialization_level"]
            != MigrationMaterializationLevel.DOMAIN_NATIVE.value
        ):
            raise KernelError(
                "MIGRATION_ITEM_NOT_VALIDATABLE",
                "only activated DOMAIN_NATIVE items support append-only revalidation",
            )
        checkpoint("after_validation_snapshot_lock")
        validation_status = MigrationValidationStatus.PASS
        evidence: dict[str, Any]
        unresolved_required = snapshot["unresolved_required_references"]
        if unresolved_required:
            validation_status = MigrationValidationStatus.FAIL
            evidence = {
                "status": "FAIL",
                "error_code": "MIGRATION_REQUIRED_REFERENCE_UNRESOLVED",
                "unresolved_required_references": unresolved_required,
            }
        elif (
            item["target_materialization_level"]
            == MigrationMaterializationLevel.ARCHIVAL_NATIVE.value
        ):
            if item["target_content_hash"] != item["asset_version_content_hash"]:
                validation_status = MigrationValidationStatus.FAIL
                evidence = {
                    "status": "FAIL",
                    "error_code": "ARCHIVAL_TARGET_HASH_MISMATCH",
                }
            else:
                evidence = {
                    "status": "PASS",
                    "validator": "archival-native-asset-envelope-validator",
                    "source_hash": item["source_hash"],
                    "target_asset_id": item["target_asset_id"],
                    "target_asset_version_id": item["target_asset_version_id"],
                    "target_content_hash": item["target_content_hash"],
                    "materialization_level": MigrationMaterializationLevel.ARCHIVAL_NATIVE.value,
                }
        else:
            adapter = DomainMigrationAdapterRegistry(
                self.database_url,
                application_build_id=self.application_build_id,
                commit_sha=self.commit_sha,
            ).resolve(item["domain_adapter"])
            try:
                validation_context = replace(
                    snapshot["context"], actor_id=str(operation[2])
                )
                evidence = dict(adapter.validate(validation_context))
                if evidence.get("status") != "PASS":
                    validation_status = MigrationValidationStatus.FAIL
                    evidence["status"] = "FAIL"
                    evidence.setdefault(
                        "error_code", "DOMAIN_VALIDATOR_DID_NOT_PASS"
                    )
            except (KernelError, ValueError) as exc:
                validation_status = MigrationValidationStatus.FAIL
                evidence = {
                    "status": "FAIL",
                    "error_code": getattr(exc, "code", "DOMAIN_VALIDATION_FAILED"),
                    "error_detail": str(exc),
                }
        descriptor: DomainValidatorDescriptor = snapshot["validator_descriptor"]
        evidence.update(
            {
                "server_authoritative": True,
                "domain_adapter": descriptor.domain_adapter,
                "validator_name": descriptor.validator_name,
                "validator_version": descriptor.validator_version,
                "validator_implementation_hash": (
                    descriptor.validator_implementation_hash
                ),
                "input_hash": snapshot["input_hash"],
                "reference_snapshot_hash": snapshot["reference_snapshot_hash"],
                "dependency_projection_hash": snapshot[
                    "dependency_projection_hash"
                ],
            }
        )
        result_hash = canonical_hash(evidence)
        uow.cursor.execute(
            """
            SELECT COALESCE(MAX(validation_version), 0) + 1
            FROM authority_legacy_migration_validation
            WHERE migration_item_id=%s
            """,
            [item_id],
        )
        validation_version = int(uow.cursor.fetchone()[0])
        validation_id = str(uuid4())
        validated_item_version = expected_version + 1
        uow.cursor.execute(
            """
            UPDATE authority_legacy_migration_validation
            SET status='STALE'
            WHERE migration_item_id=%s AND status='PASS'
              AND item_version<>%s
            """,
            [item_id, validated_item_version],
        )
        uow.cursor.execute(
            """
            INSERT INTO authority_legacy_migration_validation(
                migration_validation_id, migration_run_id, migration_item_id,
                validation_version, item_version, source_hash,
                target_asset_id, target_asset_version_id,
                target_materialization_level, domain_adapter,
                validator_name, validator_version,
                validator_implementation_hash, input_hash, result_hash,
                reference_snapshot_hash, dependency_projection_hash,
                status, evidence, validated_by_operation_id,
                validated_by_actor_id
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            [
                validation_id,
                item["migration_run_id"],
                item_id,
                validation_version,
                validated_item_version,
                item["source_hash"],
                item["target_asset_id"],
                item["target_asset_version_id"],
                item["target_materialization_level"],
                descriptor.domain_adapter,
                descriptor.validator_name,
                descriptor.validator_version,
                descriptor.validator_implementation_hash,
                snapshot["input_hash"],
                result_hash,
                snapshot["reference_snapshot_hash"],
                snapshot["dependency_projection_hash"],
                validation_status.value,
                Jsonb(evidence),
                operation_id,
                operation[2],
            ],
        )
        uow.cursor.execute(
            """
            UPDATE authority_legacy_migration_item
            SET item_version=item_version+1,
                domain_state=CASE
                    WHEN validation_scope='DOMAIN' AND status='NEEDS_REVIEW'
                        THEN %s
                    ELSE domain_state
                END,
                evidence=evidence || %s,
                updated_at=NOW()
            WHERE migration_item_id=%s AND item_version=%s
              AND status=%s
            """,
            [
                (
                    "DOMAIN_DECISION_PENDING"
                    if validation_status is MigrationValidationStatus.PASS
                    else "DOMAIN_VALIDATION_FAILED"
                ),
                Jsonb(
                    {
                        "latest_domain_validation_id": validation_id,
                        "latest_domain_validation_status": validation_status.value,
                        "latest_domain_validation_result_hash": result_hash,
                        "current_domain_validation_id": validation_id,
                        "revalidation_of_activated_projection": (
                            revalidating_activated_item
                        ),
                    }
                ),
                item_id,
                expected_version,
                item["status"],
            ],
        )
        if uow.cursor.rowcount != 1:
            raise KernelError(
                "MIGRATION_ITEM_VERSION_CONFLICT",
                "migration validation item compare-and-set failed",
            )
        checkpoint("after_validation_record")
        uow.repositories.operation_graph.record_event(
            {
                "event_id": str(uuid4()),
                "audit_id": str(uuid4()),
                "outbox_id": str(uuid4()),
                "aggregate_type": "authority_legacy_migration_validation",
                "aggregate_id": validation_id,
                "operation_id": operation_id,
                "project_id": str(operation[0]),
                "event_type": "legacy_migration.item.validated",
                "correlation_id": str(operation[5]),
                "causation_id": item_id,
                "payload": {
                    "operation_id": operation_id,
                    "migration_run_id": item["migration_run_id"],
                    "migration_item_id": item_id,
                    "migration_validation_id": validation_id,
                    "validation_version": validation_version,
                    "validation_status": validation_status.value,
                    "item_version": validated_item_version,
                    "result_hash": result_hash,
                },
            }
        )
        checkpoint("after_validation_outbox")
        return {
            "migration_item_id": item_id,
            "migration_validation_id": validation_id,
            "validation_version": validation_version,
            "validation_status": validation_status.value,
            "item_version": validated_item_version,
            "input_hash": snapshot["input_hash"],
            "result_hash": result_hash,
            "validator_name": descriptor.validator_name,
            "validator_version": descriptor.validator_version,
            "validator_implementation_hash": (
                descriptor.validator_implementation_hash
            ),
            "evidence": evidence,
        }


def load_validation_snapshot(
    uow: AuthorityUnitOfWork,
    migration_item_id: str,
    *,
    bound_item_version: int,
    lock_item: bool = False,
    application_build_id: str,
    commit_sha: str,
) -> dict[str, Any]:
    lock_clause = " FOR UPDATE OF item" if lock_item else ""
    uow.cursor.execute(
        """
        SELECT item.migration_run_id, item.project_id, item.workspace_id,
               item.source_asset_type, item.stable_business_key,
               item.source_hash, COALESCE(item.operation_id::text, ''),
               item.target_asset_id, item.target_asset_version_id,
               item.target_content_hash, validation_version.content,
               current_version.content_hash, current_asset.project_id,
               item.domain_adapter,
               item.target_materialization_level, item.item_version,
               item.status, validation_version.asset_id,
               validation_version.asset_version_id,
               validation_version.content_hash, validation_asset.project_id
        FROM authority_legacy_migration_item AS item
        JOIN authority_asset_version AS current_version
          ON current_version.asset_version_id=item.target_asset_version_id
        JOIN authority_asset AS current_asset
          ON current_asset.asset_id=current_version.asset_id
        LEFT JOIN authority_legacy_migration_validation AS activation_validation
          ON activation_validation.migration_validation_id=
             item.evidence->>'migration_validation_id'
         AND activation_validation.migration_item_id=item.migration_item_id
         AND activation_validation.migration_run_id=item.migration_run_id
        JOIN authority_asset_version AS validation_version
          ON validation_version.asset_version_id=COALESCE(
              NULLIF(item.evidence->>'archival_target_asset_version_id', ''),
              activation_validation.target_asset_version_id,
              item.target_asset_version_id
          )
        JOIN authority_asset AS validation_asset
          ON validation_asset.asset_id=validation_version.asset_id
        WHERE item.migration_item_id=%s
        """
        + lock_clause,
        [migration_item_id],
    )
    row = uow.cursor.fetchone()
    if row is None:
        raise KernelError(
            "MIGRATION_ITEM_NOT_FOUND",
            "migration validation item or target AssetVersion is missing",
        )
    if str(row[1]) != str(row[12]) or str(row[1]) != str(row[20]):
        raise KernelError(
            "CROSS_PROJECT_REFERENCE",
            "migration validation target belongs to another Project",
        )
    keys = (
        "migration_run_id",
        "project_id",
        "workspace_id",
        "source_asset_type",
        "stable_business_key",
        "source_hash",
        "import_operation_id",
        "target_asset_id",
        "target_asset_version_id",
        "target_content_hash",
        "content",
        "asset_version_content_hash",
        "asset_project_id",
        "domain_adapter",
        "target_materialization_level",
        "item_version",
        "status",
        "validation_source_asset_id",
        "validation_source_asset_version_id",
        "validation_source_content_hash",
        "validation_source_asset_project_id",
    )
    item = dict(zip(keys, row, strict=True))
    for key in keys:
        if key in {"content", "item_version"}:
            continue
        item[key] = str(item[key] or "")
    item["content"] = dict(item["content"])
    item["item_version"] = int(item["item_version"])

    uow.cursor.execute(
        """
        SELECT reference.reference_ordinal,
               reference.legacy_business_key, reference.relation_type,
               reference.optional, reference.resolution_status,
               COALESCE(reference.target_item_id, ''),
               COALESCE(reference.target_asset_version_id, ''),
               reference.target_domain_projection_id,
               COALESCE(target.source_asset_type, ''),
               COALESCE(target.project_id, ''),
               COALESCE(target.workspace_id, ''),
               COALESCE(target.materialization_level, ''),
               COALESCE(target.domain_projection_id, ''),
               COALESCE(target.item_version, 0)
        FROM authority_legacy_migration_reference AS reference
        LEFT JOIN authority_legacy_migration_item AS target
          ON target.migration_item_id=reference.target_item_id
        WHERE reference.source_item_id=%s
        ORDER BY reference.reference_ordinal
        """,
        [migration_item_id],
    )
    reference_rows = list(uow.cursor.fetchall())
    references = [
        {
            "ordinal": int(value[0]),
            "legacy_business_key": str(value[1]),
            "relation_type": str(value[2]),
            "optional": bool(value[3]),
            "resolution_status": str(value[4]),
            "target_item_id": str(value[5]),
            "target_asset_version_id": str(value[6]),
            "target_domain_projection_id": str(value[7] or ""),
            "target_source_asset_type": str(value[8]),
            "target_project_id": str(value[9]),
            "target_workspace_id": str(value[10]),
            "target_materialization_level": str(value[11]),
            "target_projection_id": str(value[12]),
            "target_item_version": int(value[13]),
        }
        for value in reference_rows
    ]
    cross_scope = [
        reference["ordinal"]
        for reference in references
        if reference["resolution_status"] == "RESOLVED"
        and (
            reference["target_project_id"] != item["project_id"]
            or reference["target_workspace_id"] != item["workspace_id"]
        )
    ]
    if cross_scope:
        raise KernelError(
            "CROSS_PROJECT_REFERENCE",
            f"migration references escape Project/Workspace scope: {cross_scope}",
        )
    unresolved_required = [
        reference["ordinal"]
        for reference in references
        if not reference["optional"]
        and reference["resolution_status"] != "RESOLVED"
    ]
    resolved = tuple(
        ResolvedMigrationReference(
            legacy_business_key=reference["legacy_business_key"],
            relation_type=reference["relation_type"],
            target_item_id=reference["target_item_id"],
            target_asset_version_id=reference["target_asset_version_id"],
            target_domain_projection_id=reference["target_domain_projection_id"],
            target_source_asset_type=reference["target_source_asset_type"],
        )
        for reference in references
        if reference["resolution_status"] == "RESOLVED"
    )
    effective_adapter = item["domain_adapter"] or (
        "novel_forge.legacy_migration.archival_asset_version.v1"
    )
    descriptor = validator_descriptor(
        effective_adapter,
        application_build_id=application_build_id,
        commit_sha=commit_sha,
    )
    reference_snapshot_hash = canonical_hash(references)
    dependency_projection_hash = canonical_hash(
        [
            {
                "target_item_id": reference["target_item_id"],
                "target_asset_version_id": reference["target_asset_version_id"],
                "target_materialization_level": reference[
                    "target_materialization_level"
                ],
                "target_projection_id": reference["target_projection_id"],
                "target_item_version": reference["target_item_version"],
            }
            for reference in references
        ]
    )
    input_hash = canonical_hash(
        {
            "migration_run_id": item["migration_run_id"],
            "migration_item_id": migration_item_id,
            "project_id": item["project_id"],
            "workspace_id": item["workspace_id"],
            "item_version": bound_item_version,
            "source_asset_type": item["source_asset_type"],
            "source_hash": item["source_hash"],
            "target_asset_id": item["target_asset_id"],
            "target_asset_version_id": item["target_asset_version_id"],
            "target_content_hash": item["target_content_hash"],
            "asset_version_content_hash": item["asset_version_content_hash"],
            "validation_source_asset_id": item["validation_source_asset_id"],
            "validation_source_asset_version_id": item[
                "validation_source_asset_version_id"
            ],
            "validation_source_content_hash": item[
                "validation_source_content_hash"
            ],
            "target_materialization_level": item[
                "target_materialization_level"
            ],
            "domain_adapter": descriptor.domain_adapter,
            "validator_version": descriptor.validator_version,
            "validator_implementation_hash": (
                descriptor.validator_implementation_hash
            ),
            "reference_snapshot_hash": reference_snapshot_hash,
            "dependency_projection_hash": dependency_projection_hash,
        }
    )
    context = DomainMigrationContext(
        migration_run_id=item["migration_run_id"],
        migration_item_id=migration_item_id,
        project_id=item["project_id"],
        workspace_id=item["workspace_id"],
        source_asset_type=item["source_asset_type"],
        stable_business_key=item["stable_business_key"],
        source_hash=item["source_hash"],
        import_operation_id=item["import_operation_id"],
        target_asset_id=item["target_asset_id"],
        target_asset_version_id=item["target_asset_version_id"],
        target_content_hash=item["target_content_hash"],
        content=item["content"],
        references=resolved,
        decision_id="",
        decision_reason="",
        actor_id="",
        item_version=item["item_version"],
    )
    return {
        "item": item,
        "context": context,
        "validator_descriptor": descriptor,
        "references": references,
        "unresolved_required_references": unresolved_required,
        "reference_snapshot_hash": reference_snapshot_hash,
        "dependency_projection_hash": dependency_projection_hash,
        "input_hash": input_hash,
    }


__all__ = [
    "DomainValidatorDescriptor",
    "LegacyMigrationValidationApplication",
    "LegacyMigrationValidationCommand",
    "MIGRATION_VALIDATION_DEFINITION_VERSION",
    "MIGRATION_VALIDATION_HANDLER",
    "MIGRATION_VALIDATION_OPERATION",
    "MigrationValidationStatus",
    "canonical_hash",
    "load_validation_snapshot",
    "validator_descriptor",
]

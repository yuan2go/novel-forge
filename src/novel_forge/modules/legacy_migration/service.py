"""Resumable Legacy import coordinator and reconciliation queries."""
from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.legacy_migration.application import (
    LegacyImportApplication,
    LegacyImportCommand,
)
from novel_forge.modules.legacy_migration.codecs import (
    DEFAULT_CODEC_REGISTRY,
    MigrationCodecNotFound,
)
from novel_forge.modules.legacy_migration.domain_adapters import (
    DomainMigrationAdapterRegistry,
    DomainMigrationContext,
    ResolvedMigrationReference,
)
from novel_forge.modules.legacy_migration.scanner import (
    LegacySnapshotRecord,
    scan_legacy_snapshot,
)
from novel_forge.modules.legacy_migration.references import (
    cyclic_dependency_nodes,
    relation_supported,
    topological_activation_order,
)
from novel_forge.modules.legacy_migration.state_machine import (
    MigrationArchivalState,
    MigrationCompletionFacts,
    MigrationDomainState,
    MigrationMaterializationLevel,
    MigrationPhase,
    MigrationPhaseCheckpoint,
    MigrationReferenceStatus,
    MigrationRunCompletionLevel,
    MigrationRunStatus,
    MigrationValidationScope,
    MigrationVerificationLevel,
    derive_migration_completion,
    require_phase_transition,
)
from novel_forge.modules.legacy_migration.validation import (
    LegacyMigrationValidationApplication,
    LegacyMigrationValidationCommand,
    load_validation_snapshot,
    validator_descriptor,
)
from novel_forge.modules.project_authority import (
    ProjectAuthorityApplication,
    ProjectAuthorityCommand,
    ProjectAuthorityQuery,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


class LegacyMigrationService:
    def __init__(
        self,
        database_url: str,
        *,
        application_build_id: str,
        commit_sha: str,
        actor_id: str = "authority-migration-operator",
        allow_fixture_domain_activation: bool = False,
    ) -> None:
        if not database_url:
            raise ValueError("PostgreSQL database_url is required")
        self.database_url = database_url
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha
        self.actor_id = actor_id
        self.allow_fixture_domain_activation = bool(
            allow_fixture_domain_activation
        )

    def import_snapshot(
        self,
        root: str | Path,
        *,
        dry_run: bool = False,
        resume: bool = True,
        require_read_only: bool = True,
        fault_after_items: int | None = None,
    ) -> dict[str, Any]:
        snapshot_root = Path(root).resolve()
        scan = scan_legacy_snapshot(snapshot_root)
        if dry_run:
            return {
                "mode": "DRY_RUN",
                "snapshot_hash": scan.snapshot_hash,
                "counts": scan.counts,
                "records": [asdict(record) for record in scan.records],
                "production_mutation_performed": False,
            }
        if require_read_only and snapshot_root.stat().st_mode & 0o222:
            raise KernelError(
                "LEGACY_SNAPSHOT_NOT_FROZEN",
                "non-dry-run import requires a read-only frozen snapshot root",
            )
        run_id = _stable_id("migration-run", scan.snapshot_hash)
        self._start_run(run_id, scan.snapshot_hash, str(snapshot_root), resume=resume)
        existing_run = self.status(run_id)
        if existing_run["status"] not in {
            MigrationRunStatus.IMPORT_RUNNING.value,
            MigrationRunStatus.FAILED.value,
        }:
            return existing_run
        project_workspaces = self._bootstrap_projects(scan.records, run_id)
        imported, quarantined, skipped = self._resume_counts(run_id)
        failed = 0
        importer = LegacyImportApplication(
            self.database_url,
            application_build_id=self.application_build_id,
            commit_sha=self.commit_sha,
        )
        for ordinal, record in enumerate(scan.records, start=1):
            if fault_after_items is not None and ordinal > fault_after_items:
                raise RuntimeError(
                    f"MIGRATION_FAULT_INJECTED after {fault_after_items} item(s)"
                )
            existing = self._existing_item(run_id, record.source_ref)
            if existing in {
                "IMPORTED", "QUALIFIED", "ACTIVATED", "NEEDS_REVIEW",
                "INELIGIBLE", "QUARANTINED", "SKIPPED_DUPLICATE",
            }:
                continue
            self._upsert_item(
                run_id,
                record,
                status="DISCOVERED",
                decision=record.decision,
                phase="SCAN",
            )
            self._complete_phase(
                run_id,
                record,
                phase=MigrationPhase.SCAN,
                next_phase=MigrationPhase.CLASSIFY,
                evidence={"source_ref": record.source_ref},
            )
            self._stage_references(run_id, record)
            if record.decision != "IMPORT":
                if record.status in {"QUARANTINED", "INELIGIBLE"}:
                    self._quarantine(run_id, record)
                    quarantined += 1
                else:
                    skipped += 1
                self._upsert_item(
                    run_id,
                    record,
                    status=record.status,
                    decision=record.decision,
                    error_code=record.error_code,
                    phase="QUARANTINE" if record.status in {"QUARANTINED", "INELIGIBLE"} else "RECONCILE",
                )
                self._quarantine_or_reconcile_phase(run_id, record)
                self._checkpoint(run_id, ordinal, imported, quarantined, skipped, failed)
                continue
            self._complete_phase(
                run_id,
                record,
                phase=MigrationPhase.CLASSIFY,
                next_phase=MigrationPhase.IMPORT_CANDIDATE,
                evidence={
                    "source_asset_type": record.source_asset_type,
                    "decision": record.decision,
                },
            )
            workspace_id = project_workspaces.get(record.project_id)
            if not workspace_id:
                missing = _with_error(record, "AUTHORITY_PROJECT_MISSING", "project shell was not imported")
                self._quarantine(run_id, missing)
                self._upsert_item(
                    run_id,
                    missing,
                    status="QUARANTINED",
                    decision="QUARANTINE",
                    error_code=missing.error_code,
                    phase="QUARANTINE",
                )
                self._quarantine_or_reconcile_phase(run_id, missing)
                quarantined += 1
                self._checkpoint(run_id, ordinal, imported, quarantined, skipped, failed)
                continue
            if record.source_asset_type == "project_workspace_state":
                self._complete_phase(
                    run_id,
                    record,
                    phase=MigrationPhase.IMPORT_CANDIDATE,
                    next_phase=MigrationPhase.SEMANTIC_CONVERT,
                    evidence={"project_shell": True},
                )
                detail = ProjectAuthorityQuery(self.database_url).require_project(
                    record.project_id
                )
                target_asset_id = self._asset_id_for_version(detail["asset_version_id"])
                self._upsert_item(
                    run_id,
                    record,
                    status="NEEDS_REVIEW",
                    decision="IMPORT",
                    target_asset_id=target_asset_id,
                    target_asset_version_id=detail["asset_version_id"],
                    phase="QUALIFY",
                    target_asset_type="project_record",
                    codec_name="native:project_workspace_state->project_record",
                    codec_version="3.0.0",
                    target_content_hash=detail["content_hash"],
                    evidence={
                        "source_hash": record.source_hash,
                        "target_content_hash": detail["content_hash"],
                        "activation_decision": "NEEDS_REVIEW",
                        "replayed": False,
                        "native_project_bootstrap": True,
                        "bootstrap_shell_is_not_domain_activation": True,
                    },
                    materialization_level=MigrationMaterializationLevel.ARCHIVAL_NATIVE,
                    target_materialization_level=MigrationMaterializationLevel.DOMAIN_NATIVE,
                    domain_adapter="novel_forge.legacy_migration.project_authority.v1",
                    domain_validator="novel_forge.project_authority.domain_validator.v1",
                    projection_strategy="project_authority.authority_projection.v1",
                    activation_strategy="project_authority.explicit_command.v1",
                    domain_projection_id="",
                )
                self._complete_successful_item_phases(
                    run_id,
                    record,
                    output_hash=str(detail["content_hash"]),
                    activated=False,
                    awaiting_domain_activation=True,
                    evidence={
                        "project_bootstrap_shell_id": record.project_id,
                        "domain_activation_pending": True,
                    },
                )
                imported += 1
                self._checkpoint(run_id, ordinal, imported, quarantined, skipped, failed)
                continue
            try:
                DEFAULT_CODEC_REGISTRY.resolve(record.source_asset_type)
            except MigrationCodecNotFound as exc:
                unsupported = _with_error(
                    record, "UNSUPPORTED_SOURCE_TYPE", str(exc)
                )
                self._quarantine(run_id, unsupported)
                self._upsert_item(
                    run_id,
                    unsupported,
                    status="QUARANTINED",
                    decision="QUARANTINE",
                    error_code=unsupported.error_code,
                    phase="QUARANTINE",
                )
                self._quarantine_or_reconcile_phase(run_id, unsupported)
                quarantined += 1
                self._checkpoint(run_id, ordinal, imported, quarantined, skipped, failed)
                continue
            try:
                self._complete_phase(
                    run_id,
                    record,
                    phase=MigrationPhase.IMPORT_CANDIDATE,
                    next_phase=MigrationPhase.SEMANTIC_CONVERT,
                    evidence={"codec_source_type": record.source_asset_type},
                )
                result = importer.execute(
                    LegacyImportCommand(
                        project_id=record.project_id,
                        workspace_id=workspace_id,
                        actor_id=self.actor_id,
                        trace_id=f"trace:{run_id}",
                        correlation_id=f"correlation:{run_id}",
                        idempotency_key=(
                            f"legacy-import:{record.project_id}:{record.stable_business_key}"
                        ),
                        source_ref=record.source_ref,
                        source_hash=record.source_hash,
                        source_asset_type=record.source_asset_type,
                        stable_business_key=record.stable_business_key,
                        payload=dict(record.payload or {}),
                        references=tuple(
                            reference.to_contract()
                            for reference in record.references
                        ),
                    )
                )
                self._upsert_item(
                    run_id,
                    record,
                    status=(
                        "ACTIVATED"
                        if result["activation_decision"] == "ACTIVATE"
                        else "NEEDS_REVIEW"
                    ),
                    decision="MIGRATE_NATIVE",
                    operation_id=result["operation_id"],
                    target_asset_id=result["asset_id"],
                    target_asset_version_id=result["asset_version_id"],
                    phase="RECONCILE",
                    target_asset_type=result["target_asset_type"],
                    codec_name=result["codec_name"],
                    codec_version=result["codec_version"],
                    target_content_hash=result["content_hash"],
                    evidence={
                        "source_hash": record.source_hash,
                        "target_content_hash": result["content_hash"],
                        "replayed": result["replayed"],
                        "source_asset_type": result["source_asset_type"],
                        "target_asset_type": result["target_asset_type"],
                        "codec_name": result["codec_name"],
                        "codec_version": result["codec_version"],
                        "lifecycle": result["lifecycle"],
                        "eligibility": result["eligibility"],
                        "activation_decision": result["activation_decision"],
                        "reconciliation": result["reconciliation"],
                    },
                    materialization_level=MigrationMaterializationLevel(
                        result["materialization_level"]
                    ),
                    target_materialization_level=MigrationMaterializationLevel(
                        result["target_materialization_level"]
                    ),
                    domain_adapter=result["domain_adapter"],
                    domain_validator=result["domain_validator"],
                    projection_strategy=result["projection_strategy"],
                    activation_strategy=result["activation_strategy"],
                    resolved_workspace_id=workspace_id,
                )
                self._complete_successful_item_phases(
                    run_id,
                    record,
                    output_hash=str(result["content_hash"]),
                    activated=False,
                    awaiting_domain_activation=(
                        result["target_materialization_level"]
                        == MigrationMaterializationLevel.DOMAIN_NATIVE.value
                    ),
                    evidence={
                        "codec_name": result["codec_name"],
                        "materialization_level": result["materialization_level"],
                    },
                )
                imported += 1
            except Exception as exc:
                conflict = _with_error(
                    record,
                    "IMPORT_OPERATION_FAILED",
                    f"{type(exc).__name__}: {exc}",
                )
                self._quarantine(run_id, conflict)
                self._upsert_item(
                    run_id,
                    conflict,
                    status="FAILED",
                    decision="QUARANTINE",
                    error_code=conflict.error_code,
                    phase="QUARANTINE",
                )
                self._quarantine_or_reconcile_phase(run_id, conflict)
                failed += 1
            self._checkpoint(run_id, ordinal, imported, quarantined, skipped, failed)
        self._resolve_references(run_id, scan.records)
        imported, quarantined, skipped = self._resume_counts(run_id)
        failed = self._failed_count(run_id)
        status = self._derive_import_run_status(
            run_id,
            failed=failed,
            quarantined=quarantined,
        )
        self._finish_run(run_id, status, imported, quarantined, skipped, failed)
        return self.status(run_id)

    def status(self, migration_run_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT migration_run_id, source_kind, source_hash, status, report,
                       workspace_id, snapshot_hash, mode, idempotency_key,
                       cursor_state, counts, phase, reconciliation,
                       checkpoint_hash, created_at, updated_at, finished_at,
                       run_completion_level, required_verification_level
                FROM authority_migration_run WHERE migration_run_id = %s
                """,
                [migration_run_id],
            )
            row = uow.cursor.fetchone()
            if row is None:
                raise KernelError("MIGRATION_RUN_NOT_FOUND", "migration run does not exist")
            uow.cursor.execute(
                """
                SELECT status, COUNT(*) FROM authority_legacy_migration_item
                WHERE migration_run_id = %s GROUP BY status ORDER BY status
                """,
                [migration_run_id],
            )
            item_counts = {status: int(count) for status, count in uow.cursor.fetchall()}
        return {
            "migration_run_id": row[0],
            "source_kind": row[1],
            "source_hash": row[2],
            "status": row[3],
            "report": row[4],
            "workspace_id": row[5],
            "snapshot_hash": row[6],
            "mode": row[7],
            "idempotency_key": row[8],
            "cursor_state": row[9],
            "counts": row[10],
            "phase": row[11],
            "reconciliation": row[12],
            "checkpoint_hash": row[13],
            "created_at": str(row[14]),
            "updated_at": str(row[15]),
            "finished_at": str(row[16]) if row[16] else None,
            "run_completion_level": str(row[17]),
            "required_verification_level": str(row[18]),
            "item_counts": item_counts,
        }

    def validate_domain_item(
        self, migration_item_id: str, *, expected_item_version: int
    ) -> dict[str, Any]:
        context, _adapter_name, _target_level = self._domain_context(
            migration_item_id
        )
        if context.item_version != expected_item_version:
            raise KernelError(
                "MIGRATION_ITEM_VERSION_CONFLICT",
                "domain validation expected item version is stale",
            )
        result = LegacyMigrationValidationApplication(
            self.database_url,
            application_build_id=self.application_build_id,
            commit_sha=self.commit_sha,
        ).execute(
            LegacyMigrationValidationCommand(
                migration_run_id=context.migration_run_id,
                migration_item_id=migration_item_id,
                project_id=context.project_id,
                workspace_id=context.workspace_id,
                actor_id=self.actor_id,
                expected_item_version=expected_item_version,
                source_hash=context.source_hash,
                target_asset_version_id=context.target_asset_version_id,
                idempotency_key=(
                    f"migration:validate:{migration_item_id}:"
                    f"{expected_item_version}:{context.source_hash}"
                ),
                trace_id=f"trace:{context.migration_run_id}",
                correlation_id=f"migration:{context.migration_run_id}",
            )
        )
        return result

    def activate_domain_item(
        self,
        migration_item_id: str,
        *,
        expected_item_version: int,
    ) -> dict[str, Any]:
        # Domain Authority applications open their own UnitOfWork boundaries.
        # This explicit coordinated scope makes those boundaries nested
        # savepoints on the same connection, retaining one atomic activation
        # transaction without requiring a second migration-pool connection.
        with AuthorityUnitOfWork(
            self.database_url, coordinate_nested=True
        ) as uow:
            uow.cursor.execute(
                """
                SELECT migration_run_id
                FROM authority_legacy_migration_item
                WHERE migration_item_id=%s
                """,
                [migration_item_id],
            )
            run_row = uow.cursor.fetchone()
            if run_row is None:
                raise KernelError(
                    "MIGRATION_ITEM_NOT_FOUND",
                    "domain migration item does not exist",
                )
            uow.cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                [str(run_row[0])],
            )
            context, adapter_name, target_level = self._domain_context(
                migration_item_id,
                uow=uow,
                lock_activation_scope=True,
            )
            if target_level != MigrationMaterializationLevel.DOMAIN_NATIVE.value:
                raise KernelError(
                    "DOMAIN_MIGRATION_NOT_REQUIRED",
                    "ARCHIVAL_NATIVE items cannot be activated as domain projections",
                )
            if context.item_version != expected_item_version:
                raise KernelError(
                    (
                        "MIGRATION_DECISION_STALE"
                        if context.decision_id
                        else "MIGRATION_ITEM_VERSION_CONFLICT"
                    ),
                    "domain activation expected item version or decision is stale",
                )
            if not context.decision_id:
                raise KernelError(
                    "MIGRATION_APPROVAL_REQUIRED",
                    "domain activation requires an independent approved decision",
                )
            validation_binding = self._require_activation_validation(
                context,
                expected_item_version=expected_item_version,
                uow=uow,
            )
            self._require_domain_dependencies_activated(context, uow=uow)
            context = replace(
                context,
                migration_validation_id=str(
                    validation_binding["migration_validation_id"]
                ),
                validator_result_hash=str(validation_binding["result_hash"]),
                validator_version=str(validation_binding["validator_version"]),
            )
            adapter = DomainMigrationAdapterRegistry(
                self.database_url,
                application_build_id=self.application_build_id,
                commit_sha=self.commit_sha,
                allow_fixture_activation=self.allow_fixture_domain_activation,
            ).resolve(adapter_name)
            # The migration item, validation, decision, references, and
            # dependency projections remain locked while the domain Authority
            # commits. This closes the validation/activation TOCTOU window.
            result = adapter.activate(context)
            uow.cursor.execute(
                """
                UPDATE authority_legacy_migration_item
                SET materialization_level='DOMAIN_NATIVE',
                    materialization_stage='DOMAIN',
                    domain_state='DOMAIN_ACTIVATED',
                    status='ACTIVATED',
                    target_asset_id=%s,
                    target_asset_version_id=%s,
                    target_content_hash=%s,
                    domain_projection_id=%s,
                    evidence=evidence || %s,
                    item_version=item_version+1,
                    updated_at=NOW()
                WHERE migration_item_id=%s AND item_version=%s
                  AND status='QUALIFIED'
                """,
                [
                    result.target_asset_id,
                    result.target_asset_version_id,
                    result.target_content_hash,
                    result.domain_projection_id,
                    Jsonb(
                        {
                            "domain_activation": result.evidence,
                            "archival_target_asset_id": context.target_asset_id,
                            "archival_target_asset_version_id": (
                                context.target_asset_version_id
                            ),
                            "archival_target_content_hash": (
                                context.target_content_hash
                            ),
                            "domain_activation_operation_id": (
                                result.activation_operation_id
                            ),
                            "migration_validation_id": context.migration_validation_id,
                            "validator_result_hash": context.validator_result_hash,
                        }
                    ),
                    migration_item_id,
                    expected_item_version,
                ],
            )
            if uow.cursor.rowcount != 1:
                raise KernelError(
                    "MIGRATION_ACTIVATION_RECONCILIATION_REQUIRED",
                    "domain command committed but migration item CAS failed; reconcile",
                )
            uow.cursor.execute(
                """
                UPDATE authority_legacy_migration_reference
                SET target_asset_id=%s,
                    target_asset_version_id=%s,
                    target_domain_projection_id=%s,
                    evidence=evidence || %s,
                    updated_at=NOW()
                WHERE target_item_id=%s AND resolution_status='RESOLVED'
                """,
                [
                    result.target_asset_id,
                    result.target_asset_version_id,
                    result.domain_projection_id,
                    Jsonb(
                        {
                            "domain_target_rebound": True,
                            "activation_operation_id": (
                                result.activation_operation_id
                            ),
                        }
                    ),
                    migration_item_id,
                ],
            )
            uow.commit()
        self._mark_run_domain_activation_progress(context.migration_run_id)
        record = self._record_for_item(migration_item_id)
        self._complete_phase(
            context.migration_run_id,
            record,
            phase=MigrationPhase.ACTIVATE,
            next_phase=MigrationPhase.RECONCILE,
            output_hash=result.target_content_hash,
            evidence={
                "domain_projection_id": result.domain_projection_id,
                "activation_operation_id": result.activation_operation_id,
                "independent_decision_id": context.decision_id,
                "migration_validation_id": context.migration_validation_id,
                "validator_result_hash": context.validator_result_hash,
                "validator_version": context.validator_version,
            },
        )
        post_activation_context, _adapter_name, _target_level = self._domain_context(
            migration_item_id
        )
        post_activation_validation = self.validate_domain_item(
            migration_item_id,
            expected_item_version=post_activation_context.item_version,
        )
        if post_activation_validation["validation_status"] != "PASS":
            raise KernelError(
                "MIGRATION_POST_ACTIVATION_VALIDATION_FAILED",
                "activated domain projection failed current server validation",
            )
        return {
            "migration_item_id": migration_item_id,
            "materialization_level": MigrationMaterializationLevel.DOMAIN_NATIVE.value,
            "status": "ACTIVATED",
            "domain_projection_id": result.domain_projection_id,
            "target_asset_version_id": result.target_asset_version_id,
            "activation_operation_id": result.activation_operation_id,
            "item_version": int(post_activation_validation["item_version"]),
            "evidence": {
                **result.evidence,
                "post_activation_validation_id": post_activation_validation[
                    "migration_validation_id"
                ],
                "post_activation_validation_result_hash": (
                    post_activation_validation["result_hash"]
                ),
            },
        }

    def _quarantine_dependency_cycles(
        self,
        run_id: str,
        records_by_item: dict[str, LegacySnapshotRecord],
    ) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT migration_item_id
                FROM authority_legacy_migration_item
                WHERE migration_run_id=%s
                  AND target_materialization_level='DOMAIN_NATIVE'
                  AND status NOT IN ('QUARANTINED','INELIGIBLE','FAILED')
                """,
                [run_id],
            )
            nodes = tuple(str(row[0]) for row in uow.cursor.fetchall())
            uow.cursor.execute(
                """
                SELECT source_item_id, target_item_id
                FROM authority_legacy_migration_reference
                WHERE migration_run_id=%s AND resolution_status='RESOLVED'
                  AND target_item_id IS NOT NULL
                  AND NOT optional
                """,
                [run_id],
            )
            dependencies: dict[str, list[str]] = {}
            for source_item_id, target_item_id in uow.cursor.fetchall():
                dependencies.setdefault(str(source_item_id), []).append(
                    str(target_item_id)
                )
            cycle_nodes = cyclic_dependency_nodes(
                nodes=nodes,
                dependencies=dependencies,
            )
            if not cycle_nodes:
                return
            uow.cursor.execute(
                """
                UPDATE authority_legacy_migration_reference
                SET resolution_status='CONFLICT',
                    evidence=evidence || %s, updated_at=NOW()
                WHERE migration_run_id=%s
                  AND source_item_id=ANY(%s)
                  AND target_item_id=ANY(%s)
                """,
                [
                    Jsonb(
                        {
                            "error_code": "MIGRATION_DEPENDENCY_CYCLE",
                            "cycle_item_ids": sorted(cycle_nodes),
                        }
                    ),
                    run_id,
                    list(cycle_nodes),
                    list(cycle_nodes),
                ],
            )
            uow.cursor.execute(
                """
                UPDATE authority_legacy_migration_item
                SET status='QUARANTINED', decision='QUARANTINE',
                    error_code='MIGRATION_DEPENDENCY_CYCLE',
                    error_detail='Domain activation dependency graph contains a cycle',
                    reference_state='CONFLICT',
                    archival_state='REFERENCES_PENDING', updated_at=NOW()
                WHERE migration_run_id=%s AND migration_item_id=ANY(%s)
                """,
                [run_id, list(cycle_nodes)],
            )
            uow.commit()
        for item_id in cycle_nodes:
            record = records_by_item.get(item_id)
            if record is None:
                continue
            failed_record = _with_error(
                record,
                "MIGRATION_DEPENDENCY_CYCLE",
                "Domain activation dependency graph contains a cycle",
            )
            self._quarantine(run_id, failed_record)
            self._quarantine_or_reconcile_phase(run_id, failed_record)

    def domain_activation_order(
        self,
        migration_run_id: str,
        *,
        uow: AuthorityUnitOfWork | None = None,
        lock_graph: bool = False,
    ) -> list[str]:
        if uow is None:
            with AuthorityUnitOfWork(self.database_url) as owned_uow:
                return self.domain_activation_order(
                    migration_run_id,
                    uow=owned_uow,
                    lock_graph=lock_graph,
                )
        item_lock = " FOR SHARE" if lock_graph else ""
        reference_lock = " FOR SHARE" if lock_graph else ""
        uow.cursor.execute(
                """
                SELECT migration_item_id
                FROM authority_legacy_migration_item
                WHERE migration_run_id=%s
                  AND target_materialization_level='DOMAIN_NATIVE'
                  AND status NOT IN ('QUARANTINED','INELIGIBLE','FAILED')
                ORDER BY migration_item_id
                """
                + item_lock,
                [migration_run_id],
        )
        nodes = tuple(str(row[0]) for row in uow.cursor.fetchall())
        uow.cursor.execute(
                """
                SELECT source_item_id, target_item_id
                FROM authority_legacy_migration_reference
                WHERE migration_run_id=%s AND resolution_status='RESOLVED'
                  AND target_item_id IS NOT NULL
                  AND NOT optional
                ORDER BY source_item_id, reference_ordinal
                """
                + reference_lock,
                [migration_run_id],
        )
        dependencies: dict[str, list[str]] = {}
        for source_item_id, target_item_id in uow.cursor.fetchall():
            dependencies.setdefault(str(source_item_id), []).append(
                str(target_item_id)
            )
        try:
            return topological_activation_order(
                nodes=nodes,
                dependencies=dependencies,
            )
        except ValueError as exc:
            raise KernelError(
                "MIGRATION_DEPENDENCY_CYCLE",
                str(exc),
            ) from exc

    def _require_domain_dependencies_activated(
        self,
        context: DomainMigrationContext,
        *,
        uow: AuthorityUnitOfWork | None = None,
    ) -> None:
        if uow is None:
            with AuthorityUnitOfWork(self.database_url) as owned_uow:
                self._require_domain_dependencies_activated(
                    context,
                    uow=owned_uow,
                )
                return
        order = self.domain_activation_order(
            context.migration_run_id,
            uow=uow,
            lock_graph=True,
        )
        if context.migration_item_id not in order:
            raise KernelError(
                "MIGRATION_ACTIVATION_PLAN_CONFLICT",
                "migration item is absent from the domain activation graph",
            )
        uow.cursor.execute(
                """
                SELECT target.migration_item_id, target.source_asset_type,
                       target.target_materialization_level,
                       target.materialization_level, target.domain_state
                FROM authority_legacy_migration_reference AS reference
                JOIN authority_legacy_migration_item AS target
                  ON target.migration_item_id=reference.target_item_id
                WHERE reference.source_item_id=%s
                  AND reference.resolution_status='RESOLVED'
                  AND NOT reference.optional
                ORDER BY reference.reference_ordinal
                FOR SHARE OF reference, target
                """,
                [context.migration_item_id],
        )
        dependencies = list(uow.cursor.fetchall())
        for item_id, source_type, target_level, materialization_level, state in dependencies:
            if (
                str(target_level) == MigrationMaterializationLevel.DOMAIN_NATIVE.value
                and (
                    str(materialization_level)
                    != MigrationMaterializationLevel.DOMAIN_NATIVE.value
                    or str(state)
                    not in {
                        MigrationDomainState.DOMAIN_ACTIVATED.value,
                        MigrationDomainState.DOMAIN_RECONCILED.value,
                    }
                )
            ):
                raise KernelError(
                    "MIGRATION_DEPENDENCY_NOT_ACTIVATED",
                    f"{source_type} dependency {item_id} is not Domain Activated",
                )

    def _require_activation_validation(
        self,
        context: DomainMigrationContext,
        *,
        expected_item_version: int,
        uow: AuthorityUnitOfWork | None = None,
    ) -> dict[str, Any]:
        if uow is None:
            with AuthorityUnitOfWork(self.database_url) as owned_uow:
                return self._require_activation_validation(
                    context,
                    expected_item_version=expected_item_version,
                    uow=owned_uow,
                )
        uow.cursor.execute(
            """
            SELECT decision.migration_validation_id,
                   decision.validation_result_hash,
                   validation.migration_run_id,
                   validation.migration_item_id,
                   validation.item_version,
                   validation.source_hash,
                   validation.target_asset_version_id,
                   validation.domain_adapter,
                   validation.validator_name,
                   validation.validator_version,
                   validation.validator_implementation_hash,
                   validation.input_hash, validation.result_hash,
                   validation.reference_snapshot_hash,
                   validation.dependency_projection_hash,
                   validation.status
            FROM authority_legacy_migration_decision AS decision
            JOIN authority_legacy_migration_validation AS validation
              ON validation.migration_validation_id=decision.migration_validation_id
            WHERE decision.migration_decision_id=%s
              AND decision.migration_item_id=%s
              AND decision.decision='APPROVE'
            FOR SHARE OF decision, validation
            """,
            [context.decision_id, context.migration_item_id],
        )
        row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "MIGRATION_VALIDATION_REQUIRED",
                "approved migration decision is not bound to validation",
            )
        validation_item_version = int(row[4])
        if expected_item_version != validation_item_version + 1:
            raise KernelError(
                "MIGRATION_DECISION_STALE",
                "item version no longer has the validated approval relationship",
            )
        snapshot = load_validation_snapshot(
            uow,
            context.migration_item_id,
            bound_item_version=validation_item_version,
            lock_item=True,
            application_build_id=self.application_build_id,
            commit_sha=self.commit_sha,
        )
        descriptor = snapshot["validator_descriptor"]
        expected_scope = (
            context.migration_run_id,
            context.migration_item_id,
            context.source_hash,
            context.target_asset_version_id,
            snapshot["item"]["domain_adapter"],
        )
        actual_scope = (
            str(row[2]),
            str(row[3]),
            str(row[5]),
            str(row[6]),
            str(row[7]),
        )
        if expected_scope != actual_scope:
            raise KernelError(
                "MIGRATION_VALIDATION_SCOPE_CONFLICT",
                "activation validation scope changed after approval",
            )
        if str(row[15]) != "PASS":
            raise KernelError(
                "MIGRATION_VALIDATION_NOT_PASSING",
                "activation requires a non-revoked PASS validation",
            )
        if str(row[0]) == "" or str(row[1]) != str(row[12]):
            raise KernelError(
                "MIGRATION_DECISION_VALIDATION_CONFLICT",
                "decision validation result binding is invalid",
            )
        if snapshot["unresolved_required_references"]:
            raise KernelError(
                "MIGRATION_REQUIRED_REFERENCE_UNRESOLVED",
                "required references changed after approval",
            )
        if (
            str(row[8]) != descriptor.validator_name
            or str(row[9]) != descriptor.validator_version
            or str(row[10]) != descriptor.validator_implementation_hash
            or str(row[11]) != snapshot["input_hash"]
            or str(row[13]) != snapshot["reference_snapshot_hash"]
            or str(row[14]) != snapshot["dependency_projection_hash"]
        ):
            raise KernelError(
                "MIGRATION_VALIDATION_STALE",
                "activation inputs, dependencies, or validator changed",
            )
        return {
            "migration_validation_id": str(row[0]),
            "result_hash": str(row[12]),
            "validator_version": str(row[9]),
        }

    def _domain_context(
        self,
        migration_item_id: str,
        *,
        uow: AuthorityUnitOfWork | None = None,
        lock_activation_scope: bool = False,
    ) -> tuple[DomainMigrationContext, str, str]:
        if uow is None:
            with AuthorityUnitOfWork(self.database_url) as owned_uow:
                return self._domain_context(
                    migration_item_id,
                    uow=owned_uow,
                    lock_activation_scope=lock_activation_scope,
                )
        item_lock = (
            " FOR UPDATE OF item"
            if lock_activation_scope
            else ""
        )
        reference_lock = (
            " FOR SHARE OF reference, target" if lock_activation_scope else ""
        )
        uow.cursor.execute(
            """
            SELECT item.migration_run_id, item.project_id,
                   item.workspace_id, item.source_asset_type,
                   item.stable_business_key, item.source_hash,
                   COALESCE(item.operation_id::text, ''),
                   item.target_asset_id, item.target_asset_version_id,
                   item.target_content_hash, version.content,
                   item.domain_adapter,
                   item.target_materialization_level,
                   item.item_version, item.status,
                   COALESCE(decision.migration_decision_id, ''),
                   COALESCE(decision.reason, ''),
                   COALESCE(decision.actor_id, %s)
            FROM authority_legacy_migration_item AS item
            JOIN authority_asset_version AS version
              ON version.asset_version_id=item.target_asset_version_id
            LEFT JOIN LATERAL (
                SELECT migration_decision_id, reason, actor_id, decision
                FROM authority_legacy_migration_decision
                WHERE migration_item_id=item.migration_item_id
                ORDER BY decision_version DESC LIMIT 1
            ) AS decision ON decision.decision='APPROVE'
            WHERE item.migration_item_id=%s
            """
            + item_lock,
            [self.actor_id, migration_item_id],
        )
        row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "MIGRATION_ITEM_NOT_FOUND",
                "domain migration item or target AssetVersion is missing",
            )
        uow.cursor.execute(
            """
            SELECT reference.legacy_business_key,
                   reference.relation_type,
                   reference.target_item_id,
                   reference.target_asset_version_id,
                   reference.target_domain_projection_id,
                   target.source_asset_type
            FROM authority_legacy_migration_reference AS reference
            JOIN authority_legacy_migration_item AS target
              ON target.migration_item_id=reference.target_item_id
            WHERE reference.source_item_id=%s
              AND reference.resolution_status='RESOLVED'
            ORDER BY reference.reference_ordinal
            """
            + reference_lock,
            [migration_item_id],
        )
        references = tuple(
            ResolvedMigrationReference(
                legacy_business_key=str(item[0]),
                relation_type=str(item[1]),
                target_item_id=str(item[2]),
                target_asset_version_id=str(item[3]),
                target_domain_projection_id=str(item[4] or ""),
                target_source_asset_type=str(item[5]),
            )
            for item in uow.cursor.fetchall()
        )
        reviewable_statuses = {"NEEDS_REVIEW", "QUALIFIED"}
        if not lock_activation_scope:
            reviewable_statuses.add("ACTIVATED")
        if str(row[14]) not in reviewable_statuses:
            raise KernelError(
                "MIGRATION_ITEM_NOT_REVIEWABLE",
                f"domain migration item is in {row[14]}",
            )
        context = DomainMigrationContext(
            migration_run_id=str(row[0]),
            migration_item_id=migration_item_id,
            project_id=str(row[1]),
            workspace_id=str(row[2]),
            source_asset_type=str(row[3]),
            stable_business_key=str(row[4]),
            source_hash=str(row[5]),
            import_operation_id=str(row[6]),
            target_asset_id=str(row[7]),
            target_asset_version_id=str(row[8]),
            target_content_hash=str(row[9]),
            content=dict(row[10]),
            references=references,
            decision_id=str(row[15]),
            decision_reason=str(row[16]),
            actor_id=str(row[17]),
            item_version=int(row[13]),
        )
        return context, str(row[11]), str(row[12])

    def _record_for_item(self, migration_item_id: str) -> LegacySnapshotRecord:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT source_ref, source_category, source_hash,
                       stable_business_key, project_id, workspace_id,
                       source_asset_type, status
                FROM authority_legacy_migration_item
                WHERE migration_item_id=%s
                """,
                [migration_item_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "MIGRATION_ITEM_NOT_FOUND", "migration item does not exist"
            )
        return LegacySnapshotRecord(
            source_ref=str(row[0]),
            category=str(row[1]),
            source_hash=str(row[2]),
            size_bytes=0,
            stable_business_key=str(row[3]),
            project_id=str(row[4]),
            workspace_id=str(row[5]),
            source_asset_type=str(row[6]),
            payload=None,
            references=(),
            decision="IMPORT",
            status=str(row[7]),
        )

    def verify(
        self,
        migration_run_id: str,
        *,
        snapshot_root: str | Path | None = None,
        required_level: MigrationVerificationLevel | str = (
            MigrationVerificationLevel.ARCHIVAL_NATIVE
        ),
    ) -> dict[str, Any]:
        # Verification is a single run-consistent observation. Every mutable
        # migration command (validation, decision, activation) takes the same
        # transaction-scoped advisory lock before touching Item/Validation
        # state, so none can commit between freshness checks and the persisted
        # reconciliation result. Coordinated nested UnitOfWorks reuse this
        # transaction and retain compatibility with a max_size=1 pool.
        with AuthorityUnitOfWork(
            self.database_url, coordinate_nested=True
        ) as verification_uow:
            verification_uow.cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                [migration_run_id],
            )
            result = self._verify_locked(
                migration_run_id,
                snapshot_root=snapshot_root,
                required_level=required_level,
            )
            verification_uow.commit()
            return result

    def _verify_locked(
        self,
        migration_run_id: str,
        *,
        snapshot_root: str | Path | None,
        required_level: MigrationVerificationLevel | str,
    ) -> dict[str, Any]:
        verification_level = MigrationVerificationLevel(required_level)
        self._refresh_current_activated_validations(migration_run_id)
        status = self.status(migration_run_id)
        # Every verification level is a source-to-target proof.  Omitting the
        # source snapshot can report durable run status, but can never produce
        # a PASS by implicitly trusting the recorded hash.
        hash_matches = False
        actual_hash = status["snapshot_hash"]
        if snapshot_root is not None:
            actual_hash = scan_legacy_snapshot(snapshot_root).snapshot_hash
            hash_matches = actual_hash == status["snapshot_hash"]
        counts = status["item_counts"]
        terminal = sum(
            counts.get(value, 0)
            for value in (
                "IMPORTED", "QUALIFIED", "ACTIVATED", "NEEDS_REVIEW", "INELIGIBLE", "QUARANTINED",
                "SKIPPED_DUPLICATE", "FAILED",
            )
        )
        total = sum(counts.values())
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT
                    COUNT(DISTINCT item.migration_item_id)
                        FILTER (WHERE target_asset_version_id IS NOT NULL),
                    COUNT(DISTINCT target_asset_version_id)
                        FILTER (WHERE target_asset_version_id IS NOT NULL),
                    COUNT(DISTINCT item.migration_item_id) FILTER (
                        WHERE target_asset_version_id IS NOT NULL
                          AND target_content_hash = version.content_hash
                    ),
                    COUNT(DISTINCT item.migration_item_id) FILTER (
                        WHERE target_asset_version_id IS NOT NULL
                          AND qualification.asset_version_id IS NOT NULL
                    ),
                    COUNT(DISTINCT item.migration_item_id) FILTER (
                        WHERE item.status = 'ACTIVATED'
                          AND version.lifecycle = 'ACTIVE'
                          AND version.eligibility = 'ELIGIBLE'
                    )
                FROM authority_legacy_migration_item AS item
                LEFT JOIN authority_asset_version AS version
                  ON version.asset_version_id = item.target_asset_version_id
                LEFT JOIN authority_asset_qualification AS qualification
                  ON qualification.asset_version_id = item.target_asset_version_id
                WHERE item.migration_run_id = %s
                """,
                [migration_run_id],
            )
            target_count, distinct_targets, hash_count, qualification_count, active_count = (
                int(value) for value in uow.cursor.fetchone()
            )
            uow.cursor.execute(
                """
                SELECT
                    COUNT(DISTINCT item.operation_id),
                    COUNT(DISTINCT audit.operation_id),
                    COUNT(DISTINCT outbox.payload->>'operation_id')
                FROM authority_legacy_migration_item AS item
                LEFT JOIN audit_log AS audit ON audit.operation_id = item.operation_id
                LEFT JOIN outbox_event AS outbox
                  ON outbox.payload->>'operation_id' = item.operation_id
                 AND outbox.topic = 'legacy_migration.asset.converted'
                WHERE item.migration_run_id = %s AND item.operation_id IS NOT NULL
                """,
                [migration_run_id],
            )
            operation_count, audited_operation_count, outbox_operation_count = (
                int(value) for value in uow.cursor.fetchone()
            )
            uow.cursor.execute(
                """
                SELECT COUNT(*),
                       COUNT(*) FILTER (WHERE resolution_status='RESOLVED'),
                       COUNT(*) FILTER (WHERE resolution_status='UNRESOLVED'),
                       COUNT(*) FILTER (
                           WHERE resolution_status IN (
                               'QUARANTINED','OPTIONAL_MISSING','CONFLICT'
                           )
                       ),
                       COUNT(*) FILTER (
                           WHERE NOT optional
                             AND resolution_status <> 'RESOLVED'
                       )
                FROM authority_legacy_migration_reference
                WHERE migration_run_id=%s
                """,
                [migration_run_id],
            )
            (
                reference_count,
                resolved_reference_count,
                unresolved_reference_count,
                closed_reference_exception_count,
                required_reference_failures,
            ) = (int(value) for value in uow.cursor.fetchone())
            uow.cursor.execute(
                """
                SELECT item.migration_item_id, item.item_version,
                       item.domain_adapter, item.source_hash,
                       COALESCE(
                           item.evidence->>'current_domain_validation_id',
                           item.evidence->>'migration_validation_id',
                           item.evidence->>'latest_domain_validation_id',
                           ''
                       ) AS bound_validation_id,
                       COALESCE(latest.migration_validation_id, ''),
                       COALESCE(latest.status, ''),
                       COALESCE(latest.source_hash, ''),
                       COALESCE(latest.domain_adapter, ''),
                       COALESCE(latest.validator_name, ''),
                       COALESCE(latest.validator_version, ''),
                       COALESCE(latest.validator_implementation_hash, ''),
                       COALESCE(latest.item_version, 0),
                       COALESCE(latest.input_hash, ''),
                       COALESCE(latest.reference_snapshot_hash, ''),
                       COALESCE(latest.dependency_projection_hash, ''),
                       COALESCE(latest.target_asset_version_id, '')
                FROM authority_legacy_migration_item AS item
                LEFT JOIN LATERAL (
                    SELECT migration_validation_id, status, source_hash,
                           domain_adapter, validator_name, validator_version,
                           validator_implementation_hash, item_version,
                           input_hash, reference_snapshot_hash,
                           dependency_projection_hash, target_asset_version_id
                    FROM authority_legacy_migration_validation
                    WHERE migration_item_id=item.migration_item_id
                    ORDER BY validation_version DESC
                    LIMIT 1
                ) AS latest ON TRUE
                WHERE item.migration_run_id=%s
                  AND item.target_materialization_level='DOMAIN_NATIVE'
                  AND item.domain_state IN (
                      'DOMAIN_VALIDATED','DOMAIN_DECISION_PENDING',
                      'DOMAIN_APPROVED','DOMAIN_ACTIVATION_PENDING',
                      'DOMAIN_ACTIVATED','DOMAIN_RECONCILED'
                  )
                """,
                [migration_run_id],
            )
            validation_rows = list(uow.cursor.fetchall())
            domain_validation_failures = 0
            for validation_row in validation_rows:
                adapter_name = str(validation_row[2])
                current_descriptor = validator_descriptor(
                    adapter_name,
                    application_build_id=self.application_build_id,
                    commit_sha=self.commit_sha,
                )
                try:
                    current_snapshot = load_validation_snapshot(
                        uow,
                        str(validation_row[0]),
                        bound_item_version=int(validation_row[1]),
                        application_build_id=self.application_build_id,
                        commit_sha=self.commit_sha,
                    )
                except (KernelError, ValueError):
                    domain_validation_failures += 1
                    continue
                if (
                    not str(validation_row[4])
                    or str(validation_row[4]) != str(validation_row[5])
                    or str(validation_row[6]) != "PASS"
                    or str(validation_row[3]) != str(validation_row[7])
                    or adapter_name != str(validation_row[8])
                    or current_descriptor.validator_name != str(validation_row[9])
                    or current_descriptor.validator_version != str(validation_row[10])
                    or current_descriptor.validator_implementation_hash
                    != str(validation_row[11])
                    or int(validation_row[1]) != int(validation_row[12])
                    or current_snapshot["input_hash"] != str(validation_row[13])
                    or current_snapshot["reference_snapshot_hash"]
                    != str(validation_row[14])
                    or current_snapshot["dependency_projection_hash"]
                    != str(validation_row[15])
                    or current_snapshot["item"]["target_asset_version_id"]
                    != str(validation_row[16])
                ):
                    domain_validation_failures += 1
            uow.cursor.execute(
                """
                SELECT COUNT(*)
                FROM authority_legacy_migration_item AS item
                LEFT JOIN authority_legacy_migration_validation AS activation
                  ON activation.migration_validation_id=
                     item.evidence->>'migration_validation_id'
                LEFT JOIN LATERAL (
                    SELECT migration_validation_id, validation_result_hash
                    FROM authority_legacy_migration_decision
                    WHERE migration_item_id=item.migration_item_id
                      AND decision='APPROVE'
                    ORDER BY decision_version DESC LIMIT 1
                ) AS decision ON TRUE
                WHERE item.migration_run_id=%s
                  AND item.status='ACTIVATED'
                  AND item.target_materialization_level='DOMAIN_NATIVE'
                  AND (
                      activation.migration_validation_id IS NULL
                      OR activation.status NOT IN ('PASS','STALE')
                      OR decision.migration_validation_id IS DISTINCT FROM
                         activation.migration_validation_id
                      OR decision.validation_result_hash IS DISTINCT FROM
                         activation.result_hash
                  )
                """,
                [migration_run_id],
            )
            domain_validation_failures += int(uow.cursor.fetchone()[0])
        target_integrity = (
            target_count == distinct_targets == hash_count == qualification_count
        )
        operation_integrity = (
            operation_count
            == audited_operation_count
            == outbox_operation_count
        )
        reference_integrity = (
            unresolved_reference_count == 0
            and reference_count
            == resolved_reference_count + closed_reference_exception_count
        )
        domain = self._reconcile_domains(migration_run_id)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT COUNT(*) FILTER (WHERE status='FAIL')
                FROM authority_legacy_migration_domain_reconciliation
                WHERE migration_run_id=%s
                """,
                [migration_run_id],
            )
            domain_reconciliation_failures = int(uow.cursor.fetchone()[0])
        domain["domain_native_core_proven"] = (
            domain["pending_domain_native_count"] == 0
            and domain["actual_domain_failures"] == 0
            and domain_validation_failures == 0
            and domain_reconciliation_failures == 0
            and required_reference_failures == 0
        )
        archival_reconciled = (
            terminal == total
            and target_integrity
            and operation_integrity
            and reference_integrity
            and counts.get("FAILED", 0) == 0
        )
        completion = derive_migration_completion(
            MigrationCompletionFacts(
                archival_integrity=hash_matches and archival_reconciled,
                domain_native_count=(
                    domain["domain_native_count"]
                    + domain["pending_domain_native_count"]
                ),
                domain_native_activated_count=domain["domain_native_pass_count"],
                pending_domain_native_count=domain["pending_domain_native_count"],
                failed_count=counts.get("FAILED", 0),
                quarantine_count=(
                    counts.get("QUARANTINED", 0)
                    + counts.get("INELIGIBLE", 0)
                ),
                actual_domain_failures=domain["actual_domain_failures"],
                domain_validation_failures=domain_validation_failures,
                domain_reconciliation_failures=domain_reconciliation_failures,
                required_reference_failures=required_reference_failures,
            ),
            required_level=verification_level,
        )
        result = {
            "migration_run_id": migration_run_id,
            "status": completion.run_status.value,
            "verification_status": (
                "PASS" if completion.required_level_satisfied else "FAIL"
            ),
            "required_level": completion.required_level.value,
            "required_level_satisfied": completion.required_level_satisfied,
            "run_completion_level": completion.completion_level.value,
            "expected_snapshot_hash": status["snapshot_hash"],
            "actual_snapshot_hash": actual_hash,
            "hash_matches": hash_matches,
            "source_snapshot_verified": snapshot_root is not None and hash_matches,
            "item_count": total,
            "terminal_item_count": terminal,
            "archival_reconciled": archival_reconciled,
            "reconciled": completion.required_level_satisfied,
            "target_asset_version_count": target_count,
            "distinct_target_asset_version_count": distinct_targets,
            "target_hash_match_count": hash_count,
            "qualification_count": qualification_count,
            "production_assets_activated": active_count,
            "needs_review_count": counts.get("NEEDS_REVIEW", 0),
            "quarantine_count": counts.get("QUARANTINED", 0) + counts.get("FAILED", 0),
            "operation_count": operation_count,
            "audited_operation_count": audited_operation_count,
            "outbox_operation_count": outbox_operation_count,
            "operation_integrity": operation_integrity,
            "reference_count": reference_count,
            "resolved_reference_count": resolved_reference_count,
            "unresolved_reference_count": unresolved_reference_count,
            "closed_reference_exception_count": closed_reference_exception_count,
            "required_reference_failures": required_reference_failures,
            "reference_integrity": reference_integrity,
            "domain_validation_failures": domain_validation_failures,
            "domain_reconciliation_failures": domain_reconciliation_failures,
            **domain,
        }
        self._complete_reconciliation_phases(migration_run_id, result)
        self._refresh_current_activated_validations(migration_run_id)
        self._persist_reconciliation(migration_run_id, result)
        return result

    def _refresh_current_activated_validations(
        self, migration_run_id: str
    ) -> None:
        refresh: list[tuple[str, int]] = []
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT item.migration_item_id, item.item_version,
                       item.domain_adapter,
                       COALESCE(
                           item.evidence->>'current_domain_validation_id', ''
                       ),
                       COALESCE(latest.migration_validation_id, ''),
                       COALESCE(latest.status, ''),
                       COALESCE(latest.item_version, 0),
                       COALESCE(latest.validator_implementation_hash, ''),
                       COALESCE(latest.input_hash, ''),
                       COALESCE(latest.reference_snapshot_hash, ''),
                       COALESCE(latest.dependency_projection_hash, ''),
                       COALESCE(latest.target_asset_version_id, '')
                FROM authority_legacy_migration_item AS item
                LEFT JOIN LATERAL (
                    SELECT migration_validation_id, status, item_version,
                           validator_implementation_hash, input_hash,
                           reference_snapshot_hash,
                           dependency_projection_hash, target_asset_version_id
                    FROM authority_legacy_migration_validation
                    WHERE migration_item_id=item.migration_item_id
                    ORDER BY validation_version DESC LIMIT 1
                ) AS latest ON TRUE
                WHERE item.migration_run_id=%s
                  AND item.status='ACTIVATED'
                  AND item.target_materialization_level='DOMAIN_NATIVE'
                ORDER BY item.migration_item_id
                """,
                [migration_run_id],
            )
            rows = list(uow.cursor.fetchall())
            for row in rows:
                descriptor = validator_descriptor(
                    str(row[2]),
                    application_build_id=self.application_build_id,
                    commit_sha=self.commit_sha,
                )
                if not int(row[6]):
                    continue
                try:
                    snapshot = load_validation_snapshot(
                        uow,
                        str(row[0]),
                        bound_item_version=int(row[6]),
                        application_build_id=self.application_build_id,
                        commit_sha=self.commit_sha,
                    )
                except (KernelError, ValueError):
                    continue
                semantic_snapshot_matches = (
                    bool(str(row[3]))
                    and str(row[3]) == str(row[4])
                    and str(row[5]) == "PASS"
                    and descriptor.validator_implementation_hash == str(row[7])
                    and snapshot["input_hash"] == str(row[8])
                    and snapshot["reference_snapshot_hash"] == str(row[9])
                    and snapshot["dependency_projection_hash"] == str(row[10])
                    and snapshot["item"]["target_asset_version_id"]
                    == str(row[11])
                )
                # Only heal item-version drift caused by a completed migration
                # phase. Any content/reference/dependency/validator drift stays
                # stale and must fail verification until an explicit Operation
                # produces a new Validation record.
                if semantic_snapshot_matches and int(row[1]) != int(row[6]):
                    refresh.append((str(row[0]), int(row[1])))
        for migration_item_id, item_version in refresh:
            self.validate_domain_item(
                migration_item_id, expected_item_version=item_version
            )

    def _reconcile_domains(self, migration_run_id: str) -> dict[str, Any]:
        rows: list[tuple[Any, ...]]
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT migration_item_id, project_id, workspace_id,
                       source_asset_type, materialization_level,
                       target_materialization_level, domain_adapter,
                       domain_projection_id, target_asset_version_id
                FROM authority_legacy_migration_item
                WHERE migration_run_id=%s
                  AND target_asset_version_id IS NOT NULL
                ORDER BY migration_item_id
                """,
                [migration_run_id],
            )
            rows = list(uow.cursor.fetchall())
        actual_domain = 0
        actual_domain_passes = 0
        actual_domain_failures = 0
        pending_domain = 0
        archival = 0
        for row in rows:
            (
                item_id,
                project_id,
                workspace_id,
                source_type,
                materialization_level,
                target_level,
                adapter,
                projection_id,
                target_version_id,
            ) = row
            status = "NOT_APPLICABLE"
            evidence: dict[str, Any] = {
                "source_asset_type": str(source_type),
                "materialization_level": str(materialization_level),
                "target_materialization_level": str(target_level),
            }
            if str(materialization_level) == MigrationMaterializationLevel.DOMAIN_NATIVE:
                actual_domain += 1
                if str(source_type) == "project_workspace_state":
                    with AuthorityUnitOfWork(self.database_url) as uow:
                        uow.cursor.execute(
                            """
                            SELECT project.current_asset_version_id,
                                   workspace.current_asset_version_id,
                                   project.status, project.version
                            FROM authority_project AS project
                            JOIN authority_workspace AS workspace
                              ON workspace.workspace_id=project.primary_workspace_id
                             AND workspace.project_id=project.project_id
                            WHERE project.project_id=%s
                              AND workspace.workspace_id=%s
                            """,
                            [project_id, workspace_id],
                        )
                        projection = uow.cursor.fetchone()
                    status = (
                        "PASS"
                        if projection is not None
                        and str(projection[0]) == str(target_version_id)
                        else "FAIL"
                    )
                    evidence.update(
                        {
                            "project_projection_present": projection is not None,
                            "project_current_asset_version_id": (
                                str(projection[0]) if projection else ""
                            ),
                            "workspace_current_asset_version_id": (
                                str(projection[1]) if projection else ""
                            ),
                            "project_status": str(projection[2]) if projection else "",
                            "project_version": int(projection[3]) if projection else None,
                        }
                    )
                elif str(source_type) in {"book", "book_record"}:
                    with AuthorityUnitOfWork(self.database_url) as uow:
                        uow.cursor.execute(
                            """
                            SELECT book.current_book_asset_version_id,
                                   book.status, book.version,
                                   COUNT(*) OVER ()
                            FROM authority_book AS book
                            WHERE book.project_id=%s AND book.book_id=%s
                            """,
                            [project_id, projection_id],
                        )
                        projection = uow.cursor.fetchone()
                    status = (
                        "PASS"
                        if projection is not None
                        and str(projection[0]) == str(target_version_id)
                        and int(projection[3]) == 1
                        else "FAIL"
                    )
                    evidence.update(
                        {
                            "book_projection_present": projection is not None,
                            "book_current_asset_version_id": (
                                str(projection[0]) if projection else ""
                            ),
                            "book_status": str(projection[1]) if projection else "",
                            "book_version": int(projection[2]) if projection else None,
                        }
                    )
                elif str(source_type) in {
                    "book_design",
                    "book_design_candidate",
                }:
                    with AuthorityUnitOfWork(self.database_url) as uow:
                        uow.cursor.execute(
                            """
                            SELECT candidate.status, version.lifecycle,
                                   book.current_book_design_asset_version_id,
                                   decision.decision_id,
                                   activation.activation_id
                            FROM authority_book_design_candidate AS candidate
                            JOIN authority_asset_version AS version
                              ON version.asset_version_id=candidate.asset_version_id
                            JOIN authority_book AS book
                              ON book.book_id=candidate.book_id
                             AND book.project_id=candidate.project_id
                            LEFT JOIN LATERAL (
                                SELECT decision_id
                                FROM authority_asset_decision
                                WHERE asset_version_id=candidate.asset_version_id
                                  AND decision='APPROVE'
                                ORDER BY created_at DESC LIMIT 1
                            ) AS decision ON TRUE
                            LEFT JOIN authority_asset_activation AS activation
                              ON activation.asset_version_id=candidate.asset_version_id
                             AND activation.retired_at IS NULL
                            WHERE candidate.project_id=%s
                              AND candidate.asset_version_id=%s
                            """,
                            [project_id, target_version_id],
                        )
                        projection = uow.cursor.fetchone()
                    status = (
                        "PASS"
                        if projection is not None
                        and tuple(str(value or "") for value in projection[:3])
                        == ("ACTIVE", "ACTIVE", str(target_version_id))
                        and bool(projection[3])
                        and bool(projection[4])
                        else "FAIL"
                    )
                    evidence.update(
                        {
                            "book_design_projection_present": projection is not None,
                            "candidate_status": str(projection[0]) if projection else "",
                            "asset_lifecycle": str(projection[1]) if projection else "",
                            "active_version_id": str(projection[2]) if projection else "",
                            "domain_decision_id": str(projection[3]) if projection else "",
                            "domain_activation_id": str(projection[4]) if projection else "",
                        }
                    )
                elif str(source_type) in {
                    "story_design",
                    "story_design_candidate",
                }:
                    with AuthorityUnitOfWork(self.database_url) as uow:
                        uow.cursor.execute(
                            """
                            SELECT state.lifecycle, state.qualification,
                                   state.approval, state.version,
                                   active.asset_version_id
                            FROM authority_story_design_version_state AS state
                            JOIN authority_story_design_active_version AS active
                              ON active.project_id=state.project_id
                             AND active.logical_key=state.logical_key
                            WHERE state.project_id=%s
                              AND state.asset_version_id=%s
                            """,
                            [project_id, target_version_id],
                        )
                        projection = uow.cursor.fetchone()
                    status = (
                        "PASS"
                        if projection is not None
                        and tuple(str(value) for value in projection[:3])
                        == ("ACTIVE", "QUALIFIED", "APPROVED")
                        and str(projection[4]) == str(target_version_id)
                        else "FAIL"
                    )
                    evidence.update(
                        {
                            "story_design_projection_present": projection is not None,
                            "lifecycle": str(projection[0]) if projection else "",
                            "qualification": str(projection[1]) if projection else "",
                            "approval": str(projection[2]) if projection else "",
                            "aggregate_version": int(projection[3]) if projection else None,
                            "active_version_id": str(projection[4]) if projection else "",
                        }
                    )
                elif str(source_type) in {
                    "book_plan",
                    "outline_version",
                    "volume_plan",
                    "arc_plan",
                    "chapter_group_plan",
                    "chapter_plan",
                    "chapter_plan_version",
                }:
                    with AuthorityUnitOfWork(self.database_url) as uow:
                        uow.cursor.execute(
                            """
                            SELECT binding.binding_id, binding.contract_type,
                                   binding.parent_version_id,
                                   binding.freshness,
                                   active.asset_version_id,
                                   COUNT(hierarchy.hierarchy_id)
                            FROM story_plan_binding AS binding
                            JOIN active_story_plan_version AS active
                              ON active.binding_id=binding.binding_id
                             AND active.project_id=binding.project_id
                            LEFT JOIN story_plan_hierarchy AS hierarchy
                              ON hierarchy.child_binding_id=binding.binding_id
                            WHERE binding.project_id=%s
                              AND binding.asset_version_id=%s
                            GROUP BY binding.binding_id, binding.contract_type,
                                     binding.parent_version_id,
                                     binding.freshness, active.asset_version_id
                            """,
                            [project_id, target_version_id],
                        )
                        projection = uow.cursor.fetchone()
                    parent_required = str(source_type) in {
                        "volume_plan",
                        "chapter_group_plan",
                        "chapter_plan",
                        "chapter_plan_version",
                    }
                    status = (
                        "PASS"
                        if projection is not None
                        and str(projection[0]) == str(projection_id)
                        and str(projection[3]) == "CURRENT"
                        and str(projection[4]) == str(target_version_id)
                        and (
                            not parent_required
                            or (bool(projection[2]) and int(projection[5]) == 1)
                        )
                        else "FAIL"
                    )
                    evidence.update(
                        {
                            "planning_projection_present": projection is not None,
                            "binding_id": str(projection[0]) if projection else "",
                            "contract_type": str(projection[1]) if projection else "",
                            "parent_version_id": str(projection[2] or "") if projection else "",
                            "freshness": str(projection[3]) if projection else "",
                            "active_version_id": str(projection[4]) if projection else "",
                            "hierarchy_edge_count": int(projection[5]) if projection else 0,
                        }
                    )
                elif str(source_type) == "source_document":
                    with AuthorityUnitOfWork(self.database_url) as uow:
                        uow.cursor.execute(
                            """
                            SELECT source.source_document_id,
                                   source.asset_version_id,
                                   source.source_content_hash,
                                   source.governance_status,
                                   version.lifecycle, version.eligibility,
                                   version.governance, blob.status,
                                   blob.actual_hash, blob.expected_hash,
                                   blob.actual_object_key, blob.object_key
                            FROM authority_source_document AS source
                            JOIN authority_asset_version AS version
                              ON version.asset_version_id=source.asset_version_id
                            JOIN authority_blob AS blob
                              ON blob.blob_id=source.blob_id
                            WHERE source.project_id=%s
                              AND source.source_document_id=%s
                            """,
                            [project_id, projection_id],
                        )
                        projection = uow.cursor.fetchone()
                    status = (
                        "PASS"
                        if projection is not None
                        and str(projection[1]) == str(target_version_id)
                        and tuple(str(value) for value in projection[3:8])
                        == (
                            "ELIGIBLE",
                            "ACTIVE",
                            "ELIGIBLE",
                            "CLEAR",
                            "AVAILABLE",
                        )
                        and str(projection[8]) == str(projection[9])
                        and str(projection[10]) == str(projection[11])
                        else "FAIL"
                    )
                    evidence.update(
                        {
                            "source_projection_present": projection is not None,
                            "source_document_id": str(projection[0]) if projection else "",
                            "source_asset_version_id": str(projection[1]) if projection else "",
                            "source_content_hash": str(projection[2]) if projection else "",
                            "governance_status": str(projection[3]) if projection else "",
                            "lifecycle": str(projection[4]) if projection else "",
                            "eligibility": str(projection[5]) if projection else "",
                            "governance": str(projection[6]) if projection else "",
                            "blob_status": str(projection[7]) if projection else "",
                            "blob_receipt_matches": bool(
                                projection
                                and str(projection[8]) == str(projection[9])
                                and str(projection[10]) == str(projection[11])
                            ),
                        }
                    )
                elif str(source_type) in {
                    "knowledge_card_candidate",
                    "knowledge_card",
                }:
                    with AuthorityUnitOfWork(self.database_url) as uow:
                        uow.cursor.execute(
                            """
                            SELECT card.knowledge_card_id,
                                   card.asset_version_id,
                                   card.candidate_asset_version_id,
                                   card.governance_decision_asset_version_id,
                                   card.status, version.lifecycle,
                                   version.eligibility, version.governance,
                                   operation.status
                            FROM authority_mkaos_knowledge_card AS card
                            JOIN authority_asset_version AS version
                              ON version.asset_version_id=card.asset_version_id
                            JOIN authority_operation AS operation
                              ON operation.operation_id=card.created_by_operation_id
                            WHERE card.project_id=%s
                              AND card.knowledge_card_id=%s
                            """,
                            [project_id, projection_id],
                        )
                        projection = uow.cursor.fetchone()
                    status = (
                        "PASS"
                        if projection is not None
                        and str(projection[1]) == str(target_version_id)
                        and tuple(str(value) for value in projection[4:9])
                        == (
                            "ACTIVE",
                            "ACTIVE",
                            "ELIGIBLE",
                            "CLEAR",
                            "SUCCEEDED",
                        )
                        and bool(projection[2])
                        and bool(projection[3])
                        else "FAIL"
                    )
                    evidence.update(
                        {
                            "mkaos_card_projection_present": projection is not None,
                            "knowledge_card_id": str(projection[0]) if projection else "",
                            "knowledge_card_asset_version_id": str(projection[1]) if projection else "",
                            "candidate_asset_version_id": str(projection[2]) if projection else "",
                            "decision_asset_version_id": str(projection[3]) if projection else "",
                            "card_status": str(projection[4]) if projection else "",
                            "lifecycle": str(projection[5]) if projection else "",
                            "eligibility": str(projection[6]) if projection else "",
                            "governance": str(projection[7]) if projection else "",
                            "operation_status": str(projection[8]) if projection else "",
                        }
                    )
                elif str(source_type) == "knowledge_pack":
                    with AuthorityUnitOfWork(self.database_url) as uow:
                        uow.cursor.execute(
                            """
                            SELECT pack.knowledge_pack_id,
                                   pack.asset_version_id, pack.status,
                                   pack.item_count, pack.selection_hash,
                                   version.lifecycle, version.eligibility,
                                   version.governance, operation.status,
                                   COUNT(item.ordinal)
                            FROM authority_mkaos_knowledge_pack AS pack
                            JOIN authority_asset_version AS version
                              ON version.asset_version_id=pack.asset_version_id
                            JOIN authority_operation AS operation
                              ON operation.operation_id=pack.created_by_operation_id
                            LEFT JOIN authority_mkaos_knowledge_pack_item AS item
                              ON item.knowledge_pack_id=pack.knowledge_pack_id
                            WHERE pack.project_id=%s
                              AND pack.knowledge_pack_id=%s
                            GROUP BY pack.knowledge_pack_id,
                                     pack.asset_version_id, pack.status,
                                     pack.item_count, pack.selection_hash,
                                     version.lifecycle, version.eligibility,
                                     version.governance, operation.status
                            """,
                            [project_id, projection_id],
                        )
                        projection = uow.cursor.fetchone()
                    status = (
                        "PASS"
                        if projection is not None
                        and str(projection[1]) == str(target_version_id)
                        and tuple(str(value) for value in projection[2:3] + projection[5:9])
                        == (
                            "ACTIVE",
                            "ACTIVE",
                            "ELIGIBLE",
                            "CLEAR",
                            "SUCCEEDED",
                        )
                        and int(projection[3]) == int(projection[9])
                        and bool(projection[4])
                        else "FAIL"
                    )
                    evidence.update(
                        {
                            "mkaos_pack_projection_present": projection is not None,
                            "knowledge_pack_id": str(projection[0]) if projection else "",
                            "knowledge_pack_asset_version_id": str(projection[1]) if projection else "",
                            "pack_status": str(projection[2]) if projection else "",
                            "item_count": int(projection[3]) if projection else 0,
                            "selection_hash": str(projection[4]) if projection else "",
                            "persisted_item_count": int(projection[9]) if projection else 0,
                        }
                    )
                else:
                    status = "FAIL"
                    evidence["error"] = "DOMAIN_RECONCILER_NOT_REGISTERED"
                if status == "PASS":
                    actual_domain_passes += 1
                else:
                    actual_domain_failures += 1
            elif str(target_level) == MigrationMaterializationLevel.DOMAIN_NATIVE:
                status = "NEEDS_REVIEW"
                pending_domain += 1
                evidence["reason"] = "DOMAIN_ADAPTER_HAS_NOT_MATERIALIZED_PROJECTION"
            else:
                archival += 1
            adapter_name = str(adapter or "archival_asset_version")
            with AuthorityUnitOfWork(self.database_url) as uow:
                uow.cursor.execute(
                    """
                    INSERT INTO authority_legacy_migration_domain_reconciliation(
                        domain_reconciliation_id, migration_run_id,
                        migration_item_id, domain_adapter, status,
                        projection_id, evidence
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (migration_item_id, domain_adapter) DO UPDATE
                    SET status=EXCLUDED.status,
                        projection_id=EXCLUDED.projection_id,
                        evidence=EXCLUDED.evidence,
                        reconciled_at=NOW()
                    """,
                    [
                        _stable_id("domain-reconcile", str(item_id), adapter_name),
                        migration_run_id,
                        item_id,
                        adapter_name,
                        status,
                        str(projection_id or ""),
                        Jsonb(evidence),
                    ],
                )
                if str(materialization_level) == MigrationMaterializationLevel.DOMAIN_NATIVE:
                    domain_state = (
                        MigrationDomainState.DOMAIN_RECONCILED.value
                        if status == "PASS"
                        else MigrationDomainState.DOMAIN_RECONCILIATION_FAILED.value
                    )
                    uow.cursor.execute(
                        """
                        UPDATE authority_legacy_migration_item
                        SET materialization_stage='DOMAIN', domain_state=%s,
                            archival_state='ARCHIVAL_RECONCILED', updated_at=NOW()
                        WHERE migration_item_id=%s
                        """,
                        [domain_state, item_id],
                    )
                elif str(target_level) != MigrationMaterializationLevel.DOMAIN_NATIVE:
                    uow.cursor.execute(
                        """
                        UPDATE authority_legacy_migration_item
                        SET archival_state='ARCHIVAL_RECONCILED',
                            domain_state='DOMAIN_NOT_APPLICABLE', updated_at=NOW()
                        WHERE migration_item_id=%s
                        """,
                        [item_id],
                    )
                uow.commit()
        return {
            "domain_native_count": actual_domain,
            "domain_native_pass_count": actual_domain_passes,
            "actual_domain_failures": actual_domain_failures,
            "pending_domain_native_count": pending_domain,
            "archival_native_count": archival,
            "domain_native_core_proven": pending_domain == 0 and actual_domain_failures == 0,
        }

    def _complete_reconciliation_phases(
        self, migration_run_id: str, reconciliation: dict[str, Any]
    ) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT source_ref, source_category, source_hash,
                       stable_business_key, project_id, workspace_id,
                       source_asset_type, target_content_hash
                FROM authority_legacy_migration_item
                WHERE migration_run_id=%s AND next_phase='RECONCILE'
                ORDER BY migration_item_id
                """,
                [migration_run_id],
            )
            rows = list(uow.cursor.fetchall())
        for row in rows:
            record = LegacySnapshotRecord(
                source_ref=str(row[0]),
                category=str(row[1]),
                source_hash=str(row[2]),
                size_bytes=0,
                stable_business_key=str(row[3]),
                project_id=str(row[4]),
                workspace_id=str(row[5]),
                source_asset_type=str(row[6]),
                payload=None,
                references=(),
                decision="IMPORT",
                status="VALIDATED",
            )
            output_hash = str(row[7] or "")
            self._complete_phase(
                migration_run_id,
                record,
                phase=MigrationPhase.RECONCILE,
                next_phase=MigrationPhase.COMPLETE,
                output_hash=output_hash,
                evidence={
                    "reconciled": bool(reconciliation["reconciled"]),
                    "reference_integrity": bool(
                        reconciliation["reference_integrity"]
                    ),
                    "operation_integrity": bool(
                        reconciliation["operation_integrity"]
                    ),
                },
            )

    def quarantine_list(
        self, *, migration_run_id: str | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        clauses = ["resolution_status = 'OPEN'"]
        params: list[Any] = []
        if migration_run_id:
            clauses.append("migration_run_id = %s")
            params.append(migration_run_id)
        params.append(limit)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT quarantine_id, migration_run_id, project_id, workspace_id,
                       category, source_ref, reason_code, payload_hash, payload,
                       resolution_status, created_at
                FROM authority_data_quarantine WHERE """
                + " AND ".join(clauses)
                + " ORDER BY created_at DESC, quarantine_id LIMIT %s",
                params,
            )
            rows = uow.cursor.fetchall()
        keys = (
            "quarantine_id", "migration_run_id", "project_id", "workspace_id",
            "category", "source_ref", "reason_code", "payload_hash", "payload",
            "resolution_status", "created_at",
        )
        return [dict(zip(keys, (*row[:-1], str(row[-1])), strict=True)) for row in rows]

    def _bootstrap_projects(
        self, records: tuple[LegacySnapshotRecord, ...], run_id: str
    ) -> dict[str, str]:
        query = ProjectAuthorityQuery(self.database_url)
        application = ProjectAuthorityApplication(
            self.database_url,
            application_build_id=self.application_build_id,
            commit_sha=self.commit_sha,
        )
        workspaces: dict[str, str] = {}
        for record in records:
            if record.payload is None or record.source_asset_type != "project_workspace_state":
                continue
            workspace_id = record.workspace_id or f"workspace:{record.project_id}"
            try:
                existing = query.require_project(record.project_id)
                workspaces[record.project_id] = str(existing["workspace_id"])
                continue
            except KernelError as exc:
                if exc.code != "PROJECT_NOT_FOUND":
                    raise
            content = record.payload.get("content") or {}
            memory = content.get("memory") if isinstance(content.get("memory"), dict) else {}
            metadata = record.payload.get("metadata") or {}
            project_config = _remove_paths(content.get("project_config") or {})
            result = application.execute(
                ProjectAuthorityCommand(
                    definition_name="project_lifecycle.create",
                    project_id=record.project_id,
                    workspace_id=workspace_id,
                    actor_id=self.actor_id,
                    idempotency_key=f"legacy-project-shell:{record.project_id}",
                    trace_id=f"trace:{run_id}",
                    correlation_id=f"correlation:{run_id}",
                    payload={
                        "title": str(memory.get("project_title") or record.payload.get("title") or record.project_id),
                        "series_title": str(memory.get("series_title") or metadata.get("series_title") or ""),
                        "book_number": memory.get("book_number") or metadata.get("book_number"),
                        "health": "BLOCKED",
                        "stage": "DESIGN",
                        "config": {
                            **project_config,
                            "legacy_import_run_id": run_id,
                            "migration_review_required": True,
                        },
                    },
                )
            )
            detail = query.require_project(record.project_id)
            application.execute(
                ProjectAuthorityCommand(
                    definition_name="project_lifecycle.transition",
                    project_id=record.project_id,
                    workspace_id=workspace_id,
                    actor_id=self.actor_id,
                    idempotency_key=f"legacy-project-shell-pause:{record.project_id}",
                    trace_id=f"trace:{run_id}",
                    correlation_id=f"correlation:{run_id}",
                    payload={"target_status": "PAUSED"},
                    expected_version=detail["version"],
                    expected_current_asset_version_id=detail["asset_version_id"],
                )
            )
            workspaces[record.project_id] = str(result["workspace_id"])
        return workspaces

    def _start_run(
        self, run_id: str, snapshot_hash: str, source_root: str, *, resume: bool
    ) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                INSERT INTO authority_migration_run(
                    migration_run_id, source_kind, source_hash, status, report,
                    snapshot_hash, mode, idempotency_key, cursor_state, counts
                ) VALUES (%s, 'legacy_localstorage_snapshot', %s, 'IMPORT_RUNNING', %s,
                          %s, 'IMPORT', %s, '{}'::jsonb, '{}'::jsonb)
                ON CONFLICT (migration_run_id) DO NOTHING
                """,
                [run_id, snapshot_hash, Jsonb({"source_root": source_root}), snapshot_hash, snapshot_hash],
            )
            if uow.cursor.rowcount == 0 and not resume:
                raise KernelError("MIGRATION_RUN_EXISTS", "migration run already exists; use resume")
            uow.cursor.execute(
                """
                UPDATE authority_migration_run
                SET status = 'IMPORT_RUNNING', run_completion_level='NONE',
                    updated_at = NOW(), finished_at=NULL
                WHERE migration_run_id = %s
                  AND status IN ('IMPORT_RUNNING','FAILED')
                """,
                [run_id],
            )
            uow.commit()

    def _existing_item(self, run_id: str, source_ref: str) -> str:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                "SELECT status FROM authority_legacy_migration_item WHERE migration_run_id=%s AND source_ref=%s",
                [run_id, source_ref],
            )
            row = uow.cursor.fetchone()
        return str(row[0]) if row else ""

    def _resume_counts(self, run_id: str) -> tuple[int, int, int]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT
                    COUNT(*) FILTER (
                        WHERE status IN ('IMPORTED','QUALIFIED','ACTIVATED','NEEDS_REVIEW')
                    ),
                    COUNT(*) FILTER (WHERE status IN ('QUARANTINED','INELIGIBLE')),
                    COUNT(*) FILTER (WHERE status = 'SKIPPED_DUPLICATE')
                FROM authority_legacy_migration_item
                WHERE migration_run_id = %s
                """,
                [run_id],
            )
            row = uow.cursor.fetchone()
        return int(row[0]), int(row[1]), int(row[2])

    def _upsert_item(
        self,
        run_id: str,
        record: LegacySnapshotRecord,
        *,
        status: str,
        decision: str,
        error_code: str = "",
        operation_id: str | None = None,
        target_asset_id: str | None = None,
        target_asset_version_id: str | None = None,
        evidence: dict[str, Any] | None = None,
        phase: str = "CLASSIFY",
        target_asset_type: str = "",
        codec_name: str = "",
        codec_version: str = "",
        target_content_hash: str = "",
        materialization_level: MigrationMaterializationLevel = (
            MigrationMaterializationLevel.ARCHIVAL_NATIVE
        ),
        target_materialization_level: MigrationMaterializationLevel = (
            MigrationMaterializationLevel.ARCHIVAL_NATIVE
        ),
        domain_adapter: str = "",
        domain_validator: str = "",
        projection_strategy: str = "immutable_asset_version_only.v1",
        activation_strategy: str = "NEEDS_REVIEW",
        domain_projection_id: str = "",
        resolved_workspace_id: str = "",
    ) -> None:
        item_id = _stable_id("migration-item", run_id, record.source_ref)
        reference_state = (
            MigrationReferenceStatus.UNRESOLVED
            if record.references
            else MigrationReferenceStatus.RESOLVED
        )
        if status == "DISCOVERED":
            archival_state = MigrationArchivalState.DISCOVERED
        elif record.references:
            archival_state = MigrationArchivalState.REFERENCES_PENDING
        elif target_asset_version_id:
            archival_state = MigrationArchivalState.ARCHIVAL_VALIDATED
        else:
            archival_state = MigrationArchivalState.CLASSIFIED
        if target_materialization_level is MigrationMaterializationLevel.ARCHIVAL_NATIVE:
            domain_state = MigrationDomainState.DOMAIN_NOT_APPLICABLE
        elif materialization_level is MigrationMaterializationLevel.DOMAIN_NATIVE:
            domain_state = MigrationDomainState.DOMAIN_ACTIVATED
        else:
            domain_state = MigrationDomainState.DOMAIN_VALIDATION_PENDING
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                INSERT INTO authority_legacy_migration_item(
                    migration_item_id, migration_run_id, project_id, workspace_id,
                    source_ref, source_category, source_hash, stable_business_key,
                    operation_id, target_asset_id, target_asset_version_id,
                    status, decision, error_code, evidence
                    , source_asset_type, target_asset_type, codec_name,
                    codec_version, phase, target_content_hash, reference_count,
                    reconciliation, materialization_level,
                    target_materialization_level, domain_adapter,
                    domain_validator, projection_strategy,
                    activation_strategy, domain_projection_id, next_phase,
                    reference_state, materialization_stage, archival_state,
                    domain_state, validation_scope
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                          %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                          %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                          %s)
                ON CONFLICT (migration_run_id, source_ref) DO UPDATE
                SET operation_id=COALESCE(EXCLUDED.operation_id, authority_legacy_migration_item.operation_id),
                    target_asset_id=COALESCE(EXCLUDED.target_asset_id, authority_legacy_migration_item.target_asset_id),
                    target_asset_version_id=COALESCE(EXCLUDED.target_asset_version_id, authority_legacy_migration_item.target_asset_version_id),
                    status=EXCLUDED.status, decision=EXCLUDED.decision,
                    workspace_id=COALESCE(NULLIF(EXCLUDED.workspace_id, ''), authority_legacy_migration_item.workspace_id),
                    error_code=EXCLUDED.error_code, evidence=EXCLUDED.evidence,
                    source_asset_type=EXCLUDED.source_asset_type,
                    target_asset_type=COALESCE(NULLIF(EXCLUDED.target_asset_type, ''), authority_legacy_migration_item.target_asset_type),
                    codec_name=COALESCE(NULLIF(EXCLUDED.codec_name, ''), authority_legacy_migration_item.codec_name),
                    codec_version=COALESCE(NULLIF(EXCLUDED.codec_version, ''), authority_legacy_migration_item.codec_version),
                    phase=EXCLUDED.phase,
                    target_content_hash=COALESCE(NULLIF(EXCLUDED.target_content_hash, ''), authority_legacy_migration_item.target_content_hash),
                    reference_count=EXCLUDED.reference_count,
                    reconciliation=EXCLUDED.reconciliation,
                    materialization_level=EXCLUDED.materialization_level,
                    target_materialization_level=EXCLUDED.target_materialization_level,
                    domain_adapter=COALESCE(NULLIF(EXCLUDED.domain_adapter, ''), authority_legacy_migration_item.domain_adapter),
                    domain_validator=COALESCE(NULLIF(EXCLUDED.domain_validator, ''), authority_legacy_migration_item.domain_validator),
                    projection_strategy=COALESCE(NULLIF(EXCLUDED.projection_strategy, ''), authority_legacy_migration_item.projection_strategy),
                    activation_strategy=COALESCE(NULLIF(EXCLUDED.activation_strategy, ''), authority_legacy_migration_item.activation_strategy),
                    domain_projection_id=COALESCE(NULLIF(EXCLUDED.domain_projection_id, ''), authority_legacy_migration_item.domain_projection_id),
                    materialization_stage=EXCLUDED.materialization_stage,
                    archival_state=EXCLUDED.archival_state,
                    domain_state=EXCLUDED.domain_state,
                    validation_scope=EXCLUDED.validation_scope,
                    updated_at=NOW()
                """,
                [
                    item_id, run_id, record.project_id,
                    resolved_workspace_id or record.workspace_id,
                    record.source_ref, record.category, record.source_hash,
                    record.stable_business_key, operation_id, target_asset_id,
                    target_asset_version_id, status, decision, error_code,
                    Jsonb(evidence or {"errors": list(record.errors)}),
                    record.source_asset_type, target_asset_type, codec_name,
                    codec_version, phase, target_content_hash,
                    len(record.references), Jsonb((evidence or {}).get("reconciliation", {})),
                    materialization_level.value,
                    target_materialization_level.value,
                    domain_adapter,
                    domain_validator,
                    projection_strategy,
                    activation_strategy,
                    domain_projection_id,
                    MigrationPhase.SCAN.value,
                    reference_state.value,
                    (
                        "DOMAIN"
                        if materialization_level is MigrationMaterializationLevel.DOMAIN_NATIVE
                        else "ARCHIVAL"
                    ),
                    archival_state.value,
                    domain_state.value,
                    (
                        MigrationValidationScope.DOMAIN.value
                        if target_materialization_level
                        is MigrationMaterializationLevel.DOMAIN_NATIVE
                        else MigrationValidationScope.ARCHIVAL.value
                    ),
                ],
            )
            uow.commit()

    def _complete_successful_item_phases(
        self,
        run_id: str,
        record: LegacySnapshotRecord,
        *,
        output_hash: str,
        activated: bool,
        awaiting_domain_activation: bool = False,
        evidence: dict[str, Any],
    ) -> None:
        chain: list[tuple[MigrationPhase, MigrationPhase]] = [
            (MigrationPhase.SEMANTIC_CONVERT, MigrationPhase.VALIDATE),
            (MigrationPhase.VALIDATE, MigrationPhase.QUALIFY),
        ]
        if activated:
            chain.extend(
                [
                    (MigrationPhase.QUALIFY, MigrationPhase.ACTIVATE),
                    (MigrationPhase.ACTIVATE, MigrationPhase.RECONCILE),
                ]
            )
        elif awaiting_domain_activation:
            chain.append((MigrationPhase.QUALIFY, MigrationPhase.ACTIVATE))
        else:
            chain.append((MigrationPhase.QUALIFY, MigrationPhase.RECONCILE))
        for phase, next_phase in chain:
            self._complete_phase(
                run_id,
                record,
                phase=phase,
                next_phase=next_phase,
                output_hash=output_hash,
                evidence=evidence,
            )

    def _complete_phase(
        self,
        run_id: str,
        record: LegacySnapshotRecord,
        *,
        phase: MigrationPhase,
        next_phase: MigrationPhase,
        evidence: dict[str, Any],
        output_hash: str = "",
    ) -> None:
        require_phase_transition(phase, next_phase)
        item_id = _stable_id("migration-item", run_id, record.source_ref)
        started_at = datetime.now(timezone.utc)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT item_version, phase_version, next_phase,
                       target_asset_id, target_asset_version_id,
                       target_asset_type, reference_state, reference_count
                FROM authority_legacy_migration_item
                WHERE migration_item_id=%s
                FOR UPDATE
                """,
                [item_id],
            )
            row = uow.cursor.fetchone()
            if row is None:
                raise KernelError(
                    "MIGRATION_ITEM_NOT_FOUND",
                    "phase transition target does not exist",
                )
            current_next = MigrationPhase(str(row[2]))
            if current_next != phase:
                uow.cursor.execute(
                    """
                    SELECT 1 FROM authority_legacy_migration_phase_evidence
                    WHERE migration_item_id=%s AND phase=%s
                    """,
                    [item_id, phase.value],
                )
                if uow.cursor.fetchone() is not None:
                    return
                raise KernelError(
                    "MIGRATION_PHASE_CONFLICT",
                    f"expected {phase.value}, found {current_next.value}",
                )
            item_version = int(row[0])
            phase_version = int(row[1]) + 1
            reference_state = MigrationReferenceStatus(str(row[6]))
            target_identity = ":".join(
                value
                for value in (
                    record.project_id,
                    str(row[5] or record.source_asset_type),
                    record.stable_business_key,
                    str(row[3] or ""),
                    str(row[4] or ""),
                )
                if value
            )
            checkpoint = MigrationPhaseCheckpoint(
                migration_run_id=run_id,
                item_id=item_id,
                phase=phase,
                source_hash=record.source_hash,
                target_identity=target_identity,
                reference_state=reference_state,
                counts={"references": int(row[7]), "attempt": 1},
            )
            phase_evidence = {
                **evidence,
                "checkpoint_hash": checkpoint.checkpoint_hash,
                "checkpoint": checkpoint.content,
            }
            uow.cursor.execute(
                """
                UPDATE authority_legacy_migration_item
                SET phase=%s, next_phase=%s,
                    item_version=item_version+1,
                    phase_version=%s,
                    phase_started_at=%s,
                    phase_completed_at=NOW(),
                    phase_attempt_count=phase_attempt_count+1,
                    phase_input_hash=%s,
                    phase_output_hash=%s,
                    phase_evidence=%s,
                    updated_at=NOW()
                WHERE migration_item_id=%s AND item_version=%s
                """,
                [
                    phase.value,
                    next_phase.value,
                    phase_version,
                    started_at,
                    record.source_hash,
                    output_hash,
                    Jsonb(phase_evidence),
                    item_id,
                    item_version,
                ],
            )
            if uow.cursor.rowcount != 1:
                raise KernelError(
                    "MIGRATION_ITEM_VERSION_CONFLICT",
                    "migration item changed during phase compare-and-set",
                )
            uow.cursor.execute(
                """
                INSERT INTO authority_legacy_migration_phase_evidence(
                    phase_evidence_id, migration_run_id, migration_item_id,
                    phase, phase_version, attempt_count, input_hash,
                    output_hash, evidence, next_phase, started_at, completed_at
                ) VALUES (%s, %s, %s, %s, %s, 1, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (migration_item_id, phase_version) DO NOTHING
                """,
                [
                    _stable_id("migration-phase", item_id, str(phase_version)),
                    run_id,
                    item_id,
                    phase.value,
                    phase_version,
                    record.source_hash,
                    output_hash,
                    Jsonb(phase_evidence),
                    next_phase.value,
                    started_at,
                ],
            )
            uow.commit()

    def _quarantine_or_reconcile_phase(
        self, run_id: str, record: LegacySnapshotRecord
    ) -> None:
        item_id = _stable_id("migration-item", run_id, record.source_ref)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                "SELECT next_phase FROM authority_legacy_migration_item WHERE migration_item_id=%s",
                [item_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            return
        current = MigrationPhase(str(row[0]))
        if current is MigrationPhase.COMPLETE:
            return
        if current is MigrationPhase.QUARANTINE:
            self._complete_phase(
                run_id,
                record,
                phase=MigrationPhase.QUARANTINE,
                next_phase=MigrationPhase.RECONCILE,
                evidence={"error_code": record.error_code},
            )
            return
        require_phase_transition(current, MigrationPhase.QUARANTINE)
        self._complete_phase(
            run_id,
            record,
            phase=current,
            next_phase=MigrationPhase.QUARANTINE,
            evidence={"error_code": record.error_code},
        )
        self._complete_phase(
            run_id,
            record,
            phase=MigrationPhase.QUARANTINE,
            next_phase=MigrationPhase.RECONCILE,
            evidence={"error_code": record.error_code},
        )

    def _stage_references(
        self, run_id: str, record: LegacySnapshotRecord
    ) -> None:
        item_id = _stable_id("migration-item", run_id, record.source_ref)
        with AuthorityUnitOfWork(self.database_url) as uow:
            for reference in record.references:
                uow.cursor.execute(
                    """
                    INSERT INTO authority_legacy_migration_reference(
                        migration_reference_id, migration_run_id,
                        source_item_id, reference_ordinal,
                        legacy_business_key, relation_type, optional,
                        expected_source_type, expected_target_asset_type,
                        expected_content_hash, cardinality,
                        compatibility_evidence, resolution_status, evidence
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, 'UNRESOLVED', %s
                    )
                    ON CONFLICT (
                        migration_run_id, source_item_id, reference_ordinal
                    ) DO NOTHING
                    """,
                    [
                        _stable_id(
                            "migration-reference",
                            run_id,
                            item_id,
                            str(reference.ordinal),
                        ),
                        run_id,
                        item_id,
                        reference.ordinal,
                        reference.business_key,
                        reference.relation_type.value,
                        reference.optional,
                        reference.expected_source_type,
                        reference.expected_target_asset_type,
                        reference.expected_content_hash,
                        reference.cardinality,
                        Jsonb(reference.compatibility_evidence),
                        Jsonb(
                            {
                                "source_ref": record.source_ref,
                                "reference_contract": reference.to_contract(),
                            }
                        ),
                    ],
                )
            uow.commit()

    def _resolve_references(
        self,
        run_id: str,
        records: tuple[LegacySnapshotRecord, ...],
    ) -> None:
        records_by_item = {
            _stable_id("migration-item", run_id, item.source_ref): item
            for item in records
        }
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT reference.migration_reference_id,
                       reference.source_item_id,
                       reference.legacy_business_key,
                       source.project_id, source.workspace_id,
                       source.source_asset_type,
                       reference.relation_type, reference.optional,
                       reference.expected_source_type,
                       reference.expected_target_asset_type,
                       reference.expected_content_hash,
                       reference.cardinality
                FROM authority_legacy_migration_reference AS reference
                JOIN authority_legacy_migration_item AS source
                  ON source.migration_item_id=reference.source_item_id
                WHERE reference.migration_run_id=%s
                  AND reference.resolution_status='UNRESOLVED'
                ORDER BY reference.source_item_id, reference.reference_ordinal
                """,
                [run_id],
            )
            unresolved = list(uow.cursor.fetchall())
        for (
            reference_id,
            source_item_id,
            business_key,
            source_project_id,
            source_workspace_id,
            source_type,
            relation_type,
            optional,
            expected_source_type,
            expected_target_asset_type,
            expected_content_hash,
            cardinality,
        ) in unresolved:
            with AuthorityUnitOfWork(self.database_url) as uow:
                uow.cursor.execute(
                    """
                    SELECT migration_item_id, project_id, target_asset_id,
                           target_asset_version_id, domain_projection_id,
                           workspace_id, source_asset_type, target_asset_type,
                           target_content_hash
                    FROM authority_legacy_migration_item
                    WHERE migration_run_id=%s AND stable_business_key=%s
                      AND target_asset_version_id IS NOT NULL
                      AND status NOT IN ('QUARANTINED','INELIGIBLE','FAILED')
                    ORDER BY migration_item_id
                    """,
                    [run_id, business_key],
                )
                targets = list(uow.cursor.fetchall())
                status = MigrationReferenceStatus.RESOLVED
                error_code = ""
                if len(targets) != 1:
                    if len(targets) == 0 and bool(optional):
                        status = MigrationReferenceStatus.OPTIONAL_MISSING
                        error_code = "OPTIONAL_REFERENCE_MISSING"
                    else:
                        status = (
                            MigrationReferenceStatus.CONFLICT
                            if len(targets) > 1
                            else MigrationReferenceStatus.QUARANTINED
                        )
                        error_code = (
                            "AMBIGUOUS_REFERENCE"
                            if len(targets) > 1
                            else "MISSING_REFERENCE"
                        )
                elif str(targets[0][1]) != str(source_project_id):
                    status = MigrationReferenceStatus.QUARANTINED
                    error_code = "CROSS_PROJECT_REFERENCE"
                elif str(targets[0][5]) != str(source_workspace_id):
                    status = MigrationReferenceStatus.QUARANTINED
                    error_code = "CROSS_WORKSPACE_REFERENCE"
                elif not relation_supported(str(source_type), relation_type):
                    status = MigrationReferenceStatus.QUARANTINED
                    error_code = "UNSUPPORTED_RELATION_TYPE"
                elif expected_source_type and str(targets[0][6]) != str(
                    expected_source_type
                ):
                    status = MigrationReferenceStatus.CONFLICT
                    error_code = "REFERENCE_SOURCE_TYPE_MISMATCH"
                elif expected_target_asset_type and str(targets[0][7]) != str(
                    expected_target_asset_type
                ):
                    status = MigrationReferenceStatus.CONFLICT
                    error_code = "REFERENCE_TARGET_TYPE_MISMATCH"
                elif expected_content_hash and str(targets[0][8]) != str(
                    expected_content_hash
                ):
                    status = MigrationReferenceStatus.CONFLICT
                    error_code = "REFERENCE_CONTENT_HASH_MISMATCH"
                elif str(cardinality) == "ONE" and len(targets) != 1:
                    status = MigrationReferenceStatus.CONFLICT
                    error_code = "REFERENCE_CARDINALITY_CONFLICT"
                if status is MigrationReferenceStatus.RESOLVED:
                    target = targets[0]
                    uow.cursor.execute(
                        """
                        UPDATE authority_legacy_migration_reference
                        SET target_item_id=%s, target_asset_id=%s,
                            target_asset_version_id=%s,
                            target_domain_projection_id=%s,
                            resolution_status='RESOLVED', resolved_at=NOW(),
                            evidence=evidence || %s, updated_at=NOW()
                        WHERE migration_reference_id=%s
                          AND resolution_status='UNRESOLVED'
                        """,
                        [
                            target[0],
                            target[2],
                            target[3],
                            str(target[4] or ""),
                            Jsonb(
                                {
                                    "resolved_business_key": business_key,
                                    "project_scope_match": True,
                                    "workspace_scope_match": True,
                                    "source_type_match": (
                                        not expected_source_type
                                        or str(target[6]) == str(expected_source_type)
                                    ),
                                    "target_type_match": (
                                        not expected_target_asset_type
                                        or str(target[7])
                                        == str(expected_target_asset_type)
                                    ),
                                    "content_hash_match": (
                                        not expected_content_hash
                                        or str(target[8])
                                        == str(expected_content_hash)
                                    ),
                                    "cardinality": cardinality,
                                }
                            ),
                            reference_id,
                        ],
                    )
                else:
                    uow.cursor.execute(
                        """
                        UPDATE authority_legacy_migration_reference
                        SET resolution_status=%s,
                            evidence=evidence || %s, updated_at=NOW()
                        WHERE migration_reference_id=%s
                          AND resolution_status='UNRESOLVED'
                        """,
                        [status.value, Jsonb({"error_code": error_code}), reference_id],
                    )
                    if status is not MigrationReferenceStatus.OPTIONAL_MISSING:
                        uow.cursor.execute(
                            """
                            UPDATE authority_legacy_migration_item
                            SET status='QUARANTINED', decision='QUARANTINE',
                                error_code=%s, reference_state=%s,
                                archival_state='REFERENCES_PENDING',
                                error_detail=%s, updated_at=NOW()
                            WHERE migration_item_id=%s
                            """,
                            [
                                error_code,
                                status.value,
                                f"reference resolution failed: {business_key}",
                                source_item_id,
                            ],
                        )
                uow.commit()
            if status not in {
                MigrationReferenceStatus.RESOLVED,
                MigrationReferenceStatus.OPTIONAL_MISSING,
            }:
                record = records_by_item.get(str(source_item_id))
                if record is not None:
                    failed_record = _with_error(
                        record,
                        error_code,
                        f"reference resolution failed: {business_key}",
                    )
                    self._quarantine(run_id, failed_record)
                    self._quarantine_or_reconcile_phase(run_id, failed_record)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                UPDATE authority_legacy_migration_item AS item
                SET reference_state=summary.reference_state,
                    archival_state=CASE
                        WHEN summary.reference_state='RESOLVED'
                            THEN 'REFERENCES_RESOLVED'
                        ELSE 'REFERENCES_PENDING'
                    END,
                    updated_at=NOW()
                FROM (
                    SELECT source_item_id,
                           CASE
                               WHEN BOOL_OR(resolution_status='CONFLICT') THEN 'CONFLICT'
                               WHEN BOOL_OR(resolution_status='QUARANTINED') THEN 'QUARANTINED'
                               WHEN BOOL_OR(resolution_status='UNRESOLVED') THEN 'UNRESOLVED'
                               WHEN BOOL_OR(resolution_status='OPTIONAL_MISSING') THEN 'OPTIONAL_MISSING'
                               ELSE 'RESOLVED'
                           END AS reference_state
                    FROM authority_legacy_migration_reference
                    WHERE migration_run_id=%s
                    GROUP BY source_item_id
                ) AS summary
                WHERE item.migration_item_id=summary.source_item_id
                """,
                [run_id],
            )
            uow.commit()
        self._quarantine_dependency_cycles(run_id, records_by_item)

    def _failed_count(self, run_id: str) -> int:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT COUNT(*) FROM authority_legacy_migration_item
                WHERE migration_run_id=%s AND status='FAILED'
                """,
                [run_id],
            )
            row = uow.cursor.fetchone()
        return int(row[0])

    def _quarantine(self, run_id: str, record: LegacySnapshotRecord) -> None:
        quarantine_id = _stable_id("quarantine", run_id, record.source_ref, record.source_hash)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                INSERT INTO authority_data_quarantine(
                    quarantine_id, migration_run_id, source_ref, reason_code,
                    payload_hash, payload, project_id, workspace_id, category,
                    source_payload, object_reference, source_size_bytes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (quarantine_id) DO NOTHING
                """,
                [
                    quarantine_id, run_id, record.source_ref,
                    record.error_code or "MIGRATION_POLICY_REJECTED", record.source_hash,
                    Jsonb({"errors": list(record.errors), "metadata": asdict(record)}),
                    record.project_id, record.workspace_id, record.category,
                    Jsonb(record.payload or {}),
                    Jsonb(
                        {
                            "provider": "unresolved",
                            "object_key": f"legacy-snapshot/{record.source_hash.removeprefix('sha256:')}",
                            "expected_hash": record.source_hash,
                            "expected_size": record.size_bytes,
                            "verification_status": "REQUIRED" if record.payload is None else "INLINE_VERIFIED",
                        }
                    ),
                    record.size_bytes,
                ],
            )
            uow.commit()

    def _checkpoint(
        self, run_id: str, ordinal: int, imported: int, quarantined: int, skipped: int, failed: int
    ) -> None:
        counts = {"imported": imported, "quarantined": quarantined, "skipped": skipped, "failed": failed}
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                UPDATE authority_migration_run
                SET cursor_state=%s, counts=%s, phase='CLASSIFY',
                    checkpoint_hash=%s, updated_at=NOW()
                WHERE migration_run_id=%s
                """,
                [
                    Jsonb({"last_ordinal": ordinal}),
                    Jsonb(counts),
                    _checkpoint_hash(run_id, ordinal, counts),
                    run_id,
                ],
            )
            uow.commit()

    def _finish_run(
        self, run_id: str, status: str, imported: int, quarantined: int, skipped: int, failed: int
    ) -> None:
        counts = {"imported": imported, "quarantined": quarantined, "skipped": skipped, "failed": failed}
        completion_level = (
            MigrationRunCompletionLevel.DOMAIN_RECONCILED.value
            if status == MigrationRunStatus.DOMAIN_RECONCILED.value
            else (
                MigrationRunCompletionLevel.ARCHIVAL_RECONCILED.value
                if status
                in {
                    MigrationRunStatus.ARCHIVAL_RECONCILED.value,
                    MigrationRunStatus.DOMAIN_REVIEW_PENDING.value,
                    MigrationRunStatus.DOMAIN_ACTIVATION_PARTIAL.value,
                }
                else MigrationRunCompletionLevel.NONE.value
            )
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                UPDATE authority_migration_run
                SET status=%s, counts=%s, report=%s, phase='RECONCILE',
                    run_completion_level=%s,
                    required_verification_level='ARCHIVAL_NATIVE',
                    updated_at=NOW(), finished_at=NOW()
                WHERE migration_run_id=%s
                """,
                [
                    status,
                    Jsonb(counts),
                    Jsonb(
                        {
                            "counts": counts,
                            "native_conversion": True,
                            "phase": "RECONCILE",
                        }
                    ),
                    completion_level,
                    run_id,
                ],
            )
            uow.commit()

    def _derive_import_run_status(
        self, run_id: str, *, failed: int, quarantined: int
    ) -> str:
        if failed:
            return MigrationRunStatus.FAILED.value
        if quarantined:
            return MigrationRunStatus.QUARANTINED.value
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT
                    COUNT(*) FILTER (
                        WHERE target_materialization_level='DOMAIN_NATIVE'
                    ),
                    COUNT(*) FILTER (
                        WHERE materialization_level='DOMAIN_NATIVE'
                          AND status='ACTIVATED'
                    ),
                    COUNT(*) FILTER (
                        WHERE target_materialization_level='DOMAIN_NATIVE'
                          AND materialization_level<>'DOMAIN_NATIVE'
                    )
                FROM authority_legacy_migration_item
                WHERE migration_run_id=%s
                """,
                [run_id],
            )
            domain_count, activated_count, pending_count = (
                int(value) for value in uow.cursor.fetchone()
            )
        if pending_count:
            return (
                MigrationRunStatus.DOMAIN_ACTIVATION_PARTIAL.value
                if activated_count
                else MigrationRunStatus.DOMAIN_REVIEW_PENDING.value
            )
        if domain_count:
            return MigrationRunStatus.DOMAIN_ACTIVATION_PARTIAL.value
        return MigrationRunStatus.ARCHIVAL_RECONCILED.value

    def _mark_run_domain_activation_progress(self, run_id: str) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT COUNT(*) FILTER (
                           WHERE target_materialization_level='DOMAIN_NATIVE'
                             AND materialization_level='DOMAIN_NATIVE'
                       )
                FROM authority_legacy_migration_item
                WHERE migration_run_id=%s
                """,
                [run_id],
            )
            activated_count = int(uow.cursor.fetchone()[0])
            if activated_count:
                uow.cursor.execute(
                    """
                    UPDATE authority_migration_run
                    SET status='DOMAIN_ACTIVATION_PARTIAL',
                        run_completion_level='ARCHIVAL_RECONCILED',
                        updated_at=NOW(), finished_at=NULL
                    WHERE migration_run_id=%s
                      AND status NOT IN ('FAILED','QUARANTINED','CANCELLED')
                    """,
                    [run_id],
                )
            uow.commit()

    def _asset_id_for_version(self, asset_version_id: str) -> str:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                "SELECT asset_id FROM authority_asset_version WHERE asset_version_id = %s",
                [asset_version_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("MIGRATION_TARGET_MISSING", "native project AssetVersion is missing")
        return str(row[0])

    def _persist_reconciliation(
        self, migration_run_id: str, reconciliation: dict[str, Any]
    ) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                UPDATE authority_migration_run
                SET phase='RECONCILE', reconciliation=%s,
                    report=report || %s, status=%s,
                    run_completion_level=%s,
                    required_verification_level=%s,
                    updated_at=NOW(),
                    finished_at=CASE
                        WHEN %s IN ('ARCHIVAL_RECONCILED','DOMAIN_RECONCILED',
                                    'QUARANTINED','FAILED','CANCELLED')
                        THEN NOW() ELSE finished_at END
                WHERE migration_run_id=%s
                """,
                [
                    Jsonb(reconciliation),
                    Jsonb({"reconciliation": reconciliation}),
                    reconciliation["status"],
                    reconciliation["run_completion_level"],
                    reconciliation["required_level"],
                    reconciliation["status"],
                    migration_run_id,
                ],
            )
            uow.commit()


def _remove_paths(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _remove_paths(child)
            for key, child in value.items()
            if not str(key).lower().endswith(("_path", "_file", "_directory"))
        }
    if isinstance(value, list):
        return [_remove_paths(child) for child in value]
    return value


def _with_error(record: LegacySnapshotRecord, code: str, message: str) -> LegacySnapshotRecord:
    from dataclasses import replace

    return replace(
        record,
        decision="QUARANTINE",
        status="QUARANTINED",
        error_code=code,
        errors=(*record.errors, message),
    )


def _stable_id(*parts: str) -> str:
    return str(uuid5(NAMESPACE_URL, "\x1f".join(parts)))


def _checkpoint_hash(
    run_id: str, ordinal: int, counts: dict[str, int]
) -> str:
    import hashlib
    import json

    encoded = json.dumps(
        {"run_id": run_id, "ordinal": ordinal, "counts": counts},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = ["LegacyMigrationService"]

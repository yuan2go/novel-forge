from __future__ import annotations


MIGRATION_ID = "20260804_0058_authority_cutover_release_qualification"
DOWN_REVISION = "20260804_0057_hot_query_governance"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = (
    "Restore the pre-0058 backup for a full rollback. Additive phase, reference, "
    "decision, reconciliation, worker-health, and outbox-fence structures can be "
    "forward-fixed without rewriting immutable Authority AssetVersions."
)


UPGRADE_STATEMENTS = [
    """
    ALTER TABLE authority_legacy_migration_item
        ADD COLUMN materialization_level TEXT NOT NULL DEFAULT 'ARCHIVAL_NATIVE',
        ADD COLUMN target_materialization_level TEXT NOT NULL DEFAULT 'ARCHIVAL_NATIVE',
        ADD COLUMN domain_adapter TEXT NOT NULL DEFAULT '',
        ADD COLUMN domain_validator TEXT NOT NULL DEFAULT '',
        ADD COLUMN projection_strategy TEXT NOT NULL DEFAULT '',
        ADD COLUMN activation_strategy TEXT NOT NULL DEFAULT 'EXPLICIT_APPROVAL_REQUIRED',
        ADD COLUMN domain_projection_id TEXT NOT NULL DEFAULT '',
        ADD COLUMN item_version BIGINT NOT NULL DEFAULT 0,
        ADD COLUMN phase_version BIGINT NOT NULL DEFAULT 0,
        ADD COLUMN phase_started_at TIMESTAMPTZ,
        ADD COLUMN phase_completed_at TIMESTAMPTZ,
        ADD COLUMN phase_attempt_count INTEGER NOT NULL DEFAULT 0,
        ADD COLUMN phase_input_hash TEXT NOT NULL DEFAULT '',
        ADD COLUMN phase_output_hash TEXT NOT NULL DEFAULT '',
        ADD COLUMN phase_evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
        ADD COLUMN error_detail TEXT NOT NULL DEFAULT '',
        ADD COLUMN next_phase TEXT NOT NULL DEFAULT 'CLASSIFY',
        ADD COLUMN reference_state TEXT NOT NULL DEFAULT 'UNRESOLVED',
        ADD CONSTRAINT authority_legacy_migration_item_materialization_check
            CHECK (materialization_level IN ('ARCHIVAL_NATIVE','DOMAIN_NATIVE')),
        ADD CONSTRAINT authority_legacy_migration_item_target_materialization_check
            CHECK (target_materialization_level IN ('ARCHIVAL_NATIVE','DOMAIN_NATIVE')),
        ADD CONSTRAINT authority_legacy_migration_item_version_check
            CHECK (item_version >= 0 AND phase_version >= 0 AND phase_attempt_count >= 0),
        ADD CONSTRAINT authority_legacy_migration_item_next_phase_check CHECK (
            next_phase IN (
                'SCAN','CLASSIFY','IMPORT_CANDIDATE','SEMANTIC_CONVERT',
                'VALIDATE','QUALIFY','ACTIVATE','QUARANTINE','RECONCILE','COMPLETE'
            )
        ),
        ADD CONSTRAINT authority_legacy_migration_item_reference_state_check CHECK (
            reference_state IN (
                'UNRESOLVED','RESOLVED','QUARANTINED','OPTIONAL_MISSING','CONFLICT'
            )
        )
    """,
    """
    CREATE TABLE authority_legacy_migration_phase_evidence (
        phase_evidence_id TEXT PRIMARY KEY,
        migration_run_id TEXT NOT NULL
            REFERENCES authority_migration_run(migration_run_id),
        migration_item_id TEXT NOT NULL
            REFERENCES authority_legacy_migration_item(migration_item_id),
        phase TEXT NOT NULL,
        phase_version BIGINT NOT NULL,
        attempt_count INTEGER NOT NULL,
        input_hash TEXT NOT NULL,
        output_hash TEXT NOT NULL DEFAULT '',
        evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
        error_code TEXT NOT NULL DEFAULT '',
        error_detail TEXT NOT NULL DEFAULT '',
        next_phase TEXT NOT NULL,
        started_at TIMESTAMPTZ NOT NULL,
        completed_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(migration_item_id, phase_version),
        CHECK (phase IN (
            'SCAN','CLASSIFY','IMPORT_CANDIDATE','SEMANTIC_CONVERT',
            'VALIDATE','QUALIFY','ACTIVATE','QUARANTINE','RECONCILE'
        )),
        CHECK (next_phase IN (
            'SCAN','CLASSIFY','IMPORT_CANDIDATE','SEMANTIC_CONVERT',
            'VALIDATE','QUALIFY','ACTIVATE','QUARANTINE','RECONCILE','COMPLETE'
        )),
        CHECK (phase_version > 0 AND attempt_count > 0),
        CHECK (input_hash LIKE 'sha256:%'),
        CHECK (output_hash = '' OR output_hash LIKE 'sha256:%')
    )
    """,
    """
    CREATE INDEX authority_legacy_migration_phase_resume_v2_idx
    ON authority_legacy_migration_item(
        migration_run_id, next_phase, item_version, updated_at, migration_item_id
    ) WHERE next_phase <> 'COMPLETE'
    """,
    """
    CREATE INDEX authority_legacy_migration_phase_evidence_item_idx
    ON authority_legacy_migration_phase_evidence(
        migration_item_id, phase_version DESC
    )
    """,
    """
    CREATE INDEX authority_legacy_migration_phase_evidence_run_idx
    ON authority_legacy_migration_phase_evidence(migration_run_id)
    """,
    """
    CREATE TABLE authority_legacy_migration_reference (
        migration_reference_id TEXT PRIMARY KEY,
        migration_run_id TEXT NOT NULL
            REFERENCES authority_migration_run(migration_run_id),
        source_item_id TEXT NOT NULL
            REFERENCES authority_legacy_migration_item(migration_item_id),
        reference_ordinal INTEGER NOT NULL,
        legacy_business_key TEXT NOT NULL,
        relation_type TEXT NOT NULL,
        optional BOOLEAN NOT NULL DEFAULT FALSE,
        target_item_id TEXT
            REFERENCES authority_legacy_migration_item(migration_item_id),
        target_asset_id TEXT REFERENCES authority_asset(asset_id),
        target_asset_version_id TEXT
            REFERENCES authority_asset_version(asset_version_id),
        target_domain_projection_id TEXT NOT NULL DEFAULT '',
        resolution_status TEXT NOT NULL DEFAULT 'UNRESOLVED',
        evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
        resolved_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(migration_run_id, source_item_id, reference_ordinal),
        CHECK (reference_ordinal >= 0),
        CHECK (legacy_business_key <> '' AND relation_type <> ''),
        CHECK (resolution_status IN (
            'UNRESOLVED','RESOLVED','QUARANTINED','OPTIONAL_MISSING','CONFLICT'
        )),
        CHECK (
            resolution_status <> 'RESOLVED'
            OR (
                target_item_id IS NOT NULL
                AND target_asset_id IS NOT NULL
                AND target_asset_version_id IS NOT NULL
                AND resolved_at IS NOT NULL
            )
        )
    )
    """,
    """
    CREATE UNIQUE INDEX authority_legacy_migration_reference_edge_identity_idx
    ON authority_legacy_migration_reference(
        migration_run_id, source_item_id, reference_ordinal,
        target_asset_version_id, relation_type
    ) WHERE target_asset_version_id IS NOT NULL
    """,
    """
    CREATE INDEX authority_legacy_migration_reference_target_idx
    ON authority_legacy_migration_reference(
        migration_run_id, legacy_business_key, resolution_status
    )
    """,
    """
    CREATE INDEX authority_legacy_migration_reference_target_item_fk_idx
    ON authority_legacy_migration_reference(target_item_id)
    """,
    """
    CREATE INDEX authority_legacy_migration_reference_target_asset_fk_idx
    ON authority_legacy_migration_reference(target_asset_id)
    """,
    """
    CREATE TABLE authority_legacy_migration_decision (
        migration_decision_id TEXT PRIMARY KEY,
        migration_run_id TEXT NOT NULL
            REFERENCES authority_migration_run(migration_run_id),
        migration_item_id TEXT NOT NULL
            REFERENCES authority_legacy_migration_item(migration_item_id),
        decision_version BIGINT NOT NULL,
        actor_id TEXT NOT NULL,
        decision TEXT NOT NULL,
        reason TEXT NOT NULL,
        expected_item_version BIGINT NOT NULL,
        source_hash TEXT NOT NULL,
        target_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        domain_validation_evidence JSONB NOT NULL,
        idempotency_key TEXT NOT NULL,
        operation_id TEXT REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(migration_item_id, decision_version),
        UNIQUE(migration_run_id, idempotency_key),
        CHECK (decision_version > 0 AND expected_item_version >= 0),
        CHECK (actor_id <> '' AND reason <> '' AND idempotency_key <> ''),
        CHECK (decision IN ('APPROVE','REJECT')),
        CHECK (source_hash LIKE 'sha256:%')
    )
    """,
    """
    CREATE TABLE authority_legacy_migration_domain_reconciliation (
        domain_reconciliation_id TEXT PRIMARY KEY,
        migration_run_id TEXT NOT NULL
            REFERENCES authority_migration_run(migration_run_id),
        migration_item_id TEXT NOT NULL
            REFERENCES authority_legacy_migration_item(migration_item_id),
        domain_adapter TEXT NOT NULL,
        status TEXT NOT NULL,
        projection_id TEXT NOT NULL DEFAULT '',
        expected_version BIGINT,
        actual_version BIGINT,
        evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
        reconciled_by_operation_id TEXT
            REFERENCES authority_operation(operation_id),
        reconciled_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(migration_item_id, domain_adapter),
        CHECK (domain_adapter <> ''),
        CHECK (status IN ('PASS','FAIL','NEEDS_REVIEW','NOT_APPLICABLE'))
    )
    """,
    """
    CREATE INDEX authority_legacy_migration_decision_target_version_fk_idx
    ON authority_legacy_migration_decision(target_asset_version_id)
    """,
    """
    CREATE INDEX authority_legacy_migration_decision_operation_fk_idx
    ON authority_legacy_migration_decision(operation_id)
    """,
    """
    CREATE INDEX authority_legacy_migration_reconciliation_run_fk_idx
    ON authority_legacy_migration_domain_reconciliation(migration_run_id)
    """,
    """
    CREATE INDEX authority_legacy_migration_reconciliation_operation_fk_idx
    ON authority_legacy_migration_domain_reconciliation(reconciled_by_operation_id)
    """,
    """
    ALTER TABLE authority_worker_health_projection
        ADD COLUMN active_attempt_id TEXT NOT NULL DEFAULT '',
        ADD COLUMN last_heartbeat_at TIMESTAMPTZ,
        ADD COLUMN completed_batch_count BIGINT NOT NULL DEFAULT 0,
        ADD COLUMN completed_operation_count BIGINT NOT NULL DEFAULT 0,
        ADD COLUMN failed_operation_count BIGINT NOT NULL DEFAULT 0,
        ADD COLUMN last_database_error TEXT NOT NULL DEFAULT '',
        ADD CONSTRAINT authority_worker_health_completed_batch_nonnegative
            CHECK (completed_batch_count >= 0),
        ADD CONSTRAINT authority_worker_health_completed_operation_nonnegative
            CHECK (completed_operation_count >= 0),
        ADD CONSTRAINT authority_worker_health_failed_operation_nonnegative
            CHECK (failed_operation_count >= 0)
    """,
    """
    UPDATE authority_worker_health_projection
    SET completed_batch_count=completed_count,
        failed_operation_count=failed_count,
        last_heartbeat_at=updated_at
    """,
    """
    ALTER TABLE outbox_event
        ADD COLUMN lease_id TEXT NOT NULL DEFAULT '',
        ADD COLUMN fencing_token BIGINT NOT NULL DEFAULT 0,
        ADD COLUMN runtime_group TEXT NOT NULL DEFAULT '',
        ADD CONSTRAINT outbox_event_fencing_token_nonnegative
            CHECK (fencing_token >= 0)
    """,
    """
    CREATE INDEX authority_worker_health_active_operation_idx
    ON authority_worker_health_projection(active_operation_id)
    WHERE active_operation_id IS NOT NULL
    """,
    """
    CREATE INDEX authority_attempt_worker_health_idx
    ON authority_attempt(worker_id, status, started_at DESC, attempt_number DESC)
    WHERE worker_id <> ''
    """,
    """
    CREATE INDEX outbox_event_worker_health_idx
    ON outbox_event(claimed_by, status, claimed_at DESC)
    WHERE claimed_by <> ''
    """,
]


DOWNGRADE_STATEMENTS: list[str] = []

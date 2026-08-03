from __future__ import annotations

MIGRATION_ID = "20260801_0043_project_workspace_and_legacy_migration_authority"
DOWN_REVISION = "20260730_0042_reader_calibration"


UPGRADE_STATEMENTS = [
    # Close foreign-key query gaps left by the immediately preceding forward-only
    # planning migrations.  Keeping these here preserves their published semantics.
    "CREATE INDEX authority_book_chapter_request_parent_group_version_fk_idx ON authority_book_chapter_request(parent_group_version_id)",
    "CREATE INDEX authority_chapter_group_chapter_acceptance_operation_fk_idx ON authority_chapter_group_chapter(acceptance_operation_id)",
    "CREATE INDEX authority_chapter_group_chapter_outcome_version_fk_idx ON authority_chapter_group_chapter(chapter_outcome_version_id)",
    "CREATE INDEX authority_chapter_group_plan_adjustment_version_fk_idx ON authority_chapter_group_production(plan_adjustment_proposal_version_id)",
    "CREATE INDEX authority_chapter_group_active_request_fk_idx ON authority_chapter_group_production(active_chapter_request_id)",
    "CREATE INDEX authority_chapter_group_book_run_fk_idx ON authority_chapter_group_production(book_run_id)",
    "CREATE INDEX authority_chapter_group_recap_operation_fk_idx ON authority_chapter_group_production(recap_operation_id)",
    "CREATE INDEX authority_chapter_group_volume_plan_version_fk_idx ON authority_chapter_group_production(volume_plan_version_id)",
    "CREATE INDEX authority_child_delegation_plan_version_fk_idx ON authority_child_delegation(plan_version_id)",
    "CREATE INDEX authority_plan_change_impact_recorded_operation_fk_idx ON authority_plan_change_impact(recorded_by_operation_id)",
    "CREATE INDEX authority_plan_change_impact_source_version_fk_idx ON authority_plan_change_impact(source_asset_version_id)",
    "CREATE INDEX authority_plan_change_proposal_source_evidence_fk_idx ON authority_plan_change_proposal(source_evidence_version_id)",
    "CREATE INDEX authority_story_design_active_operation_fk_idx ON authority_story_design_active_version(activated_by_operation_id)",
    "CREATE INDEX authority_story_design_state_created_operation_fk_idx ON authority_story_design_version_state(created_by_operation_id)",
    "CREATE INDEX authority_story_design_state_updated_operation_fk_idx ON authority_story_design_version_state(updated_by_operation_id)",
    # Legacy migration candidates are immutable Authority versions but are not
    # production-active.  IMPORTED is deliberately a lifecycle state instead of
    # overloading DRAFT; eligibility and governance remain fail-closed until an
    # explicit review/decision creates a successor version.
    """
    ALTER TABLE authority_asset_version
    DROP CONSTRAINT authority_asset_version_lifecycle_check
    """,
    """
    ALTER TABLE authority_asset_version
    ADD CONSTRAINT authority_asset_version_lifecycle_check
    CHECK (lifecycle IN (
        'DRAFT', 'IMPORTED', 'ACTIVE', 'SUPERSEDED', 'RETIRED', 'DELETED'
    ))
    """,
    """
    ALTER TABLE authority_asset_qualification
    DROP CONSTRAINT authority_asset_qualification_decision_check
    """,
    """
    ALTER TABLE authority_asset_qualification
    ADD CONSTRAINT authority_asset_qualification_decision_check
    CHECK (decision IN (
        'PENDING_EVALUATION', 'ELIGIBLE', 'INELIGIBLE', 'REVOKED'
    ))
    """,
    """
    CREATE TABLE authority_project (
        project_id TEXT PRIMARY KEY,
        primary_workspace_id TEXT NOT NULL UNIQUE,
        title TEXT NOT NULL,
        series_title TEXT NOT NULL DEFAULT '',
        book_number INTEGER,
        status TEXT NOT NULL,
        stage TEXT NOT NULL,
        health TEXT NOT NULL,
        current_asset_version_id TEXT NOT NULL UNIQUE
            REFERENCES authority_asset_version(asset_version_id),
        created_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        last_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        version BIGINT NOT NULL DEFAULT 1,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CHECK (project_id <> '' AND primary_workspace_id <> '' AND title <> ''),
        CHECK (book_number IS NULL OR book_number > 0),
        CHECK (status IN ('ACTIVE', 'PAUSED', 'ARCHIVED', 'DELETED')),
        CHECK (stage IN (
            'DESIGN', 'PLANNING', 'PRODUCTION', 'REVIEW',
            'PUBLISHING', 'COMPLETED'
        )),
        CHECK (health IN ('UNKNOWN', 'HEALTHY', 'DEGRADED', 'BLOCKED')),
        CHECK (version > 0)
    )
    """,
    """
    CREATE TABLE authority_workspace (
        workspace_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        book_id TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL,
        current_asset_version_id TEXT NOT NULL UNIQUE
            REFERENCES authority_asset_version(asset_version_id),
        created_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        last_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        version BIGINT NOT NULL DEFAULT 1,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id, workspace_id),
        CHECK (workspace_id <> ''),
        CHECK (status IN ('ACTIVE', 'PAUSED', 'ARCHIVED', 'DELETED')),
        CHECK (version > 0)
    )
    """,
    """
    ALTER TABLE authority_project
    ADD CONSTRAINT authority_project_primary_workspace_fk
    FOREIGN KEY (primary_workspace_id)
    REFERENCES authority_workspace(workspace_id)
    DEFERRABLE INITIALLY DEFERRED
    """,
    """
    CREATE TABLE authority_project_binding (
        binding_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        workspace_id TEXT REFERENCES authority_workspace(workspace_id),
        binding_type TEXT NOT NULL,
        target_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        created_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        superseded_by_operation_id TEXT
            REFERENCES authority_operation(operation_id),
        active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        superseded_at TIMESTAMPTZ,
        CHECK (binding_type IN (
            'BOOK', 'PLATFORM_PROFILE', 'GENRE_MARKET_PROFILE',
            'QUALITY_STANDARD_PROFILE', 'STYLE_PROFILE',
            'CONTINUITY_BIBLE', 'PRODUCTION_PROFILE'
        )),
        CHECK ((active AND superseded_at IS NULL) OR
               (NOT active AND superseded_at IS NOT NULL))
    )
    """,
    """
    CREATE UNIQUE INDEX authority_project_binding_one_active_idx
    ON authority_project_binding(
        project_id, COALESCE(workspace_id, ''), binding_type
    ) WHERE active
    """,
    """
    CREATE INDEX authority_project_query_idx
    ON authority_project(status, updated_at DESC, project_id)
    """,
    """
    CREATE INDEX authority_workspace_project_query_idx
    ON authority_workspace(project_id, status, updated_at DESC)
    """,
    "CREATE INDEX authority_project_created_operation_fk_idx ON authority_project(created_by_operation_id)",
    "CREATE INDEX authority_project_last_operation_fk_idx ON authority_project(last_operation_id)",
    "CREATE INDEX authority_workspace_created_operation_fk_idx ON authority_workspace(created_by_operation_id)",
    "CREATE INDEX authority_workspace_last_operation_fk_idx ON authority_workspace(last_operation_id)",
    """
    CREATE INDEX authority_project_binding_target_fk_idx
    ON authority_project_binding(target_asset_version_id)
    """,
    """
    CREATE INDEX authority_project_binding_operation_fk_idx
    ON authority_project_binding(created_by_operation_id)
    """,
    "CREATE INDEX authority_project_binding_workspace_fk_idx ON authority_project_binding(workspace_id)",
    "CREATE INDEX authority_project_binding_superseded_operation_fk_idx ON authority_project_binding(superseded_by_operation_id)",
    """
    ALTER TABLE authority_migration_run
        ADD COLUMN workspace_id TEXT NOT NULL DEFAULT '',
        ADD COLUMN operation_id TEXT REFERENCES authority_operation(operation_id),
        ADD COLUMN snapshot_hash TEXT NOT NULL DEFAULT '',
        ADD COLUMN mode TEXT NOT NULL DEFAULT 'IMPORT',
        ADD COLUMN idempotency_key TEXT,
        ADD COLUMN cursor_state JSONB NOT NULL DEFAULT '{}'::jsonb,
        ADD COLUMN counts JSONB NOT NULL DEFAULT '{}'::jsonb,
        ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        ADD COLUMN finished_at TIMESTAMPTZ
    """,
    """
    CREATE UNIQUE INDEX authority_migration_run_idempotency_idx
    ON authority_migration_run(source_kind, idempotency_key)
    WHERE idempotency_key IS NOT NULL
    """,
    "CREATE INDEX authority_migration_run_operation_fk_idx ON authority_migration_run(operation_id)",
    """
    CREATE TABLE authority_legacy_migration_item (
        migration_item_id TEXT PRIMARY KEY,
        migration_run_id TEXT NOT NULL
            REFERENCES authority_migration_run(migration_run_id),
        project_id TEXT NOT NULL DEFAULT '',
        workspace_id TEXT NOT NULL DEFAULT '',
        source_ref TEXT NOT NULL,
        source_category TEXT NOT NULL,
        source_hash TEXT NOT NULL,
        stable_business_key TEXT NOT NULL,
        operation_id TEXT REFERENCES authority_operation(operation_id),
        target_asset_id TEXT REFERENCES authority_asset(asset_id),
        target_asset_version_id TEXT
            REFERENCES authority_asset_version(asset_version_id),
        status TEXT NOT NULL,
        decision TEXT NOT NULL,
        error_code TEXT NOT NULL DEFAULT '',
        evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(migration_run_id, source_ref),
        UNIQUE(migration_run_id, stable_business_key, source_hash),
        CHECK (source_ref <> '' AND source_category <> ''),
        CHECK (source_hash LIKE 'sha256:%'),
        CHECK (status IN (
            'DISCOVERED', 'VALIDATED', 'IMPORTED', 'NEEDS_REVIEW',
            'QUARANTINED', 'INELIGIBLE', 'SKIPPED_DUPLICATE', 'FAILED'
        )),
        CHECK (decision IN (
            'PENDING', 'IMPORT', 'REBUILD', 'DISCARD_REBUILDABLE',
            'QUARANTINE', 'REJECT'
        ))
    )
    """,
    """
    CREATE INDEX authority_legacy_migration_item_resume_idx
    ON authority_legacy_migration_item(
        migration_run_id, status, updated_at, migration_item_id
    )
    """,
    "CREATE INDEX authority_legacy_migration_item_asset_fk_idx ON authority_legacy_migration_item(target_asset_id)",
    "CREATE INDEX authority_legacy_migration_item_version_fk_idx ON authority_legacy_migration_item(target_asset_version_id)",
    "CREATE INDEX authority_legacy_migration_item_operation_fk_idx ON authority_legacy_migration_item(operation_id)",
    """
    ALTER TABLE authority_data_quarantine
        ADD COLUMN project_id TEXT NOT NULL DEFAULT '',
        ADD COLUMN workspace_id TEXT NOT NULL DEFAULT '',
        ADD COLUMN category TEXT NOT NULL DEFAULT '',
        ADD COLUMN resolution_status TEXT NOT NULL DEFAULT 'OPEN',
        ADD COLUMN resolved_by_operation_id TEXT
            REFERENCES authority_operation(operation_id),
        ADD COLUMN resolved_at TIMESTAMPTZ,
        ADD CONSTRAINT authority_data_quarantine_resolution_check
        CHECK (resolution_status IN ('OPEN', 'ACCEPTED', 'REJECTED', 'REPAIRED'))
    """,
    """
    CREATE INDEX authority_data_quarantine_open_idx
    ON authority_data_quarantine(resolution_status, created_at DESC)
    WHERE resolution_status = 'OPEN'
    """,
    "CREATE INDEX authority_data_quarantine_resolution_operation_fk_idx ON authority_data_quarantine(resolved_by_operation_id)",
]


# Forward-only Authority migration. Restore uses the pre-migration database
# backup plus the snapshot/hash rehearsal documented by the migration runbook.
DOWNGRADE_STATEMENTS: list[str] = []

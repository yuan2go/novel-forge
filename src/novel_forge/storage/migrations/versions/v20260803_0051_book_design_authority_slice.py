from __future__ import annotations

MIGRATION_ID = "20260803_0051_book_design_authority_slice"
DOWN_REVISION = "20260801_0050_mkaos_authority"


UPGRADE_STATEMENTS = [
    "ALTER TABLE authority_asset_version ADD COLUMN schema_version TEXT NOT NULL DEFAULT 'legacy-unversioned.v1'",
    "ALTER TABLE authority_asset_version ADD CONSTRAINT authority_asset_version_schema_version_check CHECK (schema_version ~ '^[a-z0-9][a-z0-9._-]*\\.v[0-9]+$')",
    "ALTER TABLE authority_blob ADD COLUMN retention_class TEXT NOT NULL DEFAULT 'STANDARD'",
    "ALTER TABLE authority_blob ADD COLUMN encryption_metadata JSONB NOT NULL DEFAULT '{}'::jsonb",
    "ALTER TABLE authority_blob ADD COLUMN retention_until TIMESTAMPTZ",
    "ALTER TABLE authority_blob ADD COLUMN orphan_detected_at TIMESTAMPTZ",
    "ALTER TABLE authority_blob ADD COLUMN gc_eligible_at TIMESTAMPTZ",
    "ALTER TABLE authority_blob ADD COLUMN gc_operation_id TEXT REFERENCES authority_operation(operation_id)",
    "ALTER TABLE authority_blob ADD COLUMN last_verified_at TIMESTAMPTZ",
    "ALTER TABLE authority_blob ADD CONSTRAINT authority_blob_retention_class_check CHECK (retention_class IN ('EPHEMERAL', 'STANDARD', 'LONG_TERM', 'LEGAL_HOLD'))",
    "CREATE INDEX authority_blob_orphan_gc_idx ON authority_blob(status, gc_eligible_at) WHERE orphan_detected_at IS NOT NULL AND legal_hold = FALSE",
    "CREATE INDEX authority_blob_gc_operation_fk_idx ON authority_blob(gc_operation_id) WHERE gc_operation_id IS NOT NULL",
    """
    CREATE TABLE authority_book (
        book_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        workspace_id TEXT NOT NULL REFERENCES authority_workspace(workspace_id),
        principal_id TEXT NOT NULL,
        service_identity TEXT NOT NULL,
        book_scope JSONB NOT NULL,
        production_profile JSONB NOT NULL,
        runtime_policy JSONB NOT NULL,
        release_identity TEXT NOT NULL,
        status TEXT NOT NULL,
        current_book_asset_version_id TEXT NOT NULL UNIQUE
            REFERENCES authority_asset_version(asset_version_id),
        current_book_design_asset_version_id TEXT
            REFERENCES authority_asset_version(asset_version_id),
        created_by_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        last_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        version BIGINT NOT NULL DEFAULT 1,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id, workspace_id, book_id),
        CHECK (book_id <> '' AND principal_id <> '' AND service_identity <> ''),
        CHECK (release_identity <> ''),
        CHECK (status IN ('DESIGN_PENDING', 'DESIGN_ACTIVE', 'PAUSED', 'ARCHIVED')),
        CHECK (jsonb_typeof(book_scope) = 'object'),
        CHECK (jsonb_typeof(production_profile) = 'object'),
        CHECK (jsonb_typeof(runtime_policy) = 'object'),
        CHECK (version > 0)
    )
    """,
    """
    CREATE TABLE authority_asset_dependency (
        dependency_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        book_id TEXT NOT NULL REFERENCES authority_book(book_id),
        source_asset_version_id TEXT NOT NULL REFERENCES authority_asset_version(asset_version_id),
        target_asset_version_id TEXT NOT NULL REFERENCES authority_asset_version(asset_version_id),
        dependency_type TEXT NOT NULL,
        created_by_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(source_asset_version_id, target_asset_version_id, dependency_type),
        CHECK (source_asset_version_id <> target_asset_version_id),
        CHECK (dependency_type IN ('REQUIRED', 'DERIVED_FROM', 'CONSTRAINED_BY', 'EVALUATES', 'EFFECTIVE_AFTER'))
    )
    """,
    """
    CREATE TABLE authority_asset_decision (
        decision_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        book_id TEXT NOT NULL REFERENCES authority_book(book_id),
        asset_version_id TEXT NOT NULL REFERENCES authority_asset_version(asset_version_id),
        decision TEXT NOT NULL,
        reason TEXT NOT NULL,
        decided_by TEXT NOT NULL,
        decided_by_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        evidence JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(asset_version_id, decided_by_operation_id),
        CHECK (decision IN ('APPROVE', 'REJECT')),
        CHECK (reason <> '' AND decided_by <> '')
    )
    """,
    """
    CREATE TABLE authority_asset_activation (
        activation_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        book_id TEXT NOT NULL REFERENCES authority_book(book_id),
        asset_id TEXT NOT NULL REFERENCES authority_asset(asset_id),
        asset_version_id TEXT NOT NULL REFERENCES authority_asset_version(asset_version_id),
        decision_id TEXT NOT NULL REFERENCES authority_asset_decision(decision_id),
        activated_by_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        effective_from_chapter INTEGER,
        effective_to_chapter INTEGER,
        activation_reason TEXT NOT NULL,
        retired_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CHECK (effective_from_chapter IS NULL OR effective_from_chapter > 0),
        CHECK (effective_to_chapter IS NULL OR effective_to_chapter >= effective_from_chapter)
    )
    """,
    "CREATE UNIQUE INDEX authority_asset_activation_one_current_idx ON authority_asset_activation(asset_id, book_id) WHERE retired_at IS NULL",
    """
    CREATE TABLE authority_asset_supersession (
        supersession_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        book_id TEXT NOT NULL REFERENCES authority_book(book_id),
        previous_asset_version_id TEXT NOT NULL REFERENCES authority_asset_version(asset_version_id),
        successor_asset_version_id TEXT NOT NULL REFERENCES authority_asset_version(asset_version_id),
        superseded_by_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        reason TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(previous_asset_version_id, successor_asset_version_id),
        CHECK (previous_asset_version_id <> successor_asset_version_id)
    )
    """,
    """
    CREATE TABLE authority_asset_evidence (
        evidence_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        book_id TEXT NOT NULL REFERENCES authority_book(book_id),
        asset_version_id TEXT NOT NULL REFERENCES authority_asset_version(asset_version_id),
        evidence_type TEXT NOT NULL,
        schema_version TEXT NOT NULL,
        evidence JSONB NOT NULL,
        evidence_hash TEXT NOT NULL,
        created_by_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(asset_version_id, evidence_type, evidence_hash),
        CHECK (evidence_hash LIKE 'sha256:%')
    )
    """,
    """
    CREATE TABLE authority_book_design_candidate (
        candidate_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        workspace_id TEXT NOT NULL REFERENCES authority_workspace(workspace_id),
        book_id TEXT NOT NULL REFERENCES authority_book(book_id),
        asset_id TEXT NOT NULL REFERENCES authority_asset(asset_id),
        asset_version_id TEXT NOT NULL UNIQUE REFERENCES authority_asset_version(asset_version_id),
        schema_version TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        status TEXT NOT NULL,
        created_by_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        last_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CHECK (status IN ('VALIDATED', 'APPROVED', 'REJECTED', 'ACTIVE', 'SUPERSEDED')),
        CHECK (content_hash LIKE 'sha256:%')
    )
    """,
    "CREATE INDEX authority_book_design_query_idx ON authority_book_design_candidate(book_id, status, created_at DESC)",
    """
    CREATE TABLE authority_slice_legacy_cutover (
        slice_key TEXT PRIMARY KEY,
        legacy_source TEXT NOT NULL,
        authority_target TEXT NOT NULL,
        discovery_status TEXT NOT NULL,
        import_status TEXT NOT NULL,
        validation_status TEXT NOT NULL,
        writer_cutover_status TEXT NOT NULL,
        reader_compatibility_until DATE NOT NULL,
        retirement_deadline DATE NOT NULL,
        recorded_by_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        evidence JSONB NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CHECK (writer_cutover_status = 'DISABLED'),
        CHECK (retirement_deadline >= reader_compatibility_until)
    )
    """,
    "CREATE INDEX authority_book_project_workspace_idx ON authority_book(project_id, workspace_id, status, updated_at DESC)",
    "CREATE INDEX authority_book_workspace_fk_idx ON authority_book(workspace_id)",
    "CREATE INDEX authority_book_current_design_fk_idx ON authority_book(current_book_design_asset_version_id) WHERE current_book_design_asset_version_id IS NOT NULL",
    "CREATE INDEX authority_book_created_operation_fk_idx ON authority_book(created_by_operation_id)",
    "CREATE INDEX authority_book_last_operation_fk_idx ON authority_book(last_operation_id)",
    "CREATE INDEX authority_asset_dependency_project_fk_idx ON authority_asset_dependency(project_id)",
    "CREATE INDEX authority_asset_dependency_book_fk_idx ON authority_asset_dependency(book_id)",
    "CREATE INDEX authority_asset_dependency_target_idx ON authority_asset_dependency(target_asset_version_id)",
    "CREATE INDEX authority_asset_dependency_created_operation_fk_idx ON authority_asset_dependency(created_by_operation_id)",
    "CREATE INDEX authority_asset_decision_project_fk_idx ON authority_asset_decision(project_id)",
    "CREATE INDEX authority_asset_decision_book_fk_idx ON authority_asset_decision(book_id)",
    "CREATE INDEX authority_asset_decision_target_idx ON authority_asset_decision(asset_version_id, created_at DESC)",
    "CREATE INDEX authority_asset_decision_operation_fk_idx ON authority_asset_decision(decided_by_operation_id)",
    "CREATE INDEX authority_asset_activation_project_fk_idx ON authority_asset_activation(project_id)",
    "CREATE INDEX authority_asset_activation_book_fk_idx ON authority_asset_activation(book_id)",
    "CREATE INDEX authority_asset_activation_version_fk_idx ON authority_asset_activation(asset_version_id)",
    "CREATE INDEX authority_asset_activation_decision_fk_idx ON authority_asset_activation(decision_id)",
    "CREATE INDEX authority_asset_activation_operation_fk_idx ON authority_asset_activation(activated_by_operation_id)",
    "CREATE INDEX authority_asset_supersession_project_fk_idx ON authority_asset_supersession(project_id)",
    "CREATE INDEX authority_asset_supersession_book_fk_idx ON authority_asset_supersession(book_id)",
    "CREATE INDEX authority_asset_supersession_successor_fk_idx ON authority_asset_supersession(successor_asset_version_id)",
    "CREATE INDEX authority_asset_supersession_operation_fk_idx ON authority_asset_supersession(superseded_by_operation_id)",
    "CREATE INDEX authority_asset_evidence_project_fk_idx ON authority_asset_evidence(project_id)",
    "CREATE INDEX authority_asset_evidence_book_fk_idx ON authority_asset_evidence(book_id)",
    "CREATE INDEX authority_asset_evidence_target_idx ON authority_asset_evidence(asset_version_id, evidence_type)",
    "CREATE INDEX authority_asset_evidence_operation_fk_idx ON authority_asset_evidence(created_by_operation_id)",
    "CREATE INDEX authority_book_design_project_fk_idx ON authority_book_design_candidate(project_id)",
    "CREATE INDEX authority_book_design_workspace_fk_idx ON authority_book_design_candidate(workspace_id)",
    "CREATE INDEX authority_book_design_asset_fk_idx ON authority_book_design_candidate(asset_id)",
    "CREATE INDEX authority_book_design_created_operation_fk_idx ON authority_book_design_candidate(created_by_operation_id)",
    "CREATE INDEX authority_book_design_last_operation_fk_idx ON authority_book_design_candidate(last_operation_id)",
    "CREATE INDEX authority_slice_cutover_operation_fk_idx ON authority_slice_legacy_cutover(recorded_by_operation_id)",
]


DOWNGRADE_STATEMENTS: list[str] = []

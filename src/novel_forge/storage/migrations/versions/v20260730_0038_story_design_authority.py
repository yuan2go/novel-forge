from __future__ import annotations

MIGRATION_ID = "20260730_0038_story_design_authority"
DOWN_REVISION = "20260730_0037_story_state_reducer_registry"

UPGRADE_STATEMENTS = [
    """
    CREATE TABLE authority_story_design_generator_definition (
        operation_name TEXT NOT NULL,
        definition_version TEXT NOT NULL,
        capability TEXT NOT NULL,
        output_candidate_type TEXT NOT NULL,
        definition JSONB NOT NULL,
        definition_hash TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY(operation_name, definition_version),
        UNIQUE(operation_name, definition_hash),
        CHECK (jsonb_typeof(definition) = 'object'),
        CHECK (definition_hash LIKE 'sha256:%'),
        CHECK (status IN ('ACTIVE', 'RETIRED'))
    )
    """,
    """
    CREATE TABLE authority_story_design_version_state (
        project_id TEXT NOT NULL,
        asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        logical_key TEXT NOT NULL,
        generator_operation_name TEXT NOT NULL,
        generator_definition_version TEXT NOT NULL,
        candidate_type TEXT NOT NULL,
        lifecycle TEXT NOT NULL,
        qualification TEXT NOT NULL,
        approval TEXT NOT NULL,
        freshness TEXT NOT NULL,
        planning_scope TEXT NOT NULL,
        source_kind TEXT NOT NULL,
        execution_evidence JSONB NOT NULL,
        semantic_repair_count INTEGER NOT NULL DEFAULT 0,
        structural_regeneration_count INTEGER NOT NULL DEFAULT 0,
        created_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        updated_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        version BIGINT NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY(project_id, asset_version_id),
        UNIQUE(project_id, logical_key, asset_version_id),
        FOREIGN KEY(generator_operation_name, generator_definition_version)
            REFERENCES authority_story_design_generator_definition(
                operation_name, definition_version
            ),
        CHECK (lifecycle IN (
            'CANDIDATE', 'MATERIALIZED', 'ACTIVE', 'SUPERSEDED', 'REJECTED'
        )),
        CHECK (qualification IN (
            'PENDING', 'STRUCTURALLY_VALID', 'SEMANTICALLY_VALID',
            'QUALIFIED', 'FAILED'
        )),
        CHECK (approval IN (
            'NOT_REQUESTED', 'PENDING', 'APPROVED', 'REJECTED'
        )),
        CHECK (freshness IN ('CURRENT', 'IMPACTED', 'STALE')),
        CHECK (planning_scope IN (
            'BOOK', 'VOLUME', 'ARC', 'CHAPTER_GROUP', 'CHAPTER'
        )),
        CHECK (source_kind IN ('GENERATED', 'LEGACY_IMPORT')),
        CHECK (jsonb_typeof(execution_evidence) = 'object'),
        CHECK (semantic_repair_count >= 0),
        CHECK (structural_regeneration_count >= 0)
    )
    """,
    """
    CREATE TABLE authority_story_design_transition (
        transition_operation_id TEXT PRIMARY KEY
            REFERENCES authority_operation(operation_id),
        project_id TEXT NOT NULL,
        asset_version_id TEXT NOT NULL,
        transition_type TEXT NOT NULL,
        from_version BIGINT NOT NULL,
        to_version BIGINT NOT NULL,
        evidence JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        FOREIGN KEY(project_id, asset_version_id)
            REFERENCES authority_story_design_version_state(
                project_id, asset_version_id
            ),
        UNIQUE(project_id, asset_version_id, to_version),
        CHECK (transition_type IN (
            'ENROLL', 'MATERIALIZE', 'STRUCTURAL_VALIDATE',
            'SEMANTIC_VALIDATE', 'QUALIFY', 'SUBMIT_APPROVAL',
            'APPROVE', 'ACTIVATE', 'REJECT'
        )),
        CHECK (to_version >= from_version),
        CHECK (jsonb_typeof(evidence) = 'object')
    )
    """,
    """
    CREATE TABLE authority_story_design_active_version (
        project_id TEXT NOT NULL,
        logical_key TEXT NOT NULL,
        asset_version_id TEXT NOT NULL,
        activated_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        activated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY(project_id, logical_key),
        UNIQUE(project_id, asset_version_id),
        FOREIGN KEY(project_id, asset_version_id)
            REFERENCES authority_story_design_version_state(
                project_id, asset_version_id
            )
    )
    """,
    """
    CREATE INDEX authority_story_design_state_query_idx
    ON authority_story_design_version_state(
        project_id, planning_scope, lifecycle, freshness, updated_at
    )
    """,
    """
    CREATE INDEX authority_story_design_generator_idx
    ON authority_story_design_version_state(
        generator_operation_name, generator_definition_version
    )
    """,
    """
    CREATE INDEX authority_story_design_transition_asset_idx
    ON authority_story_design_transition(
        project_id, asset_version_id, created_at
    )
    """,
]

DOWNGRADE_STATEMENTS: list[str] = []

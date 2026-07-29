from __future__ import annotations

MIGRATION_ID = "20260730_0039_hierarchical_planning"
DOWN_REVISION = "20260730_0038_story_design_authority"

UPGRADE_STATEMENTS = [
    """
    CREATE TABLE story_plan_binding (
        binding_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        contract_type TEXT NOT NULL,
        logical_key TEXT NOT NULL,
        asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        parent_version_id TEXT
            REFERENCES authority_asset_version(asset_version_id),
        execution_scope TEXT NOT NULL,
        freshness TEXT NOT NULL,
        created_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        version BIGINT NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id, asset_version_id),
        UNIQUE(project_id, book_id, logical_key, asset_version_id),
        CHECK (contract_type IN (
            'BOOK', 'VOLUME', 'ARC', 'CHAPTER_GROUP', 'CHAPTER'
        )),
        CHECK (execution_scope IN (
            'EXECUTED', 'FROZEN', 'PLANNED', 'SPECULATIVE'
        )),
        CHECK (freshness IN ('CURRENT', 'IMPACTED', 'STALE')),
        CHECK (
            (contract_type = 'BOOK' AND parent_version_id IS NULL)
            OR contract_type = 'ARC'
            OR (contract_type IN ('VOLUME', 'CHAPTER_GROUP', 'CHAPTER')
                AND parent_version_id IS NOT NULL)
        )
    )
    """,
    """
    CREATE TABLE story_plan_hierarchy (
        hierarchy_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        parent_binding_id TEXT NOT NULL
            REFERENCES story_plan_binding(binding_id),
        child_binding_id TEXT NOT NULL UNIQUE
            REFERENCES story_plan_binding(binding_id),
        relation_type TEXT NOT NULL,
        created_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id, parent_binding_id, child_binding_id),
        CHECK (relation_type IN (
            'BOOK_CONTAINS_VOLUME',
            'VOLUME_CONTAINS_CHAPTER_GROUP',
            'CHAPTER_GROUP_CONTAINS_CHAPTER'
        ))
    )
    """,
    """
    CREATE TABLE active_story_plan_version (
        project_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        logical_key TEXT NOT NULL,
        binding_id TEXT NOT NULL UNIQUE
            REFERENCES story_plan_binding(binding_id),
        asset_version_id TEXT NOT NULL,
        activated_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        activated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY(project_id, book_id, logical_key),
        UNIQUE(project_id, asset_version_id)
    )
    """,
    """
    CREATE TABLE asset_dependency_edge (
        dependency_edge_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        source_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        dependent_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        dependency_type TEXT NOT NULL,
        invalidation_policy TEXT NOT NULL,
        created_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(
            project_id, source_asset_version_id,
            dependent_asset_version_id, dependency_type
        ),
        CHECK (source_asset_version_id <> dependent_asset_version_id),
        CHECK (dependency_type IN (
            'PARENT_VERSION', 'ARC_CONTRIBUTION', 'CANON_DEPENDENCY',
            'CONTEXT_INPUT', 'PLAN_IMPACT'
        )),
        CHECK (invalidation_policy IN (
            'MARK_STALE', 'MARK_IMPACTED', 'REVALIDATE', 'NONE'
        ))
    )
    """,
    """
    CREATE TABLE planning_horizon (
        planning_horizon_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        executed_through_chapter INTEGER NOT NULL,
        frozen_through_chapter INTEGER NOT NULL,
        planned_through_chapter INTEGER NOT NULL,
        speculative_through_chapter INTEGER NOT NULL,
        active_book_plan_version_id TEXT NOT NULL,
        active_volume_plan_version_id TEXT,
        active_group_plan_version_id TEXT,
        active_chapter_plan_version_id TEXT,
        active_arc_ids JSONB NOT NULL,
        window_version BIGINT NOT NULL,
        based_on_canon_version TEXT NOT NULL,
        based_on_story_state_version TEXT NOT NULL,
        policy_version TEXT NOT NULL,
        status TEXT NOT NULL,
        updated_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id, book_id, window_version),
        CHECK (
            0 <= executed_through_chapter
            AND executed_through_chapter <= frozen_through_chapter
            AND frozen_through_chapter <= planned_through_chapter
            AND planned_through_chapter <= speculative_through_chapter
        ),
        CHECK (jsonb_typeof(active_arc_ids) = 'array'),
        CHECK (status IN ('CURRENT', 'SUPERSEDED'))
    )
    """,
    """
    CREATE UNIQUE INDEX planning_horizon_one_current_idx
    ON planning_horizon(project_id, book_id)
    WHERE status='CURRENT'
    """,
    """
    CREATE TABLE story_production_cursor (
        project_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        accepted_through_chapter INTEGER NOT NULL,
        active_group_plan_version_id TEXT,
        active_chapter_plan_version_id TEXT,
        story_state_version_id TEXT,
        canon_version_id TEXT,
        version BIGINT NOT NULL DEFAULT 0,
        updated_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY(project_id, book_id),
        CHECK (accepted_through_chapter >= 0)
    )
    """,
    """
    CREATE INDEX story_plan_binding_scope_idx
    ON story_plan_binding(
        project_id, book_id, contract_type, execution_scope, freshness
    )
    """,
    """
    CREATE INDEX story_plan_hierarchy_parent_idx
    ON story_plan_hierarchy(project_id, parent_binding_id)
    """,
    """
    CREATE INDEX asset_dependency_source_idx
    ON asset_dependency_edge(
        project_id, source_asset_version_id, dependency_type
    )
    """,
    """
    CREATE INDEX asset_dependency_dependent_idx
    ON asset_dependency_edge(
        project_id, dependent_asset_version_id, dependency_type
    )
    """,
]

DOWNGRADE_STATEMENTS: list[str] = []

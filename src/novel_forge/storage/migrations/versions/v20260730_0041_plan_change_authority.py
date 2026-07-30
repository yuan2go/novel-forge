from __future__ import annotations

MIGRATION_ID = "20260730_0041_plan_change_authority"
DOWN_REVISION = "20260730_0040_chapter_group_authority"

UPGRADE_STATEMENTS = [
    """
    CREATE TABLE authority_plan_change_proposal (
        proposal_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        source_type TEXT NOT NULL,
        source_evidence_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        target_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        proposed_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        target_contract_type TEXT NOT NULL,
        target_logical_key TEXT NOT NULL,
        target_execution_scope TEXT NOT NULL,
        semantic_diff JSONB NOT NULL,
        risk TEXT NOT NULL,
        status TEXT NOT NULL,
        proposal_operation_id TEXT NOT NULL UNIQUE
            REFERENCES authority_operation(operation_id),
        approval_operation_id TEXT UNIQUE
            REFERENCES authority_operation(operation_id),
        activation_operation_id TEXT UNIQUE
            REFERENCES authority_operation(operation_id),
        stable_idempotency_key TEXT NOT NULL,
        failure_reason TEXT NOT NULL DEFAULT '',
        version BIGINT NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id, stable_idempotency_key),
        UNIQUE(project_id, target_asset_version_id, proposed_asset_version_id),
        CHECK (source_type IN (
            'LONGFORM_RECAP', 'PLAN_VS_ACTUAL', 'READER_OUTCOME',
            'HUMAN_FEEDBACK', 'CANON_CHANGE', 'STORY_STATE_CHANGE',
            'QUALITY_ISSUE', 'PLATFORM_CHANGE',
            'ENDING_REACHABILITY_RISK', 'ARC_CLOSURE_RISK'
        )),
        CHECK (target_contract_type IN (
            'BOOK', 'VOLUME', 'ARC', 'CHAPTER_GROUP', 'CHAPTER'
        )),
        CHECK (target_execution_scope IN (
            'EXECUTED', 'FROZEN', 'PLANNED', 'SPECULATIVE'
        )),
        CHECK (risk IN ('LOW', 'MEDIUM', 'HIGH')),
        CHECK (status IN (
            'PENDING_APPROVAL', 'APPROVED', 'REJECTED',
            'ACTIVATION_PENDING', 'ACTIVE', 'FAILED'
        )),
        CHECK (jsonb_typeof(semantic_diff) = 'array'),
        CHECK (target_asset_version_id <> proposed_asset_version_id)
    )
    """,
    """
    CREATE TABLE authority_plan_change_decision (
        decision_id TEXT PRIMARY KEY,
        proposal_id TEXT NOT NULL UNIQUE
            REFERENCES authority_plan_change_proposal(proposal_id),
        project_id TEXT NOT NULL,
        decision TEXT NOT NULL,
        authority_type TEXT NOT NULL,
        authority_version TEXT NOT NULL,
        decision_operation_id TEXT NOT NULL UNIQUE
            REFERENCES authority_operation(operation_id),
        evidence JSONB NOT NULL,
        decided_by TEXT NOT NULL,
        decided_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CHECK (decision IN ('APPROVED', 'REJECTED')),
        CHECK (jsonb_typeof(evidence) = 'object')
    )
    """,
    """
    CREATE TABLE authority_plan_change_impact (
        impact_id TEXT PRIMARY KEY,
        proposal_id TEXT NOT NULL
            REFERENCES authority_plan_change_proposal(proposal_id),
        project_id TEXT NOT NULL,
        source_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        impacted_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        dependency_path JSONB NOT NULL,
        execution_scope TEXT NOT NULL,
        previous_freshness TEXT NOT NULL,
        target_freshness TEXT NOT NULL,
        automatic_mutation_allowed BOOLEAN NOT NULL,
        recorded_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(proposal_id, impacted_asset_version_id),
        CHECK (jsonb_typeof(dependency_path) = 'array'),
        CHECK (execution_scope IN (
            'EXECUTED', 'FROZEN', 'PLANNED', 'SPECULATIVE'
        )),
        CHECK (previous_freshness IN ('CURRENT', 'IMPACTED', 'STALE')),
        CHECK (target_freshness IN ('CURRENT', 'IMPACTED', 'STALE')),
        CHECK (
            execution_scope <> 'EXECUTED'
            OR automatic_mutation_allowed = FALSE
        )
    )
    """,
    """
    CREATE INDEX plan_change_query_idx
    ON authority_plan_change_proposal(
        project_id, book_id, status, risk, updated_at DESC
    )
    """,
    """
    CREATE INDEX plan_change_impact_query_idx
    ON authority_plan_change_impact(
        project_id, impacted_asset_version_id, created_at DESC
    )
    """,
]

DOWNGRADE_STATEMENTS: list[str] = []

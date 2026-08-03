from __future__ import annotations

MIGRATION_ID = "20260801_0050_mkaos_authority"
DOWN_REVISION = "20260801_0049_source_transform_fk_indexes"


UPGRADE_STATEMENTS = [
    """
    CREATE TABLE authority_mkaos_knowledge_candidate (
        knowledge_candidate_id TEXT PRIMARY KEY
            REFERENCES authority_asset(asset_id),
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        workspace_id TEXT NOT NULL REFERENCES authority_workspace(workspace_id),
        asset_version_id TEXT NOT NULL UNIQUE
            REFERENCES authority_asset_version(asset_version_id),
        execution_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        created_by_operation_id TEXT NOT NULL UNIQUE
            REFERENCES authority_operation(operation_id),
        candidate_hash TEXT NOT NULL,
        abstraction_policy_version TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id, candidate_hash),
        CHECK (status IN (
            'NEEDS_REVIEW', 'APPROVED', 'REJECTED', 'QUARANTINED'
        ))
    )
    """,
    """
    CREATE INDEX authority_mkaos_candidate_project_idx
    ON authority_mkaos_knowledge_candidate(project_id, created_at DESC)
    """,
    """
    CREATE INDEX authority_mkaos_candidate_workspace_idx
    ON authority_mkaos_knowledge_candidate(workspace_id, created_at DESC)
    """,
    """
    CREATE INDEX authority_mkaos_candidate_execution_idx
    ON authority_mkaos_knowledge_candidate(execution_asset_version_id)
    """,
    """
    CREATE TABLE authority_mkaos_evidence_span (
        evidence_span_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        candidate_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        source_chunk_id TEXT NOT NULL
            REFERENCES authority_source_chunk(source_chunk_id),
        source_chunk_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        chunk_byte_start BIGINT NOT NULL,
        chunk_byte_end BIGINT NOT NULL,
        evidence_hash TEXT NOT NULL,
        created_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(
            candidate_asset_version_id, source_chunk_asset_version_id,
            chunk_byte_start, chunk_byte_end
        ),
        CHECK (chunk_byte_start >= 0),
        CHECK (chunk_byte_end > chunk_byte_start)
    )
    """,
    """
    CREATE INDEX authority_mkaos_evidence_project_idx
    ON authority_mkaos_evidence_span(project_id, created_at DESC)
    """,
    """
    CREATE INDEX authority_mkaos_evidence_candidate_idx
    ON authority_mkaos_evidence_span(candidate_asset_version_id)
    """,
    """
    CREATE INDEX authority_mkaos_evidence_chunk_idx
    ON authority_mkaos_evidence_span(source_chunk_id)
    """,
    """
    CREATE INDEX authority_mkaos_evidence_chunk_version_idx
    ON authority_mkaos_evidence_span(source_chunk_asset_version_id)
    """,
    """
    CREATE INDEX authority_mkaos_evidence_operation_idx
    ON authority_mkaos_evidence_span(created_by_operation_id)
    """,
    """
    CREATE TABLE authority_mkaos_governance_decision (
        governance_decision_id TEXT PRIMARY KEY
            REFERENCES authority_asset(asset_id),
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        workspace_id TEXT NOT NULL REFERENCES authority_workspace(workspace_id),
        asset_version_id TEXT NOT NULL UNIQUE
            REFERENCES authority_asset_version(asset_version_id),
        candidate_asset_version_id TEXT NOT NULL UNIQUE
            REFERENCES authority_asset_version(asset_version_id),
        created_by_operation_id TEXT NOT NULL UNIQUE
            REFERENCES authority_operation(operation_id),
        decision TEXT NOT NULL,
        reviewer_id TEXT NOT NULL,
        policy_version TEXT NOT NULL,
        rationale_hash TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CHECK (decision IN ('APPROVE', 'REJECT'))
    )
    """,
    """
    CREATE INDEX authority_mkaos_decision_project_idx
    ON authority_mkaos_governance_decision(project_id, created_at DESC)
    """,
    """
    CREATE INDEX authority_mkaos_decision_workspace_idx
    ON authority_mkaos_governance_decision(workspace_id, created_at DESC)
    """,
    """
    CREATE TABLE authority_mkaos_knowledge_card (
        knowledge_card_id TEXT PRIMARY KEY REFERENCES authority_asset(asset_id),
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        workspace_id TEXT NOT NULL REFERENCES authority_workspace(workspace_id),
        asset_version_id TEXT NOT NULL UNIQUE
            REFERENCES authority_asset_version(asset_version_id),
        candidate_asset_version_id TEXT NOT NULL UNIQUE
            REFERENCES authority_asset_version(asset_version_id),
        governance_decision_asset_version_id TEXT NOT NULL UNIQUE
            REFERENCES authority_asset_version(asset_version_id),
        created_by_operation_id TEXT NOT NULL UNIQUE
            REFERENCES authority_operation(operation_id),
        content_hash TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id, content_hash),
        CHECK (status IN ('ACTIVE', 'SUPERSEDED', 'REVOKED'))
    )
    """,
    """
    CREATE INDEX authority_mkaos_card_project_idx
    ON authority_mkaos_knowledge_card(project_id, created_at DESC)
    """,
    """
    CREATE INDEX authority_mkaos_card_workspace_idx
    ON authority_mkaos_knowledge_card(workspace_id, created_at DESC)
    """,
    """
    CREATE TABLE authority_mkaos_knowledge_pack (
        knowledge_pack_id TEXT PRIMARY KEY REFERENCES authority_asset(asset_id),
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        workspace_id TEXT NOT NULL REFERENCES authority_workspace(workspace_id),
        asset_version_id TEXT NOT NULL UNIQUE
            REFERENCES authority_asset_version(asset_version_id),
        target_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        created_by_operation_id TEXT NOT NULL UNIQUE
            REFERENCES authority_operation(operation_id),
        selector_policy_version TEXT NOT NULL,
        selector_policy_hash TEXT NOT NULL,
        selection_hash TEXT NOT NULL,
        item_count INTEGER NOT NULL,
        status TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id, target_asset_version_id, selection_hash),
        CHECK (item_count > 0),
        CHECK (status IN ('ACTIVE', 'SUPERSEDED', 'ROLLED_BACK'))
    )
    """,
    """
    CREATE UNIQUE INDEX authority_mkaos_pack_one_active_target_idx
    ON authority_mkaos_knowledge_pack(project_id, target_asset_version_id)
    WHERE status = 'ACTIVE'
    """,
    """
    CREATE INDEX authority_mkaos_pack_project_idx
    ON authority_mkaos_knowledge_pack(project_id, created_at DESC)
    """,
    """
    CREATE INDEX authority_mkaos_pack_workspace_idx
    ON authority_mkaos_knowledge_pack(workspace_id, created_at DESC)
    """,
    """
    CREATE INDEX authority_mkaos_pack_target_idx
    ON authority_mkaos_knowledge_pack(target_asset_version_id)
    """,
    """
    CREATE TABLE authority_mkaos_knowledge_pack_item (
        knowledge_pack_id TEXT NOT NULL
            REFERENCES authority_mkaos_knowledge_pack(knowledge_pack_id),
        knowledge_pack_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        knowledge_card_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        ordinal INTEGER NOT NULL,
        usage_role TEXT NOT NULL,
        frozen_weight NUMERIC(12, 6) NOT NULL,
        created_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY(knowledge_pack_id, ordinal),
        UNIQUE(knowledge_pack_id, knowledge_card_asset_version_id),
        CHECK (ordinal >= 0),
        CHECK (usage_role IN ('PRINCIPLE', 'CONSTRAINT', 'CHECK', 'REFERENCE')),
        CHECK (frozen_weight > 0 AND frozen_weight <= 100)
    )
    """,
    """
    CREATE INDEX authority_mkaos_pack_item_pack_version_idx
    ON authority_mkaos_knowledge_pack_item(knowledge_pack_asset_version_id)
    """,
    """
    CREATE INDEX authority_mkaos_pack_item_card_version_idx
    ON authority_mkaos_knowledge_pack_item(knowledge_card_asset_version_id)
    """,
    """
    CREATE INDEX authority_mkaos_pack_item_operation_idx
    ON authority_mkaos_knowledge_pack_item(created_by_operation_id)
    """,
]


# Forward-only: these rows are immutable lineage and governance evidence. Restore
# uses database backup plus Blob/object reconciliation instead of destructive down SQL.
DOWNGRADE_STATEMENTS: list[str] = []

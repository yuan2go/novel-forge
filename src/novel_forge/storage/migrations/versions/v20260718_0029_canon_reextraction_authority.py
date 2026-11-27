from __future__ import annotations

MIGRATION_ID = "20260718_0029_canon_reextraction_authority"
DOWN_REVISION = "20260718_0028_provider_adapter_v2"

UPGRADE_STATEMENTS = [
    "ALTER TABLE authority_canon_approval_request DROP CONSTRAINT authority_canon_approval_request_status_check",
    "ALTER TABLE authority_canon_approval_request ADD CONSTRAINT authority_canon_approval_request_status_check CHECK (status IN ('PENDING','APPROVED','REJECTED','EDITED_AND_APPROVED','DEFERRED','REEXTRACTION_REQUESTED','INVALIDATED','EXPIRED'))",
    "ALTER TABLE authority_canon_approval_request ADD COLUMN proposal_generation INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE authority_canon_approval_request ADD COLUMN defer_until TIMESTAMPTZ",
    "ALTER TABLE authority_canon_approval_request ADD COLUMN required_information TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE authority_canon_approval_request ADD COLUMN assigned_operator TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE authority_canon_approval_request ADD COLUMN expiry_policy TEXT NOT NULL DEFAULT 'REOPEN'",
    "ALTER TABLE authority_canon_approval_request ADD CONSTRAINT authority_canon_approval_generation_positive CHECK (proposal_generation > 0)",
    "ALTER TABLE authority_canon_approval_request ADD CONSTRAINT authority_canon_defer_expiry_policy_check CHECK (expiry_policy IN ('REOPEN','EXPIRE'))",
    "ALTER TABLE authority_canon_approval_decision ADD COLUMN resolution_asset_version_id TEXT REFERENCES authority_asset_version(asset_version_id)",
    "CREATE INDEX authority_canon_decision_resolution_idx ON authority_canon_approval_decision(resolution_asset_version_id) WHERE resolution_asset_version_id IS NOT NULL",
    """
    CREATE TABLE authority_canon_approval_transition (
        transition_id TEXT PRIMARY KEY,
        approval_request_id TEXT NOT NULL REFERENCES authority_canon_approval_request(approval_request_id),
        project_id TEXT NOT NULL,
        from_status TEXT NOT NULL,
        to_status TEXT NOT NULL,
        actor_id TEXT NOT NULL,
        reason TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        expected_version BIGINT NOT NULL,
        trace_id TEXT NOT NULL,
        correlation_id TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id, approval_request_id, idempotency_key)
    )
    """,
    "CREATE INDEX authority_canon_approval_transition_request_idx ON authority_canon_approval_transition(approval_request_id, created_at)",
    """
    CREATE TABLE authority_canon_reextraction_generation (
        reextraction_generation_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        root_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        saga_id TEXT NOT NULL REFERENCES authority_saga(saga_id),
        generation INTEGER NOT NULL,
        status TEXT NOT NULL,
        supersedes_proposal_asset_version_id TEXT NOT NULL REFERENCES authority_asset_version(asset_version_id),
        extraction_operation_id TEXT REFERENCES authority_operation(operation_id),
        extraction_asset_version_id TEXT REFERENCES authority_asset_version(asset_version_id),
        proposal_operation_id TEXT REFERENCES authority_operation(operation_id),
        proposal_asset_version_id TEXT REFERENCES authority_asset_version(asset_version_id),
        invalidation_reason TEXT NOT NULL,
        created_by_decision_asset_version_id TEXT NOT NULL REFERENCES authority_asset_version(asset_version_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id, root_operation_id, generation),
        CHECK (generation > 1),
        CHECK (status IN ('REEXTRACTION_PENDING','EXTRACTION_RUNNING','PROPOSAL_PENDING','PROPOSAL_RUNNING','WAITING_APPROVAL','RESOLVED','CANCELLED'))
    )
    """,
    "CREATE INDEX authority_canon_reextraction_pending_idx ON authority_canon_reextraction_generation(project_id, root_operation_id, status)",
    "CREATE INDEX authority_canon_reextraction_saga_idx ON authority_canon_reextraction_generation(saga_id)",
    "CREATE INDEX authority_canon_reextraction_supersedes_idx ON authority_canon_reextraction_generation(supersedes_proposal_asset_version_id)",
    "CREATE INDEX authority_canon_reextraction_extract_op_idx ON authority_canon_reextraction_generation(extraction_operation_id) WHERE extraction_operation_id IS NOT NULL",
    "CREATE INDEX authority_canon_reextraction_extract_asset_idx ON authority_canon_reextraction_generation(extraction_asset_version_id) WHERE extraction_asset_version_id IS NOT NULL",
    "CREATE INDEX authority_canon_reextraction_proposal_op_idx ON authority_canon_reextraction_generation(proposal_operation_id) WHERE proposal_operation_id IS NOT NULL",
    "CREATE INDEX authority_canon_reextraction_proposal_asset_idx ON authority_canon_reextraction_generation(proposal_asset_version_id) WHERE proposal_asset_version_id IS NOT NULL",
    "CREATE INDEX authority_canon_reextraction_decision_idx ON authority_canon_reextraction_generation(created_by_decision_asset_version_id)",
]

DOWNGRADE_STATEMENTS: list[str] = []

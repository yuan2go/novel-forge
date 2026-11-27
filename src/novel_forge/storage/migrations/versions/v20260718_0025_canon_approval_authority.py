from __future__ import annotations

MIGRATION_ID = "20260718_0025_canon_approval_authority"
DOWN_REVISION = "20260718_0024_pre_provider_runtime_hardening"

UPGRADE_STATEMENTS = [
    """
    CREATE TABLE authority_canon_approval_request (
        approval_request_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        root_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        saga_id TEXT NOT NULL REFERENCES authority_saga(saga_id),
        proposal_asset_version_id TEXT NOT NULL REFERENCES authority_asset_version(asset_version_id),
        change_id TEXT NOT NULL,
        change_type TEXT NOT NULL,
        risk JSONB NOT NULL,
        status TEXT NOT NULL DEFAULT 'PENDING',
        version BIGINT NOT NULL DEFAULT 0,
        expires_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id, proposal_asset_version_id, change_id),
        CHECK (status IN ('PENDING','APPROVED','REJECTED','EDITED_AND_APPROVED','DEFERRED','REEXTRACTION_REQUESTED','EXPIRED')),
        CHECK (version >= 0)
    )
    """,
    "CREATE INDEX authority_canon_approval_project_status_idx ON authority_canon_approval_request(project_id, status, created_at)",
    "CREATE INDEX authority_canon_approval_root_idx ON authority_canon_approval_request(root_operation_id, status)",
    "CREATE INDEX authority_canon_approval_saga_idx ON authority_canon_approval_request(saga_id)",
    """
    CREATE TABLE authority_canon_approval_decision (
        approval_decision_id TEXT PRIMARY KEY,
        approval_request_id TEXT NOT NULL REFERENCES authority_canon_approval_request(approval_request_id),
        project_id TEXT NOT NULL,
        decision TEXT NOT NULL,
        reason TEXT NOT NULL,
        evidence JSONB NOT NULL,
        edited_payload JSONB,
        principal_id TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        request_digest TEXT NOT NULL,
        asset_version_id TEXT NOT NULL REFERENCES authority_asset_version(asset_version_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id, approval_request_id, idempotency_key),
        UNIQUE(asset_version_id),
        CHECK (decision IN ('APPROVE','REJECT','EDIT_AND_APPROVE','DEFER','REQUEST_REEXTRACTION'))
    )
    """,
    "CREATE INDEX authority_canon_decision_request_idx ON authority_canon_approval_decision(approval_request_id, created_at DESC)",
]

DOWNGRADE_STATEMENTS: list[str] = []

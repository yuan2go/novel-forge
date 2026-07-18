from __future__ import annotations

MIGRATION_ID = "20260718_0030_provider_callback_authority"
DOWN_REVISION = "20260718_0029_canon_reextraction_authority"

UPGRADE_STATEMENTS = [
    """
    CREATE TABLE authority_provider_callback_receipt (
        callback_receipt_id TEXT PRIMARY KEY,
        project_id TEXT,
        provider TEXT NOT NULL,
        provider_request_id TEXT NOT NULL,
        provider_message_id TEXT NOT NULL,
        external_effect_id TEXT REFERENCES authority_external_effect(external_effect_id),
        dispatch_id TEXT REFERENCES authority_external_effect_dispatch(dispatch_id),
        payload_hash TEXT NOT NULL,
        signature_status TEXT NOT NULL,
        outcome TEXT NOT NULL,
        raw_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        normalized_receipt JSONB NOT NULL DEFAULT '{}'::jsonb,
        processing_status TEXT NOT NULL DEFAULT 'PENDING',
        processed_at TIMESTAMPTZ,
        attempt_count INTEGER NOT NULL DEFAULT 0,
        last_error TEXT NOT NULL DEFAULT '',
        trace_id TEXT NOT NULL,
        correlation_id TEXT NOT NULL,
        received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT authority_provider_callback_signature_check
            CHECK (signature_status IN ('VERIFIED','REJECTED')),
        CONSTRAINT authority_provider_callback_processing_check
            CHECK (processing_status IN ('PENDING','PROCESSING','PROCESSED','QUARANTINED','CONFLICTED','FAILED_RETRYABLE','FAILED_FINAL')),
        CONSTRAINT authority_provider_callback_attempt_nonnegative CHECK (attempt_count >= 0),
        CONSTRAINT authority_provider_callback_binding_check CHECK (
            (project_id IS NOT NULL AND external_effect_id IS NOT NULL AND dispatch_id IS NOT NULL)
            OR processing_status = 'QUARANTINED'
        ),
        UNIQUE(provider, provider_message_id)
    )
    """,
    "CREATE UNIQUE INDEX authority_provider_callback_payload_identity_idx ON authority_provider_callback_receipt(provider, provider_request_id, payload_hash) WHERE project_id IS NOT NULL",
    "CREATE INDEX authority_provider_callback_effect_idx ON authority_provider_callback_receipt(external_effect_id, processing_status)",
    "CREATE INDEX authority_provider_callback_project_idx ON authority_provider_callback_receipt(project_id, received_at DESC) WHERE project_id IS NOT NULL",
    """
    CREATE TABLE authority_provider_callback_attempt (
        callback_attempt_id TEXT PRIMARY KEY,
        callback_receipt_id TEXT NOT NULL REFERENCES authority_provider_callback_receipt(callback_receipt_id),
        project_id TEXT NOT NULL,
        attempt_number INTEGER NOT NULL,
        status TEXT NOT NULL,
        worker_id TEXT NOT NULL,
        error_code TEXT NOT NULL DEFAULT '',
        error_detail TEXT NOT NULL DEFAULT '',
        started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        finished_at TIMESTAMPTZ,
        CONSTRAINT authority_provider_callback_attempt_number CHECK (attempt_number > 0),
        CONSTRAINT authority_provider_callback_attempt_status CHECK (status IN ('RUNNING','SUCCEEDED','FAILED_RETRYABLE','FAILED_FINAL')),
        UNIQUE(callback_receipt_id, attempt_number)
    )
    """,
    "CREATE INDEX authority_provider_callback_attempt_project_idx ON authority_provider_callback_attempt(project_id, status, started_at)",
    """
    CREATE TABLE authority_worker_health_projection (
        worker_id TEXT NOT NULL,
        worker_kind TEXT NOT NULL,
        status TEXT NOT NULL,
        last_poll_at TIMESTAMPTZ,
        last_successful_poll_at TIMESTAMPTZ,
        last_fatal_error JSONB NOT NULL DEFAULT '{}'::jsonb,
        restart_expectation TEXT NOT NULL,
        active_operation_id TEXT,
        lease_count INTEGER NOT NULL DEFAULT 0,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY(worker_id, worker_kind),
        CONSTRAINT authority_worker_health_status_check CHECK (status IN ('STARTING','READY','BUSY','DEGRADED','FATAL','STOPPED')),
        CONSTRAINT authority_worker_health_lease_nonnegative CHECK (lease_count >= 0)
    )
    """,
    "CREATE INDEX authority_worker_health_freshness_idx ON authority_worker_health_projection(worker_kind, status, updated_at DESC)",
]

DOWNGRADE_STATEMENTS: list[str] = []

from __future__ import annotations

MIGRATION_ID = "20260713_0017_external_effect_runtime"
DOWN_REVISION = "20260713_0016_asset_blob_protocol"

UPGRADE_STATEMENTS = [
    "ALTER TABLE authority_external_effect ADD COLUMN provider TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE authority_external_effect ADD COLUMN capability TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE authority_external_effect ADD COLUMN max_attempts INTEGER NOT NULL DEFAULT 3",
    "ALTER TABLE authority_external_effect ADD COLUMN reversible BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE authority_external_effect ADD COLUMN last_error JSONB NOT NULL DEFAULT '{}'::jsonb",
    "ALTER TABLE authority_external_effect ADD CONSTRAINT authority_effect_max_attempts_positive CHECK (max_attempts > 0)",
    "ALTER TABLE authority_external_effect_dispatch ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
    "ALTER TABLE authority_external_effect_dispatch ADD COLUMN finished_at TIMESTAMPTZ",
    """
    CREATE TABLE authority_effect_dispatch_lease (
        lease_id TEXT PRIMARY KEY,
        dispatch_id TEXT NOT NULL REFERENCES authority_external_effect_dispatch(dispatch_id),
        owner TEXT NOT NULL,
        fencing_token BIGINT NOT NULL,
        acquired_at TIMESTAMPTZ NOT NULL,
        expires_at TIMESTAMPTZ NOT NULL,
        heartbeat_at TIMESTAMPTZ NOT NULL,
        released_at TIMESTAMPTZ,
        release_reason TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL,
        UNIQUE(dispatch_id, fencing_token),
        CHECK (fencing_token > 0),
        CHECK (expires_at > acquired_at),
        CHECK (status IN ('HELD', 'RELEASED', 'EXPIRED')),
        CHECK (
            (status = 'HELD' AND released_at IS NULL)
            OR (status IN ('RELEASED', 'EXPIRED') AND released_at IS NOT NULL)
        )
    )
    """,
    "CREATE UNIQUE INDEX authority_one_held_effect_dispatch_lease ON authority_effect_dispatch_lease(dispatch_id) WHERE status = 'HELD'",
    "CREATE INDEX authority_effect_dispatch_lease_history_idx ON authority_effect_dispatch_lease(dispatch_id, fencing_token DESC)",
    """
    CREATE OR REPLACE FUNCTION authority_acquire_effect_dispatch_lease(
        p_lease_id TEXT,
        p_dispatch_id TEXT,
        p_owner TEXT,
        p_lease_seconds INTEGER
    )
    RETURNS SETOF authority_effect_dispatch_lease
    LANGUAGE plpgsql
    AS $$
    DECLARE
        next_token BIGINT;
        dispatch_status TEXT;
    BEGIN
        IF p_lease_seconds <= 0 THEN
            RAISE EXCEPTION 'effect lease duration must be positive'
                USING ERRCODE = '23514', CONSTRAINT = 'authority_effect_lease_duration_positive';
        END IF;
        SELECT status INTO dispatch_status
        FROM authority_external_effect_dispatch
        WHERE dispatch_id = p_dispatch_id
        FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'effect dispatch does not exist'
                USING ERRCODE = '23503', CONSTRAINT = 'authority_effect_lease_dispatch_fk';
        END IF;
        IF dispatch_status NOT IN ('CREATED', 'LEASED', 'DISPATCHING') THEN
            RAISE EXCEPTION 'effect dispatch state is not leaseable: %', dispatch_status
                USING ERRCODE = '23514', CONSTRAINT = 'authority_effect_dispatch_leaseable_status';
        END IF;
        UPDATE authority_effect_dispatch_lease
        SET status = 'EXPIRED', released_at = NOW(), release_reason = 'lease_expired'
        WHERE dispatch_id = p_dispatch_id AND status = 'HELD' AND expires_at <= NOW();
        IF EXISTS (
            SELECT 1 FROM authority_effect_dispatch_lease
            WHERE dispatch_id = p_dispatch_id AND status = 'HELD'
        ) THEN
            RAISE EXCEPTION 'effect dispatch already has a held lease'
                USING ERRCODE = '23514', CONSTRAINT = 'authority_effect_one_effective_lease';
        END IF;
        SELECT COALESCE(MAX(fencing_token), 0) + 1 INTO next_token
        FROM authority_effect_dispatch_lease WHERE dispatch_id = p_dispatch_id;
        UPDATE authority_external_effect_dispatch
        SET status = 'DISPATCHING', updated_at = NOW()
        WHERE dispatch_id = p_dispatch_id;
        RETURN QUERY
        INSERT INTO authority_effect_dispatch_lease (
            lease_id, dispatch_id, owner, fencing_token,
            acquired_at, expires_at, heartbeat_at, status
        )
        VALUES (
            p_lease_id, p_dispatch_id, p_owner, next_token,
            NOW(), NOW() + make_interval(secs => p_lease_seconds), NOW(), 'HELD'
        )
        RETURNING *;
    END;
    $$
    """,
    """
    CREATE TABLE authority_effect_command_rejection (
        rejection_id TEXT PRIMARY KEY,
        external_effect_id TEXT NOT NULL REFERENCES authority_external_effect(external_effect_id),
        dispatch_id TEXT NOT NULL REFERENCES authority_external_effect_dispatch(dispatch_id),
        worker_id TEXT NOT NULL,
        presented_fencing_token BIGINT NOT NULL,
        current_fencing_token BIGINT,
        command_type TEXT NOT NULL,
        payload JSONB NOT NULL,
        trace_id TEXT NOT NULL,
        correlation_id TEXT NOT NULL,
        rejected_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE authority_effect_reconciliation_evidence (
        reconciliation_id TEXT PRIMARY KEY,
        external_effect_id TEXT NOT NULL REFERENCES authority_external_effect(external_effect_id),
        provider TEXT NOT NULL,
        stable_idempotency_key TEXT NOT NULL,
        outcome TEXT NOT NULL,
        evidence JSONB NOT NULL,
        trace_id TEXT NOT NULL,
        correlation_id TEXT NOT NULL,
        reconciled_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CHECK (outcome IN ('success', 'not_found', 'ambiguous', 'failed_final'))
    )
    """,
    "CREATE INDEX authority_effect_rejection_dispatch_idx ON authority_effect_command_rejection(dispatch_id, rejected_at DESC)",
    "CREATE INDEX authority_effect_rejection_effect_idx ON authority_effect_command_rejection(external_effect_id, rejected_at DESC)",
    "CREATE INDEX authority_effect_reconciliation_idx ON authority_effect_reconciliation_evidence(external_effect_id, reconciled_at DESC)",
]

DOWNGRADE_STATEMENTS: list[str] = []

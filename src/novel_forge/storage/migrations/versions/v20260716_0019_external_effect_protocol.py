from __future__ import annotations

MIGRATION_ID = "20260716_0019_external_effect_protocol"
DOWN_REVISION = "20260713_0018_operation_graph_completion"

EFFECT_STATES = (
    "READY",
    "DISPATCHING",
    "DISPATCHED",
    "SUCCEEDED",
    "FAILED_RETRYABLE",
    "FAILED_FINAL",
    "UNKNOWN",
    "RECONCILIATION_REQUIRED",
    "CANCELLATION_REQUESTED",
    "CANCELLED",
    "COMPENSATION_REQUIRED",
    "COMPENSATING",
    "COMPENSATED",
    "DEAD_LETTER",
)

DISPATCH_STATES = (
    "CREATED",
    "DISPATCHING",
    "ACKNOWLEDGED",
    "SUCCEEDED",
    "FAILED_RETRYABLE",
    "FAILED_FINAL",
    "UNKNOWN",
    "CANCEL_REQUESTED",
    "CANCELLED",
    "SUPERSEDED",
    "DEAD_LETTER",
)


def _sql_values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


UPGRADE_STATEMENTS = [
    "ALTER TABLE authority_external_effect ADD COLUMN project_id TEXT",
    """
    UPDATE authority_external_effect AS effect
    SET project_id = operation.project_id
    FROM authority_operation AS operation
    WHERE operation.operation_id = effect.operation_id
    """,
    "ALTER TABLE authority_external_effect ALTER COLUMN project_id SET NOT NULL",
    "ALTER TABLE authority_external_effect ADD COLUMN completion_policy TEXT NOT NULL DEFAULT 'synchronous_final'",
    "ALTER TABLE authority_external_effect ADD COLUMN compensates_effect_id TEXT REFERENCES authority_external_effect(external_effect_id)",
    """
    ALTER TABLE authority_external_effect
    ADD CONSTRAINT authority_external_effect_completion_policy_check
    CHECK (completion_policy IN (
        'synchronous_final', 'async_ack', 'callback_receipt', 'poll_reconciliation'
    ))
    """,
    "DROP INDEX authority_effect_stable_key_unique",
    "CREATE UNIQUE INDEX authority_effect_project_stable_key_unique ON authority_external_effect(project_id, effect_type, stable_idempotency_key)",
    "UPDATE authority_external_effect SET status = 'READY' WHERE status IN ('REQUESTED', 'DISPATCHABLE', 'PLANNED')",
    "UPDATE authority_external_effect SET status = 'DISPATCHED' WHERE status IN ('IN_FLIGHT', 'ACKNOWLEDGED')",
    "UPDATE authority_external_effect SET status = 'FAILED_RETRYABLE' WHERE status = 'FAILED'",
    "UPDATE authority_external_effect_dispatch SET status = 'DISPATCHING' WHERE status = 'LEASED'",
    "UPDATE authority_external_effect_dispatch SET status = 'ACKNOWLEDGED' WHERE status = 'SENT'",
    "UPDATE authority_external_effect_dispatch SET status = 'FAILED_RETRYABLE' WHERE status = 'FAILED'",
    "UPDATE authority_external_effect_dispatch SET status = 'UNKNOWN' WHERE status = 'TIMED_OUT'",
    "ALTER TABLE authority_external_effect DROP CONSTRAINT authority_external_effect_status_check",
    f"ALTER TABLE authority_external_effect ADD CONSTRAINT authority_external_effect_status_check CHECK (status IN ({_sql_values(EFFECT_STATES)}))",
    "ALTER TABLE authority_external_effect_dispatch DROP CONSTRAINT authority_external_effect_dispatch_status_check",
    f"ALTER TABLE authority_external_effect_dispatch ADD CONSTRAINT authority_external_effect_dispatch_status_check CHECK (status IN ({_sql_values(DISPATCH_STATES)}))",
    "ALTER TABLE authority_external_receipt ADD COLUMN status TEXT NOT NULL DEFAULT 'RECEIVED'",
    "ALTER TABLE authority_external_receipt ADD CONSTRAINT authority_external_receipt_status_check CHECK (status IN ('RECEIVED', 'VERIFIED', 'REJECTED'))",
    "CREATE INDEX authority_external_effect_compensation_idx ON authority_external_effect(compensates_effect_id) WHERE compensates_effect_id IS NOT NULL",
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
        effect_id TEXT;
    BEGIN
        IF p_lease_seconds <= 0 THEN
            RAISE EXCEPTION 'effect lease duration must be positive'
                USING ERRCODE = '23514', CONSTRAINT = 'authority_effect_lease_duration_positive';
        END IF;
        SELECT status, external_effect_id INTO dispatch_status, effect_id
        FROM authority_external_effect_dispatch
        WHERE dispatch_id = p_dispatch_id
        FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'effect dispatch does not exist'
                USING ERRCODE = '23503', CONSTRAINT = 'authority_effect_lease_dispatch_fk';
        END IF;
        IF dispatch_status NOT IN ('CREATED', 'DISPATCHING') THEN
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
        UPDATE authority_external_effect
        SET status = 'DISPATCHING'
        WHERE external_effect_id = effect_id
          AND status IN ('READY', 'FAILED_RETRYABLE', 'DISPATCHING');
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
]

DOWNGRADE_STATEMENTS: list[str] = []

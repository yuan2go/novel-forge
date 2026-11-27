from __future__ import annotations

MIGRATION_ID = "20260713_0009_attempt_lease_invariants"
DOWN_REVISION = "20260713_0008_authority_schema_recovery"

ATTEMPT_STATES = (
    "CREATED",
    "QUEUED",
    "LEASED",
    "RUNNING",
    "CHECKPOINTED",
    "RESULT_SUBMITTED",
    "SUCCEEDED",
    "FAILED_RETRYABLE",
    "FAILED_FINAL",
    "TIMED_OUT",
    "LEASE_LOST",
    "SUPERSEDED",
    "LATE_RESULT_REJECTED",
    "CANCELLED",
)


def _sql_values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


UPGRADE_STATEMENTS = [
    f"""
    ALTER TABLE authority_attempt
    ADD CONSTRAINT authority_attempt_status_check
    CHECK (status IN ({_sql_values(ATTEMPT_STATES)}))
    """,
    """
    ALTER TABLE authority_attempt
    ADD CONSTRAINT authority_attempt_number_positive
    CHECK (attempt_number > 0)
    """,
    """
    CREATE OR REPLACE FUNCTION authority_validate_attempt_number()
    RETURNS TRIGGER
    LANGUAGE plpgsql
    AS $$
    DECLARE
        expected_attempt_number INTEGER;
    BEGIN
        PERFORM 1
        FROM authority_operation
        WHERE operation_id = NEW.operation_id
        FOR UPDATE;

        SELECT COALESCE(MAX(attempt_number), 0) + 1
        INTO expected_attempt_number
        FROM authority_attempt
        WHERE operation_id = NEW.operation_id;

        IF NEW.attempt_number <> expected_attempt_number THEN
            RAISE EXCEPTION 'attempt_number must be the next monotonic value: expected %, received %',
                expected_attempt_number,
                NEW.attempt_number
                USING ERRCODE = '23514',
                      CONSTRAINT = 'authority_attempt_number_monotonic';
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE TRIGGER authority_attempt_number_guard
    BEFORE INSERT ON authority_attempt
    FOR EACH ROW
    EXECUTE FUNCTION authority_validate_attempt_number()
    """,
    "DROP INDEX authority_one_held_lease",
    """
    ALTER TABLE authority_lease_acquisition
    ADD COLUMN status TEXT NOT NULL DEFAULT 'HELD'
    """,
    """
    ALTER TABLE authority_lease_acquisition
    ADD CONSTRAINT authority_lease_status_check
    CHECK (status IN ('HELD', 'RELEASED', 'EXPIRED'))
    """,
    """
    ALTER TABLE authority_lease_acquisition
    ADD CONSTRAINT authority_lease_fencing_positive
    CHECK (fencing_token > 0)
    """,
    """
    ALTER TABLE authority_lease_acquisition
    ADD CONSTRAINT authority_lease_time_order_check
    CHECK (expires_at > acquired_at)
    """,
    """
    ALTER TABLE authority_lease_acquisition
    ADD CONSTRAINT authority_lease_release_consistency_check
    CHECK (
        (status = 'HELD' AND released_at IS NULL)
        OR
        (status IN ('RELEASED', 'EXPIRED') AND released_at IS NOT NULL)
    )
    """,
    """
    CREATE OR REPLACE FUNCTION authority_validate_lease_acquisition()
    RETURNS TRIGGER
    LANGUAGE plpgsql
    AS $$
    DECLARE
        expected_fencing_token BIGINT;
    BEGIN
        PERFORM 1
        FROM authority_attempt
        WHERE attempt_id = NEW.attempt_id
        FOR UPDATE;

        UPDATE authority_lease_acquisition
        SET status = 'EXPIRED',
            released_at = NOW(),
            release_reason = 'lease_expired'
        WHERE attempt_id = NEW.attempt_id
          AND status = 'HELD'
          AND expires_at <= NOW();

        IF EXISTS (
            SELECT 1
            FROM authority_lease_acquisition
            WHERE attempt_id = NEW.attempt_id
              AND status = 'HELD'
        ) THEN
            RAISE EXCEPTION 'attempt already has an effective lease'
                USING ERRCODE = '23514',
                      CONSTRAINT = 'authority_attempt_one_effective_lease';
        END IF;

        SELECT COALESCE(MAX(fencing_token), 0) + 1
        INTO expected_fencing_token
        FROM authority_lease_acquisition
        WHERE attempt_id = NEW.attempt_id;

        IF NEW.fencing_token <> expected_fencing_token THEN
            RAISE EXCEPTION 'fencing token must be monotonic: expected %, received %',
                expected_fencing_token,
                NEW.fencing_token
                USING ERRCODE = '23514',
                      CONSTRAINT = 'authority_lease_fencing_monotonic';
        END IF;

        IF NEW.status <> 'HELD' OR NEW.released_at IS NOT NULL THEN
            RAISE EXCEPTION 'new lease acquisition must start HELD and unreleased'
                USING ERRCODE = '23514',
                      CONSTRAINT = 'authority_lease_initial_state_check';
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE TRIGGER authority_lease_acquisition_guard
    BEFORE INSERT ON authority_lease_acquisition
    FOR EACH ROW
    EXECUTE FUNCTION authority_validate_lease_acquisition()
    """,
    """
    CREATE UNIQUE INDEX authority_one_held_lease
    ON authority_lease_acquisition(attempt_id)
    WHERE status = 'HELD'
    """,
    """
    CREATE OR REPLACE FUNCTION authority_acquire_attempt_lease(
        p_lease_id TEXT,
        p_attempt_id TEXT,
        p_owner TEXT,
        p_lease_seconds INTEGER
    )
    RETURNS SETOF authority_lease_acquisition
    LANGUAGE plpgsql
    AS $$
    DECLARE
        next_fencing_token BIGINT;
        attempt_status TEXT;
    BEGIN
        IF p_lease_seconds <= 0 THEN
            RAISE EXCEPTION 'lease duration must be positive'
                USING ERRCODE = '23514',
                      CONSTRAINT = 'authority_lease_duration_positive';
        END IF;

        SELECT status
        INTO attempt_status
        FROM authority_attempt
        WHERE attempt_id = p_attempt_id
        FOR UPDATE;

        IF NOT FOUND THEN
            RAISE EXCEPTION 'attempt does not exist'
                USING ERRCODE = '23503',
                      CONSTRAINT = 'authority_lease_attempt_fk';
        END IF;

        IF attempt_status NOT IN ('QUEUED', 'LEASED', 'RUNNING', 'CHECKPOINTED') THEN
            RAISE EXCEPTION 'attempt state is not leaseable: %', attempt_status
                USING ERRCODE = '23514',
                      CONSTRAINT = 'authority_attempt_leaseable_status';
        END IF;

        SELECT COALESCE(MAX(fencing_token), 0) + 1
        INTO next_fencing_token
        FROM authority_lease_acquisition
        WHERE attempt_id = p_attempt_id;

        RETURN QUERY
        INSERT INTO authority_lease_acquisition (
            lease_id,
            attempt_id,
            owner,
            fencing_token,
            acquired_at,
            expires_at,
            heartbeat_at,
            status
        )
        VALUES (
            p_lease_id,
            p_attempt_id,
            p_owner,
            next_fencing_token,
            NOW(),
            NOW() + make_interval(secs => p_lease_seconds),
            NOW(),
            'HELD'
        )
        RETURNING *;
    END;
    $$
    """,
    "CREATE INDEX authority_lease_attempt_history_idx ON authority_lease_acquisition(attempt_id, fencing_token DESC)",
]

DOWNGRADE_STATEMENTS: list[str] = []

from __future__ import annotations

MIGRATION_ID = "20260713_0011_effect_inbox_invariants"
DOWN_REVISION = "20260713_0010_asset_blob_invariants"

EXTERNAL_EFFECT_STATES = (
    "REQUESTED",
    "DISPATCHABLE",
    "IN_FLIGHT",
    "SUCCEEDED",
    "FAILED",
    "RECONCILIATION_REQUIRED",
    "CANCELLATION_REQUESTED",
    "CANCELLED",
    "COMPENSATION_REQUIRED",
    "COMPENSATED",
)
DISPATCH_STATES = (
    "CREATED",
    "SENT",
    "ACKNOWLEDGED",
    "SUCCEEDED",
    "FAILED",
    "TIMED_OUT",
    "UNKNOWN",
    "CANCEL_REQUESTED",
    "CANCELLED",
    "SUPERSEDED",
)
MIGRATION_RUN_STATES = (
    "PLANNED",
    "RUNNING",
    "VALIDATING",
    "SUCCEEDED",
    "FAILED",
    "CANCELLED",
    "QUARANTINED",
)


def _sql_values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


UPGRADE_STATEMENTS = [
    f"""
    ALTER TABLE authority_external_effect
    ADD CONSTRAINT authority_external_effect_status_check
    CHECK (status IN ({_sql_values(EXTERNAL_EFFECT_STATES)}))
    """,
    f"""
    ALTER TABLE authority_external_effect_dispatch
    ADD CONSTRAINT authority_external_effect_dispatch_status_check
    CHECK (status IN ({_sql_values(DISPATCH_STATES)}))
    """,
    """
    ALTER TABLE authority_external_effect_dispatch
    ADD CONSTRAINT authority_external_effect_dispatch_generation_positive
    CHECK (generation > 0)
    """,
    f"""
    ALTER TABLE authority_migration_run
    ADD CONSTRAINT authority_migration_run_status_check
    CHECK (status IN ({_sql_values(MIGRATION_RUN_STATES)}))
    """,
    """
    CREATE TABLE authority_inbox_conflict (
        conflict_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        consumer_name TEXT NOT NULL,
        message_id TEXT NOT NULL,
        expected_payload_hash TEXT NOT NULL,
        received_payload_hash TEXT NOT NULL,
        detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        FOREIGN KEY (consumer_name, message_id)
            REFERENCES authority_inbox_message(consumer_name, message_id)
    )
    """,
    """
    CREATE OR REPLACE FUNCTION authority_record_inbox_message(
        p_consumer_name TEXT,
        p_message_id TEXT,
        p_payload_hash TEXT,
        p_outcome JSONB
    )
    RETURNS TABLE(disposition TEXT, stored_outcome JSONB)
    LANGUAGE plpgsql
    AS $$
    DECLARE
        existing_payload_hash TEXT;
        existing_outcome JSONB;
    BEGIN
        INSERT INTO authority_inbox_message (
            consumer_name,
            message_id,
            payload_hash,
            outcome
        )
        VALUES (
            p_consumer_name,
            p_message_id,
            p_payload_hash,
            p_outcome
        )
        ON CONFLICT (consumer_name, message_id) DO NOTHING
        RETURNING outcome
        INTO existing_outcome;

        IF FOUND THEN
            RETURN QUERY SELECT 'RECORDED'::TEXT, existing_outcome;
            RETURN;
        END IF;

        SELECT payload_hash, outcome
        INTO existing_payload_hash, existing_outcome
        FROM authority_inbox_message
        WHERE consumer_name = p_consumer_name
          AND message_id = p_message_id
        FOR UPDATE;

        IF existing_payload_hash = p_payload_hash THEN
            RETURN QUERY SELECT 'REPLAY'::TEXT, existing_outcome;
            RETURN;
        END IF;

        INSERT INTO authority_inbox_conflict (
            consumer_name,
            message_id,
            expected_payload_hash,
            received_payload_hash
        )
        VALUES (
            p_consumer_name,
            p_message_id,
            existing_payload_hash,
            p_payload_hash
        );
        RETURN QUERY SELECT 'CONFLICT'::TEXT, existing_outcome;
    END;
    $$
    """,
    """
    CREATE TABLE authority_external_receipt (
        external_receipt_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        provider TEXT NOT NULL,
        receipt_id TEXT NOT NULL,
        dispatch_id TEXT NOT NULL REFERENCES authority_external_effect_dispatch(dispatch_id),
        payload_hash TEXT NOT NULL,
        received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(provider, receipt_id)
    )
    """,
    "CREATE INDEX authority_external_effect_operation_status_idx ON authority_external_effect(operation_id, status)",
    "CREATE INDEX authority_dispatch_effect_status_idx ON authority_external_effect_dispatch(external_effect_id, status)",
    "CREATE INDEX authority_external_receipt_dispatch_idx ON authority_external_receipt(dispatch_id)",
    "CREATE INDEX authority_inbox_conflict_message_idx ON authority_inbox_conflict(consumer_name, message_id, detected_at DESC)",
    "CREATE INDEX authority_operation_definition_fk_idx ON authority_operation(definition_name, definition_version)",
    "CREATE INDEX authority_asset_qualification_version_idx ON authority_asset_qualification(asset_version_id)",
    "CREATE INDEX authority_quarantine_migration_idx ON authority_data_quarantine(migration_run_id) WHERE migration_run_id IS NOT NULL",
]

DOWNGRADE_STATEMENTS: list[str] = []

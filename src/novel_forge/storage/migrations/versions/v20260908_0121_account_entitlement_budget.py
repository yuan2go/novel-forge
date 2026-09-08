from __future__ import annotations


MIGRATION_ID = "20260908_0121_account_entitlement_budget"
DOWN_REVISION = "20260907_0120_foundation_generation"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = (
    "retain existing priced evidence; new account-entitlement reservations use "
    "nullable monetary fields with explicit UNKNOWN status"
)


UPGRADE_STATEMENTS = [
    "ALTER TABLE authority_budget_reservation ALTER COLUMN estimated_amount DROP NOT NULL",
    "ALTER TABLE authority_budget_reservation ALTER COLUMN reserved_amount DROP NOT NULL",
    "ALTER TABLE authority_budget_reservation ALTER COLUMN settled_amount DROP NOT NULL",
    "ALTER TABLE authority_budget_reservation ADD COLUMN accounting_basis TEXT NOT NULL DEFAULT 'PRICED'",
    "ALTER TABLE authority_budget_reservation ADD COLUMN estimated_cost_status TEXT NOT NULL DEFAULT 'KNOWN'",
    "ALTER TABLE authority_budget_reservation ADD COLUMN settled_cost_status TEXT NOT NULL DEFAULT 'PENDING'",
    "UPDATE authority_budget_reservation SET settled_cost_status='KNOWN' WHERE status='SETTLED'",
    """
    ALTER TABLE authority_budget_reservation
    ADD CONSTRAINT authority_budget_cost_observability_check CHECK (
        (
            accounting_basis='PRICED'
            AND estimated_cost_status='KNOWN'
            AND estimated_amount IS NOT NULL
            AND reserved_amount IS NOT NULL
            AND settled_cost_status IN ('PENDING','KNOWN')
            AND (status<>'SETTLED' OR (
                settled_cost_status='KNOWN' AND settled_amount IS NOT NULL
            ))
        ) OR (
            accounting_basis='ACCOUNT_ENTITLEMENT'
            AND estimated_cost_status='UNKNOWN'
            AND estimated_amount IS NULL
            AND reserved_amount IS NULL
            AND settled_amount IS NULL
            AND settled_cost_status IN ('PENDING','UNKNOWN')
            AND (status<>'SETTLED' OR settled_cost_status='UNKNOWN')
        )
    )
    """,
    "ALTER TABLE authority_operation_cost_evidence ALTER COLUMN amount DROP NOT NULL",
    "ALTER TABLE authority_operation_cost_evidence ADD COLUMN accounting_basis TEXT NOT NULL DEFAULT 'PRICED'",
    "ALTER TABLE authority_operation_cost_evidence ADD COLUMN cost_status TEXT NOT NULL DEFAULT 'KNOWN'",
    """
    ALTER TABLE authority_operation_cost_evidence
    ADD CONSTRAINT authority_operation_cost_observability_check CHECK (
        (accounting_basis='PRICED' AND cost_status='KNOWN' AND amount IS NOT NULL)
        OR
        (accounting_basis='ACCOUNT_ENTITLEMENT' AND cost_status='UNKNOWN' AND amount IS NULL)
    )
    """,
    """
    CREATE FUNCTION authority_budget_cost_accounting_guard()
    RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        IF ROW(
            OLD.accounting_basis,OLD.estimated_cost_status
        ) IS DISTINCT FROM ROW(
            NEW.accounting_basis,NEW.estimated_cost_status
        ) THEN
            RAISE EXCEPTION 'BUDGET_COST_IDENTITY_IMMUTABLE:%',
                OLD.reservation_id USING ERRCODE='check_violation';
        END IF;
        IF OLD.status IN ('SETTLED','RELEASED','REJECTED')
           AND OLD.settled_cost_status IS DISTINCT FROM NEW.settled_cost_status THEN
            RAISE EXCEPTION 'BUDGET_COST_TERMINAL_IMMUTABLE:%',
                OLD.reservation_id USING ERRCODE='check_violation';
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE TRIGGER authority_budget_cost_accounting_immutable
    BEFORE UPDATE ON authority_budget_reservation
    FOR EACH ROW EXECUTE FUNCTION authority_budget_cost_accounting_guard()
    """,
]


DOWNGRADE_STATEMENTS: list[str] = []

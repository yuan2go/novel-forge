from __future__ import annotations

MIGRATION_ID = "20260718_0026_canon_saga_gate"
DOWN_REVISION = "20260718_0025_canon_approval_authority"

UPGRADE_STATEMENTS = [
    "ALTER TABLE authority_saga DROP CONSTRAINT authority_saga_status_check",
    """
    ALTER TABLE authority_saga
    ADD CONSTRAINT authority_saga_status_check CHECK (status IN (
        'RUNNING', 'FORWARD_RECOVERY', 'WAITING_GATE', 'COMPENSATING',
        'SUCCEEDED', 'COMPENSATED', 'COMPENSATION_FAILED',
        'MANUAL_INTERVENTION', 'CANCELLED'
    ))
    """,
]

DOWNGRADE_STATEMENTS: list[str] = []

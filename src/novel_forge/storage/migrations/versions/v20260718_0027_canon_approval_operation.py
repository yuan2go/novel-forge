from __future__ import annotations

MIGRATION_ID = "20260718_0027_canon_approval_operation"
DOWN_REVISION = "20260718_0026_canon_saga_gate"

UPGRADE_STATEMENTS = [
    "ALTER TABLE authority_canon_approval_decision ADD COLUMN decision_operation_id TEXT REFERENCES authority_operation(operation_id)",
    "CREATE UNIQUE INDEX authority_canon_decision_operation_idx ON authority_canon_approval_decision(decision_operation_id) WHERE decision_operation_id IS NOT NULL",
]

DOWNGRADE_STATEMENTS: list[str] = []

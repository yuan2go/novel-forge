from __future__ import annotations

MIGRATION_ID = "20261007_0164_realization_comparison_uncertainty"
DOWN_REVISION = "20261007_0163_failed_step_successor"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "retain independent intent-comparison uncertainty without rewriting historical realization evidence"
UPGRADE_STATEMENTS = [
    """ALTER TABLE authority_narrative_realization_deviation
        DROP CONSTRAINT authority_narrative_realization_deviation_deviation_kind_check""",
    """ALTER TABLE authority_narrative_realization_deviation ADD CONSTRAINT
        authority_narrative_realization_deviation_deviation_kind_check CHECK (deviation_kind IN (
            'MISSING_REQUIRED_EVENT','UNPLANNED_EVENT','STATE_DELTA_DRIFT',
            'KNOWLEDGE_BOUNDARY_DRIFT','CAUSALITY_DRIFT','REALIZATION_COMPARISON_UNCERTAIN'))""",
]
DOWNGRADE_STATEMENTS: list[str] = []

from __future__ import annotations

MIGRATION_ID = '20261007_0177_realization_comparison_uncertainty'
DOWN_REVISION = '20261007_0176_quality_correction_control'
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "append scoped evidence without rewriting published history or permitting uncertain consumption"

UPGRADE_STATEMENTS = [
    r"""ALTER TABLE authority_narrative_realization_deviation
        DROP CONSTRAINT authority_narrative_realization_deviation_deviation_kind_check""",
    r"""ALTER TABLE authority_narrative_realization_deviation ADD CONSTRAINT
        authority_narrative_realization_deviation_deviation_kind_check CHECK (deviation_kind IN (
            'MISSING_REQUIRED_EVENT','UNPLANNED_EVENT','STATE_DELTA_DRIFT',
            'KNOWLEDGE_BOUNDARY_DRIFT','CAUSALITY_DRIFT','REALIZATION_COMPARISON_UNCERTAIN'))""",
]
DOWNGRADE_STATEMENTS: list[str] = []

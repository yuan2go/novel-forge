from __future__ import annotations

from .v20261007_0168_canon_output_repair import UPGRADE_STATEMENTS as PREVIOUS_GUARDS

MIGRATION_ID = "20261007_0169_quality_correction_control"
DOWN_REVISION = "20261007_0168_canon_output_repair"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "select explicit creative correction controls for unexecuted work while preserving frozen attempts and outputs"
UPGRADE_STATEMENTS = [
    PREVIOUS_GUARDS[0].replace(
        "'creative-execution-template.v9')",
        "'creative-execution-template.v9','creative-execution-template.v10')",
    )
]
DOWNGRADE_STATEMENTS: list[str] = []

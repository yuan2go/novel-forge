from __future__ import annotations

from .v20261006_0162_stage_repair_policy import UPGRADE_STATEMENTS as PREVIOUS_GUARDS

MIGRATION_ID = "20261006_0164_execution_contract_continuation"
DOWN_REVISION = "20261006_0163_failed_step_successor"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "retain prior template semantics and rejected history; explicitly authorized v5 inherits native optional-world and bounded stage repair guards"
UPGRADE_STATEMENTS = [
    PREVIOUS_GUARDS[2].replace(
        "IN ('creative-execution-template.v3','creative-execution-template.v4')",
        "IN ('creative-execution-template.v3','creative-execution-template.v4','creative-execution-template.v5')",
    ).replace(
        "t->>'version'='creative-execution-template.v4'",
        "t->>'version' IN ('creative-execution-template.v4','creative-execution-template.v5')",
    ),
]
DOWNGRADE_STATEMENTS: list[str] = []

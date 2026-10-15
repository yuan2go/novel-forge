from __future__ import annotations

from .v20261014_0210_operation_outbox_lookup_indexes import UPGRADE_STATEMENTS as INDEX_STATEMENTS

MIGRATION_ID = "20261015_0216_operation_evidence_indexes"
DOWN_REVISION = "20261015_0215_planning_input_scope_reads"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Append preserved operation evidence lookup indexes on the current main migration chain."

UPGRADE_STATEMENTS = list(INDEX_STATEMENTS)
DOWNGRADE_STATEMENTS: list[str] = []

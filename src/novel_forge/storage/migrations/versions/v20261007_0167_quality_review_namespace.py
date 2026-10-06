from __future__ import annotations

from .v20261007_0166_retained_graph_continuation import UPGRADE_STATEMENTS as PREVIOUS_GUARDS

MIGRATION_ID = '20261007_0167_quality_review_namespace'
DOWN_REVISION = '20261007_0166_retained_graph_continuation'
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = 'admit an explicit retained Quality result template without rewriting historical snapshots'
UPGRADE_STATEMENTS = [PREVIOUS_GUARDS[0].replace("'creative-execution-template.v7')", "'creative-execution-template.v7','creative-execution-template.v8')")]
DOWNGRADE_STATEMENTS: list[str] = []

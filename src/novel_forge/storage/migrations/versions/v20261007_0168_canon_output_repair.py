from __future__ import annotations

from .v20261007_0167_quality_review_namespace import UPGRADE_STATEMENTS as PREVIOUS_GUARDS

MIGRATION_ID = '20261007_0168_canon_output_repair'
DOWN_REVISION = '20261007_0167_quality_review_namespace'
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = 'admit the explicit Canon output recovery template while preserving frozen history'
UPGRADE_STATEMENTS = [PREVIOUS_GUARDS[0].replace("'creative-execution-template.v8')", "'creative-execution-template.v8','creative-execution-template.v9')")]
DOWNGRADE_STATEMENTS: list[str] = []

from __future__ import annotations

from .v20261014_0209_planning_input_scope_point_reads import UPGRADE_STATEMENTS as SCOPE_STATEMENTS

MIGRATION_ID = "20261015_0215_planning_input_scope_reads"
DOWN_REVISION = "20261015_0214_story_design_book_scope"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Append preserved immutable Planning input point reads on the current main migration chain."

UPGRADE_STATEMENTS = list(SCOPE_STATEMENTS)
DOWNGRADE_STATEMENTS: list[str] = []

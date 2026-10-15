from __future__ import annotations

from . import v20261015_0217_retained_working_continuation as published

MIGRATION_ID = "20261015_0218_retained_working_convergence"
DOWN_REVISION = "20261015_0217_craft_context_convergence"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = published.FORWARD_FIX

UPGRADE_STATEMENTS = list(published.UPGRADE_STATEMENTS)
DOWNGRADE_STATEMENTS: list[str] = []

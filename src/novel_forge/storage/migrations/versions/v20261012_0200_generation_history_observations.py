from __future__ import annotations

from .v20261009_0186_generation_capacity_inheritance import UPGRADE_STATEMENTS as ISOLATION

MIGRATION_ID = "20261012_0200_generation_history_observations"
DOWN_REVISION = "20261011_0199_plan_change_capacity"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Retain generation history without cumulative recovery ceilings; preserve isolation identity and revoked commit rights."

_ISOLATION_FUNCTION = next(statement for statement in ISOLATION if "CREATE OR REPLACE FUNCTION" in statement)
assert "AND r.chain_depth<=3" in _ISOLATION_FUNCTION
UPGRADE_STATEMENTS = [
    "ALTER TABLE authority_story_planning_runtime_continuation DROP CONSTRAINT authority_story_planning_runtime_continuation_chain_depth_check",
    "ALTER TABLE authority_story_planning_runtime_continuation ADD CONSTRAINT authority_story_planning_runtime_continuation_chain_depth_check CHECK (chain_depth > 0)",
    _ISOLATION_FUNCTION.replace(" AND r.chain_depth<=3", ""),
]
DOWNGRADE_STATEMENTS: list[str] = []

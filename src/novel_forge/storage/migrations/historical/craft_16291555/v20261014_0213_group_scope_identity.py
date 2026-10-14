from __future__ import annotations

from .v20261014_0212_group_method_scope_context import UPGRADE_STATEMENTS as PREVIOUS

MIGRATION_ID = "20261014_0213_group_scope_identity"
DOWN_REVISION = "20261014_0212_group_method_scope_context"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Compare the Group Context scope against the owning generation, because the immutable command derives scope from its generator."

_OLD = "context.content->>'planning_scope'=r.source_command->>'planning_scope'"
assert PREVIOUS[0].count(_OLD) == 1
UPGRADE_STATEMENTS = [PREVIOUS[0].replace(_OLD, "context.content->>'planning_scope'=prior.planning_scope")]
DOWNGRADE_STATEMENTS: list[str] = []

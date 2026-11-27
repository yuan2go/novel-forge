from __future__ import annotations

from .v20261007_0179_planning_arc_scope_revalidation import UPGRADE_STATEMENTS as PREVIOUS

MIGRATION_ID = "20261016_0222_planning_host_frozen_definition"
DOWN_REVISION = "20261016_0221_working_scope_fk_indexes"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Read the immutable Operation definition snapshot in the existing Planning Host guard; retain all source, receipt and frontier predicates."

_ANCHOR = "original.definition_hash=r.target_runtime #>> '{planning_host_revalidation,source_definition_hash}'"
assert PREVIOUS[0].count(_ANCHOR) == 1
UPGRADE_STATEMENTS = [PREVIOUS[0].replace(
    _ANCHOR,
    "original.definition_snapshot->>'definition_hash'=r.target_runtime #>> '{planning_host_revalidation,source_definition_hash}'",
)]
DOWNGRADE_STATEMENTS: list[str] = []

from __future__ import annotations

from .v20261015_0217_craft_context_convergence import GUARD_STATEMENT as PREVIOUS_GUARD
from .v20261015_0218_world_exact_context_accounting import _SQL

MIGRATION_ID = "20261015_0219_world_exact_context_convergence"
DOWN_REVISION = "20261015_0218_retained_working_convergence"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Append frozen zero-send World exact accounting without replacing main's capacity or receipt contracts."

# INVARIANT: Extend the current dispatch without removing any existing recovery predicate.
_ANCHOR = "AND NOT authority_prepared_chapter_context_continuation_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))"
assert PREVIOUS_GUARD.count(_ANCHOR) == 1
GUARD_STATEMENT = PREVIOUS_GUARD.replace(
    _ANCHOR,
    _ANCHOR + "\n               AND NOT authority_unsent_world_exact_context_continuation_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))",
)
UPGRADE_STATEMENTS = [_SQL, GUARD_STATEMENT]
DOWNGRADE_STATEMENTS: list[str] = []

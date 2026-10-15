from __future__ import annotations

from .v20261015_0219_world_exact_context_convergence import GUARD_STATEMENT as PREVIOUS_GUARD
from .v20261015_0219_chapter_prior_method_audits import _SQL

MIGRATION_ID = "20261015_0220_chapter_prior_audit_convergence"
DOWN_REVISION = "20261015_0219_world_exact_context_convergence"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Append immutable prior-plan method audit references while retaining World receipts and all prior recovery contracts."

# INVARIANT: Prior-audit continuation augments, rather than replaces, the main guard.
_ANCHOR = "AND NOT authority_unsent_world_exact_context_continuation_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))"
assert PREVIOUS_GUARD.count(_ANCHOR) == 1
GUARD_STATEMENT = PREVIOUS_GUARD.replace(
    _ANCHOR,
    _ANCHOR + "\n               AND NOT authority_chapter_prior_audit_continuation_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))",
)
UPGRADE_STATEMENTS = [_SQL, GUARD_STATEMENT]
DOWNGRADE_STATEMENTS: list[str] = []

from __future__ import annotations

from .v20261015_0216_chapter_method_context import _SQL as CHAPTER_SQL
from .v20261015_0218_world_exact_context_accounting import UPGRADE_STATEMENTS as PREVIOUS

MIGRATION_ID = "20261015_0219_chapter_prior_method_audits"
DOWN_REVISION = "20261015_0218_world_exact_context_accounting"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Keep the original unsent main Chapter failure and verified World receipts; reference only prior plan method audits by their immutable sources."

_SQL = CHAPTER_SQL.replace("authority_prepared_chapter_context_continuation_permitted", "authority_chapter_prior_audit_continuation_permitted").replace(
    "context_revalidation,contract_version}'='chapter-method-scope-projection.v1'",
    "context_revalidation,contract_version}'='chapter-prior-method-audits.v1'").replace(
    "AND context.content->>'planning_chapter_method_scope_projection_version' IS NULL",
    "AND context.content->>'planning_chapter_method_scope_projection_version'='chapter-method-scope-projection.v1' AND context.content->>'planning_prior_method_audit_projection_version' IS NULL")
_GUARD = 'AND NOT authority_unsent_world_exact_context_continuation_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))'
assert PREVIOUS[1].count(_GUARD) == 1
UPGRADE_STATEMENTS = [_SQL, PREVIOUS[1].replace(_GUARD,
    _GUARD + '\n               AND NOT authority_chapter_prior_audit_continuation_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))')]
DOWNGRADE_STATEMENTS: list[str] = []

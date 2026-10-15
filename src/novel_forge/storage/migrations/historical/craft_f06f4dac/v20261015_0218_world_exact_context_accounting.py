from __future__ import annotations

from .v20261015_0215_world_method_context import _SQL as WORLD_SQL
from .v20261015_0216_chapter_method_context import UPGRADE_STATEMENTS as PREVIOUS

MIGRATION_ID = "20261015_0218_world_exact_context_accounting"
DOWN_REVISION = "20261015_0217_retained_working_continuation"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Retain the exact zero-send World protected capacity failure; append lossless accounting evidence under the same frozen method, request and source policy."

_SQL = WORLD_SQL.replace("authority_unsent_world_context_continuation_permitted", "authority_unsent_world_exact_context_continuation_permitted").replace(
    "context_revalidation,contract_version}'='world-method-scope-projection.v1'",
    "context_revalidation,contract_version}'='world-protected-context-accounting.v1'").replace(
    "AND context.content->>'world_method_scope_projection_version' IS NULL",
    "AND context.content->>'world_method_scope_projection_version'='world-method-scope-projection.v1' AND context.content->>'world_protected_context_accounting_version' IS NULL")
_GUARD = 'AND NOT authority_prepared_chapter_context_continuation_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))'
assert PREVIOUS[1].count(_GUARD) == 1
UPGRADE_STATEMENTS = [_SQL, PREVIOUS[1].replace(_GUARD,
    _GUARD + '\n               AND NOT authority_unsent_world_exact_context_continuation_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))')]
DOWNGRADE_STATEMENTS: list[str] = []

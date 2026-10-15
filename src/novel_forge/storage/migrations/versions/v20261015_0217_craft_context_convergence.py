from __future__ import annotations

from . import v20261014_0207_foundation_method_context as foundation
from . import v20261014_0208_book_method_scope_context as book
from . import v20261014_0211_unsent_context_query_recovery as query
from . import v20261014_0212_group_method_scope_context as group
from . import v20261014_0213_group_scope_identity as group_scope
from . import v20261014_0214_book_query_recovery as book_query
from . import v20261015_0215_world_method_context as world
from . import v20261015_0216_chapter_method_context as chapter
from . import v20261014_0211_world_input_delivery_recovery as main_world
from .v20261009_0191_provider_schema_successor import UPGRADE_STATEMENTS as MAIN_GUARD

MIGRATION_ID = "20261015_0217_craft_context_convergence"
DOWN_REVISION = "20261015_0216_operation_evidence_indexes"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Compose precise method projection recovery with current World inheritance, complete receipts and unsent input recovery; retain every historical contract."

def _with_method_scopes(statement: str) -> str:
    assert statement.count(foundation._OLD) == 1
    statement = statement.replace(foundation._OLD, foundation._NEW)
    generators = "IN ('arc_plan.generate','chapter_group_plan.generate','chapter_plan.generate')"
    assert statement.count(generators) == 1
    statement = statement.replace(generators,
        "IN ('arc_plan.generate','chapter_group_plan.generate','chapter_plan.generate','character.cast.generate')")
    assert statement.count(book._OLD) == 1
    return statement.replace(book._OLD, book._NEW).replace(
        "IN ('arc_plan.generate','chapter_group_plan.generate','chapter_plan.generate','character.cast.generate')",
        "IN ('arc_plan.generate','chapter_group_plan.generate','chapter_plan.generate','character.cast.generate','book_plan.generate')",
    )


_CURRENT = _with_method_scopes(main_world.UPGRADE_STATEMENTS[1])

# INVARIANT: The rendered Group branch inherits the latest main prefix, including World lineage guards, before adding its exact historical failure proof.
_PREFIX = _with_method_scopes(main_world._PREFIX)
_GROUP_TAIL = group._GROUP[group._GROUP.index(main_world._ANCHOR):]
assert _GROUP_TAIL.count(group_scope._OLD) == 1
_GROUP_TAIL = _GROUP_TAIL.replace(group_scope._OLD,
    "context.content->>'planning_scope'=prior.planning_scope")
_GROUP = _PREFIX.replace("'typed-planning-window-projection.v1'", "'group-method-scope-projection.v1'") + _GROUP_TAIL
_HEADER, _BODY = _CURRENT.split("    SELECT ", 1)
_, _GROUP_BODY = _GROUP.split("    SELECT ", 1)
assert _BODY.rstrip().endswith("$$")
CAPACITY_STATEMENT = _HEADER + "    SELECT " + _BODY.rstrip().removesuffix("$$").rstrip() + " OR " + _GROUP_BODY + " $$"

# COMPATIBILITY: These distinct functions retain their frozen query, zero-effect World and completed-World Chapter contracts; the common guard dispatches by durable evidence.
QUERY_STATEMENTS = [query.UPGRADE_STATEMENTS[0], book_query.UPGRADE_STATEMENTS[0]]
WORLD_STATEMENTS = [world.UPGRADE_STATEMENTS[0], chapter.UPGRADE_STATEMENTS[0]]
GUARD_STATEMENT = chapter.UPGRADE_STATEMENTS[1]
_BASE_GUARD = MAIN_GUARD[1]
_BASE_END = "AND NOT authority_schema_continuation_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))"
assert _BASE_GUARD.count(_BASE_END) == 1
assert GUARD_STATEMENT == _BASE_GUARD.replace(_BASE_END,
    _BASE_END
    + "\n               AND NOT authority_unsent_query_continuation_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))"
    + "\n               AND NOT authority_book_unsent_query_continuation_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))"
    + "\n               AND NOT authority_unsent_world_context_continuation_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))"
    + "\n               AND NOT authority_prepared_chapter_context_continuation_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))")
UPGRADE_STATEMENTS = [CAPACITY_STATEMENT, *QUERY_STATEMENTS, *WORLD_STATEMENTS, GUARD_STATEMENT]
DOWNGRADE_STATEMENTS: list[str] = []

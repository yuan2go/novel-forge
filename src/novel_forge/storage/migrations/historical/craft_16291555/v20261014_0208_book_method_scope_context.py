from __future__ import annotations

from .v20261014_0207_foundation_method_context import UPGRADE_STATEMENTS as PREVIOUS

MIGRATION_ID = "20261014_0208_book_method_scope_context"
DOWN_REVISION = "20261014_0207_foundation_method_context"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Permit exact unsent experimental Book method scope with immutable selected methods, Foundation inputs and native zero-effect recovery proof."

_OLD = """AND jsonb_array_length(context.content #> '{narrative_intelligence,selected}')>0))"""
_NEW = """AND jsonb_array_length(context.content #> '{narrative_intelligence,selected}')>0)
          OR (generation->>'generator_operation_name'='book_plan.generate'
          AND generation->>'planning_scope'='BOOK'
          AND r.target_runtime #>> '{planning_capacity,context_revalidation,contract_version}'='book-method-scope-projection.v1'
          AND context.content #>> '{knowledge_access_policy,craft_candidate_review_version}'='explicit-allowlist-craft-review.v1'
          AND context.content #>> '{knowledge_access_policy,usage_scope}'='EXPERIMENTAL_VALIDATION'
          AND context.content #>> '{knowledge_access_policy,mode}'='ALLOW_ONLY'
          AND context.content->>'book_id'=r.book_id
          AND context.content->>'project_id'=r.project_id
          AND jsonb_array_length(context.content #> '{narrative_intelligence,selected}')>0))"""
assert PREVIOUS[0].count(_OLD) == 1
UPGRADE_STATEMENTS = [PREVIOUS[0].replace(_OLD, _NEW).replace(
    "IN ('arc_plan.generate','chapter_group_plan.generate','chapter_plan.generate','character.cast.generate')",
    "IN ('arc_plan.generate','chapter_group_plan.generate','chapter_plan.generate','character.cast.generate','book_plan.generate')",
)]
DOWNGRADE_STATEMENTS: list[str] = []

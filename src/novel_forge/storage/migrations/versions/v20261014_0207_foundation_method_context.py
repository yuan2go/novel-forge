from __future__ import annotations

from .v20261012_0203_capacity_availability_observation import UPGRADE_STATEMENTS as PREVIOUS

MIGRATION_ID = "20261014_0207_foundation_method_context"
DOWN_REVISION = "20261014_0206_story_design_book_namespace"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Permit exact unsent Character Cast method-query projection with experimental scope, frozen Context, input, authorization and lease evidence."

_OLD = """OR (generation->>'generator_operation_name'='chapter_plan.generate'
          AND r.target_runtime #>> '{planning_capacity,context_revalidation,contract_version}'='planning-exact-value-reference.v1'))"""
_NEW = """OR (generation->>'generator_operation_name'='chapter_plan.generate'
          AND r.target_runtime #>> '{planning_capacity,context_revalidation,contract_version}'='planning-exact-value-reference.v1')
          OR (generation->>'generator_operation_name'='character.cast.generate'
          AND generation->>'planning_scope'='NOT_APPLICABLE'
          AND r.target_runtime #>> '{planning_capacity,context_revalidation,contract_version}'='foundation-method-recall-projection.v1'
          AND context.content #>> '{knowledge_access_policy,craft_candidate_review_version}'='explicit-allowlist-craft-review.v1'
          AND context.content #>> '{knowledge_access_policy,usage_scope}'='EXPERIMENTAL_VALIDATION'
          AND context.content #>> '{knowledge_access_policy,mode}'='ALLOW_ONLY'
          AND context.content->>'book_id'=r.book_id
          AND context.content->>'project_id'=r.project_id
          AND jsonb_array_length(context.content #> '{narrative_intelligence,selected}')>0))"""
assert PREVIOUS[0].count(_OLD) == 1
UPGRADE_STATEMENTS = [PREVIOUS[0].replace(_OLD, _NEW).replace(
    "IN ('arc_plan.generate','chapter_group_plan.generate','chapter_plan.generate')",
    "IN ('arc_plan.generate','chapter_group_plan.generate','chapter_plan.generate','character.cast.generate')",
)]
DOWNGRADE_STATEMENTS: list[str] = []

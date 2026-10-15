from __future__ import annotations

from .v20261014_0208_book_method_scope_context import UPGRADE_STATEMENTS as PREVIOUS

MIGRATION_ID = "20261014_0212_group_method_scope_context"
DOWN_REVISION = "20261014_0211_unsent_context_query_recovery"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Permit the exact zero-send rendered Group capacity failure to retain its frozen repair candidate under an explicit method scope projection."

_OLD = PREVIOUS[0]
_HEADER, _BODY = _OLD.split("    SELECT ", 1)
assert _BODY.endswith("\n    ) $$")
_BODY = _BODY.removesuffix(" $$")
_ROUTE = "      AND EXISTS(SELECT 1 FROM authority_operation_output_asset output\n        JOIN authority_asset_version version USING(asset_version_id) JOIN authority_asset asset ON asset.asset_id=version.asset_id\n        WHERE output.operation_id=source.operation_id AND asset.asset_type='routing_decision'"
assert _BODY.count(_ROUTE) == 1
_GROUP = _BODY[:_BODY.index(_ROUTE)]
_GROUP = _GROUP.replace("'typed-planning-window-projection.v1'", "'group-method-scope-projection.v1'")
assert _GROUP.count("='PROVIDER_ROUTING_BLOCKED')") == 1
_GROUP = _GROUP.replace("='PROVIDER_ROUTING_BLOCKED')", "='CONTEXT_CAPACITY_EXCEEDED'\n        AND attempt.result->>'error_message'='CONTEXT_CAPACITY_EXCEEDED: Complete input leaves no model context for generation')")
_GROUP += """      AND generation->>'generator_operation_name'='chapter_group_plan.generate'
      AND r.source_command->>'execution_contract_version'='1.21.0'
      AND r.target_runtime #>> '{planning_capacity,context_revalidation,contract_version}'='group-method-scope-projection.v1'
      AND r.target_runtime #>> '{planning_capacity,context_revalidation,source_operation_status}'='FAILED_RETRYABLE'
      AND r.target_runtime #>> '{planning_capacity,context_revalidation,failure_message}'='Complete input leaves no model context for generation'
      AND context.content->>'planning_group_method_scope_projection_version' IS NULL
      AND context.content->>'project_id'=r.project_id AND context.content->>'book_id'=r.book_id
      AND context.content->>'planning_scope'=r.source_command->>'planning_scope'
      AND context.content #>> '{knowledge_access_policy,craft_candidate_review_version}'='explicit-allowlist-craft-review.v1'
      AND context.content #>> '{knowledge_access_policy,usage_scope}'='EXPERIMENTAL_VALIDATION'
      AND context.content #>> '{knowledge_access_policy,mode}'='ALLOW_ONLY'
      AND jsonb_array_length(context.content #> '{narrative_intelligence,selected}')>0
      AND NULLIF(r.source_command->>'repair_of_candidate_id','') IS NOT NULL
      AND context.content #>> '{repair_context,source_candidate,asset_version_id}'=r.source_command->>'repair_of_candidate_id'
      AND NOT EXISTS(SELECT 1 FROM authority_operation_output_asset WHERE operation_id=source.operation_id AND output_key<>'planning.context_bundle')
      AND NOT EXISTS(SELECT 1 FROM authority_attempt WHERE operation_id=source.operation_id AND status IN ('CLAIMED','EXECUTING','WAITING_EXTERNAL_RESULT','LEASED','RUNNING','CHECKPOINTED','RESULT_SUBMITTED'))
    )"""
UPGRADE_STATEMENTS = [_HEADER + "    SELECT " + _BODY + " OR " + _GROUP + " $$"]
DOWNGRADE_STATEMENTS: list[str] = []

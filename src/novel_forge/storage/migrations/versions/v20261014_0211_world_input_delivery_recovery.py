from __future__ import annotations

from .v20261014_0210_world_working_frontier_revalidation import UPGRADE_STATEMENTS as PREVIOUS

MIGRATION_ID = "20261014_0211_world_input_delivery_recovery"
DOWN_REVISION = "20261014_0210_world_working_frontier_revalidation"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Admit a proven unsent World input delivery successor at unchanged capacity and frozen story inputs; retain the failed operation and legacy guards."

_FUNCTION = PREVIOUS[2]
_ANCHOR = "      AND EXISTS(SELECT 1 FROM authority_attempt attempt WHERE attempt.operation_id=source.operation_id\n"
assert _FUNCTION.count(_ANCHOR) == 1
_PREFIX, _LEGACY = _FUNCTION.split(_ANCHOR, 1)
_LEGACY = _LEGACY.rstrip()
assert _LEGACY.endswith("    ) $$")
_LEGACY = (_ANCHOR + _LEGACY.removesuffix("    ) $$")).removeprefix("      AND ")
_DELIVERY = r"""EXISTS(SELECT 1 FROM authority_attempt attempt
        JOIN authority_asset_version frozen ON frozen.asset_version_id=r.target_runtime#>>'{planning_capacity,context_revalidation,world_input_delivery,source_ref,asset_version_id}'
        JOIN authority_asset asset ON asset.asset_id=frozen.asset_id AND asset.asset_type='world_preparation_source' AND asset.project_id=r.project_id
        JOIN authority_operation_output_asset output ON output.asset_version_id=frozen.asset_version_id AND output.operation_id=source.operation_id
        JOIN authority_book_production book ON book.book_run_id=frozen.content#>>'{contract,request,book_run_id}'
        WHERE attempt.operation_id=source.operation_id AND attempt.status='FAILED_FINAL'
          AND attempt.attempt_number=(SELECT max(attempt_number) FROM authority_attempt WHERE operation_id=source.operation_id)
          AND COALESCE(attempt.error->>'error_code',attempt.result->>'error_code')='PROGRAMMING_BUG'
          AND starts_with(COALESCE(attempt.error->>'error_message',attempt.result->>'error_message'),'PROTECTED_CONTEXT_BUDGET_EXCEEDED:')
          AND source.status='FAILED_FINAL' AND source.definition_version='1.21.0'
          AND registered.actor_id=source.actor_id AND registered.project_id=r.project_id AND registered.workspace_id=r.workspace_id
          AND generation->>'generator_operation_name'='chapter_plan.generate' AND generation->>'planning_scope'='CHAPTER'
          AND r.target_runtime#>>'{planning_capacity,context_revalidation,contract_version}'='planning-exact-value-reference.v1'
          AND r.target_runtime#>>'{planning_capacity,context_revalidation,world_input_delivery,contract_version}'='world-input-delivery-revalidation.v1'
          AND r.target_runtime#>>'{planning_capacity,context_revalidation,world_input_delivery,provider_projection_version}'='world-role-delivery.v4'
          AND r.target_runtime#>'{planning_capacity,prior_task_tokens}'=r.target_runtime#>'{planning_capacity,allocated_task_tokens}'
          AND r.target_runtime#>>'{planning_capacity,context_revalidation,world_input_delivery,delivered_task_hash}' ~ '^sha256:[0-9a-f]{64}$'
          AND r.target_runtime#>>'{planning_capacity,context_revalidation,world_input_delivery,context_projection_hash}' ~ '^sha256:[0-9a-f]{64}$'
          AND r.target_runtime#>'{planning_capacity,context_revalidation,world_input_delivery,historical_failure}'=attempt.result
          AND frozen.content_hash=r.target_runtime#>>'{planning_capacity,context_revalidation,world_input_delivery,source_ref,content_hash}'
          AND frozen.content#>>'{contract,contract_version}'='world-preparation-source.v5'
          AND frozen.content#>>'{contract,provider_projection_version}'='world-role-delivery.v3'
          AND frozen.content#>'{contract,actor_experiment}' IS NULL
          AND frozen.content#>'{contract,request}'=source.command_payload#>'{payload,world_preparation_request}'
          AND frozen.content#>'{contract,working_manuscript}'=source.command_payload#>'{payload,arc_working_set,working_manuscript}'
          AND frozen.content#>>'{contract,working_manuscript,book_run_id}'=book.book_run_id
          AND frozen.content#>>'{contract,working_manuscript,target_chapter}'=frozen.content#>>'{contract,target_chapter}'
          AND book.project_id=r.project_id AND book.workspace_id=r.workspace_id AND book.book_id=r.book_id
          AND book.state IN ('READY','CHAPTER_PLAN_REQUIRED') AND book.active_chapter_request_id IS NULL
          AND (book.current_chapter+1)::text=frozen.content#>>'{contract,target_chapter}'
          AND prior.logical_key='chapter:'||(book.current_chapter+1)::text
          AND book.accepted_through_chapter::text=frozen.content#>>'{contract,request,accepted_through_chapter}'
          AND book.input_snapshot_id=frozen.content#>>'{contract,request,input_snapshot_id}'
          AND NOT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=source.operation_id)
          AND NOT EXISTS(SELECT 1 FROM authority_budget_reservation WHERE operation_id=source.operation_id)
          AND NOT EXISTS(SELECT 1 FROM authority_attempt active WHERE active.operation_id=source.operation_id AND active.status IN ('LEASED','RUNNING','CHECKPOINTED','RESULT_SUBMITTED')))
"""
UPGRADE_STATEMENTS = [
    _FUNCTION.replace("authority_unsent_context_continuation_permitted(", "authority_unsent_context_continuation_permitted_legacy_0211("),
    _PREFIX + "      AND ((" + _LEGACY + " AND r.target_runtime#>'{planning_capacity,context_revalidation,world_input_delivery}' IS NULL) OR (" + _DELIVERY + "))\n    ) $$\n",
]
DOWNGRADE_STATEMENTS: list[str] = []

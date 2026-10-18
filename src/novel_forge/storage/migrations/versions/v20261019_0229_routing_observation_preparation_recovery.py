from __future__ import annotations

from .v20261018_0226_semantic_preparation_continuation import PERMITTED as SEMANTIC_PERMITTED
from .v20261018_0228_terminal_preparation_handoff import GUARD_STATEMENT as PREVIOUS_GUARD

MIGRATION_ID = '20261019_0229_routing_observation_preparation_recovery'
DOWN_REVISION = '20261018_0228_terminal_preparation_handoff'
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = 'Index unchanged real-Provider observation cohort lookup and append exact zero-send query-failure preparation handoffs without changing terminal history or old commit rights.'

OBSERVATION_INDEX = """CREATE INDEX authority_real_model_observation_cohort_idx ON authority_asset_version (
 (COALESCE(content->>'stage',COALESCE(content->'provider_evidence',content)#>>'{production_execution,execution_request,stage}')),
 ((COALESCE(content->'provider_evidence',content))->>'provider_id'),
 ((COALESCE(content->'provider_evidence',content))->>'model_id'),
 ((COALESCE(content->'provider_evidence',content))#>>'{production_execution,route_snapshot,reasoning_effort}'),
 created_at DESC) WHERE COALESCE(COALESCE(content->'provider_evidence',content)->>'real_model_call',
 COALESCE(content->'provider_evidence',content)->>'real_provider_proven')='true'"""


CHAIN_INDEX = """CREATE INDEX authority_routing_observation_chain_idx ON authority_external_effect (
 project_id,(request_payload #>> '{_production_execution,capability_runtime,routing_decision,task,chain_id}'),created_at)"""
GENERATED_INDEX = """CREATE INDEX authority_generated_effect_observation_idx ON authority_asset_version (
 (content #>> '{provider_evidence,production_execution,execution_request,external_effect_id}'),created_at DESC)
 WHERE content #>> '{provider_evidence,production_execution,execution_request,external_effect_id}' IS NOT NULL"""

PERMITTED = SEMANTIC_PERMITTED.replace('authority_semantic_preparation_continuation_permitted', 'authority_unsent_preparation_query_permitted')
for before, after in (
    (" JOIN authority_operation_output_asset output ON output.operation_id=source.operation_id AND output.output_key='planning.context_bundle'\n JOIN authority_asset_version context ON context.asset_version_id=output.asset_version_id AND context.content_hash=output.content_hash",
     " JOIN authority_asset_version context ON context.asset_version_id=r.target_runtime#>>'{preparation_handoff,context_asset_version_id}' AND context.content_hash=r.target_runtime#>>'{preparation_handoff,context_content_hash}'"),
    ("AND registration.status='SUCCEEDED' AND registration.definition_name='story_planning.runtime_continuation.register'",
     "AND registration.status='SUCCEEDED' AND registration.definition_name='story_planning.runtime_continuation.register' AND registration.definition_version='8.0.0'"),
    ("AND attempt.status='FAILED_RETRYABLE' AND attempt.result->>'error_code'='PROVIDER_CONTEXT_CAPACITY_UNCERTAIN'\n AND attempt.result->>'error_message'='PROVIDER_CONTEXT_CAPACITY_UNCERTAIN: a byte upper bound exceeds capacity; configure a matched tokenizer before lossy compression'\n AND attempt.result->>'failure_class'='retryable' AND attempt.result#>'{failure_details,actual_tokens}'='null'::jsonb\n AND (attempt.result#>>'{failure_details,upper_bound}')::integer>(attempt.result#>>'{failure_details,limit}')::integer\n AND (attempt.result#>>'{failure_details,limit}')::integer>0",
     "AND attempt.status='FAILED_FINAL' AND attempt.result->>'error_code'='PROGRAMMING_BUG'\n AND attempt.result->>'error_message'='canceling statement due to statement timeout'\n AND attempt.result->>'failure_class'='programming_bug' AND attempt.result->'failure_details'='{}'::jsonb"),
    ("AND r.target_runtime#>'{planning_capacity,context_revalidation,source_failure}'=attempt.result\n AND r.target_runtime#>'{planning_capacity,context_revalidation,single_request_limit}'=attempt.result#>'{failure_details,limit}'",
     "AND r.target_runtime#>'{preparation_handoff,unsent_query_failure,original_failure}'=attempt.result\n AND r.target_runtime#>>'{preparation_handoff,unsent_query_failure,source_operation_id}'=source.operation_id\n AND r.target_runtime#>>'{preparation_handoff,unsent_query_failure,source_attempt_id}'=attempt.attempt_id"),
    ("AND r.target_runtime#>'{planning_capacity,single_request_ceiling}'=attempt.result#>'{failure_details,limit}'",
     "AND r.target_runtime#>'{planning_capacity,single_request_ceiling}'=r.target_runtime#>'{planning_capacity,context_revalidation,single_request_limit}'"),
):
    assert before in PERMITTED
    PERMITTED = PERMITTED.replace(before, after)
_EXTRA = """
 AND r.target_runtime#>>'{preparation_handoff,contract_version}'='planning-unsent-preparation-query-handoff.v1'
 AND r.target_runtime#>>'{preparation_handoff,source_submission_rights}'='RELEASED_BY_UNSENT_QUERY_FAILURE'
 AND r.target_runtime#>'{preparation_handoff,main_dispatch_count}'='0'::jsonb
 AND jsonb_array_length(r.target_runtime#>'{preparation_handoff,retained_preparation}')>0
 AND (SELECT count(*) FROM authority_operation_output_asset WHERE operation_id=source.operation_id)<=1
 AND NOT EXISTS(SELECT 1 FROM authority_operation_output_asset WHERE operation_id=source.operation_id
   AND (output_key IS DISTINCT FROM 'planning.context_bundle' OR role IS DISTINCT FROM 'context_bundle' OR content_hash IS DISTINCT FROM context.content_hash))
 AND NOT EXISTS(SELECT 1 FROM authority_cancellation_command WHERE operation_id=book.root_operation_id)
 AND r.target_runtime#>>'{preparation_handoff,input_snapshot_id}'=book.input_snapshot_id
 AND source.actor_id=registration.actor_id
 AND EXISTS(SELECT 1 FROM authority_operation_output_asset prior_output
   JOIN authority_operation prior_registration ON prior_registration.operation_id=prior_output.operation_id
   JOIN authority_asset_version prior_receipt ON prior_receipt.asset_version_id=prior_output.asset_version_id
   JOIN authority_asset prior_asset ON prior_asset.asset_id=prior_receipt.asset_id
   WHERE prior_registration.status='SUCCEEDED' AND prior_registration.definition_name='story_planning.runtime_continuation.register'
    AND prior_registration.definition_version IN ('7.0.0','8.0.0') AND prior_registration.actor_id=source.actor_id
    AND prior_asset.project_id=r.project_id AND prior_asset.asset_type='planning_runtime_continuation' AND prior_output.role='primary'
    AND prior_receipt.content->>'continuation_id'=r.source_command->>'runtime_continuation_id'
    AND prior_receipt.content->'successor_command'=r.source_command
    AND prior_receipt.content#>>'{target_runtime,preparation_handoff,contract_version}' IN ('planning-isolated-preparation-handoff.v1','planning-unsent-preparation-query-handoff.v1')
    AND prior_receipt.content#>'{target_runtime,preparation_handoff}'=r.target_runtime#>'{preparation_handoff,unsent_query_failure,inherited_preparation}'
    AND ((r.target_runtime->'preparation_handoff')-'contract_version'-'unsent_query_failure'-'source_submission_rights')=
        ((prior_receipt.content#>'{target_runtime,preparation_handoff}')-'contract_version'-'unsent_query_failure'-'source_submission_rights')
    AND r.target_runtime#>'{planning_capacity,allocated_task_tokens}'=prior_receipt.content#>'{target_runtime,planning_capacity,allocated_task_tokens}'
    AND r.target_runtime#>'{planning_capacity,single_request_ceiling}'=prior_receipt.content#>'{target_runtime,planning_capacity,single_request_ceiling}')
"""
PERMITTED = PERMITTED.replace(') $$', _EXTRA + ') $$')
_ANCHOR = 'AND NOT authority_terminal_preparation_handoff_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))'
assert PREVIOUS_GUARD.count(_ANCHOR) == 1
GUARD_STATEMENT = PREVIOUS_GUARD.replace(_ANCHOR, _ANCHOR + '\n               AND NOT authority_unsent_preparation_query_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))')
UPGRADE_STATEMENTS = [OBSERVATION_INDEX, CHAIN_INDEX, GENERATED_INDEX, PERMITTED, GUARD_STATEMENT]
DOWNGRADE_STATEMENTS: list[str] = []

from __future__ import annotations

from .v20261018_0226_semantic_preparation_continuation import PERMITTED as SEMANTIC_PERMITTED
from .v20261019_0230_unsent_preparation_lineage import GUARD_STATEMENT as PREVIOUS_GUARD, QUERY_V9_PERMITTED

MIGRATION_ID = '20261019_0231_prepared_main_handoff'
DOWN_REVISION = '20261019_0230_unsent_preparation_lineage'
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = 'Append exact failed pre-submit main handoff, preserving failed Dispatch history, settled preparation and the complete frozen projection without restoring old submission rights.'

PERMITTED = SEMANTIC_PERMITTED
for before, after in (
    ('authority_semantic_preparation_continuation_permitted', 'authority_prepared_main_handoff_permitted'),
    (" JOIN authority_operation_output_asset output ON output.operation_id=source.operation_id AND output.output_key='planning.context_bundle'\n JOIN authority_asset_version context ON context.asset_version_id=output.asset_version_id AND context.content_hash=output.content_hash",
     " JOIN authority_asset_version context ON context.asset_version_id=r.target_runtime#>>'{preparation_handoff,context_asset_version_id}' AND context.content_hash=r.target_runtime#>>'{preparation_handoff,context_content_hash}'"),
    ("AND registration.status='SUCCEEDED' AND registration.definition_name='story_planning.runtime_continuation.register'",
     "AND registration.status='SUCCEEDED' AND registration.definition_name='story_planning.runtime_continuation.register' AND registration.definition_version='10.0.0' AND registration.actor_id=source.actor_id"),
    ("AND attempt.status='FAILED_RETRYABLE' AND attempt.result->>'error_code'='PROVIDER_CONTEXT_CAPACITY_UNCERTAIN'\n AND attempt.result->>'error_message'='PROVIDER_CONTEXT_CAPACITY_UNCERTAIN: a byte upper bound exceeds capacity; configure a matched tokenizer before lossy compression'\n AND attempt.result->>'failure_class'='retryable' AND attempt.result#>'{failure_details,actual_tokens}'='null'::jsonb\n AND (attempt.result#>>'{failure_details,upper_bound}')::integer>(attempt.result#>>'{failure_details,limit}')::integer\n AND (attempt.result#>>'{failure_details,limit}')::integer>0",
     "AND attempt.status='FAILED_RETRYABLE' AND attempt.result->>'error_code'='EFFECT_RETRYABLE_FAILURE_RECORDED'\n AND attempt.result->>'error_message'='EFFECT_RETRYABLE_FAILURE_RECORDED: adapter exception was recorded as retryable_failure'\n AND attempt.result->>'failure_class'='retryable' AND attempt.result->'failure_details'='{}'::jsonb"),
    ("AND r.target_runtime#>'{planning_capacity,context_revalidation,source_failure}'=attempt.result\n AND r.target_runtime#>'{planning_capacity,context_revalidation,single_request_limit}'=attempt.result#>'{failure_details,limit}'",
     "AND r.target_runtime#>'{preparation_handoff,prepared_main_failure,original_failure}'=attempt.result\n AND r.target_runtime#>>'{preparation_handoff,prepared_main_failure,source_operation_id}'=source.operation_id\n AND r.target_runtime#>>'{preparation_handoff,prepared_main_failure,source_attempt_id}'=attempt.attempt_id"),
    ("AND r.target_runtime#>'{planning_capacity,external_intents_at_source}'='0'::jsonb",
     "AND (r.target_runtime#>>'{planning_capacity,external_intents_at_source}')::integer=(SELECT count(*) FROM authority_external_effect WHERE operation_id=source.operation_id)"),
    ("AND r.target_runtime#>'{planning_capacity,single_request_ceiling}'=attempt.result#>'{failure_details,limit}'",
     "AND r.target_runtime#>'{planning_capacity,single_request_ceiling}'=r.target_runtime#>'{planning_capacity,context_revalidation,single_request_limit}'"),
    (" AND NOT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=source.operation_id)\n AND NOT EXISTS(SELECT 1 FROM authority_budget_reservation WHERE operation_id=source.operation_id)",
     " AND NOT EXISTS(SELECT 1 FROM authority_budget_reservation WHERE operation_id=source.operation_id AND status NOT IN ('SETTLED','RELEASED'))"),
):
    assert before in PERMITTED
    PERMITTED = PERMITTED.replace(before, after)

_EXTRA = """
 AND r.target_runtime#>>'{preparation_handoff,contract_version}'='planning-prepared-main-handoff.v1'
 AND r.target_runtime#>>'{preparation_handoff,source_submission_rights}'='RELEASED_BY_TERMINAL_PRE_SUBMIT_HANDOFF'
 AND r.target_runtime#>'{preparation_handoff,main_dispatch_count}'='1'::jsonb
 AND r.target_runtime#>>'{preparation_handoff,input_snapshot_id}'=book.input_snapshot_id
 AND NOT EXISTS(SELECT 1 FROM authority_cancellation_command WHERE operation_id=book.root_operation_id)
 AND EXISTS(SELECT 1 FROM authority_external_effect main
   JOIN authority_budget_reservation budget USING(external_effect_id)
   JOIN authority_external_effect_dispatch dispatch USING(external_effect_id)
   WHERE main.external_effect_id=r.target_runtime#>>'{preparation_handoff,prepared_main_failure,external_effect_id}'
    AND main.operation_id=source.operation_id AND main.project_id=r.project_id AND main.effect_type='model.invoke'
    AND main.status='FAILED_RETRYABLE' AND budget.status='RELEASED'
    AND main.request_hash=r.target_runtime#>>'{preparation_handoff,prepared_main_failure,request_hash}'
    AND main.request_payload->>'stage'=prior.generator_operation_name
    AND main.request_payload->>'operation_id'=source.operation_id
    AND main.request_payload#>>'{_production_execution,attempt_id}'=attempt.attempt_id
    AND main.last_error=jsonb_build_object('message','Planning gateway execution failed: KernelError: CORPUS_CONSUMPTION_INPUT_BOUND: provider input exceeds lineage inspection bounds',
      'error_type','ExternalEffectAdapterError','failure_kind','transport','request_sent',false)
    AND main.last_error=r.target_runtime#>'{preparation_handoff,prepared_main_failure,diagnostic}'
    AND dispatch.status='FAILED_RETRYABLE' AND dispatch.evidence=main.last_error
    AND dispatch.dispatch_id=r.target_runtime#>>'{preparation_handoff,prepared_main_failure,dispatch_id}'
    AND dispatch.generation=(r.target_runtime#>>'{preparation_handoff,prepared_main_failure,generation}')::integer
    AND (SELECT count(*) FROM authority_external_effect_dispatch WHERE external_effect_id=main.external_effect_id)=1
    AND NOT EXISTS(SELECT 1 FROM authority_effect_dispatch_lease WHERE dispatch_id=dispatch.dispatch_id AND status='HELD')
    AND NOT EXISTS(SELECT 1 FROM authority_external_receipt WHERE dispatch_id=dispatch.dispatch_id)
    AND NOT EXISTS(SELECT 1 FROM authority_asset_version v JOIN authority_asset a USING(asset_id)
      WHERE a.project_id=r.project_id AND a.asset_type='execution_recovery_session'
       AND v.content#>>'{record,request,external_effect_id}'=main.external_effect_id)
    AND main.request_payload#>'{input,_context_capacity_projection,source_boundary}'=r.target_runtime#>'{preparation_handoff,preparation_source_boundary}'
    AND main.request_payload#>>'{input,_context_capacity_projection,original_hash}'=r.target_runtime#>>'{preparation_handoff,preparation_source_projection_hash}')
 AND NOT EXISTS(SELECT 1 FROM authority_external_effect prepared
   LEFT JOIN authority_budget_reservation budget USING(external_effect_id)
   WHERE prepared.operation_id=source.operation_id
    AND prepared.external_effect_id<>r.target_runtime#>>'{preparation_handoff,prepared_main_failure,external_effect_id}'
    AND NOT COALESCE(prepared.effect_type='model.invoke' AND prepared.status='SUCCEEDED' AND budget.status='SETTLED'
      AND prepared.request_payload->>'stage' IN ('context_compress','context_fidelity')
      AND prepared.request_payload#>'{input,context_compression_task,frozen_input_boundary}'=r.target_runtime#>'{preparation_handoff,preparation_source_boundary}'
      AND prepared.request_payload#>>'{input,context_compression_task,task,source_projection_hash}'=r.target_runtime#>>'{preparation_handoff,preparation_source_projection_hash}'
      AND r.target_runtime#>'{preparation_handoff,retained_preparation}' @> jsonb_build_array(jsonb_build_object(
        'external_effect_id',prepared.external_effect_id,'operation_id',source.operation_id,'request_hash',prepared.request_hash,
        'stage',prepared.request_payload->>'stage','receipt_contract','STOPPED_GENERATION_SIBLING'))
      AND EXISTS(SELECT 1 FROM authority_external_effect_dispatch d JOIN authority_external_receipt receipt USING(dispatch_id)
        WHERE d.external_effect_id=prepared.external_effect_id AND d.status='SUCCEEDED' AND receipt.status='VERIFIED'),false))
 AND EXISTS(SELECT 1 FROM authority_story_planning_runtime_continuation parent
   JOIN authority_operation control ON control.operation_id=parent.registered_by_operation_id
   JOIN authority_operation_output_asset output ON output.operation_id=control.operation_id AND output.role='primary'
   JOIN authority_asset_version receipt ON receipt.asset_version_id=output.asset_version_id AND receipt.content_hash=output.content_hash
   WHERE parent.continuation_id=r.source_command->>'runtime_continuation_id' AND parent.successor_operation_id=source.operation_id
    AND parent.successor_command=r.source_command AND parent.project_id=r.project_id AND parent.book_id=r.book_id
    AND control.status='SUCCEEDED' AND control.definition_name='story_planning.runtime_continuation.register'
    AND receipt.content->'target_runtime'=parent.target_runtime
    AND parent.target_runtime#>'{preparation_handoff}'=r.target_runtime#>'{preparation_handoff,prepared_main_failure,inherited_preparation}'
    AND parent.target_runtime#>>'{preparation_handoff,context_asset_version_id}'=context.asset_version_id
    AND parent.target_runtime#>>'{preparation_handoff,context_content_hash}'=context.content_hash
    AND parent.target_runtime#>'{preparation_handoff,preparation_source_boundary}'=r.target_runtime#>'{preparation_handoff,preparation_source_boundary}'
    AND parent.target_runtime#>'{preparation_handoff,preparation_source_projection_hash}'=r.target_runtime#>'{preparation_handoff,preparation_source_projection_hash}'
    AND (r.target_runtime#>'{preparation_handoff,retained_preparation}') @> (parent.target_runtime#>'{preparation_handoff,retained_preparation}')
    AND parent.target_runtime->'planning_capacity'->'context_revalidation'=r.target_runtime->'planning_capacity'->'context_revalidation'
    AND parent.target_runtime#>'{planning_capacity,allocated_task_tokens}'=r.target_runtime#>'{planning_capacity,allocated_task_tokens}'
    AND parent.target_runtime#>'{planning_capacity,single_request_ceiling}'=r.target_runtime#>'{planning_capacity,single_request_ceiling}')
"""
PERMITTED = PERMITTED.replace(') $$', _EXTRA + ') $$')
_ANCHOR = 'AND NOT authority_unsent_preparation_lineage_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))'
assert PREVIOUS_GUARD.count(_ANCHOR) == 1
GUARD_STATEMENT = PREVIOUS_GUARD.replace(_ANCHOR, _ANCHOR + '\n               AND NOT authority_prepared_main_handoff_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))')
HOST_PERMITTED = []
for kind in ('query', 'lineage'):
    statement = QUERY_V9_PERMITTED
    for before, after in (
        ('authority_unsent_preparation_query_v9_permitted', 'authority_prepared_main_' + kind + '_permitted'),
        ("registration.definition_version='9.0.0'", "registration.definition_version='10.0.0'"),
        ("prior_registration.definition_version IN ('7.0.0','8.0.0','9.0.0')", "prior_registration.definition_version='10.0.0'"),
        ("IN ('planning-isolated-preparation-handoff.v1','planning-unsent-preparation-query-handoff.v1','planning-unsent-preparation-lineage-handoff.v1')", "='planning-prepared-main-handoff.v1'"),
        ("r.target_runtime#>>'{preparation_handoff,contract_version}'='planning-unsent-preparation-query-handoff.v1'", "r.target_runtime#>>'{preparation_handoff,contract_version}'='planning-prepared-main-handoff.v1'"),
        ("r.target_runtime#>'{preparation_handoff,main_dispatch_count}'='0'::jsonb", "r.target_runtime#>'{preparation_handoff,main_dispatch_count}'='1'::jsonb"),
        ("IN ('context_compress','context_fidelity')", "IN ('context_compress','context_fidelity',prior.generator_operation_name)"),
    ):
        assert before in statement
        statement = statement.replace(before, after)
    if kind == 'lineage':
        for before, after in (
            ("attempt.status='FAILED_FINAL' AND attempt.result->>'error_code'='PROGRAMMING_BUG'", "attempt.status='FAILED_RETRYABLE' AND attempt.result->>'error_code'='PLANNING_ROUTING_LINEAGE_DEPTH_EXCEEDED'"),
            ("attempt.result->>'error_message'='canceling statement due to statement timeout'", "attempt.result->>'error_message'='PLANNING_ROUTING_LINEAGE_DEPTH_EXCEEDED: Planning repair routing lineage exceeds its bounded depth'"),
            ("attempt.result->>'failure_class'='programming_bug'", "attempt.result->>'failure_class'='retryable'"),
            ('unsent_query_failure', 'unsent_lineage_failure'),
            ('RELEASED_BY_UNSENT_QUERY_FAILURE', 'RELEASED_BY_UNSENT_LINEAGE_FAILURE'),
        ):
            assert before in statement
            statement = statement.replace(before, after)
    HOST_PERMITTED.append(statement)
    GUARD_STATEMENT = GUARD_STATEMENT.replace(_ANCHOR, _ANCHOR + '\n               AND NOT authority_prepared_main_' + kind + '_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))')
UPGRADE_STATEMENTS = [PERMITTED, *HOST_PERMITTED, GUARD_STATEMENT]
DOWNGRADE_STATEMENTS: list[str] = []

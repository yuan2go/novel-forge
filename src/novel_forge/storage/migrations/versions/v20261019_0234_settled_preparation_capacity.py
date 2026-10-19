from __future__ import annotations

from .v20261019_0233_acknowledged_preparation_routing import PERMITTED as PREVIOUS_PERMITTED, GUARD_STATEMENT as PREVIOUS_GUARD

MIGRATION_ID = '20261019_0234_settled_preparation_capacity'
DOWN_REVISION = '20261019_0233_acknowledged_preparation_routing'
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = 'Append same-capacity v13 succession after settled preparation and an unsent full-source capacity refusal; preserve prior guards, UNKNOWN and terminal history.'

CAPACITY_STOPPED = """CREATE FUNCTION authority_settled_capacity_preparation_stopped(identity TEXT, actor TEXT)
RETURNS BOOLEAN LANGUAGE SQL STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM authority_operation op
 JOIN LATERAL (SELECT result FROM authority_attempt WHERE operation_id=identity ORDER BY attempt_number DESC LIMIT 1) latest ON TRUE
 WHERE op.operation_id=identity AND op.actor_id=actor AND op.definition_name='story_planning.generate'
 AND op.definition_version='1.21.0' AND op.status IN ('FAILED_RETRYABLE','FAILED_FINAL')
 AND latest.result->>'error_code'='TASK_CONTEXT_COMPRESSION_NO_PROGRESS'
 AND latest.result->>'error_message'='TASK_CONTEXT_COMPRESSION_NO_PROGRESS: All remaining source expression is required or already verified; the complete request still exceeds capacity'
 AND latest.result->>'failure_class'='retryable'
 AND latest.result#>>'{failure_details,projection,contract_version}'='complete-request-capacity.v1'
 AND latest.result#>>'{failure_details,projection,semantic_contract}'='source-unit-dependency-and-final-composition.v2'
 AND latest.result#>>'{failure_details,projection,original_hash}' IS NOT NULL
 AND latest.result#>'{failure_details,projection,original_hash}'=latest.result#>'{failure_details,projection,result_hash}'
 AND latest.result#>'{failure_details,projection,compression_receipt,fast_path}'='true'::jsonb
 AND latest.result#>'{failure_details,projection,measurement,actual_provider_tokens}'='null'::jsonb
 AND jsonb_path_exists(latest.result,'$.failure_details.projection.measurement ? (@.limit.type() == "number" && @.before_reserved.type() == "number" && @.after_reserved.type() == "number" && @.limit > 0 && @.before_reserved > @.limit && @.after_reserved > @.limit)')
 AND NOT EXISTS(SELECT 1 FROM authority_attempt WHERE operation_id=identity AND status NOT IN ('FAILED_RETRYABLE','FAILED_FINAL'))
 AND NOT EXISTS(SELECT 1 FROM authority_lease_acquisition l JOIN authority_attempt a USING(attempt_id) WHERE a.operation_id=identity AND l.status='HELD')
 AND NOT EXISTS(SELECT 1 FROM authority_worker_cancel_signal WHERE operation_id=identity AND acknowledged_at IS NULL)
 AND NOT EXISTS(SELECT 1 FROM authority_cancellation_command WHERE operation_id=identity)
 AND EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=identity)
 AND NOT EXISTS(SELECT 1 FROM authority_external_effect e LEFT JOIN authority_budget_reservation b USING(external_effect_id)
   WHERE e.operation_id=identity AND NOT COALESCE(e.project_id=op.project_id AND e.effect_type='model.invoke'
    AND e.request_payload->>'stage' IN ('context_compress','context_fidelity') AND e.status='SUCCEEDED'
    AND b.status='SETTLED' AND b.project_id=e.project_id AND b.operation_id=e.operation_id
    AND EXISTS(SELECT 1 FROM authority_external_effect_dispatch d JOIN authority_external_receipt receipt USING(dispatch_id)
      WHERE d.external_effect_id=e.external_effect_id AND d.status='SUCCEEDED' AND receipt.status='VERIFIED'),false)))
$$"""
MEMBER_STOPPED = """CREATE FUNCTION authority_first_preparation_member_v13_stopped(identity TEXT, actor TEXT)
RETURNS BOOLEAN LANGUAGE SQL STABLE AS $$
 SELECT authority_first_preparation_member_v12_stopped(identity,actor)
 OR authority_settled_capacity_preparation_stopped(identity,actor)
$$"""
PERMITTED = PREVIOUS_PERMITTED
for before, after in (
    ('authority_first_isolated_preparation_v12_permitted', 'authority_first_isolated_preparation_v13_permitted'),
    ('authority_first_preparation_member_v12_stopped', 'authority_first_preparation_member_v13_stopped'),
    ("registration.definition_version='12.0.0'", "registration.definition_version='13.0.0'"),
    ('planning-first-isolated-preparation-handoff.v2', 'planning-first-isolated-preparation-handoff.v3'),
):
    assert before in PERMITTED
    PERMITTED = PERMITTED.replace(before, after)
_ANCHOR = "AND source.definition_name='story_planning.generate'"
assert PERMITTED.count(_ANCHOR) == 1
PERMITTED = PERMITTED.replace(_ANCHOR, """AND source.status<>'FAILED_RETRYABLE'
 AND EXISTS(SELECT 1 FROM jsonb_array_elements(r.target_runtime#>'{preparation_handoff,stopped_ancestry}') member
   WHERE member->>'kind'='UNSENT_CAPACITY_FAILURE')
 AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(r.target_runtime#>'{preparation_handoff,stopped_ancestry}') member
  LEFT JOIN authority_operation op ON op.operation_id=member->>'operation_id'
  LEFT JOIN LATERAL (SELECT result FROM authority_attempt WHERE operation_id=op.operation_id ORDER BY attempt_number DESC LIMIT 1) a ON TRUE
  WHERE member->>'kind'='UNSENT_CAPACITY_FAILURE' AND NOT COALESCE(
   authority_settled_capacity_preparation_stopped(op.operation_id,source.actor_id)
   AND a.result#>'{failure_details,projection,source_boundary}'=r.target_runtime#>'{preparation_handoff,preparation_source_boundary}'
   AND a.result#>>'{failure_details,projection,original_hash}'=r.target_runtime#>>'{preparation_handoff,preparation_source_projection_hash}'
   AND a.result#>>'{failure_details,projection,stage}'=prior.generator_operation_name,false))
 """ + _ANCHOR)
_ANCHOR = 'AND NOT authority_first_isolated_preparation_v12_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))'
assert PREVIOUS_GUARD.count(_ANCHOR) == 1
GUARD_STATEMENT = PREVIOUS_GUARD.replace(_ANCHOR, _ANCHOR + '\n               AND NOT authority_first_isolated_preparation_v13_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))')
UPGRADE_STATEMENTS = [CAPACITY_STOPPED, MEMBER_STOPPED, PERMITTED, GUARD_STATEMENT]
DOWNGRADE_STATEMENTS: list[str] = []

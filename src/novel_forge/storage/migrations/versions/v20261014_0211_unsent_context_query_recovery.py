from __future__ import annotations

from .v20261009_0191_provider_schema_successor import UPGRADE_STATEMENTS as PRIOR_STATEMENTS

MIGRATION_ID = "20261014_0211_unsent_context_query_recovery"
DOWN_REVISION = "20261014_0210_operation_outbox_lookup_indexes"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Permit only operator-diagnosed zero-send historical Context query failures through their exact native continuation."

UPGRADE_STATEMENTS = [
    """CREATE FUNCTION authority_unsent_query_continuation_permitted(runtime_id TEXT, child_id TEXT, generation JSONB)
    RETURNS BOOLEAN LANGUAGE SQL STABLE AS $$
    SELECT EXISTS(SELECT 1 FROM authority_story_planning_runtime_continuation r
      JOIN authority_operation registered ON registered.operation_id=r.registered_by_operation_id
      JOIN authority_operation source ON source.operation_id=r.source_operation_id
      JOIN authority_operation child ON child.operation_id=child_id
      JOIN authority_story_planning_generation prior ON prior.operation_id=source.operation_id
      JOIN authority_attempt attempt ON attempt.operation_id=source.operation_id
        AND attempt.attempt_number=(SELECT max(attempt_number) FROM authority_attempt WHERE operation_id=source.operation_id)
      JOIN authority_attempt_capability_pack_snapshot pack ON pack.operation_id=source.operation_id AND pack.attempt_id=attempt.attempt_id
      JOIN authority_story_formation_run formation ON formation.formation_run_id=r.decision_evidence->>'formation_run_id'
      JOIN authority_story_planning_runtime_continuation reference ON reference.continuation_id=r.decision_evidence #>> '{original_stage_runtime,continuation_id}'
      JOIN authority_operation reference_operation ON reference_operation.operation_id=reference.successor_operation_id
      JOIN authority_story_planning_generation reference_generation ON reference_generation.operation_id=reference_operation.operation_id
      WHERE r.continuation_id=runtime_id AND r.successor_operation_id=child_id
      AND source.status='FAILED_FINAL' AND source.definition_name='story_planning.generate'
      AND registered.status='SUCCEEDED' AND registered.definition_name='story_planning.runtime_continuation.register'
      AND attempt.status='FAILED_FINAL' AND attempt.result->>'error_code'='PROGRAMMING_BUG'
      AND attempt.result->>'failure_class'='programming_bug'
      AND attempt.result->>'error_message'='canceling statement due to statement timeout'
      AND r.decision_evidence->>'recovery_kind'='planning-unsent-context-query-recovery.v1'
      AND r.decision_evidence #> '{database_failure,source_failure}'=attempt.result
      AND r.decision_evidence #>> '{database_failure,source_operation_id}'=source.operation_id
      AND r.decision_evidence #>> '{database_failure,source_attempt_id}'=attempt.attempt_id
      AND r.decision_evidence #>> '{database_failure,project_id}'=r.project_id
      AND r.decision_evidence #>> '{database_failure,workspace_id}'=r.workspace_id
      AND r.decision_evidence #>> '{database_failure,book_id}'=r.book_id
      AND r.decision_evidence #>> '{database_failure,pack_snapshot_id}'=pack.snapshot_id
      AND r.decision_evidence #>> '{database_failure,pack_snapshot_hash}'=pack.snapshot_hash
      AND r.decision_evidence #>> '{unsent_context_query_diagnostic,contract_version}'='planning-unsent-context-query-recovery.v1'
      AND r.decision_evidence #>> '{unsent_context_query_diagnostic,source_operation_id}'=source.operation_id
      AND r.decision_evidence #>> '{unsent_context_query_diagnostic,source_attempt_id}'=attempt.attempt_id
      AND r.decision_evidence #>> '{unsent_context_query_diagnostic,query_owner}'='mkaos_authority.list_planning_usage'
      AND r.decision_evidence #>> '{unsent_context_query_diagnostic,revalidation_status}'='PASS_NO_PROVIDER_NO_OUTPUT'
      AND reference_operation.status='SUCCEEDED' AND reference_operation.actor_id=source.actor_id
      AND reference.project_id=r.project_id AND reference.workspace_id=r.workspace_id AND reference.book_id=r.book_id
      AND reference_generation.generator_operation_name=prior.generator_operation_name
      AND reference_generation.logical_key=prior.logical_key
      AND source.command_payload #>> '{payload,opening_execution_binding,opening_run_id}' IS NOT NULL
      AND source.command_payload #>> '{payload,opening_execution_binding,opening_run_id}'=
          reference_operation.command_payload #>> '{payload,opening_execution_binding,opening_run_id}'
      AND r.decision_evidence #>> '{original_stage_runtime,operation_id}'=reference_operation.operation_id
      AND NOT EXISTS(SELECT 1 FROM (VALUES ('model_provider'),('model_id'),('reasoning_effort'),('runtime_class'),('model_backend_id'),('cost_accounting_basis')) identity(key)
        WHERE r.target_runtime->identity.key IS DISTINCT FROM reference.target_runtime->identity.key)
      AND (r.target_runtime->'account' #- '{entitlement,authorization_ref}')=
          (reference.target_runtime->'account' #- '{entitlement,authorization_ref}')
      AND EXISTS(SELECT 1 FROM authority_external_effect e WHERE e.operation_id=reference_operation.operation_id
        AND e.status='SUCCEEDED' AND e.request_payload->>'stage'=prior.generator_operation_name)
      AND NOT EXISTS(SELECT 1 FROM (VALUES ('prompt_bundle_hash'),('route_policy_hash'),('context_policy_hash'),('skill_bundle_hash'),('tool_policy_hash')) identity(key)
        WHERE pack.snapshot_payload->identity.key IS DISTINCT FROM r.target_runtime->'pack_snapshot'->identity.key)
      AND formation.project_id=r.project_id AND formation.workspace_id=r.workspace_id AND formation.book_id=r.book_id
      AND formation.frozen_stage_inputs #>> '{generation_policy,auto_authorization,authorized_by_principal_id}'=registered.actor_id
      AND NOT EXISTS(SELECT 1 FROM authority_story_creation_cancellation WHERE formation_run_id=formation.formation_run_id)
      AND r.source_command=source.command_payload->'payload' AND r.successor_command=child.command_payload->'payload'
      AND (r.successor_command-'runtime_continuation_id'-'idempotency_key')=(r.source_command-'runtime_continuation_id'-'idempotency_key')
      AND child.causation_operation_id=source.operation_id AND child.actor_id=source.actor_id
      AND child.project_id=r.project_id AND child.workspace_id=r.workspace_id
      AND source.project_id=r.project_id AND source.workspace_id=r.workspace_id
      AND prior.project_id=r.project_id AND prior.workspace_id=r.workspace_id AND prior.book_id=r.book_id
      AND generation->>'project_id'=r.project_id AND generation->>'workspace_id'=r.workspace_id AND generation->>'book_id'=r.book_id
      AND generation->>'generator_operation_name'=prior.generator_operation_name
      AND generation->>'logical_key'=prior.logical_key AND generation->>'planning_scope'=prior.planning_scope
      AND generation->'input_snapshot'=prior.input_snapshot AND generation->>'input_snapshot_hash'=prior.input_snapshot_hash
      AND generation->>'repair_number'=prior.repair_number::text
      AND generation->>'repair_of_operation_id' IS NOT DISTINCT FROM prior.repair_of_operation_id
      AND generation->>'repair_result_asset_version_id' IS NOT DISTINCT FROM prior.repair_result_asset_version_id
      AND generation->>'narrative_search_id' IS NOT DISTINCT FROM prior.narrative_search_id
      AND generation->>'narrative_search_branch_key' IS NOT DISTINCT FROM prior.narrative_search_branch_key
      AND generation->>'candidate_asset_version_id' IS NULL AND prior.candidate_asset_version_id IS NULL
      AND NOT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=source.operation_id)
      AND NOT EXISTS(SELECT 1 FROM authority_budget_reservation WHERE operation_id=source.operation_id)
      AND NOT EXISTS(SELECT 1 FROM authority_operation_output_asset WHERE operation_id=source.operation_id)
      AND NOT EXISTS(SELECT 1 FROM authority_lease_acquisition l JOIN authority_attempt a USING(attempt_id) WHERE a.operation_id=source.operation_id AND l.status='HELD')
      AND NOT EXISTS(SELECT 1 FROM authority_attempt WHERE operation_id=source.operation_id AND status IN ('LEASED','RUNNING','CHECKPOINTED','RESULT_SUBMITTED'))
      AND NOT EXISTS(SELECT 1 FROM authority_worker_cancel_signal WHERE operation_id=source.operation_id AND acknowledged_at IS NULL)
      AND NOT EXISTS(SELECT 1 FROM authority_book_production WHERE project_id=r.project_id AND book_id=r.book_id AND state IN ('ABORTED','CANCELLED','COMPLETED'))
    ) $$""",
    PRIOR_STATEMENTS[1].replace(
        'AND NOT authority_schema_continuation_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))',
        'AND NOT authority_schema_continuation_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))\n               AND NOT authority_unsent_query_continuation_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))',
    ),
]
DOWNGRADE_STATEMENTS: list[str] = []

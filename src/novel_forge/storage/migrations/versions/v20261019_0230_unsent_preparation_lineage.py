from __future__ import annotations

from .v20261019_0229_routing_observation_preparation_recovery import PERMITTED as QUERY_PERMITTED, GUARD_STATEMENT as PREVIOUS_GUARD

MIGRATION_ID = '20261019_0230_unsent_preparation_lineage'
DOWN_REVISION = '20261019_0229_routing_observation_preparation_recovery'
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = 'Append exact zero-send lineage-failure preparation custody while preserving original content-repair numbers, failures, inputs and unknown usage.'

PERMITTED = QUERY_PERMITTED
for before, after in (
    ('authority_unsent_preparation_query_permitted', 'authority_unsent_preparation_lineage_permitted'),
    ("registration.definition_version='8.0.0'", "registration.definition_version='9.0.0'"),
    ("attempt.status='FAILED_FINAL' AND attempt.result->>'error_code'='PROGRAMMING_BUG'", "attempt.status='FAILED_RETRYABLE' AND attempt.result->>'error_code'='PLANNING_ROUTING_LINEAGE_DEPTH_EXCEEDED'"),
    ("attempt.result->>'error_message'='canceling statement due to statement timeout'", "attempt.result->>'error_message'='PLANNING_ROUTING_LINEAGE_DEPTH_EXCEEDED: Planning repair routing lineage exceeds its bounded depth'"),
    ("attempt.result->>'failure_class'='programming_bug'", "attempt.result->>'failure_class'='retryable'"),
    ('unsent_query_failure', 'unsent_lineage_failure'),
    ('planning-unsent-preparation-query-handoff.v1', 'planning-unsent-preparation-lineage-handoff.v1'),
    ('RELEASED_BY_UNSENT_QUERY_FAILURE', 'RELEASED_BY_UNSENT_LINEAGE_FAILURE'),
    ("prior_registration.definition_version IN ('7.0.0','8.0.0')", "prior_registration.definition_version IN ('7.0.0','8.0.0','9.0.0')"),
    ("IN ('planning-isolated-preparation-handoff.v1','planning-unsent-preparation-lineage-handoff.v1')", "IN ('planning-isolated-preparation-handoff.v1','planning-unsent-preparation-query-handoff.v1','planning-unsent-preparation-lineage-handoff.v1')"),
):
    assert before in PERMITTED
    PERMITTED = PERMITTED.replace(before, after)

_ANCHOR = 'AND NOT authority_unsent_preparation_query_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))'
assert PREVIOUS_GUARD.count(_ANCHOR) == 1
GUARD_STATEMENT = PREVIOUS_GUARD.replace(_ANCHOR, _ANCHOR + '\n               AND NOT authority_unsent_preparation_lineage_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))')
QUERY_V9_PERMITTED = QUERY_PERMITTED
for before, after in (
    ('authority_unsent_preparation_query_permitted', 'authority_unsent_preparation_query_v9_permitted'),
    ("registration.definition_version='8.0.0'", "registration.definition_version='9.0.0'"),
    ("prior_registration.definition_version IN ('7.0.0','8.0.0')", "prior_registration.definition_version IN ('7.0.0','8.0.0','9.0.0')"),
    ("IN ('planning-isolated-preparation-handoff.v1','planning-unsent-preparation-query-handoff.v1')", "IN ('planning-isolated-preparation-handoff.v1','planning-unsent-preparation-query-handoff.v1','planning-unsent-preparation-lineage-handoff.v1')"),
):
    assert before in QUERY_V9_PERMITTED
    QUERY_V9_PERMITTED = QUERY_V9_PERMITTED.replace(before, after)
GUARD_STATEMENT = GUARD_STATEMENT.replace(_ANCHOR, _ANCHOR + '\n               AND NOT authority_unsent_preparation_query_v9_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))')
_LOCAL_OUTPUTS = """
 AND (SELECT count(*) FROM authority_operation_output_asset WHERE operation_id=source.operation_id AND output_key='planning.context_bundle')<=1
 AND jsonb_array_length(COALESCE(r.target_runtime#>'{preparation_handoff,retained_local_preparation}','[]'::jsonb))=
   (SELECT count(*) FROM authority_operation_output_asset WHERE operation_id=source.operation_id AND output_key<>'planning.context_bundle')
 AND NOT EXISTS(SELECT 1 FROM authority_operation_output_asset output
   LEFT JOIN authority_asset_version local_version ON local_version.asset_version_id=output.asset_version_id
   LEFT JOIN authority_asset local_asset ON local_asset.asset_id=local_version.asset_id
   WHERE output.operation_id=source.operation_id AND NOT COALESCE(
    (output.output_key='planning.context_bundle' AND output.role='context_bundle' AND output.content_hash=context.content_hash)
    OR (output.role='execution_contract' AND output.output_key LIKE 'production_execution.contract.capability_materialization_manifest.%'
     AND local_asset.project_id=r.project_id AND local_asset.asset_type='capability_materialization_manifest'
     AND output.content_hash=local_version.content_hash
     AND local_version.content#>>'{contract,schema_version}'='novelos.planning_capability_materialization.v1'
     AND local_version.content#>>'{contract,stage}' IN ('context_compress','context_fidelity')
     AND local_version.content#>>'{contract,attempt_snapshot,operation_id}'=source.operation_id
     AND local_version.content#>>'{contract,attempt_snapshot,attempt_id}'=attempt.attempt_id
     AND local_version.content#>>'{contract,attempt_snapshot,snapshot_id}'=snapshot.snapshot_id
     AND local_version.content#>>'{contract,attempt_snapshot,snapshot_hash}'=snapshot.snapshot_hash
     AND local_version.content#>'{contract,pack_identity}'=jsonb_build_object(
       'pack_id',snapshot.snapshot_payload->'pack_id','pack_version',snapshot.snapshot_payload->'pack_version',
       'manifest_hash',snapshot.snapshot_payload->'manifest_hash','compilation_hash',snapshot.snapshot_payload->'compilation_hash',
       'catalog_snapshot_hash',snapshot.snapshot_payload->'catalog_snapshot_hash','binding_set_id',snapshot.snapshot_payload->'binding_set_id',
       'binding_set_hash',snapshot.snapshot_payload->'binding_set_hash')
     AND COALESCE(r.target_runtime#>'{preparation_handoff,retained_local_preparation}','[]'::jsonb) @> jsonb_build_array(jsonb_build_object(
       'asset_version_id',output.asset_version_id,'content_hash',output.content_hash,'output_key',output.output_key,'role',output.role,
       'asset_type',local_asset.asset_type,'stage',local_version.content#>>'{contract,stage}'))),false))
"""
_STRICT_OUTPUTS = """ AND (SELECT count(*) FROM authority_operation_output_asset WHERE operation_id=source.operation_id)<=1
 AND NOT EXISTS(SELECT 1 FROM authority_operation_output_asset WHERE operation_id=source.operation_id
   AND (output_key IS DISTINCT FROM 'planning.context_bundle' OR role IS DISTINCT FROM 'context_bundle' OR content_hash IS DISTINCT FROM context.content_hash))"""
assert _STRICT_OUTPUTS in PERMITTED and _STRICT_OUTPUTS in QUERY_V9_PERMITTED
PERMITTED = PERMITTED.replace(_STRICT_OUTPUTS,_LOCAL_OUTPUTS).replace("-'source_submission_rights')", "-'source_submission_rights'-'retained_local_preparation')")
QUERY_V9_PERMITTED = QUERY_V9_PERMITTED.replace(_STRICT_OUTPUTS,_LOCAL_OUTPUTS).replace("-'source_submission_rights')", "-'source_submission_rights'-'retained_local_preparation')")
UPGRADE_STATEMENTS = [PERMITTED, QUERY_V9_PERMITTED, GUARD_STATEMENT]
DOWNGRADE_STATEMENTS: list[str] = []

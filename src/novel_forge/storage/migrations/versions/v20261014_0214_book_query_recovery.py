from __future__ import annotations

from .v20261014_0211_unsent_context_query_recovery import UPGRADE_STATEMENTS as PREVIOUS

MIGRATION_ID = "20261014_0214_book_query_recovery"
DOWN_REVISION = "20261014_0213_group_scope_identity"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Retain the original failed first Chapter planning and authorize only its exact current Book and active parent Group reference."

_NAME = 'authority_book_unsent_query_continuation_permitted'
_SQL = PREVIOUS[0]
_REPLACEMENTS = {
    'CREATE FUNCTION authority_unsent_query_continuation_permitted': f'CREATE FUNCTION {_NAME}',
    'AND reference_generation.generator_operation_name=prior.generator_operation_name\n      AND reference_generation.logical_key=prior.logical_key': """AND prior.generator_operation_name='chapter_plan.generate' AND prior.logical_key='chapter:1'
      AND prior.repair_number=0 AND prior.repair_of_operation_id IS NULL
      AND source.command_payload #>> '{payload,execution_contract_version}'='1.21.0'
      AND reference_generation.generator_operation_name='chapter_group_plan.generate' AND reference_generation.status='ACTIVE'
      AND reference_generation.candidate_asset_version_id=source.command_payload #>> '{payload,input_versions,chapter_group_plan}'""",
    "AND source.command_payload #>> '{payload,opening_execution_binding,opening_run_id}' IS NOT NULL\n      AND source.command_payload #>> '{payload,opening_execution_binding,opening_run_id}'=\n          reference_operation.command_payload #>> '{payload,opening_execution_binding,opening_run_id}'": """AND source.command_payload #>> '{payload,opening_execution_binding,opening_run_id}' IS NULL
      AND r.decision_evidence #>> '{original_stage_runtime,reference_kind}'='BOOK_SUPERVISOR_FIRST_CHAPTER_PLAN'
      AND r.decision_evidence #>> '{original_stage_runtime,evidence_boundary}'='SAME_BOOK_ACTIVE_PARENT_GROUP_REFERENCE_NOT_SOURCE_PROVIDER_INPUT'
      AND source.command_payload #>> '{payload,world_preparation_request,accepted_through_chapter}'='0'
      AND EXISTS(SELECT 1 FROM authority_book_production book
        JOIN authority_book_production_input_binding input ON input.book_run_id=book.book_run_id
          AND input.project_id=book.project_id AND input.book_id=book.book_id
        JOIN authority_book_production_input_snapshot snapshot ON snapshot.snapshot_id=input.snapshot_id
          AND snapshot.project_id=book.project_id AND snapshot.workspace_id=book.workspace_id AND snapshot.book_id=book.book_id
        JOIN active_story_plan_version active ON active.project_id=book.project_id AND active.book_id=book.book_id
        JOIN story_plan_binding parent ON parent.binding_id=active.binding_id AND parent.asset_version_id=active.asset_version_id
          AND parent.project_id=book.project_id AND parent.book_id=book.book_id AND parent.contract_type='CHAPTER_GROUP' AND parent.freshness='CURRENT'
        JOIN authority_asset_version version ON version.asset_version_id=parent.asset_version_id
        WHERE book.book_run_id=source.command_payload #>> '{payload,world_preparation_request,book_run_id}'
          AND book.project_id=r.project_id AND book.workspace_id=r.workspace_id AND book.book_id=r.book_id
          AND book.stable_idempotency_key=formation.formation_run_id || ':production'
          AND book.input_mode='RESOLVED_AUTHORITY_INPUT' AND book.state='CHAPTER_PLAN_REQUIRED'
          AND book.current_chapter=0 AND book.accepted_through_chapter=0 AND book.active_chapter_request_id IS NULL
          AND COALESCE(book.active_story_state_version_id,'')=source.command_payload #>> '{payload,world_preparation_request,story_state_version_id}'
          AND COALESCE(book.active_canon_snapshot_version_id,'')=source.command_payload #>> '{payload,world_preparation_request,canon_version_id}'
          AND input.snapshot_id=source.command_payload #>> '{payload,world_preparation_request,input_snapshot_id}'
          AND NOT EXISTS(SELECT 1 FROM authority_book_production_input_binding newer WHERE newer.book_run_id=book.book_run_id AND newer.binding_version>input.binding_version)
          AND parent.asset_version_id=reference_generation.candidate_asset_version_id
          AND (version.content->'chapter_range'->>0)::integer<=1 AND (version.content->'chapter_range'->>1)::integer>=1
          AND NOT EXISTS(SELECT 1 FROM authority_book_chapter_acceptance WHERE book_run_id=book.book_run_id)
          AND r.decision_evidence #>> '{original_stage_runtime,book_scope,scope_version}'='book-supervisor-first-chapter-query-recovery.v1'
          AND r.decision_evidence #>> '{original_stage_runtime,book_scope,book_run_id}'=book.book_run_id
          AND r.decision_evidence #>> '{original_stage_runtime,book_scope,book_version_at_recovery}'=book.version::text
          AND r.decision_evidence #>> '{original_stage_runtime,book_scope,input_binding_id}'=input.binding_id
          AND r.decision_evidence #>> '{original_stage_runtime,book_scope,input_binding_version}'=input.binding_version::text
          AND r.decision_evidence #>> '{original_stage_runtime,book_scope,input_snapshot_id}'=snapshot.snapshot_id
          AND r.decision_evidence #>> '{original_stage_runtime,book_scope,input_snapshot_hash}'=snapshot.snapshot_hash
          AND r.decision_evidence #>> '{original_stage_runtime,book_scope,parent_binding_id}'=parent.binding_id
          AND r.decision_evidence #>> '{original_stage_runtime,book_scope,parent_binding_version}'=parent.version::text
          AND r.decision_evidence #>> '{original_stage_runtime,book_scope,parent_asset_version_id}'=version.asset_version_id
          AND r.decision_evidence #>> '{original_stage_runtime,book_scope,parent_content_hash}'=version.content_hash)
      AND pack.snapshot_payload->>'route_policy_hash'=reference.target_runtime #>> '{pack_snapshot,route_policy_hash}'""",
    "e.request_payload->>'stage'=prior.generator_operation_name": "e.request_payload->>'stage'=reference_generation.generator_operation_name",
}
for _old, _new in _REPLACEMENTS.items():
    assert _SQL.count(_old) == 1
    _SQL = _SQL.replace(_old, _new)

_GUARD = 'AND NOT authority_unsent_query_continuation_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))'
assert PREVIOUS[1].count(_GUARD) == 1
UPGRADE_STATEMENTS = [_SQL, PREVIOUS[1].replace(_GUARD,
    _GUARD + f'\n               AND NOT {_NAME}(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))')]
DOWNGRADE_STATEMENTS: list[str] = []

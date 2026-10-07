from __future__ import annotations

MIGRATION_ID = '20261007_0179_planning_arc_scope_revalidation'
DOWN_REVISION = '20261007_0178_planning_reference_contract_successor'
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "append scoped evidence without rewriting published history or permitting uncertain consumption"

UPGRADE_STATEMENTS = [
    r"""CREATE OR REPLACE FUNCTION authority_planning_host_continuation_permitted(runtime_id TEXT, child_id TEXT, generation JSONB)
RETURNS BOOLEAN LANGUAGE plpgsql AS $$
DECLARE mode TEXT; source_id TEXT; admitted BOOLEAN;
BEGIN
 SELECT command_payload #>> '{payload,repair_reason}' INTO mode FROM authority_operation WHERE operation_id=child_id;
 IF mode NOT IN ('PLANNING_REFERENCE_CONTRACT_SUCCESSOR','PLANNING_ARC_SCOPE_SUCCESSOR') OR mode IS NULL THEN RETURN FALSE; END IF;
 SELECT source_operation_id INTO source_id FROM authority_story_planning_runtime_continuation WHERE continuation_id=runtime_id;
 SELECT EXISTS (
 SELECT 1 FROM authority_story_planning_runtime_continuation r
 JOIN authority_story_planning_generation source ON source.operation_id=r.source_operation_id
 JOIN authority_operation original ON original.operation_id=source.operation_id
 JOIN authority_operation child ON child.operation_id=child_id
 JOIN authority_operation registration ON registration.operation_id=r.registered_by_operation_id
 JOIN authority_asset_version candidate ON candidate.asset_version_id=source.candidate_asset_version_id
 JOIN authority_story_design_version_state owner ON owner.asset_version_id=candidate.asset_version_id AND owner.project_id=source.project_id
 LEFT JOIN authority_book_production book ON book.project_id=source.project_id AND book.workspace_id=source.workspace_id AND book.book_id=source.book_id
 WHERE r.continuation_id=runtime_id AND r.successor_operation_id=child_id
 AND r.source_command=original.command_payload->'payload' AND r.successor_command=child.command_payload->'payload'
 AND r.project_id=source.project_id AND r.workspace_id=source.workspace_id AND r.book_id=source.book_id
 AND original.project_id=r.project_id AND original.workspace_id=r.workspace_id
 AND child.project_id=r.project_id AND child.workspace_id=r.workspace_id AND child.actor_id=original.actor_id
 AND registration.project_id=r.project_id AND registration.workspace_id=r.workspace_id AND registration.actor_id=original.actor_id
 AND registration.status='SUCCEEDED' AND registration.definition_name='story_planning.runtime_continuation.register' AND registration.definition_version='2.0.0'
 AND original.status='SUCCEEDED' AND source.status='REJECTED' AND owner.lifecycle='REJECTED'
 AND owner.qualification='FAILED' AND owner.approval IN ('NOT_REQUESTED','PENDING') AND owner.freshness='CURRENT'
 AND owner.created_by_operation_id=original.operation_id
 AND r.source_evidence_asset_version_id=candidate.asset_version_id
 AND child.definition_name='story_planning.generate' AND child.definition_version='1.21.0'
 AND child.command_payload #>> '{payload,execution_contract_version}'='1.21.0'
 AND original.command_payload #>> '{payload,execution_contract_version}'=original.definition_version
 AND child.causation_operation_id=original.operation_id AND child.command_payload #>> '{payload,runtime_continuation_id}'=runtime_id
 AND generation->>'project_id'=source.project_id AND generation->>'workspace_id'=source.workspace_id AND generation->>'book_id'=source.book_id
 AND generation->>'generator_operation_name'=source.generator_operation_name AND source.generator_operation_name='chapter_group_plan.generate'
 AND generation->>'planning_scope'=source.planning_scope AND source.planning_scope='CHAPTER_GROUP'
 AND generation->>'logical_key'=source.logical_key AND generation->>'input_snapshot_hash'=source.input_snapshot_hash
 AND generation->'input_snapshot'=source.input_snapshot AND (generation->>'repair_number')::int=source.repair_number AND source.repair_number BETWEEN 0 AND 4
 AND generation->>'runtime_continuation_id'=runtime_id AND generation->>'repair_reason'=mode
 AND generation->>'candidate_asset_version_id' IS NULL AND generation->>'repair_of_candidate_id' IS NULL
 AND generation->>'repair_of_operation_id' IS NULL AND generation->>'repair_result_asset_version_id' IS NULL
 AND (child.command_payload #>> '{payload,repair_number}')::int=source.repair_number
 AND child.command_payload #>> '{payload,generator_operation_name}'=source.generator_operation_name
 AND child.command_payload #>> '{payload,book_id}'=source.book_id AND child.command_payload #>> '{payload,logical_key}'=source.logical_key
 AND EXISTS(SELECT 1 FROM authority_attempt a WHERE a.operation_id=original.operation_id AND a.status='SUCCEEDED'
    AND a.attempt_number=(SELECT max(last.attempt_number) FROM authority_attempt last WHERE last.operation_id=original.operation_id))
 AND EXISTS(SELECT 1 FROM authority_story_planning_validation_report report WHERE report.generation_operation_id=original.operation_id
    AND report.candidate_asset_version_id=candidate.asset_version_id AND report.project_id=source.project_id AND report.status='FAIL'
    AND report.validation_report_id=(SELECT last.validation_report_id FROM authority_story_planning_validation_report last
        WHERE last.candidate_asset_version_id=candidate.asset_version_id ORDER BY last.created_at DESC,last.validation_report_id DESC LIMIT 1)
    AND report.report->>'error_code'=CASE WHEN mode='PLANNING_REFERENCE_CONTRACT_SUCCESSOR' THEN 'WORLD_REALIZATION_REFERENCE_INVALID' ELSE 'NARRATIVE_REALIZATION_ARC_SCOPE_INVALID' END
    AND report.report_hash=r.target_runtime #>> ARRAY[CASE WHEN mode='PLANNING_REFERENCE_CONTRACT_SUCCESSOR' THEN 'planning_reference_contract' ELSE 'planning_host_revalidation' END,'validation_report_hash'])
 AND candidate.content_hash=r.target_runtime #>> ARRAY[CASE WHEN mode='PLANNING_REFERENCE_CONTRACT_SUCCESSOR' THEN 'planning_reference_contract' ELSE 'planning_host_revalidation' END,'source_candidate_hash']
 AND (CASE WHEN book.book_run_id IS NULL THEN 'null'::jsonb ELSE jsonb_build_object('book_run_id',book.book_run_id,'accepted_through_chapter',book.accepted_through_chapter,'current_chapter',book.current_chapter,
      'book_plan_version',book.book_plan_version,'longform_context_versions',book.longform_context_versions,'active_chapter_request_id',book.active_chapter_request_id) END)
    =r.target_runtime #> ARRAY[CASE WHEN mode='PLANNING_REFERENCE_CONTRACT_SUCCESSOR' THEN 'planning_reference_contract' ELSE 'planning_host_revalidation' END,'source_book_frontier']
 AND (book.book_run_id IS NULL OR book.state NOT IN ('ABORTED','COMPLETED','CANCELLED'))
 AND NOT EXISTS(SELECT 1 FROM authority_story_creation_cancellation cancelled JOIN authority_story_formation_run formation USING(formation_run_id) WHERE cancelled.project_id=source.project_id AND formation.book_id=source.book_id)
 AND NOT EXISTS(SELECT 1 FROM authority_story_creation_cancellation cancelled WHERE cancelled.project_id=book.project_id AND book.stable_idempotency_key=cancelled.formation_run_id||':production')
 AND EXISTS(SELECT 1 FROM authority_external_effect receipt JOIN authority_budget_reservation budget ON budget.external_effect_id=receipt.external_effect_id
      WHERE receipt.operation_id=source.operation_id AND receipt.status='SUCCEEDED' AND budget.status='SETTLED'
        AND receipt.external_effect_id=r.target_runtime #>> ARRAY[CASE WHEN mode='PLANNING_REFERENCE_CONTRACT_SUCCESSOR' THEN 'planning_reference_contract' ELSE 'planning_host_revalidation' END,'source_external_effect_id'])
 AND ((mode='PLANNING_REFERENCE_CONTRACT_SUCCESSOR' AND original.definition_version='1.19.0' AND r.chain_depth=3
 AND r.decision_evidence->>'changed_contract'='planning-host-source-selectors.v2'
 AND r.target_runtime #>> '{planning_reference_contract,contract_version}'='planning-reference-contract-successor.v2'
 AND EXISTS(SELECT 1 FROM authority_story_planning_runtime_continuation prior WHERE prior.successor_operation_id=original.operation_id AND prior.chain_depth=2
     AND prior.target_runtime #> '{planning_capacity,context_revalidation}' IS NOT NULL)) OR (mode='PLANNING_ARC_SCOPE_SUCCESSOR' AND original.definition_version='1.20.0'
 AND original.definition_hash=r.target_runtime #>> '{planning_host_revalidation,source_definition_hash}'
 AND r.source_release_sha=r.target_runtime #>> '{planning_host_revalidation,source_release_sha}'
 AND r.target_runtime #>> '{planning_host_revalidation,historical_source_sha}'='c9c7fc1d9a6d8a2dde715890105990d02a37d657' AND r.chain_depth=4
 AND r.decision_evidence->>'planning_host_revalidation'='planning-arc-scope-revalidation.v2'
 AND r.decision_evidence->'provider_dispatch_authorized'='false'::jsonb
 AND r.target_runtime #>> '{planning_host_revalidation,contract_version}'='planning-arc-scope-revalidation.v2'
 AND EXISTS(SELECT 1 FROM authority_story_planning_runtime_continuation prior WHERE prior.successor_operation_id=original.operation_id AND prior.chain_depth=3
    AND prior.decision_evidence->>'changed_contract'='planning-host-source-selectors.v1'
    AND prior.target_runtime #>> '{planning_reference_contract,contract_version}'='planning-reference-contract-successor.v1')
 AND NOT EXISTS(SELECT 1 FROM authority_external_effect sent WHERE sent.operation_id=child_id)
 AND NOT EXISTS(SELECT 1 FROM authority_budget_reservation consumed WHERE consumed.operation_id=child_id)))
 ) INTO admitted;
 IF NOT admitted THEN RETURN FALSE; END IF;
 WITH RECURSIVE lineage(operation_id) AS (
 SELECT source_id UNION SELECT neighbor.operation_id FROM lineage
 JOIN authority_operation anchor ON anchor.operation_id=lineage.operation_id
 JOIN authority_operation neighbor ON neighbor.causation_operation_id=anchor.operation_id OR neighbor.operation_id=anchor.causation_operation_id
 WHERE neighbor.definition_name='story_planning.generate' AND neighbor.project_id=anchor.project_id)
 SELECT EXISTS(SELECT 1 FROM authority_external_effect effect JOIN lineage USING(operation_id) WHERE effect.status NOT IN ('SUCCEEDED','FAILED_FINAL','CANCELLED'))
 OR EXISTS(SELECT 1 FROM authority_budget_reservation budget JOIN lineage USING(operation_id) WHERE budget.status NOT IN ('SETTLED','RELEASED'))
        OR NOT authority_planning_cli_lineage_reconciled(source_id)
 OR EXISTS(SELECT 1 FROM authority_lease_acquisition lease JOIN authority_attempt a USING(attempt_id) JOIN lineage ON lineage.operation_id=a.operation_id
    WHERE lease.status='HELD' AND NOT(a.operation_id=child_id AND a.status='RUNNING' AND a.attempt_number=(SELECT max(active.attempt_number) FROM authority_attempt active WHERE active.operation_id=child_id)
       AND EXISTS(SELECT 1 FROM authority_operation child WHERE child.operation_id=child_id AND child.status='RUNNING')))
 INTO admitted;
 RETURN NOT admitted;
END; $$""",
    r"""ALTER TABLE authority_story_planning_runtime_continuation DROP CONSTRAINT authority_story_planning_runtime_continuation_chain_depth_check""",
    r"""ALTER TABLE authority_story_planning_runtime_continuation ADD CONSTRAINT authority_story_planning_runtime_continuation_chain_depth_check CHECK(chain_depth BETWEEN 1 AND 2 OR(chain_depth=3 AND(COALESCE(decision_evidence->>'projection_revalidation','')='world-direction-projection.v1' OR(decision_evidence->>'changed_contract'='planning-host-source-selectors.v2' AND target_runtime #>> '{planning_reference_contract,contract_version}'='planning-reference-contract-successor.v2'))) OR(chain_depth=4 AND decision_evidence->>'planning_host_revalidation'='planning-arc-scope-revalidation.v2' AND decision_evidence->'provider_dispatch_authorized'='false'::jsonb AND target_runtime #>> '{planning_host_revalidation,contract_version}'='planning-arc-scope-revalidation.v2'))""",
    r"""ALTER TABLE authority_story_planning_generation DROP CONSTRAINT authority_planning_repair_source_check""",
    r"""ALTER TABLE authority_story_planning_generation ADD CONSTRAINT authority_planning_repair_source_check CHECK (
            (repair_number=0 AND repair_of_candidate_id IS NULL AND repair_of_operation_id IS NULL AND repair_result_asset_version_id IS NULL AND repair_reason IS NULL)
            OR (repair_number>0 AND repair_reason IS NOT NULL AND ((repair_of_candidate_id IS NOT NULL AND repair_of_operation_id IS NULL AND repair_result_asset_version_id IS NULL)
                OR (repair_of_candidate_id IS NULL AND repair_of_operation_id IS NOT NULL AND repair_result_asset_version_id IS NOT NULL AND repair_number<=4)))
            OR (repair_number BETWEEN 0 AND 4 AND runtime_continuation_id IS NOT NULL
                AND repair_reason IN ('WORLD_AGENCY_CONTRACT_SUCCESSOR','WORLD_HOST_REVALIDATION_SUCCESSOR','WORLD_HOST_PROJECTION_SUCCESSOR','PLANNING_REFERENCE_CONTRACT_SUCCESSOR','PLANNING_ARC_SCOPE_SUCCESSOR') AND repair_of_candidate_id IS NULL AND repair_of_operation_id IS NULL AND repair_result_asset_version_id IS NULL))""",
]
DOWNGRADE_STATEMENTS: list[str] = []

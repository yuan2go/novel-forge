from __future__ import annotations

MIGRATION_ID = '20261009_0187_chapter_generation_isolation'
DOWN_REVISION = "20261009_0186_generation_capacity_inheritance"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Fence stopped pure Chapter generation through the existing Kernel step successor; count generation recovery separately from capacity decisions."

UPGRADE_STATEMENTS = [
    """CREATE OR REPLACE FUNCTION authority_generation_isolation_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
 BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'GENERATION_ISOLATION_IMMUTABLE'; END IF;
 IF NOT EXISTS(SELECT 1 FROM authority_external_effect e JOIN authority_operation o USING(operation_id)
 LEFT JOIN authority_story_planning_generation g ON g.operation_id=o.operation_id
 JOIN authority_asset_version v ON v.asset_version_id=NEW.materialization_asset_version_id
 JOIN authority_asset a ON a.asset_id=v.asset_id
 WHERE e.external_effect_id=NEW.external_effect_id AND e.operation_id=NEW.operation_id AND e.project_id=NEW.project_id
 AND o.workspace_id=NEW.workspace_id AND o.actor_id=NEW.proof->>'actor_id'
 AND o.status IN ('FAILED_FINAL','DEAD_LETTER')
 AND e.effect_type='model.invoke' AND e.status IN ('UNKNOWN','RECONCILIATION_REQUIRED') AND e.request_hash=NEW.request_hash
 AND ((o.definition_name='story_planning.generate' AND g.book_id=NEW.book_id AND g.workspace_id=NEW.workspace_id
 AND o.command_payload#>>'{payload,book_id}'=NEW.book_id
 AND o.command_payload#>>'{payload,workspace_id}'=NEW.workspace_id
 AND o.command_payload#>>'{payload,project_id}'=NEW.project_id
 AND NEW.proof->>'continuation_id'='planning-runtime-continuation:'||o.operation_id) OR (
 o.definition_name IN ('chapter.memo.generate','chapter.draft.generate','chapter.review.evaluate','chapter.revision.apply','chapter.canon.extract')
 AND o.command_payload->>'book_id'=NEW.book_id
 AND NEW.proof->>'continuation_id'='chapter-generation-successor:'||o.operation_id
 AND EXISTS(SELECT 1 FROM authority_saga_step step
 JOIN authority_book_chapter_request request ON request.chapter_root_operation_id=o.root_operation_id
 JOIN authority_book_production book USING(book_run_id)
 JOIN authority_operation root ON root.operation_id=request.chapter_root_operation_id
 WHERE step.operation_id=o.operation_id AND step.saga_id=o.saga_id
 AND book.project_id=NEW.project_id AND book.workspace_id=NEW.workspace_id AND book.book_id=NEW.book_id
 AND book.active_chapter_request_id=request.chapter_request_id
 AND root.actor_id=o.actor_id AND root.status='WAITING_CHILDREN' AND root.definition_name='chapter.slice.run')))
 AND e.request_payload#>>'{_production_execution,book_id}'=NEW.book_id AND a.project_id=NEW.project_id
 AND e.request_payload#>>'{_production_execution,capability_runtime,materialization_asset_version_id}'=v.asset_version_id
 AND e.request_payload#>>'{_production_execution,capability_runtime,materialization_content_hash}'=v.content_hash
 AND v.content#>>'{contract,tool_permissions,default}'='DENY'
 AND v.content#>'{contract,tool_permissions,allowed}'='["model.provider.invoke"]'::jsonb
 AND NEW.proof->>'contract_version'='pure-generation-isolation.v1'
 AND NEW.proof->>'remote_outcome'='UNKNOWN' AND NEW.proof->>'usage'='UNKNOWN'
 AND NEW.proof->>'business_commit_right'='REVOKED' AND NEW.proof->>'activation_right'='REVOKED'
 AND NOT EXISTS(SELECT 1 FROM authority_lease_acquisition l JOIN authority_attempt attempt USING(attempt_id)
 WHERE attempt.operation_id=o.operation_id AND l.status='HELD')
 AND NOT EXISTS(SELECT 1 FROM authority_operation_output_asset output WHERE output.operation_id=o.operation_id AND output.role='primary'))
 THEN RAISE EXCEPTION 'GENERATION_ISOLATION_SCOPE_UNSAFE'; END IF;
 RETURN NEW; END $$""",
    """ALTER TABLE authority_story_planning_runtime_continuation DROP CONSTRAINT authority_story_planning_runtime_continuation_chain_depth_check""",
    """ALTER TABLE authority_story_planning_runtime_continuation ADD CONSTRAINT authority_story_planning_runtime_continuation_chain_depth_check CHECK (
 chain_depth BETWEEN 1 AND 2 OR
 (chain_depth=3 AND decision_evidence->>'projection_revalidation'='world-direction-projection.v1') OR
 (chain_depth=3 AND decision_evidence->>'changed_contract'='planning-host-source-selectors.v2' AND target_runtime#>>'{planning_reference_contract,contract_version}'='planning-reference-contract-successor.v2') OR
 (chain_depth=4 AND decision_evidence->>'planning_host_revalidation'='planning-arc-scope-revalidation.v2' AND decision_evidence->'provider_dispatch_authorized'='false'::jsonb AND target_runtime#>>'{planning_host_revalidation,contract_version}'='planning-arc-scope-revalidation.v2') OR
 (chain_depth=3 AND decision_evidence->>'capacity_inheritance'='generation-capacity-inheritance.v1' AND target_runtime#>>'{generation_isolation,contract_version}'='pure-generation-isolation.v1') OR
 (chain_depth BETWEEN 3 AND 6 AND decision_evidence->>'recovery_kind'='ISOLATED_PURE_GENERATION' AND (decision_evidence->>'recovery_attempt_number')::int BETWEEN 1 AND 2 AND target_runtime#>>'{generation_isolation,contract_version}'='pure-generation-isolation.v1'))"""
]

DOWNGRADE_STATEMENTS: list[str] = []

from __future__ import annotations

MIGRATION_ID = "20261009_0185_pure_generation_isolation"
DOWN_REVISION = "20261009_0184_cli_original_reconciliation"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Fence unrecoverable pure generation without changing remote facts; bind exact native Planning continuations."

UPGRADE_STATEMENTS = [
    """CREATE TABLE authority_generation_isolation (
 isolation_id TEXT PRIMARY KEY, external_effect_id TEXT NOT NULL UNIQUE REFERENCES authority_external_effect,
 operation_id TEXT NOT NULL REFERENCES authority_operation, project_id TEXT NOT NULL,
 workspace_id TEXT NOT NULL, book_id TEXT NOT NULL, request_hash TEXT NOT NULL,
 materialization_asset_version_id TEXT NOT NULL REFERENCES authority_asset_version,
 proof JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""",
    """CREATE FUNCTION authority_generation_isolated(effect_id TEXT) RETURNS BOOLEAN LANGUAGE SQL STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM authority_generation_isolation i JOIN authority_external_effect e USING(external_effect_id)
 JOIN authority_operation o ON o.operation_id=i.operation_id
 WHERE i.external_effect_id=effect_id AND i.request_hash=e.request_hash AND i.project_id=e.project_id
 AND i.operation_id=e.operation_id AND o.project_id=i.project_id AND o.workspace_id=i.workspace_id
 AND o.status IN ('FAILED_FINAL','DEAD_LETTER') AND i.proof->>'contract_version'='pure-generation-isolation.v1') $$""",
    """CREATE FUNCTION authority_generation_isolation_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
 BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'GENERATION_ISOLATION_IMMUTABLE'; END IF;
 IF NOT EXISTS(SELECT 1 FROM authority_external_effect e JOIN authority_operation o USING(operation_id)
 JOIN authority_story_planning_generation g ON g.operation_id=o.operation_id
 JOIN authority_asset_version v ON v.asset_version_id=NEW.materialization_asset_version_id
 JOIN authority_asset a ON a.asset_id=v.asset_id
 WHERE e.external_effect_id=NEW.external_effect_id AND e.operation_id=NEW.operation_id AND e.project_id=NEW.project_id
 AND o.workspace_id=NEW.workspace_id AND o.actor_id=NEW.proof->>'actor_id'
 AND o.status IN ('FAILED_FINAL','DEAD_LETTER') AND o.definition_name='story_planning.generate'
 AND e.effect_type='model.invoke' AND e.status IN ('UNKNOWN','RECONCILIATION_REQUIRED') AND e.request_hash=NEW.request_hash
 AND g.book_id=NEW.book_id AND g.workspace_id=NEW.workspace_id
 AND o.command_payload#>>'{payload,book_id}'=NEW.book_id
 AND o.command_payload#>>'{payload,workspace_id}'=NEW.workspace_id
 AND o.command_payload#>>'{payload,project_id}'=NEW.project_id
 AND e.request_payload#>>'{_production_execution,book_id}'=NEW.book_id AND a.project_id=NEW.project_id
 AND e.request_payload#>>'{_production_execution,capability_runtime,materialization_asset_version_id}'=v.asset_version_id
 AND e.request_payload#>>'{_production_execution,capability_runtime,materialization_content_hash}'=v.content_hash
 AND v.content#>>'{contract,tool_permissions,default}'='DENY'
 AND v.content#>'{contract,tool_permissions,allowed}'='["model.provider.invoke"]'::jsonb
 AND NEW.proof->>'contract_version'='pure-generation-isolation.v1'
 AND NEW.proof->>'remote_outcome'='UNKNOWN' AND NEW.proof->>'usage'='UNKNOWN'
 AND NEW.proof->>'business_commit_right'='REVOKED' AND NEW.proof->>'activation_right'='REVOKED'
 AND NEW.proof->>'continuation_id'='planning-runtime-continuation:'||o.operation_id
 AND NOT EXISTS(SELECT 1 FROM authority_lease_acquisition l JOIN authority_attempt attempt USING(attempt_id)
 WHERE attempt.operation_id=o.operation_id AND l.status='HELD')
 AND NOT EXISTS(SELECT 1 FROM authority_operation_output_asset output WHERE output.operation_id=o.operation_id AND output.role='primary'))
 THEN RAISE EXCEPTION 'GENERATION_ISOLATION_SCOPE_UNSAFE'; END IF;
 RETURN NEW; END $$""",
    """CREATE TRIGGER authority_generation_isolation_guard BEFORE INSERT OR UPDATE OR DELETE ON authority_generation_isolation
 FOR EACH ROW EXECUTE FUNCTION authority_generation_isolation_guard()""",
    """CREATE FUNCTION authority_generation_commit_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
 BEGIN
 IF TG_TABLE_NAME='authority_external_effect' THEN
 IF NEW.status IS DISTINCT FROM OLD.status AND authority_generation_isolated(NEW.external_effect_id)
 THEN RAISE EXCEPTION 'GENERATION_ATTEMPT_ISOLATED'; END IF;
 ELSIF NEW.role='primary' AND EXISTS(SELECT 1 FROM authority_generation_isolation i WHERE i.operation_id=NEW.operation_id)
 THEN RAISE EXCEPTION 'GENERATION_ATTEMPT_ISOLATED'; END IF;
 RETURN NEW; END $$""",
    """CREATE TRIGGER authority_generation_effect_commit_guard BEFORE UPDATE ON authority_external_effect
 FOR EACH ROW EXECUTE FUNCTION authority_generation_commit_guard()""",
    """CREATE TRIGGER authority_generation_output_commit_guard BEFORE INSERT ON authority_operation_output_asset
 FOR EACH ROW EXECUTE FUNCTION authority_generation_commit_guard()""",
    """CREATE FUNCTION authority_generation_continuation_permitted(runtime_id TEXT, child_id TEXT, generation JSONB)
 RETURNS BOOLEAN LANGUAGE SQL STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM authority_story_planning_runtime_continuation r
 JOIN authority_operation registered ON registered.operation_id=r.registered_by_operation_id
 JOIN authority_operation source ON source.operation_id=r.source_operation_id
 JOIN authority_operation child ON child.operation_id=child_id
 JOIN authority_story_planning_generation prior ON prior.operation_id=source.operation_id
 JOIN authority_generation_isolation i ON i.operation_id=source.operation_id
 WHERE r.continuation_id=runtime_id AND r.successor_operation_id=child_id
 AND registered.status='SUCCEEDED' AND registered.definition_name='story_planning.runtime_continuation.register'
 AND authority_generation_isolated(i.external_effect_id)
 AND r.source_command=source.command_payload->'payload' AND r.successor_command=child.command_payload->'payload'
 AND (r.successor_command-'runtime_continuation_id'-'idempotency_key'-'opening_execution_binding')=(r.source_command-'runtime_continuation_id'-'idempotency_key'-'opening_execution_binding')
 AND child.causation_operation_id=source.operation_id AND child.project_id=i.project_id AND child.workspace_id=i.workspace_id
 AND child.actor_id=source.actor_id AND r.book_id=i.book_id AND generation->>'book_id'=i.book_id
 AND generation->>'generator_operation_name'=prior.generator_operation_name
 AND generation->>'logical_key'=prior.logical_key AND generation->>'planning_scope'=prior.planning_scope
 AND generation->'input_snapshot'=prior.input_snapshot AND generation->>'input_snapshot_hash'=prior.input_snapshot_hash
 AND (generation->>'repair_number')::int=prior.repair_number
 AND generation->>'narrative_search_id' IS NOT DISTINCT FROM prior.narrative_search_id
 AND generation->>'narrative_search_branch_key' IS NOT DISTINCT FROM prior.narrative_search_branch_key
 AND generation->>'candidate_asset_version_id' IS NULL
 AND r.target_runtime#>>'{generation_isolation,external_effect_id}'=i.external_effect_id
 AND r.decision_evidence->>'authorization_ref'=i.proof->>'authorization_ref') $$""",
    """CREATE OR REPLACE FUNCTION authority_planning_cli_lineage_reconciled(source_id TEXT)
RETURNS BOOLEAN LANGUAGE SQL STABLE AS $$
 WITH scope AS (
   SELECT source.project_id, COALESCE(NULLIF(source.root_operation_id,''),source.operation_id) AS root_id,
     COALESCE(request_book.book_id,production.book_id,NULLIF(source.command_payload->>'book_id',''),
       NULLIF(source.command_payload #>> '{payload,book_id}',''),
       NULLIF(original.command_payload->>'book_id',''),
       NULLIF(original.command_payload #>> '{payload,book_id}',''),'') AS book_id
   FROM authority_operation source
   LEFT JOIN authority_operation original ON original.operation_id=source.root_operation_id AND original.project_id=source.project_id
   LEFT JOIN authority_book_chapter_request request ON request.project_id=source.project_id
     AND request.chapter_root_operation_id=COALESCE(NULLIF(source.root_operation_id,''),source.operation_id)
   LEFT JOIN authority_book_production request_book ON request_book.book_run_id=request.book_run_id
     AND request_book.project_id=source.project_id
   LEFT JOIN authority_book_production production ON production.project_id=source.project_id
     AND production.root_operation_id=COALESCE(NULLIF(source.root_operation_id,''),source.operation_id)
   WHERE source.operation_id=source_id
     AND (request.book_run_id IS NULL OR (request_book.book_run_id IS NOT NULL AND request_book.workspace_id=source.workspace_id))
     AND (production.book_id IS NULL OR production.workspace_id=source.workspace_id)
     AND NOT EXISTS(SELECT 1 FROM authority_story_planning_generation generation
       WHERE generation.operation_id=source.operation_id AND generation.project_id=source.project_id
         AND COALESCE(request_book.book_id,production.book_id) IS NOT NULL
         AND generation.book_id<>COALESCE(request_book.book_id,production.book_id))
 )
 SELECT EXISTS(SELECT 1 FROM scope) AND NOT EXISTS (
   SELECT 1 FROM scope
   JOIN authority_external_effect effect ON effect.project_id=scope.project_id
   JOIN authority_operation owner ON owner.operation_id=effect.operation_id AND owner.project_id=effect.project_id
   LEFT JOIN authority_operation original ON original.operation_id=owner.root_operation_id AND original.project_id=owner.project_id
   LEFT JOIN authority_book_chapter_request request ON request.project_id=owner.project_id
     AND request.chapter_root_operation_id=COALESCE(NULLIF(owner.root_operation_id,''),owner.operation_id)
   LEFT JOIN authority_book_production request_book ON request_book.book_run_id=request.book_run_id
     AND request_book.project_id=owner.project_id
   LEFT JOIN authority_book_production production ON production.project_id=owner.project_id
     AND production.root_operation_id=COALESCE(NULLIF(owner.root_operation_id,''),owner.operation_id)
   LEFT JOIN authority_budget_reservation budget ON budget.external_effect_id=effect.external_effect_id AND budget.project_id=effect.project_id
   JOIN authority_external_effect_dispatch dispatch ON dispatch.external_effect_id=effect.external_effect_id
   WHERE ((scope.book_id='' AND (owner.operation_id=scope.root_id OR owner.root_operation_id=scope.root_id))
     OR (scope.book_id<>'' AND COALESCE(request_book.book_id,production.book_id,NULLIF(effect.request_payload #>> '{_production_execution,book_id}',''),
       NULLIF(owner.command_payload->>'book_id',''),NULLIF(owner.command_payload #>> '{payload,book_id}',''),
       NULLIF(original.command_payload->>'book_id',''),NULLIF(original.command_payload #>> '{payload,book_id}',''),
       NULLIF(budget.evidence->>'work_id',''))=scope.book_id))
     AND NOT authority_generation_isolated(effect.external_effect_id)
     AND dispatch.evidence #>> '{production_execution,execution_handle,transport}'='LOCAL_CLI_REMOTE_INFERENCE'
     AND (dispatch.evidence #>> '{production_execution,execution_result,outcome}' IN ('UNKNOWN','TIMED_OUT','CANCELLED','ORPHANED')
       OR (dispatch.evidence #>> '{production_execution,execution_result,outcome}'='RETRYABLE_FAILURE'
         AND dispatch.evidence #>> '{production_execution,process_evidence,failure_code}'='PROCESS_EXIT_FAILURE'))
     AND (dispatch.evidence #>> '{production_execution,execution_result,outcome}'='ORPHANED'
       OR NOT COALESCE(dispatch.evidence #> '{production_execution,execution_result,started_at}'='null'::jsonb,FALSE))
     AND NULLIF(dispatch.evidence #>> '{production_execution,execution_result,usage_receipt_ref}','') IS NULL
     AND NOT EXISTS(SELECT 1 FROM authority_effect_reconciliation_evidence r
       WHERE r.external_effect_id=effect.external_effect_id
         AND r.evidence->>'contract_version'='cli-original-reconciliation.v1'
         AND r.evidence->>'project_id'=effect.project_id AND r.evidence->>'operation_id'=effect.operation_id
         AND r.evidence->>'request_hash'=effect.request_hash
         AND r.evidence->>'dispatch_id'=dispatch.dispatch_id
         AND r.evidence->>'generation'=dispatch.generation::text)
 );
$$""",
    """CREATE OR REPLACE FUNCTION authority_planning_result_repair_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP='UPDATE' THEN
            IF ROW(OLD.repair_of_operation_id,OLD.repair_result_asset_version_id,OLD.runtime_continuation_id)
               IS DISTINCT FROM ROW(NEW.repair_of_operation_id,NEW.repair_result_asset_version_id,NEW.runtime_continuation_id) THEN
                RAISE EXCEPTION 'PLANNING_RESULT_REPAIR_IDENTITY_IMMUTABLE' USING ERRCODE='check_violation';
            END IF;
        ELSE
            IF NEW.runtime_continuation_id IS NOT NULL
               AND NOT authority_world_contract_continuation_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))
               AND NOT authority_planning_host_continuation_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))
            AND NOT authority_generation_continuation_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))
               AND NOT EXISTS (
                SELECT 1 FROM authority_story_planning_runtime_continuation r
                JOIN authority_operation source ON source.operation_id=r.source_operation_id AND source.status IN ('CANCELLED','FAILED_FINAL','DEAD_LETTER')
                JOIN authority_story_planning_generation source_generation ON source_generation.operation_id=source.operation_id
                JOIN authority_operation child ON child.operation_id=NEW.operation_id
                JOIN authority_operation registration ON registration.operation_id=r.registered_by_operation_id
                WHERE r.continuation_id=NEW.runtime_continuation_id
                  AND registration.status='SUCCEEDED' AND registration.definition_name IN ('story_planning.runtime_continuation.register','story_planning.world_preparation.defer')
                  AND r.project_id=NEW.project_id AND r.workspace_id=NEW.workspace_id AND r.book_id=NEW.book_id
                  AND r.source_command=source.command_payload->'payload' AND r.successor_command=child.command_payload->'payload'
                  AND (child.causation_operation_id=source.operation_id OR (
                    r.target_runtime #>> '{planning_capacity,version}'='planning-capacity-allocation.v1'
                    AND EXISTS (
                      SELECT 1 FROM authority_operation_output_asset repair_output
                      JOIN authority_story_planning_generation repair
                        ON repair.operation_id=repair_output.operation_id
                        AND repair.candidate_asset_version_id=repair_output.asset_version_id
                      WHERE repair_output.asset_version_id=r.source_command->>'repair_of_candidate_id'
                        AND repair.project_id=NEW.project_id AND repair.workspace_id=NEW.workspace_id
                        AND repair.book_id=NEW.book_id
                        AND child.causation_operation_id=repair.operation_id
                    )
                  ))
                  AND (r.successor_operation_id IS NULL OR r.successor_operation_id=child.operation_id)
                  AND source_generation.generator_operation_name=NEW.generator_operation_name
                  AND source_generation.logical_key=NEW.logical_key AND source_generation.input_snapshot_hash=NEW.input_snapshot_hash
                  AND source_generation.repair_number=NEW.repair_number
                  AND source_generation.repair_of_candidate_id IS NOT DISTINCT FROM NEW.repair_of_candidate_id
                  AND source_generation.repair_reason IS NOT DISTINCT FROM NEW.repair_reason
                  AND ((registration.definition_name='story_planning.runtime_continuation.register' AND (source.status='CANCELLED' OR (
                    source.status IN ('FAILED_FINAL','DEAD_LETTER')
                    AND r.target_runtime #>> '{planning_capacity,version}'='planning-capacity-allocation.v1'
                    AND source_generation.candidate_asset_version_id IS NULL
                    AND r.successor_command->>'runtime_continuation_id'=r.continuation_id
                    AND COALESCE((SELECT COALESCE(a.result->>'error_code',a.error->>'error_code')
                        FROM authority_attempt a WHERE a.operation_id=source.operation_id
                        ORDER BY a.attempt_number DESC LIMIT 1),'')='PLANNING_PROVIDER_CONTEXT_BUDGET_EXCEEDED'
                    AND NOT EXISTS(SELECT 1 FROM authority_external_effect e WHERE e.operation_id=source.operation_id)
                    AND NOT EXISTS(SELECT 1 FROM authority_budget_reservation b WHERE b.operation_id=source.operation_id)
                  ) OR (
                    source_generation.repair_of_candidate_id IS NOT NULL
                    AND NOT EXISTS (SELECT 1 FROM authority_external_effect e WHERE e.operation_id=source.operation_id)
                    AND NOT EXISTS (SELECT 1 FROM authority_budget_reservation b WHERE b.operation_id=source.operation_id)
                    AND EXISTS (SELECT 1 FROM authority_attempt a WHERE a.operation_id=source.operation_id
                        AND a.attempt_number=(SELECT max(last.attempt_number) FROM authority_attempt last WHERE last.operation_id=source.operation_id)
                        AND a.status='FAILED_FINAL'
                        AND COALESCE(a.error->>'error_code',a.result->>'error_code')='NATIVE_PLANNING_REPAIR_SOURCE_INVALID')
                    AND EXISTS (SELECT 1 FROM authority_operation_output_asset output
                        JOIN authority_asset_version v USING(asset_version_id)
                        JOIN authority_asset asset ON asset.asset_id=v.asset_id
                        WHERE output.operation_id=registration.operation_id AND asset.asset_type='planning_runtime_continuation'
                          AND v.content->>'source_operation_id'=source.operation_id
                          AND v.content #>> '{source_preflight_failure,contract_version}'='planning-input-order-preflight.v1')
                  ))) OR (
                    registration.definition_name='story_planning.world_preparation.defer'
                    AND source_generation.project_id=NEW.project_id
                    AND source_generation.workspace_id=NEW.workspace_id
                    AND source_generation.book_id=NEW.book_id
                    AND source_generation.planning_scope=NEW.planning_scope
                    AND source.status IN ('FAILED_FINAL','DEAD_LETTER') AND source_generation.candidate_asset_version_id IS NULL
                    AND source.command_payload #> '{payload,world_preparation_request}' IS NOT NULL
                    AND EXISTS (SELECT 1 FROM authority_attempt a WHERE a.operation_id=source.operation_id
                        AND a.attempt_number=(SELECT max(last.attempt_number) FROM authority_attempt last WHERE last.operation_id=source.operation_id)
                        AND a.status='FAILED_FINAL'
                        AND COALESCE(a.error->>'error_code',a.result->>'error_code') IN ('WORLD_PREPARATION_RESULT_INVALID','WORLD_PREPARATION_BLOCKED'))
                    AND (SELECT count(*) FROM authority_external_effect e WHERE e.operation_id=source.operation_id)=2
                    AND (SELECT count(DISTINCT e.request_payload->>'stage') FROM authority_external_effect e
                        WHERE e.operation_id=source.operation_id AND e.status='SUCCEEDED'
                        AND e.request_payload->>'stage' IN ('world_candidates.generate','world_candidates.evaluate'))=2
                    AND (SELECT count(*) FROM authority_budget_reservation b WHERE b.operation_id=source.operation_id)=2
                    AND NOT EXISTS (SELECT 1 FROM authority_budget_reservation b WHERE b.operation_id=source.operation_id AND b.status<>'SETTLED')
                    AND NOT EXISTS (SELECT 1 FROM authority_lease_acquisition l JOIN authority_attempt a USING(attempt_id)
                        WHERE a.operation_id=source.operation_id AND l.status='HELD')
                    AND EXISTS (SELECT 1 FROM authority_operation_output_asset output
                        JOIN authority_asset_version v USING(asset_version_id)
                        JOIN authority_asset asset ON asset.asset_id=v.asset_id
                        WHERE output.operation_id=registration.operation_id AND asset.asset_type='narrative_governance_action'
                          AND asset.project_id=NEW.project_id
                          AND v.asset_version_id=r.decision_evidence #>> '{world_optional_action,asset_version_id}'
                          AND v.content_hash=r.decision_evidence #>> '{world_optional_action,content_hash}'
                          AND v.content #>> '{contract,book_id}'=NEW.book_id
                          AND v.content #>> '{contract,optional_preparation,contract_version}'='world-optional-preparation.v1'
                          AND v.content #>> '{contract,optional_preparation,status}'='NOT_RUN'
                          AND v.content #>> '{contract,world_plan,disposition}'='DEFER'
                          AND v.content #>> '{contract,world_plan,selected_candidate_id}'=''
                          AND v.content #> '{contract,world_plan,preparation_schedule}'='[]'::jsonb
                          AND v.content #> '{contract,fact_mutation_allowed}'='false'::jsonb
                          AND v.content #> '{contract,optional_preparation,policy_admission}'=r.decision_evidence->'policy_admission'
                          AND EXISTS (SELECT 1 FROM jsonb_array_elements(r.decision_evidence #> '{policy_admission,policy_snapshot,policy,execution_templates}') t
                              WHERE t->>'book_id'=NEW.book_id AND t->>'mode'='CREATIVE_VALIDATION'
                                AND t->>'version' IN ('creative-execution-template.v3','creative-execution-template.v4','creative-execution-template.v5','creative-execution-template.v6','creative-execution-template.v7','creative-execution-template.v8','creative-execution-template.v9','creative-execution-template.v10','creative-execution-template.v11')
                                AND t->>'world_future_preparation' IN ('OPTIONAL','DISABLED')
                                AND t->'require_literary_qualification'='false'::jsonb))
                  ))
                  AND source_generation.repair_of_operation_id IS NOT DISTINCT FROM NEW.repair_of_operation_id
                  AND source_generation.repair_result_asset_version_id IS NOT DISTINCT FROM NEW.repair_result_asset_version_id
            ) THEN
                RAISE EXCEPTION 'PLANNING_RUNTIME_CONTINUATION_GENERATION_INVALID' USING ERRCODE='check_violation';
            END IF;
            IF NEW.repair_of_operation_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM authority_story_planning_generation parent
                JOIN authority_operation op ON op.operation_id=parent.operation_id
                JOIN authority_operation child ON child.operation_id=NEW.operation_id
                JOIN authority_operation_output_asset source ON source.operation_id=parent.operation_id
                WHERE parent.operation_id=NEW.repair_of_operation_id
                  AND parent.project_id=NEW.project_id AND parent.workspace_id=NEW.workspace_id
                  AND parent.book_id=NEW.book_id AND parent.generator_operation_name=NEW.generator_operation_name
                  AND parent.logical_key=NEW.logical_key AND parent.input_snapshot_hash=NEW.input_snapshot_hash
                  AND parent.candidate_asset_version_id IS NULL AND (op.status='FAILED_FINAL' OR (op.status='DEAD_LETTER' AND NOT EXISTS (
                  SELECT 1 FROM authority_external_effect pending
                  WHERE pending.operation_id=parent.operation_id
                    AND pending.status NOT IN ('SUCCEEDED','FAILED_FINAL','CANCELLED')
              ) AND EXISTS (
                  SELECT 1 FROM authority_external_effect known
                  WHERE known.operation_id=parent.operation_id AND known.status='SUCCEEDED'
              )))
                  AND NEW.repair_number=parent.repair_number+1
                  AND (child.causation_operation_id=parent.operation_id OR EXISTS (
                    SELECT 1 FROM authority_story_planning_runtime_continuation continuation
                    JOIN authority_operation runtime_source ON runtime_source.operation_id=continuation.source_operation_id
                    WHERE continuation.continuation_id=NEW.runtime_continuation_id
                      AND continuation.project_id=NEW.project_id AND continuation.workspace_id=NEW.workspace_id
                      AND continuation.book_id=NEW.book_id
                      AND continuation.successor_command=child.command_payload->'payload'
                      AND continuation.source_command=runtime_source.command_payload->'payload'
                      AND continuation.source_command->>'repair_of_operation_id'=parent.operation_id
                      AND continuation.source_command->>'repair_result_asset_version_id'=NEW.repair_result_asset_version_id
                      AND (continuation.source_command->>'repair_number')::int=NEW.repair_number
                      AND (continuation.successor_operation_id IS NULL OR continuation.successor_operation_id=child.operation_id)
                      AND child.causation_operation_id=runtime_source.operation_id
                  ))
                  AND source.asset_version_id=NEW.repair_result_asset_version_id
            ) THEN
                RAISE EXCEPTION 'PLANNING_RESULT_REPAIR_SOURCE_INVALID' USING ERRCODE='check_violation';
            END IF;
        END IF;
        IF TG_OP='INSERT' AND NEW.repair_of_operation_id IS NOT NULL AND NEW.repair_number>2 AND NOT EXISTS (
            SELECT 1 FROM authority_runtime_policy_selection s
            JOIN authority_runtime_policy_version v USING(owner,project_id,policy_version)
            JOIN authority_operation policy ON policy.operation_id=v.created_by_operation_id
            JOIN LATERAL jsonb_array_elements(v.content->'execution_templates') t ON TRUE
            WHERE s.owner='PROVIDER_ROUTING' AND s.project_id=NEW.project_id AND policy.status='SUCCEEDED'
              AND t->>'book_id'=NEW.book_id AND t->>'version' IN ('creative-execution-template.v4','creative-execution-template.v5','creative-execution-template.v6','creative-execution-template.v7','creative-execution-template.v8','creative-execution-template.v9','creative-execution-template.v10','creative-execution-template.v11')
              AND t->>'mode'='CREATIVE_VALIDATION' AND t->'require_literary_qualification'='false'::jsonb
              AND t #>> '{repair_routing,version}'='native-repair-routing.v2'
              AND (t #>> '{repair_routing,max_same_route_repairs}')::int BETWEEN 1 AND 2
        ) THEN
            RAISE EXCEPTION 'PLANNING_STAGE_REPAIR_POLICY_REQUIRED' USING ERRCODE='check_violation';
        END IF;
        RETURN NEW;
    END; $$""",
    """ALTER TABLE authority_effect_manual_resolution DROP CONSTRAINT authority_effect_manual_resolution_decision_check""",
    """ALTER TABLE authority_effect_manual_resolution ADD CONSTRAINT authority_effect_manual_resolution_decision_check CHECK(decision IN ('MARK_SUCCEEDED','MARK_NOT_FOUND','MARK_FAILED_FINAL','MARK_CANCELLED','RETRY_WITH_NEW_GENERATION','ISOLATE_PURE_GENERATION'))""",
    """ALTER TABLE authority_book_opening_recovery_assessment DROP CONSTRAINT authority_book_opening_recovery_assessment_disposition_check""",
    """ALTER TABLE authority_book_opening_recovery_assessment ADD CONSTRAINT authority_book_opening_recovery_assessment_disposition_check CHECK ((disposition = ANY (ARRAY['ISOLATED_PURE_GENERATION'::text, 'PROVEN_NO_EFFECT'::text, 'PROVEN_SUCCESS'::text, 'PROVEN_TERMINAL_FAILURE'::text, 'UNKNOWN_AMBIGUOUS'::text, 'EXECUTION_LOST'::text, 'RECONCILIATION_REQUIRED'::text])))""",
    """CREATE OR REPLACE FUNCTION public.authority_assert_book_opening_recovery_fact(target_recovery_assessment_id text)
 RETURNS void
 LANGUAGE plpgsql
AS $function$
    DECLARE
        assessment RECORD;
        receipt RECORD;
        intent_binding RECORD;
        successor_binding RECORD;
        opening_binding RECORD;
        predecessor_binding RECORD;
        expected_assessment_kind TEXT;
        matching_receipts BIGINT;
    BEGIN
        SELECT recovery_assessment_id,assessment_kind,opening_run_id,
               opening_execution_id,execution_generation,disposition
        INTO assessment
        FROM authority_book_opening_recovery_assessment
        WHERE recovery_assessment_id=target_recovery_assessment_id;
        IF NOT FOUND THEN
            RETURN;
        END IF;

        IF assessment.disposition='ISOLATED_PURE_GENERATION' AND NOT EXISTS(
            SELECT 1 FROM authority_book_opening_recovery_assessment a
            WHERE a.recovery_assessment_id=assessment.recovery_assessment_id
            AND jsonb_array_length(a.snapshot#>'{external_effect,evidence}')>0
            AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(a.snapshot#>'{external_effect,evidence}') item
                WHERE NOT authority_generation_isolated(item->>'effect_id'))
        ) THEN RAISE EXCEPTION 'GENERATION_ISOLATION_RECOVERY_PROOF_REQUIRED'; END IF;

        FOR intent_binding IN
            SELECT *
            FROM authority_book_opening_recovery_intent
            WHERE recovery_assessment_id=assessment.recovery_assessment_id
        LOOP
            IF assessment.assessment_kind IS DISTINCT FROM 'RECOVERY'
               OR assessment.disposition NOT IN (
                   'PROVEN_NO_EFFECT','PROVEN_SUCCESS',
                   'PROVEN_TERMINAL_FAILURE','ISOLATED_PURE_GENERATION'
               )
               OR assessment.opening_execution_id IS DISTINCT FROM
                  intent_binding.predecessor_execution_id
               OR assessment.execution_generation IS DISTINCT FROM
                  intent_binding.predecessor_generation THEN
                RAISE EXCEPTION
                    'BOOK_OPENING_RECOVERY_INTENT_ASSESSMENT_BINDING_INVALID:%',
                    intent_binding.recovery_intent_id
                    USING ERRCODE='check_violation';
            END IF;
            SELECT COUNT(*) INTO matching_receipts
            FROM authority_book_opening_recovery_receipt
            WHERE recovery_intent_id=intent_binding.recovery_intent_id
              AND recovery_assessment_id=assessment.recovery_assessment_id
              AND receipt_kind='RECOVERY_ADMISSION';
            IF matching_receipts IS DISTINCT FROM 1::BIGINT THEN
                RAISE EXCEPTION
                    'BOOK_OPENING_RECOVERY_INTENT_RECEIPT_REQUIRED:%',
                    intent_binding.recovery_intent_id
                    USING ERRCODE='check_violation';
            END IF;
        END LOOP;

        FOR receipt IN
            SELECT *
            FROM authority_book_opening_recovery_receipt
            WHERE recovery_assessment_id=
                  assessment.recovery_assessment_id
        LOOP
            expected_assessment_kind = CASE receipt.receipt_kind
                WHEN 'EXECUTION_LOSS_CONVERGENCE' THEN 'EXECUTION_LOSS'
                WHEN 'RECOVERY_ADMISSION' THEN 'RECOVERY'
                WHEN 'CHECKPOINT_RECONCILIATION' THEN
                    'CHECKPOINT_RECONCILIATION'
                WHEN 'LEGACY_EXECUTION_RECONCILIATION' THEN
                    'LEGACY_EXECUTION_RECONCILIATION'
            END;
            IF assessment.assessment_kind IS DISTINCT FROM
               expected_assessment_kind THEN
                RAISE EXCEPTION
                    'BOOK_OPENING_RECOVERY_RECEIPT_ASSESSMENT_KIND_INVALID:%',
                    receipt.recovery_receipt_id
                    USING ERRCODE='check_violation';
            END IF;
            IF assessment.opening_execution_id IS DISTINCT FROM
               receipt.predecessor_execution_id
               OR assessment.execution_generation IS DISTINCT FROM
                  receipt.predecessor_generation THEN
                RAISE EXCEPTION
                    'BOOK_OPENING_RECOVERY_RECEIPT_ASSESSMENT_BINDING_INVALID:%',
                    receipt.recovery_receipt_id
                    USING ERRCODE='check_violation';
            END IF;
            IF (receipt.receipt_kind='EXECUTION_LOSS_CONVERGENCE'
                AND assessment.disposition IS DISTINCT FROM 'EXECUTION_LOST')
               OR (receipt.receipt_kind IN (
                       'CHECKPOINT_RECONCILIATION',
                       'LEGACY_EXECUTION_RECONCILIATION'
                   ) AND assessment.disposition IS DISTINCT FROM
                       'RECONCILIATION_REQUIRED') THEN
                RAISE EXCEPTION
                    'BOOK_OPENING_RECOVERY_RECEIPT_DISPOSITION_INVALID:%',
                    receipt.recovery_receipt_id
                    USING ERRCODE='check_violation';
            END IF;

            SELECT lifecycle,current_execution_id,current_execution_generation
            INTO opening_binding
            FROM authority_book_opening_run
            WHERE opening_run_id=receipt.opening_run_id;
            SELECT lifecycle INTO predecessor_binding
            FROM authority_book_opening_execution
            WHERE opening_run_id=receipt.opening_run_id
              AND opening_execution_id=receipt.predecessor_execution_id
              AND generation=receipt.predecessor_generation;

            IF receipt.receipt_kind='RECOVERY_ADMISSION' THEN
                SELECT recovery_intent_id,opening_run_id,
                       recovery_assessment_id,predecessor_execution_id,
                       predecessor_generation,successor_generation
                INTO intent_binding
                FROM authority_book_opening_recovery_intent
                WHERE recovery_intent_id=receipt.recovery_intent_id
                  AND opening_run_id=receipt.opening_run_id;
                IF NOT FOUND
                   OR intent_binding.recovery_assessment_id IS DISTINCT FROM
                      receipt.recovery_assessment_id
                   OR intent_binding.predecessor_execution_id IS DISTINCT FROM
                      receipt.predecessor_execution_id
                   OR intent_binding.predecessor_generation IS DISTINCT FROM
                      receipt.predecessor_generation
                   OR intent_binding.successor_generation IS DISTINCT FROM
                      receipt.successor_generation THEN
                    RAISE EXCEPTION
                        'BOOK_OPENING_RECOVERY_RECEIPT_INTENT_BINDING_INVALID:%',
                        receipt.recovery_receipt_id
                        USING ERRCODE='check_violation';
                END IF;

                SELECT predecessor_execution_id,predecessor_generation,
                       recovery_intent_id
                INTO successor_binding
                FROM authority_book_opening_execution
                WHERE opening_run_id=receipt.opening_run_id
                  AND opening_execution_id=receipt.successor_execution_id
                  AND generation=receipt.successor_generation;
                IF NOT FOUND
                   OR successor_binding.predecessor_execution_id
                      IS DISTINCT FROM receipt.predecessor_execution_id
                   OR successor_binding.predecessor_generation
                      IS DISTINCT FROM receipt.predecessor_generation
                   OR successor_binding.recovery_intent_id IS DISTINCT FROM
                      receipt.recovery_intent_id THEN
                    RAISE EXCEPTION
                        'BOOK_OPENING_RECOVERY_RECEIPT_INTENT_BINDING_INVALID:%',
                        receipt.recovery_receipt_id
                        USING ERRCODE='check_violation';
                END IF;
                IF opening_binding.lifecycle IS DISTINCT FROM 'ADMITTED'
                   OR opening_binding.current_execution_id IS DISTINCT FROM
                      receipt.successor_execution_id
                   OR opening_binding.current_execution_generation IS DISTINCT FROM
                      receipt.successor_generation THEN
                    RAISE EXCEPTION
                        'BOOK_OPENING_RECOVERY_RECEIPT_OPENING_BINDING_INVALID:%',
                        receipt.recovery_receipt_id
                        USING ERRCODE='check_violation';
                END IF;
            ELSIF opening_binding.current_execution_id IS DISTINCT FROM
                  receipt.predecessor_execution_id
               OR opening_binding.current_execution_generation IS DISTINCT FROM
                  receipt.predecessor_generation
               OR (
                   receipt.receipt_kind='EXECUTION_LOSS_CONVERGENCE'
                   AND (
                       opening_binding.lifecycle IS DISTINCT FROM 'FAILED'
                       OR predecessor_binding.lifecycle IS DISTINCT FROM 'LOST'
                   )
               )
               OR (
                   receipt.receipt_kind='CHECKPOINT_RECONCILIATION'
                   AND (
                       opening_binding.lifecycle IS DISTINCT FROM 'FAILED'
                       OR predecessor_binding.lifecycle NOT IN ('FAILED','LOST')
                   )
               ) THEN
                RAISE EXCEPTION
                    'BOOK_OPENING_RECOVERY_RECEIPT_OPENING_BINDING_INVALID:%',
                    receipt.recovery_receipt_id
                    USING ERRCODE='check_violation';
            END IF;
        END LOOP;
    END;
    $function$
""",
]

DOWNGRADE_STATEMENTS: list[str] = []

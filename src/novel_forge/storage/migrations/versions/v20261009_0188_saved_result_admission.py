from __future__ import annotations

MIGRATION_ID = "20261009_0188_saved_result_admission"
DOWN_REVISION = "20261009_0187_chapter_generation_isolation"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Admit verified original saved Planning output after a failed terminal owner without new Provider I/O or rewriting history."

UPGRADE_STATEMENTS = [
    r"""CREATE OR REPLACE FUNCTION authority_result_admission_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP<>'INSERT' THEN
            RAISE EXCEPTION 'PLANNING_RESULT_ADMISSION_IMMUTABLE' USING ERRCODE='check_violation';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM authority_story_planning_generation g
            JOIN authority_operation source ON source.operation_id=g.operation_id
            JOIN authority_operation recovery ON recovery.operation_id=NEW.recovery_operation_id
            JOIN authority_operation_output_asset raw ON raw.operation_id=source.operation_id
                AND raw.asset_version_id=NEW.source_result_asset_version_id
            JOIN authority_operation_output_asset candidate ON candidate.operation_id=recovery.operation_id
                AND candidate.asset_version_id=NEW.candidate_asset_version_id
            JOIN authority_asset_version candidate_version ON candidate_version.asset_version_id=candidate.asset_version_id
            JOIN authority_external_effect effect ON effect.operation_id=source.operation_id
                AND effect.external_effect_id=NEW.external_effect_id
            WHERE source.operation_id=NEW.source_operation_id AND source.status IN ('FAILED_FINAL','DEAD_LETTER')
                AND source.project_id=NEW.project_id AND recovery.project_id=source.project_id
                AND recovery.workspace_id=source.workspace_id AND g.book_id=NEW.book_id
                AND recovery.causation_operation_id=source.operation_id
                AND g.version=NEW.source_generation_version AND g.candidate_asset_version_id IS NULL
                AND ((source.status='FAILED_FINAL' AND ((recovery.definition_name='story_planning.result_admission.recover' AND effect.status='SUCCEEDED')
                    OR (recovery.definition_name='story_planning.gateway_result.revalidate' AND effect.status='FAILED_FINAL'
                        AND recovery.definition_snapshot->>'handler_contract_version'='planning-gateway-result-revalidation.v1'
                        AND NEW.evidence->>'contract_version'='planning-gateway-result-revalidation.v1'
                        AND NEW.evidence->>'original_failure'='OUTPUT_SCHEMA_FAILURE'
                        AND NEW.evidence->>'original_gateway_outcome'='FINAL_FAILURE'
                        AND NEW.evidence->>'current_result_validation'='VALID'
                        AND NEW.evidence->'provider_invoked'='false'::jsonb
                        AND NEW.evidence->>'literary_qualification'='NOT_RUN'
                        AND NEW.evidence->>'external_effect_id'=effect.external_effect_id
                        AND NEW.evidence->>'source_operation_id'=source.operation_id
                        AND NEW.evidence->>'target_release_sha'=recovery.definition_snapshot->>'commit_sha'
                        AND jsonb_array_length(NEW.evidence->'legacy_literal_null_paths')>0
                        AND candidate_version.content->'result_admission_recovery'=NEW.evidence
                        AND effect.last_error #>> '{production_execution,process_evidence,failure_code}'='OUTPUT_SCHEMA_FAILURE'
                        AND effect.last_error #>> '{production_execution,execution_result,outcome}'='FINAL_FAILURE'
                        AND effect.request_payload #>> '{_production_execution,capability_runtime,routing_decision,mode}'='CREATIVE_VALIDATION'
                        AND NOT EXISTS(SELECT 1 FROM authority_external_effect e WHERE e.operation_id=source.operation_id AND e.external_effect_id<>effect.external_effect_id AND e.status<>'SUCCEEDED')
                        AND NOT EXISTS(SELECT 1 FROM authority_budget_reservation b WHERE b.operation_id=source.operation_id AND b.status<>'SETTLED')
                        AND (SELECT count(*) FROM authority_budget_reservation b WHERE b.external_effect_id=effect.external_effect_id AND b.status='SETTLED')=1
                        AND NOT EXISTS(SELECT 1 FROM authority_lease_acquisition l JOIN authority_attempt a USING(attempt_id) WHERE a.operation_id=source.operation_id AND l.status='HELD')
                        AND EXISTS(SELECT 1 FROM authority_operation_output_asset output JOIN authority_asset_version v USING(asset_version_id)
                            JOIN authority_asset a ON a.asset_id=v.asset_id WHERE output.operation_id=recovery.operation_id
                            AND a.asset_type='planning_gateway_result_revalidation' AND a.project_id=NEW.project_id
                            AND v.content->'evidence'=NEW.evidence
                            AND v.content->'locally_bound_result'=(candidate_version.content->'candidate_payload')-'constraint_envelope'-'craft_strategy')
                    ))) OR (
                    recovery.definition_name='story_planning.gateway_result.revalidate'
                    AND recovery.definition_snapshot->>'handler_contract_version'='planning-gateway-result-revalidation.v1'
                    AND effect.status='SUCCEEDED' AND effect.effect_type='model.invoke'
                    AND NOT authority_generation_isolated(effect.external_effect_id)
                    AND NEW.evidence->>'contract_version'='planning-gateway-result-revalidation.v1'
                    AND NEW.evidence->>'original_gateway_outcome'='SUCCEEDED'
                    AND NEW.evidence->>'current_result_validation'='VALID'
                    AND NEW.evidence->'provider_invoked'='false'::jsonb
                    AND NEW.evidence->>'source_operation_id'=source.operation_id
                    AND NEW.evidence->>'external_effect_id'=effect.external_effect_id
                    AND NEW.evidence->>'target_release_sha'=recovery.definition_snapshot->>'commit_sha'
                    AND candidate_version.content->'result_admission_recovery'=NEW.evidence
                    AND NOT EXISTS(SELECT 1 FROM authority_lease_acquisition lease JOIN authority_attempt attempt USING(attempt_id)
                        WHERE attempt.operation_id=source.operation_id AND lease.status='HELD')
                    AND NOT EXISTS(SELECT 1 FROM authority_worker_cancel_signal WHERE operation_id=source.operation_id AND acknowledged_at IS NULL)
                    AND NOT EXISTS(SELECT 1 FROM authority_operation_output_asset WHERE operation_id=source.operation_id AND role='primary')
                    AND EXISTS(SELECT 1 FROM authority_external_effect_dispatch dispatch
                        JOIN authority_external_receipt receipt USING(dispatch_id)
                        JOIN authority_asset_version normalized ON normalized.asset_version_id=NEW.source_result_asset_version_id
                        WHERE dispatch.external_effect_id=effect.external_effect_id AND dispatch.status='SUCCEEDED'
                          AND dispatch.payload_hash=effect.request_hash AND receipt.status='VERIFIED'
                          AND receipt.payload #>> '{evidence,recovery_action}'='LOCAL_SAVED_RESULT_REUSE'
                          AND receipt.payload #>> '{evidence,production_execution,execution_request,operation_id}'=source.operation_id
                          AND receipt.payload #>> '{evidence,production_execution,execution_request,book_id}'=g.book_id
                          AND normalized.content->>'kind'='normalized-output'
                          AND normalized.content->'payload'=receipt.payload #> '{evidence,result}'
                          AND normalized.content->>'execution_id'=receipt.payload #>> '{evidence,production_execution,execution_request,execution_id}')
                    ) )
        ) THEN
            RAISE EXCEPTION 'PLANNING_RESULT_ADMISSION_SCOPE_INVALID' USING ERRCODE='check_violation';
        END IF;
        RETURN NEW;
    END; $$""",
]
DOWNGRADE_STATEMENTS: list[str] = []

from __future__ import annotations

from .v20261009_0193_completed_planning_admission import UPGRADE_STATEMENTS as PREVIOUS

MIGRATION_ID = "20261013_0205_completed_release_recovery"
DOWN_REVISION = "20261013_0204_retrieval_generation_progress"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Admit an exact completed Planning result after release-only retryable assembly failure through a new recovery owner; preserve the original failure and prevent new Provider dispatch."

_OLD_SCOPE = "source.status IN ('FAILED_FINAL','DEAD_LETTER')"
_NEW_SCOPE = """(source.status IN ('FAILED_FINAL','DEAD_LETTER') OR (
    source.status='FAILED_RETRYABLE'
    AND recovery.definition_name='story_planning.gateway_result.revalidate'
    AND recovery.definition_snapshot->>'handler_contract_version'='planning-gateway-result-revalidation.v2'
    AND NEW.evidence->>'contract_version'='planning-gateway-result-revalidation.v2'
    AND NEW.evidence->>'completed_result_source'='VERIFIED_PROVIDER_COMPLETION'
    AND NEW.evidence->>'source_release_sha'<>NEW.evidence->>'target_release_sha'
    AND source.version::text=NEW.evidence#>>'{retryable_release_recovery,source_operation_version}'
    AND effect.status='SUCCEEDED' AND effect.effect_type='model.invoke'
    AND (SELECT count(*) FROM authority_external_effect WHERE operation_id=source.operation_id)=1
    AND NOT EXISTS(SELECT 1 FROM authority_budget_reservation WHERE operation_id=source.operation_id AND status<>'SETTLED')
    AND NOT EXISTS(SELECT 1 FROM authority_worker_cancel_signal WHERE operation_id=source.operation_id)
    AND NOT EXISTS(SELECT 1 FROM authority_story_planning_generation WHERE repair_of_operation_id=source.operation_id)
    AND NOT EXISTS(SELECT 1 FROM authority_story_creation_cancellation cancellation
      JOIN authority_story_formation_run formation USING(formation_run_id)
      WHERE formation.project_id=source.project_id AND formation.book_id=g.book_id)
    AND EXISTS(SELECT 1 FROM authority_attempt attempt
      WHERE attempt.operation_id=source.operation_id AND attempt.status='FAILED_RETRYABLE'
        AND attempt.attempt_id=NEW.evidence#>>'{retryable_release_recovery,source_attempt_id}'
        AND attempt.attempt_number::text=NEW.evidence#>>'{retryable_release_recovery,source_attempt_number}'
        AND attempt.attempt_number=(SELECT max(latest.attempt_number) FROM authority_attempt latest WHERE latest.operation_id=source.operation_id)
        AND attempt.result=NEW.evidence#>'{retryable_release_recovery,source_failure_result}'
        AND attempt.result->>'error_code'='CAPABILITY_PACK_RUNTIME_ADMISSION_DRIFT'
        AND attempt.result->>'error_message'='CAPABILITY_PACK_RUNTIME_ADMISSION_DRIFT: runtime contract differs from Pack execution snapshot: release_sha')
    AND EXISTS(SELECT 1 FROM authority_asset_version materialization JOIN authority_asset materialization_asset USING(asset_id)
      WHERE materialization.asset_version_id=effect.request_payload#>>'{_production_execution,capability_runtime,materialization_asset_version_id}'
        AND materialization.content_hash=effect.request_payload#>>'{_production_execution,capability_runtime,materialization_content_hash}'
        AND materialization_asset.project_id=source.project_id
        AND materialization.content#>>'{contract,tool_permissions,default}'='DENY'
        AND materialization.content#>'{contract,tool_permissions,allowed}'='["model.provider.invoke"]'::jsonb)
))"""
_OLD_VERSION = """recovery.definition_name='story_planning.gateway_result.revalidate'
                    AND recovery.definition_snapshot->>'handler_contract_version'='planning-gateway-result-revalidation.v1'
                    AND effect.status='SUCCEEDED' AND effect.effect_type='model.invoke'
                    AND NOT authority_generation_isolated(effect.external_effect_id)
                    AND NEW.evidence->>'contract_version'='planning-gateway-result-revalidation.v1'"""
_NEW_VERSION = """recovery.definition_name='story_planning.gateway_result.revalidate'
                    AND ((source.status IN ('FAILED_FINAL','DEAD_LETTER')
                      AND recovery.definition_snapshot->>'handler_contract_version'='planning-gateway-result-revalidation.v1'
                      AND NEW.evidence->>'contract_version'='planning-gateway-result-revalidation.v1') OR (
                      source.status='FAILED_RETRYABLE'
                      AND recovery.definition_snapshot->>'handler_contract_version'='planning-gateway-result-revalidation.v2'
                      AND NEW.evidence->>'contract_version'='planning-gateway-result-revalidation.v2'))
                    AND effect.status='SUCCEEDED' AND effect.effect_type='model.invoke'
                    AND NOT authority_generation_isolated(effect.external_effect_id)"""
assert PREVIOUS[0].count(_OLD_SCOPE) == 1
assert PREVIOUS[0].count(_OLD_VERSION) == 1
_OWNER_LOCK = """BEGIN
        IF NEW.evidence->>'contract_version'='planning-gateway-result-revalidation.v2' THEN
            PERFORM formation_run_id FROM authority_story_formation_run
              WHERE project_id=NEW.project_id AND book_id=NEW.book_id ORDER BY formation_run_id FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'PLANNING_RESULT_ADMISSION_CREATION_OWNER_REQUIRED' USING ERRCODE='check_violation';
            END IF;
            PERFORM operation_id FROM authority_operation WHERE operation_id=NEW.source_operation_id FOR UPDATE;
            PERFORM generation_id FROM authority_story_planning_generation WHERE operation_id=NEW.source_operation_id FOR UPDATE;
        END IF;"""
UPGRADE_STATEMENTS = [PREVIOUS[0].replace(_OLD_SCOPE, _NEW_SCOPE).replace(_OLD_VERSION, _NEW_VERSION).replace("BEGIN", _OWNER_LOCK, 1)]
DOWNGRADE_STATEMENTS: list[str] = []

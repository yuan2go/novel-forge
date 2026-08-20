from __future__ import annotations


MIGRATION_ID = "20260820_0094_narrative_evaluator_codex_lineage"
DOWN_REVISION = "20260820_0093_book_liveness_critical_path_closure"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = (
    "Replace the Narrative Provider lineage guard with the canonical set of "
    "real-provider execution transports; no business rows are rewritten"
)


UPGRADE_STATEMENTS = [
    """
    CREATE OR REPLACE FUNCTION authority_validate_narrative_provider_lineage()
    RETURNS TRIGGER AS $$
    DECLARE
        model_call_content JSONB;
        model_call_content_hash TEXT;
        model_call_asset_type TEXT;
        model_call_project_id TEXT;
        evaluation_asset_content JSONB;
        evaluation_asset_content_hash TEXT;
        evaluation_asset_type TEXT;
        evaluation_asset_project_id TEXT;
    BEGIN
        IF NEW.evaluator_execution_class <> 'MODEL_PROVIDER'
           OR NEW.trust_boundary <> 'INDEPENDENT' THEN
            RETURN NEW;
        END IF;

        SELECT version.content, version.content_hash, asset.asset_type, asset.project_id
        INTO model_call_content, model_call_content_hash,
             model_call_asset_type, model_call_project_id
        FROM authority_asset_version AS version
        JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
        WHERE version.asset_version_id=NEW.provider_model_call_asset_version_id;

        SELECT version.content, version.content_hash,
               asset.asset_type, asset.project_id
        INTO evaluation_asset_content, evaluation_asset_content_hash,
             evaluation_asset_type, evaluation_asset_project_id
        FROM authority_asset_version AS version
        JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
        WHERE version.asset_version_id=NEW.evaluation_asset_version_id;

        IF NOT FOUND
           OR model_call_asset_type IS DISTINCT FROM 'model_call_log'
           OR model_call_project_id IS DISTINCT FROM NEW.project_id
           OR model_call_content_hash IS DISTINCT FROM
              NEW.provider_model_call_content_hash
           OR model_call_content->>'operation_id' IS DISTINCT FROM
              NEW.evaluation_operation_id
           OR model_call_content->>'attempt_id' IS DISTINCT FROM
              NEW.evaluation_attempt_id
           OR model_call_content->>'stage' IS DISTINCT FROM
              'narrative_semantic_evaluation'
           OR model_call_content#>>'{target_lineage,target_asset_version_id}'
              IS DISTINCT FROM NEW.asset_version_id
           OR model_call_content#>>'{target_lineage,target_content_hash}'
              IS DISTINCT FROM NEW.candidate_content_hash
           OR model_call_content#>>'{target_lineage,generation_operation_id}'
              IS DISTINCT FROM NEW.generation_operation_id
           OR model_call_content#>>'{provider_evidence,real_model_call}'
              IS DISTINCT FROM 'true'
           OR COALESCE(
                model_call_content#>>'{provider_evidence,production_execution,execution_handle,transport}',
                ''
              ) NOT IN ('REMOTE_PROVIDER_API', 'LOCAL_CLI_REMOTE_INFERENCE')
           OR model_call_content#>>'{provider_evidence,production_execution,route_snapshot,route_snapshot_id}'
              IS DISTINCT FROM NEW.provider_route_snapshot_id
           OR authority_sha256_jsonb(model_call_content->'provider_evidence')
              IS DISTINCT FROM NEW.provider_evidence_hash
           OR authority_sha256_jsonb(model_call_content#>'{provider_evidence,result}')
              IS DISTINCT FROM NEW.provider_result_hash
           OR evaluation_asset_type IS DISTINCT FROM
              'narrative_design_evaluation'
           OR evaluation_asset_project_id IS DISTINCT FROM NEW.project_id
           OR evaluation_asset_content#>>'{candidate_asset_version_id}'
              IS DISTINCT FROM NEW.asset_version_id
           OR evaluation_asset_content#>>'{candidate_content_hash}'
              IS DISTINCT FROM NEW.candidate_content_hash
           OR evaluation_asset_content#>>'{generation_operation_id}'
              IS DISTINCT FROM NEW.generation_operation_id
           OR evaluation_asset_content#>>'{evaluation_operation_id}'
              IS DISTINCT FROM NEW.evaluation_operation_id
           OR evaluation_asset_content#>>'{evaluation_attempt_id}'
              IS DISTINCT FROM NEW.evaluation_attempt_id
           OR evaluation_asset_content#>>'{evaluator_execution_class}'
              IS DISTINCT FROM NEW.evaluator_execution_class
           OR evaluation_asset_content#>>'{evaluation_evidence_hash}'
              IS DISTINCT FROM NEW.evaluation_evidence_hash
           OR evaluation_asset_content#>>'{qualification,qualification_hash}'
              IS DISTINCT FROM NEW.qualification_hash
           OR evaluation_asset_content#>'{evaluation}'
              IS DISTINCT FROM model_call_content#>'{provider_evidence,result}'
           OR evaluation_asset_content#>>'{provider_execution,provider_evidence_hash}'
              IS DISTINCT FROM NEW.provider_evidence_hash
           OR evaluation_asset_content#>>'{provider_execution,provider_result_hash}'
              IS DISTINCT FROM NEW.provider_result_hash
           OR evaluation_asset_content#>>'{provider_execution,route_snapshot_id}'
              IS DISTINCT FROM NEW.provider_route_snapshot_id
           OR authority_sha256_jsonb(NEW.evaluation)
              IS DISTINCT FROM NEW.evaluation_hash
           OR NEW.evaluation->>'layer' IS DISTINCT FROM NEW.design_layer
           OR NEW.evaluation->>'profile_id' IS DISTINCT FROM NEW.profile_id
           OR NEW.evaluation->>'profile_version' IS DISTINCT FROM
              NEW.profile_version
           OR NEW.evaluation->>'profile_hash' IS DISTINCT FROM NEW.profile_hash
           OR NEW.evaluation->>'capability_id' IS DISTINCT FROM NEW.capability_id
           OR NEW.evaluation->>'skill_ref' IS DISTINCT FROM NEW.skill_ref
           OR NOT EXISTS (
                SELECT 1
                FROM jsonb_array_elements(
                    evaluation_asset_content#>'{evaluation,evaluations}'
                ) AS item(value)
                WHERE item.value=NEW.evaluation
           )
           OR NOT EXISTS (
                SELECT 1
                FROM jsonb_array_elements(
                    evaluation_asset_content#>'{qualification,receipts}'
                ) AS receipt(value)
                WHERE receipt.value->>'layer'=NEW.design_layer
                  AND receipt.value->>'status'=NEW.qualification_status
                  AND receipt.value->>'profile_id'=NEW.profile_id
                  AND receipt.value->>'profile_version'=NEW.profile_version
                  AND receipt.value->>'profile_hash'=NEW.profile_hash
                  AND receipt.value->>'evaluation_hash'=NEW.evaluation_hash
                  AND receipt.value->'evidence'=NEW.evaluation
           )
        THEN
            RAISE EXCEPTION
                'Narrative qualification Provider lineage does not match exact ModelCallLog';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
]


def upgrade(connection) -> None:
    with connection.cursor() as cursor:
        for statement in UPGRADE_STATEMENTS:
            cursor.execute(statement)


__all__ = [
    "BACKUP_REQUIRED",
    "DOWN_REVISION",
    "FORWARD_FIX",
    "FORWARD_ONLY",
    "MIGRATION_ID",
    "UPGRADE_STATEMENTS",
    "upgrade",
]

from __future__ import annotations

MIGRATION_ID = "20260920_0139_narrative_reference_sampling"
DOWN_REVISION = "20260920_0138_narrative_craft_origin"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = "Preserve production qualification head guards while binding isolated reference sampling to native Kernel Operations and immutable policy grants."

UPGRADE_STATEMENTS = [
    """
    CREATE FUNCTION authority_narrative_reference_qualification_guard()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF EXISTS (SELECT 1 FROM authority_operation operation
                   WHERE operation.operation_id=NEW.evaluation_operation_id
                     AND operation.project_id=NEW.project_id
                     AND operation.command_payload->'payload' ? 'reference_evaluation') THEN
            RAISE EXCEPTION 'NARRATIVE_REFERENCE_CANNOT_QUALIFY_PRODUCTION'
                USING ERRCODE='check_violation';
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE TRIGGER authority_narrative_reference_qualification_guard
    BEFORE INSERT OR UPDATE ON authority_narrative_design_qualification
    FOR EACH ROW EXECUTE FUNCTION authority_narrative_reference_qualification_guard()
    """,
    """
    CREATE FUNCTION authority_narrative_reference_gate_is_open(
        p_operation_id TEXT, p_project_id TEXT
    ) RETURNS BOOLEAN LANGUAGE sql VOLATILE AS $$
        SELECT EXISTS (
            SELECT 1 FROM authority_operation operation
            CROSS JOIN LATERAL (SELECT operation.command_payload->'payload' value) payload
            CROSS JOIN LATERAL (SELECT payload.value->'routing_bootstrap_authorization' value) snapshot
            CROSS JOIN LATERAL (SELECT snapshot.value->'authorization' value) grant_scope
            JOIN authority_runtime_policy_version policy
              ON policy.owner='PROVIDER_ROUTING' AND policy.project_id=operation.project_id
              AND policy.policy_version=snapshot.value->>'policy_version'
              AND policy.content_hash=snapshot.value->>'policy_hash'
              AND policy.actor_id=snapshot.value->>'policy_actor_id'
              AND policy.created_by_operation_id=snapshot.value->>'policy_operation_id'
              AND policy.content->'bootstrap_authorizations' @> jsonb_build_array(grant_scope.value)
            JOIN authority_operation generation
              ON generation.operation_id=payload.value->>'generation_operation_id'
              AND generation.project_id=operation.project_id
              AND generation.status IN ('WAITING_GATE','SUCCEEDED')
              AND generation.actor_id=payload.value->>'generation_actor_id'
              AND generation.actor_id<>operation.actor_id
            JOIN authority_operation_output_asset output ON output.operation_id=generation.operation_id
              AND output.asset_version_id=payload.value->>'candidate_asset_version_id'
              AND output.content_hash=payload.value->>'candidate_content_hash'
            JOIN authority_asset_version candidate ON candidate.asset_version_id=output.asset_version_id
              AND candidate.content_hash=output.content_hash AND candidate.governance='CLEAR'
              AND candidate.content->>'routing_eligibility'='BENCHMARK_ONLY'
            JOIN authority_asset candidate_asset ON candidate_asset.asset_id=candidate.asset_id
              AND candidate_asset.project_id=operation.project_id
            JOIN authority_asset_version labels ON labels.asset_version_id=payload.value #>> '{reference_evaluation,asset_version_id}'
              AND labels.content_hash=payload.value #>> '{reference_evaluation,content_hash}'
              AND labels.governance='CLEAR' AND labels.lifecycle='ACTIVE'
              AND labels.content->>'candidate_asset_version_id'=candidate.asset_version_id
              AND labels.content->>'candidate_content_hash'=candidate.content_hash
              AND labels.content->>'contract_version'='narrative-design-operator-review.v1'
              AND labels.content->'ground_truth_claimed'='false'::jsonb
              AND labels.content->'human_preference_evidence'='false'::jsonb
              AND labels.content->'provider_evidence_claimed'='false'::jsonb
            JOIN authority_asset labels_asset ON labels_asset.asset_id=labels.asset_id
              AND labels_asset.project_id=operation.project_id
              AND labels_asset.asset_type='narrative_design_operator_review'
            JOIN authority_operation_output_asset label_output ON label_output.asset_version_id=labels.asset_version_id
              AND label_output.content_hash=labels.content_hash
            JOIN authority_operation label_author ON label_author.operation_id=label_output.operation_id
              AND label_author.project_id=operation.project_id
              AND label_author.definition_name='story_design.review.author'
              AND label_author.status='SUCCEEDED'
              AND label_author.actor_id NOT IN (operation.actor_id,generation.actor_id)
              AND NOT EXISTS (SELECT 1 FROM authority_external_effect effect WHERE effect.operation_id=label_author.operation_id)
            WHERE operation.operation_id=p_operation_id AND operation.project_id=p_project_id
              AND operation.definition_name='story_design.semantic_evaluate' AND operation.definition_version='1.0.0'
              AND operation.idempotency_scope='book:narrative-semantic-evaluation'
              AND operation.idempotency_key=payload.value->>'idempotency_key'
              AND payload.value->>'evaluator_execution_class'='MODEL_PROVIDER'
              AND snapshot.value->>'project_id'=operation.project_id
              AND snapshot.value->>'environment'='validation'
              AND grant_scope.value->>'purpose'='REFERENCE_EVALUATION'
              AND grant_scope.value->>'environment'='validation'
              AND grant_scope.value->>'task_type'='narrative_semantic_evaluation'
              AND grant_scope.value->'production_eligible'='false'::jsonb
              AND jsonb_typeof(grant_scope.value->'campaign')='object'
              AND grant_scope.value->>'book_id'=payload.value->>'book_id'
              AND grant_scope.value->>'logical_key'=candidate.asset_version_id
              AND grant_scope.value->>'generation_idempotency_key'=operation.idempotency_key
              AND grant_scope.value->>'authorization_id'=payload.value->>'routing_bootstrap_authorization_id'
              AND grant_scope.value->'reference_evaluation'=payload.value->'reference_evaluation'
              AND COALESCE(payload.value->'opening_execution_binding','{}'::jsonb)='{}'::jsonb
              AND COALESCE(generation.command_payload #> '{payload,opening_execution_binding}','{}'::jsonb)='{}'::jsonb
        );
    $$
    """,
    """
    DO $migration$ DECLARE definition TEXT; anchor TEXT; addition TEXT;
    BEGIN
        SELECT pg_get_functiondef('authority_narrative_replacement_gate_is_open(text,text)'::regprocedure) INTO definition;
        anchor := E'        SELECT\n            execution.evaluation_execution_id,';
        IF (length(definition)-length(replace(definition,anchor,'')))/length(anchor)<>1 THEN
            RAISE EXCEPTION 'NARRATIVE_REFERENCE_GATE_ANCHOR_DRIFT';
        END IF;
        addition := E'        IF EXISTS (SELECT 1 FROM authority_operation WHERE operation_id=p_operation_id AND project_id=p_project_id AND command_payload->''payload'' ? ''reference_evaluation'') THEN\n'
            || E'            RETURN authority_narrative_reference_gate_is_open(p_operation_id,p_project_id);\n'
            || E'        END IF;\n';
        EXECUTE replace(definition,anchor,addition||anchor);
    END; $migration$
    """,
]

from __future__ import annotations

MIGRATION_ID = "20261009_0184_cli_original_reconciliation"
DOWN_REVISION = "20261008_0183_source_observation_span_identity"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Append original CLI reconciliation evidence without rewriting dispatches or settlements."

UPGRADE_STATEMENTS = [
    """CREATE UNIQUE INDEX authority_cli_original_reconciliation_once
    ON authority_effect_reconciliation_evidence(external_effect_id,(evidence->>'dispatch_id'))
    WHERE evidence->>'contract_version'='cli-original-reconciliation.v1'""",
    """CREATE FUNCTION authority_cli_original_reconciliation_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP<>'INSERT' THEN
            IF OLD.evidence->>'contract_version'='cli-original-reconciliation.v1'
                OR (TG_OP='UPDATE' AND NEW.evidence->>'contract_version'='cli-original-reconciliation.v1') THEN
                RAISE EXCEPTION 'Original CLI reconciliation evidence is immutable';
            END IF;
            IF TG_OP='DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END IF;
        IF NEW.evidence->>'contract_version' IS DISTINCT FROM 'cli-original-reconciliation.v1' THEN RETURN NEW; END IF;
        IF NEW.outcome NOT IN ('success','not_found','failed_final','cancelled')
            OR NEW.evidence->>'outcome' IS DISTINCT FROM NEW.outcome
            OR NOT EXISTS(SELECT 1 FROM authority_external_effect e
                JOIN authority_external_effect_dispatch d USING(external_effect_id)
                JOIN authority_budget_reservation b ON b.external_effect_id=e.external_effect_id AND b.project_id=e.project_id
                JOIN authority_asset_version v ON ('authority-asset-version:'||v.asset_version_id)=NEW.evidence->>'original_remote_receipt_ref'
                JOIN authority_asset a ON a.asset_id=v.asset_id AND a.project_id=e.project_id
                WHERE e.external_effect_id=NEW.external_effect_id
                  AND NEW.provider=e.provider AND NEW.stable_idempotency_key=e.stable_idempotency_key
                  AND NEW.evidence->>'project_id'=e.project_id AND NEW.evidence->>'operation_id'=e.operation_id
                  AND NEW.evidence->>'dispatch_id'=d.dispatch_id AND NEW.evidence->>'generation'=d.generation::text
                  AND NEW.evidence->>'request_hash'=e.request_hash AND d.payload_hash=e.request_hash
                  AND d.evidence#>>'{production_execution,execution_handle,transport}'='LOCAL_CLI_REMOTE_INFERENCE'
                  AND NULLIF(d.evidence#>>'{production_execution,execution_result,usage_receipt_ref}','') IS NULL
                  AND NEW.evidence#>>'{budget_correction,reservation_id}'=b.reservation_id
                  AND NEW.evidence#>>'{budget_correction,original_actual_tokens}'=b.actual_tokens::text
                  AND NEW.evidence#>>'{budget_correction,accounting_basis}'=b.accounting_basis
                  AND NEW.evidence#>>'{budget_correction,actual_tokens}'=v.content#>>'{usage,total_tokens}'
                  AND b.accounting_basis='ACCOUNT_ENTITLEMENT'
                  AND ((b.status='SETTLED' AND b.evidence->'measurement_available'='false'::jsonb
                    AND NEW.evidence#>>'{budget_correction,mode}'='APPEND_CORRECTION')
                    OR (b.status='HELD_UNKNOWN' AND NEW.evidence#>>'{budget_correction,mode}'='HELD_SETTLEMENT'))
                  AND a.asset_type='cli_remote_receipt' AND v.schema_version='cli-remote-receipt.v1'
                  AND v.governance='CLEAR' AND v.eligibility='ELIGIBLE'
                  AND v.content->>'contract_version'='cli-remote-receipt.v1'
                  AND v.content->>'outcome'=NEW.outcome
                  AND v.content->>'verified_by'=NEW.evidence->>'verified_by') THEN
            RAISE EXCEPTION 'Original CLI reconciliation identity or usage differs';
        END IF;
        RETURN NEW;
    END $$""",
    """CREATE TRIGGER authority_cli_original_reconciliation_guard
    BEFORE INSERT OR UPDATE OR DELETE ON authority_effect_reconciliation_evidence
    FOR EACH ROW EXECUTE FUNCTION authority_cli_original_reconciliation_guard()""",
    r"""CREATE OR REPLACE FUNCTION authority_planning_cli_lineage_reconciled(source_id TEXT)
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
]

DOWNGRADE_STATEMENTS: list[str] = []

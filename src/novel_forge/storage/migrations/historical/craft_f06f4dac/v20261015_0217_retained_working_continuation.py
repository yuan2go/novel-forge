from __future__ import annotations

MIGRATION_ID = "20261015_0217_retained_working_continuation"
DOWN_REVISION = "20261015_0216_chapter_method_context"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Keep permission-failed Writer history immutable; append explicit unaccepted working-use evidence without a successful Draft or Canon mutation."

UPGRADE_STATEMENTS = [
    """CREATE TABLE authority_book_retained_working_continuation (
        book_run_id TEXT NOT NULL REFERENCES authority_book_production(book_run_id),
        chapter_request_id TEXT NOT NULL UNIQUE REFERENCES authority_book_chapter_request(chapter_request_id),
        chapter_number INTEGER NOT NULL CHECK(chapter_number>0),
        source_candidate_asset_version_id TEXT NOT NULL UNIQUE REFERENCES authority_asset_version(asset_version_id),
        source_candidate_content_hash TEXT NOT NULL,
        working_asset_version_id TEXT NOT NULL UNIQUE REFERENCES authority_asset_version(asset_version_id),
        working_content_hash TEXT NOT NULL,
        context_snapshot JSONB NOT NULL CHECK(context_snapshot->>'version'='working-manuscript-context.v1'),
        proof JSONB NOT NULL CHECK(proof->>'contract_version'='retained-working-continuation.v1'
            AND proof->>'source_permission_gate'='FAILED_FINAL' AND proof->>'qualification'='WORKING_USE_ONLY'
            AND proof->>'formal_acceptance'='NOT_GRANTED' AND proof->>'author_acceptance'='NOT_GRANTED'
            AND proof->>'provider_calls'='0'),
        created_by_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY(book_run_id,chapter_number)
    )""",
    """CREATE FUNCTION authority_book_retained_working_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Retained working continuation evidence is immutable'; END IF;
      IF NOT EXISTS(SELECT 1 FROM authority_book_production b
        JOIN authority_book_chapter_request r ON r.chapter_request_id=NEW.chapter_request_id AND r.book_run_id=b.book_run_id
        JOIN authority_asset_version candidate ON candidate.asset_version_id=NEW.source_candidate_asset_version_id
        JOIN authority_asset a ON a.asset_id=candidate.asset_id AND a.project_id=b.project_id AND a.asset_type='execution_evidence'
        JOIN authority_operation_output_asset original ON original.asset_version_id=candidate.asset_version_id
        JOIN authority_operation source ON source.operation_id=original.operation_id AND source.root_operation_id=r.chapter_root_operation_id
        JOIN authority_operation root ON root.operation_id=r.chapter_root_operation_id
        JOIN authority_attempt attempt ON attempt.operation_id=source.operation_id AND attempt.attempt_id=NEW.proof->>'source_attempt_id'
        JOIN authority_external_effect effect ON effect.operation_id=source.operation_id AND effect.external_effect_id=NEW.proof->>'source_external_effect_id'
        JOIN authority_budget_reservation budget USING(external_effect_id)
        JOIN authority_asset_version working ON working.asset_version_id=NEW.working_asset_version_id
        JOIN authority_asset w ON w.asset_id=working.asset_id AND w.project_id=b.project_id AND w.asset_type='retained_working_prose'
        JOIN authority_operation_output_asset output ON output.asset_version_id=working.asset_version_id AND output.operation_id=NEW.created_by_operation_id
        JOIN authority_operation owner ON owner.operation_id=NEW.created_by_operation_id
        JOIN authority_asset_version profile ON profile.asset_version_id=b.production_profile_version
        WHERE b.book_run_id=NEW.book_run_id AND b.current_chapter=NEW.chapter_number-1
        AND b.active_chapter_request_id=NEW.chapter_request_id AND r.chapter_number=NEW.chapter_number
        AND b.state IN ('CHAPTER_RUNNING','CHAPTER_SUBMITTED','CHAPTER_WAITING_RETRY') AND r.status_reference<>'CANCELLED'
        AND NOT EXISTS(SELECT 1 FROM authority_story_creation_cancellation c
            WHERE c.project_id=b.project_id AND b.stable_idempotency_key=c.formation_run_id || ':production')
        AND NOT EXISTS(SELECT 1 FROM authority_worker_cancel_signal signal
            WHERE signal.operation_id IN (root.operation_id,source.operation_id,b.root_operation_id) AND signal.acknowledged_at IS NULL)
        AND candidate.governance='CLEAR' AND candidate.eligibility='ELIGIBLE'
        AND candidate.lifecycle IN ('ACTIVE','SUPERSEDED')
        AND root.definition_version='3.10.0-author-first.v1' AND root.status='WAITING_CHILDREN'
        AND profile.content#>>'{knowledge_access_policy,usage_scope}'='EXPERIMENTAL_VALIDATION'
        AND source.definition_name='chapter.draft.generate' AND source.status='FAILED_FINAL'
        AND source.actor_id=owner.actor_id AND source.project_id=owner.project_id AND source.workspace_id=owner.workspace_id
        AND source.command_payload->>'book_id'=b.book_id
        AND attempt.status='FAILED_FINAL' AND attempt.result->>'error_code'='MODEL_EFFECT_FINAL_UNAUTHORIZED_TOOL_INVOCATION'
        AND effect.status='FAILED_FINAL' AND budget.status='SETTLED'
        AND (SELECT count(*) FROM authority_external_effect WHERE operation_id=source.operation_id)=1
        AND candidate.content_hash=NEW.source_candidate_content_hash AND candidate.content->>'kind'='prose-candidate'
        AND candidate.content#>>'{payload,completeness}'='COMPLETE_SOURCE_PROSE'
        AND candidate.content#>>'{payload,selection_status}'='NOT_SELECTED'
        AND candidate.content#>>'{payload,acceptance_status}'='NOT_ACCEPTED'
        AND candidate.content#>>'{payload,external_effect_id}'=effect.external_effect_id
        AND candidate.content#>>'{payload,text_sha256}'=NEW.proof->>'text_sha256'
        AND working.content_hash=NEW.working_content_hash AND working.content->>'contract_version'='retained-working-continuation.v1'
        AND working.content->>'book_id'=b.book_id AND working.content->>'project_id'=b.project_id
        AND working.content->>'chapter'=NEW.chapter_number::text
        AND working.content->>'text'=candidate.content#>>'{payload,text}'
        AND working.content->'retained_working_provenance'=NEW.proof
        AND NEW.proof->>'source_operation_id'=source.operation_id
        AND NEW.proof->>'source_candidate_asset_version_id'=candidate.asset_version_id
        AND NEW.proof->>'source_candidate_content_hash'=candidate.content_hash
        AND NEW.proof#>>'{discovery_trace,external_resource_count}'='0'
        AND NEW.proof#>>'{discovery_trace,contract_version}'='empty-metadata-discovery-evidence.v1'
        AND jsonb_array_length(NEW.proof#>'{discovery_trace,calls}')=2
        AND owner.definition_name='book.authority.mutate' AND owner.project_id=b.project_id AND owner.workspace_id=b.workspace_id
        AND owner.command_payload#>>'{payload,action}'='retained_working_continue'
        AND NEW.context_snapshot->>'book_run_id'=b.book_run_id AND NEW.context_snapshot->>'project_id'=b.project_id
        AND NOT EXISTS(SELECT 1 FROM authority_lease_acquisition lease JOIN authority_attempt a USING(attempt_id)
            JOIN authority_operation o USING(operation_id) WHERE o.root_operation_id=root.operation_id AND lease.status='HELD')
      ) THEN RAISE EXCEPTION 'Retained working continuation requires exact unaccepted original and failed permission evidence'; END IF;
      RETURN NEW;
    END $$""",
    """CREATE TRIGGER authority_book_retained_working_guard BEFORE INSERT OR UPDATE OR DELETE
        ON authority_book_retained_working_continuation FOR EACH ROW EXECUTE FUNCTION authority_book_retained_working_guard()""",
]
DOWNGRADE_STATEMENTS: list[str] = []

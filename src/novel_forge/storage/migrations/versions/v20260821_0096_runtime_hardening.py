from __future__ import annotations


MIGRATION_ID = "20260821_0096_runtime_hardening"
DOWN_REVISION = "20260821_0095_post_merge_correctness_repair"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = (
    "Preserve accepted narrative truth. Reconcile Arc follow-up terminal states, "
    "unknown embedding effects, frozen Agent execution, and semantic retrieval "
    "through their existing Authorities and durable runtime records."
)


UPGRADE_STATEMENTS = [
    "CREATE EXTENSION IF NOT EXISTS vector",
    """
    ALTER TABLE authority_agent_harness_session
    ADD COLUMN execution_contract JSONB NOT NULL DEFAULT '{}'::jsonb
    """,
    """
    ALTER TABLE authority_agent_harness_session
    ADD COLUMN execution_contract_hash TEXT NOT NULL DEFAULT '' CHECK (
        execution_contract_hash = '' OR
        execution_contract_hash ~ '^sha256:[0-9a-f]{64}$'
    )
    """,
    """
    ALTER TABLE authority_agent_harness_session
    ADD CONSTRAINT authority_agent_harness_execution_contract_identity_check
    CHECK (
        (execution_contract = '{}'::jsonb AND execution_contract_hash = '') OR
        (execution_contract <> '{}'::jsonb AND execution_contract_hash <> '')
    )
    """,
    """
    ALTER TABLE authority_arc_checkpoint_followup
    DROP CONSTRAINT authority_arc_checkpoint_followup_status_check
    """,
    """
    ALTER TABLE authority_arc_checkpoint_followup
    ADD CONSTRAINT authority_arc_checkpoint_followup_status_check CHECK (
        status IN (
            'READY','RUNNING','PROPOSED','WAITING_APPROVAL','COMPLETED',
            'FAILED_RETRYABLE','FAILED_FINAL','DEAD_LETTER','CANCELLED',
            'RECONCILIATION_REQUIRED','MANUAL_INTERVENTION'
        )
    )
    """,
    """
    ALTER TABLE authority_retrieval_embedding_projection
    DROP CONSTRAINT authority_retrieval_embedding_projection_status_check
    """,
    """
    UPDATE authority_retrieval_embedding_projection
    SET status='FAILED_FINAL', version=version+1, updated_at=NOW(),
        evidence=evidence || '{"migration":"FAILED_TERMINAL_TO_FAILED_FINAL"}'::jsonb
    WHERE status='FAILED_TERMINAL'
    """,
    """
    ALTER TABLE authority_retrieval_embedding_projection
    ADD CONSTRAINT authority_retrieval_embedding_projection_status_check CHECK (
        status IN (
            'PENDING','RUNNING','READY','FAILED_RETRYABLE','FAILED_FINAL',
            'DEAD_LETTER','CANCELLED','RECONCILIATION_REQUIRED'
        )
    )
    """,
    """
    ALTER TABLE authority_retrieval_embedding_projection
    ADD COLUMN embedding_vector vector
    """,
    """
    UPDATE authority_retrieval_embedding_projection
    SET embedding_vector=embedding::text::vector
    WHERE embedding IS NOT NULL
    """,
    """
    ALTER TABLE authority_retrieval_embedding_projection
    ADD CONSTRAINT authority_retrieval_embedding_vector_check CHECK (
        (embedding_vector IS NULL AND status<>'READY') OR
        (embedding_vector IS NOT NULL
         AND vector_dims(embedding_vector)=embedding_dimensions)
    )
    """,
    """
    CREATE INDEX authority_retrieval_embedding_governed_vector_idx
    ON authority_retrieval_embedding_projection(
        project_id, book_id, embedding_model, embedding_dimensions,
        projection_version, status
    ) WHERE status='READY' AND embedding_vector IS NOT NULL
    """,
    """
    CREATE INDEX authority_retrieval_embedding_vector_1024_hnsw_idx
    ON authority_retrieval_embedding_projection
    USING hnsw ((embedding_vector::vector(1024)) vector_cosine_ops)
    WHERE status='READY' AND embedding_dimensions=1024
    """,
    """
    CREATE INDEX authority_retrieval_embedding_vector_1536_hnsw_idx
    ON authority_retrieval_embedding_projection
    USING hnsw ((embedding_vector::vector(1536)) vector_cosine_ops)
    WHERE status='READY' AND embedding_dimensions=1536
    """,
    """
    CREATE INDEX authority_retrieval_embedding_vector_3072_hnsw_idx
    ON authority_retrieval_embedding_projection
    USING hnsw ((embedding_vector::halfvec(3072)) halfvec_cosine_ops)
    WHERE status='READY' AND embedding_dimensions=3072
    """,
    """
    CREATE TABLE authority_retrieval_candidate_snapshot (
        candidate_snapshot_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        operation_id TEXT NOT NULL UNIQUE
            REFERENCES authority_operation(operation_id),
        attempt_id TEXT NOT NULL,
        fencing_token BIGINT NOT NULL CHECK (fencing_token > 0),
        query_plan_fingerprint TEXT NOT NULL CHECK (
            query_plan_fingerprint ~ '^sha256:[0-9a-f]{64}$'
        ),
        candidate_projection_cutoff TIMESTAMPTZ NOT NULL,
        ranking_policy_version TEXT NOT NULL,
        query_embedding JSONB NOT NULL DEFAULT '[]'::jsonb,
        query_embedding_model TEXT NOT NULL DEFAULT '',
        query_embedding_dimensions INTEGER CHECK (
            query_embedding_dimensions IS NULL OR query_embedding_dimensions > 0
        ),
        query_embedding_evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
        candidate_asset_versions JSONB NOT NULL,
        documents JSONB NOT NULL,
        semantic_status JSONB NOT NULL,
        snapshot_hash TEXT NOT NULL CHECK (
            snapshot_hash ~ '^sha256:[0-9a-f]{64}$'
        ),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        FOREIGN KEY(attempt_id, operation_id)
            REFERENCES authority_attempt(attempt_id, operation_id),
        FOREIGN KEY(attempt_id, fencing_token)
            REFERENCES authority_lease_acquisition(attempt_id, fencing_token),
        CHECK (
            (query_embedding='[]'::jsonb AND query_embedding_model=''
             AND query_embedding_dimensions IS NULL) OR
            (query_embedding<>'[]'::jsonb AND query_embedding_model<>''
             AND query_embedding_dimensions IS NOT NULL)
        )
    )
    """,
    """
    CREATE INDEX authority_retrieval_candidate_snapshot_scope_idx
    ON authority_retrieval_candidate_snapshot(project_id, book_id, created_at)
    """,
    """
    CREATE FUNCTION authority_retrieval_candidate_snapshot_guard()
    RETURNS TRIGGER AS $$
    DECLARE
        operation_project_id TEXT;
    BEGIN
        IF TG_OP <> 'INSERT' THEN
            RAISE EXCEPTION 'retrieval candidate snapshots are immutable'
                USING ERRCODE='23514',
                      CONSTRAINT='authority_retrieval_candidate_snapshot_immutable';
        END IF;
        SELECT project_id INTO operation_project_id
        FROM authority_operation WHERE operation_id=NEW.operation_id;
        IF operation_project_id IS NULL
           OR operation_project_id<>NEW.project_id THEN
            RAISE EXCEPTION 'candidate snapshot Project differs from Operation'
                USING ERRCODE='23514',
                      CONSTRAINT='authority_retrieval_candidate_snapshot_scope';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE TRIGGER authority_retrieval_candidate_snapshot_guard_trigger
    BEFORE INSERT OR UPDATE OR DELETE
    ON authority_retrieval_candidate_snapshot
    FOR EACH ROW EXECUTE FUNCTION authority_retrieval_candidate_snapshot_guard()
    """,
]


DOWNGRADE_STATEMENTS: list[str] = []


__all__ = [
    "BACKUP_REQUIRED",
    "DOWN_REVISION",
    "FORWARD_FIX",
    "FORWARD_ONLY",
    "MIGRATION_ID",
    "UPGRADE_STATEMENTS",
]

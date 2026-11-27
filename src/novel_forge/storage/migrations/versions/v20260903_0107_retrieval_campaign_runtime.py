from __future__ import annotations


MIGRATION_ID = "20260903_0107_retrieval_campaign_runtime"
DOWN_REVISION = "20260902_0106_quality_qualification_scope_generalization"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = "append replacement retrieval campaign evidence; frozen round snapshots remain immutable"


UPGRADE_STATEMENTS = [
    """
    CREATE TABLE authority_retrieval_campaign (
        campaign_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        operation_id TEXT NOT NULL UNIQUE
            REFERENCES authority_operation(operation_id),
        attempt_id TEXT NOT NULL,
        fencing_token BIGINT NOT NULL CHECK (fencing_token > 0),
        chapter INTEGER NOT NULL CHECK (chapter > 0),
        accepted_through_chapter INTEGER NOT NULL
            CHECK (accepted_through_chapter >= 0),
        accepted_boundary JSONB NOT NULL,
        intent_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        memo_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        intent_fingerprint TEXT NOT NULL CHECK (
            intent_fingerprint ~ '^sha256:[0-9a-f]{64}$'
        ),
        memo_fingerprint TEXT NOT NULL CHECK (
            memo_fingerprint ~ '^sha256:[0-9a-f]{64}$'
        ),
        policy_version TEXT NOT NULL,
        policy JSONB NOT NULL,
        coverage_contract JSONB NOT NULL,
        input_fingerprint TEXT NOT NULL CHECK (
            input_fingerprint ~ '^sha256:[0-9a-f]{64}$'
        ),
        status TEXT NOT NULL DEFAULT 'RUNNING' CHECK (
            status IN ('RUNNING','COMPLETED','FALLBACK','FAILED')
        ),
        termination_reason TEXT NOT NULL DEFAULT '' CHECK (
            termination_reason IN (
                '', 'REQUIRED_EVIDENCE_SATISFIED', 'MAX_ROUNDS_REACHED',
                'QUERY_BUDGET_EXHAUSTED', 'MODEL_BUDGET_EXHAUSTED',
                'NO_NOVEL_QUERY', 'NO_NEW_EVIDENCE', 'POLICY_BLOCKED',
                'DETERMINISTIC_FALLBACK'
            )
        ),
        final_result_fingerprint TEXT CHECK (
            final_result_fingerprint IS NULL OR
            final_result_fingerprint ~ '^sha256:[0-9a-f]{64}$'
        ),
        final_evidence_identity TEXT CHECK (
            final_evidence_identity IS NULL OR
            final_evidence_identity ~ '^sha256:[0-9a-f]{64}$'
        ),
        version BIGINT NOT NULL DEFAULT 1 CHECK (version > 0),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        FOREIGN KEY(attempt_id, operation_id)
            REFERENCES authority_attempt(attempt_id, operation_id),
        FOREIGN KEY(attempt_id, fencing_token)
            REFERENCES authority_lease_acquisition(attempt_id, fencing_token),
        UNIQUE(campaign_id, project_id, book_id, operation_id),
        CHECK (
            (status='RUNNING' AND termination_reason=''
             AND final_result_fingerprint IS NULL
             AND final_evidence_identity IS NULL) OR
            (status<>'RUNNING' AND termination_reason<>''
             AND final_result_fingerprint IS NOT NULL
             AND final_evidence_identity IS NOT NULL)
        )
    )
    """,
    """
    CREATE TABLE authority_retrieval_round (
        round_id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL
            REFERENCES authority_retrieval_campaign(campaign_id),
        project_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        attempt_id TEXT NOT NULL,
        fencing_token BIGINT NOT NULL CHECK (fencing_token > 0),
        round_number INTEGER NOT NULL CHECK (round_number BETWEEN 0 AND 2),
        accepted_through_chapter INTEGER NOT NULL
            CHECK (accepted_through_chapter >= 0),
        query_plan JSONB NOT NULL,
        query_plan_fingerprint TEXT NOT NULL CHECK (
            query_plan_fingerprint ~ '^sha256:[0-9a-f]{64}$'
        ),
        expansion_plan JSONB NOT NULL DEFAULT '{}'::jsonb,
        expansion_plan_fingerprint TEXT NOT NULL DEFAULT '' CHECK (
            expansion_plan_fingerprint='' OR
            expansion_plan_fingerprint ~ '^sha256:[0-9a-f]{64}$'
        ),
        expansion_reason TEXT NOT NULL DEFAULT '',
        provider_evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
        external_effect_id TEXT REFERENCES authority_external_effect(external_effect_id),
        candidate_projection_cutoff TIMESTAMPTZ NOT NULL,
        candidate_asset_versions JSONB NOT NULL,
        documents JSONB NOT NULL,
        rejected_documents JSONB NOT NULL,
        semantic_status JSONB NOT NULL,
        coverage_before JSONB NOT NULL,
        coverage_after JSONB NOT NULL,
        new_evidence_count INTEGER NOT NULL CHECK (new_evidence_count >= 0),
        input_tokens INTEGER NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
        output_tokens INTEGER NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
        cost_amount NUMERIC(18,8) NOT NULL DEFAULT 0 CHECK (cost_amount >= 0),
        currency TEXT NOT NULL DEFAULT 'USD',
        latency_ms INTEGER NOT NULL DEFAULT 0 CHECK (latency_ms >= 0),
        snapshot_hash TEXT NOT NULL CHECK (
            snapshot_hash ~ '^sha256:[0-9a-f]{64}$'
        ),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(campaign_id, round_number),
        UNIQUE(campaign_id, query_plan_fingerprint),
        FOREIGN KEY(campaign_id, project_id, book_id, operation_id)
            REFERENCES authority_retrieval_campaign(
                campaign_id, project_id, book_id, operation_id
            ),
        FOREIGN KEY(attempt_id, operation_id)
            REFERENCES authority_attempt(attempt_id, operation_id),
        FOREIGN KEY(attempt_id, fencing_token)
            REFERENCES authority_lease_acquisition(attempt_id, fencing_token),
        CHECK (
            (round_number=0 AND expansion_plan='{}'::jsonb
             AND expansion_plan_fingerprint='' AND expansion_reason='') OR
            (round_number>0 AND expansion_plan<>'{}'::jsonb
             AND expansion_plan_fingerprint<>'' AND expansion_reason<>'')
        )
    )
    """,
    """
    CREATE INDEX authority_retrieval_round_campaign_idx
    ON authority_retrieval_round(campaign_id, round_number)
    """,
    """
    CREATE INDEX authority_retrieval_campaign_scope_idx
    ON authority_retrieval_campaign(
        project_id, book_id, accepted_through_chapter, created_at DESC
    )
    """,
    """
    CREATE INDEX authority_retrieval_campaign_intent_fk_idx
    ON authority_retrieval_campaign(intent_asset_version_id)
    """,
    """
    CREATE INDEX authority_retrieval_campaign_memo_fk_idx
    ON authority_retrieval_campaign(memo_asset_version_id)
    """,
    """
    CREATE INDEX authority_retrieval_campaign_attempt_operation_fk_idx
    ON authority_retrieval_campaign(attempt_id, operation_id)
    """,
    """
    CREATE INDEX authority_retrieval_campaign_attempt_fence_fk_idx
    ON authority_retrieval_campaign(attempt_id, fencing_token)
    """,
    """
    CREATE INDEX authority_retrieval_round_operation_fk_idx
    ON authority_retrieval_round(operation_id)
    """,
    """
    CREATE INDEX authority_retrieval_round_effect_fk_idx
    ON authority_retrieval_round(external_effect_id)
    """,
    """
    CREATE INDEX authority_retrieval_round_campaign_scope_fk_idx
    ON authority_retrieval_round(campaign_id, project_id, book_id, operation_id)
    """,
    """
    CREATE INDEX authority_retrieval_round_attempt_operation_fk_idx
    ON authority_retrieval_round(attempt_id, operation_id)
    """,
    """
    CREATE INDEX authority_retrieval_round_attempt_fence_fk_idx
    ON authority_retrieval_round(attempt_id, fencing_token)
    """,
    """
    WITH validity AS (
        SELECT retrieval_document_id,
               MIN(accepted_from_chapter) OVER (
                   PARTITION BY project_id, book_id, memory_layer
                   ORDER BY accepted_from_chapter
                   GROUPS BETWEEN 1 FOLLOWING AND 1 FOLLOWING
               ) AS next_accepted_chapter
        FROM authority_narrative_retrieval_document
        WHERE memory_layer IN ('L1','L2','L4','L5')
    )
    UPDATE authority_narrative_retrieval_document AS document
    SET accepted_to_chapter=validity.next_accepted_chapter-1
    FROM validity
    WHERE document.retrieval_document_id=validity.retrieval_document_id
      AND document.accepted_to_chapter IS NULL
      AND validity.next_accepted_chapter IS NOT NULL
    """,
    """
    CREATE INDEX authority_narrative_retrieval_scope_boundary_idx
    ON authority_narrative_retrieval_document(
        project_id, book_id, accepted_from_chapter DESC, retrieval_document_id
    ) INCLUDE (
        accepted_to_chapter, source_asset_version_id, memory_layer, projection_hash
    )
    """,
    """
    CREATE INDEX authority_narrative_retrieval_active_to_idx
    ON authority_narrative_retrieval_document(
        project_id, book_id, accepted_to_chapter, accepted_from_chapter DESC
    ) WHERE accepted_to_chapter IS NOT NULL
    """,
    """
    CREATE INDEX authority_narrative_retrieval_entity_gin_idx
    ON authority_narrative_retrieval_document USING GIN(entity_ids)
    """,
    """
    CREATE INDEX authority_narrative_retrieval_relationship_gin_idx
    ON authority_narrative_retrieval_document USING GIN(relationship_ids)
    """,
    """
    CREATE INDEX authority_narrative_retrieval_character_gin_idx
    ON authority_narrative_retrieval_document USING GIN(character_ids)
    """,
    """
    CREATE INDEX authority_narrative_retrieval_arc_gin_idx
    ON authority_narrative_retrieval_document USING GIN(arc_plan_version_ids)
    """,
    """
    CREATE INDEX authority_narrative_retrieval_obligation_gin_idx
    ON authority_narrative_retrieval_document USING GIN(obligation_ids)
    """,
    """
    CREATE FUNCTION authority_retrieval_campaign_scope_guard()
    RETURNS TRIGGER AS $$
    DECLARE
        operation_project TEXT;
        intent_project TEXT;
        memo_project TEXT;
    BEGIN
        SELECT project_id INTO operation_project
        FROM authority_operation WHERE operation_id=NEW.operation_id;
        SELECT asset.project_id INTO intent_project
        FROM authority_asset_version AS version
        JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
        WHERE version.asset_version_id=NEW.intent_asset_version_id;
        SELECT asset.project_id INTO memo_project
        FROM authority_asset_version AS version
        JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
        WHERE version.asset_version_id=NEW.memo_asset_version_id;
        IF operation_project IS DISTINCT FROM NEW.project_id
           OR intent_project IS DISTINCT FROM NEW.project_id
           OR memo_project IS DISTINCT FROM NEW.project_id
           OR COALESCE(
               (NEW.accepted_boundary->>'accepted_through_chapter')::INTEGER,
               -1
           ) <> NEW.accepted_through_chapter
           OR NEW.coverage_contract->'accepted_boundary'
              IS DISTINCT FROM NEW.accepted_boundary THEN
            RAISE EXCEPTION 'retrieval campaign scope differs from frozen inputs'
                USING ERRCODE='23514',
                      CONSTRAINT='authority_retrieval_campaign_scope';
        END IF;
        IF TG_OP='UPDATE' AND OLD.status<>'RUNNING' THEN
            RAISE EXCEPTION 'terminal retrieval campaigns are immutable'
                USING ERRCODE='23514',
                      CONSTRAINT='authority_retrieval_campaign_terminal_immutable';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE TRIGGER authority_retrieval_campaign_scope_guard_trigger
    BEFORE INSERT OR UPDATE ON authority_retrieval_campaign
    FOR EACH ROW EXECUTE FUNCTION authority_retrieval_campaign_scope_guard()
    """,
    """
    CREATE FUNCTION authority_retrieval_round_guard()
    RETURNS TRIGGER AS $$
    DECLARE
        campaign_status TEXT;
        campaign_project TEXT;
        campaign_book TEXT;
        campaign_operation TEXT;
        campaign_boundary INTEGER;
        campaign_boundary_json JSONB;
        round_zero_cutoff TIMESTAMPTZ;
        prior_round_exists BOOLEAN;
        effect_operation TEXT;
    BEGIN
        IF TG_OP <> 'INSERT' THEN
            RAISE EXCEPTION 'retrieval round snapshots are immutable'
                USING ERRCODE='23514',
                      CONSTRAINT='authority_retrieval_round_immutable';
        END IF;
        SELECT status, project_id, book_id, operation_id,
               accepted_through_chapter, accepted_boundary
          INTO campaign_status, campaign_project, campaign_book,
               campaign_operation, campaign_boundary, campaign_boundary_json
        FROM authority_retrieval_campaign
        WHERE campaign_id=NEW.campaign_id
        FOR UPDATE;
        IF campaign_status IS DISTINCT FROM 'RUNNING'
           OR campaign_project IS DISTINCT FROM NEW.project_id
           OR campaign_book IS DISTINCT FROM NEW.book_id
           OR campaign_operation IS DISTINCT FROM NEW.operation_id
           OR campaign_boundary IS DISTINCT FROM NEW.accepted_through_chapter
           OR NEW.query_plan->'accepted_boundary'
              IS DISTINCT FROM campaign_boundary_json THEN
            RAISE EXCEPTION 'retrieval round differs from its running campaign'
                USING ERRCODE='23514',
                      CONSTRAINT='authority_retrieval_round_scope';
        END IF;
        IF NEW.round_number > 0 THEN
            SELECT EXISTS(
                SELECT 1 FROM authority_retrieval_round
                WHERE campaign_id=NEW.campaign_id
                  AND round_number=NEW.round_number-1
            ) INTO prior_round_exists;
            SELECT candidate_projection_cutoff INTO round_zero_cutoff
            FROM authority_retrieval_round
            WHERE campaign_id=NEW.campaign_id AND round_number=0;
            IF NOT prior_round_exists
               OR round_zero_cutoff IS DISTINCT FROM NEW.candidate_projection_cutoff THEN
                RAISE EXCEPTION 'retrieval rounds must be consecutive at one cutoff'
                    USING ERRCODE='23514',
                          CONSTRAINT='authority_retrieval_round_sequence';
            END IF;
        END IF;
        IF NEW.external_effect_id IS NOT NULL THEN
            SELECT operation_id INTO effect_operation
            FROM authority_external_effect
            WHERE external_effect_id=NEW.external_effect_id;
            IF effect_operation IS DISTINCT FROM NEW.operation_id THEN
                RAISE EXCEPTION 'retrieval round effect belongs to another operation'
                    USING ERRCODE='23514',
                          CONSTRAINT='authority_retrieval_round_effect_scope';
            END IF;
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE TRIGGER authority_retrieval_round_guard_trigger
    BEFORE INSERT OR UPDATE OR DELETE ON authority_retrieval_round
    FOR EACH ROW EXECUTE FUNCTION authority_retrieval_round_guard()
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

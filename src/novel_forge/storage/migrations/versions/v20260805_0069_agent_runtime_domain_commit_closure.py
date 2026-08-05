from __future__ import annotations


MIGRATION_ID = "20260805_0069_agent_runtime_domain_commit_closure"
DOWN_REVISION = "20260805_0068_unified_agent_runtime"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = (
    "Repair an exact collaboration commit by validating the existing Domain "
    "AssetVersion and replaying only Decision/Commit finalization. Never rerun "
    "the Provider when ExternalEffect delivery is uncertain."
)


UPGRADE_STATEMENTS = [
    """
    ALTER TABLE authority_agent_collaboration_commit
    ADD COLUMN attempt_id TEXT REFERENCES authority_attempt(attempt_id),
    ADD COLUMN fencing_token BIGINT,
    ADD COLUMN content_hash TEXT
    """,
    """
    ALTER TABLE authority_agent_collaboration_commit
    ADD CONSTRAINT authority_agent_commit_exact_lineage_complete
    CHECK (
        (attempt_id IS NULL AND fencing_token IS NULL AND content_hash IS NULL)
        OR
        (attempt_id IS NOT NULL AND fencing_token > 0
         AND content_hash ~ '^sha256:[0-9a-f]{64}$')
    )
    """,
    """
    CREATE UNIQUE INDEX authority_agent_commit_candidate_unique
    ON authority_agent_collaboration_commit(candidate_version_id)
    """,
    """
    CREATE UNIQUE INDEX authority_agent_commit_attempt_fence_asset_unique
    ON authority_agent_collaboration_commit(
        attempt_id, fencing_token, asset_version_id
    ) WHERE attempt_id IS NOT NULL
    """,
    """
    CREATE UNIQUE INDEX authority_agent_commit_exact_asset_unique
    ON authority_agent_collaboration_commit(asset_version_id)
    WHERE attempt_id IS NOT NULL
    """,
    """
    CREATE OR REPLACE FUNCTION authority_agent_exact_commit_guard()
    RETURNS TRIGGER AS $$
    DECLARE
        attempt_operation TEXT;
        output_hash TEXT;
        fence_exists BOOLEAN;
        candidate_session TEXT;
        candidate_operation TEXT;
        candidate_attempt TEXT;
        operation_project TEXT;
        session_project TEXT;
        asset_project TEXT;
    BEGIN
        IF NEW.attempt_id IS NULL THEN
            RETURN NEW;
        END IF;
        SELECT operation_id INTO attempt_operation
        FROM authority_attempt WHERE attempt_id=NEW.attempt_id;
        SELECT output.content_hash, asset.project_id
        INTO output_hash, asset_project
        FROM authority_operation_output_asset AS output
        JOIN authority_asset_version AS version
          ON version.asset_version_id=output.asset_version_id
        JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
        WHERE output.operation_id=NEW.operation_id
          AND output.asset_version_id=NEW.asset_version_id;
        SELECT project_id INTO operation_project
        FROM authority_operation WHERE operation_id=NEW.operation_id;
        SELECT EXISTS(
            SELECT 1 FROM authority_lease_acquisition
            WHERE attempt_id=NEW.attempt_id
              AND fencing_token=NEW.fencing_token
              AND status='HELD'
        ) INTO fence_exists;
        SELECT candidate.session_id, work_order.operation_id,
               work_order.attempt_id
        INTO candidate_session, candidate_operation, candidate_attempt
        FROM authority_agent_candidate_version AS candidate
        JOIN authority_agent_work_order AS work_order
          ON work_order.turn_id=candidate.originating_turn_id
        WHERE candidate.candidate_version_id=NEW.candidate_version_id;
        SELECT project_id INTO session_project
        FROM authority_agent_collaboration_session
        WHERE session_id=NEW.session_id;
        IF attempt_operation IS DISTINCT FROM NEW.operation_id
           OR candidate_operation IS DISTINCT FROM NEW.operation_id
           OR candidate_attempt IS DISTINCT FROM NEW.attempt_id
           OR output_hash IS DISTINCT FROM NEW.content_hash
           OR NOT fence_exists
           OR candidate_session IS DISTINCT FROM NEW.session_id
           OR operation_project IS DISTINCT FROM session_project
           OR operation_project IS DISTINCT FROM asset_project THEN
            RAISE EXCEPTION 'exact Agent collaboration commit lineage is invalid'
                USING ERRCODE='23514',
                      CONSTRAINT='authority_agent_exact_commit_guard';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE CONSTRAINT TRIGGER authority_agent_exact_commit_fact_guard
    AFTER INSERT ON authority_agent_collaboration_commit
    DEFERRABLE INITIALLY IMMEDIATE
    FOR EACH ROW EXECUTE FUNCTION authority_agent_exact_commit_guard()
    """,
    """
    CREATE TRIGGER authority_agent_collaboration_commit_immutable
    BEFORE UPDATE OR DELETE ON authority_agent_collaboration_commit
    FOR EACH ROW EXECUTE FUNCTION authority_agent_collaboration_immutable()
    """,
]


DOWNGRADE_STATEMENTS: list[str] = []

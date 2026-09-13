from __future__ import annotations

MIGRATION_ID = "20260914_0133_formation_evaluation_recovery"
DOWN_REVISION = "20260914_0132_planning_runtime_continuation"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = "Preserve terminal evaluations and append a scoped Formation continuation with exact candidate lineage."

UPGRADE_STATEMENTS = [
    """
    CREATE TABLE authority_narrative_formation_recovery (
        recovery_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        workspace_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        formation_run_id TEXT NOT NULL REFERENCES authority_story_formation_run(formation_run_id),
        frozen_input_digest TEXT NOT NULL CHECK(frozen_input_digest ~ '^sha256:[0-9a-f]{64}$'),
        formation_version BIGINT NOT NULL CHECK(formation_version > 0),
        resume_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        source_operation_id TEXT NOT NULL UNIQUE REFERENCES authority_operation(operation_id),
        successor_operation_id TEXT NOT NULL UNIQUE REFERENCES authority_operation(operation_id),
        candidate_asset_version_id TEXT NOT NULL REFERENCES authority_asset_version(asset_version_id),
        candidate_content_hash TEXT NOT NULL CHECK(candidate_content_hash ~ '^sha256:[0-9a-f]{64}$'),
        successor_generation BIGINT NOT NULL CHECK(successor_generation BETWEEN 2 AND 3),
        evidence JSONB NOT NULL CHECK(jsonb_typeof(evidence)='object'),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        FOREIGN KEY(project_id,workspace_id,book_id) REFERENCES authority_book(project_id,workspace_id,book_id)
    )
    """,
    "CREATE INDEX authority_narrative_formation_recovery_scope_idx ON authority_narrative_formation_recovery(project_id,workspace_id,book_id)",
    "CREATE INDEX authority_narrative_formation_recovery_run_idx ON authority_narrative_formation_recovery(formation_run_id)",
    "CREATE INDEX authority_narrative_formation_recovery_resume_idx ON authority_narrative_formation_recovery(resume_operation_id)",
    "CREATE INDEX authority_narrative_formation_recovery_candidate_idx ON authority_narrative_formation_recovery(candidate_asset_version_id)",
    "ALTER TABLE authority_narrative_evaluation_execution ADD COLUMN formation_recovery_ref TEXT UNIQUE REFERENCES authority_narrative_formation_recovery(recovery_id)",
    """
    DO $$ DECLARE constraint_name TEXT; matches INTEGER;
    BEGIN
        SELECT count(*),min(conname) INTO matches,constraint_name
        FROM pg_constraint WHERE conrelid='authority_narrative_evaluation_execution'::regclass
          AND contype='c' AND pg_get_constraintdef(oid) LIKE '%predecessor_generation%'
          AND pg_get_constraintdef(oid) LIKE '%recovery_intent_id%';
        IF matches<>1 THEN RAISE EXCEPTION 'NARRATIVE_EVALUATION_LINEAGE_CONSTRAINT_DRIFT'; END IF;
        EXECUTE format('ALTER TABLE authority_narrative_evaluation_execution DROP CONSTRAINT %I',constraint_name);
    END; $$
    """,
    """
    ALTER TABLE authority_narrative_evaluation_execution ADD CONSTRAINT authority_narrative_evaluation_recovery_lineage CHECK (
        (generation=1 AND predecessor_execution_id IS NULL AND predecessor_generation IS NULL
         AND predecessor_operation_id IS NULL AND recovery_intent_id IS NULL AND formation_recovery_ref IS NULL)
        OR
        (generation>1 AND predecessor_execution_id IS NOT NULL AND predecessor_generation=generation-1
         AND predecessor_operation_id IS NOT NULL AND (
             (recovery_intent_id IS NOT NULL AND formation_recovery_ref IS NULL)
             OR (recovery_intent_id IS NULL AND formation_recovery_ref IS NOT NULL AND generation<=3)
         ))
    )
    """,
    """
    CREATE FUNCTION authority_narrative_formation_recovery_immutable() RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION 'NARRATIVE_FORMATION_RECOVERY_IMMUTABLE' USING ERRCODE='check_violation';
    END; $$
    """,
    "CREATE TRIGGER authority_narrative_formation_recovery_immutable BEFORE UPDATE OR DELETE ON authority_narrative_formation_recovery FOR EACH ROW EXECUTE FUNCTION authority_narrative_formation_recovery_immutable()",
    """
    CREATE FUNCTION authority_narrative_formation_reference_immutable() RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        IF OLD.formation_recovery_ref IS DISTINCT FROM NEW.formation_recovery_ref THEN
            RAISE EXCEPTION 'NARRATIVE_FORMATION_RECOVERY_REFERENCE_IMMUTABLE' USING ERRCODE='check_violation';
        END IF;
        RETURN NEW;
    END; $$
    """,
    "CREATE TRIGGER authority_narrative_formation_reference_immutable BEFORE UPDATE ON authority_narrative_evaluation_execution FOR EACH ROW EXECUTE FUNCTION authority_narrative_formation_reference_immutable()",
    """
    DO $migration$ DECLARE definition TEXT; original TEXT := 'IF NEW.generation>1 THEN'; replacement TEXT;
    BEGIN
        SELECT pg_get_functiondef('authority_narrative_evaluation_execution_guard()'::regprocedure) INTO definition;
        IF (length(definition)-length(replace(definition,original,'')))/length(original)<>1 THEN
            RAISE EXCEPTION 'NARRATIVE_EVALUATION_EXECUTION_GUARD_DRIFT';
        END IF;
        replacement := $body$IF NEW.generation>1 AND NEW.formation_recovery_ref IS NOT NULL THEN
            IF NOT EXISTS (
                SELECT 1 FROM authority_narrative_formation_recovery recovery
                JOIN authority_operation source ON source.operation_id=recovery.source_operation_id
                  AND source.status='FAILED_FINAL' AND source.project_id=recovery.project_id
                JOIN authority_operation successor ON successor.operation_id=recovery.successor_operation_id
                  AND successor.project_id=source.project_id AND successor.workspace_id=source.workspace_id
                  AND successor.actor_id=source.actor_id AND successor.command_payload=source.command_payload
                  AND successor.causation_operation_id=source.operation_id
                JOIN authority_operation resume ON resume.operation_id=recovery.resume_operation_id
                  AND resume.status='SUCCEEDED' AND resume.definition_name='story.formation.resume'
                  AND resume.project_id=recovery.project_id AND resume.workspace_id=recovery.workspace_id
                  AND resume.command_payload->>'formation_run_id'=recovery.formation_run_id
                  AND resume.command_payload->>'book_id'=recovery.book_id
                WHERE recovery.recovery_id=NEW.formation_recovery_ref
                  AND recovery.project_id=NEW.project_id AND recovery.book_id=NEW.book_id
                  AND recovery.successor_operation_id=NEW.operation_id
                  AND recovery.source_operation_id=NEW.predecessor_operation_id
                  AND recovery.candidate_asset_version_id=NEW.candidate_asset_version_id
                  AND recovery.candidate_content_hash=NEW.candidate_content_hash
                  AND recovery.successor_generation=NEW.generation
                  AND NOT EXISTS (SELECT 1 FROM authority_external_effect effect WHERE effect.operation_id=source.operation_id)
            ) THEN
                RAISE EXCEPTION 'NARRATIVE_EVALUATION_FORMATION_BINDING_INVALID' USING ERRCODE='check_violation';
            END IF;
        ELSIF NEW.generation>1 THEN$body$;
        EXECUTE replace(definition,original,replacement);
    END; $migration$
    """,
    """
    CREATE FUNCTION authority_narrative_formation_gate_is_open(p_operation_id TEXT,p_project_id TEXT,p_recovery_id TEXT)
    RETURNS BOOLEAN LANGUAGE SQL VOLATILE AS $$
        SELECT EXISTS (
            SELECT 1 FROM authority_narrative_formation_recovery recovery
            JOIN authority_narrative_evaluation_execution execution ON execution.operation_id=recovery.successor_operation_id
              AND execution.formation_recovery_ref=recovery.recovery_id AND execution.project_id=recovery.project_id
              AND execution.book_id=recovery.book_id AND execution.candidate_asset_version_id=recovery.candidate_asset_version_id
              AND execution.candidate_content_hash=recovery.candidate_content_hash
              AND execution.generation=recovery.successor_generation AND execution.predecessor_operation_id=recovery.source_operation_id
            JOIN authority_narrative_evaluation_execution_head head ON head.project_id=execution.project_id
              AND head.candidate_asset_version_id=execution.candidate_asset_version_id
              AND head.current_execution_id=execution.evaluation_execution_id AND head.current_generation=execution.generation
            JOIN authority_operation source ON source.operation_id=recovery.source_operation_id
              AND source.status='FAILED_FINAL' AND source.project_id=recovery.project_id
            JOIN authority_operation successor ON successor.operation_id=recovery.successor_operation_id
              AND successor.project_id=source.project_id AND successor.workspace_id=source.workspace_id
              AND successor.actor_id=source.actor_id AND successor.command_payload=source.command_payload
              AND successor.causation_operation_id=source.operation_id
            JOIN authority_operation resume ON resume.operation_id=recovery.resume_operation_id
              AND resume.status='SUCCEEDED' AND resume.definition_name='story.formation.resume'
              AND resume.project_id=recovery.project_id AND resume.workspace_id=recovery.workspace_id
              AND resume.command_payload->>'formation_run_id'=recovery.formation_run_id
              AND resume.command_payload->>'book_id'=recovery.book_id
              AND resume.command_payload->>'expected_version'=(recovery.formation_version-1)::text
            JOIN authority_story_formation_run f ON f.formation_run_id=recovery.formation_run_id
              AND f.project_id=recovery.project_id AND f.workspace_id=recovery.workspace_id AND f.book_id=recovery.book_id
              AND f.frozen_input_digest=recovery.frozen_input_digest AND f.version>=recovery.formation_version
              AND f.lifecycle='RUNNING' AND f.current_stage='BOOK_DESIGN' AND resume.causation_operation_id=f.root_operation_id
            JOIN authority_operation proposal ON proposal.operation_id=source.command_payload->'payload'->>'generation_operation_id'
              AND proposal.definition_name='book_design.propose' AND proposal.status='SUCCEEDED'
              AND proposal.project_id=f.project_id AND proposal.workspace_id=f.workspace_id
              AND proposal.idempotency_key=f.formation_run_id||':book-design:propose'
            JOIN authority_runtime_job job ON job.project_id=f.project_id
              AND job.subject_kind='STORY_FORMATION_RUN' AND job.subject_id=f.formation_run_id
              AND job.job_kind='STORY_FORMATION_ADVANCE' AND job.runtime_group='story_formation'
              AND job.status IN ('RUNNING','CHECKPOINTED')
              AND job.input_snapshot->>'formation_run_id'=f.formation_run_id
              AND job.input_snapshot->>'observed_stage'=f.current_stage
              AND job.input_snapshot->>'observed_version'=f.version::text
              AND job.input_snapshot->>'frozen_input_digest'=f.frozen_input_digest
            JOIN authority_runtime_job_attempt attempt ON attempt.runtime_job_id=job.runtime_job_id
              AND attempt.attempt_id=job.current_attempt_id AND attempt.worker_id=job.claimed_by
              AND attempt.fencing_token=job.current_fencing_token AND attempt.status=job.status
            JOIN authority_runtime_job_lease lease ON lease.runtime_job_id=job.runtime_job_id
              AND lease.attempt_id=attempt.attempt_id AND lease.lease_id=attempt.lease_id
              AND lease.worker_id=attempt.worker_id AND lease.fencing_token=attempt.fencing_token
              AND lease.status='HELD' AND lease.lease_expires_at>clock_timestamp()
            WHERE recovery.recovery_id=p_recovery_id AND recovery.successor_operation_id=p_operation_id
              AND recovery.project_id=p_project_id
              AND NOT EXISTS (SELECT 1 FROM authority_external_effect effect WHERE effect.operation_id=source.operation_id)
        );
    $$
    """,
    """
    DO $migration$ DECLARE definition TEXT; original TEXT; replacement TEXT;
    BEGIN
        SELECT pg_get_functiondef('authority_narrative_replacement_gate_is_open(text,text)'::regprocedure) INTO definition;
        original := 'execution.recovery_intent_id,';
        IF (length(definition)-length(replace(definition,original,'')))/length(original)<>1 THEN
            RAISE EXCEPTION 'NARRATIVE_REPLACEMENT_GATE_PROJECTION_DRIFT';
        END IF;
        definition := replace(definition,original,original||' execution.formation_recovery_ref,');
        definition := replace(definition,'OR evaluation.recovery_intent_id IS NOT NULL',
            'OR evaluation.recovery_intent_id IS NOT NULL OR evaluation.formation_recovery_ref IS NOT NULL');
        original := 'OR NULLIF(evaluation.recovery_intent_id,'''') IS NULL';
        IF strpos(definition,original)=0 THEN RAISE EXCEPTION 'NARRATIVE_REPLACEMENT_GATE_LINEAGE_DRIFT'; END IF;
        definition := replace(definition,original,
            'OR (NULLIF(evaluation.recovery_intent_id,'''') IS NULL AND evaluation.formation_recovery_ref IS NULL)');
        original := E'        SELECT EXISTS (\n            SELECT 1\n            FROM authority_runtime_job AS job';
        IF strpos(definition,original)=0 THEN RAISE EXCEPTION 'NARRATIVE_REPLACEMENT_GATE_EXECUTION_DRIFT'; END IF;
        replacement := E'        IF evaluation.formation_recovery_ref IS NOT NULL THEN\n'
            ||E'            RETURN authority_narrative_formation_gate_is_open(p_operation_id,p_project_id,evaluation.formation_recovery_ref);\n'
            ||E'        END IF;\n'||original;
        EXECUTE replace(definition,original,replacement);
    END; $migration$
    """,
]

from __future__ import annotations


MIGRATION_ID = "20260821_0095_post_merge_correctness_repair"
DOWN_REVISION = "20260820_0094_industrial_autonomous_novel_os"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = (
    "Keep accepted history immutable. Resume BOOK_PROJECTION_REPAIR RuntimeJobs "
    "until terminal validation can activate the canonical projection pointer."
)


UPGRADE_STATEMENTS = [
    """
    ALTER TABLE authority_book_narrative_projection_set
    ADD COLUMN projection_provenance JSONB NOT NULL DEFAULT '{}'::jsonb
    """,
    """
    CREATE UNIQUE INDEX authority_attempt_identity_operation_idx
    ON authority_attempt(attempt_id, operation_id)
    """,
    """
    CREATE TABLE authority_book_projection_repair (
        repair_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        book_id TEXT NOT NULL REFERENCES authority_book(book_id),
        book_run_id TEXT NOT NULL UNIQUE
            REFERENCES authority_book_production(book_run_id),
        runtime_job_id TEXT UNIQUE
            REFERENCES authority_runtime_job(runtime_job_id)
            DEFERRABLE INITIALLY DEFERRED,
        operation_id TEXT REFERENCES authority_operation(operation_id),
        target_accepted_through_chapter INTEGER NOT NULL
            CHECK (target_accepted_through_chapter > 0),
        discovered_acceptance_count INTEGER NOT NULL
            CHECK (discovered_acceptance_count > 0),
        next_chapter INTEGER NOT NULL DEFAULT 1 CHECK (next_chapter > 0),
        authoritative_status TEXT NOT NULL DEFAULT 'REGISTERED'
            CHECK (authoritative_status IN (
                'REGISTERED','RUNNING','CHECKPOINTED',
                'AUTHORITATIVE_REPAIR_COMPLETE',
                'FAILED_RETRYABLE','FAILED_TERMINAL'
            )),
        semantic_projection_status TEXT NOT NULL DEFAULT 'NOT_REQUESTED'
            CHECK (semantic_projection_status IN (
                'NOT_REQUESTED','PENDING',
                'RETRIEVAL_SEMANTIC_PROJECTION_READY',
                'FAILED_RETRYABLE','UNAVAILABLE_BY_POLICY'
            )),
        discovery_evidence JSONB NOT NULL,
        target_evidence_digest TEXT NOT NULL CHECK (
            target_evidence_digest ~ '^sha256:[0-9a-f]{64}$'
        ),
        terminal_validation JSONB NOT NULL DEFAULT '{}'::jsonb,
        terminal_digest TEXT NOT NULL DEFAULT '' CHECK (
            terminal_digest='' OR terminal_digest ~ '^sha256:[0-9a-f]{64}$'
        ),
        terminal_attempt_id TEXT,
        terminal_command_fencing_token BIGINT,
        terminal_runtime_attempt_id TEXT,
        terminal_runtime_fencing_token BIGINT,
        last_error JSONB NOT NULL DEFAULT '{}'::jsonb,
        version BIGINT NOT NULL DEFAULT 1 CHECK (version > 0),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        completed_at TIMESTAMPTZ,
        UNIQUE(repair_id, project_id, book_run_id),
        FOREIGN KEY(terminal_attempt_id, operation_id)
            REFERENCES authority_attempt(attempt_id, operation_id),
        FOREIGN KEY(terminal_attempt_id, terminal_command_fencing_token)
            REFERENCES authority_lease_acquisition(attempt_id, fencing_token),
        FOREIGN KEY(runtime_job_id, terminal_runtime_attempt_id,
                    terminal_runtime_fencing_token)
            REFERENCES authority_runtime_job_attempt(
                runtime_job_id, attempt_id, fencing_token
            ),
        CHECK (next_chapter <= target_accepted_through_chapter + 1),
        CHECK (
            authoritative_status<>'AUTHORITATIVE_REPAIR_COMPLETE'
            OR (
                next_chapter=target_accepted_through_chapter+1
                AND terminal_digest<>''
                AND terminal_attempt_id IS NOT NULL
                AND terminal_command_fencing_token IS NOT NULL
                AND terminal_runtime_attempt_id IS NOT NULL
                AND terminal_runtime_fencing_token IS NOT NULL
                AND completed_at IS NOT NULL
            )
        )
    )
    """,
    """
    CREATE TABLE authority_book_projection_repair_checkpoint (
        checkpoint_id TEXT PRIMARY KEY,
        repair_id TEXT NOT NULL
            REFERENCES authority_book_projection_repair(repair_id),
        project_id TEXT NOT NULL,
        book_run_id TEXT NOT NULL,
        chapter_number INTEGER NOT NULL CHECK (chapter_number > 0),
        acceptance_id TEXT NOT NULL
            REFERENCES authority_book_chapter_acceptance(acceptance_id),
        projection_set_id TEXT NOT NULL
            REFERENCES authority_book_narrative_projection_set(projection_set_id),
        source_evidence_digest TEXT NOT NULL CHECK (
            source_evidence_digest ~ '^sha256:[0-9a-f]{64}$'
        ),
        projection_hash TEXT NOT NULL CHECK (
            projection_hash ~ '^sha256:[0-9a-f]{64}$'
        ),
        projector_version TEXT NOT NULL,
        adaptation_evidence JSONB NOT NULL,
        operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        attempt_id TEXT NOT NULL REFERENCES authority_attempt(attempt_id),
        fencing_token BIGINT NOT NULL CHECK (fencing_token > 0),
        runtime_job_id TEXT NOT NULL REFERENCES authority_runtime_job(runtime_job_id),
        runtime_attempt_id TEXT NOT NULL
            REFERENCES authority_runtime_job_attempt(attempt_id),
        runtime_fencing_token BIGINT NOT NULL CHECK (runtime_fencing_token > 0),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(repair_id, chapter_number),
        UNIQUE(project_id, book_run_id, chapter_number),
        FOREIGN KEY(repair_id, project_id, book_run_id)
            REFERENCES authority_book_projection_repair(
                repair_id, project_id, book_run_id
            ),
        FOREIGN KEY(attempt_id, fencing_token)
            REFERENCES authority_lease_acquisition(attempt_id, fencing_token),
        FOREIGN KEY(attempt_id, operation_id)
            REFERENCES authority_attempt(attempt_id, operation_id),
        FOREIGN KEY(runtime_job_id, runtime_attempt_id, runtime_fencing_token)
            REFERENCES authority_runtime_job_attempt(
                runtime_job_id, attempt_id, fencing_token
            )
    )
    """,
    """
    CREATE TABLE authority_arc_checkpoint_followup (
        followup_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        book_id TEXT NOT NULL REFERENCES authority_book(book_id),
        book_run_id TEXT NOT NULL
            REFERENCES authority_book_production(book_run_id),
        projection_set_id TEXT NOT NULL
            REFERENCES authority_book_narrative_projection_set(projection_set_id),
        checkpoint_id TEXT NOT NULL
            REFERENCES authority_arc_checkpoint_v2(checkpoint_id),
        accepted_through_chapter INTEGER NOT NULL CHECK (accepted_through_chapter > 0),
        decision TEXT NOT NULL CHECK (decision IN ('CORRECT','REPLAN_REQUIRED')),
        status TEXT NOT NULL DEFAULT 'READY' CHECK (
            status IN ('READY','RUNNING','PROPOSED','WAITING_APPROVAL',
                       'COMPLETED','FAILED_RETRYABLE','FAILED_TERMINAL')
        ),
        reason_evidence JSONB NOT NULL,
        target_plan_version_ids JSONB NOT NULL,
        idempotency_key TEXT NOT NULL,
        trace_id TEXT NOT NULL,
        operation_id TEXT REFERENCES authority_operation(operation_id),
        plan_change_id TEXT,
        last_error JSONB NOT NULL DEFAULT '{}'::jsonb,
        version BIGINT NOT NULL DEFAULT 1 CHECK (version > 0),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id, idempotency_key),
        UNIQUE(checkpoint_id)
    )
    """,
    """
    CREATE TABLE authority_retrieval_embedding_projection (
        embedding_projection_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        retrieval_document_id TEXT NOT NULL
            REFERENCES authority_narrative_retrieval_document(retrieval_document_id),
        source_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        source_content_hash TEXT NOT NULL CHECK (
            source_content_hash ~ '^sha256:[0-9a-f]{64}$'
        ),
        projection_version TEXT NOT NULL,
        status TEXT NOT NULL CHECK (
            status IN ('PENDING','RUNNING','READY','FAILED_RETRYABLE','FAILED_TERMINAL')
        ),
        embedding JSONB,
        embedding_model TEXT NOT NULL DEFAULT '',
        embedding_provider TEXT NOT NULL DEFAULT '',
        embedding_dimensions INTEGER CHECK (
            embedding_dimensions IS NULL OR embedding_dimensions > 0
        ),
        route_snapshot_id TEXT NOT NULL DEFAULT '',
        external_effect_id TEXT REFERENCES authority_external_effect(external_effect_id),
        receipt_id TEXT NOT NULL DEFAULT '',
        operation_id TEXT REFERENCES authority_operation(operation_id),
        projection_hash TEXT NOT NULL DEFAULT '' CHECK (
            projection_hash='' OR projection_hash ~ '^sha256:[0-9a-f]{64}$'
        ),
        evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
        version BIGINT NOT NULL DEFAULT 1 CHECK (version > 0),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(retrieval_document_id, projection_version),
        CHECK (
            status<>'READY' OR (
                embedding IS NOT NULL AND embedding_model<>''
                AND embedding_provider<>'' AND embedding_dimensions IS NOT NULL
                AND route_snapshot_id<>'' AND external_effect_id IS NOT NULL
                AND receipt_id<>'' AND projection_hash<>''
            )
        )
    )
    """,
    """
    CREATE INDEX authority_book_projection_repair_status_idx
    ON authority_book_projection_repair(authoritative_status, updated_at)
    """,
    """
    CREATE INDEX authority_book_projection_repair_project_idx
    ON authority_book_projection_repair(project_id)
    """,
    """
    CREATE INDEX authority_book_projection_repair_book_idx
    ON authority_book_projection_repair(book_id)
    """,
    """
    CREATE INDEX authority_book_projection_repair_operation_idx
    ON authority_book_projection_repair(operation_id)
    """,
    """
    CREATE INDEX authority_book_projection_repair_terminal_attempt_fence_idx
    ON authority_book_projection_repair(
        terminal_attempt_id, terminal_command_fencing_token
    )
    """,
    """
    CREATE INDEX authority_book_projection_repair_terminal_operation_idx
    ON authority_book_projection_repair(terminal_attempt_id, operation_id)
    """,
    """
    CREATE INDEX authority_book_projection_repair_terminal_runtime_idx
    ON authority_book_projection_repair(
        runtime_job_id, terminal_runtime_attempt_id,
        terminal_runtime_fencing_token
    )
    """,
    """
    CREATE INDEX authority_book_projection_repair_checkpoint_projection_idx
    ON authority_book_projection_repair_checkpoint(projection_set_id)
    """,
    """
    CREATE INDEX authority_book_projection_repair_checkpoint_scope_fk_idx
    ON authority_book_projection_repair_checkpoint(
        repair_id, project_id, book_run_id
    )
    """,
    """
    CREATE INDEX authority_book_projection_repair_checkpoint_acceptance_idx
    ON authority_book_projection_repair_checkpoint(acceptance_id)
    """,
    """
    CREATE INDEX authority_book_projection_repair_checkpoint_operation_idx
    ON authority_book_projection_repair_checkpoint(operation_id)
    """,
    """
    CREATE INDEX authority_book_projection_repair_checkpoint_attempt_idx
    ON authority_book_projection_repair_checkpoint(attempt_id, operation_id)
    """,
    """
    CREATE INDEX authority_book_projection_repair_checkpoint_fence_idx
    ON authority_book_projection_repair_checkpoint(attempt_id, fencing_token)
    """,
    """
    CREATE INDEX authority_book_projection_repair_checkpoint_runtime_idx
    ON authority_book_projection_repair_checkpoint(
        runtime_job_id, runtime_attempt_id, runtime_fencing_token
    )
    """,
    """
    CREATE INDEX authority_arc_checkpoint_followup_status_idx
    ON authority_arc_checkpoint_followup(status, updated_at)
    """,
    """
    CREATE INDEX authority_arc_checkpoint_followup_project_idx
    ON authority_arc_checkpoint_followup(project_id)
    """,
    """
    CREATE INDEX authority_arc_checkpoint_followup_book_idx
    ON authority_arc_checkpoint_followup(book_id)
    """,
    """
    CREATE INDEX authority_arc_checkpoint_followup_book_run_idx
    ON authority_arc_checkpoint_followup(book_run_id)
    """,
    """
    CREATE INDEX authority_arc_checkpoint_followup_projection_idx
    ON authority_arc_checkpoint_followup(projection_set_id)
    """,
    """
    CREATE INDEX authority_arc_checkpoint_followup_operation_idx
    ON authority_arc_checkpoint_followup(operation_id)
    """,
    """
    CREATE INDEX authority_retrieval_embedding_projection_status_idx
    ON authority_retrieval_embedding_projection(project_id, book_id, status)
    """,
    """
    CREATE INDEX authority_retrieval_embedding_projection_source_idx
    ON authority_retrieval_embedding_projection(source_asset_version_id)
    """,
    """
    CREATE INDEX authority_retrieval_embedding_projection_effect_idx
    ON authority_retrieval_embedding_projection(external_effect_id)
    """,
    """
    CREATE INDEX authority_retrieval_embedding_projection_operation_idx
    ON authority_retrieval_embedding_projection(operation_id)
    """,
    """
    INSERT INTO authority_book_projection_repair(
        repair_id, project_id, book_id, book_run_id,
        target_accepted_through_chapter, discovered_acceptance_count,
        authoritative_status, discovery_evidence, target_evidence_digest,
        last_error
    )
    SELECT 'book-projection-repair:' || encode(
               digest(convert_to(production.book_run_id, 'UTF8'), 'sha256'), 'hex'
           ),
           production.project_id,
           production.book_id,
           production.book_run_id,
           production.accepted_through_chapter,
           COUNT(acceptance.acceptance_id)::integer,
           CASE
             WHEN COUNT(acceptance.acceptance_id)=production.accepted_through_chapter
              AND COUNT(DISTINCT acceptance.chapter_number)=
                  production.accepted_through_chapter
              AND MIN(acceptance.chapter_number)=1
              AND MAX(acceptance.chapter_number)=production.accepted_through_chapter
              AND BOOL_AND(acceptance_operation.status='SUCCEEDED')
              AND BOOL_AND(plan.asset_version_id IS NOT NULL)
             THEN 'REGISTERED'
             ELSE 'FAILED_TERMINAL'
           END,
           jsonb_build_object(
               'reason', CASE
                   WHEN production.active_longform_projection_set_id IS NULL
                   THEN 'ACTIVE_POINTER_MISSING'
                   ELSE 'ACTIVE_POINTER_STALE'
               END,
               'discovered_at_migration', '0095',
               'accepted_through_chapter', production.accepted_through_chapter,
               'minimum_chapter', MIN(acceptance.chapter_number),
               'maximum_chapter', MAX(acceptance.chapter_number),
               'distinct_chapter_count', COUNT(DISTINCT acceptance.chapter_number),
               'acceptance_ids', jsonb_agg(
                   acceptance.acceptance_id ORDER BY acceptance.chapter_number
               ),
               'accepted_evidence', jsonb_agg(
                   jsonb_build_object(
                       'chapter_number', acceptance.chapter_number,
                       'acceptance_id', acceptance.acceptance_id,
                       'acceptance_operation_id',
                           acceptance.acceptance_operation_id,
                       'acceptance_operation_status',
                           acceptance_operation.status,
                       'chapter_outcome_asset_version_id',
                           acceptance.chapter_outcome_asset_version_id,
                       'chapter_outcome_content_hash', outcome.content_hash,
                       'story_state_asset_version_id',
                           acceptance.story_state_asset_version_id,
                       'story_state_content_hash', story.content_hash,
                       'canon_snapshot_asset_version_id',
                           acceptance.canon_snapshot_asset_version_id,
                       'canon_snapshot_content_hash', canon.content_hash,
                       'chapter_plan_asset_version_id',
                           COALESCE(
                               NULLIF(
                                   request.command_payload->>
                                   'execution_chapter_plan_asset_version_id',
                                   ''
                               ),
                               request.chapter_plan_version
                           ),
                       'chapter_plan_content_hash', plan.content_hash
                   ) ORDER BY acceptance.chapter_number
               )
           ),
           authority_sha256_jsonb(jsonb_build_object(
               'book_run_id', production.book_run_id,
               'target_accepted_through_chapter',
                   production.accepted_through_chapter,
               'accepted_evidence', jsonb_agg(
                   jsonb_build_object(
                       'chapter_number', acceptance.chapter_number,
                       'acceptance_id', acceptance.acceptance_id,
                       'acceptance_operation_id',
                           acceptance.acceptance_operation_id,
                       'acceptance_operation_status',
                           acceptance_operation.status,
                       'chapter_outcome_asset_version_id',
                           acceptance.chapter_outcome_asset_version_id,
                       'chapter_outcome_content_hash', outcome.content_hash,
                       'story_state_asset_version_id',
                           acceptance.story_state_asset_version_id,
                       'story_state_content_hash', story.content_hash,
                       'canon_snapshot_asset_version_id',
                           acceptance.canon_snapshot_asset_version_id,
                       'canon_snapshot_content_hash', canon.content_hash,
                       'chapter_plan_asset_version_id',
                           COALESCE(
                               NULLIF(
                                   request.command_payload->>
                                   'execution_chapter_plan_asset_version_id',
                                   ''
                               ),
                               request.chapter_plan_version
                           ),
                       'chapter_plan_content_hash', plan.content_hash
                   ) ORDER BY acceptance.chapter_number
               )
           )),
           CASE
             WHEN COUNT(acceptance.acceptance_id)=production.accepted_through_chapter
              AND COUNT(DISTINCT acceptance.chapter_number)=
                  production.accepted_through_chapter
              AND MIN(acceptance.chapter_number)=1
              AND MAX(acceptance.chapter_number)=production.accepted_through_chapter
              AND BOOL_AND(acceptance_operation.status='SUCCEEDED')
              AND BOOL_AND(plan.asset_version_id IS NOT NULL)
             THEN '{}'::jsonb
             ELSE jsonb_build_object(
               'code', 'ACCEPTED_CHAPTER_SEQUENCE_INVALID',
               'expected_count', production.accepted_through_chapter,
               'observed_count', COUNT(acceptance.acceptance_id),
               'distinct_count', COUNT(DISTINCT acceptance.chapter_number),
               'minimum_chapter', MIN(acceptance.chapter_number),
               'maximum_chapter', MAX(acceptance.chapter_number)
               ,'all_acceptance_operations_succeeded',
                   BOOL_AND(acceptance_operation.status='SUCCEEDED')
               ,'all_frozen_chapter_plans_present',
                   BOOL_AND(plan.asset_version_id IS NOT NULL)
             )
           END
    FROM authority_book_production AS production
    JOIN authority_book_chapter_acceptance AS acceptance
      ON acceptance.book_run_id=production.book_run_id
     AND acceptance.project_id=production.project_id
     AND acceptance.status='COMMITTED'
    JOIN authority_book_chapter_request AS request
      ON request.chapter_request_id=acceptance.chapter_request_id
     AND request.book_run_id=acceptance.book_run_id
    LEFT JOIN authority_operation AS acceptance_operation
      ON acceptance_operation.operation_id=acceptance.acceptance_operation_id
    JOIN authority_asset_version AS outcome
      ON outcome.asset_version_id=acceptance.chapter_outcome_asset_version_id
    JOIN authority_asset_version AS story
      ON story.asset_version_id=acceptance.story_state_asset_version_id
    JOIN authority_asset_version AS canon
      ON canon.asset_version_id=acceptance.canon_snapshot_asset_version_id
    LEFT JOIN authority_asset_version AS plan
      ON plan.asset_version_id=COALESCE(
          NULLIF(
              request.command_payload->>
              'execution_chapter_plan_asset_version_id',
              ''
          ),
          request.chapter_plan_version
      )
    LEFT JOIN authority_book_narrative_projection_set AS active_projection
      ON active_projection.projection_set_id=
         production.active_longform_projection_set_id
    WHERE production.accepted_through_chapter>0
      AND (
        production.active_longform_projection_set_id IS NULL
        OR active_projection.chapter_number<>production.accepted_through_chapter
        OR active_projection.status<>'COMPLETE'
        OR active_projection.project_id<>production.project_id
        OR active_projection.book_id<>production.book_id
        OR active_projection.book_run_id<>production.book_run_id
        OR EXISTS (
            SELECT 1
            FROM authority_book_chapter_acceptance AS history
            LEFT JOIN authority_book_narrative_projection_set AS projection
              ON projection.projection_set_id=history.longform_projection_set_id
            WHERE history.book_run_id=production.book_run_id
              AND history.project_id=production.project_id
              AND history.status='COMMITTED'
              AND (
                history.longform_projection_set_id IS NULL
                OR projection.acceptance_id<>history.acceptance_id
                OR projection.chapter_outcome_asset_version_id<>
                   history.chapter_outcome_asset_version_id
                OR projection.story_state_asset_version_id<>
                   history.story_state_asset_version_id
                OR projection.canon_snapshot_asset_version_id<>
                   history.canon_snapshot_asset_version_id
              )
        )
      )
    GROUP BY production.project_id, production.book_id,
             production.book_run_id, production.accepted_through_chapter,
             production.active_longform_projection_set_id,
             active_projection.chapter_number, active_projection.status
    ON CONFLICT(book_run_id) DO NOTHING
    """,
    """
    WITH repair_job AS (
      SELECT repair.*,
             'projection-repair:' || repair.book_run_id AS repair_dedupe_key,
             jsonb_build_object(
               'repair_id', repair.repair_id,
               'book_run_id', repair.book_run_id,
               'target_accepted_through_chapter',
               repair.target_accepted_through_chapter,
               'target_evidence_digest', repair.target_evidence_digest
             ) AS repair_input
      FROM authority_book_projection_repair AS repair
      WHERE repair.runtime_job_id IS NULL
        AND repair.authoritative_status='REGISTERED'
    )
    INSERT INTO authority_runtime_job(
        runtime_job_id, job_kind, runtime_group, subject_kind,
        subject_id, project_id, dedupe_key, input_snapshot,
        input_hash, status, priority, max_attempts
    )
    SELECT 'runtime-job:' || encode(
               digest(
                 convert_to(
                   repair.project_id || chr(31) || 'book_repair' || chr(31)
                   || 'BOOK_PROJECTION_REPAIR' || chr(31)
                   || repair.repair_dedupe_key,
                   'UTF8'
                 ),
                 'sha256'
               ),
               'hex'
           ),
           'BOOK_PROJECTION_REPAIR', 'book_repair', 'BOOK_RUN',
           repair.book_run_id, repair.project_id,
           repair.repair_dedupe_key,
           repair.repair_input,
           authority_sha256_jsonb(repair.repair_input),
           'READY', 20, 10
    FROM repair_job AS repair
    ON CONFLICT DO NOTHING
    """,
    """
    UPDATE authority_book_projection_repair AS repair
    SET runtime_job_id=job.runtime_job_id, updated_at=NOW()
    FROM authority_runtime_job AS job
    WHERE job.project_id=repair.project_id
      AND job.runtime_group='book_repair'
      AND job.job_kind='BOOK_PROJECTION_REPAIR'
      AND job.subject_kind='BOOK_RUN'
      AND job.subject_id=repair.book_run_id
      AND repair.runtime_job_id IS NULL
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

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
        terminal_fencing_token BIGINT,
        last_error JSONB NOT NULL DEFAULT '{}'::jsonb,
        version BIGINT NOT NULL DEFAULT 1 CHECK (version > 0),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        completed_at TIMESTAMPTZ,
        CHECK (
            authoritative_status<>'AUTHORITATIVE_REPAIR_COMPLETE'
            OR (
                next_chapter=target_accepted_through_chapter+1
                AND terminal_digest<>''
                AND terminal_fencing_token IS NOT NULL
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
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(repair_id, chapter_number),
        UNIQUE(project_id, book_run_id, chapter_number)
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
    CREATE INDEX authority_book_projection_repair_checkpoint_projection_idx
    ON authority_book_projection_repair_checkpoint(projection_set_id)
    """,
    """
    CREATE INDEX authority_arc_checkpoint_followup_status_idx
    ON authority_arc_checkpoint_followup(status, updated_at)
    """,
    """
    CREATE INDEX authority_retrieval_embedding_projection_status_idx
    ON authority_retrieval_embedding_projection(project_id, book_id, status)
    """,
    """
    INSERT INTO authority_book_projection_repair(
        repair_id, project_id, book_id, book_run_id,
        target_accepted_through_chapter, discovered_acceptance_count,
        discovery_evidence, target_evidence_digest
    )
    SELECT 'book-projection-repair:' || encode(
               digest(convert_to(production.book_run_id, 'UTF8'), 'sha256'), 'hex'
           ),
           production.project_id,
           production.book_id,
           production.book_run_id,
           production.accepted_through_chapter,
           COUNT(acceptance.acceptance_id)::integer,
           jsonb_build_object(
               'reason', CASE
                   WHEN production.active_longform_projection_set_id IS NULL
                   THEN 'ACTIVE_POINTER_MISSING'
                   ELSE 'ACTIVE_POINTER_STALE'
               END,
               'discovered_at_migration', '0095',
               'accepted_through_chapter', production.accepted_through_chapter,
               'acceptance_ids', jsonb_agg(
                   acceptance.acceptance_id ORDER BY acceptance.chapter_number
               )
           ),
           'sha256:' || encode(
               digest(
                   convert_to(
                       production.book_run_id || chr(31)
                       || production.accepted_through_chapter::text || chr(31)
                       || string_agg(
                           acceptance.acceptance_id || ':'
                           || acceptance.chapter_outcome_asset_version_id || ':'
                           || acceptance.story_state_asset_version_id || ':'
                           || acceptance.canon_snapshot_asset_version_id,
                           '|' ORDER BY acceptance.chapter_number
                       ),
                       'UTF8'
                   ),
                   'sha256'
               ),
               'hex'
           )
    FROM authority_book_production AS production
    JOIN authority_book_chapter_acceptance AS acceptance
      ON acceptance.book_run_id=production.book_run_id
     AND acceptance.project_id=production.project_id
     AND acceptance.status='COMMITTED'
    LEFT JOIN authority_book_narrative_projection_set AS active_projection
      ON active_projection.projection_set_id=
         production.active_longform_projection_set_id
    WHERE production.accepted_through_chapter>0
      AND (
        production.active_longform_projection_set_id IS NULL
        OR active_projection.chapter_number<>production.accepted_through_chapter
        OR active_projection.status<>'COMPLETE'
      )
    GROUP BY production.project_id, production.book_id,
             production.book_run_id, production.accepted_through_chapter,
             production.active_longform_projection_set_id,
             active_projection.chapter_number, active_projection.status
    HAVING COUNT(acceptance.acceptance_id)=production.accepted_through_chapter
    ON CONFLICT(book_run_id) DO NOTHING
    """,
    """
    INSERT INTO authority_runtime_job(
        runtime_job_id, job_kind, runtime_group, subject_kind,
        subject_id, project_id, dedupe_key, input_snapshot,
        input_hash, status, priority, max_attempts
    )
    SELECT 'runtime-job:book-projection-repair:' || encode(
               digest(convert_to(repair.book_run_id, 'UTF8'), 'sha256'), 'hex'
           ),
           'BOOK_PROJECTION_REPAIR', 'book_repair', 'BOOK_RUN',
           repair.book_run_id, repair.project_id,
           'projection-repair:' || repair.book_run_id,
           jsonb_build_object(
               'repair_id', repair.repair_id,
               'book_run_id', repair.book_run_id,
               'target_accepted_through_chapter',
               repair.target_accepted_through_chapter,
               'target_evidence_digest', repair.target_evidence_digest
           ),
           'sha256:' || encode(
               digest(
                   convert_to(
                       repair.repair_id || chr(31)
                       || repair.target_evidence_digest,
                       'UTF8'
                   ),
                   'sha256'
               ),
               'hex'
           ),
           'READY', 20, 10
    FROM authority_book_projection_repair AS repair
    WHERE repair.runtime_job_id IS NULL
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

from __future__ import annotations


MIGRATION_ID = "20260820_0094_industrial_autonomous_novel_os"
DOWN_REVISION = "20260820_0093_book_liveness_critical_path_closure"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = (
    "Keep accepted Chapter history immutable. Rebuild new Arc, Obligation, retrieval, "
    "Agent transcript and lineage projections from accepted AssetVersion/Operation evidence."
)


UPGRADE_STATEMENTS = [
    """
    ALTER TABLE authority_attempt_capability_pack_snapshot
    DROP CONSTRAINT IF EXISTS authority_attempt_capability_pack_snapshot_check2
    """,
    """
    ALTER TABLE authority_attempt_capability_pack_snapshot
    ADD CONSTRAINT authority_attempt_capability_pack_snapshot_operation_check
    CHECK (operation_definition_ref<>'')
    """,
    """
    CREATE OR REPLACE VIEW authority_narrative_state_event_projection AS
    SELECT acceptance.project_id,
           production.book_id,
           acceptance.book_run_id,
           acceptance.acceptance_id,
           acceptance.acceptance_operation_id,
           acceptance_operation.trace_id,
           acceptance.chapter_number AS accepted_chapter,
           acceptance.chapter_outcome_asset_version_id,
           event.payload AS event_payload,
           event.event_ordinal,
           acceptance.created_at AS recorded_at
    FROM authority_book_chapter_acceptance AS acceptance
    JOIN authority_book_production AS production
      ON production.book_run_id=acceptance.book_run_id
     AND production.project_id=acceptance.project_id
    JOIN authority_operation AS acceptance_operation
      ON acceptance_operation.operation_id=acceptance.acceptance_operation_id
     AND acceptance_operation.project_id=acceptance.project_id
     AND acceptance_operation.status='SUCCEEDED'
    JOIN authority_asset_version AS outcome_version
      ON outcome_version.asset_version_id=
         acceptance.chapter_outcome_asset_version_id
     AND outcome_version.lifecycle IN ('ACTIVE', 'SUPERSEDED')
     AND outcome_version.eligibility='ELIGIBLE'
     AND outcome_version.governance='CLEAR'
    JOIN authority_asset AS outcome_asset
      ON outcome_asset.asset_id=outcome_version.asset_id
     AND outcome_asset.project_id=acceptance.project_id
     AND outcome_asset.asset_type='chapter_outcome'
    CROSS JOIN LATERAL jsonb_array_elements(
      outcome_version.content->'state_events'
    ) WITH ORDINALITY AS event(payload, event_ordinal)
    WHERE acceptance.status='COMMITTED'
      AND outcome_version.content->>'contract_version' IN (
          'chapter-outcome-v2', 'chapter-outcome-v3'
      )
      AND outcome_version.content->>'project_id'=acceptance.project_id
      AND outcome_version.content->>'book_id'=production.book_id
      AND (outcome_version.content->>'chapter_number')::integer=
          acceptance.chapter_number
      AND event.payload->>'contract_version' IN (
          'narrative-state-event-v2', 'narrative-state-event-v3'
      )
      AND event.payload->>'layer'='STATE_EVENT'
    """,
    """
    CREATE OR REPLACE VIEW authority_narrative_state_rebuild_source AS
    SELECT acceptance.project_id,
           production.book_id,
           acceptance.book_run_id,
           acceptance.acceptance_id,
           acceptance.chapter_number AS accepted_chapter,
           acceptance.chapter_outcome_asset_version_id,
           acceptance.story_state_asset_version_id,
           outcome.content AS chapter_outcome,
           acceptance.created_at AS recorded_at
    FROM authority_book_chapter_acceptance AS acceptance
    JOIN authority_book_production AS production
      ON production.book_run_id=acceptance.book_run_id
     AND production.project_id=acceptance.project_id
    JOIN authority_operation AS acceptance_operation
      ON acceptance_operation.operation_id=acceptance.acceptance_operation_id
     AND acceptance_operation.project_id=acceptance.project_id
     AND acceptance_operation.status='SUCCEEDED'
    JOIN authority_asset_version AS outcome
      ON outcome.asset_version_id=acceptance.chapter_outcome_asset_version_id
     AND outcome.lifecycle IN ('ACTIVE', 'SUPERSEDED')
     AND outcome.eligibility='ELIGIBLE'
     AND outcome.governance='CLEAR'
    JOIN authority_asset AS outcome_asset
      ON outcome_asset.asset_id=outcome.asset_id
     AND outcome_asset.project_id=acceptance.project_id
     AND outcome_asset.asset_type='chapter_outcome'
    WHERE acceptance.status='COMMITTED'
      AND outcome.content->>'contract_version' IN (
        'chapter-outcome-v1', 'chapter-outcome-v2', 'chapter-outcome-v3'
      )
      AND outcome.content->>'project_id'=acceptance.project_id
      AND outcome.content->>'book_id'=production.book_id
      AND (outcome.content->>'chapter_number')::integer=
          acceptance.chapter_number
    """,
    """
    CREATE TABLE authority_book_narrative_projection_set (
        projection_set_id TEXT PRIMARY KEY,
        acceptance_id TEXT NOT NULL UNIQUE
            REFERENCES authority_book_chapter_acceptance(acceptance_id),
        project_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        book_run_id TEXT NOT NULL REFERENCES authority_book_production(book_run_id),
        chapter_request_id TEXT NOT NULL UNIQUE
            REFERENCES authority_book_chapter_request(chapter_request_id),
        chapter_number INTEGER NOT NULL CHECK (chapter_number > 0),
        acceptance_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        chapter_outcome_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        story_state_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        canon_snapshot_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        arc_state JSONB NOT NULL,
        obligation_state JSONB NOT NULL,
        projection_hash TEXT NOT NULL CHECK (
            projection_hash ~ '^sha256:[0-9a-f]{64}$'
        ),
        status TEXT NOT NULL CHECK (status='COMPLETE'),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id, book_id, chapter_number),
        UNIQUE(project_id, chapter_request_id, acceptance_operation_id)
    )
    """,
    """
    ALTER TABLE authority_book_chapter_acceptance
    ADD COLUMN longform_projection_set_id TEXT,
    ADD CONSTRAINT authority_book_acceptance_longform_projection_fk
      FOREIGN KEY(longform_projection_set_id)
      REFERENCES authority_book_narrative_projection_set(projection_set_id)
      DEFERRABLE INITIALLY DEFERRED
    """,
    """
    ALTER TABLE authority_book_production
    ADD COLUMN active_longform_projection_set_id TEXT,
    ADD CONSTRAINT authority_book_active_longform_projection_fk
      FOREIGN KEY(active_longform_projection_set_id)
      REFERENCES authority_book_narrative_projection_set(projection_set_id)
      DEFERRABLE INITIALLY DEFERRED
    """,
    """
    CREATE TABLE authority_arc_progress_v2 (
        progress_id TEXT PRIMARY KEY,
        projection_set_id TEXT NOT NULL
            REFERENCES authority_book_narrative_projection_set(projection_set_id),
        project_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        arc_plan_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        chapter_number INTEGER NOT NULL CHECK (chapter_number > 0),
        acceptance_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        chapter_outcome_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        observation_status TEXT NOT NULL CHECK (
            observation_status IN (
                'OBSERVED','NOT_OBSERVED','NOT_MATERIALIZED','UNKNOWN'
            )
        ),
        contribution_kind TEXT NOT NULL,
        progress_units INTEGER NOT NULL CHECK (progress_units >= 0),
        cumulative_progress_units INTEGER NOT NULL
            CHECK (cumulative_progress_units >= 0),
        deviation_units INTEGER,
        evidence JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id, book_id, arc_plan_version_id, chapter_number)
    )
    """,
    """
    CREATE TABLE authority_arc_actual_state (
        project_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        arc_plan_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        projection_set_id TEXT NOT NULL
            REFERENCES authority_book_narrative_projection_set(projection_set_id),
        accepted_through_chapter INTEGER NOT NULL
            CHECK (accepted_through_chapter > 0),
        acceptance_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        observation_status TEXT NOT NULL CHECK (
            observation_status IN (
                'OBSERVED','NOT_OBSERVED','NOT_MATERIALIZED','UNKNOWN'
            )
        ),
        lifecycle_status TEXT NOT NULL CHECK (
            lifecycle_status IN (
                'PLANNED','READY','ACTIVE','DORMANT','BLOCKED','COMPLETED','ABANDONED'
            )
        ),
        cumulative_progress_units INTEGER NOT NULL
            CHECK (cumulative_progress_units >= 0),
        current_phase TEXT NOT NULL DEFAULT '',
        state JSONB NOT NULL,
        version INTEGER NOT NULL CHECK (version > 0),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY(project_id, book_id, arc_plan_version_id)
    )
    """,
    """
    CREATE TABLE authority_arc_checkpoint_v2 (
        checkpoint_id TEXT PRIMARY KEY,
        projection_set_id TEXT NOT NULL
            REFERENCES authority_book_narrative_projection_set(projection_set_id),
        project_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        arc_plan_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        accepted_through_chapter INTEGER NOT NULL
            CHECK (accepted_through_chapter > 0),
        acceptance_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        progress_id TEXT NOT NULL REFERENCES authority_arc_progress_v2(progress_id),
        decision TEXT NOT NULL CHECK (
            decision IN ('CONTINUE','CORRECT','REPLAN_REQUIRED','COMPLETED','UNKNOWN')
        ),
        reasons JSONB NOT NULL,
        checkpoint JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id, book_id, arc_plan_version_id, accepted_through_chapter)
    )
    """,
    """
    CREATE TABLE authority_arc_outcome_v2 (
        arc_outcome_id TEXT PRIMARY KEY,
        projection_set_id TEXT NOT NULL
            REFERENCES authority_book_narrative_projection_set(projection_set_id),
        project_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        arc_plan_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        accepted_through_chapter INTEGER NOT NULL
            CHECK (accepted_through_chapter > 0),
        acceptance_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        status TEXT NOT NULL CHECK (status IN ('COMPLETED','ABANDONED')),
        completion_evidence JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id, book_id, arc_plan_version_id)
    )
    """,
    """
    CREATE TABLE authority_narrative_obligation_state (
        project_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        obligation_id TEXT NOT NULL,
        projection_set_id TEXT NOT NULL
            REFERENCES authority_book_narrative_projection_set(projection_set_id),
        accepted_through_chapter INTEGER NOT NULL
            CHECK (accepted_through_chapter > 0),
        acceptance_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        story_state_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        obligation_type TEXT NOT NULL,
        status TEXT NOT NULL,
        state JSONB NOT NULL,
        version INTEGER NOT NULL CHECK (version > 0),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY(project_id, book_id, obligation_id)
    )
    """,
    """
    CREATE TABLE authority_narrative_retrieval_document (
        retrieval_document_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        source_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        source_artifact_type TEXT NOT NULL,
        accepted_from_chapter INTEGER NOT NULL CHECK (accepted_from_chapter >= 0),
        accepted_to_chapter INTEGER CHECK (
            accepted_to_chapter IS NULL OR accepted_to_chapter >= accepted_from_chapter
        ),
        memory_layer TEXT NOT NULL CHECK (
            memory_layer IN ('L0','L1','L2','L3','L4','L5','L6','L7','L8','L9')
        ),
        content_text TEXT NOT NULL,
        search_vector TSVECTOR GENERATED ALWAYS AS (
            to_tsvector('simple', COALESCE(content_text, ''))
        ) STORED,
        embedding JSONB,
        entity_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
        relationship_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
        character_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
        arc_plan_version_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
        obligation_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
        temporal_coordinate JSONB NOT NULL DEFAULT '{}'::jsonb,
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        projection_hash TEXT NOT NULL CHECK (
            projection_hash ~ '^sha256:[0-9a-f]{64}$'
        ),
        created_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id, book_id, source_asset_version_id, memory_layer)
    )
    """,
    """
    CREATE INDEX authority_narrative_retrieval_search_idx
    ON authority_narrative_retrieval_document USING GIN(search_vector)
    """,
    """
    CREATE TABLE authority_agent_harness_session (
        agent_session_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        workspace_id TEXT NOT NULL REFERENCES authority_workspace(workspace_id),
        operation_id TEXT NOT NULL UNIQUE REFERENCES authority_operation(operation_id),
        agent_role TEXT NOT NULL CHECK (
            agent_role IN ('STUDIO_DIRECTOR','RESEARCH_KNOWLEDGE')
        ),
        status TEXT NOT NULL CHECK (
            status IN ('READY','RUNNING','WAITING_TOOL','CHECKPOINTED','COMPLETED','FAILED','CANCELLED','ESCALATION_REQUIRED')
        ),
        accepted_boundary JSONB NOT NULL,
        tool_policy JSONB NOT NULL,
        skill_bindings JSONB NOT NULL,
        budget JSONB NOT NULL,
        usage JSONB NOT NULL,
        next_sequence BIGINT NOT NULL DEFAULT 1 CHECK (next_sequence > 0),
        version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE authority_agent_transcript_event (
        transcript_event_id TEXT PRIMARY KEY,
        agent_session_id TEXT NOT NULL
            REFERENCES authority_agent_harness_session(agent_session_id),
        sequence BIGINT NOT NULL CHECK (sequence > 0),
        request_id TEXT NOT NULL,
        turn_number INTEGER NOT NULL CHECK (turn_number >= 0),
        event_type TEXT NOT NULL CHECK (
            event_type IN (
                'REQUEST_STARTED','MODEL_MESSAGE','TOOL_REQUESTED','TOOL_OBSERVED',
                'AUTHORITY_COMMAND_SUBMITTED','REQUEST_COMMITTED','REQUEST_FAILED',
                'CHECKPOINT','SESSION_STOPPED'
            )
        ),
        operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        attempt_id TEXT REFERENCES authority_attempt(attempt_id),
        external_effect_id TEXT REFERENCES authority_external_effect(external_effect_id),
        payload JSONB NOT NULL,
        payload_hash TEXT NOT NULL CHECK (payload_hash ~ '^sha256:[0-9a-f]{64}$'),
        trace_id TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(agent_session_id, sequence)
    )
    """,
    """
    CREATE INDEX authority_agent_transcript_request_idx
    ON authority_agent_transcript_event(agent_session_id, request_id, sequence)
    """,
    """
    CREATE TABLE authority_artifact_lineage_edge (
        lineage_edge_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        book_id TEXT,
        upstream_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        downstream_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        relationship_type TEXT NOT NULL,
        semantic_dimensions JSONB NOT NULL,
        invalidation_policy TEXT NOT NULL CHECK (
            invalidation_policy IN ('PROPAGATE','REQUALIFY','INFORMATIONAL','IMMUNE_ACCEPTED_HISTORY')
        ),
        context_fingerprint TEXT,
        created_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id, upstream_asset_version_id, downstream_asset_version_id, relationship_type),
        CHECK (upstream_asset_version_id <> downstream_asset_version_id)
    )
    """,
    """
    CREATE INDEX authority_artifact_lineage_upstream_idx
    ON authority_artifact_lineage_edge(project_id, upstream_asset_version_id)
    """,
    """
    CREATE INDEX authority_artifact_lineage_downstream_idx
    ON authority_artifact_lineage_edge(project_id, downstream_asset_version_id)
    """,
    """
    CREATE TABLE authority_artifact_invalidation (
        invalidation_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        book_id TEXT,
        target_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        source_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        semantic_diff JSONB NOT NULL,
        status TEXT NOT NULL CHECK (
            status IN ('OPEN','REGENERATING','REQUALIFIED','RESOLVED','IMMUNE')
        ),
        reason TEXT NOT NULL,
        created_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        resolved_by_operation_id TEXT REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        resolved_at TIMESTAMPTZ,
        UNIQUE(project_id, target_asset_version_id, source_asset_version_id, status)
    )
    """,
    """
    CREATE INDEX authority_book_narrative_projection_run_idx
    ON authority_book_narrative_projection_set(book_run_id)
    """,
    """
    CREATE INDEX authority_book_narrative_projection_outcome_idx
    ON authority_book_narrative_projection_set(chapter_outcome_asset_version_id)
    """,
    """
    CREATE INDEX authority_book_narrative_projection_story_state_idx
    ON authority_book_narrative_projection_set(story_state_asset_version_id)
    """,
    """
    CREATE INDEX authority_book_narrative_projection_canon_idx
    ON authority_book_narrative_projection_set(canon_snapshot_asset_version_id)
    """,
    """
    CREATE INDEX authority_book_acceptance_longform_projection_idx
    ON authority_book_chapter_acceptance(longform_projection_set_id)
    """,
    """
    CREATE INDEX authority_book_active_longform_projection_idx
    ON authority_book_production(active_longform_projection_set_id)
    """,
    """
    CREATE INDEX authority_arc_progress_v2_projection_idx
    ON authority_arc_progress_v2(projection_set_id)
    """,
    """
    CREATE INDEX authority_arc_progress_v2_acceptance_operation_idx
    ON authority_arc_progress_v2(acceptance_operation_id)
    """,
    """
    CREATE INDEX authority_arc_progress_v2_outcome_idx
    ON authority_arc_progress_v2(chapter_outcome_asset_version_id)
    """,
    """
    CREATE INDEX authority_arc_actual_projection_idx
    ON authority_arc_actual_state(projection_set_id)
    """,
    """
    CREATE INDEX authority_arc_actual_acceptance_operation_idx
    ON authority_arc_actual_state(acceptance_operation_id)
    """,
    """
    CREATE INDEX authority_arc_checkpoint_v2_projection_idx
    ON authority_arc_checkpoint_v2(projection_set_id)
    """,
    """
    CREATE INDEX authority_arc_checkpoint_v2_acceptance_operation_idx
    ON authority_arc_checkpoint_v2(acceptance_operation_id)
    """,
    """
    CREATE INDEX authority_arc_checkpoint_v2_progress_idx
    ON authority_arc_checkpoint_v2(progress_id)
    """,
    """
    CREATE INDEX authority_arc_outcome_v2_projection_idx
    ON authority_arc_outcome_v2(projection_set_id)
    """,
    """
    CREATE INDEX authority_arc_outcome_v2_acceptance_operation_idx
    ON authority_arc_outcome_v2(acceptance_operation_id)
    """,
    """
    CREATE INDEX authority_narrative_obligation_projection_idx
    ON authority_narrative_obligation_state(projection_set_id)
    """,
    """
    CREATE INDEX authority_narrative_obligation_acceptance_operation_idx
    ON authority_narrative_obligation_state(acceptance_operation_id)
    """,
    """
    CREATE INDEX authority_narrative_obligation_story_state_idx
    ON authority_narrative_obligation_state(story_state_asset_version_id)
    """,
    """
    CREATE INDEX authority_narrative_retrieval_created_operation_idx
    ON authority_narrative_retrieval_document(created_by_operation_id)
    """,
    """
    CREATE INDEX authority_agent_harness_project_idx
    ON authority_agent_harness_session(project_id)
    """,
    """
    CREATE INDEX authority_agent_harness_workspace_idx
    ON authority_agent_harness_session(workspace_id)
    """,
    """
    CREATE INDEX authority_agent_transcript_operation_idx
    ON authority_agent_transcript_event(operation_id)
    """,
    """
    CREATE INDEX authority_agent_transcript_attempt_idx
    ON authority_agent_transcript_event(attempt_id)
    """,
    """
    CREATE INDEX authority_agent_transcript_effect_idx
    ON authority_agent_transcript_event(external_effect_id)
    """,
    """
    CREATE INDEX authority_artifact_lineage_operation_idx
    ON authority_artifact_lineage_edge(created_by_operation_id)
    """,
    """
    CREATE INDEX authority_artifact_invalidation_created_operation_idx
    ON authority_artifact_invalidation(created_by_operation_id)
    """,
    """
    CREATE INDEX authority_artifact_invalidation_resolved_operation_idx
    ON authority_artifact_invalidation(resolved_by_operation_id)
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

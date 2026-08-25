from __future__ import annotations


MIGRATION_ID = "20260825_0100_hierarchy_closure"
DOWN_REVISION = "20260825_0099_creative_engineering_convergence"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = (
    "supersede future Foundation/Realization bindings through a later migration; "
    "accepted Chapter evidence and execution history remain immutable"
)


UPGRADE_STATEMENTS = [
    """
    UPDATE authority_operation_definition
       SET enabled=FALSE
     WHERE name IN (
       'agent.chapter_binding.register',
       'agent.chapter_binding.activate',
       'agent.candidate.execute'
     )
        OR (name='agent.session.execute' AND definition_version='2.0.0')
    """,
    """
    ALTER TABLE authority_story_design_version_state
    ADD COLUMN design_scope TEXT
    """,
    """
    UPDATE authority_story_design_version_state
    SET design_scope=CASE generator_operation_name
        WHEN 'creative.candidates.generate' THEN 'CREATIVE_FOUNDATION'
        WHEN 'theme.candidates.generate' THEN 'THEME_CONTRACT'
        WHEN 'ending.intent.generate' THEN 'ENDING_INTENT'
        WHEN 'reader.promise.generate' THEN 'READER_PROMISE'
        WHEN 'world.design.generate' THEN 'WORLD_BIBLE'
        WHEN 'character.cast.generate' THEN 'CHARACTER_CAST'
        WHEN 'book_plan.generate' THEN 'BOOK_PLAN'
        WHEN 'volume_plan.generate' THEN 'VOLUME_PLAN'
        WHEN 'arc_plan.generate' THEN 'ARC_PLAN'
        WHEN 'chapter_group_plan.generate' THEN 'CHAPTER_GROUP_PLAN'
        WHEN 'chapter_plan.generate' THEN 'CHAPTER_PLAN'
        ELSE 'LEGACY_UNCLASSIFIED'
    END
    """,
    """
    ALTER TABLE authority_story_design_version_state
    ALTER COLUMN design_scope SET NOT NULL,
    ADD CONSTRAINT authority_story_design_scope_check CHECK (design_scope IN (
        'CREATIVE_FOUNDATION','THEME_CONTRACT','ENDING_INTENT','READER_PROMISE',
        'WORLD_BIBLE','CHARACTER_CAST','BOOK_PLAN','VOLUME_PLAN','ARC_PLAN',
        'CHAPTER_GROUP_PLAN','CHAPTER_PLAN','LEGACY_UNCLASSIFIED'
    ))
    """,
    """
    ALTER TABLE authority_story_design_version_state
    DROP CONSTRAINT authority_story_design_version_state_planning_scope_check
    """,
    """
    UPDATE authority_story_design_version_state
       SET planning_scope='NOT_APPLICABLE'
     WHERE generator_operation_name IN (
       'creative.candidates.generate',
       'theme.candidates.generate',
       'ending.intent.generate',
       'reader.promise.generate',
       'world.design.generate',
       'character.cast.generate'
     )
    """,
    """
    ALTER TABLE authority_story_design_version_state
    ADD CONSTRAINT authority_story_design_version_state_planning_scope_check
    CHECK (planning_scope IN (
        'NOT_APPLICABLE','BOOK','VOLUME','ARC','CHAPTER_GROUP','CHAPTER'
    ))
    """,
    """
    ALTER TABLE authority_narrative_design_qualification
    DROP CONSTRAINT authority_narrative_design_qualification_design_layer_check
    """,
    """
    ALTER TABLE authority_narrative_design_qualification
    ADD CONSTRAINT authority_narrative_design_qualification_design_layer_check
    CHECK (design_layer IN (
        'STORY_INTENT', 'STORY_FOUNDATION', 'BOOK_ARCHITECTURE',
        'VOLUME_ARCHITECTURE', 'NARRATIVE_ARC_GRAPH',
        'CHARACTER_DEVELOPMENT', 'DISCLOSURE_OBLIGATION',
        'NARRATIVE_SCHEDULING', 'NARRATIVE_REALIZATION_PROOF',
        'CHAPTER_EXECUTION_PLAN', 'SCENE_ARCHITECTURE'
    ))
    """,
    """
    CREATE TABLE authority_story_formation_run (
        formation_run_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        workspace_id TEXT NOT NULL REFERENCES authority_workspace(workspace_id),
        book_id TEXT NOT NULL REFERENCES authority_book(book_id),
        root_operation_id TEXT NOT NULL UNIQUE
            REFERENCES authority_operation(operation_id),
        stable_idempotency_key TEXT NOT NULL,
        expected_book_version BIGINT NOT NULL,
        lifecycle TEXT NOT NULL,
        current_stage TEXT NOT NULL,
        formation_policy_version TEXT NOT NULL,
        frozen_stage_inputs JSONB NOT NULL,
        frozen_input_digest TEXT NOT NULL,
        book_design_asset_version_id TEXT
            REFERENCES authority_asset_version(asset_version_id),
        book_design_content_hash TEXT,
        foundation_set_digest TEXT,
        failure JSONB NOT NULL DEFAULT '{}'::jsonb,
        recovery_instruction JSONB NOT NULL DEFAULT '{}'::jsonb,
        version BIGINT NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        FOREIGN KEY(project_id, book_id)
            REFERENCES authority_book(project_id, book_id),
        UNIQUE(project_id, book_id, stable_idempotency_key),
        CHECK (expected_book_version >= 0),
        CHECK (lifecycle IN (
            'ADMITTED','RUNNING','WAITING_APPROVAL','READY','FAILED','ABORTED'
        )),
        CHECK (current_stage IN (
            'CREATIVE_SEARCH','CREATIVE_FOUNDATION','THEME_CONTRACT',
            'ENDING_INTENT','READER_PROMISE','WORLD_BIBLE','CHARACTER_CAST',
            'BOOK_DESIGN','COMPLETE'
        )),
        CHECK (
            foundation_set_digest IS NULL
            OR foundation_set_digest LIKE 'sha256:%'
        ),
        CHECK (jsonb_typeof(frozen_stage_inputs)='object'),
        CHECK (frozen_input_digest LIKE 'sha256:%'),
        CHECK (
            (book_design_asset_version_id IS NULL AND book_design_content_hash IS NULL)
            OR (
                book_design_asset_version_id IS NOT NULL
                AND book_design_content_hash LIKE 'sha256:%'
            )
        ),
        CHECK (jsonb_typeof(failure)='object'),
        CHECK (jsonb_typeof(recovery_instruction)='object')
    )
    """,
    """
    CREATE TABLE authority_story_formation_stage (
        formation_stage_id TEXT PRIMARY KEY,
        formation_run_id TEXT NOT NULL
            REFERENCES authority_story_formation_run(formation_run_id),
        stage TEXT NOT NULL,
        attempt_ordinal INTEGER NOT NULL,
        status TEXT NOT NULL,
        upstream_digest TEXT,
        generation_operation_id TEXT REFERENCES authority_operation(operation_id),
        candidate_asset_version_id TEXT
            REFERENCES authority_asset_version(asset_version_id),
        candidate_content_hash TEXT,
        qualification_evidence_asset_version_id TEXT
            REFERENCES authority_asset_version(asset_version_id),
        qualification_hash TEXT,
        activation_operation_id TEXT REFERENCES authority_operation(operation_id),
        binding JSONB NOT NULL DEFAULT '{}'::jsonb,
        checkpoint JSONB NOT NULL DEFAULT '{}'::jsonb,
        failure JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(formation_run_id, stage, attempt_ordinal),
        CHECK (attempt_ordinal > 0),
        CHECK (stage IN (
            'CREATIVE_SEARCH','CREATIVE_FOUNDATION','THEME_CONTRACT',
            'ENDING_INTENT','READER_PROMISE','WORLD_BIBLE','CHARACTER_CAST',
            'BOOK_DESIGN'
        )),
        CHECK (status IN (
            'PENDING','RUNNING','WAITING_APPROVAL','QUALIFIED','ACTIVE',
            'FAILED','SUPERSEDED'
        )),
        CHECK (upstream_digest IS NULL OR upstream_digest LIKE 'sha256:%'),
        CHECK (
            candidate_content_hash IS NULL
            OR candidate_content_hash LIKE 'sha256:%'
        ),
        CHECK (
            qualification_hash IS NULL OR qualification_hash LIKE 'sha256:%'
        ),
        CHECK (jsonb_typeof(binding)='object'),
        CHECK (jsonb_typeof(checkpoint)='object'),
        CHECK (jsonb_typeof(failure)='object')
    )
    """,
    """
    CREATE TABLE authority_book_opening_run (
        opening_run_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        workspace_id TEXT NOT NULL REFERENCES authority_workspace(workspace_id),
        book_id TEXT NOT NULL REFERENCES authority_book(book_id),
        root_operation_id TEXT NOT NULL UNIQUE
            REFERENCES authority_operation(operation_id),
        stable_idempotency_key TEXT NOT NULL,
        lifecycle TEXT NOT NULL,
        frozen_request JSONB NOT NULL,
        frozen_request_digest TEXT NOT NULL,
        result JSONB NOT NULL DEFAULT '{}'::jsonb,
        failure JSONB NOT NULL DEFAULT '{}'::jsonb,
        recovery_instruction JSONB NOT NULL DEFAULT '{}'::jsonb,
        version BIGINT NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        FOREIGN KEY(project_id, book_id)
            REFERENCES authority_book(project_id, book_id),
        UNIQUE(project_id, book_id, stable_idempotency_key),
        CHECK (lifecycle IN (
            'ADMITTED','RUNNING','COMPLETE','FAILED','ABORTED'
        )),
        CHECK (jsonb_typeof(frozen_request)='object'),
        CHECK (frozen_request_digest LIKE 'sha256:%'),
        CHECK (jsonb_typeof(result)='object'),
        CHECK (jsonb_typeof(failure)='object'),
        CHECK (jsonb_typeof(recovery_instruction)='object')
    )
    """,
    """
    CREATE TABLE authority_book_foundation_binding (
        foundation_binding_id TEXT PRIMARY KEY,
        formation_run_id TEXT NOT NULL
            REFERENCES authority_story_formation_run(formation_run_id),
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        book_id TEXT NOT NULL REFERENCES authority_book(book_id),
        set_generation BIGINT NOT NULL,
        foundation_role TEXT NOT NULL,
        authority_name TEXT NOT NULL,
        asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        content_hash TEXT NOT NULL,
        schema_version TEXT NOT NULL,
        qualification_evidence_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        qualification_hash TEXT NOT NULL,
        activation_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        upstream_digest TEXT,
        freshness TEXT NOT NULL,
        activated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        retired_at TIMESTAMPTZ,
        FOREIGN KEY(project_id, book_id)
            REFERENCES authority_book(project_id, book_id),
        UNIQUE(project_id, book_id, set_generation, foundation_role),
        CHECK (set_generation > 0),
        CHECK (foundation_role IN (
            'CREATIVE_FOUNDATION','THEME_CONTRACT','ENDING_INTENT',
            'READER_PROMISE','WORLD_BIBLE','CHARACTER_CAST'
        )),
        CHECK (authority_name='STORY_DESIGN_AUTHORITY'),
        CHECK (content_hash LIKE 'sha256:%'),
        CHECK (qualification_hash LIKE 'sha256:%'),
        CHECK (upstream_digest IS NULL OR upstream_digest LIKE 'sha256:%'),
        CHECK (freshness IN ('CURRENT','IMPACTED','STALE')),
        CHECK (
            (freshness='CURRENT' AND retired_at IS NULL)
            OR freshness<>'CURRENT'
        )
    )
    """,
    """
    CREATE UNIQUE INDEX authority_book_foundation_one_current_role_idx
    ON authority_book_foundation_binding(project_id, book_id, foundation_role)
    WHERE freshness='CURRENT' AND retired_at IS NULL
    """,
    """
    CREATE INDEX authority_story_formation_claim_idx
    ON authority_story_formation_run(lifecycle, updated_at, formation_run_id)
    WHERE lifecycle IN ('ADMITTED','RUNNING')
    """,
    """
    CREATE TABLE authority_narrative_realization (
        realization_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        book_id TEXT NOT NULL REFERENCES authority_book(book_id),
        chapter_group_plan_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        chapter_group_content_hash TEXT NOT NULL,
        chapter_start INTEGER NOT NULL,
        chapter_end INTEGER NOT NULL,
        foundation_set_digest TEXT NOT NULL,
        accepted_through_chapter INTEGER NOT NULL,
        story_state_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        story_state_content_hash TEXT NOT NULL,
        canon_snapshot_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        canon_snapshot_content_hash TEXT NOT NULL,
        arc_working_set_digest TEXT NOT NULL,
        arc_plan_bindings JSONB NOT NULL,
        proof JSONB NOT NULL,
        content_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        content_hash TEXT NOT NULL,
        proof_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        proof_hash TEXT NOT NULL,
        contract_digest TEXT NOT NULL,
        lifecycle TEXT NOT NULL,
        qualification_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        approval_operation_id TEXT REFERENCES authority_operation(operation_id),
        frozen_by_operation_id TEXT REFERENCES authority_operation(operation_id),
        invalidated_by_operation_id TEXT REFERENCES authority_operation(operation_id),
        executed_by_operation_id TEXT REFERENCES authority_operation(operation_id),
        version BIGINT NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        FOREIGN KEY(project_id, book_id)
            REFERENCES authority_book(project_id, book_id),
        UNIQUE(project_id, content_asset_version_id),
        UNIQUE(project_id, contract_digest),
        CHECK (chapter_start > 0 AND chapter_end >= chapter_start),
        CHECK (chapter_end - chapter_start + 1 BETWEEN 1 AND 8),
        CHECK (accepted_through_chapter >= 0),
        CHECK (chapter_group_content_hash LIKE 'sha256:%'),
        CHECK (foundation_set_digest LIKE 'sha256:%'),
        CHECK (story_state_content_hash LIKE 'sha256:%'),
        CHECK (canon_snapshot_content_hash LIKE 'sha256:%'),
        CHECK (arc_working_set_digest LIKE 'sha256:%'),
        CHECK (jsonb_typeof(arc_plan_bindings)='array'),
        CHECK (jsonb_array_length(arc_plan_bindings) > 0),
        CHECK (jsonb_typeof(proof)='object'),
        CHECK (content_hash LIKE 'sha256:%'),
        CHECK (proof_hash LIKE 'sha256:%'),
        CHECK (contract_digest LIKE 'sha256:%'),
        CHECK (lifecycle IN (
            'PROPOSED','QUALIFIED','APPROVED','FROZEN','EXECUTED',
            'REJECTED','STALE','SUPERSEDED'
        ))
    )
    """,
    """
    CREATE TABLE authority_narrative_realization_current (
        project_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        chapter_group_plan_version_id TEXT NOT NULL,
        realization_id TEXT NOT NULL UNIQUE
            REFERENCES authority_narrative_realization(realization_id),
        bound_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        bound_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY(project_id, book_id, chapter_group_plan_version_id),
        FOREIGN KEY(project_id, book_id)
            REFERENCES authority_book(project_id, book_id)
    )
    """,
    """
    CREATE TABLE authority_narrative_realization_event (
        realization_id TEXT NOT NULL
            REFERENCES authority_narrative_realization(realization_id),
        event_id TEXT NOT NULL,
        slice_id TEXT NOT NULL,
        chapter_number INTEGER NOT NULL,
        required BOOLEAN NOT NULL,
        event_order INTEGER NOT NULL,
        planned_event JSONB NOT NULL,
        planned_event_hash TEXT NOT NULL,
        PRIMARY KEY(realization_id, event_id),
        UNIQUE(realization_id, event_order),
        CHECK (chapter_number > 0),
        CHECK (event_order > 0),
        CHECK (jsonb_typeof(planned_event)='object'),
        CHECK (planned_event_hash LIKE 'sha256:%')
    )
    """,
    """
    CREATE TABLE authority_narrative_realization_consumption (
        consumption_id TEXT PRIMARY KEY,
        realization_id TEXT NOT NULL,
        planned_event_id TEXT NOT NULL,
        chapter_plan_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        acceptance_id TEXT NOT NULL
            REFERENCES authority_book_chapter_acceptance(acceptance_id),
        chapter_outcome_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        observed_event_id TEXT,
        observed_event_hash TEXT,
        coverage_status TEXT NOT NULL,
        evidence JSONB NOT NULL,
        consumed_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        FOREIGN KEY(realization_id, planned_event_id)
            REFERENCES authority_narrative_realization_event(realization_id, event_id),
        UNIQUE(realization_id, planned_event_id),
        CHECK (coverage_status IN (
            'OBSERVED','ACCEPTED','DEVIATED','NOT_OBSERVED'
        )),
        CHECK (
            (coverage_status IN ('OBSERVED','ACCEPTED','DEVIATED')
             AND observed_event_id IS NOT NULL
             AND observed_event_hash LIKE 'sha256:%')
            OR (coverage_status='NOT_OBSERVED'
                AND observed_event_id IS NULL
                AND observed_event_hash IS NULL)
        ),
        CHECK (jsonb_typeof(evidence)='object')
    )
    """,
    """
    CREATE TABLE authority_narrative_realization_deviation (
        deviation_id TEXT PRIMARY KEY,
        realization_id TEXT NOT NULL
            REFERENCES authority_narrative_realization(realization_id),
        acceptance_id TEXT NOT NULL
            REFERENCES authority_book_chapter_acceptance(acceptance_id),
        chapter_plan_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        deviation_kind TEXT NOT NULL,
        affected_future_from_chapter INTEGER NOT NULL,
        evidence JSONB NOT NULL,
        evidence_hash TEXT NOT NULL,
        replan_request_operation_id TEXT
            REFERENCES authority_operation(operation_id),
        created_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(realization_id, acceptance_id, deviation_kind, evidence_hash),
        CHECK (deviation_kind IN (
            'MISSING_REQUIRED_EVENT','UNPLANNED_EVENT','STATE_DELTA_DRIFT',
            'KNOWLEDGE_BOUNDARY_DRIFT','CAUSALITY_DRIFT'
        )),
        CHECK (affected_future_from_chapter > 0),
        CHECK (jsonb_typeof(evidence)='object'),
        CHECK (evidence_hash LIKE 'sha256:%')
    )
    """,
    """
    CREATE INDEX authority_narrative_realization_query_idx
    ON authority_narrative_realization(
        project_id, book_id, chapter_group_plan_version_id, lifecycle, updated_at
    )
    """,
    """
    CREATE INDEX authority_narrative_realization_consumption_outcome_idx
    ON authority_narrative_realization_consumption(
        chapter_outcome_asset_version_id, realization_id
    )
    """,
    """
    ALTER TABLE authority_book_chapter_request
    ADD COLUMN narrative_realization_id TEXT
        REFERENCES authority_narrative_realization(realization_id),
    ADD COLUMN narrative_realization_slice_id TEXT,
    ADD COLUMN narrative_realization_contract_digest TEXT
    """,
    """
    ALTER TABLE authority_book_chapter_request
    ADD CONSTRAINT authority_book_chapter_realization_digest_check
    CHECK (
        narrative_realization_contract_digest IS NULL
        OR narrative_realization_contract_digest LIKE 'sha256:%'
    )
    """,
    """
    ALTER TABLE authority_book_production_input_snapshot
    ADD COLUMN foundation_set JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN foundation_set_digest TEXT NOT NULL
        DEFAULT 'sha256:0000000000000000000000000000000000000000000000000000000000000000',
    ADD COLUMN book_design_schema_version TEXT NOT NULL DEFAULT 'legacy'
    """,
    """
    ALTER TABLE authority_book_production_input_snapshot
    ADD CONSTRAINT authority_book_production_foundation_set_check
    CHECK (jsonb_typeof(foundation_set)='object'),
    ADD CONSTRAINT authority_book_production_foundation_digest_check
    CHECK (foundation_set_digest LIKE 'sha256:%')
    """,
    """
    CREATE INDEX authority_story_formation_workspace_fk_idx
    ON authority_story_formation_run(workspace_id)
    """,
    """
    CREATE INDEX authority_book_opening_workspace_fk_idx
    ON authority_book_opening_run(workspace_id)
    """,
    """
    CREATE INDEX authority_story_formation_book_design_fk_idx
    ON authority_story_formation_run(book_design_asset_version_id)
    """,
    """
    CREATE INDEX authority_story_formation_stage_generation_fk_idx
    ON authority_story_formation_stage(generation_operation_id)
    """,
    """
    CREATE INDEX authority_story_formation_stage_candidate_fk_idx
    ON authority_story_formation_stage(candidate_asset_version_id)
    """,
    """
    CREATE INDEX authority_story_formation_stage_qualification_fk_idx
    ON authority_story_formation_stage(qualification_evidence_asset_version_id)
    """,
    """
    CREATE INDEX authority_story_formation_stage_activation_fk_idx
    ON authority_story_formation_stage(activation_operation_id)
    """,
    """
    CREATE INDEX authority_book_foundation_formation_fk_idx
    ON authority_book_foundation_binding(formation_run_id)
    """,
    """
    CREATE INDEX authority_book_foundation_asset_fk_idx
    ON authority_book_foundation_binding(asset_version_id)
    """,
    """
    CREATE INDEX authority_book_foundation_qualification_fk_idx
    ON authority_book_foundation_binding(qualification_evidence_asset_version_id)
    """,
    """
    CREATE INDEX authority_book_foundation_activation_fk_idx
    ON authority_book_foundation_binding(activation_operation_id)
    """,
    """
    CREATE INDEX authority_realization_story_state_fk_idx
    ON authority_narrative_realization(story_state_asset_version_id)
    """,
    """
    CREATE INDEX authority_realization_canon_fk_idx
    ON authority_narrative_realization(canon_snapshot_asset_version_id)
    """,
    """
    CREATE INDEX authority_realization_proof_fk_idx
    ON authority_narrative_realization(proof_asset_version_id)
    """,
    """
    CREATE INDEX authority_realization_qualification_operation_fk_idx
    ON authority_narrative_realization(qualification_operation_id)
    """,
    """
    CREATE INDEX authority_realization_approval_operation_fk_idx
    ON authority_narrative_realization(approval_operation_id)
    """,
    """
    CREATE INDEX authority_realization_frozen_operation_fk_idx
    ON authority_narrative_realization(frozen_by_operation_id)
    """,
    """
    CREATE INDEX authority_realization_invalidated_operation_fk_idx
    ON authority_narrative_realization(invalidated_by_operation_id)
    """,
    """
    CREATE INDEX authority_realization_executed_operation_fk_idx
    ON authority_narrative_realization(executed_by_operation_id)
    """,
    """
    CREATE INDEX authority_realization_current_operation_fk_idx
    ON authority_narrative_realization_current(bound_by_operation_id)
    """,
    """
    CREATE INDEX authority_realization_consumption_plan_fk_idx
    ON authority_narrative_realization_consumption(chapter_plan_asset_version_id)
    """,
    """
    CREATE INDEX authority_realization_consumption_acceptance_fk_idx
    ON authority_narrative_realization_consumption(acceptance_id)
    """,
    """
    CREATE INDEX authority_realization_consumption_operation_fk_idx
    ON authority_narrative_realization_consumption(consumed_by_operation_id)
    """,
    """
    CREATE INDEX authority_realization_deviation_plan_fk_idx
    ON authority_narrative_realization_deviation(chapter_plan_asset_version_id)
    """,
    """
    CREATE INDEX authority_realization_deviation_replan_fk_idx
    ON authority_narrative_realization_deviation(replan_request_operation_id)
    """,
    """
    CREATE INDEX authority_realization_deviation_operation_fk_idx
    ON authority_narrative_realization_deviation(created_by_operation_id)
    """,
    """
    CREATE INDEX authority_book_chapter_request_realization_fk_idx
    ON authority_book_chapter_request(narrative_realization_id)
    """,
]

DOWNGRADE_STATEMENTS: list[str] = []


def upgrade(connection) -> None:
    with connection.cursor() as cursor:
        for statement in UPGRADE_STATEMENTS:
            cursor.execute(statement)


__all__ = [
    "BACKUP_REQUIRED",
    "DOWN_REVISION",
    "DOWNGRADE_STATEMENTS",
    "FORWARD_FIX",
    "FORWARD_ONLY",
    "MIGRATION_ID",
    "UPGRADE_STATEMENTS",
    "upgrade",
]

from __future__ import annotations


MIGRATION_ID = "20260825_0098_narrative_evolution_engine"
DOWN_REVISION = "20260824_0097_narrative_evaluator_codex_lineage"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = (
    "repair narrative-search lifecycle rows with a later forward migration; "
    "candidate projections and selection decisions are immutable evidence"
)


UPGRADE_STATEMENTS = [
    """
    CREATE TABLE authority_story_narrative_search (
        search_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        workspace_id TEXT NOT NULL REFERENCES authority_workspace(workspace_id),
        book_id TEXT NOT NULL REFERENCES authority_book(book_id),
        book_run_id TEXT REFERENCES authority_book_production(book_run_id),
        generator_operation_name TEXT NOT NULL,
        planning_scope TEXT NOT NULL,
        logical_key TEXT NOT NULL,
        parent_version_id TEXT REFERENCES authority_asset_version(asset_version_id),
        parent_state_asset_version_id TEXT REFERENCES authority_asset_version(asset_version_id),
        parent_state_content_hash TEXT,
        accepted_through_chapter INTEGER NOT NULL,
        planning_horizon JSONB NOT NULL,
        desired_transformation JSONB NOT NULL,
        hard_constraints JSONB NOT NULL,
        input_snapshot_hash TEXT NOT NULL,
        strategy_directives JSONB NOT NULL,
        candidate_target INTEGER NOT NULL,
        status TEXT NOT NULL,
        selected_candidate_asset_version_id TEXT REFERENCES authority_asset_version(asset_version_id),
        stable_idempotency_key TEXT NOT NULL,
        version BIGINT NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        FOREIGN KEY(project_id, workspace_id, book_id)
            REFERENCES authority_book(project_id, workspace_id, book_id),
        UNIQUE(project_id, book_id, stable_idempotency_key),
        CHECK (generator_operation_name IN (
            'book_plan.generate', 'volume_plan.generate', 'arc_plan.generate',
            'chapter_group_plan.generate'
        )),
        CHECK (planning_scope IN ('BOOK', 'VOLUME', 'ARC', 'CHAPTER_GROUP')),
        CHECK (accepted_through_chapter >= 0),
        CHECK (accepted_through_chapter = 0 OR book_run_id IS NOT NULL),
        CHECK (jsonb_typeof(planning_horizon)='object'),
        CHECK (jsonb_typeof(desired_transformation)='object'),
        CHECK (jsonb_typeof(hard_constraints)='array'),
        CHECK (jsonb_typeof(strategy_directives)='array'),
        CHECK (jsonb_array_length(strategy_directives)=candidate_target),
        CHECK (candidate_target BETWEEN 2 AND 5),
        CHECK (input_snapshot_hash LIKE 'sha256:%'),
        CHECK (parent_state_content_hash IS NULL OR parent_state_content_hash LIKE 'sha256:%'),
        CHECK (status IN (
            'OPEN', 'GENERATING', 'READY_FOR_SELECTION', 'SELECTED',
            'ACTIVATED', 'STALE', 'FAILED'
        )),
        CHECK ((status IN ('SELECTED', 'ACTIVATED')) =
               (selected_candidate_asset_version_id IS NOT NULL)),
        CHECK ((parent_state_asset_version_id IS NULL) =
               (parent_state_content_hash IS NULL))
    )
    """,
    """
    CREATE TABLE authority_story_narrative_search_candidate (
        membership_id TEXT PRIMARY KEY,
        search_id TEXT NOT NULL REFERENCES authority_story_narrative_search(search_id),
        branch_key TEXT NOT NULL,
        candidate_asset_version_id TEXT NOT NULL UNIQUE REFERENCES authority_asset_version(asset_version_id),
        generation_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        projection JSONB NOT NULL,
        projection_hash TEXT NOT NULL,
        strategy_fingerprint TEXT NOT NULL,
        comparison_score NUMERIC(8, 6) NOT NULL,
        qualification_hash TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(search_id, branch_key),
        CHECK (jsonb_typeof(projection)='object'),
        CHECK (projection_hash LIKE 'sha256:%'),
        CHECK (qualification_hash LIKE 'sha256:%'),
        CHECK (comparison_score BETWEEN 0 AND 1),
        CHECK (status IN ('ELIGIBLE', 'REJECTED', 'SELECTED'))
    )
    """,
    """
    CREATE TABLE authority_story_narrative_search_decision (
        decision_id TEXT PRIMARY KEY,
        search_id TEXT NOT NULL UNIQUE REFERENCES authority_story_narrative_search(search_id),
        selected_candidate_asset_version_id TEXT NOT NULL REFERENCES authority_asset_version(asset_version_id),
        candidate_set_hash TEXT NOT NULL,
        comparison JSONB NOT NULL,
        comparison_hash TEXT NOT NULL,
        selection_reason JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CHECK (candidate_set_hash LIKE 'sha256:%'),
        CHECK (comparison_hash LIKE 'sha256:%'),
        CHECK (jsonb_typeof(comparison)='object'),
        CHECK (jsonb_typeof(selection_reason)='array')
    )
    """,
    """
    ALTER TABLE authority_story_planning_generation
        ADD COLUMN narrative_search_id TEXT REFERENCES authority_story_narrative_search(search_id),
        ADD COLUMN narrative_search_branch_key TEXT,
        ADD CHECK ((narrative_search_id IS NULL) = (narrative_search_branch_key IS NULL))
    """,
    """
    CREATE INDEX authority_story_narrative_search_open_idx
        ON authority_story_narrative_search(project_id, book_id, status, created_at)
        WHERE status IN ('OPEN', 'GENERATING', 'READY_FOR_SELECTION')
    """,
    """
    CREATE INDEX authority_story_narrative_search_candidate_search_idx
        ON authority_story_narrative_search_candidate(search_id, status, branch_key)
    """,
    """
    CREATE INDEX authority_story_planning_generation_search_idx
        ON authority_story_planning_generation(narrative_search_id, narrative_search_branch_key)
        WHERE narrative_search_id IS NOT NULL
    """,
    """
    CREATE INDEX authority_story_narrative_search_scope_fk_idx
        ON authority_story_narrative_search(project_id, workspace_id, book_id)
    """,
    """
    CREATE INDEX authority_story_narrative_search_workspace_fk_idx
        ON authority_story_narrative_search(workspace_id)
    """,
    """
    CREATE INDEX authority_story_narrative_search_book_run_fk_idx
        ON authority_story_narrative_search(book_run_id)
        WHERE book_run_id IS NOT NULL
    """,
    """
    CREATE INDEX authority_story_narrative_search_parent_fk_idx
        ON authority_story_narrative_search(parent_version_id)
        WHERE parent_version_id IS NOT NULL
    """,
    """
    CREATE INDEX authority_story_narrative_search_parent_state_fk_idx
        ON authority_story_narrative_search(parent_state_asset_version_id)
        WHERE parent_state_asset_version_id IS NOT NULL
    """,
    """
    CREATE INDEX authority_story_narrative_search_selected_fk_idx
        ON authority_story_narrative_search(selected_candidate_asset_version_id)
        WHERE selected_candidate_asset_version_id IS NOT NULL
    """,
    """
    CREATE INDEX authority_story_narrative_search_candidate_generation_fk_idx
        ON authority_story_narrative_search_candidate(generation_operation_id)
    """,
    """
    CREATE INDEX authority_story_narrative_search_decision_selected_fk_idx
        ON authority_story_narrative_search_decision(selected_candidate_asset_version_id)
    """,
    """
    CREATE INDEX authority_retrieval_candidate_attempt_fence_fk_idx
        ON authority_retrieval_candidate_snapshot(attempt_id, fencing_token)
    """,
    """
    CREATE INDEX authority_retrieval_candidate_attempt_operation_fk_idx
        ON authority_retrieval_candidate_snapshot(attempt_id, operation_id)
    """,
    """
    CREATE OR REPLACE VIEW authority_context_runtime_usage_projection AS
    SELECT context_asset.project_id,
           COALESCE(context_version.content->>'book_id', '') AS book_id,
           context_version.asset_version_id AS context_bundle_asset_version_id,
           context_output.operation_id AS context_build_operation_id,
           context_operation.trace_id,
           context_version.content->'context_manifest'->'task'
             ->>'target_capability_id' AS target_capability_id,
           context_version.content->'context_manifest'->'task'
             ->>'created_by_operation_id' AS manifest_operation_id,
           context_version.content->'context_manifest'->'narrative_position'
             AS narrative_position,
           context_version.content->'context_manifest'->'authority_state_boundary'
             AS authority_state_boundary,
           selected.value->>'asset_version_id' AS selected_asset_version_id,
           selected.value->>'asset_type' AS selected_asset_type,
           selected.value->>'inclusion_reason' AS inclusion_reason,
           selected.value->>'narrative_function' AS narrative_function,
           selected.value->>'allowed_use' AS allowed_use,
           consumer.operation_id AS consumer_operation_id,
           consumer.definition_name AS consumer_definition_name,
           consumer.status AS consumer_status,
           result.asset_version_id AS result_asset_version_id,
           result_asset.asset_type AS result_asset_type,
           context_operation.created_at AS context_built_at,
           consumer.updated_at AS consumed_at
    FROM authority_operation_output_asset AS context_output
    JOIN authority_operation AS context_operation
      ON context_operation.operation_id=context_output.operation_id
     AND context_operation.status='SUCCEEDED'
    JOIN authority_asset_version AS context_version
      ON context_version.asset_version_id=context_output.asset_version_id
    JOIN authority_asset AS context_asset
      ON context_asset.asset_id=context_version.asset_id
     AND context_asset.asset_type='context_bundle'
    CROSS JOIN LATERAL jsonb_array_elements(
      COALESCE(
        context_version.content->'context_manifest'->'selected_inputs',
        '[]'::jsonb
      )
    ) AS selected(value)
    JOIN authority_asset_version AS selected_version
      ON selected_version.asset_version_id=selected.value->>'asset_version_id'
    JOIN authority_asset AS selected_asset
      ON selected_asset.asset_id=selected_version.asset_id
     AND selected_asset.project_id=context_asset.project_id
    JOIN authority_operation AS consumer
      ON consumer.project_id=context_asset.project_id
     AND consumer.status='SUCCEEDED'
     AND EXISTS (
       SELECT 1
       FROM jsonb_array_elements(consumer.input_asset_snapshot) AS input(value)
       WHERE input.value->>'asset_version_id'=context_version.asset_version_id
     )
    LEFT JOIN authority_operation_output_asset AS result
      ON result.operation_id=consumer.operation_id
     AND result.role='primary'
    LEFT JOIN authority_asset AS result_asset
      ON result_asset.asset_id=result.asset_id
     AND result_asset.project_id=context_asset.project_id
    WHERE context_output.output_key='chapter.context'
      AND context_version.content->>'context_contract_version' IN (
          'authority-context-bundle-v5', 'authority-context-bundle-v6'
      )
      AND context_version.content->'context_manifest'->>'contract_version' IN (
          'narrative-context-manifest-v1', 'narrative-context-manifest-v2'
      )
    """,
    """
    CREATE OR REPLACE VIEW authority_mkaos_runtime_selection_projection AS
    SELECT context_asset.project_id,
           COALESCE(context_version.content->>'book_id', '') AS book_id,
           context_version.asset_version_id AS context_bundle_asset_version_id,
           context_output.operation_id AS context_build_operation_id,
           context_operation.trace_id,
           context_version.content->'context_manifest'->'task'
             ->>'target_capability_id' AS target_capability_id,
           context_version.content->'context_manifest'->'narrative_position'
             AS narrative_position,
           pack.knowledge_pack_id,
           pack.asset_version_id AS knowledge_pack_asset_version_id,
           item.knowledge_card_asset_version_id,
           item.usage_role,
           item.frozen_weight,
           selected.value->>'inclusion_reason' AS inclusion_reason,
           selected.value->>'narrative_function' AS narrative_function,
           context_operation.created_at AS selected_at
    FROM authority_operation_output_asset AS context_output
    JOIN authority_operation AS context_operation
      ON context_operation.operation_id=context_output.operation_id
     AND context_operation.status='SUCCEEDED'
    JOIN authority_asset_version AS context_version
      ON context_version.asset_version_id=context_output.asset_version_id
    JOIN authority_asset AS context_asset
      ON context_asset.asset_id=context_version.asset_id
     AND context_asset.asset_type='context_bundle'
    CROSS JOIN LATERAL jsonb_array_elements(
      COALESCE(
        context_version.content->'context_manifest'->'selected_inputs',
        '[]'::jsonb
      )
    ) AS selected(value)
    JOIN authority_mkaos_knowledge_pack AS pack
      ON pack.asset_version_id=selected.value->>'asset_version_id'
     AND pack.project_id=context_asset.project_id
    JOIN authority_mkaos_knowledge_pack_item AS item
      ON item.knowledge_pack_id=pack.knowledge_pack_id
     AND item.knowledge_pack_asset_version_id=pack.asset_version_id
    WHERE context_output.output_key='chapter.context'
      AND selected.value->>'asset_type'='knowledge_pack'
      AND context_version.content->>'context_contract_version' IN (
          'authority-context-bundle-v5', 'authority-context-bundle-v6'
      )
      AND context_version.content->'context_manifest'->>'contract_version' IN (
          'narrative-context-manifest-v1', 'narrative-context-manifest-v2'
      )
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

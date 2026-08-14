from __future__ import annotations


MIGRATION_ID = "20260814_0088_canonical_narrative_architecture"
DOWN_REVISION = "20260813_0087_book_initial_narrative_state_binding"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = (
    "Expose active immutable Narrative Segments, cross-cutting Arc Graphs, and "
    "Chapter Execution Plans without creating a parallel planning authority"
)


UPGRADE_STATEMENTS = [
    """
    CREATE VIEW authority_narrative_segment_projection AS
    SELECT binding.project_id,
           binding.book_id,
           binding.logical_key AS volume_logical_key,
           binding.asset_version_id AS volume_plan_version_id,
           version.content_hash AS volume_plan_content_hash,
           segment.value->>'segment_id' AS narrative_segment_id,
           segment.value->>'objective' AS objective,
           segment.value->'chapter_range' AS chapter_range,
           segment.value->>'entry_state_ref' AS entry_state_ref,
           segment.value->'exit_state_spec' AS exit_state_spec,
           segment.value->'arc_checkpoint_refs' AS arc_checkpoint_refs,
           segment.ordinality AS segment_ordinal
    FROM active_story_plan_version AS active
    JOIN story_plan_binding AS binding
      ON binding.binding_id=active.binding_id
    JOIN authority_asset_version AS version
      ON version.asset_version_id=binding.asset_version_id
    CROSS JOIN LATERAL jsonb_array_elements(
      CASE
        WHEN jsonb_typeof(version.content->'narrative_segments')='array'
        THEN version.content->'narrative_segments'
        ELSE '[]'::jsonb
      END
    ) WITH ORDINALITY AS segment(value, ordinality)
    WHERE binding.contract_type='VOLUME'
      AND binding.freshness='CURRENT'
      AND version.content->>'narrative_architecture_version'='canonical-narrative-v1'
    """,
    """
    CREATE VIEW authority_narrative_arc_graph_projection AS
    SELECT binding.project_id,
           binding.book_id,
           binding.logical_key AS arc_logical_key,
           binding.asset_version_id AS arc_plan_version_id,
           version.content_hash AS arc_plan_content_hash,
           version.content->>'thread_id' AS thread_id,
           version.content->>'arc_type' AS arc_type,
           version.content->'cross_volume_scope' AS cross_volume_scope,
           version.content->'arc_segments' AS arc_segments,
           version.content->'arc_relations' AS arc_relations,
           version.content->'closure_conditions' AS closure_conditions
    FROM active_story_plan_version AS active
    JOIN story_plan_binding AS binding
      ON binding.binding_id=active.binding_id
    JOIN authority_asset_version AS version
      ON version.asset_version_id=binding.asset_version_id
    WHERE binding.contract_type='ARC'
      AND binding.parent_version_id IS NULL
      AND binding.freshness='CURRENT'
      AND version.content->>'narrative_architecture_version'='canonical-narrative-v1'
    """,
    """
    CREATE VIEW authority_chapter_execution_plan_projection AS
    SELECT binding.project_id,
           binding.book_id,
           binding.logical_key AS chapter_logical_key,
           binding.asset_version_id AS chapter_plan_version_id,
           binding.parent_version_id AS chapter_group_plan_version_id,
           version.content_hash AS chapter_plan_content_hash,
           (version.content->>'chapter_number')::INTEGER AS chapter_number,
           version.content->'narrative_segment_ref' AS narrative_segment_ref,
           version.content->>'chapter_intent' AS chapter_intent,
           version.content->'arc_schedule' AS arc_schedule,
           version.content->'character_participation' AS character_participation,
           version.content->'knowledge_boundaries' AS knowledge_boundaries,
           version.content->'disclosures' AS disclosures,
           version.content->'required_state_transitions' AS required_state_transitions,
           version.content->'reader_experience' AS reader_experience,
           version.content->'scene_plan' AS scene_plan,
           version.content->'expected_exit_state' AS expected_exit_state
    FROM active_story_plan_version AS active
    JOIN story_plan_binding AS binding
      ON binding.binding_id=active.binding_id
    JOIN authority_asset_version AS version
      ON version.asset_version_id=binding.asset_version_id
    WHERE binding.contract_type='CHAPTER'
      AND binding.freshness='CURRENT'
      AND version.content->>'narrative_architecture_version'='canonical-narrative-v1'
    """,
]


DOWNGRADE_STATEMENTS: list[str] = []

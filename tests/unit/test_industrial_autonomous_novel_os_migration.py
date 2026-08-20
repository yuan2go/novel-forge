from novel_forge.storage.migrations.versions import (
    v20260820_0093_book_liveness_critical_path_closure as previous,
)
from novel_forge.storage.migrations.versions import (
    v20260820_0094_industrial_autonomous_novel_os as migration,
)


def test_industrial_novel_os_migration_is_forward_only_and_authority_scoped() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    assert migration.DOWN_REVISION == previous.MIGRATION_ID
    assert migration.FORWARD_ONLY is True
    for table in (
        "authority_book_narrative_projection_set",
        "authority_arc_progress_v2",
        "authority_arc_actual_state",
        "authority_arc_checkpoint_v2",
        "authority_arc_outcome_v2",
        "authority_narrative_obligation_state",
        "authority_narrative_retrieval_document",
        "authority_agent_harness_session",
        "authority_agent_transcript_event",
        "authority_artifact_lineage_edge",
        "authority_artifact_invalidation",
    ):
        assert f"CREATE TABLE {table}" in sql
    assert "authority_chapter_best_candidate" not in sql
    assert "active_longform_projection_set_id" in sql
    assert "longform_projection_set_id" in sql
    assert "observation_status IN" in sql
    assert "search_vector TSVECTOR GENERATED ALWAYS" in sql
    assert "USING GIN(search_vector)" in sql
    assert "DEFERRABLE INITIALLY DEFERRED" in sql
    assert "DROP TABLE" not in sql

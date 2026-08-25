from novel_forge.storage.migrations.versions import (
    v20260825_0098_narrative_evolution_engine as migration,
)


def test_narrative_evolution_migration_is_forward_only_head() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    assert migration.DOWN_REVISION == "20260824_0097_narrative_evaluator_codex_lineage"
    assert migration.FORWARD_ONLY is True
    assert "authority_story_narrative_search" in sql
    assert "authority_story_narrative_search_candidate" in sql
    assert "authority_story_narrative_search_decision" in sql
    assert "narrative_search_id" in sql
    assert "candidate_target BETWEEN 2 AND 5" in sql
    assert "authority_story_narrative_search_scope_fk_idx" in sql
    assert "authority_retrieval_candidate_attempt_fence_fk_idx" in sql
    assert "CREATE OR REPLACE VIEW authority_context_runtime_usage_projection" in sql
    assert "CREATE OR REPLACE VIEW authority_mkaos_runtime_selection_projection" in sql
    assert "authority-context-bundle-v6" in sql
    assert "narrative-context-manifest-v2" in sql

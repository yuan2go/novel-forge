from novel_forge.storage.migrations.versions import (
    v20260825_0099_creative_engineering_convergence as migration,
)


def test_creative_engineering_convergence_migration_is_forward_only_head() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    assert migration.DOWN_REVISION == "20260825_0098_narrative_evolution_engine"
    assert migration.FORWARD_ONLY is True
    assert "agent.chapter_binding.register" in sql
    assert "agent.chapter_binding.activate" in sql
    assert "agent.candidate.execute" in sql
    assert "agent.session.execute" in sql
    assert "SET enabled=FALSE" in sql
    assert "SKILL_ACTIVATED" in sql
    assert "authority_narrative_retrieval_authoring_projection_idx" in sql
    assert "authority-context-bundle-v7" in sql
    assert "narrative-context-manifest-v3" in sql
    assert "BM25" not in sql

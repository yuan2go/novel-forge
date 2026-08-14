from novel_forge.storage.migrations import validate_migration_chain
from novel_forge.storage.migrations.versions import (
    v20260814_0088_canonical_narrative_architecture as migration,
)


def test_canonical_narrative_architecture_is_forward_only_head() -> None:
    validate_migration_chain()

    assert migration.FORWARD_ONLY is True
    assert migration.DOWN_REVISION == (
        "20260813_0087_book_initial_narrative_state_binding"
    )
    sql = "\n".join(migration.UPGRADE_STATEMENTS)
    assert "authority_narrative_segment_projection" in sql
    assert "authority_narrative_arc_graph_projection" in sql
    assert "authority_chapter_execution_plan_projection" in sql
    assert "binding.parent_version_id IS NULL" in sql

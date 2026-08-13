from __future__ import annotations

from novel_forge.storage.migrations.versions import (
    v20260813_0087_book_initial_narrative_state_binding as migration,
)


def test_initial_narrative_state_migration_is_forward_pair_binding() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    assert migration.DOWN_REVISION == (
        "20260812_0086_corrective_generation_terminal_lineage"
    )
    assert migration.FORWARD_ONLY is True
    assert "initial_story_state_version" in sql
    assert "initial_canon_snapshot_version" in sql
    assert "authority_book_input_initial_narrative_pair_check" in sql
    assert "initial_story_state_version IS NULL" in sql
    assert "initial_story_state_version IS NOT NULL" in sql
    assert "idx_book_input_initial_story_state" in sql
    assert "idx_book_input_initial_canon_snapshot" in sql

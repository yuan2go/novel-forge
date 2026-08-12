from __future__ import annotations

from novel_forge.storage.migrations import LATEST_MIGRATION_ID, validate_migration_chain
from novel_forge.storage.migrations.versions import (
    v20260812_0085_corrective_action_terminal_lineage as previous,
    v20260812_0086_corrective_generation_terminal_lineage as migration,
)


def test_terminal_lineage_is_a_forward_only_projection_fix() -> None:
    validate_migration_chain()
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    assert LATEST_MIGRATION_ID == migration.MIGRATION_ID
    assert migration.DOWN_REVISION == previous.MIGRATION_ID
    assert migration.FORWARD_ONLY is True
    assert "MIGRATION_ONLY base projection" in sql
    assert "FAILED_FINAL" in sql
    assert "DEAD_LETTER" in sql
    assert "CANCELLED" in sql
    assert "SUPERSEDED" in sql
    assert "chapter.revision.review" in sql
    assert "chapter.quality.evaluate" in sql
    assert "quality-correction:([0-9]+)$" in sql
    assert "CREATE TABLE" not in sql

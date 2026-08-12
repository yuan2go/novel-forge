from __future__ import annotations

from novel_forge.storage.migrations.versions import (
    v20260812_0082_narrative_state_contract_v2 as migration,
)


def test_migration_is_forward_only_and_preserves_authority_history() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    assert migration.MIGRATION_ID == "20260812_0082_narrative_state_contract_v2"
    assert migration.DOWN_REVISION == "20260811_0081_source_intelligence_router"
    assert migration.FORWARD_ONLY is True
    assert migration.BACKUP_REQUIRED is True
    assert migration.DOWNGRADE_STATEMENTS == []
    assert "UPDATE authority_asset_version" not in sql
    assert "DELETE FROM authority_asset_version" not in sql
    assert "UPDATE authority_book_chapter_acceptance" not in sql
    assert "DELETE FROM authority_book_chapter_acceptance" not in sql


def test_event_current_and_rebuild_views_are_rooted_in_committed_acceptance() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    for view in (
        "authority_narrative_state_event_projection",
        "authority_narrative_current_state_projection",
        "authority_narrative_state_rebuild_source",
    ):
        assert f"CREATE VIEW {view}" in sql
    assert sql.count("authority_book_chapter_acceptance") >= 3
    assert sql.count("acceptance.status='COMMITTED'") >= 3
    assert "acceptance_operation.status='SUCCEEDED'" in sql
    assert "chapter-outcome-v2" in sql
    assert "story-state-snapshot-v2" in sql
    assert "canon-snapshot-v2" in sql
    assert "'chapter-outcome-v1', 'chapter-outcome-v2'" in sql


def test_reducer_receipts_are_event_and_entity_addressable() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    for column in (
        "event_id",
        "state_kind",
        "entity_key",
        "reducer_semantics",
        "accepted_chapter",
    ):
        assert f"ADD COLUMN {column}" in sql
    assert "authority_story_reducer_event_identity_idx" in sql
    assert "authority_story_reducer_entity_replay_idx" in sql

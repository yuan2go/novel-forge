from __future__ import annotations

from novel_forge.storage.migrations import LATEST_MIGRATION_ID, validate_migration_chain
from novel_forge.storage.migrations.versions import (
    v20260825_0100_hierarchy_closure as migration,
)


def test_hierarchy_closure_extends_one_forward_head() -> None:
    validate_migration_chain()

    assert LATEST_MIGRATION_ID == migration.MIGRATION_ID
    assert migration.DOWN_REVISION == "20260825_0099_creative_engineering_convergence"
    assert migration.FORWARD_ONLY is True
    assert migration.DOWNGRADE_STATEMENTS == []


def test_hierarchy_schema_reuses_authorities_without_new_plan_scale() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    assert "CREATE TABLE authority_story_formation_run" in sql
    assert "CREATE TABLE authority_narrative_realization" in sql
    assert "CREATE TABLE authority_narrative_realization_consumption" in sql
    assert "REFERENCES authority_operation(operation_id)" in sql
    assert "REFERENCES authority_asset_version(asset_version_id)" in sql
    assert "ALTER TABLE story_plan_binding" not in sql
    assert "NARRATIVE_REALIZATION'" not in sql
    assert "AcceptedNarrativeRealization" not in sql


def test_realization_schema_tracks_partial_accepted_coverage() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    for value in ("OBSERVED", "ACCEPTED", "DEVIATED", "NOT_OBSERVED"):
        assert f"'{value}'" in sql
    assert "planned_event_id" in sql
    assert "observed_event_id" in sql
    assert "chapter_outcome_asset_version_id" in sql
    assert "invalidated_by_operation_id" in sql
    assert "authority_book_chapter_acceptance(acceptance_id)" in sql
    assert "MISSING_REQUIRED_EVENT" in sql

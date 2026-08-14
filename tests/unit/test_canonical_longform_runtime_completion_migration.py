from novel_forge.storage.migrations.versions import (
    v20260814_0090_progressive_replan_scopes as previous,
)
from novel_forge.storage.migrations.versions import (
    v20260814_0091_canonical_longform_runtime_completion as migration,
)


def test_independent_narrative_evaluation_lineage_is_migrated_in_place() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    assert migration.DOWN_REVISION == previous.MIGRATION_ID
    assert "'EVALUATION_PENDING'" in sql
    assert "authority_book_design_candidate_status_check" in sql
    assert "volume_portfolio_plan_versions" in sql
    assert "narrative_chapter_cursor" in sql
    assert "authority_volume_portfolio_projection" in sql
    assert "authority_canonical_planning_projection" in sql
    assert "authority_multiscale_quality_projection" in sql
    assert "generation_operation_id" in sql
    assert "evaluation_operation_id" in sql
    assert "evaluation_attempt_id" in sql
    assert "evaluation_asset_version_id" in sql
    assert "generation_operation_id<>evaluation_operation_id" in sql
    assert "trust_boundary='INDEPENDENT'" in sql
    assert "CREATE OR REPLACE VIEW authority_current_narrative_design_qualification" in sql
    assert "'narrative-state-event-v2', 'narrative-state-event-v3'" in sql

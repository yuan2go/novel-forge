from __future__ import annotations

from novel_forge.storage.migrations import LATEST_MIGRATION_ID, validate_migration_chain
from novel_forge.storage.migrations.versions import (
    v20260811_0080_source_snapshot_governance_identity as previous,
    v20260811_0081_source_intelligence_router as migration,
    v20260812_0082_narrative_state_contract_v2 as narrative_state_migration,
    v20260812_0083_narrative_runtime_convergence as narrative_runtime_migration,
    v20260812_0084_development_gap_final_convergence as convergence_migration,
    v20260812_0085_corrective_action_terminal_lineage as terminal_migration,
    v20260812_0086_corrective_generation_terminal_lineage as generation_migration,
    v20260813_0087_book_initial_narrative_state_binding as initial_state_migration,
    v20260814_0088_canonical_narrative_architecture as head_migration,
    v20260814_0089_progressive_narrative_design as progressive_migration,
    v20260814_0090_progressive_replan_scopes as current_head_migration,
    v20260814_0091_canonical_longform_runtime_completion as completion_migration,
    v20260814_0092_longform_correctness_closure as correctness_migration,
    v20260820_0093_book_liveness_critical_path_closure as liveness_migration,
    v20260820_0094_industrial_autonomous_novel_os as novel_os_migration,
    v20260821_0095_post_merge_correctness_repair as repair_migration,
    v20260821_0096_runtime_hardening as runtime_hardening_migration,
    v20260824_0097_narrative_evaluator_codex_lineage as codex_lineage_migration,
    v20260825_0098_narrative_evolution_engine as evolution_migration,
    v20260825_0099_creative_engineering_convergence as creative_engineering_migration,
    v20260825_0100_hierarchy_closure as hierarchy_closure_migration,
)


def test_source_intelligence_router_is_forward_only_migration_head() -> None:
    validate_migration_chain()
    assert migration.DOWN_REVISION == previous.MIGRATION_ID
    assert migration.FORWARD_ONLY is True
    assert narrative_state_migration.DOWN_REVISION == migration.MIGRATION_ID
    assert (
        narrative_runtime_migration.DOWN_REVISION
        == narrative_state_migration.MIGRATION_ID
    )
    assert (
        convergence_migration.DOWN_REVISION == narrative_runtime_migration.MIGRATION_ID
    )
    assert terminal_migration.DOWN_REVISION == convergence_migration.MIGRATION_ID
    assert generation_migration.DOWN_REVISION == terminal_migration.MIGRATION_ID
    assert initial_state_migration.DOWN_REVISION == generation_migration.MIGRATION_ID
    assert head_migration.DOWN_REVISION == initial_state_migration.MIGRATION_ID
    assert progressive_migration.DOWN_REVISION == head_migration.MIGRATION_ID
    assert current_head_migration.DOWN_REVISION == progressive_migration.MIGRATION_ID
    assert completion_migration.DOWN_REVISION == current_head_migration.MIGRATION_ID
    assert correctness_migration.DOWN_REVISION == completion_migration.MIGRATION_ID
    assert liveness_migration.DOWN_REVISION == correctness_migration.MIGRATION_ID
    assert novel_os_migration.DOWN_REVISION == liveness_migration.MIGRATION_ID
    assert repair_migration.DOWN_REVISION == novel_os_migration.MIGRATION_ID
    assert runtime_hardening_migration.DOWN_REVISION == repair_migration.MIGRATION_ID
    assert (
        codex_lineage_migration.DOWN_REVISION
        == runtime_hardening_migration.MIGRATION_ID
    )
    assert evolution_migration.DOWN_REVISION == codex_lineage_migration.MIGRATION_ID
    assert (
        creative_engineering_migration.DOWN_REVISION == evolution_migration.MIGRATION_ID
    )
    assert (
        hierarchy_closure_migration.DOWN_REVISION
        == creative_engineering_migration.MIGRATION_ID
    )
    assert LATEST_MIGRATION_ID == hierarchy_closure_migration.MIGRATION_ID


def test_profile_and_analysis_plan_use_existing_asset_authority() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS).lower()
    for table in (
        "authority_source_content_profile",
        "authority_source_content_profile_input",
        "authority_source_analysis_plan",
    ):
        assert f"create table {table}" in sql
    assert "references authority_asset(asset_id)" in sql
    assert "references authority_asset_version(asset_version_id)" in sql
    assert "source_content_profile_asset_version_id" in sql
    assert "source_analysis_plan_asset_version_id" in sql
    assert "logical_document_scope" in sql
    assert "classifier_contract_hash" in sql
    assert "methodology_content_hash" in sql
    assert "analysis_plan_asset_version_id" in sql
    assert "profiles" in sql and "routes" in sql and "plans" in sql
    assert "raw_text" not in sql
    assert "source_text" not in sql
    assert "sample_text" not in sql


def test_import_identity_is_separate_from_intelligence_policy() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS).lower()
    assert "rename column analysis_profile to legacy_analysis_profile" in sql
    assert "intelligence_policy jsonb" in sql
    assert "intelligence_policy_hash text" in sql
    assert "analysis_override jsonb" in sql
    assert (
        "import_policy_hash"
        not in sql.split("create table authority_source_content_profile", 1)[1].split(
            "create table authority_source_content_profile_input", 1
        )[0]
    )


def test_fail_closed_status_and_recomputation_causes_are_schema_backed() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS).lower()
    assert "needs_review" in sql
    assert "classifier_upgrade" in sql
    assert "routing_policy_upgrade" in sql
    assert "methodology_upgrade" in sql
    assert "profile_override" in sql
    assert "profiling" in sql
    assert "analysis_planning" in sql
    assert "authority_validate_source_profile_scope" in sql

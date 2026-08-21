from __future__ import annotations

from novel_forge.storage.migrations import LATEST_MIGRATION_ID, validate_migration_chain
from novel_forge.storage.migrations.versions import (
    v20260811_0076_source_import_runtime as migration,
    v20260811_0077_source_reprocessing_execution as execution_migration,
    v20260811_0078_reprocessing_action_expansion as action_migration,
    v20260811_0079_source_import_scope_closure as scope_migration,
    v20260811_0080_source_snapshot_governance_identity as governance_migration,
    v20260811_0081_source_intelligence_router as intelligence_migration,
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
)


def test_source_import_runtime_is_registered_forward_only_head() -> None:
    validate_migration_chain()
    assert (
        narrative_state_migration.DOWN_REVISION == intelligence_migration.MIGRATION_ID
    )
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
    assert LATEST_MIGRATION_ID == novel_os_migration.MIGRATION_ID
    assert migration.DOWN_REVISION == "20260811_0075_source_deconstruction_intelligence"
    assert migration.FORWARD_ONLY is True
    sql = "\n".join(migration.UPGRADE_STATEMENTS).lower()
    for table in (
        "authority_source_import_job",
        "authority_source_repository_snapshot",
        "authority_source_repository_file",
        "authority_source_import_work",
    ):
        assert f"create table {table}" in sql
    assert "execution_spec jsonb" in sql
    assert "partially_applied" in sql
    assert "raw_text" not in sql
    assert "clean_text" not in sql
    assert "source_text" not in sql


def test_reprocessing_execution_result_and_dependencies_are_versioned() -> None:
    assert execution_migration.DOWN_REVISION == migration.MIGRATION_ID
    sql = "\n".join(execution_migration.UPGRADE_STATEMENTS).lower()
    assert "dependency_ids jsonb" in sql
    assert "result jsonb" in sql
    assert action_migration.DOWN_REVISION == execution_migration.MIGRATION_ID
    action_sql = "\n".join(action_migration.UPGRADE_STATEMENTS).lower()
    assert "recompute_aggregate" in action_sql
    assert "reabstract" in action_sql
    assert "regovern" in action_sql


def test_source_import_scope_closure_is_database_enforced() -> None:
    assert scope_migration.DOWN_REVISION == action_migration.MIGRATION_ID
    sql = "\n".join(scope_migration.UPGRADE_STATEMENTS).lower()
    assert "authority_source_import_job_snapshot_fk" in sql
    assert "authority_source_import_job_previous_snapshot_fk" in sql
    assert "authority_source_import_work_target_idx" in sql
    assert "authority_source_repository_file_operation_idx" in sql
    assert "authority_source_repository_snapshot_workspace_idx" in sql
    assert "source import job scope mismatch" in sql
    assert "source import sourcedocument scope mismatch" in sql
    assert "source import sourcetransform scope mismatch" in sql
    assert "source import source lineage mismatch" in sql


def test_repository_snapshot_identity_freezes_governance_policy() -> None:
    assert governance_migration.DOWN_REVISION == scope_migration.MIGRATION_ID
    sql = "\n".join(governance_migration.UPGRADE_STATEMENTS).lower()
    assert "governance_policy_hash" in sql
    assert "authority_source_repository_snapshot_identity_key" in sql
    assert "import_policy_hash, governance_policy_hash" in sql

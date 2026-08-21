from __future__ import annotations

from novel_forge.storage.migrations import LATEST_MIGRATION_ID, validate_migration_chain
from novel_forge.storage.migrations.versions import (
    v20260805_0071_capability_pack_authority as foundation_migration,
)
from novel_forge.storage.migrations.versions import (
    v20260806_0072_capability_pack_integrity_hardening as migration,
)
from novel_forge.storage.migrations.versions import (
    v20260806_0073_core_functional_loops as core_migration,
)
from novel_forge.storage.migrations.versions import (
    v20260811_0074_longform_native_intelligence as longform_migration,
)
from novel_forge.storage.migrations.versions import (
    v20260811_0075_source_deconstruction_intelligence as deconstruction_migration,
)
from novel_forge.storage.migrations.versions import (
    v20260811_0076_source_import_runtime as source_import_migration,
)
from novel_forge.storage.migrations.versions import (
    v20260811_0077_source_reprocessing_execution as reprocessing_migration,
)
from novel_forge.storage.migrations.versions import (
    v20260811_0078_reprocessing_action_expansion as action_migration,
)
from novel_forge.storage.migrations.versions import (
    v20260811_0079_source_import_scope_closure as scope_migration,
)
from novel_forge.storage.migrations.versions import (
    v20260811_0080_source_snapshot_governance_identity as governance_migration,
    v20260811_0081_source_intelligence_router as latest_migration,
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
)


def _sql() -> str:
    return "\n".join(migration.UPGRADE_STATEMENTS)


def test_capability_pack_authority_remains_in_linear_migration_chain() -> None:
    validate_migration_chain()
    assert migration.MIGRATION_ID == (
        "20260806_0072_capability_pack_integrity_hardening"
    )
    assert migration.DOWN_REVISION == foundation_migration.MIGRATION_ID
    assert core_migration.DOWN_REVISION == migration.MIGRATION_ID
    assert longform_migration.DOWN_REVISION == core_migration.MIGRATION_ID
    assert deconstruction_migration.DOWN_REVISION == longform_migration.MIGRATION_ID
    assert (
        source_import_migration.DOWN_REVISION == deconstruction_migration.MIGRATION_ID
    )
    assert reprocessing_migration.DOWN_REVISION == source_import_migration.MIGRATION_ID
    assert action_migration.DOWN_REVISION == reprocessing_migration.MIGRATION_ID
    assert scope_migration.DOWN_REVISION == action_migration.MIGRATION_ID
    assert governance_migration.DOWN_REVISION == scope_migration.MIGRATION_ID
    assert latest_migration.DOWN_REVISION == governance_migration.MIGRATION_ID
    assert narrative_state_migration.DOWN_REVISION == latest_migration.MIGRATION_ID
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
    assert LATEST_MIGRATION_ID == repair_migration.MIGRATION_ID
    assert migration.FORWARD_ONLY is True


def test_schema_has_registry_deployment_and_runtime_snapshot_facts() -> None:
    sql = "\n".join(foundation_migration.UPGRADE_STATEMENTS)
    for relation in (
        "authority_capability_pack",
        "authority_capability_pack_version",
        "authority_capability_pack_compilation",
        "authority_capability_pack_approval",
        "authority_capability_pack_binding_set",
        "authority_capability_pack_deployment",
        "authority_capability_pack_activation",
        "authority_capability_pack_rollout",
        "authority_capability_pack_assignment",
        "authority_capability_pack_deprecation",
    ):
        assert f"CREATE TABLE {relation}" in sql
    assert "capability_pack_deployment_id" in sql
    assert "capability_pack_binding_set_hash" in sql
    assert "capability_pack_assignment_ref" in sql
    assert "chapter_node_binding_id DROP NOT NULL" in sql
    assert "authority_agent_runtime_binding_source_check" in sql
    assert "ALTER TABLE authority_chapter_node_agent_binding" not in sql


def test_schema_uses_cas_immutability_and_scope_constraints() -> None:
    sql = "\n".join(foundation_migration.UPGRADE_STATEMENTS)
    assert "activation_version BIGINT NOT NULL" in sql
    assert "authority_capability_pack_immutable" in sql
    assert "authority_capability_pack_assignment_immutable" in sql
    assert "target_scope_type IN ('SYSTEM', 'PROJECT', 'WORKSPACE', 'BOOK')" in sql
    assert "baseline_deployment_id <> candidate_deployment_id" in sql
    assert "manifest_hash ~ '^sha256:[0-9a-f]{64}$'" in sql
    assert "compilation_hash ~ '^sha256:[0-9a-f]{64}$'" in sql


def test_schema_does_not_create_a_second_runtime() -> None:
    sql = ("\n".join(foundation_migration.UPGRADE_STATEMENTS) + _sql()).lower()
    for forbidden in (
        "create table authority_capability_pack_run",
        "create table authority_capability_pack_attempt",
        "create table authority_capability_pack_lease",
        "create table authority_capability_pack_fence",
        "create table authority_capability_pack_worker",
    ):
        assert forbidden not in sql


def test_integrity_hardening_adds_provenance_and_attempt_snapshot_authority() -> None:
    sql = _sql()
    for signal in (
        "authority_capability_pack_approval_exact_compilation_fk",
        "authority_capability_pack_deployment_compilation_chain_fk",
        "authority_capability_pack_deployment_binding_chain_fk",
        "authority_capability_pack_dependency",
        "authority_attempt_capability_pack_snapshot",
        "authority_attempt_capability_pack_snapshot_immutable",
        "authority_agent_runtime_pack_integrity_fact_guard",
        "authority_capability_pack_one_open_rollout",
    ):
        assert signal in sql


def test_integrity_hardening_keeps_existing_attempt_lease_and_fence_authority() -> None:
    sql = _sql().lower()
    for forbidden in (
        "create table authority_capability_pack_attempt",
        "create table authority_capability_pack_lease",
        "create table authority_capability_pack_fence",
    ):
        assert forbidden not in sql

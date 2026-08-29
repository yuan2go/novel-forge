from __future__ import annotations

from novel_forge.storage.migrations import LATEST_MIGRATION_ID, validate_migration_chain
from novel_forge.storage.migrations.versions import (
    v20260829_0104_book_opening_workflow_nodes as migration,
)


def test_workflow_nodes_migration_is_the_forward_only_head() -> None:
    validate_migration_chain()

    assert LATEST_MIGRATION_ID == migration.MIGRATION_ID
    assert migration.MIGRATION_ID == "20260829_0104_book_opening_workflow_nodes"
    assert (
        migration.DOWN_REVISION
        == "20260829_0103_book_opening_semantic_runtime_hardening"
    )
    assert migration.FORWARD_ONLY is True
    assert migration.BACKUP_REQUIRED is False
    assert migration.DOWNGRADE_STATEMENTS == []


def test_run_execution_and_checkpoint_gain_versioned_workflow_identity() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    for token in (
        "workflow_contract_version TEXT NOT NULL",
        "DEFAULT 'legacy-monolithic-v2'",
        "current_workflow_node_id TEXT",
        "workflow_graph_revision BIGINT NOT NULL DEFAULT 0",
        "workflow_graph_hash TEXT NOT NULL DEFAULT ''",
        "workflow_node_id TEXT",
        "workflow_transition_kind TEXT NOT NULL",
        "DEFAULT 'LEGACY_MONOLITHIC'",
        "source_checkpoint_id TEXT",
        "source_checkpoint_sequence BIGINT NOT NULL DEFAULT 0",
        "source_checkpoint_hash TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE authority_book_opening_semantic_checkpoint",
        "ADD COLUMN workflow_node_id TEXT",
    ):
        assert token in sql
    assert "book-opening-workflow-v1" in sql
    assert "ALTER COLUMN workflow_contract_version DROP DEFAULT" in sql
    assert "ALTER COLUMN workflow_graph_revision DROP DEFAULT" in sql
    assert "ALTER COLUMN workflow_graph_hash DROP DEFAULT" in sql
    assert "authority_bo_execution_workflow_shape_check" in sql
    assert "authority_bo_execution_generation_lineage_check" in sql


def test_workflow_execution_and_runtime_capability_are_version_paired() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    assert "book-opening-execution-v3" in sql
    assert "BOOK_OPENING_WORKFLOW_NODE_EXECUTE" in sql
    assert "book_opening_workflow_v1" in sql
    assert "authority_bo_run_execution_contract_pair_check" in sql
    assert "authority_book_opening_workflow_runtime_policy_check" in sql
    assert "authority_book_opening_workflow_semantic_binding_shape_check" in sql
    assert (
        "CREATE OR REPLACE FUNCTION authority_book_opening_runtime_policy_guard" in sql
    )
    assert "CREATE OR REPLACE FUNCTION authority_book_opening_execution_guard" in sql
    assert (
        "CREATE OR REPLACE FUNCTION authority_assert_book_opening_current_execution"
        in sql
    )
    assert (
        "CREATE OR REPLACE FUNCTION authority_narrative_replacement_gate_is_open" in sql
    )
    assert "binding.opening_execution_contract_version" in sql


def test_legacy_recovery_execution_may_resume_a_durable_v2_checkpoint() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS)
    workflow_shape = sql.split(
        "ADD CONSTRAINT authority_bo_execution_workflow_shape_check", 1
    )[1].split("ADD CONSTRAINT authority_bo_execution_generation_lineage_check", 1)[0]

    assert "workflow_transition_kind='LEGACY_MONOLITHIC'" in workflow_shape
    assert "source_checkpoint_id IS NOT NULL" in workflow_shape
    assert "source_checkpoint_sequence>0" in workflow_shape
    assert "source_checkpoint_hash ~ '^sha256:[0-9a-f]{64}$'" in workflow_shape

    graph_guard = sql.split(
        "CREATE OR REPLACE FUNCTION authority_assert_book_opening_workflow_graph", 1
    )[1].split("CREATE OR REPLACE FUNCTION authority_bo_workflow_graph_guard", 1)[0]
    legacy_graph_branch = graph_guard.split(
        "IF opening.workflow_contract_version='legacy-monolithic-v2'", 1
    )[1].split("RETURN;", 1)[0]
    assert "workflow_transition_kind<>'LEGACY_MONOLITHIC'" in legacy_graph_branch
    assert "source_checkpoint_id IS NOT NULL" not in legacy_graph_branch
    assert "binding.opening_workflow_contract_version" in sql


def test_fixed_five_node_graph_is_database_constrained_and_immutable() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    assert "CREATE TABLE authority_book_opening_workflow_node" in sql
    assert "CREATE TABLE authority_book_opening_workflow_edge" in sql
    for node_key, node_kind, ordinal in (
        ("book-plan", "BOOK_PLAN", 1),
        ("volume-portfolio", "VOLUME_PORTFOLIO", 2),
        ("current-volume", "CURRENT_VOLUME", 3),
        ("initial-arc-scope", "INITIAL_ARC_SCOPE", 4),
        ("input-snapshot", "INPUT_SNAPSHOT", 5),
    ):
        assert f"node_key='{node_key}'" in sql
        assert f"node_kind='{node_kind}'" in sql
        assert f"ordinal={ordinal}" in sql
    assert "UNIQUE(opening_run_id,node_key)" in sql
    assert "UNIQUE(opening_run_id,ordinal)" in sql
    assert "stable_idempotency_key TEXT NOT NULL" in sql
    assert "UNIQUE(opening_run_id,stable_idempotency_key)" in sql
    assert "authority_book_opening_workflow_fact_immutable" in sql
    assert "BOOK_OPENING_WORKFLOW_FACT_IMMUTABLE" in sql
    assert "BOOK_OPENING_WORKFLOW_GRAPH_INVALID" in sql


def test_legacy_snapshot_entitlement_is_migration_snapshot_not_time_inference() -> None:
    statements = migration.UPGRADE_STATEMENTS
    sql = "\n".join(statements)

    table_index = next(
        index
        for index, statement in enumerate(statements)
        if "CREATE TABLE authority_book_opening_legacy_snapshot_entitlement"
        in statement
    )
    backfill_index = next(
        index
        for index, statement in enumerate(statements)
        if "INSERT INTO authority_book_opening_legacy_snapshot_entitlement" in statement
    )
    seal_index = next(
        index
        for index, statement in enumerate(statements)
        if "CREATE TRIGGER authority_bo_legacy_snapshot_entitlement_sealed" in statement
    )

    assert table_index < backfill_index < seal_index
    assert "snapshot_id TEXT PRIMARY KEY" in sql
    assert "snapshot_hash TEXT NOT NULL UNIQUE" in sql
    assert "snapshot_id,project_id,workspace_id,book_id,snapshot_hash" in sql
    assert "FROM authority_book_production_input_snapshot AS snapshot" in sql
    assert "BEFORE INSERT OR UPDATE OR DELETE" in sql
    assert "BOOK_OPENING_LEGACY_SNAPSHOT_ENTITLEMENT_SEALED" in sql
    assert "source_migration_id" in sql
    assert "created_at <" not in sql
    assert "created_at <=" not in sql


def test_terminal_opening_authority_facts_are_immutable() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    assert "authority_bo_run_terminal_immutable_guard" in sql
    assert "OLD.lifecycle IN ('COMPLETE','ABORTED')" in sql
    assert "to_jsonb(OLD) - 'updated_at'" in sql
    assert "to_jsonb(NEW) - 'updated_at'" in sql
    assert "BOOK_OPENING_RUN_TERMINAL_IMMUTABLE" in sql
    assert "CREATE TRIGGER authority_book_opening_run_terminal_immutable" in sql
    assert "TG_OP='DELETE'" in sql
    assert "RETURN OLD" in sql
    assert "BEFORE UPDATE OR DELETE ON authority_book_opening_run" in sql


def test_node_receipt_is_terminal_evidence_not_a_second_authority() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    assert "CREATE TABLE authority_book_opening_node_receipt" in sql
    for token in (
        "node_receipt_id TEXT PRIMARY KEY",
        "result JSONB NOT NULL",
        "result_hash TEXT NOT NULL",
        "authoritative_evidence_hash TEXT NOT NULL",
        "reviewable_artifact_kind TEXT NOT NULL",
        "reviewable_asset_version_ids TEXT[] NOT NULL",
        "checkpoint_id TEXT NOT NULL",
        "checkpoint_sequence BIGINT NOT NULL",
        "checkpoint_hash TEXT NOT NULL",
        "UNIQUE(opening_run_id,workflow_node_id)",
    ):
        assert token in sql
    assert "receipt.authoritative_evidence_hash IS DISTINCT FROM" in sql
    assert "checkpoint.evidence_hash" in sql
    assert "checkpoint_evidence_type IS DISTINCT FROM" in sql
    assert "'BOOK_OPENING_NODE_RECEIPT'" in sql
    assert "authority_book_opening_node_receipt_immutable" in sql


def test_transition_receipt_uniquely_authorizes_successor_execution() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    assert "CREATE TABLE authority_book_opening_workflow_transition_receipt" in sql
    for token in (
        "workflow_transition_receipt_id TEXT PRIMARY KEY",
        "source_node_receipt_id TEXT NOT NULL UNIQUE",
        "successor_opening_execution_id TEXT NOT NULL",
        "successor_execution_generation BIGINT NOT NULL",
        "successor_workflow_node_id TEXT NOT NULL",
        "transition_kind TEXT NOT NULL",
        "transition_hash TEXT NOT NULL",
        "CONSTRAINT authority_bo_transition_successor_key UNIQUE",
    ):
        assert token in sql
    assert "transition_kind='CONTINUATION'" in sql
    assert "exact_workflow_continuation" in sql
    assert "predecessor_lifecycle IS DISTINCT FROM 'SUCCEEDED'" in sql
    assert "BOOK_OPENING_WORKFLOW_TRANSITION_INVALID" in sql


def test_deferred_relational_guards_preserve_v2_and_close_v3_tears() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    assert "authority_assert_book_opening_workflow_graph" in sql
    assert "authority_assert_book_opening_node_receipt" in sql
    assert "authority_assert_book_opening_workflow_transition" in sql
    assert "CREATE CONSTRAINT TRIGGER" in sql
    assert "DEFERRABLE INITIALLY DEFERRED" in sql
    assert "workflow_contract_version='legacy-monolithic-v2'" in sql
    assert "workflow_transition_kind='LEGACY_MONOLITHIC'" in sql
    assert "workflow_contract_version='book-opening-workflow-v1'" in sql
    assert "COUNT(*) FILTER (WHERE node_kind='BOOK_PLAN')" in sql
    assert "execution.workflow_node_id IS DISTINCT FROM" in sql
    assert "node.ordinal>receipt_count+1" in sql
    assert "checkpoint.checkpoint_sequence>" in sql
    assert "receipt.checkpoint_sequence" in sql
    assert "ORDER BY checkpoint.checkpoint_sequence DESC" in sql
    assert "BOOK_OPENING_NODE_RECEIPT_INVALID" in sql
    assert "BOOK_OPENING_WORKFLOW_TRANSITION_INVALID" in sql


def test_generation_lineage_supports_normal_continuation_without_weakening_recovery() -> (
    None
):
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    assert "workflow_transition_kind='RECOVERY'" in sql
    assert "recovery_intent_id IS NOT NULL" in sql
    assert "exact_recovery_admission" in sql
    assert "workflow_transition_kind='CONTINUATION'" in sql
    assert "recovery_intent_id IS NULL" in sql
    assert "exact_workflow_continuation" in sql
    assert "source_checkpoint_id" in sql
    assert "source_checkpoint_sequence" in sql
    assert "source_checkpoint_hash" in sql


def test_workflow_foreign_keys_have_supporting_indexes() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    for index_name in (
        "authority_bo_node_opening_fk_idx",
        "authority_bo_edge_successor_fk_idx",
        "authority_bo_execution_node_fk_idx",
        "authority_bo_execution_source_checkpoint_fk_idx",
        "authority_bo_checkpoint_node_fk_idx",
        "authority_bo_node_receipt_execution_fk_idx",
        "authority_bo_transition_predecessor_fk_idx",
        "authority_bo_transition_successor_fk_idx",
        "authority_bo_transition_node_fk_idx",
        "authority_bo_transition_checkpoint_fk_idx",
    ):
        assert f"CREATE INDEX {index_name}" in sql
    assert "CREATE UNIQUE INDEX authority_bo_checkpoint_node_unique_idx" in sql
    assert "evidence_type='BOOK_OPENING_NODE_RECEIPT'" in sql


def test_migration_is_additive_and_preserves_v2_history() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS).upper()

    assert "DROP TABLE" not in sql
    assert "DROP COLUMN" not in sql
    assert "UPDATE AUTHORITY_BOOK_OPENING" not in sql
    assert "DELETE FROM AUTHORITY_BOOK_OPENING" not in sql
    assert "LEGACY_MONOLITHIC" in sql
    assert "legacy" in migration.FORWARD_FIX.lower()

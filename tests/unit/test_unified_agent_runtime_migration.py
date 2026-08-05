from __future__ import annotations

from novel_forge.storage.migrations import MIGRATIONS, validate_migration_chain


def _sql() -> str:
    migration = next(
        item
        for item in MIGRATIONS
        if item.migration_id == "20260805_0068_unified_agent_runtime"
    )
    return "\n".join(migration.upgrade_statements)


def test_unified_agent_runtime_migration_extends_linear_head() -> None:
    validate_migration_chain()
    migration = next(
        item
        for item in MIGRATIONS
        if item.migration_id == "20260805_0068_unified_agent_runtime"
    )
    assert migration.migration_id == "20260805_0068_unified_agent_runtime"
    assert (
        migration.down_revision
        == "20260804_0067_activated_migration_archival_binding"
    )


def test_schema_reuses_kernel_attempt_lease_and_fence() -> None:
    sql = _sql()

    assert "CREATE TABLE authority_agent_runtime_binding" in sql
    assert "REFERENCES authority_operation(operation_id)" in sql
    assert "REFERENCES authority_attempt(attempt_id)" in sql
    assert "REFERENCES authority_agent_work_order(work_order_id)" in sql
    assert "fencing_token" in sql
    assert "CREATE TABLE authority_agent_attempt" not in sql
    assert "CREATE TABLE authority_agent_lease" not in sql
    assert "CREATE TABLE authority_capability_pack_run" not in sql


def test_schema_has_version_activation_cas_and_immutable_bindings() -> None:
    sql = _sql()

    assert "CREATE TABLE authority_agent_definition_activation" in sql
    assert "CREATE TABLE authority_chapter_node_agent_binding" in sql
    assert "CREATE TABLE authority_chapter_node_agent_binding_activation" in sql
    assert "expected_version" not in sql
    assert "activation_version" in sql
    assert "authority_agent_runtime_binding_immutable" in sql
    assert "attempt_id TEXT NOT NULL UNIQUE" in sql
    assert "capability_pack_compilation_hash" in sql
    assert "operation_definition_hash" in sql
    assert "release_sha" in sql
    assert "workflow_definition_ref, workflow_node_id,\n            binding_id, binding_version" in sql


def test_schema_does_not_persist_duplicate_agent_run_status() -> None:
    sql = _sql()

    runtime_table = sql.split(
        "CREATE TABLE authority_agent_runtime_binding", maxsplit=1
    )[1].split(")", maxsplit=1)[0]
    assert "run_status" not in runtime_table
    assert "attempt_status" not in runtime_table
    assert "operation_status" not in runtime_table

from __future__ import annotations

from novel_forge.storage.migrations import LATEST_MIGRATION_ID, validate_migration_chain
from novel_forge.storage.migrations.versions import (
    v20260830_0105_p0_backend_qualification_repairs as migration,
)


def test_0105_is_the_registered_forward_only_head() -> None:
    validate_migration_chain()

    assert migration.MIGRATION_ID == "20260830_0105_p0_backend_qualification_repairs"
    assert (
        migration.DOWN_REVISION
        == "20260829_0104_book_opening_workflow_nodes"
    )
    assert migration.FORWARD_ONLY is True
    assert migration.BACKUP_REQUIRED is False
    assert migration.DOWNGRADE_STATEMENTS == []
    assert LATEST_MIGRATION_ID == migration.MIGRATION_ID


def test_0105_indexes_every_0104_foreign_key_by_its_complete_column_set() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    for index_definition in (
        "ON authority_book_opening_legacy_snapshot_entitlement(\n"
        "        snapshot_id,project_id,workspace_id,book_id,snapshot_hash\n"
        "    )",
        "ON authority_book_opening_node_receipt(\n"
        "        opening_run_id,checkpoint_id,checkpoint_sequence,checkpoint_hash\n"
        "    )",
        "ON authority_book_opening_workflow_transition_receipt(\n"
        "        opening_run_id,source_node_receipt_id\n"
        "    )",
        "ON authority_book_opening_input_snapshot_binding(\n"
        "        opening_run_id,node_receipt_id\n"
        "    )",
    ):
        assert index_definition in sql


def test_0105_flushes_deferred_integrity_checks_before_index_ddl() -> None:
    assert migration.UPGRADE_STATEMENTS[0].strip() == (
        "SET CONSTRAINTS ALL IMMEDIATE"
    )
    assert all(
        "CREATE INDEX" not in statement.upper()
        for statement in migration.UPGRADE_STATEMENTS[:1]
    )

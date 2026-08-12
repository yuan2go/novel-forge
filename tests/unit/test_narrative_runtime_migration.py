from __future__ import annotations

from novel_forge.storage.migrations.versions import (
    v20260812_0083_narrative_runtime_convergence as migration,
)


def test_runtime_convergence_migration_is_forward_only_and_adds_no_authority() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    assert migration.MIGRATION_ID == "20260812_0083_narrative_runtime_convergence"
    assert migration.DOWN_REVISION == "20260812_0082_narrative_state_contract_v2"
    assert migration.FORWARD_ONLY is True
    assert migration.BACKUP_REQUIRED is True
    assert migration.DOWNGRADE_STATEMENTS == []
    assert "CREATE TABLE" not in sql
    assert "UPDATE authority_asset_version" not in sql
    assert "DELETE FROM authority_asset_version" not in sql


def test_replan_evidence_and_runtime_usage_are_derived_from_existing_authority() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    for column in ("impact_scope", "preserved_invariants", "decision_evidence"):
        assert f"ADD COLUMN {column}" in sql
    assert "CREATE VIEW authority_context_runtime_usage_projection" in sql
    assert "CREATE VIEW authority_mkaos_runtime_usage_projection" in sql
    assert "authority_operation_output_asset" in sql
    assert "consumer.input_asset_snapshot" in sql
    assert "consumer.status='SUCCEEDED'" in sql
    assert "narrative-context-manifest-v1" in sql
    assert "authority_mkaos_knowledge_pack_item" in sql
    assert "result_asset_version_id" in sql

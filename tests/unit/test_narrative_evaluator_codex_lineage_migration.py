from __future__ import annotations

from novel_forge.storage.migrations import LATEST_MIGRATION_ID, validate_migration_chain
from novel_forge.storage.migrations.versions import (
    v20260824_0097_narrative_evaluator_codex_lineage as migration,
    v20260825_0098_narrative_evolution_engine as evolution,
    v20260825_0099_creative_engineering_convergence as convergence,
    v20260825_0100_hierarchy_closure as hierarchy_closure,
)


def test_codex_lineage_forward_fix_is_the_registered_head() -> None:
    validate_migration_chain()

    assert evolution.DOWN_REVISION == migration.MIGRATION_ID
    assert convergence.DOWN_REVISION == evolution.MIGRATION_ID
    assert hierarchy_closure.DOWN_REVISION == convergence.MIGRATION_ID
    assert LATEST_MIGRATION_ID == hierarchy_closure.MIGRATION_ID
    assert migration.DOWN_REVISION == "20260821_0096_runtime_hardening"
    assert migration.FORWARD_ONLY is True
    assert migration.BACKUP_REQUIRED is False
    assert "no business rows are rewritten" in migration.FORWARD_FIX


def test_provider_lineage_guard_accepts_only_canonical_real_transports() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    assert (
        "CREATE OR REPLACE FUNCTION authority_validate_narrative_provider_lineage"
        in sql
    )
    assert "REMOTE_PROVIDER_API" in sql
    assert "LOCAL_CLI_REMOTE_INFERENCE" in sql
    assert "COALESCE(" in sql
    assert "NOT IN" in sql
    assert "provider_evidence,real_model_call" in sql
    assert "provider_route_snapshot_id" in sql

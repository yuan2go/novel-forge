from __future__ import annotations

from novel_forge.storage.migrations import MIGRATIONS, validate_migration_chain


def test_domain_commit_closure_is_the_linear_head() -> None:
    validate_migration_chain()
    migration = MIGRATIONS[-1]
    assert migration.migration_id == (
        "20260805_0069_agent_runtime_domain_commit_closure"
    )
    assert migration.down_revision == "20260805_0068_unified_agent_runtime"
    sql = "\n".join(migration.upgrade_statements)
    assert "ADD COLUMN attempt_id" in sql
    assert "ADD COLUMN fencing_token" in sql
    assert "ADD COLUMN content_hash" in sql
    assert "authority_agent_commit_candidate_unique" in sql
    assert "authority_agent_commit_exact_asset_unique" in sql
    assert "authority_agent_exact_commit_guard" in sql
    assert "authority_agent_collaboration_commit_immutable" in sql
    assert "CREATE TABLE authority_agent_attempt" not in sql
    assert "CREATE TABLE authority_agent_lease" not in sql

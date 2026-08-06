from __future__ import annotations

from novel_forge.storage.migrations.versions import (
    v20260805_0070_agent_runtime_recovery_protocol as migration,
)


def test_recovery_protocol_keeps_its_linear_predecessor_contract() -> None:
    assert migration.MIGRATION_ID == (
        "20260805_0070_agent_runtime_recovery_protocol"
    )
    assert migration.DOWN_REVISION == (
        "20260805_0069_agent_runtime_domain_commit_closure"
    )
    assert migration.FORWARD_ONLY is True


def test_recovery_protocol_adds_only_immutable_evidence_relations() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    assert "authority_execution_recovery_authorization" in sql
    assert "authority_agent_candidate_supersession" in sql
    assert "authority_agent_session_attempt_unique" in sql
    assert "authority_agent_superseded_commit_guard" in sql
    assert "authority_execution_recovery_immutable" in sql
    assert "authority_agent_candidate_supersession_immutable" in sql
    assert "CREATE TABLE authority_attempt" not in sql
    assert "CREATE TABLE authority_lease" not in sql
    assert "CREATE TABLE authority_external_effect" not in sql
    assert "UPDATE authority_external_effect" not in sql


def test_recovery_authorization_retains_both_fences() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    assert "execution_fencing_token BIGINT NOT NULL" in sql
    assert "recovery_fencing_token BIGINT NOT NULL" in sql
    assert "recovery_fencing_token >= execution_fencing_token" in sql
    assert "status='HELD' AND expires_at > NOW()" in sql
    assert "current_owner IS DISTINCT FROM NEW.recovery_worker_id" in sql

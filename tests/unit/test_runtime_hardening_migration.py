from novel_forge.storage.migrations import LATEST_MIGRATION_ID, validate_migration_chain
from novel_forge.storage.migrations.versions import (
    v20260821_0095_post_merge_correctness_repair as previous,
    v20260821_0096_runtime_hardening as migration,
    v20260824_0097_narrative_evaluator_codex_lineage as codex_lineage,
    v20260825_0098_narrative_evolution_engine as evolution,
    v20260825_0099_creative_engineering_convergence as convergence,
    v20260825_0100_hierarchy_closure as hierarchy_closure,
)


def test_0096_is_forward_only_and_expands_runtime_terminal_evidence() -> None:
    validate_migration_chain()
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    assert migration.DOWN_REVISION == previous.MIGRATION_ID
    assert codex_lineage.DOWN_REVISION == migration.MIGRATION_ID
    assert evolution.DOWN_REVISION == codex_lineage.MIGRATION_ID
    assert convergence.DOWN_REVISION == evolution.MIGRATION_ID
    assert hierarchy_closure.DOWN_REVISION == convergence.MIGRATION_ID
    assert hierarchy_closure.MIGRATION_ID == LATEST_MIGRATION_ID
    assert migration.FORWARD_ONLY is True
    for status in (
        "FAILED_RETRYABLE",
        "FAILED_FINAL",
        "DEAD_LETTER",
        "CANCELLED",
        "RECONCILIATION_REQUIRED",
        "MANUAL_INTERVENTION",
    ):
        assert f"'{status}'" in sql
    assert "CREATE EXTENSION IF NOT EXISTS vector" in sql
    assert "embedding_vector vector" in sql
    assert "vector_cosine_ops" in sql
    assert "halfvec_cosine_ops" in sql
    assert "authority_retrieval_candidate_snapshot" in sql
    assert "authority_retrieval_candidate_snapshot_immutable" in sql
    assert "authority_retrieval_candidate_snapshot_scope" in sql
    assert "query_plan_fingerprint" in sql
    assert "ranking_policy_version" in sql

    assert "authority_retrieval_embedding_projection" in sql
    assert "FAILED_TERMINAL_TO_FAILED_FINAL" in sql
    for status in (
        "FAILED_RETRYABLE",
        "FAILED_FINAL",
        "DEAD_LETTER",
        "CANCELLED",
        "RECONCILIATION_REQUIRED",
    ):
        assert f"'{status}'" in sql

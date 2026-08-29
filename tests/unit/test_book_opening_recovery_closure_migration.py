from __future__ import annotations

from novel_forge.storage.migrations import MIGRATIONS, validate_migration_chain
from novel_forge.storage.migrations.versions import (
    v20260828_0102_book_opening_recovery_closure as migration,
)


def test_book_opening_recovery_closure_remains_in_the_forward_chain() -> None:
    validate_migration_chain()

    assert migration.MIGRATION_ID in {
        item.migration_id for item in MIGRATIONS
    }
    assert migration.DOWN_REVISION == "20260826_0101_quality_qualification"
    assert migration.FORWARD_ONLY is True
    assert migration.BACKUP_REQUIRED is False
    assert migration.DOWNGRADE_STATEMENTS == []


def test_expand_schema_separates_execution_loss_from_recovery_authorization() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    for table in (
        "authority_book_opening_execution",
        "authority_book_opening_semantic_checkpoint",
        "authority_book_opening_recovery_assessment",
        "authority_book_opening_recovery_intent",
        "authority_book_opening_recovery_receipt",
        "authority_narrative_evaluation_execution",
        "authority_narrative_evaluation_execution_head",
    ):
        assert f"CREATE TABLE {table}" in sql
    assert "'EXECUTION_LOSS_CONVERGENCE'" in sql
    assert "'RECOVERY_ADMISSION'" in sql
    assert "receipt_kind='EXECUTION_LOSS_CONVERGENCE'" in sql
    assert "recovery_intent_id IS NULL" in sql
    assert "receipt_kind='RECOVERY_ADMISSION'" in sql
    assert "recovery_intent_id IS NOT NULL" in sql


def test_runtime_takeover_policy_and_relational_binding_are_database_enforced() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    assert "lease_loss_policy TEXT NOT NULL DEFAULT 'SAME_JOB_TAKEOVER'" in sql
    assert "'AUTHORITY_CONVERGENCE_REQUIRED'" in sql
    assert "WHERE job_kind='BOOK_OPENING_EXECUTE'" in sql
    assert "current_execution_id TEXT" in sql
    assert "current_execution_generation BIGINT" in sql
    assert "authority_book_opening_current_execution_fk" in sql
    assert "authority_book_opening_execution_attempt_fk_idx" in sql
    assert "BOOK_OPENING_RUNTIME_BINDING_INVALID" in sql
    assert "BOOK_OPENING_RELATIONAL_CLOSURE_INVALID" in sql
    assert "RUNTIME_JOB_CURRENT_CLAIM_IDENTITY_INVALID" in sql
    assert "authority_book_opening_runtime_policy_check" in sql
    assert "authority_book_opening_runtime_policy_guard" in sql
    assert "RUNTIME_JOB_AUTHORITY_ATTEMPT_REPLACEMENT_FORBIDDEN" in sql
    assert "authority_runtime_job_attempt_no_takeover_guard" in sql
    assert "binding.job_status IS DISTINCT FROM 'READY'" in sql
    assert "CREATE CONSTRAINT TRIGGER" in sql
    assert "DEFERRABLE INITIALLY DEFERRED" in sql
    assert "lease_expires_at" not in sql


def test_evaluation_predecessor_index_has_each_identity_column_once() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS)
    marker = "CREATE INDEX authority_narrative_evaluation_predecessor_fk_idx"
    statement = next(item for item in migration.UPGRADE_STATEMENTS if marker in item)
    columns = statement.split(
        "ON authority_narrative_evaluation_execution(", maxsplit=1
    )[1].split(")", maxsplit=1)[0]

    assert columns.count("predecessor_execution_id") == 1
    assert columns.count("predecessor_generation") == 1
    assert columns.count("predecessor_operation_id") == 1
    assert sql.count(marker) == 1


def test_checkpoint_and_evaluation_generation_are_append_only_lineage() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    for token in (
        "predecessor_checkpoint_id",
        "predecessor_checkpoint_hash",
        "checkpoint_hash",
        "semantic_work_key",
        "owning_authority",
        "evidence_id",
        "evidence_version",
        "evidence_hash",
        "predecessor_execution_id",
        "predecessor_operation_id",
        "recovery_intent_id",
        "UNIQUE(project_id, candidate_asset_version_id, generation)",
        "authority_narrative_evaluation_execution_head",
    ):
        assert token in sql
    assert "NARRATIVE_EVALUATION_EXECUTION_TERMINAL_IMMUTABLE" in sql
    assert "BOOK_OPENING_RECOVERY_FACT_IMMUTABLE" in sql
    assert "UNIQUE(opening_run_id, semantic_work_key)" in sql


def test_recovery_facts_are_deferred_relationally_bound() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    assert "authority_assert_book_opening_recovery_fact" in sql
    assert "authority_book_opening_recovery_fact_guard" in sql
    assert "BOOK_OPENING_RECOVERY_INTENT_ASSESSMENT_BINDING_INVALID" in sql
    assert "BOOK_OPENING_RECOVERY_INTENT_RECEIPT_REQUIRED" in sql
    assert "BOOK_OPENING_RECOVERY_RECEIPT_ASSESSMENT_KIND_INVALID" in sql
    assert "BOOK_OPENING_RECOVERY_RECEIPT_ASSESSMENT_BINDING_INVALID" in sql
    assert "BOOK_OPENING_RECOVERY_RECEIPT_DISPOSITION_INVALID" in sql
    assert "BOOK_OPENING_RECOVERY_RECEIPT_INTENT_BINDING_INVALID" in sql
    assert "BOOK_OPENING_RECOVERY_RECEIPT_OPENING_BINDING_INVALID" in sql
    assert "LEGACY_EXECUTION_RECONCILIATION" in sql
    assert "DEFERRABLE INITIALLY DEFERRED" in sql


def test_opening_heads_and_checkpoint_digests_are_database_guarded() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    assert "authority_book_opening_head_monotonic_guard" in sql
    assert "BOOK_OPENING_EXECUTION_HEAD_NON_MONOTONIC" in sql
    assert "BOOK_OPENING_CHECKPOINT_HEAD_NON_MONOTONIC" in sql
    assert "authority_assert_book_opening_checkpoint_binding" in sql
    assert "BOOK_OPENING_CHECKPOINT_BINDING_INVALID" in sql
    assert "binding.execution_request_digest IS DISTINCT FROM" in sql
    assert "binding.opening_request_digest" in sql
    assert "recovery_intent_id TEXT UNIQUE" in sql
    assert "NARRATIVE_EVALUATION_RECOVERY_INTENT_BINDING_INVALID" in sql


def test_legacy_terminal_execution_compatibility_preserves_terminal_truth() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    assert "runtime_job_id TEXT UNIQUE" in sql
    assert "generation=1" in sql
    assert "NEW.lifecycle NOT IN ('FAILED','ABORTED')" in sql
    assert "binding.job_status NOT IN ('FAILED','DEAD_LETTER')" in sql
    assert "'FAILED','LOST','ABORTED'" in sql


def test_legacy_semantic_execution_bootstrap_preserves_operation_truth() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS)
    upper = sql.upper()

    assert "narrative-evaluation-execution:legacy:" in sql
    assert "operation.command_payload->'payload'->>'candidate_asset_version_id'" in sql
    assert "operation.operation_id" in sql
    assert "operation.status='CANCELLED' THEN 'CANCELLED'" in sql
    assert "generation=1" in sql
    assert "DROP INDEX AUTHORITY_NARRATIVE_EVALUATION_CANDIDATE_ONCE_IDX" not in upper
    assert "UPDATE AUTHORITY_OPERATION" not in upper
    assert "UPDATE AUTHORITY_ATTEMPT" not in upper
    assert "UPDATE AUTHORITY_LEASE_ACQUISITION" not in upper


def test_migration_fails_closed_for_malformed_legacy_candidate_evidence() -> None:
    preflight = "\n".join(migration.PREFLIGHT_STATEMENTS)

    assert "semantic_evaluation_candidate_identity_missing" in preflight
    assert "semantic_evaluation_candidate_identity_duplicate" in preflight
    assert "semantic_evaluation_candidate_evidence_invalid" in preflight
    assert "runtime_job_active_claim_identity_invalid" in preflight
    assert "authority_asset_version" in preflight
    assert "authority_book" in preflight


def test_contract_migration_is_deliberately_deferred() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS).upper()

    assert "DROP TABLE" not in sql
    assert "DROP COLUMN" not in sql
    assert "DROP INDEX" not in sql
    assert "LEGACY_RECONCILIATION_REQUIRED" in sql
    assert "histor" in migration.FORWARD_FIX.lower()

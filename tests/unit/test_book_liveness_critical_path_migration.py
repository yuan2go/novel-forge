from __future__ import annotations

from novel_forge.storage.migrations import LATEST_MIGRATION_ID, validate_migration_chain
from novel_forge.storage.migrations.versions import (
    v20260814_0092_longform_correctness_closure as previous,
    v20260820_0093_book_liveness_critical_path_closure as migration,
    v20260824_0097_narrative_evaluator_codex_lineage as codex_lineage,
    v20260825_0098_narrative_evolution_engine as evolution,
    v20260825_0099_creative_engineering_convergence as convergence,
    v20260825_0100_hierarchy_closure as hierarchy_closure,
    v20260826_0101_quality_qualification as quality_qualification,
    v20260828_0102_book_opening_recovery_closure as recovery_closure,
    v20260829_0103_book_opening_semantic_runtime_hardening as semantic_hardening,
)


def test_book_liveness_closure_is_the_forward_only_backup_required_head() -> None:
    validate_migration_chain()

    assert migration.DOWN_REVISION == previous.MIGRATION_ID
    assert evolution.DOWN_REVISION == codex_lineage.MIGRATION_ID
    assert convergence.DOWN_REVISION == evolution.MIGRATION_ID
    assert hierarchy_closure.DOWN_REVISION == convergence.MIGRATION_ID
    assert quality_qualification.DOWN_REVISION == hierarchy_closure.MIGRATION_ID
    assert recovery_closure.DOWN_REVISION == quality_qualification.MIGRATION_ID
    assert semantic_hardening.DOWN_REVISION == recovery_closure.MIGRATION_ID
    assert LATEST_MIGRATION_ID == "20260829_0104_book_opening_workflow_nodes"
    assert migration.FORWARD_ONLY is True
    assert migration.BACKUP_REQUIRED is True
    assert "pre-0093 backup" in migration.FORWARD_FIX
    assert "durable follow-up operation link" in migration.FORWARD_FIX


def test_book_liveness_migration_is_evidence_guarded_and_adds_query_indexes() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    assert "book.state='COMPLETED'" in sql
    assert "group_run.state='CLOSURE_PENDING'" in sql
    assert "accepted_through_chapter > 0" in sql
    assert "acceptance.status='COMMITTED'" in sql
    assert "active_chapter_request_id IS NULL" in sql
    assert "DROP COLUMN last_reader_outcome_operation_id" in sql
    assert "DROP COLUMN last_recap_operation_id" in sql
    for index_name in (
        "authority_book_acceptance_followup_admission_idx",
        "authority_book_followup_backlog_idx",
        "authority_book_followup_runtime_job_progress_idx",
    ):
        assert f"CREATE INDEX {index_name}" in sql
    assert "runtime_group='book_followup'" in sql
    assert "job_kind='BOOK_FOLLOWUP_ADMISSION'" in sql

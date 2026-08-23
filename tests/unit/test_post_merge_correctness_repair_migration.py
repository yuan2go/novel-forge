from novel_forge.storage.migrations import LATEST_MIGRATION_ID, validate_migration_chain
from novel_forge.storage.migrations.versions import (
    v20260820_0094_industrial_autonomous_novel_os as previous,
)
from novel_forge.storage.migrations.versions import (
    v20260821_0095_post_merge_correctness_repair as migration,
)


def test_0095_is_forward_only_registration_not_projection_business_logic() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    validate_migration_chain()
    assert migration.DOWN_REVISION == previous.MIGRATION_ID
    assert migration.FORWARD_ONLY is True
    assert migration.MIGRATION_ID != LATEST_MIGRATION_ID
    assert "CREATE TABLE authority_book_projection_repair" in sql
    assert "CREATE TABLE authority_book_projection_repair_checkpoint" in sql
    assert "BOOK_PROJECTION_REPAIR" in sql
    assert "AUTHORITATIVE_REPAIR_COMPLETE" in sql
    assert "RETRIEVAL_SEMANTIC_PROJECTION_READY" in sql
    assert "active_longform_projection_set_id IS NULL" in sql
    assert "active_projection.chapter_number<>production.accepted_through_chapter" in sql
    assert "ACCEPTED_CHAPTER_SEQUENCE_INVALID" in sql
    assert "authority_sha256_jsonb(repair.repair_input)" in sql
    assert "FOREIGN KEY(attempt_id, fencing_token)" in sql
    assert "runtime_fencing_token" in sql
    assert "terminal_command_fencing_token" in sql
    assert "terminal_runtime_fencing_token" in sql
    assert "acceptance_operation_status" in sql
    assert "chapter_plan_content_hash" in sql
    assert "authority_attempt_identity_operation_idx" in sql
    assert "authority_arc_progress_v2" not in sql
    assert "authority_arc_actual_state" not in sql
    assert "authority_narrative_obligation_state" not in sql
    assert "UPDATE authority_book_production\n    SET active_longform_projection_set_id" not in sql


def test_0095_keeps_authoritative_and_semantic_completion_independent() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    assert "authoritative_status TEXT NOT NULL" in sql
    assert "semantic_projection_status TEXT NOT NULL" in sql
    assert "AUTHORITATIVE_REPAIR_COMPLETE" in sql
    assert "UNAVAILABLE_BY_POLICY" in sql
    assert "CHECK (authoritative_status IN" in sql
    assert "CHECK (semantic_projection_status IN" in sql


def test_0095_registers_arc_followup_and_embedding_projection_authority() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    assert "CREATE TABLE authority_arc_checkpoint_followup" in sql
    assert "CREATE TABLE authority_retrieval_embedding_projection" in sql
    assert "external_effect_id" in sql
    assert "receipt_id" in sql
    assert "projection_hash" in sql

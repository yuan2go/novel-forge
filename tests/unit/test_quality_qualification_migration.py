from __future__ import annotations

from novel_forge.storage.migrations import LATEST_MIGRATION_ID, validate_migration_chain
from novel_forge.storage.migrations.versions import (
    v20260826_0101_quality_qualification as migration,
    v20260828_0102_book_opening_recovery_closure as successor,
    v20260829_0103_book_opening_semantic_runtime_hardening as semantic_hardening,
)


def test_quality_qualification_extends_one_forward_head() -> None:
    validate_migration_chain()

    assert successor.DOWN_REVISION == migration.MIGRATION_ID
    assert semantic_hardening.DOWN_REVISION == successor.MIGRATION_ID
    assert LATEST_MIGRATION_ID == "20260829_0104_book_opening_workflow_nodes"
    assert migration.DOWN_REVISION == "20260825_0100_hierarchy_closure"
    assert migration.FORWARD_ONLY is True
    assert migration.DOWNGRADE_STATEMENTS == []


def test_campaign_evidence_schema_is_layered_and_fail_closed() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    for table in (
        "authority_quality_qualification_campaign",
        "authority_quality_qualification_subject",
        "authority_quality_qualification_evidence",
        "authority_quality_qualification_decision",
    ):
        assert f"CREATE TABLE {table}" in sql
    for value in (
        "L1_HARD_CORRECTNESS",
        "L2_EDITORIAL_QUALITY",
        "L3_READER_LONGITUDINAL",
        "PASS_WITH_LIMITATIONS",
        "NOT_PROVEN",
        "WAITING_HUMAN_EVIDENCE",
    ):
        assert f"'{value}'" in sql
    assert "exact_release_sha" in sql
    assert "migration_head" in sql
    assert "manifest_asset_version_id" in sql
    assert "provider_route_manifest" in sql
    assert "capability_pack_manifest" in sql
    assert "foundation_lineage" in sql
    assert "planning_lineage" in sql
    assert "realization_lineage" in sql
    assert "budget_policy" in sql
    assert "chapter_group_ranges" in sql
    assert "decision_version BIGINT NOT NULL" in sql
    assert "UNIQUE(campaign_id, decision_version)" in sql
    assert "CREATE VIEW authority_current_quality_qualification_decision" in sql


def test_human_blind_schema_extends_existing_reader_calibration_authority() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    assert "ALTER TABLE human_preference_task" in sql
    assert "ALTER TABLE human_preference_pair" in sql
    assert "ALTER TABLE human_preference_decision" in sql
    assert "CREATE TABLE human_preference_evaluation_pack" in sql
    assert "CREATE TABLE human_preference_adjudication" in sql
    for field in (
        "protocol_version",
        "evaluation_profile_version",
        "evaluator_identity_class",
        "scope_type",
        "chapter_start",
        "chapter_end",
        "dimension_scores",
        "adjudication_status",
        "blind_pair_token",
        "private_mapping_hash",
    ):
        assert field in sql
    for value in (
        "'CANNOT_JUDGE'",
        "'CHAPTER'",
        "'ARC'",
        "'AGREED'",
        "'DISAGREED'",
        "'ADJUDICATED'",
    ):
        assert value in sql
    assert "position_revealed_after_decision=FALSE" in sql.replace(" ", "")
    assert "REFERENCES authority_asset_version(asset_version_id)" in sql
    assert "REFERENCES authority_operation(operation_id)" in sql


def test_migration_preserves_historical_rows_and_is_non_destructive() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS).upper()

    assert "DELETE FROM HUMAN_PREFERENCE" not in sql
    assert "DROP TABLE" not in sql
    assert "REJECT_BOTH" in sql
    assert migration.BACKUP_REQUIRED is False
    assert "historical" in migration.FORWARD_FIX.lower()


def test_operator_authored_foundation_source_is_explicit_not_provider_evidence() -> (
    None
):
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    assert "OPERATOR_AUTHORED" in sql
    assert "authority_story_design_version_state_source_kind_check" in sql

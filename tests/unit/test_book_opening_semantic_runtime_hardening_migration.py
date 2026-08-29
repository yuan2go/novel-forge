from __future__ import annotations

import inspect
import re

from novel_forge.modules.story_design_authority.application import (
    _OPERATOR_AUTHOR_OPERATION_BY_GENERATOR,
)
from novel_forge.modules.story_design_authority.replacement_gate import (
    assert_narrative_replacement_execution_gate_in_uow,
)
from novel_forge.storage.migrations import LATEST_MIGRATION_ID, validate_migration_chain
from novel_forge.storage.migrations.versions import (
    v20260829_0103_book_opening_semantic_runtime_hardening as migration,
)


def test_semantic_runtime_hardening_is_the_forward_only_head() -> None:
    validate_migration_chain()

    assert LATEST_MIGRATION_ID == migration.MIGRATION_ID
    assert migration.DOWN_REVISION == "20260828_0102_book_opening_recovery_closure"
    assert migration.FORWARD_ONLY is True
    assert migration.BACKUP_REQUIRED is False
    assert migration.DOWNGRADE_STATEMENTS == []


def test_future_branch_evidence_is_relationally_bound_and_immutable() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    assert "branch_evidence_contract_version" in sql
    assert "branch_evidence_hash" in sql
    assert "authority_story_planning_generation_search_identity" in sql
    assert "authority_story_narrative_membership_generation_fk" in sql
    assert "NARRATIVE_SEARCH_MEMBERSHIP_IDENTITY_IMMUTABLE" in sql
    assert "NARRATIVE_SEARCH_BRANCH_EVIDENCE_INVALID" in sql
    assert "narrative_search_id" in sql
    assert "narrative_search_branch_key" in sql


def test_legacy_branch_reconciliation_is_append_only_and_outer_bound() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    assert (
        "CREATE TABLE authority_story_narrative_branch_reconciliation_evidence" in sql
    )
    assert "CREATE TABLE authority_book_opening_branch_reconciliation_assessment" in sql
    assert "CREATE TABLE authority_book_opening_branch_reconciliation_receipt" in sql
    assert "source_branch_evidence_contract_version='legacy-unbound'" in sql
    assert "narrative-search-branch-reconciliation.v1" in sql
    assert "authority_story_narrative_branch_reconciliation_immutable" in sql
    assert "authority_book_opening_branch_reconciliation_assessment_immutable" in sql
    assert "authority_book_opening_branch_reconciliation_receipt_immutable" in sql
    assert "qualification_receipt_set_hash" in sql
    assert "runtime_fencing_token" in sql
    assert "reconciliation_evidence_id,evidence_version,evidence_hash" in sql
    assert "checkpoint_id,checkpoint_sequence,checkpoint_hash" in sql
    assert "event_id TEXT NOT NULL UNIQUE" in sql


def test_budget_scope_and_assessment_v2_are_database_bound() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    assert "CREATE TABLE authority_provider_budget_scope" in sql
    assert "CREATE TABLE authority_budget_evidence_link" in sql
    assert "budget_scope_id" in sql
    assert "assessment_contract_version" in sql
    assert "budget_policy_hash" in sql
    assert "budget_snapshot_digest" in sql
    assert "budget_outcome" in sql
    assert "BOOK_OPENING_RECOVERY_ASSESSMENT_V2_BUDGET_INVALID" in sql
    assert "PROJECTION_ONLY" in sql
    assert "RECONCILIATION_REQUIRED" in sql


def test_budget_reservation_identity_lifecycle_and_version_are_database_guarded() -> (
    None
):
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    assert "authority_budget_reservation_version_guard" in sql
    assert "authority_budget_reservation_version_monotonic" in sql
    assert "BUDGET_RESERVATION_IDENTITY_IMMUTABLE" in sql
    assert "BUDGET_RESERVATION_TERMINAL_IMMUTABLE" in sql
    assert "BUDGET_RESERVATION_TRANSITION_INVALID" in sql
    assert "BUDGET_RESERVATION_VERSION_NON_MONOTONIC" in sql
    assert "BUDGET_RESERVATION_VERSION_WITHOUT_CHANGE" in sql


def test_legacy_budget_reconciliation_receipt_is_unique_and_immutable() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    assert "CREATE TABLE authority_book_opening_budget_reconciliation_receipt" in sql
    assert "UNIQUE(opening_run_id)" in sql
    assert "UNIQUE(command_operation_id)" in sql
    assert "UNIQUE(opening_run_id,intent_hash)" in sql
    assert "authority_book_opening_budget_reconciliation_receipt_immutable" in sql
    assert "novel_forge_reject_immutable_mutation" in sql


def test_replacement_gate_is_derived_from_existing_authority_rows() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS)
    gate_sql = next(
        statement
        for statement in migration.UPGRADE_STATEMENTS
        if "CREATE OR REPLACE FUNCTION authority_narrative_replacement_gate_is_open"
        in statement
    )
    preflight = "\n".join(migration.PREFLIGHT_STATEMENTS)

    assert "authority_narrative_replacement_gate_is_open" in sql
    assert "authority_narrative_replacement_operation_gate_guard" in sql
    assert "authority_narrative_replacement_evaluation_gate_guard" in sql
    assert "authority_narrative_replacement_attempt_gate_guard" in sql
    assert "authority_narrative_replacement_effect_gate_guard" in sql
    assert "authority_narrative_replacement_dispatch_gate_guard" in sql
    assert "NARRATIVE_EVALUATION_REPLACEMENT_EXECUTION_GATE_CLOSED" in sql
    assert "semantic_execution_mode" in sql
    assert "NEW_REPLACEMENT" in sql
    assert "RESUME_CURRENT" in sql
    assert "RETURNS BOOLEAN LANGUAGE plpgsql VOLATILE" in gate_sql
    assert "lease.lease_expires_at>clock_timestamp()" in gate_sql
    assert "lease.lease_expires_at>transaction_timestamp()" not in gate_sql
    assert "IF NOT FOUND" in gate_sql
    assert "NOT FOUND OR evaluation.generation=1" not in gate_sql
    assert "opening.book_id=evaluation.book_id" in gate_sql
    assert "assessment.assessment_kind='RECOVERY'" in gate_sql
    assert "receipt.recovery_assessment_id" in gate_sql
    assert "replacement_evaluation_execution_id" in gate_sql
    assert "evaluation.predecessor_operation_id" in gate_sql
    assert "generation_operation.definition_name=" in gate_sql
    assert "'story_planning.generate'" in gate_sql
    assert "generation_output.asset_version_id" in gate_sql
    assert "design_state.source_kind='OPERATOR_AUTHORED'" in gate_sql
    assert "'story_design.creative_foundation.author'" in gate_sql
    assert "generation_version.content->>'provider_generated'" in gate_sql
    assert "'opening_execution_binding'" in gate_sql
    assert "jsonb_object_length" not in gate_sql
    assert "COUNT(*) FROM jsonb_object_keys(opening_binding)" in gate_sql
    assert "active_semantic_evaluation_lineage_missing" in preflight
    assert "active_replacement_runtime_binding_missing" in preflight
    assert "active_replacement_operation_outer_gate_closed" in preflight
    assert "held_replacement_dispatch_outer_gate_closed" in preflight
    assert sql.count("IF NOT FOUND THEN") >= 3
    assert "NARRATIVE_EVALUATION_OPERATION_LINEAGE_MISSING" in sql
    assert "NARRATIVE_EVALUATION_DISPATCH_LINEAGE_MISSING" in sql
    assert "CREATE TABLE authority_narrative_replacement_gate" not in sql


def test_operator_authoring_gate_mapping_matches_story_design_authority() -> None:
    expected = {
        "creative.candidates.generate": (
            "story_design.creative_foundation.author",
            "creative_foundation",
        ),
        "theme.candidates.generate": (
            "story_design.theme_contract.author",
            "theme_contract",
        ),
        "ending.intent.generate": (
            "story_design.ending_intent.author",
            "ending_intent",
        ),
        "reader.promise.generate": (
            "story_design.reader_promise.author",
            "reader_promise",
        ),
        "world.design.generate": (
            "story_design.world_bible.author",
            "world_bible",
        ),
        "character.cast.generate": (
            "story_design.character_cast.author",
            "character_cast",
        ),
    }
    assert _OPERATOR_AUTHOR_OPERATION_BY_GENERATOR == expected
    gate_sql = next(
        statement
        for statement in migration.UPGRADE_STATEMENTS
        if "CREATE OR REPLACE FUNCTION authority_narrative_replacement_gate_is_open"
        in statement
    )
    python_gate = inspect.getsource(
        assert_narrative_replacement_execution_gate_in_uow
    )
    for generator, (author_definition, asset_type) in expected.items():
        author_mapping = re.compile(
            rf"WHEN\s+'{re.escape(generator)}'\s+THEN\s+"
            rf"'{re.escape(author_definition)}'"
        )
        asset_mapping = re.compile(
            rf"WHEN\s+'{re.escape(generator)}'\s+THEN\s+"
            rf"'{re.escape(asset_type)}'"
        )
        assert author_mapping.search(gate_sql)
        assert asset_mapping.search(gate_sql)
        assert author_mapping.search(python_gate)
        assert asset_mapping.search(python_gate)


def test_migration_preserves_history_and_requires_explicit_legacy_reconciliation() -> (
    None
):
    sql = "\n".join(migration.UPGRADE_STATEMENTS).upper()

    assert "UPDATE AUTHORITY_OPERATION" not in sql
    assert "UPDATE AUTHORITY_ATTEMPT" not in sql
    assert "UPDATE AUTHORITY_LEASE_ACQUISITION" not in sql
    assert "UPDATE AUTHORITY_BOOK_OPENING_RECOVERY_ASSESSMENT" not in sql
    assert "LEGACY_BUDGET_RECONCILIATION_REQUIRED" in sql
    assert "DROP TABLE" not in sql
    assert "DROP COLUMN" not in sql

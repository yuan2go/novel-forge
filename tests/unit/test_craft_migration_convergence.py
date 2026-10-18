import hashlib
import json
from pathlib import Path

import pytest

from novel_forge.storage.migrations import MIGRATIONS, pending_migrations, validate_migration_chain
from novel_forge.storage.migrations.versions import (
    v20261014_0211_world_input_delivery_recovery as main_world,
    v20261015_0214_story_design_book_scope as scope,
    v20261015_0217_craft_context_convergence as convergence,
    v20261015_0217_retained_working_continuation as retained_published,
    v20261015_0218_retained_working_convergence as retained_convergence,
)


def test_main_upgrade_appends_convergence_and_rejects_both_foreign_and_discontinuous_history():
    validate_migration_chain()
    main_head = next(index for index, item in enumerate(MIGRATIONS)
                     if item.migration_id == "20261014_0212_prose_citation_revalidation")
    applied = {item.migration_id for item in MIGRATIONS[:main_head + 1]}
    assert [item.migration_id for item in pending_migrations(applied)] == [
        "20261015_0213_source_method_isolation",
        "20261015_0214_story_design_book_scope",
        "20261015_0215_planning_input_scope_reads",
        "20261015_0216_operation_evidence_indexes",
        "20261015_0217_craft_context_convergence",
        "20261015_0218_retained_working_convergence",
        "20261015_0219_world_exact_context_convergence",
        "20261015_0220_chapter_prior_audit_convergence",
        "20261016_0221_working_scope_fk_indexes",
        "20261016_0222_planning_host_frozen_definition",
        "20261018_0223_working_plan_input_continuation",
        "20261018_0224_working_regeneration_isolation",
        "20261018_0225_impacted_working_plan_continuation",
        "20261018_0226_semantic_preparation_continuation",
        "20261018_0227_completed_preparation_handoff",
        "20261018_0228_terminal_preparation_handoff",
        "20261019_0229_routing_observation_preparation_recovery",
        "20261019_0230_unsent_preparation_lineage",
        "20261019_0231_prepared_main_handoff",
    ]
    with pytest.raises(ValueError, match="MIGRATION_HISTORY_FOREIGN"):
        pending_migrations(applied | {"20261014_0205_source_observation_generation_isolation"})
    with pytest.raises(ValueError, match="MIGRATION_HISTORY_DISCONTINUOUS"):
        pending_migrations(applied - {"20261013_0205_completed_release_recovery"})


def test_published_craft_modules_remain_exact_and_outside_active_registry():
    root = Path(__file__).resolve().parents[2]
    history = root / "src/novel_forge/storage/migrations/historical/craft_16291555"
    manifest = json.loads((history / "manifest.json").read_text())
    assert manifest["source_commit"] == "1629155509ef6b0c6b8f41a1f35cee326517f9be"
    assert manifest["registered_on_main"] is False
    assert len(manifest["modules"]) == 12
    active = {item.migration_id for item in MIGRATIONS}
    for row in manifest["modules"]:
        original = root / row["original_path"]
        retained = root / row["retained_path"]
        assert not original.exists()
        assert retained.parent == history
        assert hashlib.sha256(retained.read_bytes()).hexdigest() == row["sha256"]
        assert retained.stem[1:] not in active


def test_retained_working_published_bytes_and_exact_sql_are_preserved_after_canonical_head():
    root = Path(__file__).resolve().parents[2]
    history = root / "src/novel_forge/storage/migrations/historical/craft_2eb0e685"
    manifest = json.loads((history / "manifest.json").read_text())
    assert manifest["source_commit"] == "2eb0e685e0e4dc3c84a931330f3fb3e97156d8d7"
    assert manifest["registered_on_main"] is False and len(manifest["modules"]) == 1
    row = manifest["modules"][0]
    assert not (root / row["original_path"]).exists()
    assert hashlib.sha256((root / row["retained_path"]).read_bytes()).hexdigest() == row["sha256"]
    assert row["sha256"] == "c7d6edf87979553c12d32679a42f8056c941f0ea0b9150a25f40b89ee1fa0718"
    assert retained_convergence.DOWN_REVISION == convergence.MIGRATION_ID
    assert retained_convergence.UPGRADE_STATEMENTS == retained_published.UPGRADE_STATEMENTS
    retained_index = next(index for index, item in enumerate(MIGRATIONS)
                          if item.migration_id == retained_convergence.MIGRATION_ID)
    assert MIGRATIONS[retained_index + 1].down_revision == retained_convergence.MIGRATION_ID
    with pytest.raises(ValueError, match="MIGRATION_HISTORY_FOREIGN"):
        pending_migrations({item.migration_id for item in MIGRATIONS[:-1]} | {retained_published.MIGRATION_ID})


def test_latest_published_fork_sources_remain_importable_without_becoming_active_migrations():
    import importlib
    root = Path(__file__).resolve().parents[2]
    history = root / "src/novel_forge/storage/migrations/historical/craft_f06f4dac"
    manifest = json.loads((history / "manifest.json").read_text())
    assert manifest["source_commit"] == "f06f4daccada314b25f7559733ad331d5c056da0"
    assert manifest["registered_on_main"] is False and len(manifest["modules"]) == 3
    active = {item.migration_id for item in MIGRATIONS}
    for row in manifest["modules"]:
        original = root / row["original_path"]
        retained = root / row["retained_path"]
        assert not original.exists()
        assert hashlib.sha256(retained.read_bytes()).hexdigest() == row["sha256"]
        module = importlib.import_module("novel_forge.storage.migrations.versions." + retained.stem)
        assert hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest() == row["sha256"]
        assert module.MIGRATION_ID not in active
    from novel_forge.tools.architecture_manifest import check_migrations
    assert check_migrations(root)["head"] == "20261019_0231_prepared_main_handoff"


def test_capacity_composition_retains_latest_world_delivery_and_inheritance_verbatim():
    statement = convergence.CAPACITY_STATEMENT
    assert main_world._DELIVERY in statement
    for contract in (
        "world-host-revalidation.v1", "world-host-revalidation.v2",
        "world-host-revalidation.v3", "world-host-revalidation.v4",
        "world-isolated-source-correction.v1", "world-source-inheritance.v1",
        "foundation-method-recall-projection.v1", "book-method-scope-projection.v1",
        "group-method-scope-projection.v1",
    ):
        assert contract in statement
    assert statement.count("generation->>'generator_operation_name'='character.cast.generate'") == 2
    assert statement.count("context.content->>'planning_scope'=prior.planning_scope") == 1
    assert "context.content->>'planning_scope'=r.source_command->>'planning_scope'" not in statement
    assert "AND r.target_runtime#>'{planning_capacity,context_revalidation,world_input_delivery}' IS NULL" in statement


def test_guard_preserves_main_and_separates_zero_effect_world_from_two_completed_world_calls():
    main_head = next(index for index, item in enumerate(MIGRATIONS)
                     if item.migration_id == "20261014_0212_prose_citation_revalidation")
    prior = [statement for item in MIGRATIONS[:main_head + 1] for statement in item.upgrade_statements
             if "CREATE OR REPLACE FUNCTION authority_planning_result_repair_guard()" in statement][-1]
    assert prior == convergence._BASE_GUARD
    for function in (
        "authority_generation_continuation_permitted", "authority_unsent_context_continuation_permitted",
        "authority_schema_continuation_permitted", "authority_unsent_query_continuation_permitted",
        "authority_book_unsent_query_continuation_permitted",
        "authority_unsent_world_context_continuation_permitted",
        "authority_prepared_chapter_context_continuation_permitted",
    ):
        assert f"AND NOT {function}(" in convergence.GUARD_STATEMENT
    world, chapter = convergence.WORLD_STATEMENTS
    assert "external_intents_at_source}'='0'::jsonb" in world
    assert "NOT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=source.operation_id)" in world
    assert "external_intents_at_source}'='2'::jsonb" in chapter
    assert "authority_prepared_world_source_safe(source.operation_id,r.target_runtime)" in chapter
    for statement in (world, chapter, *convergence.QUERY_STATEMENTS):
        assert "authority_story_creation_cancellation" in statement
        assert "authority_worker_cancel_signal" in statement
        assert "authority_lease_acquisition" in statement


def test_scope_backfill_checks_nested_and_producer_lineage_before_upgrading():
    for statement in (scope.BOOK_SCOPE_STATEMENT, scope.PREFLIGHT_STATEMENTS[0]):
        assert "{scope,book_id}" in statement
        assert "{creative_input_selection,book_id}" in statement
        assert "request.chapter_root_operation_id=operation.root_operation_id" in statement
        assert "operation.project_id=" in statement
    assert "STORY_DESIGN_BOOK_LINEAGE_AMBIGUOUS" in scope.PREFLIGHT_STATEMENTS[0]
    assert "STORY_DESIGN_BOOK_OWNER_MISSING" in scope.PREFLIGHT_STATEMENTS[0]
    assert "ELSE 'BOOK:'||book_id END" in scope.UPGRADE_STATEMENTS[3]
    assert "'LEGACY_UNBOUND'" in scope.UPGRADE_STATEMENTS[3]


def test_working_plan_input_recovery_retains_all_previous_generation_guards():
    from novel_forge.storage.migrations.versions import v20261018_0223_working_plan_input_continuation as recovery
    assert recovery.GUARD_STATEMENT.replace(
        "\n               AND NOT authority_working_plan_input_continuation_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))", ""
    ) == recovery.PREVIOUS_GUARD
    assert "effect.provider='production_execution_gateway'" in recovery.PERMITTED
    assert "routing_decision,selected,candidate,provider}'=r.target_runtime->>'model_provider'" in recovery.PERMITTED
    assert "NOT r.decision_evidence ? 'pack_version_successor'" in recovery.PERMITTED
    assert "NOT r.decision_evidence ? 'capacity_policy_upgrade'" in recovery.PERMITTED

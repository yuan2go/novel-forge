from novel_forge.storage.migrations.versions import (
    v20260814_0091_canonical_longform_runtime_completion as previous,
)
from novel_forge.storage.migrations.versions import (
    v20260814_0092_longform_correctness_closure as migration,
)


def test_longform_correctness_closure_is_one_forward_authority_migration() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    assert migration.DOWN_REVISION == previous.MIGRATION_ID
    assert migration.FORWARD_ONLY is True
    assert "arc_portfolio_plan_versions" in sql
    assert "current_relevant_arc_plan_versions" in sql
    assert "arc_projection_subset_check" in sql
    assert "active_arc_plan_versions=current_relevant_arc_plan_versions" in sql
    assert "authority_validate_book_arc_projection" in sql
    assert "'ARC_RELATION'" in sql
    assert "DISABLE TRIGGER authority_book_production_input_snapshot_immutable" in sql
    assert "DISABLE TRIGGER authority_book_production_input_snapshot_scope_guard" in sql
    assert "ENABLE TRIGGER authority_book_production_input_snapshot_scope_guard" in sql
    assert "volume_portfolio_plan_versions=COALESCE" in sql
    assert "snapshot.active_arc_plan_versions" in sql
    assert "active_story_plan_version AS active" not in sql.split(
        "volume_portfolio_plan_versions=COALESCE", 1
    )[1].split("WHERE snapshot.volume_portfolio_plan_versions", 1)[0]
    assert "jsonb_array_length(volume_portfolio_plan_versions)>0" in sql
    assert "BEFORE INSERT OR UPDATE ON authority_book_production_input_snapshot" in sql
    assert "EXCEPT" in sql
    assert "'arc_plan_versions'" in sql
    assert "NOT longform_context_versions ? 'arc_plan_version'" in sql
    assert "provider_model_call_asset_version_id" in sql
    assert "provider_result_hash" in sql
    assert "evaluator_execution_class <> 'MODEL_PROVIDER'" in sql
    assert "^sha256:[0-9a-f]{64}$" in sql
    assert "authority_validate_narrative_provider_lineage" in sql
    assert "authority_narrative_evaluation_candidate_once_idx" in sql
    assert "authority_sha256_jsonb(model_call_content->'provider_evidence')" in sql
    assert "REMOTE_PROVIDER_API" in sql
    assert "SET trust_boundary='LEGACY_COUPLED'" in sql
    assert "receipt.value->'evidence'=NEW.evaluation" in sql
    assert "evaluation_asset_content#>'{evaluation}'" in sql
    assert "narrative_load_policy_lineage" in sql
    assert "content->'narrative_load_budget'" not in sql

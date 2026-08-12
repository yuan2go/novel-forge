from __future__ import annotations

from novel_forge.storage.migrations.versions import (
    v20260812_0084_development_gap_final_convergence as migration,
)


def test_migration_converges_projections_without_new_execution_authority() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    assert migration.MIGRATION_ID == "20260812_0084_development_gap_final_convergence"
    assert migration.DOWN_REVISION == "20260812_0083_narrative_runtime_convergence"
    assert migration.FORWARD_ONLY is True
    assert "CREATE TABLE authority_book_replan_reevaluation" in sql
    assert "CREATE TABLE authority_operation" not in sql
    assert "CREATE TABLE authority_attempt" not in sql
    assert "authority_mkaos_runtime_selection_projection" in sql
    assert "authority_mkaos_runtime_usage_projection" in sql
    assert "authority_corrective_action_lineage_projection" in sql
    assert (
        "authority_runtime_job(project_id, runtime_group, job_kind, dedupe_key)"
        in sql
    )
    assert (
        "project_id, runtime_group, job_kind, subject_kind, subject_id" in sql
    )


def test_consumption_requires_successful_provider_effect_and_attempt_identity() -> None:
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    assert "effect.effect_type='model.invoke'" in sql
    assert "effect.status='SUCCEEDED'" in sql
    assert "effect.request_payload->'_production_execution'->>'attempt_id'" in sql
    assert "authority_attempt_capability_pack_snapshot" in sql
    assert "result.asset_version_id" in sql

import json
import pytest

from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import DATABASE_URL
from tests.integration import test_synthesis_formation_postgres as formation
from tests.integration.quality_context_routed_support import (
    attach_mock_qualified_router,
    bind_mock_scenario,
    SCENARIOS,
)


@pytest.mark.parametrize("scenario_name", list(SCENARIOS))
def test_formal_author_formation_acceptance_next_unit_with_router(
    tmp_path, monkeypatch, scenario_name
):
    scenario = SCENARIOS[scenario_name]
    expected_guidance = bind_mock_scenario(monkeypatch, scenario)
    build = formation.build_production_execution_composition
    routers = []

    def routed(*args, **kwargs):
        execution = build(*args, **kwargs)
        routers.append(attach_mock_qualified_router(execution, DATABASE_URL))
        return execution

    monkeypatch.setattr(formation, "build_production_execution_composition", routed)
    formation.test_native_formation_generates_foundation_from_author_brief(
        tmp_path,
        monkeypatch,
        True,
        False,
        False,
        False,
        False,
        scenario_name == "observation",
        3,
    )
    artifact = json.loads((tmp_path / "formation-production.json").read_text())
    project = artifact["formation"]["project_id"]
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """SELECT e.external_effect_id,e.request_payload->>'stage',
            e.request_payload #> '{_production_execution,capability_runtime,routing_decision}', e.status
            FROM authority_external_effect e WHERE e.project_id=%s""",
            [project],
        )
        rows = uow.cursor.fetchall()
    routed_rows = [row for row in rows if row[2]]
    assert routed_rows
    stages = {row[1] for row in routed_rows}
    assert {"draft", "review", "revision", "rereview", "quality_structural"} <= stages
    assert all(row[2]["status"] == "SELECTED" for row in routed_rows)
    assert all(row[2]["task"]["producer_contract_hash"] for row in routed_rows)
    propagation = []
    for workspace in artifact["workspaces"]["workspaces"]:
        best = next(
            row
            for row in workspace["artifacts"]["candidates"]
            if row["asset_type"] == "best_draft_candidate"
        )
        baseline = best["content"]["creative_baseline"]
        assert expected_guidance in [
            item["text"] for item in baseline["author_guidance"]["fragments"]
        ]
        facts = baseline["style"]["policies"][0]["structured_facts"]
        profile = next(
            item["value"] for item in facts if item.get("key") == "creative_style"
        )
        assert (
            profile["narrator"] == scenario["tone"]
            and profile["pov"] == scenario["pov"]
        )
        direction = next(
            item["value"] for item in facts if item.get("key") == "creative_direction"
        )
        assert (
            direction["genre"] == scenario["genre"]
            and direction["target_reader"] == scenario["audience"]
        )
        assert baseline["method_requirements"]["reward"]["status"] == "NOT_APPLICABLE"
        assert (
            baseline["method_requirements"]["chapter_hook"]["status"]
            == "NOT_APPLICABLE"
        )
        propagation.append(
            {
                "accepted": workspace["acceptance"],
                "baseline": baseline,
                "candidate": best["asset_version_id"],
            }
        )
    (tmp_path / "mock-router-evidence.json").write_text(
        json.dumps(
            {
                "evidence_class": "MOCK_E2E",
                "qualification_source": "CONTROLLED_TEST_OBSERVATIONS_NOT_PERSISTED",
                "real_provider_validated": False,
                "effects": rows,
                "scenario": scenario,
                "propagation": propagation,
            },
            default=str,
            indent=2,
        )
    )


def test_native_overflow_compression_fidelity_draft_review_and_frozen_resume():
    from tests.integration.test_chapter_model_effects_postgres import (
        ChapterModelEffectsPostgresTests,
    )

    case = ChapterModelEffectsPostgresTests()
    case.test_context_semantic_subeffects_use_frozen_pack_and_durable_kernel_replay(
        routed=True
    )


@pytest.mark.parametrize("failure", ["schema_result", "evaluation_retry"])
def test_formal_author_recovery_retains_failed_history_and_frozen_inputs(
    tmp_path, monkeypatch, failure
):
    bind_mock_scenario(monkeypatch, SCENARIOS["observation"])
    build = formation.build_production_execution_composition

    def routed(*args, **kwargs):
        execution = build(*args, **kwargs)
        attach_mock_qualified_router(execution, DATABASE_URL)
        return execution

    monkeypatch.setattr(formation, "build_production_execution_composition", routed)
    formation.test_native_formation_generates_foundation_from_author_brief(
        tmp_path,
        monkeypatch,
        True,
        failure == "schema_result",
        False,
        failure == "evaluation_retry",
        False,
        False,
        1,
        complete_after_result_repair=True,
    )
    artifact = json.loads((tmp_path / "formation-production.json").read_text())
    assert len(artifact["workspaces"]["workspaces"]) == 1
    (tmp_path / "mock-recovery-scope.json").write_text(
        json.dumps(
            {
                "evidence_class": "MOCK_E2E",
                "failure": failure,
                "real_provider_validated": False,
                "checks": "Original formal Formation recovery assertions include exact failed source, frozen input lineage and bounded replacement history",
            },
            indent=2,
        )
    )

import json

from novel_forge.modules.production_execution.provider_admission import (
    build_route_token_accounting_contract,
)
from novel_forge.modules.source_import.analysis_profiles import (
    derive_corpus_sample_byte_limit,
)
from novel_forge.modules.source_import.classical_corpus import load_corpus_registry
from scripts.run_classical_corpus_analysis import (
    _application_call_delta,
    _build_budget_plan,
    _load_native_report,
)


def test_analysis_call_delta_is_preserved_for_blocked_reports() -> None:
    assert _application_call_delta(
        {"application_effect_count": 81}, {"application_effect_count": 85}
    ) == 4


def test_frozen_corpus_analysis_budget_fits_approved_source_envelope() -> None:
    registry = load_corpus_registry()
    plan = _build_budget_plan(
        registry,
        selected_work_keys=(
            "chinese-novel.sanguoyanyi",
            "chinese-poetry.shijing",
        ),
        model_context_limit=160_000,
        output_token_reserve=4_096,
        token_safety_margin=16_384,
        token_framing_overhead=16,
    )

    assert plan["normal_application_calls"] == 166
    assert plan["repair_application_call_reserve"] == 14
    assert plan["maximum_application_calls"] == 180
    assert plan["selected_normal_application_calls"] == 17
    assert plan["project_token_limit"] == 28_800_000
    assert plan["source_sample_byte_limit"] == 107_504
    assert len(plan["works"]) == 20


def test_scripted_route_uses_its_effective_context_for_corpus_sampling() -> None:
    contract = build_route_token_accounting_contract(
        provider="scripted_provider_v2",
        model="scripted-fixture-v2",
        route_identity="route:scripted:source",
        accounting_method="",
        accounting_evidence_ref="",
        model_context_limit=0,
        output_reserve=4_096,
        safety_margin=256,
        framing_overhead=16,
    )

    assert contract.model_context_limit == 262_144
    assert derive_corpus_sample_byte_limit(
        model_context_limit=contract.model_context_limit,
        output_token_reserve=contract.output_reserve,
        token_safety_margin=contract.safety_margin,
        token_framing_overhead=contract.framing_overhead,
    ) == 225_776


def test_analysis_runner_accepts_only_matching_complete_native_report(tmp_path) -> None:
    registry = load_corpus_registry()
    path = tmp_path / "native-import.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "classical-corpus-native-import-run.v1",
                "project_id": "project:corpus",
                "workspace_id": "workspace:corpus",
                "materialized_work_count": 20,
                "failed_work_count": 0,
                "run_hash": "sha256:" + "a" * 64,
                "works": [
                    {
                        "work_key": item["work_key"],
                        "import_job_id": f"job:{index}",
                    }
                    for index, item in enumerate(registry["works"], start=1)
                ],
            }
        ),
        encoding="utf-8",
    )

    report, works = _load_native_report(
        path,
        project_id="project:corpus",
        workspace_id="workspace:corpus",
    )

    assert report["failed_work_count"] == 0
    assert len(works) == 20

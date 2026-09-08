import json

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

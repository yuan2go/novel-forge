from __future__ import annotations

import json
from pathlib import Path
from statistics import mean
from typing import Any

from novel_forge.core.constants import DATA_DIRS
from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.common import resolve_path
from novel_forge.modules.os_envelope import enforce_os_envelope, envelope_asset_metadata, is_production_environment
from novel_forge.modules.review_issue import persist_issue_candidates
from novel_forge.modules.runtime_ledger import record_gate_result
from novel_forge.schemas import (
    EvaluationGate,
    Golden10Report,
    HumanAnnotation,
    Longform100Report,
    ModelJudgeResult,
    Opening3Report,
    ProjectMetricSnapshot,
    QualityRegressionReport,
    QualityRubricPack,
    RevisionTask,
    Volume30Report,
    validate_common_fields,
)
from novel_forge.storage.local import LocalStorage


QUALITY_SUITE_REPORTS = {
    "opening_3": Opening3Report,
    "golden_10": Golden10Report,
    "volume_30": Volume30Report,
    "longform_100": Longform100Report,
}

DEFAULT_DIMENSIONS = [
    "genre_promise",
    "platform_rhythm",
    "style_adherence",
    "hook_strength",
    "conflict_density",
    "character_motivation",
    "canon_consistency",
    "ai_flavor_risk",
]

QUALITY_CALIBRATION_READINESS_GATE_KIND = "quality_calibration_readiness_gate"
QUALITY_CALIBRATION_READINESS_GATE_CONTRACT = "quality-calibration-readiness-gate-v1"


def build_quality_rubric_pack(
    storage: LocalStorage,
    *,
    genre_id: str = "",
    platform_id: str = "local",
    style_profile_path: str = "",
    scope: str = "chapter",
    environment: str = "",
    envelope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    envelope_payload = dict(envelope or {})
    if envelope_payload:
        envelope_payload.update(
            {
                "operation": "build-quality-rubric-pack",
                "task_type": "quality_eval",
                "asset_type": "quality_rubric_pack",
            }
        )
    env = enforce_os_envelope(
        storage,
        envelope_payload=envelope_payload or None,
        operation="build-quality-rubric-pack",
        project_id=str((envelope or {}).get("project_id") or ""),
        task_type="quality_eval",
        asset_type="quality_rubric_pack",
        source_policy={"raw_source_text_allowed": False, "generation_rag_allowed": True},
        environment=environment,
        require_for_production=True,
    )
    if is_production_environment(env.get("environment")) and not (genre_id and platform_id):
        raise ValueError("genre_id and platform_id are required for production quality rubric packs")
    dimensions = DEFAULT_DIMENSIONS
    weights = {
        "genre_promise": 0.18,
        "platform_rhythm": 0.12,
        "style_adherence": 0.14,
        "hook_strength": 0.16,
        "conflict_density": 0.12,
        "character_motivation": 0.12,
        "canon_consistency": 0.1,
        "ai_flavor_risk": 0.06,
    }
    asset = QualityRubricPack(
        title=f"{platform_id} {genre_id or 'general'} {scope} rubric",
        tags=["quality-eval-v2", "rubric", platform_id, genre_id or "general"],
        content={
            "rubric_id": make_id("quality_rubric_pack", f"{platform_id}-{genre_id}-{scope}"),
            "rubric_version": "v1",
            "platform_id": platform_id,
            "genre_id": genre_id or "general",
            "scope": scope,
            "dimensions": dimensions,
            "weights": weights,
            "thresholds": {"ready": 80, "needs_revision": 65, "blocked": 50},
            "judge_policy": {
                "mode": "local_heuristic_fallback",
                "does_not_claim_premium_judgment": True,
                "provider_judge_required_for_production_release": True,
                "threshold_source": "default",
                "calibration_required_for_production_acceptance": False,
            },
            "calibration_ref": "",
            "style_profile_path": style_profile_path,
        },
        metadata={
            "project_id": str(env.get("project_id") or ""),
            "platform_id": platform_id,
            "genre_id": genre_id,
            **envelope_asset_metadata(env),
        },
        references=[style_profile_path] if style_profile_path else [],
    )
    path = _write_asset(storage, asset)
    return {"path": path, "asset": storage.read_json(resolve_path(storage.root, path)), "envelope": env}


def run_quality_suite(
    storage: LocalStorage,
    *,
    suite_type: str,
    target_paths: list[str | Path],
    rubric_path: str | Path = "",
    genre_strategy_pack_path: str = "",
    style_profile_path: str = "",
    platform_id: str = "local",
    environment: str = "",
    envelope: dict[str, Any] | None = None,
    persist_issues: bool = True,
) -> dict[str, Any]:
    if suite_type not in QUALITY_SUITE_REPORTS:
        raise ValueError(f"unsupported quality suite type: {suite_type}")
    if not target_paths:
        raise ValueError("target_paths is required")
    if is_production_environment(environment or (envelope or {}).get("environment")) and not rubric_path:
        raise ValueError("rubric_path is required for production quality suite")
    rubric = _load_rubric(storage, rubric_path)
    env = enforce_os_envelope(
        storage,
        envelope_payload=envelope,
        operation="run-quality-suite",
        project_id=str(rubric.get("metadata", {}).get("project_id") or (envelope or {}).get("project_id") or ""),
        task_type=suite_type,
        asset_type=QUALITY_SUITE_REPORTS[suite_type]().type,
        source_policy={"raw_source_text_allowed": False, "generation_rag_allowed": False},
        environment=environment,
        require_for_production=True,
    )
    target_assets = [_load_target(storage, path) for path in target_paths]
    scores = [_score_target(row["asset"], rubric.get("content", {})) for row in target_assets]
    overall = round(mean([score["overall"] for score in scores]), 2)
    recommendation = _recommendation(overall, rubric.get("content", {}))
    issue_paths: list[str] = []
    if persist_issues and recommendation != "ready":
        issue_summary = persist_issue_candidates(
            storage,
            _quality_issue_candidates(target_assets, scores, recommendation, rubric, project_id=str(env.get("project_id") or "")),
            source_system="quality_eval.v2",
        )
        issue_paths = [str(path) for path in issue_summary.get("issue_paths", [])]
    report_cls = QUALITY_SUITE_REPORTS[suite_type]
    report = report_cls(
        title=f"{suite_type} quality report",
        source=",".join(row["asset"].get("id", "") for row in target_assets),
        tags=["quality-eval-v2", suite_type, recommendation, "local-heuristic"],
        content={
            "report_id": make_id(report_cls().type, suite_type),
            "suite_id": suite_type,
            "target_asset_ids": [row["asset"].get("id", "") for row in target_assets],
            "overall_score": overall,
            "scores": scores,
            "recommendation": recommendation,
            "review_issue_paths": issue_paths,
            "rubric_path": str(rubric_path),
            "genre_strategy_pack_path": genre_strategy_pack_path,
            "style_profile_path": style_profile_path,
            "platform_id": platform_id,
            "judge_policy": {"mode": "local_heuristic_fallback", "does_not_claim_premium_judgment": True},
        },
        metadata={"project_id": str(env.get("project_id") or ""), "suite_type": suite_type, **envelope_asset_metadata(env)},
        references=_dedupe([str(rubric_path), genre_strategy_pack_path, style_profile_path, *[row["path"] for row in target_assets], *issue_paths]),
    )
    report_path = _write_asset(storage, report)
    revision_task_path = ""
    if recommendation != "ready":
        revision_task_path = _write_revision_task(storage, report_path=report_path, target_paths=[row["path"] for row in target_assets], scores=scores, recommendation=recommendation, project_id=str(env.get("project_id") or ""))
        data = storage.read_json(resolve_path(storage.root, report_path))
        data["content"]["revision_task_path"] = revision_task_path
        storage.write_json(resolve_path(storage.root, report_path), data)
    return {
        "path": report_path,
        "asset": storage.read_json(resolve_path(storage.root, report_path)),
        "review_issues": issue_paths,
        "revision_task_path": revision_task_path,
        "envelope": env,
    }


def run_provider_quality_judge(
    storage: LocalStorage,
    *,
    suite_type: str,
    target_paths: list[str | Path],
    rubric_path: str | Path,
    adapter: Any | None = None,
    genre_strategy_pack_path: str = "",
    style_profile_path: str = "",
    platform_id: str = "local",
    environment: str = "",
    envelope: dict[str, Any] | None = None,
    provider_runtime_guard: dict[str, Any] | None = None,
    allow_mock_fixture: bool = False,
    require_external_provider_proof: bool = False,
    require_calibrated_thresholds: bool = False,
    persist_issues: bool = True,
) -> dict[str, Any]:
    from novel_forge.modules.model_router import call_model_via_router, record_external_provider_proof

    if suite_type not in QUALITY_SUITE_REPORTS:
        raise ValueError(f"unsupported quality suite type: {suite_type}")
    if not target_paths:
        raise ValueError("target_paths is required")
    if not rubric_path:
        raise ValueError("rubric_path is required for provider quality judge")
    production = is_production_environment(environment or (envelope or {}).get("environment"))
    if production and adapter is None:
        raise ValueError("provider quality judge requires a provider adapter in production")
    if adapter is None:
        raise ValueError("provider quality judge requires an adapter")
    rubric = _load_rubric(storage, rubric_path)
    rubric_content = rubric.get("content", {}) if isinstance(rubric.get("content", {}), dict) else {}
    calibration_ref = str(rubric_content.get("calibration_ref") or "")
    if production and require_calibrated_thresholds:
        if not calibration_ref:
            raise ValueError("production provider quality judge requires a human-calibrated rubric")
        calibration = storage.read_json(resolve_path(storage.root, calibration_ref))
        calibration_content = calibration.get("content", {}) if isinstance(calibration.get("content", {}), dict) else {}
        if calibration.get("type") != "evaluation_regression_report" or calibration_content.get("calibration_status") != "passed":
            raise ValueError("rubric calibration_ref must point to a passed provider calibration report")
        human_calibration = calibration_content.get("human_calibration", {}) if isinstance(calibration_content.get("human_calibration", {}), dict) else {}
        if not human_calibration.get("production_ready"):
            raise ValueError("provider acceptance requires multi-case, multi-annotator human calibration")
    env = enforce_os_envelope(
        storage,
        envelope_payload=envelope,
        operation="run-provider-quality-judge",
        project_id=str(rubric.get("metadata", {}).get("project_id") or (envelope or {}).get("project_id") or ""),
        task_type="quality_judge",
        asset_type=QUALITY_SUITE_REPORTS[suite_type]().type,
        source_policy={"raw_source_text_allowed": False, "generation_rag_allowed": False},
        environment=environment,
        require_for_production=True,
    )
    target_assets = [_load_target(storage, path) for path in target_paths]
    prompt_payload = _provider_judge_payload(rubric=rubric, targets=target_assets, suite_type=suite_type, platform_id=platform_id)
    routed = call_model_via_router(
        storage,
        adapter=adapter,
        operation="review",
        payload=json.dumps(prompt_payload, ensure_ascii=False, sort_keys=True),
        context={"environment": env.get("environment"), "quality_suite": suite_type, "source_policy": env.get("source_policy", {})},
        task_type="quality_judge",
        project_id=str(env.get("project_id") or ""),
        input_assets=_dedupe([str(rubric_path), *[row["path"] for row in target_assets], genre_strategy_pack_path, style_profile_path]),
        prompt_id="quality-eval-v2-provider-judge",
        prompt_version="v7",
        trace={"trace_id": str(env.get("trace_id") or "")},
        environment=str(env.get("environment") or environment or ""),
        allow_mock_fixture=allow_mock_fixture,
        provider_runtime_guard=provider_runtime_guard or {},
    )
    judge_payload = _parse_provider_judge_response(routed)
    dimension_scores = _normalized_provider_scores(judge_payload.get("scores", {}))
    overall = _weighted_overall(dimension_scores, rubric.get("content", {}))
    recommendation = str(judge_payload.get("recommendation") or _recommendation(overall, rubric.get("content", {})))
    if recommendation not in {"ready", "needs_revision", "blocked"}:
        recommendation = _recommendation(overall, rubric.get("content", {}))
    provider_evidence = _provider_evidence_from_routed(routed)
    external_proof = (
        record_external_provider_proof(
            storage,
            proof_type=f"quality_judge:{suite_type}",
            routed_result=routed,
            adapter=adapter,
            project_id=str(env.get("project_id") or ""),
            environment=str(env.get("environment") or environment or ""),
            target_refs=_dedupe([str(rubric_path), *[row["path"] for row in target_assets]]),
            strict=require_external_provider_proof,
        )
        if require_external_provider_proof
        else {"status": "not_required", "path": "", "blocking": False}
    )
    provider_evidence["external_provider_proof"] = external_proof
    provider_judge_run_report = _provider_judge_run_report(
        suite_type=suite_type,
        provider_evidence=provider_evidence,
        external_proof=external_proof,
        require_external_provider_proof=require_external_provider_proof,
        recommendation=recommendation,
        overall=overall,
    )
    threshold_calibration_status = "calibrated" if calibration_ref else "uncalibrated"
    issue_paths: list[str] = []
    scores = [
        {
            "target_asset_id": row["asset"].get("id", ""),
            "target_asset_type": row["asset"].get("type", ""),
            "dimension_scores": dimension_scores,
            "overall": overall,
            "judge_source": "provider_backed",
        }
        for row in target_assets
    ]
    if persist_issues and recommendation != "ready":
        issue_summary = persist_issue_candidates(
            storage,
            _quality_issue_candidates(target_assets, scores, recommendation, rubric, project_id=str(env.get("project_id") or "")),
            source_system="quality_eval.provider_judge",
        )
        issue_paths = [str(path) for path in issue_summary.get("issue_paths", [])]
    judge_paths: list[str] = []
    for row, score in zip(target_assets, scores):
        judge = ModelJudgeResult(
            title=f"Provider judge result for {row['asset'].get('id', '')}",
            source=row["asset"].get("id", ""),
            tags=["quality-eval-v2", "model-judge", "provider-backed", recommendation],
            content={
                "judge_id": make_id("model_judge_result", f"{row['asset'].get('id', '')}-{suite_type}"),
                "target_asset_id": row["asset"].get("id", ""),
                "rubric_id": str(rubric.get("content", {}).get("rubric_id") or ""),
                "scores": score,
                "recommendation": recommendation,
                "provider_evidence": provider_evidence,
                "rationale": str(judge_payload.get("rationale") or judge_payload.get("reason") or ""),
            },
            metadata={"project_id": str(env.get("project_id") or ""), **envelope_asset_metadata(env)},
            references=_dedupe([row["path"], str(rubric_path), provider_evidence.get("model_route_resolution_path", ""), provider_evidence.get("model_call_log_path", ""), provider_evidence.get("runtime_policy_path", ""), provider_evidence.get("cost_ledger_path", "")]),
        )
        judge_paths.append(_write_asset(storage, judge))
    report_cls = QUALITY_SUITE_REPORTS[suite_type]
    report = report_cls(
        title=f"{suite_type} provider quality report",
        source=",".join(row["asset"].get("id", "") for row in target_assets),
        tags=["quality-eval-v2", suite_type, recommendation, "provider-backed"],
        content={
            "report_id": make_id(report_cls().type, f"provider-{suite_type}"),
            "suite_id": suite_type,
            "target_asset_ids": [row["asset"].get("id", "") for row in target_assets],
            "overall_score": overall,
            "scores": scores,
            "recommendation": recommendation,
            "review_issue_paths": issue_paths,
            "rubric_path": str(rubric_path),
            "genre_strategy_pack_path": genre_strategy_pack_path,
            "style_profile_path": style_profile_path,
            "platform_id": platform_id,
            "model_judge_result_paths": judge_paths,
            "provider_runtime_evidence": provider_evidence,
            "provider_judge_run_report": provider_judge_run_report,
            "threshold_calibration": {
                "status": threshold_calibration_status,
                "rubric_version": rubric_content.get("rubric_version", "v1"),
                "calibration_ref": calibration_ref,
                "threshold_source": (rubric_content.get("judge_policy", {}) or {}).get("threshold_source", "default") if isinstance(rubric_content.get("judge_policy", {}), dict) else "default",
                "thresholds": rubric_content.get("thresholds", {}),
            },
            "judge_policy": {
                "mode": "provider_backed_judge",
                "does_not_claim_premium_judgment": not bool(rubric.get("content", {}).get("calibration_ref")),
                "provider_runtime_evidence_required": True,
                "external_provider_proof_required": bool(require_external_provider_proof),
                "provider_judge_required_for_production_release": True,
                "threshold_calibration_required_for_production_acceptance": bool(is_production_environment(env.get("environment"))),
            },
        },
        metadata={"project_id": str(env.get("project_id") or ""), "suite_type": suite_type, **envelope_asset_metadata(env)},
        references=_dedupe([str(rubric_path), genre_strategy_pack_path, style_profile_path, *[row["path"] for row in target_assets], *issue_paths, *judge_paths, str(external_proof.get("path", ""))]),
    )
    report_path = _write_asset(storage, report)
    revision_task_path = ""
    if recommendation != "ready":
        revision_task_path = _write_revision_task(storage, report_path=report_path, target_paths=[row["path"] for row in target_assets], scores=scores, recommendation=recommendation, project_id=str(env.get("project_id") or ""))
        data = storage.read_json(resolve_path(storage.root, report_path))
        data["content"]["revision_task_path"] = revision_task_path
        storage.write_json(resolve_path(storage.root, report_path), data)
    return {
        "path": report_path,
        "asset": storage.read_json(resolve_path(storage.root, report_path)),
        "model_judge_result_paths": judge_paths,
        "review_issues": issue_paths,
        "revision_task_path": revision_task_path,
        "provider_evidence": provider_evidence,
        "external_provider_proof": external_proof,
        "envelope": env,
    }


def run_quality_gate(
    storage: LocalStorage,
    *,
    quality_report_path: str | Path,
    environment: str = "",
    envelope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    report_file = resolve_path(storage.root, quality_report_path)
    report = storage.read_json(report_file)
    content = report.get("content", {}) if isinstance(report.get("content"), dict) else {}
    env = enforce_os_envelope(
        storage,
        envelope_payload=envelope,
        operation="run-quality-gate",
        project_id=str(report.get("metadata", {}).get("project_id") or ""),
        task_type="quality_gate",
        asset_type="evaluation_gate",
        source_policy={"raw_source_text_allowed": False, "generation_rag_allowed": False},
        environment=environment,
        require_for_production=True,
    )
    recommendation = str(content.get("recommendation") or "blocked")
    judge_policy = content.get("judge_policy", {}) if isinstance(content.get("judge_policy", {}), dict) else {}
    provider_judge_present = str(judge_policy.get("mode") or "") == "provider_backed_judge" and bool(content.get("model_judge_result_paths"))
    provider_judge_required = is_production_environment(env.get("environment"))
    provider_missing = provider_judge_required and not provider_judge_present
    status = "passed" if recommendation == "ready" and not provider_missing else "blocked"
    gate = EvaluationGate(
        title=f"Quality gate for {report.get('id')}",
        source=str(report.get("id") or ""),
        tags=["quality-eval-v2", "evaluation-gate", status],
        content={
            "gate_id": make_id("evaluation_gate", str(report.get("id") or "")),
            "target_asset_id": ",".join(str(item) for item in content.get("target_asset_ids", [])),
            "status": status,
            "blocking": status != "passed",
            "created_at": utc_now(),
            "quality_report_path": _display_path(storage.root, report_file),
            "recommendation": recommendation,
            "review_issue_paths": content.get("review_issue_paths", []),
            "provider_judge_required": provider_judge_required,
            "provider_judge_evidence_present": provider_judge_present,
            "provider_runtime_evidence": content.get("provider_runtime_evidence", {}) if isinstance(content.get("provider_runtime_evidence", {}), dict) else {},
            "blocking_reasons": ["provider-backed quality judge evidence is required in production"] if provider_missing else ([] if status == "passed" else ["quality recommendation is not ready"]),
        },
        metadata={"project_id": str(report.get("metadata", {}).get("project_id") or ""), **envelope_asset_metadata(env)},
        references=[_display_path(storage.root, report_file), *[str(item) for item in content.get("review_issue_paths", [])], *[str(item) for item in content.get("model_judge_result_paths", [])]],
    )
    path = _write_asset(storage, gate)
    return {"path": path, "asset": storage.read_json(resolve_path(storage.root, path)), "envelope": env}


def create_model_judge_result(
    storage: LocalStorage,
    *,
    target_asset_id: str,
    rubric_id: str,
    scores: dict[str, Any],
    recommendation: str,
    provider_evidence: dict[str, Any],
) -> dict[str, Any]:
    asset = ModelJudgeResult(
        title=f"Model judge result for {target_asset_id}",
        tags=["quality-eval-v2", "model-judge"],
        content={
            "judge_id": make_id("model_judge_result", target_asset_id),
            "target_asset_id": target_asset_id,
            "rubric_id": rubric_id,
            "scores": scores,
            "recommendation": recommendation,
            "provider_evidence": provider_evidence,
        },
    )
    path = _write_asset(storage, asset)
    return {"path": path, "asset": storage.read_json(resolve_path(storage.root, path))}


def create_human_annotation(
    storage: LocalStorage,
    *,
    target_asset_id: str,
    rubric_id: str,
    scores: dict[str, Any],
    annotator: str,
    recommendation: str,
) -> dict[str, Any]:
    asset = HumanAnnotation(
        title=f"Human annotation for {target_asset_id}",
        tags=["quality-eval-v2", "human-annotation"],
        content={
            "annotation_id": make_id("human_annotation", target_asset_id),
            "target_asset_id": target_asset_id,
            "rubric_id": rubric_id,
            "scores": scores,
            "annotator": annotator,
            "recommendation": recommendation,
        },
    )
    path = _write_asset(storage, asset)
    return {"path": path, "asset": storage.read_json(resolve_path(storage.root, path))}


def create_quality_regression_report(storage: LocalStorage, *, baseline_score: float, candidate_score: float, case_count: int) -> dict[str, Any]:
    passed = candidate_score >= baseline_score - 2
    asset = QualityRegressionReport(
        title="Quality regression report",
        tags=["quality-eval-v2", "regression", "passed" if passed else "failed"],
        content={
            "suite_id": "quality_regression",
            "case_count": case_count,
            "passed_count": case_count if passed else max(0, case_count - 1),
            "failed_count": 0 if passed else 1,
            "score_delta": round(candidate_score - baseline_score, 2),
            "blocked_assets": [] if passed else ["candidate"],
            "recommendation": "passed" if passed else "blocked",
        },
    )
    path = _write_asset(storage, asset)
    return {"path": path, "asset": storage.read_json(resolve_path(storage.root, path))}


def build_quality_calibration_readiness_report(
    storage: LocalStorage,
    *,
    project_id: str = "",
    limit: int = 1000,
    persist: bool = True,
) -> dict[str, Any]:
    """Summarize provider/human quality calibration evidence without calling providers.

    The report intentionally separates route-approved fixture/provider results from
    strict external-provider proof. It is readiness evidence for operators and the
    final unified acceptance preflight, not a premium quality judgment by itself.
    """

    storage.ensure_layout()
    rows = _quality_calibration_rows(storage, project_id=project_id, limit=max(1, int(limit or 1000)))
    by_type = _rows_by_type(rows)
    model_judges = by_type.get("model_judge_result", [])
    classified_judges = [_classify_model_judge(row) for row in model_judges]
    external_judges = [row for row in classified_judges if row["classification"] == "external_provider"]
    route_approved_judges = [row for row in classified_judges if row["classification"] == "provider_route_approved"]
    fixture_judges = [row for row in classified_judges if row["classification"] == "fixture_or_mock"]
    human_annotations = by_type.get("human_annotation", [])
    rubric_packs = by_type.get("quality_rubric_pack", [])
    suite_reports = [row for row in rows if row.get("type") in {"opening_3_report", "golden_10_report", "volume_30_report", "longform_100_report"}]
    golden_sets = [row for row in by_type.get("evaluation_suite", []) if _is_golden_set(row)]
    calibration_reports = [row for row in by_type.get("evaluation_regression_report", []) if _is_provider_calibration_report(row)]
    passed_calibration_reports = [row for row in calibration_reports if _calibration_status(row) == "passed"]
    failed_calibration_reports = [row for row in calibration_reports if _calibration_status(row) in {"needs_calibration", "failed", "blocked"}]

    dimensions = [
        _readiness_dimension("quality_rubric_pack", bool(rubric_packs), "build a quality rubric pack for the project"),
        _readiness_dimension("quality_suite_report", bool(suite_reports), "run at least one quality suite over owned/generated text"),
        _readiness_dimension("provider_judge_result", bool(model_judges), "record a provider judge result through the runtime guard"),
        _readiness_dimension("external_provider_judge_proof", bool(external_judges), "run a provider judge with external provider proof, not fixture/mock evidence"),
        _readiness_dimension("human_annotation", bool(human_annotations), "add human annotations for a calibration target"),
        _readiness_dimension("golden_set", bool(golden_sets), "build a golden set linked to human/expected scores"),
        _readiness_dimension("provider_judge_calibration", bool(passed_calibration_reports), "calibrate provider judge results against the golden set"),
    ]
    missing_dimensions = [row["dimension"] for row in dimensions if row["status"] == "missing"]
    if not rows:
        status = "missing"
    elif failed_calibration_reports and not passed_calibration_reports:
        status = "blocked"
    elif missing_dimensions:
        status = "review_required"
    else:
        status = "passed"
    evidence_paths = _dedupe([str(row.get("path") or "") for row in rows])
    summary = {
        "quality_rubric_pack_count": len(rubric_packs),
        "quality_suite_report_count": len(suite_reports),
        "model_judge_result_count": len(model_judges),
        "external_provider_judge_count": len(external_judges),
        "provider_route_approved_judge_count": len(route_approved_judges),
        "fixture_or_mock_provider_judge_count": len(fixture_judges),
        "human_annotation_count": len(human_annotations),
        "golden_set_count": len(golden_sets),
        "provider_calibration_report_count": len(calibration_reports),
        "passed_provider_calibration_count": len(passed_calibration_reports),
        "failed_provider_calibration_count": len(failed_calibration_reports),
        "missing_dimension_count": len(missing_dimensions),
        "missing_dimensions": missing_dimensions,
        "external_provider_proof_required_for_pass": True,
        "read_only": True,
    }
    content = {
        "snapshot_kind": "quality_calibration_readiness",
        "contract": "quality-calibration-readiness-v1",
        "status": status,
        "project_id": project_id,
        "snapshot_at": utc_now(),
        "throughput": {
            "asset_count": len(rows),
            "model_judge_result_count": len(model_judges),
            "human_annotation_count": len(human_annotations),
            "golden_set_count": len(golden_sets),
        },
        "quality": {
            "readiness_status": status,
            "external_provider_judge_count": len(external_judges),
            "human_annotation_count": len(human_annotations),
            "golden_set_count": len(golden_sets),
            "passed_provider_calibration_count": len(passed_calibration_reports),
            "missing_dimension_count": len(missing_dimensions),
            "fixture_or_mock_provider_judge_count": len(fixture_judges),
        },
        "task_health": {
            "review_required": status in {"missing", "review_required", "blocked"},
            "blocked_calibration_count": len(failed_calibration_reports),
            "provider_call_executed": False,
        },
        "agent_health": {
            "calibration_boundary": "read-only evidence scan; provider judge calls must use run_provider_quality_judge",
            "premium_judge_claim_allowed": status == "passed",
        },
        "storage_health": {
            "evidence_path_count": len(evidence_paths),
            "asset_types_scanned": sorted(by_type),
            "data_dirs_scanned": len(DATA_DIRS),
        },
        "recommendations": _quality_calibration_recommendations(status, summary),
        "summary": summary,
        "dimensions": dimensions,
        "model_judge_rows": classified_judges[:50],
        "human_annotation_rows": [_compact_quality_row(row) for row in human_annotations[:50]],
        "golden_set_rows": [_compact_quality_row(row) for row in golden_sets[:50]],
        "calibration_report_rows": [_compact_calibration_report(row) for row in calibration_reports[:50]],
        "evidence_paths": evidence_paths,
        "operator_action": _quality_calibration_operator_action(status, summary),
        "mutation_policy": "read-only: this report does not call providers, create annotations, approve assets, or change quality gates",
    }
    asset = ProjectMetricSnapshot(
        title=f"Quality calibration readiness {project_id or 'workspace'}",
        tags=["quality-eval-v2", "quality-calibration-readiness", status],
        content=content,
        metadata={"project_id": project_id, "snapshot_kind": "quality_calibration_readiness", "asset_status": status, "use_in_generation_rag": False},
        references=evidence_paths,
    )
    data = asset.to_dict()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    path = ""
    if persist:
        path = _display_path(storage.root, storage.write_asset_auto(asset))
        data = storage.read_json(resolve_path(storage.root, path))
    return {"status": status, "path": path, "asset": data, "summary": summary}


def run_quality_calibration_readiness_gate(
    storage: LocalStorage,
    *,
    project_id: str = "",
    environment: str = "",
    persist_readiness: bool = True,
    limit: int = 1000,
) -> dict[str, Any]:
    """Write a read-only hard-stop gate over quality calibration readiness evidence."""

    storage.ensure_layout()
    readiness = build_quality_calibration_readiness_report(
        storage,
        project_id=project_id,
        persist=persist_readiness,
        limit=limit,
    )
    readiness_asset = readiness.get("asset", {}) if isinstance(readiness.get("asset", {}), dict) else {}
    content = readiness_asset.get("content", {}) if isinstance(readiness_asset.get("content", {}), dict) else {}
    summary = content.get("summary", {}) if isinstance(content.get("summary", {}), dict) else {}
    dimensions = content.get("dimensions", []) if isinstance(content.get("dimensions", []), list) else []
    readiness_status = str(readiness.get("status") or content.get("status") or "missing")
    blockers = _quality_calibration_gate_blockers(readiness_status=readiness_status, summary=summary, dimensions=dimensions)
    production = is_production_environment(environment)
    status = "failed" if production and blockers else "warning" if blockers else "passed"
    message = (
        f"quality calibration readiness gate has {len(blockers)} blocking dimension(s)"
        if blockers
        else "quality calibration readiness gate passed"
    )
    readiness_path = str(readiness.get("path") or "")
    evidence_paths = _dedupe([readiness_path, *[str(path) for path in content.get("evidence_paths", []) if str(path or "").strip()]])
    gate_summary = {
        "readiness_status": readiness_status,
        "blocking_count": len(blockers),
        "missing_dimension_count": int(summary.get("missing_dimension_count") or 0),
        "external_provider_judge_count": int(summary.get("external_provider_judge_count") or 0),
        "fixture_or_mock_provider_judge_count": int(summary.get("fixture_or_mock_provider_judge_count") or 0),
        "human_annotation_count": int(summary.get("human_annotation_count") or 0),
        "golden_set_count": int(summary.get("golden_set_count") or 0),
        "passed_provider_calibration_count": int(summary.get("passed_provider_calibration_count") or 0),
        "failed_provider_calibration_count": int(summary.get("failed_provider_calibration_count") or 0),
        "production": production,
        "mutation_applied": False,
        "provider_call_executed": False,
        "chapter_acceptance_executed": False,
    }
    gate = record_gate_result(
        storage,
        gate_kind=QUALITY_CALIBRATION_READINESS_GATE_KIND,
        status=status,
        target_paths=evidence_paths,
        result={
            "contract": QUALITY_CALIBRATION_READINESS_GATE_CONTRACT,
            "project_id": project_id,
            "environment": environment,
            "summary": gate_summary,
            "readiness_report_path": readiness_path,
            "blocking_dimensions": blockers,
            "operator_action": _quality_calibration_gate_operator_action(status, production, blockers),
            "mutation_policy": "read-only: no provider call, annotation creation, calibration repair, chapter acceptance, or quality evidence mutation",
        },
        project_id=project_id,
        message=message,
        blocking=production and bool(blockers),
    )
    return {
        "status": status,
        "production": production,
        "blocking": production and bool(blockers),
        "message": message,
        "summary": gate_summary,
        "blocking_dimensions": blockers,
        "readiness_report": readiness,
        "readiness_report_path": readiness_path,
        "gate_result": gate,
        "gate_result_path": str(gate.get("path") or ""),
    }


def _load_rubric(storage: LocalStorage, rubric_path: str | Path) -> dict[str, Any]:
    if rubric_path:
        return storage.read_json(resolve_path(storage.root, rubric_path))
    return {
        "content": {
            "rubric_id": "local-default",
            "thresholds": {"ready": 80, "needs_revision": 65, "blocked": 50},
            "weights": {dimension: round(1 / len(DEFAULT_DIMENSIONS), 4) for dimension in DEFAULT_DIMENSIONS},
        },
        "metadata": {},
    }


def _load_target(storage: LocalStorage, path: str | Path) -> dict[str, Any]:
    resolved = resolve_path(storage.root, path)
    return {"path": _display_path(storage.root, resolved), "asset": storage.read_json(resolved)}


def _score_target(asset: dict[str, Any], rubric: dict[str, Any]) -> dict[str, Any]:
    text = _target_text(asset)
    scores = {
        "genre_promise": _text_score(text, ["目标", "承诺", "体系", "案件", "关系", "冲突"]),
        "platform_rhythm": _text_score(text, ["钩子", "转折", "下一章", "危险", "发现"]),
        "style_adherence": 82 - min(30, _count_markers(text, ["不禁", "与此同时", "仿佛凝固"]) * 8),
        "hook_strength": _text_score(text, ["然而", "突然", "真相", "代价", "不能回头"]),
        "conflict_density": _text_score(text, ["冲突", "阻碍", "敌人", "选择", "代价"]),
        "character_motivation": _text_score(text, ["想要", "必须", "害怕", "不甘", "决定"]),
        "canon_consistency": 88 - min(35, _count_markers(text, ["规则失效", "凭空出现", "无限能源"]) * 12),
        "ai_flavor_risk": 90 - min(45, _count_markers(text, ["不禁", "眸光", "空气仿佛", "一抹"]) * 10),
    }
    weights = rubric.get("weights", {}) if isinstance(rubric.get("weights"), dict) else {}
    if not weights:
        weights = {dimension: round(1 / len(scores), 4) for dimension in scores}
    overall = round(sum(float(scores[key]) * float(weights.get(key, 0)) for key in scores), 2)
    if overall <= 0:
        overall = round(mean(scores.values()), 2)
    return {"target_asset_id": asset.get("id", ""), "target_asset_type": asset.get("type", ""), "dimension_scores": scores, "overall": overall}


def _text_score(text: str, markers: list[str]) -> int:
    length_bonus = min(22, len(text) // 120)
    marker_bonus = min(24, _count_markers(text, markers) * 6)
    return min(95, 48 + length_bonus + marker_bonus)


def _count_markers(text: str, markers: list[str]) -> int:
    return sum(str(text).count(marker) for marker in markers)


def _target_text(asset: dict[str, Any]) -> str:
    content = asset.get("content", {}) if isinstance(asset.get("content"), dict) else {}
    for key in ["text", "draft_text", "chapter_text", "body", "summary"]:
        if content.get(key):
            return str(content.get(key))
    return " ".join(str(value) for value in content.values() if isinstance(value, (str, int, float)))


def _provider_judge_payload(*, rubric: dict[str, Any], targets: list[dict[str, Any]], suite_type: str, platform_id: str) -> dict[str, Any]:
    rubric_content = rubric.get("content", {}) if isinstance(rubric.get("content", {}), dict) else {}
    return {
        "task": "quality_eval_v2_provider_judge",
        "suite_type": suite_type,
        "platform_id": platform_id,
        "rubric": {
            "rubric_id": rubric_content.get("rubric_id", ""),
            "rubric_version": rubric_content.get("rubric_version", "v1"),
            "dimensions": rubric_content.get("dimensions", DEFAULT_DIMENSIONS),
            "weights": rubric_content.get("weights", {}),
            "thresholds": rubric_content.get("thresholds", {}),
            "calibration_ref": rubric_content.get("calibration_ref", ""),
            "threshold_source": (rubric_content.get("judge_policy", {}) or {}).get("threshold_source", "default") if isinstance(rubric_content.get("judge_policy", {}), dict) else "default",
        },
        "targets": [
            {
                "path": row["path"],
                "asset_id": row["asset"].get("id", ""),
                "asset_type": row["asset"].get("type", ""),
                "text_excerpt": _target_text(row["asset"])[:6000],
                "source_policy": "generated_or_operator_owned_text_only; do not use raw reference samples",
            }
            for row in targets
        ],
        "expected_json": {
            "recommendation": "ready|needs_revision|blocked",
            "scores": {dimension: "0-100" for dimension in DEFAULT_DIMENSIONS},
            "rationale": "short evidence-backed reason",
        },
    }


def _parse_provider_judge_response(result: dict[str, Any]) -> dict[str, Any]:
    if isinstance(result.get("scores"), dict):
        return result
    text = str(result.get("text") or result.get("response") or result.get("output") or "").strip()
    if text:
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return {"recommendation": "blocked", "scores": {}, "rationale": "provider judge did not return parseable JSON"}


def _normalized_provider_scores(scores: dict[str, Any]) -> dict[str, float]:
    result: dict[str, float] = {}
    for dimension in DEFAULT_DIMENSIONS:
        result[dimension] = max(0.0, min(100.0, _float(scores.get(dimension, 0.0))))
    return result


def _weighted_overall(scores: dict[str, float], rubric: dict[str, Any]) -> float:
    weights = rubric.get("weights", {}) if isinstance(rubric.get("weights"), dict) else {}
    if not weights:
        return round(mean(scores.values()), 2) if scores else 0.0
    total_weight = sum(float(weights.get(key, 0.0) or 0.0) for key in scores)
    if total_weight <= 0:
        return round(mean(scores.values()), 2) if scores else 0.0
    return round(sum(float(scores[key]) * float(weights.get(key, 0.0) or 0.0) for key in scores) / total_weight, 2)


def _provider_evidence_from_routed(result: dict[str, Any]) -> dict[str, Any]:
    gateway = result.get("model_gateway_call", {}) if isinstance(result.get("model_gateway_call", {}), dict) else {}
    return {
        "mode": "provider_runtime_policy",
        "model_route_resolution_path": str(result.get("model_route_resolution_path") or ""),
        "model_call_log_path": str(gateway.get("model_call_log_path") or ""),
        "runtime_policy_path": str(gateway.get("runtime_policy_path") or ""),
        "cost_ledger_path": str(gateway.get("cost_ledger_path") or ""),
        "provider_policy": gateway.get("provider_policy", {}) if isinstance(gateway.get("provider_policy", {}), dict) else {},
        "approval_evidence": gateway.get("approval_evidence", {}) if isinstance(gateway.get("approval_evidence", {}), dict) else {},
        "provider": str(gateway.get("provider") or ""),
        "model": str(gateway.get("model") or ""),
    }


def _provider_judge_run_report(
    *,
    suite_type: str,
    provider_evidence: dict[str, Any],
    external_proof: dict[str, Any],
    require_external_provider_proof: bool,
    recommendation: str,
    overall: float,
) -> dict[str, Any]:
    external_status = str(external_proof.get("status") or "not_required")
    return {
        "status": "completed" if recommendation in {"ready", "needs_revision", "blocked"} else "unknown",
        "suite_type": suite_type,
        "recommendation": recommendation,
        "overall_score": overall,
        "provider": str(provider_evidence.get("provider") or ""),
        "model": str(provider_evidence.get("model") or ""),
        "route_resolution_path": str(provider_evidence.get("model_route_resolution_path") or ""),
        "model_call_log_path": str(provider_evidence.get("model_call_log_path") or ""),
        "runtime_policy_path": str(provider_evidence.get("runtime_policy_path") or ""),
        "cost_ledger_path": str(provider_evidence.get("cost_ledger_path") or ""),
        "approval_evidence": provider_evidence.get("approval_evidence", {}) if isinstance(provider_evidence.get("approval_evidence", {}), dict) else {},
        "provider_policy": provider_evidence.get("provider_policy", {}) if isinstance(provider_evidence.get("provider_policy", {}), dict) else {},
        "external_provider_proof_required": bool(require_external_provider_proof),
        "external_provider_proof_status": external_status,
        "external_provider_proof_path": str(external_proof.get("path") or ""),
        "production_ready_evidence": bool(provider_evidence.get("model_route_resolution_path") and provider_evidence.get("model_call_log_path") and provider_evidence.get("runtime_policy_path") and provider_evidence.get("cost_ledger_path")),
        "credential_boundary": "credential references only; no raw provider secret is persisted",
    }


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _recommendation(overall: float, rubric: dict[str, Any]) -> str:
    thresholds = rubric.get("thresholds", {}) if isinstance(rubric.get("thresholds"), dict) else {}
    ready = float(thresholds.get("ready", 80))
    revision = float(thresholds.get("needs_revision", 65))
    if overall >= ready:
        return "ready"
    if overall >= revision:
        return "needs_revision"
    return "blocked"


def _quality_issue_candidates(targets: list[dict[str, Any]], scores: list[dict[str, Any]], recommendation: str, rubric: dict[str, Any], *, project_id: str) -> list[dict[str, Any]]:
    severity = "critical" if recommendation == "blocked" else "high"
    candidates = []
    for target, score in zip(targets, scores):
        weak = [name for name, value in score.get("dimension_scores", {}).items() if float(value) < 65]
        candidates.append(
            {
                "issue_type": "quality_gate",
                "severity": severity,
                "blocking": recommendation == "blocked",
                "target_asset_id": target["asset"].get("id", ""),
                "target_asset_type": target["asset"].get("type", ""),
                "target_asset_path": target["path"],
                "project_id": project_id,
                "message": f"quality suite recommendation is {recommendation}; weak dimensions: {', '.join(weak[:5])}",
                "fix_suggestion": "Create a revision task for weak dimensions before publish gate.",
                "evidence_refs": [target["path"], str(rubric.get("path", ""))],
            }
        )
    return candidates


def _write_revision_task(storage: LocalStorage, *, report_path: str, target_paths: list[str], scores: list[dict[str, Any]], recommendation: str, project_id: str) -> str:
    issues = [
        {
            "issue_index": index,
            "severity": "critical" if recommendation == "blocked" else "high",
            "message": f"quality score {score.get('overall')} requires {recommendation}",
            "dimension_scores": score.get("dimension_scores", {}),
        }
        for index, score in enumerate(scores)
    ]
    task = RevisionTask(
        title="Quality evaluation revision task",
        source=report_path,
        tags=["quality-eval-v2", "revision-task"],
        content={
            "task_id": make_id("revision_task", f"quality-{report_path}"),
            "review_path": report_path,
            "source_draft_path": target_paths[0] if target_paths else "",
            "issue_indexes": list(range(len(issues))),
            "issues": issues,
            "status": "open",
            "created_at": utc_now(),
            "outputs": {"quality_recommendation": recommendation, "target_paths": target_paths},
        },
        metadata={"project_id": project_id, "source_system": "quality_eval.v2"},
        references=[report_path, *target_paths],
    )
    return _write_asset(storage, task)


def _quality_calibration_rows(storage: LocalStorage, *, project_id: str, limit: int) -> list[dict[str, Any]]:
    target_types = {
        "quality_rubric_pack",
        "opening_3_report",
        "golden_10_report",
        "volume_30_report",
        "longform_100_report",
        "model_judge_result",
        "human_annotation",
        "evaluation_suite",
        "evaluation_regression_report",
        "external_provider_proof_report",
    }
    rows: list[dict[str, Any]] = []
    for category in DATA_DIRS:
        for path in reversed(storage.list_json(category)):
            data = _read_json_safe(storage, path)
            if data.get("type") not in target_types:
                continue
            metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
            content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
            row_project = str(metadata.get("project_id") or content.get("project_id") or "")
            if project_id and row_project and row_project != project_id:
                continue
            rows.append({**data, "path": _display_path(storage.root, path)})
            if len(rows) >= limit:
                return _sort_latest(rows)
    return _sort_latest(rows)


def _rows_by_type(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("type") or ""), []).append(row)
    return grouped


def _classify_model_judge(row: dict[str, Any]) -> dict[str, Any]:
    content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
    evidence = content.get("provider_evidence", {}) if isinstance(content.get("provider_evidence", {}), dict) else {}
    provider = str(evidence.get("provider") or "").strip()
    provider_policy = evidence.get("provider_policy", {}) if isinstance(evidence.get("provider_policy", {}), dict) else {}
    approval_evidence = evidence.get("approval_evidence", {}) if isinstance(evidence.get("approval_evidence", {}), dict) else {}
    external_proof = evidence.get("external_provider_proof", {}) if isinstance(evidence.get("external_provider_proof", {}), dict) else {}
    provider_lower = provider.lower()
    fixture_mode = bool(
        provider_policy.get("mock_provider_fixture_mode")
        or provider_lower in {"mock", "mock-provider", "local-mock", "mock-openai", "fixture-mock"}
        or "fixture" in provider_lower
        or str(evidence.get("mode") or "").lower() in {"fixture", "mock"}
    )
    production_ready_evidence = bool(
        evidence.get("model_route_resolution_path")
        and evidence.get("model_call_log_path")
        and evidence.get("runtime_policy_path")
        and evidence.get("cost_ledger_path")
        and provider_policy.get("status") == "passed"
        and approval_evidence.get("approved")
    )
    if str(external_proof.get("status") or "") == "passed":
        classification = "external_provider"
    elif fixture_mode:
        classification = "fixture_or_mock"
    elif production_ready_evidence:
        classification = "provider_route_approved"
    elif evidence:
        classification = "provider_evidence_incomplete"
    else:
        classification = "missing_provider_evidence"
    return {
        "id": str(row.get("id") or ""),
        "path": str(row.get("path") or ""),
        "target_asset_id": str(content.get("target_asset_id") or ""),
        "recommendation": str(content.get("recommendation") or ""),
        "provider": provider,
        "model": str(evidence.get("model") or ""),
        "classification": classification,
        "external_provider_proof_status": str(external_proof.get("status") or "missing"),
        "external_provider_proof_path": str(external_proof.get("path") or ""),
        "route_resolution_path": str(evidence.get("model_route_resolution_path") or ""),
        "model_call_log_path": str(evidence.get("model_call_log_path") or ""),
        "runtime_policy_path": str(evidence.get("runtime_policy_path") or ""),
        "cost_ledger_path": str(evidence.get("cost_ledger_path") or ""),
        "provider_policy_status": str(provider_policy.get("status") or ""),
        "approval_evidence_present": bool(approval_evidence.get("approved")),
    }


def _is_golden_set(row: dict[str, Any]) -> bool:
    content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
    golden_set = content.get("golden_set", {}) if isinstance(content.get("golden_set", {}), dict) else {}
    return bool(golden_set.get("enabled"))


def _is_provider_calibration_report(row: dict[str, Any]) -> bool:
    content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
    return bool(content.get("calibration_status") or "provider-judge-calibration" in {str(tag) for tag in row.get("tags", [])})


def _calibration_status(row: dict[str, Any]) -> str:
    content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
    metadata = row.get("metadata", {}) if isinstance(row.get("metadata", {}), dict) else {}
    return str(content.get("calibration_status") or content.get("status") or metadata.get("status") or "")


def _readiness_dimension(dimension: str, present: bool, action: str) -> dict[str, Any]:
    return {"dimension": dimension, "status": "present" if present else "missing", "required_for_pass": True, "operator_action": "" if present else action}


def _compact_quality_row(row: dict[str, Any]) -> dict[str, str]:
    content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
    metadata = row.get("metadata", {}) if isinstance(row.get("metadata", {}), dict) else {}
    return {
        "id": str(row.get("id") or ""),
        "type": str(row.get("type") or ""),
        "path": str(row.get("path") or ""),
        "status": str(content.get("status") or content.get("recommendation") or content.get("verdict") or metadata.get("status") or ""),
    }


def _compact_calibration_report(row: dict[str, Any]) -> dict[str, Any]:
    content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
    return {
        "id": str(row.get("id") or ""),
        "path": str(row.get("path") or ""),
        "status": _calibration_status(row),
        "mean_absolute_error": content.get("mean_absolute_error", 0),
        "tolerance": content.get("tolerance", 0),
        "golden_set_path": str(content.get("golden_set_path") or ""),
        "calibration_version": str(content.get("calibration_version") or ""),
        "threshold_recommendation": content.get("threshold_recommendation", {}) if isinstance(content.get("threshold_recommendation", {}), dict) else {},
        "human_calibration": content.get("human_calibration", {}) if isinstance(content.get("human_calibration", {}), dict) else {},
    }


def _quality_calibration_recommendations(status: str, summary: dict[str, Any]) -> list[str]:
    if status == "passed":
        return ["Quality calibration readiness has external provider proof, human annotation, golden set, and passed calibration evidence."]
    actions = []
    for dimension in summary.get("missing_dimensions", []):
        actions.append(f"Complete missing quality calibration dimension: {dimension}")
    if summary.get("fixture_or_mock_provider_judge_count") and not summary.get("external_provider_judge_count"):
        actions.append("Fixture/mock provider judge evidence is useful for tests but cannot satisfy external provider calibration readiness.")
    if summary.get("failed_provider_calibration_count") and not summary.get("passed_provider_calibration_count"):
        actions.append("Repair provider judge calibration before final unified acceptance.")
    return actions or ["Create quality calibration evidence before final unified acceptance."]


def _quality_calibration_gate_blockers(*, readiness_status: str, summary: dict[str, Any], dimensions: list[Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if readiness_status == "passed":
        return blockers
    if readiness_status == "missing":
        blockers.append(
            {
                "code": "quality_calibration_readiness_missing",
                "severity": "critical",
                "dimension": "quality_calibration_readiness",
                "message": "quality calibration readiness has no provider/human/golden-set evidence",
                "operator_action": "create rubric, quality suite, external provider judge proof, human annotation, golden set, and provider calibration report",
            }
        )
    elif readiness_status == "blocked":
        blockers.append(
            {
                "code": "quality_calibration_readiness_blocked",
                "severity": "critical",
                "dimension": "provider_judge_calibration",
                "message": "provider judge calibration has failed or blocked evidence",
                "operator_action": "repair or rerun provider judge calibration before production final acceptance",
            }
        )
    missing_dimensions = summary.get("missing_dimensions", []) if isinstance(summary.get("missing_dimensions", []), list) else []
    for dimension in missing_dimensions:
        blockers.append(
            {
                "code": "quality_calibration_dimension_missing",
                "severity": "high",
                "dimension": str(dimension),
                "message": f"required quality calibration dimension is missing: {dimension}",
                "operator_action": _quality_calibration_dimension_action(str(dimension), dimensions),
            }
        )
    if summary.get("fixture_or_mock_provider_judge_count") and not summary.get("external_provider_judge_count"):
        blockers.append(
            {
                "code": "quality_calibration_fixture_provider_only",
                "severity": "high",
                "dimension": "external_provider_judge_proof",
                "message": "fixture/mock provider judge evidence cannot satisfy production quality calibration",
                "operator_action": "run provider quality judge with external provider proof and operator-approved route evidence",
            }
        )
    return blockers


def _quality_calibration_dimension_action(dimension: str, dimensions: list[Any]) -> str:
    for row in dimensions:
        if not isinstance(row, dict):
            continue
        if str(row.get("dimension") or "") == dimension:
            return str(row.get("operator_action") or "")
    return "complete this quality calibration dimension before final unified acceptance"


def _quality_calibration_gate_operator_action(status: str, production: bool, blockers: list[dict[str, Any]]) -> str:
    if status == "passed":
        return "quality calibration readiness gate passed for final unified acceptance"
    if production:
        return "stop production final acceptance until quality calibration blockers are resolved"
    if blockers:
        return "review quality calibration blockers before promoting this project to production final acceptance"
    return "review quality calibration gate status"


def _quality_calibration_operator_action(status: str, summary: dict[str, Any]) -> str:
    if status == "passed":
        return "quality calibration evidence is ready for final unified acceptance preflight"
    if status == "missing":
        return "create rubric, quality suite, provider judge, human annotation, golden set, and calibration evidence"
    if status == "blocked":
        return "repair failed provider judge calibration before treating quality gates as production calibrated"
    if summary.get("external_provider_judge_count", 0) <= 0:
        return "run an approved external provider quality judge with external proof, then calibrate it against human/golden evidence"
    return "complete missing provider/human/golden calibration evidence before final unified acceptance"


def _sort_latest(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: str(row.get("updated_at") or row.get("created_at") or ""), reverse=True)


def _read_json_safe(storage: LocalStorage, path: Path) -> dict[str, Any]:
    try:
        data = storage.read_json(path)
    except (FileNotFoundError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_asset(storage: LocalStorage, asset: Any) -> str:
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("; ".join(errors))
    return _display_path(storage.root, storage.write_asset_auto(asset))


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _display_path(root: Path, path: str | Path) -> str:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = root / resolved
    return str(resolved.relative_to(root)) if resolved.is_relative_to(root) else str(resolved)

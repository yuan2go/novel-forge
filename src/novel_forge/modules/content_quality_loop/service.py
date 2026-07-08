from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.constants import ASSET_DIR_BY_TYPE
from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.character_pressure import create_character_pressure_reports
from novel_forge.modules.chapter_economy import create_chapter_economy_report
from novel_forge.modules.canon_graph import run_canon_graph_plugin
from novel_forge.modules.common import resolve_path
from novel_forge.modules.genre_os import run_genre_risk_gate
from novel_forge.modules.mobile_reading import create_mobile_reading_report
from novel_forge.modules.os_envelope import enforce_os_envelope, envelope_asset_metadata, is_production_environment
from novel_forge.modules.production_context import project_scope_from_asset
from novel_forge.modules.quality_eval import build_quality_rubric_pack, run_provider_quality_judge, run_quality_gate, run_quality_suite
from novel_forge.modules.review_issue import create_review_issue
from novel_forge.modules.style_os import run_style_drift_gate
from novel_forge.schemas import ChapterQualityTrend, ContentQualityLoopReport, QualityScoreReport, RevisionTask, validate_common_fields
from novel_forge.storage.local import LocalStorage

GENRE_PLUGIN_BY_ID = {
    "xuanhuan": "fantasy_power_scale_engine",
    "fantasy": "fantasy_power_scale_engine",
    "mystery": "mystery_evidence_chain_engine",
    "romance": "romance_relationship_state_engine",
    "historical": "historical_faction_network_engine",
    "sci_fi": "sci_fi_rule_consistency_engine",
    "horror": "horror_rule_contamination_engine",
}


def run_content_quality_loop(
    storage: LocalStorage,
    *,
    target_path: str | Path,
    stage: str = "draft",
    suite_type: str = "opening_3",
    genre_strategy_pack_path: str | Path | None = None,
    style_profile_path: str | Path | None = None,
    rubric_path: str | Path | None = None,
    platform_id: str = "local",
    canon_plugin: str = "",
    provider_adapter: Any | None = None,
    provider_runtime_guard: dict[str, Any] | None = None,
    allow_mock_fixture: bool = False,
    require_provider_judge: bool | None = None,
    require_external_provider_proof: bool = False,
    environment: str = "",
    envelope: dict[str, Any] | None = None,
    persist_issues: bool = True,
    attach_to_target: bool = True,
) -> dict[str, Any]:
    target_file = resolve_path(storage.root, target_path)
    target = storage.read_asset(target_file)
    project = project_scope_from_asset(storage, target, input_path=target_file)
    project_id = str(project.get("project_id") or "")
    workspace_path = str(project.get("workspace_path") or "")
    production = is_production_environment(environment or (envelope or {}).get("environment"))
    provider_required = production if require_provider_judge is None else bool(require_provider_judge)
    env = enforce_os_envelope(
        storage,
        envelope_payload=envelope,
        operation="run-content-quality-loop",
        project_id=project_id,
        task_type="content_quality_loop",
        asset_type="content_quality_loop_report",
        source_policy={"raw_source_text_allowed": False, "generation_rag_allowed": False},
        environment=environment,
        require_for_production=True,
    )
    genre_path = str(genre_strategy_pack_path or _latest_asset_path(storage, "genre_strategy_pack", project_id=project_id))
    style_path = str(style_profile_path or _latest_asset_path(storage, "style_profile", project_id=project_id))
    steps: list[dict[str, Any]] = []
    evidence_paths: list[str] = []
    review_issue_paths: list[str] = []
    revision_task_paths: list[str] = []
    genre_id = ""

    if genre_path:
        genre_asset = storage.read_json(resolve_path(storage.root, genre_path))
        genre_content = genre_asset.get("content", {}) if isinstance(genre_asset.get("content", {}), dict) else {}
        genre_id = str(genre_content.get("genre_id") or "")
        result = _record_step(
            "genre_risk_gate",
            run_genre_risk_gate(
                storage,
                strategy_pack_path=genre_path,
                target_path=_display_path(storage.root, target_file),
                evidence={
                    "stage": stage,
                    "auto_quality_loop": True,
                    "longform_risk_controls": genre_content.get("longform_risks", []),
                },
                environment=str(env.get("environment") or environment or ""),
                envelope=env,
                persist_issues=persist_issues,
            ),
        )
        steps.append(result)
        evidence_paths.extend(result["paths"])
        review_issue_paths.extend(result["review_issue_paths"])
    else:
        steps.append(_missing_step("genre_risk_gate", required=production, message="genre_strategy_pack is missing"))

    if style_path:
        result = _record_step(
            "style_drift_gate",
            run_style_drift_gate(
                storage,
                style_profile_path=style_path,
                target_path=_display_path(storage.root, target_file),
                environment=str(env.get("environment") or environment or ""),
                envelope=env,
                persist_issues=persist_issues,
            ),
        )
        steps.append(result)
        evidence_paths.extend(result["paths"])
        review_issue_paths.extend(result["review_issue_paths"])
        if result.get("revision_task_path"):
            revision_task_paths.append(str(result["revision_task_path"]))
    else:
        steps.append(_missing_step("style_drift_gate", required=production, message="style_profile is missing"))

    plugin = canon_plugin or GENRE_PLUGIN_BY_ID.get(genre_id, "mystery_evidence_chain_engine")
    result = _record_step(
        "canon_graph_plugin_gate",
        run_canon_graph_plugin(
            storage,
            {
                "plugin": plugin,
                "target_path": _display_path(storage.root, target_file),
                "project_id": project_id,
                "workspace_path": workspace_path,
                "persist_issues": persist_issues,
            },
        ),
    )
    steps.append(result)
    evidence_paths.extend(result["paths"])
    review_issue_paths.extend(result["review_issue_paths"])

    readable = _run_readable_prose_gate(
        storage,
        target_file=target_file,
        target=target.to_dict(),
        stage=stage,
        project_id=project_id,
        workspace_path=workspace_path,
        persist_issues=persist_issues,
    )
    readable_step = _record_step("readable_prose_gate", readable)
    steps.append(readable_step)
    evidence_paths.extend(readable_step["paths"])
    review_issue_paths.extend(readable_step["review_issue_paths"])
    if readable.get("revision_task_path"):
        revision_task_paths.append(str(readable["revision_task_path"]))

    golden_opening = _run_golden_opening_gate(
        storage,
        target_file=target_file,
        target=target.to_dict(),
        stage=stage,
        project_id=project_id,
        workspace_path=workspace_path,
        persist_issues=persist_issues,
    )
    golden_opening_step = _record_step("golden_opening_gate", golden_opening)
    steps.append(golden_opening_step)
    evidence_paths.extend(golden_opening_step["paths"])
    review_issue_paths.extend(golden_opening_step["review_issue_paths"])
    if golden_opening.get("revision_task_path"):
        revision_task_paths.append(str(golden_opening["revision_task_path"]))

    mobile = create_mobile_reading_report(
        storage,
        _display_path(storage.root, target_file),
        platform_id=platform_id,
        workspace_path=workspace_path,
        persist_issues=persist_issues,
    )
    mobile_step = _record_step("mobile_reading_gate", mobile)
    steps.append(mobile_step)
    evidence_paths.extend(mobile_step["paths"])
    review_issue_paths.extend(mobile_step["review_issue_paths"])
    if mobile.get("revision_task_path"):
        revision_task_paths.append(str(mobile["revision_task_path"]))

    economy = create_chapter_economy_report(
        storage,
        _display_path(storage.root, target_file),
        workspace_path=workspace_path,
        persist_issues=persist_issues,
    )
    economy_step = _record_step("chapter_economy_gate", economy)
    steps.append(economy_step)
    evidence_paths.extend(economy_step["paths"])
    review_issue_paths.extend(economy_step["review_issue_paths"])
    if economy.get("revision_task_path"):
        revision_task_paths.append(str(economy["revision_task_path"]))

    character_pressure = create_character_pressure_reports(
        storage,
        _display_path(storage.root, target_file),
        workspace_path=workspace_path,
        persist_issues=persist_issues,
    )
    character_pressure_step = _record_step("character_pressure_gate", character_pressure)
    steps.append(character_pressure_step)
    evidence_paths.extend(character_pressure_step["paths"])
    review_issue_paths.extend(character_pressure_step["review_issue_paths"])
    if character_pressure.get("revision_task_path"):
        revision_task_paths.append(str(character_pressure["revision_task_path"]))

    resolved_rubric_path = str(rubric_path or "")
    if not resolved_rubric_path:
        rubric = build_quality_rubric_pack(
            storage,
            genre_id=genre_id or "general",
            platform_id=platform_id,
            style_profile_path=style_path,
            scope="chapter" if stage in {"draft", "revision", "revised_draft"} else stage,
            environment=str(env.get("environment") or environment or ""),
            envelope=env,
        )
        resolved_rubric_path = str(rubric["path"])
        steps.append(_record_step("quality_rubric_pack", rubric))
        evidence_paths.append(resolved_rubric_path)

    suite = run_quality_suite(
        storage,
        suite_type=suite_type,
        target_paths=[_display_path(storage.root, target_file)],
        rubric_path=resolved_rubric_path,
        genre_strategy_pack_path=genre_path,
        style_profile_path=style_path,
        platform_id=platform_id,
        environment=str(env.get("environment") or environment or ""),
        envelope=env,
        persist_issues=persist_issues,
    )
    suite_step = _record_step("quality_suite", suite)
    steps.append(suite_step)
    evidence_paths.extend(suite_step["paths"])
    review_issue_paths.extend(suite_step["review_issue_paths"])
    if suite.get("revision_task_path"):
        revision_task_paths.append(str(suite["revision_task_path"]))

    quality_report_path = str(suite["path"])
    if provider_adapter is not None:
        provider = run_provider_quality_judge(
            storage,
            suite_type=suite_type,
            target_paths=[_display_path(storage.root, target_file)],
            rubric_path=resolved_rubric_path,
            adapter=provider_adapter,
            genre_strategy_pack_path=genre_path,
            style_profile_path=style_path,
            platform_id=platform_id,
            environment=str(env.get("environment") or environment or ""),
            envelope=env,
            provider_runtime_guard=provider_runtime_guard,
            allow_mock_fixture=allow_mock_fixture,
            require_external_provider_proof=require_external_provider_proof,
            persist_issues=persist_issues,
        )
        provider_step = _record_step("provider_quality_judge", provider)
        steps.append(provider_step)
        evidence_paths.extend(provider_step["paths"])
        review_issue_paths.extend(provider_step["review_issue_paths"])
        if provider.get("revision_task_path"):
            revision_task_paths.append(str(provider["revision_task_path"]))
        quality_report_path = str(provider["path"])
    elif provider_required:
        steps.append(_missing_step("provider_quality_judge", required=True, message="provider quality judge adapter is required"))
    else:
        steps.append({"name": "provider_quality_judge", "status": "skipped", "blocking": False, "message": "provider judge not required for this environment", "paths": [], "review_issue_paths": []})

    gate = run_quality_gate(
        storage,
        quality_report_path=quality_report_path,
        environment=str(env.get("environment") or environment or ""),
        envelope=env,
    )
    gate_step = _record_step("quality_gate", gate)
    steps.append(gate_step)
    evidence_paths.extend(gate_step["paths"])

    blocking_issues = _blocking_issues(steps)
    status = "blocked" if blocking_issues else "passed"
    if status == "passed" and any(step["status"] == "skipped" for step in steps):
        status = "passed_with_warnings"
    report = ContentQualityLoopReport(
        title=f"Content quality loop for {target.title or target.id}",
        source=target.id,
        tags=["content-quality-loop", stage, status],
        content={
            "loop_id": make_id("content_quality_loop_report", f"{target.id}-{stage}-{utc_now()}"),
            "target_asset_id": target.id,
            "target_asset_type": target.type,
            "target_asset_path": _display_path(storage.root, target_file),
            "stage": stage,
            "status": status,
            "blocking": bool(blocking_issues),
            "steps": steps,
            "evidence_paths": _dedupe(evidence_paths),
            "review_issue_paths": _dedupe(review_issue_paths),
            "revision_task_paths": _dedupe(revision_task_paths),
            "blocking_issues": blocking_issues,
            "created_at": utc_now(),
        },
        metadata={"project_id": project_id, "workspace_path": workspace_path, **envelope_asset_metadata(env)},
        references=_dedupe([_display_path(storage.root, target_file), *evidence_paths, *review_issue_paths, *revision_task_paths]),
    )
    path = _write_asset(storage, report)
    trend_path = _write_chapter_quality_trend(
        storage,
        report_path=path,
        report=report.to_dict(),
        target_file=target_file,
        target=target.to_dict(),
        steps=steps,
        review_issue_paths=review_issue_paths,
        revision_task_paths=revision_task_paths,
        project_id=project_id,
        workspace_path=workspace_path,
        status=status,
        blocking=bool(blocking_issues),
    )
    _attach_trend_to_report(storage, path, trend_path)
    if attach_to_target:
        _attach_loop_to_target(storage, target_file, path, status=status, blocking=bool(blocking_issues), chapter_quality_trend_path=trend_path)
    return {"path": path, "asset": storage.read_json(resolve_path(storage.root, path)), "status": status, "blocking": bool(blocking_issues), "envelope": env, "chapter_quality_trend_path": trend_path}


def _run_readable_prose_gate(
    storage: LocalStorage,
    *,
    target_file: Path,
    target: dict[str, Any],
    stage: str,
    project_id: str,
    workspace_path: str,
    persist_issues: bool,
) -> dict[str, Any]:
    target_content = target.get("content", {}) if isinstance(target.get("content", {}), dict) else {}
    text = str(target_content.get("text") or target_content.get("chapter_text") or "")
    metrics = _readable_prose_metrics(text)
    findings = _readable_prose_findings(text, metrics)
    blocking_findings = [item for item in findings if item.get("blocking")]
    scores = metrics["scores"]
    overall = int(round(sum(scores.values()) / max(len(scores), 1)))
    status = "blocked" if blocking_findings else "passed"
    recommendation = "block" if blocking_findings else "pass"
    report = QualityScoreReport(
        title=f"Readable prose gate for {target.get('title') or target.get('id')}",
        source=str(target.get("id") or ""),
        tags=["readable-prose-gate", stage, status],
        content={
            "target_asset_id": str(target.get("id") or ""),
            "target_asset_path": _display_path(storage.root, target_file),
            "standard_id": "readable-prose-gate-v1",
            "overall_score": overall,
            "scores": scores,
            "gate_results": {
                "status": status,
                "blocking": bool(blocking_findings),
                "blocking_issue_count": len(blocking_findings),
                "issue_count": len(findings),
                "metrics": metrics,
            },
            "recommendation": recommendation,
            "status": status,
            "blocking": bool(blocking_findings),
            "blocking_issue_count": len(blocking_findings),
            "issues": findings,
            "created_at": utc_now(),
        },
        metadata={"project_id": project_id, "workspace_path": workspace_path, "source_system": "readable_prose_gate.v1"},
        references=[_display_path(storage.root, target_file)],
    )
    report_path = _write_asset(storage, report)
    review_issue_paths: list[str] = []
    if persist_issues:
        for issue in findings:
            if not issue.get("blocking"):
                continue
            created = create_review_issue(
                storage,
                {
                    "issue_type": "quality_gate",
                    "severity": issue.get("severity", "high"),
                    "blocking": bool(issue.get("blocking")),
                    "message": issue.get("message", ""),
                    "fix_suggestion": issue.get("fix_suggestion", ""),
                    "target_asset_id": str(target.get("id") or ""),
                    "target_asset_type": str(target.get("type") or ""),
                    "target_asset_path": _display_path(storage.root, target_file),
                    "review_report_id": report.id,
                    "review_report_path": report_path,
                    "project_id": project_id,
                    "workspace_path": workspace_path,
                    "evidence_refs": [report_path, _display_path(storage.root, target_file)],
                    "source_system": "readable_prose_gate.v1",
                    "source_issue": issue,
                },
            )
            review_issue_paths.append(created["path"])
    revision_task_path = ""
    if blocking_findings:
        revision_task_path = _write_readable_prose_revision_task(
            storage,
            report_path=report_path,
            target_path=_display_path(storage.root, target_file),
            target_id=str(target.get("id") or ""),
            findings=blocking_findings,
            project_id=project_id,
            workspace_path=workspace_path,
            review_issue_paths=review_issue_paths,
        )
    data = storage.read_json(resolve_path(storage.root, report_path))
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    content["review_issue_paths"] = review_issue_paths
    content["revision_task_path"] = revision_task_path
    data["content"] = content
    data["references"] = _dedupe([*[str(item) for item in data.get("references", []) if str(item).strip()], *review_issue_paths, revision_task_path])
    storage.write_json(resolve_path(storage.root, report_path), data)
    return {
        "path": report_path,
        "asset": storage.read_json(resolve_path(storage.root, report_path)),
        "status": status,
        "blocking": bool(blocking_findings),
        "review_issues": review_issue_paths,
        "revision_task_path": revision_task_path,
    }


def _run_golden_opening_gate(
    storage: LocalStorage,
    *,
    target_file: Path,
    target: dict[str, Any],
    stage: str,
    project_id: str,
    workspace_path: str,
    persist_issues: bool,
) -> dict[str, Any]:
    target_content = target.get("content", {}) if isinstance(target.get("content", {}), dict) else {}
    chapter_no = _chapter_number(target)
    if chapter_no not in {1, 2, 3}:
        return {
            "status": "skipped",
            "blocking": False,
            "message": "golden opening gate only applies to chapters 1-3",
            "paths": [],
            "review_issues": [],
            "revision_task_path": "",
        }
    text = str(target_content.get("text") or target_content.get("chapter_text") or "")
    metrics = _golden_opening_metrics(text)
    findings = _golden_opening_findings(chapter_no, metrics)
    blocking_findings = [item for item in findings if item.get("blocking")]
    scores = metrics["scores"]
    overall = int(round(sum(scores.values()) / max(len(scores), 1)))
    status = "blocked" if blocking_findings else "passed"
    report = QualityScoreReport(
        title=f"Golden opening gate for chapter {chapter_no}",
        source=str(target.get("id") or ""),
        tags=["golden-opening-gate", stage, f"chapter-{chapter_no}", status],
        content={
            "target_asset_id": str(target.get("id") or ""),
            "target_asset_path": _display_path(storage.root, target_file),
            "chapter_no": chapter_no,
            "standard_id": "golden-opening-gate-v1",
            "overall_score": overall,
            "scores": scores,
            "gate_results": {
                "status": status,
                "blocking": bool(blocking_findings),
                "blocking_issue_count": len(blocking_findings),
                "issue_count": len(findings),
                "metrics": metrics,
                "applies_to_chapters": [1, 2, 3],
            },
            "recommendation": "block" if blocking_findings else "pass",
            "status": status,
            "blocking": bool(blocking_findings),
            "blocking_issue_count": len(blocking_findings),
            "issues": findings,
            "created_at": utc_now(),
        },
        metadata={"project_id": project_id, "workspace_path": workspace_path, "source_system": "golden_opening_gate.v1"},
        references=[_display_path(storage.root, target_file)],
    )
    report_path = _write_asset(storage, report)
    review_issue_paths: list[str] = []
    if persist_issues:
        for issue in blocking_findings:
            created = create_review_issue(
                storage,
                {
                    "issue_type": "quality_gate",
                    "severity": issue.get("severity", "high"),
                    "blocking": True,
                    "message": issue.get("message", ""),
                    "fix_suggestion": issue.get("fix_suggestion", ""),
                    "target_asset_id": str(target.get("id") or ""),
                    "target_asset_type": str(target.get("type") or ""),
                    "target_asset_path": _display_path(storage.root, target_file),
                    "review_report_id": report.id,
                    "review_report_path": report_path,
                    "project_id": project_id,
                    "workspace_path": workspace_path,
                    "evidence_refs": [report_path, _display_path(storage.root, target_file)],
                    "source_system": "golden_opening_gate.v1",
                    "source_issue": issue,
                },
            )
            review_issue_paths.append(created["path"])
    revision_task_path = ""
    if blocking_findings:
        revision_task_path = _write_golden_opening_revision_task(
            storage,
            report_path=report_path,
            target_path=_display_path(storage.root, target_file),
            target_id=str(target.get("id") or ""),
            findings=blocking_findings,
            project_id=project_id,
            workspace_path=workspace_path,
            review_issue_paths=review_issue_paths,
        )
    data = storage.read_json(resolve_path(storage.root, report_path))
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    content["review_issue_paths"] = review_issue_paths
    content["revision_task_path"] = revision_task_path
    data["content"] = content
    data["references"] = _dedupe([*[str(item) for item in data.get("references", []) if str(item).strip()], *review_issue_paths, revision_task_path])
    storage.write_json(resolve_path(storage.root, report_path), data)
    return {
        "path": report_path,
        "asset": storage.read_json(resolve_path(storage.root, report_path)),
        "status": status,
        "blocking": bool(blocking_findings),
        "review_issues": review_issue_paths,
        "revision_task_path": revision_task_path,
    }


def _readable_prose_metrics(text: str) -> dict[str, Any]:
    stripped = text.strip()
    paragraphs = [part.strip() for part in stripped.splitlines() if part.strip()] or ([stripped] if stripped else [])
    sentences = [part.strip() for part in _split_sentences(stripped) if part.strip()]
    opening = stripped[:300]
    ending = stripped[-220:]
    pressure_terms = ["异常", "危险", "证据", "冲突", "逼", "必须", "选择", "代价", "发现", "出现", "失踪", "死", "risk", "must", "evidence", "conflict"]
    action_terms = ["看", "听", "走", "抓", "问", "查", "推", "打开", "追", "挡", "拿", "承认", "选择", "逼", "检查", "发现", "decide", "search", "open"]
    hook_terms = ["下一", "然而", "没想到", "忽然", "门外", "真相", "钩子", "谁", "为何", "再次", "却", "but", "next", "truth"]
    abstract_terms = ["复杂", "重要", "某种", "一种", "似乎", "仿佛", "感觉", "命运", "内心", "东西", "事情", "意义", "无法形容", "不可名状"]
    max_paragraph = max((len(item) for item in paragraphs), default=0)
    scores = {
        "opening_pressure": _score_bool(len(opening) >= 80 and _contains_any(opening, pressure_terms)),
        "scene_progression": min(100, 35 + _count_terms(stripped, action_terms) * 8 + min(len(sentences), 8) * 4),
        "conflict_strength": min(100, 30 + _count_terms(stripped, pressure_terms) * 9),
        "specificity": max(0, 100 - _count_terms(stripped, abstract_terms) * 9),
        "ending_hook": _score_bool(len(ending) >= 60 and _contains_any(ending, hook_terms)),
        "mobile_rhythm": 100 if max_paragraph <= 420 else 72 if max_paragraph <= 760 else 48,
    }
    return {
        "char_count": len(stripped),
        "paragraph_count": len(paragraphs),
        "sentence_count": len(sentences),
        "max_paragraph_chars": max_paragraph,
        "scores": scores,
    }


def _golden_opening_metrics(text: str) -> dict[str, Any]:
    stripped = text.strip()
    first_300 = stripped[:300]
    first_800 = stripped[:800]
    ending = stripped[-320:]
    event_terms = ["异常", "危险", "发现", "出现", "失踪", "死", "血", "案件", "证据", "爆炸", "追", "门外", "合同不见", "risk", "evidence", "dead"]
    pressure_terms = ["必须", "选择", "决定", "代价", "不能", "逼", "若不", "否则", "不甘", "害怕", "decide", "must", "cost"]
    promise_terms = ["真相", "案件", "目标", "体系", "规则", "嫌疑", "关系", "秘密", "敌人", "承诺", "线索", "promise", "truth"]
    hook_terms = ["下一章", "然而", "没想到", "忽然", "真相", "门外", "谁", "为何", "新证据", "不能回头", "却", "but", "next", "truth"]
    abstract_terms = ["复杂", "重要", "某种", "一种", "似乎", "仿佛", "命运", "内心", "事情", "意义", "无法形容", "不可名状"]
    scores = {
        "opening_substance": 100 if len(stripped) >= 800 else 45 if len(stripped) >= 500 else 30,
        "first_300_event_signal": _score_bool(_contains_any(first_300, event_terms)),
        "protagonist_pressure": _score_bool(_contains_any(first_800, pressure_terms)),
        "reader_promise": _score_bool(_contains_any(stripped, promise_terms)),
        "chapter_end_hook": _score_bool(_contains_any(ending, hook_terms)),
        "opening_specificity": max(0, 100 - _count_terms(first_800, abstract_terms) * 10),
    }
    return {
        "char_count": len(stripped),
        "first_300": {"char_count": len(first_300), "has_event_signal": scores["first_300_event_signal"] >= 70},
        "first_800": {"char_count": len(first_800), "has_pressure": scores["protagonist_pressure"] >= 70},
        "scores": scores,
    }


def _golden_opening_findings(chapter_no: int, metrics: dict[str, Any]) -> list[dict[str, Any]]:
    scores = metrics.get("scores", {}) if isinstance(metrics.get("scores", {}), dict) else {}
    findings: list[dict[str, Any]] = []
    if float(scores.get("opening_substance", 0) or 0) < 70:
        findings.append(_golden_opening_issue("golden_opening.substance", "high", True, f"chapter {chapter_no} opening is too short to prove a serial opening promise", "expand the opening into a concrete scene with disturbance, choice, cost, and next-chapter pull"))
    if float(scores.get("first_300_event_signal", 0) or 0) < 70:
        findings.append(_golden_opening_issue("golden_opening.first_300_event_signal", "high", True, "first 300 characters lack an abnormal event, evidence, danger, or concrete disturbance", "rewrite the first 300 characters around an immediate visible disturbance"))
    if float(scores.get("protagonist_pressure", 0) or 0) < 70:
        findings.append(_golden_opening_issue("golden_opening.protagonist_pressure", "high", True, "opening does not force a protagonist choice, cost, or urgent constraint", "add a protagonist decision under pressure with a visible cost"))
    if float(scores.get("reader_promise", 0) or 0) < 70:
        findings.append(_golden_opening_issue("golden_opening.reader_promise", "high", True, "opening does not make the book-level reader promise legible", "surface the central question, genre engine, relationship pressure, or rule promise through action"))
    if float(scores.get("chapter_end_hook", 0) or 0) < 70:
        findings.append(_golden_opening_issue("golden_opening.chapter_end_hook", "high", True, "chapter ending does not pull the reader into the next chapter", "end with new evidence, unresolved danger, reversal, or a changed objective"))
    if float(scores.get("opening_specificity", 0) or 0) < 65:
        findings.append(_golden_opening_issue("golden_opening.specificity", "medium", False, "opening relies too much on abstract summary language", "replace abstract summary with concrete objects, actions, and reactions"))
    return findings


def _golden_opening_issue(dimension: str, severity: str, blocking: bool, message: str, fix: str) -> dict[str, Any]:
    return {
        "dimension": dimension,
        "severity": severity,
        "blocking": blocking,
        "message": message,
        "fix_suggestion": fix,
        "source_system": "golden_opening_gate.v1",
    }


def _readable_prose_findings(text: str, metrics: dict[str, Any]) -> list[dict[str, Any]]:
    scores = metrics.get("scores", {}) if isinstance(metrics.get("scores", {}), dict) else {}
    findings: list[dict[str, Any]] = []
    if int(metrics.get("char_count", 0) or 0) < 600:
        findings.append(_readable_issue("readable_prose.length", "high", True, "chapter draft is too short to prove readable prose", "expand into full scenes with action, conflict, and sensory progression"))
    if float(scores.get("opening_pressure", 0) or 0) < 70:
        findings.append(_readable_issue("readable_prose.opening_pressure", "high", True, "opening lacks a concrete event, pressure, or abnormal signal", "rewrite the first 300-800 characters around a visible disturbance, goal, and cost"))
    if float(scores.get("scene_progression", 0) or 0) < 65:
        findings.append(_readable_issue("readable_prose.scene_progression", "high", True, "chapter has too little observable action progression", "convert exposition into scene actions, decisions, and consequences"))
    if float(scores.get("conflict_strength", 0) or 0) < 65:
        findings.append(_readable_issue("readable_prose.conflict_strength", "high", True, "chapter conflict pressure is too weak for v1 production", "add an obstacle, cost, or antagonist pressure that forces a choice"))
    if float(scores.get("ending_hook", 0) or 0) < 70:
        findings.append(_readable_issue("readable_prose.ending_hook", "high", True, "ending does not create a next-chapter question or reversal", "end with unresolved pressure, new evidence, or a changed objective"))
    if float(scores.get("specificity", 0) or 0) < 70:
        findings.append(_readable_issue("readable_prose.ai_flavor", "medium", False, "draft leans on abstract or generic phrasing", "replace abstract summary with concrete objects, actions, and subtext"))
    if float(scores.get("mobile_rhythm", 0) or 0) < 70:
        findings.append(_readable_issue("readable_prose.mobile_rhythm", "medium", False, "paragraphs are too dense for mobile web-novel reading", "split long paragraphs around action turns and dialogue pressure"))
    return findings


def _readable_issue(dimension: str, severity: str, blocking: bool, message: str, fix: str) -> dict[str, Any]:
    return {
        "dimension": dimension,
        "severity": severity,
        "blocking": blocking,
        "message": message,
        "fix_suggestion": fix,
        "source_system": "readable_prose_gate.v1",
    }


def _split_sentences(text: str) -> list[str]:
    rows: list[str] = []
    current: list[str] = []
    for char in text:
        current.append(char)
        if char in {"。", "！", "？", ".", "!", "?", "\n"}:
            sentence = "".join(current).strip()
            if sentence:
                rows.append(sentence)
            current = []
    tail = "".join(current).strip()
    if tail:
        rows.append(tail)
    return rows


def _contains_any(text: str, terms: list[str]) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms)


def _count_terms(text: str, terms: list[str]) -> int:
    lowered = text.lower()
    return sum(lowered.count(term.lower()) for term in terms)


def _score_bool(value: bool) -> int:
    return 100 if value else 35


def _chapter_number(target: dict[str, Any]) -> int:
    content = target.get("content", {}) if isinstance(target.get("content", {}), dict) else {}
    metadata = target.get("metadata", {}) if isinstance(target.get("metadata", {}), dict) else {}
    for key in ["chapter", "chapter_no", "chapter_number"]:
        value = content.get(key, metadata.get(key))
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return 0


def _write_golden_opening_revision_task(
    storage: LocalStorage,
    *,
    report_path: str,
    target_path: str,
    target_id: str,
    findings: list[dict[str, Any]],
    project_id: str,
    workspace_path: str,
    review_issue_paths: list[str],
) -> str:
    strategy_ids = _dedupe(
        [
            "rewrite_opening_pressure",
            *(
                ["raise_conflict_cost"]
                if any("protagonist_pressure" in str(item.get("dimension", "")) for item in findings)
                else []
            ),
            *(
                ["strengthen_closing_hook"]
                if any("chapter_end_hook" in str(item.get("dimension", "")) for item in findings)
                else []
            ),
        ]
    )
    task = RevisionTask(
        title="Golden opening revision task",
        source=report_path,
        tags=["golden-opening-gate", "revision-task"],
        content={
            "task_id": make_id("revision_task", f"golden-opening-{target_id}-{report_path}"),
            "review_path": report_path,
            "source_draft_path": target_path,
            "issue_indexes": list(range(len(findings))),
            "issues": findings,
            "status": "open",
            "created_at": utc_now(),
            "revision_strategy_plan": {
                "strategy_ids": strategy_ids,
                "patch_scope": "opening_300_800_words_and_closing_hook",
                "required_output_evidence": ["golden_opening_gate_path", "readable_prose_gate_path", "re_review_path"],
                "risk_controls": ["preserve_premise", "no_raw_reference_text", "bounded_opening_patch", "re_review_required"],
            },
            "outputs": {
                "required_strategy": "rewrite chapters 1-3 opening promise before continuing production",
                "review_issue_paths": review_issue_paths,
            },
        },
        metadata={"project_id": project_id, "workspace_path": workspace_path, "source_system": "golden_opening_gate.v1"},
        references=[report_path, target_path, *review_issue_paths],
    )
    return _write_asset(storage, task)


def _write_readable_prose_revision_task(
    storage: LocalStorage,
    *,
    report_path: str,
    target_path: str,
    target_id: str,
    findings: list[dict[str, Any]],
    project_id: str,
    workspace_path: str,
    review_issue_paths: list[str],
) -> str:
    task = RevisionTask(
        title="Readable prose revision task",
        source=report_path,
        tags=["readable-prose-gate", "revision-task"],
        content={
            "task_id": make_id("revision_task", f"readable-prose-{target_id}-{report_path}"),
            "review_path": report_path,
            "source_draft_path": target_path,
            "issue_indexes": list(range(len(findings))),
            "issues": findings,
            "status": "open",
            "created_at": utc_now(),
            "outputs": {
                "required_strategy": "rewrite blocked prose spans before re-review",
                "review_issue_paths": review_issue_paths,
            },
        },
        metadata={"project_id": project_id, "workspace_path": workspace_path, "source_system": "readable_prose_gate.v1"},
        references=[report_path, target_path, *review_issue_paths],
    )
    return _write_asset(storage, task)


def _record_step(name: str, result: dict[str, Any]) -> dict[str, Any]:
    asset = result.get("asset", {}) if isinstance(result.get("asset", {}), dict) else {}
    content = asset.get("content", {}) if isinstance(asset.get("content", {}), dict) else {}
    status = _status_from_result(result, content)
    paths = _paths_from_result(result)
    review_paths = [str(item) for item in result.get("review_issues", []) if str(item).strip()] if isinstance(result.get("review_issues", []), list) else []
    primary_path = str(result.get("path") or (paths[0] if paths else ""))
    return {
        "name": name,
        "status": status,
        "blocking": status in {"blocked", "missing", "failed"} or bool(content.get("blocking")),
        "path": primary_path,
        "paths": paths,
        "review_issue_paths": review_paths,
        "revision_task_path": str(result.get("revision_task_path") or content.get("revision_task_path") or ""),
        "summary": _step_summary(content),
    }


def _status_from_result(result: dict[str, Any], content: dict[str, Any]) -> str:
    if result.get("status"):
        value = str(result.get("status"))
    else:
        value = str(content.get("status") or content.get("recommendation") or "")
    if value in {"ready", "passed", "pass", "accepted", "succeeded"}:
        return "passed"
    if value in {"blocked", "block", "failed"}:
        return "blocked"
    if value in {"needs_revision", "warning", "warn"}:
        return "needs_revision"
    if content.get("blocking") or int(content.get("blocking_issue_count", 0) or 0) > 0:
        return "blocked"
    return value or "passed"


def _paths_from_result(result: dict[str, Any]) -> list[str]:
    keys = [
        "path",
        "run_path",
        "acceptance_report_path",
        "style_rewrite_task_path",
        "revision_task_path",
        "protagonist_charm_report_path",
        "antagonist_pressure_report_path",
        "mobile_reading_report_path",
    ]
    values = [str(result.get(key) or "") for key in keys]
    for key in ["model_judge_result_paths", "review_issues"]:
        if isinstance(result.get(key), list):
            values.extend(str(item) for item in result[key])
    external = result.get("external_provider_proof", {}) if isinstance(result.get("external_provider_proof", {}), dict) else {}
    values.append(str(external.get("path") or ""))
    return _dedupe(values)


def _missing_step(name: str, *, required: bool, message: str) -> dict[str, Any]:
    return {"name": name, "status": "missing" if required else "skipped", "blocking": bool(required), "message": message, "paths": [], "review_issue_paths": [], "summary": {}}


def _blocking_issues(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues = []
    for step in steps:
        if step.get("blocking"):
            issues.append(
                {
                    "dimension": f"content_quality_loop.{step.get('name')}",
                    "severity": "critical" if step.get("name") in {"provider_quality_judge", "quality_gate"} else "high",
                    "message": str(step.get("message") or f"{step.get('name')} status is {step.get('status')}"),
                    "status": str(step.get("status") or ""),
                    "path": str(step.get("path") or ""),
                }
            )
    return issues


def _latest_asset_path(storage: LocalStorage, asset_type: str, *, project_id: str) -> str:
    category = ASSET_DIR_BY_TYPE.get(asset_type)
    if not category:
        return ""
    rows: list[tuple[str, str]] = []
    for path in storage.list_json(category):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if data.get("type") != asset_type:
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if project_id and str(metadata.get("project_id") or content.get("project_id") or "") not in {project_id, ""}:
            continue
        rows.append((str(data.get("updated_at") or data.get("created_at") or ""), _display_path(storage.root, path)))
    return sorted(rows)[-1][1] if rows else ""


def _step_summary(content: dict[str, Any]) -> dict[str, Any]:
    keys = ["recommendation", "status", "blocking", "blocking_issue_count", "overall_score", "drift_level", "state_machine_status"]
    return {key: content.get(key) for key in keys if key in content}


def _write_chapter_quality_trend(
    storage: LocalStorage,
    *,
    report_path: str,
    report: dict[str, Any],
    target_file: Path,
    target: dict[str, Any],
    steps: list[dict[str, Any]],
    review_issue_paths: list[str],
    revision_task_paths: list[str],
    project_id: str,
    workspace_path: str,
    status: str,
    blocking: bool,
) -> str:
    content = report.get("content", {}) if isinstance(report.get("content", {}), dict) else {}
    target_content = target.get("content", {}) if isinstance(target.get("content", {}), dict) else {}
    chapter_no = _chapter_no(target_content)
    provider_step = _step_by_name(steps, "provider_quality_judge")
    quality_gate_step = _step_by_name(steps, "quality_gate")
    quality_suite_step = _step_by_name(steps, "quality_suite")
    point = {
        "chapter_no": chapter_no,
        "stage": str(content.get("stage") or ""),
        "target_asset_id": str(target.get("id") or ""),
        "target_asset_type": str(target.get("type") or ""),
        "target_asset_path": _display_path(storage.root, target_file),
        "content_quality_loop_path": report_path,
        "content_quality_loop_status": status,
        "blocking": blocking,
        "provider_judge_status": str(provider_step.get("status") or "missing"),
        "provider_judge_path": str(provider_step.get("path") or ""),
        "quality_suite_status": str(quality_suite_step.get("status") or ""),
        "quality_suite_path": str(quality_suite_step.get("path") or ""),
        "quality_gate_status": str(quality_gate_step.get("status") or ""),
        "quality_gate_path": str(quality_gate_step.get("path") or ""),
        "review_issue_count": len(_dedupe(review_issue_paths)),
        "revision_task_count": len(_dedupe(revision_task_paths)),
        "created_at": utc_now(),
    }
    trend = ChapterQualityTrend(
        title=f"Chapter {chapter_no} quality trend point",
        source=str(target.get("id") or ""),
        tags=["chapter-quality-trend", status, str(content.get("stage") or "")],
        content={
            "trend_id": make_id("chapter_quality_trend", f"{project_id or 'local'}-{chapter_no}-{content.get('loop_id', '')}"),
            "run_id": str(content.get("loop_id") or ""),
            "points": [point],
            "summary": {
                "latest_chapter": chapter_no,
                "latest_status": status,
                "blocking": blocking,
                "provider_judge_status": point["provider_judge_status"],
                "review_issue_count": point["review_issue_count"],
                "revision_task_count": point["revision_task_count"],
            },
        },
        metadata={"project_id": project_id, "workspace_path": workspace_path, "status": status},
        references=_dedupe([report_path, _display_path(storage.root, target_file), point["provider_judge_path"], point["quality_suite_path"], point["quality_gate_path"], *review_issue_paths, *revision_task_paths]),
    )
    return _write_asset(storage, trend)


def _attach_trend_to_report(storage: LocalStorage, report_path: str, trend_path: str) -> None:
    data = storage.read_json(resolve_path(storage.root, report_path))
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    refs = data.get("references", []) if isinstance(data.get("references", []), list) else []
    content["chapter_quality_trend_path"] = trend_path
    data["content"] = content
    data["references"] = _dedupe([*refs, trend_path])
    storage.write_json(resolve_path(storage.root, report_path), data)


def _chapter_no(content: dict[str, Any]) -> int:
    try:
        return int(content.get("chapter") or content.get("chapter_no") or 0)
    except (TypeError, ValueError):
        return 0


def _step_by_name(steps: list[dict[str, Any]], name: str) -> dict[str, Any]:
    for step in steps:
        if step.get("name") == name:
            return step
    return {}


def _attach_loop_to_target(storage: LocalStorage, target_file: Path, report_path: str, *, status: str, blocking: bool, chapter_quality_trend_path: str = "") -> None:
    data = storage.read_json(target_file)
    if not isinstance(data, dict):
        return
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata["content_quality_loop_path"] = report_path
    metadata["content_quality_loop_status"] = status
    metadata["content_quality_loop_blocking"] = blocking
    if chapter_quality_trend_path:
        metadata["chapter_quality_trend_path"] = chapter_quality_trend_path
    content["content_quality_loop"] = {"path": report_path, "status": status, "blocking": blocking, "chapter_quality_trend_path": chapter_quality_trend_path}
    data["metadata"] = metadata
    data["content"] = content
    storage.write_json(target_file, data)


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

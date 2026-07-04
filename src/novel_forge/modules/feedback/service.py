from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.agent_runs import AgentExecutionContext, attach_agent_run_context_contract
from novel_forge.modules.common import read_previous, resolve_path
from novel_forge.modules.context_builder import build_flow_context_bundle, knowledge_context_contract_from_result, knowledge_context_contract_metadata, require_knowledge_context_contract
from novel_forge.modules.production_context import filter_project_safe_references, project_scope_from_asset
from novel_forge.modules.runtime_ledger import record_trace_span
from novel_forge.schemas import (
    FeedbackImportBatch,
    FeedbackInsight,
    OperationalMetricSnapshot,
    ReaderFeedback,
    ReaderFeedbackBackflowReport,
    ReaderSentimentReport,
    ReaderSimulationReport,
    ReviewRulePack,
    TopicSeed,
    WritingTemplate,
    validate_common_fields,
)
from novel_forge.storage.local import LocalStorage


FEEDBACK_TYPES = {
    "feedback_import_batch",
    "reader_feedback",
    "feedback_insight",
    "reader_sentiment_report",
    "reader_simulation_report",
    "operational_metric_snapshot",
    "reader_feedback_backflow_report",
}


READER_AGENT_PERSONAS: list[dict[str, Any]] = [
    {
        "persona_id": "shuangwen_reader",
        "name": "爽文读者",
        "focus": ["爽点够不够", "节奏拖不拖", "即时反馈"],
        "positive_keywords": ["爽", "打脸", "奖励", "赢", "碾压", "反杀", "升级", "收益", "突破"],
        "negative_keywords": ["拖", "憋屈", "铺垫", "压抑", "没爽点", "无聊"],
        "gap_label": "爽点缺口",
    },
    {
        "persona_id": "mystery_reader",
        "name": "悬疑读者",
        "focus": ["线索公平", "谜题吸引力", "反转可信"],
        "positive_keywords": ["线索", "证据", "谜", "真相", "反转", "伏笔", "嫌疑", "推理"],
        "negative_keywords": ["硬转", "没证据", "糊弄", "漏洞", "看不懂"],
        "gap_label": "谜题缺口",
    },
    {
        "persona_id": "qidian_veteran",
        "name": "起点老读者",
        "focus": ["主线成长", "付费价值", "世界观稳定"],
        "positive_keywords": ["成长", "主线", "世界", "规则", "境界", "资源", "势力", "长期"],
        "negative_keywords": ["主线散", "设定乱", "水", "停滞", "掉线"],
        "gap_label": "长线价值缺口",
    },
    {
        "persona_id": "fanqie_reader",
        "name": "番茄读者",
        "focus": ["强情绪", "强反转", "低阅读门槛"],
        "positive_keywords": ["反转", "情绪", "痛点", "误会", "爽", "立刻", "短", "直接"],
        "negative_keywords": ["慢", "复杂", "设定多", "门槛", "看不懂"],
        "gap_label": "情绪刺激缺口",
    },
    {
        "persona_id": "relationship_reader",
        "name": "女频/关系向读者",
        "focus": ["人物关系", "情绪拉扯", "人设吸引力"],
        "positive_keywords": ["关系", "心动", "误会", "选择", "动机", "拉扯", "情绪", "人设"],
        "negative_keywords": ["工具人", "没动机", "尴尬", "无感", "人设崩"],
        "gap_label": "关系张力缺口",
    },
    {
        "persona_id": "editor_reader",
        "name": "编辑视角",
        "focus": ["商业价值", "开篇留存", "平台适配"],
        "positive_keywords": ["钩子", "留存", "冲突", "卖点", "期待", "平台", "节奏", "价值"],
        "negative_keywords": ["开局慢", "定位弱", "卖点弱", "风险", "不适配"],
        "gap_label": "商业留存缺口",
    },
]


def import_feedback(storage: LocalStorage, input_path: str) -> Path:
    path = resolve_path(storage.root, input_path)
    if not path.exists():
        raise FileNotFoundError(f"feedback file not found: {path}")
    with AgentExecutionContext(
        storage,
        agent_key="feedback",
        skill="reader-feedback",
        operation="legacy-import-feedback",
        output_types=["reader_feedback"],
        sla_seconds=300,
    ) as run:
        run.guard("import_feedback_file")
        rows = _read_csv_rows(path)
        asset = ReaderFeedback(
            title=path.stem,
            source=str(path),
            tags=["feedback", "reader"],
            content={"rows": rows},
            metadata={"imported_at": utc_now(), "row_count": len(rows)},
        )
        run.guard("write_reader_feedback", "reader_feedback")
        output = storage.write_asset("feedback", asset)
        run.succeed(output_assets=[_display_path(storage.root, output)])
        return output


def list_feedback_assets(
    storage: LocalStorage,
    *,
    project_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in reversed(storage.list_json("feedback")):
        data = storage.read_json(path)
        if not isinstance(data, dict) or data.get("type") not in FEEDBACK_TYPES:
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if project_id and str(metadata.get("project_id", "")) != project_id:
            continue
        rows.append(
            {
                "path": _display_path(storage.root, path),
                "id": data.get("id", ""),
                "type": data.get("type", ""),
                "title": data.get("title") or data.get("name", ""),
                "project_id": metadata.get("project_id", ""),
                "workspace_path": metadata.get("workspace_path", ""),
                "row_count": content.get("row_count", len(content.get("rows", [])) if isinstance(content.get("rows"), list) else 0),
                "average_rating": content.get("average_rating", 0),
                "confidence": content.get("confidence") or content.get("trend_metrics", {}).get("confidence", ""),
                "sentiment_distribution": content.get("sentiment_distribution", {}),
                "character_heat": content.get("character_heat", []),
                "follow_read_risk": content.get("follow_read_risk", {}),
                "read_metrics": content.get("read_metrics", {}),
                "engagement_metrics": content.get("engagement_metrics", {}),
                "chapter_dropoffs": content.get("chapter_dropoffs", []),
                "next_chapter_strategy": content.get("next_chapter_strategy", {}),
                "reader_simulation": content.get("aggregate", {}),
                "target_updates": content.get("target_updates", {}),
                "recommendation": _feedback_recommendation(content),
                "status": content.get("status", metadata.get("asset_status", "")),
                "updated_at": data.get("updated_at", ""),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def create_feedback_import_batch(
    storage: LocalStorage,
    input_path: str,
    *,
    workspace_path: str | None = None,
    source_label: str = "",
    platform: str = "manual",
) -> dict[str, Any]:
    path = resolve_path(storage.root, input_path)
    if not path.exists():
        raise FileNotFoundError(f"feedback file not found: {path}")
    rows = _read_csv_rows(path)
    project = project_scope_from_asset(storage, {}, workspace_path=workspace_path)
    project_id = str(project.get("project_id", ""))
    workspace = str(project.get("workspace_path", ""))
    with AgentExecutionContext(
        storage,
        agent_key="feedback",
        skill="reader-feedback",
        operation="import-feedback-batch",
        output_types=["feedback_import_batch", "reader_feedback"],
        workspace_path=workspace,
        sla_seconds=300,
    ) as run:
        run.guard("import_feedback_file")
        batch_id = make_id("feedback_import_batch", path.stem)
        columns = sorted({key for row in rows for key in row})
        batch_asset = FeedbackImportBatch(
            title=f"Feedback import: {source_label or path.stem}",
            source=str(path),
            tags=["feedback", "import", platform],
            content={
                "batch_id": batch_id,
                "source": str(path),
                "source_label": source_label or path.stem,
                "platform": platform,
                "rows": rows,
                "row_count": len(rows),
                "columns": columns,
                "status": "imported",
                "imported_at": utc_now(),
            },
            metadata={
                "project_id": project_id,
                "workspace_path": workspace,
                "workflow": "feedback-import",
                "source_kind": "local_upload",
                "privacy_boundary": "aggregate reader feedback; do not store private identities beyond supplied columns",
            },
        )
        run.guard("write_feedback_import_batch", "feedback_import_batch")
        batch_result = _write(storage, batch_asset)
        feedback_asset = ReaderFeedback(
            title=f"Reader feedback: {source_label or path.stem}",
            source=batch_asset.id,
            tags=["feedback", "reader", platform],
            content={"rows": rows, "row_count": len(rows), "columns": columns, "import_batch_id": batch_asset.id},
            metadata={
                "project_id": project_id,
                "workspace_path": workspace,
                "workflow": "feedback-import",
                "imported_at": utc_now(),
                "row_count": len(rows),
                "source_path": _display_path(storage.root, path) if path.is_relative_to(storage.root) else str(path),
            },
            references=filter_project_safe_references(storage, project_id, [batch_asset.id, batch_result["path"], workspace]),
        )
        run.guard("write_reader_feedback", "reader_feedback")
        feedback_result = _write(storage, feedback_asset)
        run.succeed(output_assets=[batch_result["path"], feedback_result["path"]])
        return {"batch": batch_result, "reader_feedback": feedback_result}


def analyze_feedback(storage: LocalStorage, input_path: str | None = None) -> Path:
    feedback = read_previous(storage, "feedback", input_path)
    rows = _feedback_rows(storage, feedback.id)
    if input_path:
        rows = _merge_rows(feedback.content.get("rows", []), rows)
    comments = " ".join(row.get("comment", "") for row in rows)
    chapter_trends = build_chapter_trends(rows)
    trend_metrics = build_trend_metrics(chapter_trends, rows)
    retention_risk = assess_retention_risk(chapter_trends, rows)
    sentiment_signals = mine_sentiment_signals(rows)
    adjustment_plan = build_plot_adjustment_plan(chapter_trends, retention_risk, sentiment_signals, trend_metrics)
    with AgentExecutionContext(
        storage,
        agent_key="feedback",
        skill="reader-feedback",
        operation="analyze-feedback",
        input_assets=[input_path or feedback.id],
        output_types=["feedback_insight"],
        sla_seconds=300,
    ) as run:
        run.guard("read_asset")
        run.guard("analyze_feedback")
        asset = FeedbackInsight(
            title=f"Insight from {feedback.title}",
            source=feedback.id,
            tags=["feedback", "insight"],
            content={
                "signals": sentiment_signals["signals"],
                "average_rating": average_rating(rows),
                "next_generation_constraints": adjustment_plan["next_generation_constraints"],
                "chapter_trends": chapter_trends,
                "trend_metrics": trend_metrics,
                "retention_risk": retention_risk,
                "sentiment_signals": sentiment_signals,
                "plot_adjustment_plan": adjustment_plan,
                "raw_comment_summary": comments[:240],
            },
            metadata={
                "workflow": "feedback-trend-analysis",
                "feedback_asset_count": len([path for path in storage.list_json("feedback") if _is_reader_feedback(storage, path)]),
                "row_count": len(rows),
                "chapter_count": len(chapter_trends),
            },
            references=[feedback.id],
        )
        run.guard("write_feedback_insight", "feedback_insight")
        output = storage.write_asset("feedback", asset)
        run.succeed(output_assets=[_display_path(storage.root, output)])
        return output


def create_reader_sentiment_report(
    storage: LocalStorage,
    *,
    feedback_paths: list[str | Path] | None = None,
    project_id: str | None = None,
    workspace_path: str | None = None,
) -> dict[str, Any]:
    feedback_assets = _selected_feedback_assets(storage, feedback_paths or [], project_id=project_id)
    if not feedback_assets:
        raise FileNotFoundError("no reader_feedback assets found for sentiment report")
    rows: list[dict[str, str]] = []
    refs: list[str] = []
    for item in feedback_assets:
        rows = _merge_rows(rows, item["content"].get("rows", []))
        refs.extend([item["id"], item["path"]])
    project = project_scope_from_asset(storage, {"metadata": {"project_id": project_id or ""}, "references": refs}, workspace_path=workspace_path or _first_workspace(feedback_assets))
    resolved_project_id = str(project.get("project_id", project_id or ""))
    workspace = str(project.get("workspace_path", workspace_path or ""))
    with AgentExecutionContext(
        storage,
        agent_key="feedback",
        skill="reader-feedback",
        operation="create-reader-sentiment-report",
        input_assets=[item["path"] for item in feedback_assets],
        output_types=["reader_sentiment_report"],
        workspace_path=workspace,
        sla_seconds=300,
    ) as run:
        run.guard("read_asset")
        signals = mine_sentiment_signals(rows)
        distribution = _sentiment_distribution(rows)
        clusters = _feedback_clusters(signals, distribution, rows)
        chapter_trends = build_chapter_trends(rows)
        trend_metrics = build_trend_metrics(chapter_trends, rows)
        retention_risk = assess_retention_risk(chapter_trends, rows)
        adjustment_plan = build_plot_adjustment_plan(chapter_trends, retention_risk, signals, trend_metrics)
        character_heat = _character_heat(rows)
        follow_read_risk = _follow_read_risk(distribution, trend_metrics, retention_risk)
        next_strategy = _next_chapter_strategy(adjustment_plan, follow_read_risk, character_heat)
        asset = ReaderSentimentReport(
            title=f"Reader sentiment report {utc_now()}",
            tags=["feedback", "reader-sentiment", retention_risk.get("level", "unknown")],
            content={
                "feedback_asset_ids": [item["id"] for item in feedback_assets],
                "feedback_asset_paths": [item["path"] for item in feedback_assets],
                "sentiment_distribution": distribution,
                "clusters": clusters,
                "reader_expectations": _reader_expectations(signals, retention_risk),
                "poison_points": _cluster_labels(clusters, polarity="negative"),
                "sweet_points": _cluster_labels(clusters, polarity="positive"),
                "character_heat": character_heat,
                "follow_read_risk": follow_read_risk,
                "next_chapter_strategy": next_strategy,
                "recommendations": adjustment_plan["recommended_actions"],
                "next_generation_constraints": adjustment_plan["next_generation_constraints"],
                "chapter_trends": chapter_trends,
                "trend_metrics": trend_metrics,
                "retention_risk": retention_risk,
                "confidence": trend_metrics.get("confidence", "none"),
                "created_at": utc_now(),
            },
            metadata={
                "project_id": resolved_project_id,
                "workspace_path": workspace,
                "workflow": "reader-feedback-sentiment",
                "row_count": len(rows),
                "feedback_asset_count": len(feedback_assets),
                "risk_level": retention_risk.get("level", "unknown"),
            },
            references=filter_project_safe_references(storage, resolved_project_id, [*refs, workspace]),
        )
        run.guard("write_reader_sentiment_report", "reader_sentiment_report")
        result = _write(storage, asset)
        _record_feedback_span(
            storage,
            trace_id=resolved_project_id or str(result.get("asset", {}).get("id", "")),
            name="create_reader_sentiment_report",
            path=result["path"],
            project_id=resolved_project_id,
            workspace_path=workspace,
            attributes={"row_count": len(rows), "feedback_asset_count": len(feedback_assets), "risk_level": retention_risk.get("level", "unknown")},
        )
        run.succeed(output_assets=[result["path"]])
        return result


def create_operational_metric_snapshot(
    storage: LocalStorage,
    *,
    feedback_paths: list[str | Path] | None = None,
    project_id: str | None = None,
    workspace_path: str | None = None,
) -> dict[str, Any]:
    feedback_assets = _selected_feedback_assets(storage, feedback_paths or [], project_id=project_id)
    if not feedback_assets:
        raise FileNotFoundError("no reader_feedback assets found for operational metric snapshot")
    rows: list[dict[str, str]] = []
    refs: list[str] = []
    for item in feedback_assets:
        rows = _merge_rows(rows, item["content"].get("rows", []))
        refs.extend([item["id"], item["path"]])
    project = project_scope_from_asset(storage, {"metadata": {"project_id": project_id or ""}, "references": refs}, workspace_path=workspace_path or _first_workspace(feedback_assets))
    resolved_project_id = str(project.get("project_id", project_id or ""))
    workspace = str(project.get("workspace_path", workspace_path or ""))
    chapter_trends = build_chapter_trends(rows)
    trend_metrics = build_trend_metrics(chapter_trends, rows)
    retention_risk = assess_retention_risk(chapter_trends, rows)
    distribution = _sentiment_distribution(rows)
    heat = _character_heat(rows)
    follow_risk = _follow_read_risk(distribution, trend_metrics, retention_risk)
    dropoffs = _chapter_dropoffs(rows, chapter_trends)
    read_metrics = _read_metrics(rows)
    engagement_metrics = _engagement_metrics(rows, distribution, trend_metrics)
    recommendations = _operational_recommendations(read_metrics, engagement_metrics, follow_risk, dropoffs, heat)
    with AgentExecutionContext(
        storage,
        agent_key="feedback",
        skill="reader-feedback",
        operation="create-operational-metric-snapshot",
        input_assets=[item["path"] for item in feedback_assets],
        output_types=["operational_metric_snapshot"],
        workspace_path=workspace,
        sla_seconds=300,
    ) as run:
        run.guard("read_asset")
        run.guard("write_operational_metric_snapshot", "operational_metric_snapshot")
        asset = OperationalMetricSnapshot(
            title=f"Operational metric snapshot {utc_now()}",
            tags=["feedback", "operations", follow_risk.get("level", "unknown")],
            content={
                "project_id": resolved_project_id or "global",
                "snapshot_at": utc_now(),
                "read_metrics": read_metrics,
                "engagement_metrics": engagement_metrics,
                "character_heat": heat,
                "chapter_dropoffs": dropoffs,
                "recommendations": recommendations,
                "feedback_asset_ids": [item["id"] for item in feedback_assets],
                "row_count": len(rows),
                "follow_read_risk": follow_risk,
                "trend_metrics": trend_metrics,
                "sentiment_distribution": distribution,
            },
            metadata={
                "project_id": resolved_project_id,
                "workspace_path": workspace,
                "workflow": "reader-feedback-operational-metrics",
                "row_count": len(rows),
                "risk_level": follow_risk.get("level", "unknown"),
            },
            references=filter_project_safe_references(storage, resolved_project_id, [*refs, workspace]),
        )
        result = _write(storage, asset)
        _record_feedback_span(
            storage,
            trace_id=resolved_project_id or str(result.get("asset", {}).get("id", "")),
            name="create_operational_metric_snapshot",
            path=result["path"],
            project_id=resolved_project_id,
            workspace_path=workspace,
            attributes={"row_count": len(rows), "feedback_asset_count": len(feedback_assets), "risk_level": follow_risk.get("level", "unknown")},
        )
        run.succeed(output_assets=[result["path"]])
        return result


def create_reader_simulation_report(
    storage: LocalStorage,
    *,
    draft_path: str | Path | None = None,
    chapter_text: str | None = None,
    project_id: str | None = None,
    workspace_path: str | None = None,
    platform: str = "qidian",
    chapter: int | None = None,
) -> dict[str, Any]:
    source = _reader_simulation_source(storage, draft_path=draft_path, chapter_text=chapter_text)
    project = project_scope_from_asset(
        storage,
        source["asset"] or {"metadata": {"project_id": project_id or ""}},
        workspace_path=workspace_path,
    )
    resolved_project_id = project_id or str(project.get("project_id") or "local-system")
    workspace = workspace_path or str(project.get("workspace_path") or "")
    text = source["text"]
    if not text.strip():
        raise ValueError("chapter_text or draft content is required for reader simulation")
    with AgentExecutionContext(
        storage,
        agent_key="feedback",
        skill="reader-feedback",
        operation="create-reader-simulation-report",
        input_assets=[source["path"]] if source["path"] else [],
        output_types=["reader_simulation_report"],
        workspace_path=workspace,
        sla_seconds=300,
    ) as run:
        run.guard("read_draft_or_explicit_text")
        personas = [_simulate_reader_persona(persona, text, platform=platform) for persona in READER_AGENT_PERSONAS]
        aggregate = _aggregate_reader_simulation(personas)
        simulation_id = make_id("reader_simulation", f"{resolved_project_id}-{platform}-{chapter or source['chapter']}-{len(text)}")
        asset = ReaderSimulationReport(
            id=simulation_id,
            title=f"Reader simulation {platform} {chapter or source['chapter'] or ''}".strip(),
            source=source["path"] or "explicit-chapter-text",
            tags=["feedback", "reader-simulation", platform, aggregate["dropout_risk"]],
            content={
                "simulation_id": simulation_id,
                "project_id": resolved_project_id,
                "workspace_path": workspace,
                "platform": platform,
                "chapter": chapter or source["chapter"],
                "source_path": source["path"],
                "source_policy": {
                    "source_chunk_raw_text_allowed": False,
                    "source_document_raw_text_allowed": False,
                    "accepted_inputs": ["draft_chapter.text", "explicit_project_text"],
                },
                "personas": personas,
                "aggregate": aggregate,
                "created_at": utc_now(),
            },
            metadata={
                "project_id": resolved_project_id,
                "workspace_path": workspace,
                "workflow": "prepublish-reader-simulation",
                "platform": platform,
                "risk_level": aggregate["dropout_risk"],
                "use_in_generation_rag": False,
            },
            references=filter_project_safe_references(storage, resolved_project_id, _dedupe([source["path"], workspace])),
        )
        run.guard("write_reader_simulation_report", "reader_simulation_report")
        result = _write(storage, asset)
        _record_feedback_span(
            storage,
            trace_id=resolved_project_id,
            name="create_reader_simulation_report",
            path=result["path"],
            project_id=resolved_project_id,
            workspace_path=workspace,
            attributes={"platform": platform, "predicted_score": aggregate["predicted_score"], "dropout_risk": aggregate["dropout_risk"]},
        )
        run.succeed(output_assets=[result["path"]])
        return result


def process_real_feedback_backflow(
    storage: LocalStorage,
    *,
    metrics: dict[str, Any],
    project_id: str | None = None,
    workspace_path: str | None = None,
    platform: str = "qidian",
    release_package_path: str | Path | None = None,
    apply_mkaos_weight_update: bool = True,
    environment: str = "",
    os_envelope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(metrics, dict) or not metrics:
        raise ValueError("metrics object is required")
    resolved_project_id = project_id or str(metrics.get("project_id") or "local-system")
    workspace = workspace_path or str(metrics.get("workspace_path") or "")
    normalized = _normalize_real_feedback_metrics(metrics)
    signals = _real_feedback_signals(normalized)
    with AgentExecutionContext(
        storage,
        agent_key="feedback",
        skill="reader-feedback",
        operation="process-real-feedback-backflow",
        input_assets=[str(release_package_path)] if release_package_path else [],
        output_types=[
            "operational_metric_snapshot",
            "platform_feedback_backflow",
            "review_rule_pack",
            "topic_seed",
            "writing_template",
            "reader_feedback_backflow_report",
        ],
        workspace_path=workspace,
        sla_seconds=300,
    ) as run:
        run.guard("normalize_platform_metrics")
        snapshot = _real_feedback_metric_snapshot(
            storage,
            resolved_project_id,
            workspace,
            platform,
            normalized,
            signals,
            release_package_path=release_package_path,
        )
        snapshot_result = _write(storage, snapshot)
        context = build_flow_context_bundle(
            storage,
            snapshot_result["path"],
            flow="feedback_backflow",
            project_id=resolved_project_id,
            workspace_path=workspace,
            current_goal="real feedback backflow learning",
            token_budget=2500,
            environment=environment,
            os_envelope=os_envelope,
        )
        knowledge_contract = knowledge_context_contract_from_result(context)
        attach_agent_run_context_contract(storage, run.path, knowledge_contract)
        require_knowledge_context_contract(knowledge_contract, operation="process-real-feedback-backflow", environment=environment)
        from novel_forge.modules.platform_strategy import create_platform_feedback_backflow

        run.guard("write_platform_feedback_backflow", "platform_feedback_backflow")
        platform_backflow = create_platform_feedback_backflow(
            storage,
            {
                "platform": platform,
                "project_id": resolved_project_id,
                "workspace_path": workspace,
                "signals": signals["labels"],
            },
        )
        run.guard("write_feedback_learning_assets")
        learning_assets = _write_feedback_learning_assets(
            storage,
            project_id=resolved_project_id,
            workspace_path=workspace,
            platform=platform,
            normalized=normalized,
            signals=signals,
            snapshot_path=snapshot_result["path"],
        )
        mkaos_updates = _apply_real_feedback_mkaos_updates(
            storage,
            project_id=resolved_project_id,
            normalized=normalized,
            signals=signals,
            source_path=snapshot_result["path"],
            enabled=apply_mkaos_weight_update,
        )
        target_updates = {
            "mkaos_weight": {
                "status": "updated" if mkaos_updates else ("skipped" if not apply_mkaos_weight_update else "no_usage_events"),
                "updates": mkaos_updates,
            },
            "platform_strategy": {"status": "updated", "path": platform_backflow.get("path", "")},
            "review_rules": {"status": "updated", "path": learning_assets["review_rule_pack_path"]},
            "topic_library": {"status": "updated", "path": learning_assets["topic_seed_path"]},
            "character_templates": {"status": "updated", "path": learning_assets["character_template_path"]},
            "rhythm_templates": {"status": "updated", "path": learning_assets["rhythm_template_path"]},
        }
        report_id = make_id("reader_feedback_backflow", f"{resolved_project_id}-{platform}-{snapshot_result['path']}")
        report = ReaderFeedbackBackflowReport(
            id=report_id,
            title=f"Reader feedback backflow {platform}",
            source=str(release_package_path or snapshot_result["path"]),
            tags=["feedback", "real-feedback-backflow", platform, signals["risk_level"]],
            content={
                "backflow_report_id": report_id,
                "project_id": resolved_project_id,
                "workspace_path": workspace,
                "platform": platform,
                "metric_snapshot_path": snapshot_result["path"],
                "platform_backflow_path": platform_backflow.get("path", ""),
                "target_updates": target_updates,
                "signals": signals,
                "normalized_metrics": normalized,
                "release_package_path": str(release_package_path or ""),
                "knowledge_context_contract": knowledge_contract,
                "created_at": utc_now(),
            },
            metadata={
                "project_id": resolved_project_id,
                "workspace_path": workspace,
                "workflow": "real-feedback-backflow",
                "risk_level": signals["risk_level"],
                "use_in_generation_rag": False,
                **knowledge_context_contract_metadata(knowledge_contract),
            },
            references=filter_project_safe_references(
                storage,
                resolved_project_id,
                _dedupe(
                    [
                        snapshot_result["path"],
                        platform_backflow.get("path", ""),
                        *learning_assets["paths"],
                        str(release_package_path or ""),
                        workspace,
                    ]
                ),
            ),
        )
        run.guard("write_reader_feedback_backflow_report", "reader_feedback_backflow_report")
        report_result = _write(storage, report)
        _record_feedback_span(
            storage,
            trace_id=resolved_project_id,
            name="process_real_feedback_backflow",
            path=report_result["path"],
            project_id=resolved_project_id,
            workspace_path=workspace,
            attributes={"platform": platform, "risk_level": signals["risk_level"], "mkaos_update_count": len(mkaos_updates)},
        )
        run.succeed(output_assets=[report_result["path"], snapshot_result["path"], platform_backflow.get("path", ""), *learning_assets["paths"]])
        return {
            "status": "ready",
            "path": report_result["path"],
            "asset": report_result["asset"],
            "metric_snapshot_path": snapshot_result["path"],
            "platform_backflow_path": platform_backflow.get("path", ""),
            "learning_asset_paths": learning_assets["paths"],
            "mkaos_weight_update_count": len(mkaos_updates),
            "risk_level": signals["risk_level"],
            "target_updates": target_updates,
            "knowledge_context_contract": knowledge_contract,
        }


def process_publish_feedback_loop(
    storage: LocalStorage,
    *,
    feedback_paths: list[str | Path] | None = None,
    project_id: str | None = None,
    workspace_path: str | None = None,
    release_package_path: str | Path | None = None,
    apply_mkaos_weight_update: bool = True,
    require_human_gate: bool = True,
) -> dict[str, Any]:
    feedback_assets = _selected_feedback_assets(storage, feedback_paths or [], project_id=project_id)
    if not feedback_assets:
        raise FileNotFoundError("no reader_feedback assets found for publish feedback loop")
    resolved_project_id = project_id or str(feedback_assets[0].get("metadata", {}).get("project_id", ""))
    workspace = workspace_path or _first_workspace(feedback_assets)
    feedback_asset_paths = [item["path"] for item in feedback_assets]
    sentiment = create_reader_sentiment_report(
        storage,
        feedback_paths=feedback_asset_paths,
        project_id=resolved_project_id or None,
        workspace_path=workspace or None,
    )
    from novel_forge.modules.feedback_backflow import create_feedback_backflow_plan
    from novel_forge.modules.mkaos import apply_weight_update, list_usage_events

    backflow = create_feedback_backflow_plan(
        storage,
        feedback_paths=feedback_asset_paths,
        project_id=resolved_project_id or None,
        workspace_path=workspace or None,
        require_human_gate=require_human_gate,
    )
    sentiment_content = sentiment.get("asset", {}).get("content", {}) if isinstance(sentiment.get("asset", {}), dict) else {}
    mkaos_updates: list[dict[str, Any]] = []
    if apply_mkaos_weight_update:
        usage_events = list_usage_events(storage, project_id=resolved_project_id or None, limit=20)
        delta = _feedback_mkaos_delta(sentiment_content)
        seen: set[str] = set()
        for event in usage_events:
            content = event.get("content", {}) if isinstance(event.get("content", {}), dict) else {}
            knowledge_id = str(content.get("knowledge_id") or "").strip()
            if not knowledge_id or knowledge_id in seen:
                continue
            seen.add(knowledge_id)
            mkaos_updates.append(
                apply_weight_update(
                    storage,
                    {
                        "knowledge_id": knowledge_id,
                        "project_id": resolved_project_id or "local-system",
                        "flow": str(content.get("flow") or "review"),
                        "delta": delta,
                        "reason": "publish_feedback_loop",
                        "feedback_paths": feedback_asset_paths,
                        "release_package_path": str(release_package_path or ""),
                    },
                )
            )
            if len(mkaos_updates) >= 5:
                break
    insight = FeedbackInsight(
        title="Publish feedback loop insight",
        source=str(release_package_path or sentiment.get("path") or ""),
        tags=["feedback", "publish-loop", "mkaos-weight-update" if mkaos_updates else "no-mkaos-update"],
        content={
            "signals": sentiment_content.get("recommendations", []) if isinstance(sentiment_content.get("recommendations", []), list) else [],
            "average_rating": sentiment_content.get("average_rating", 0),
            "next_generation_constraints": sentiment_content.get("next_generation_constraints", []),
            "sentiment_report_path": sentiment.get("path", ""),
            "backflow_plan_path": backflow.get("path", ""),
            "feedback_asset_paths": feedback_asset_paths,
            "release_package_path": str(release_package_path or ""),
            "mkaos_weight_updates": mkaos_updates,
            "revision_task_proposals": backflow.get("proposals", []),
            "human_gate": {"required": require_human_gate, "status": "waiting" if require_human_gate else "not_required"},
            "status": "waiting_human" if require_human_gate else "ready",
            "created_at": utc_now(),
        },
        metadata={"project_id": resolved_project_id or "", "workspace_path": workspace or "", "workflow": "publish-feedback-loop"},
        references=filter_project_safe_references(
            storage,
            resolved_project_id or "",
            _dedupe([str(release_package_path or ""), sentiment.get("path", ""), backflow.get("path", ""), *feedback_asset_paths]),
        ),
    )
    result = _write(storage, insight)
    return {
        "status": insight.content["status"],
        "path": result["path"],
        "asset": result["asset"],
        "sentiment_report_path": sentiment.get("path", ""),
        "backflow_plan_path": backflow.get("path", ""),
        "mkaos_weight_update_count": len(mkaos_updates),
        "revision_task_proposal_count": len(backflow.get("proposals", [])),
    }


def apply_feedback_strategy_to_workspace(
    storage: LocalStorage,
    report_path: str | Path,
    *,
    workspace_path: str | None = None,
) -> dict[str, Any]:
    report_file = resolve_path(storage.root, report_path)
    report = storage.read_asset(report_file)
    if report.type != "reader_sentiment_report":
        raise ValueError("report_path must point to a reader_sentiment_report asset")
    project = project_scope_from_asset(storage, report, input_path=report_file, workspace_path=workspace_path)
    workspace = str(project.get("workspace_path") or workspace_path or "")
    if not workspace:
        raise ValueError("workspace_path is required to apply feedback strategy")
    workspace_file = resolve_path(storage.root, workspace)
    data = storage.read_json(workspace_file)
    if not isinstance(data, dict) or data.get("type") != "project_workspace_state":
        raise ValueError("workspace_path must point to a project_workspace_state asset")
    with AgentExecutionContext(
        storage,
        agent_key="feedback",
        skill="reader-feedback",
        operation="apply-feedback-strategy-to-workspace",
        input_assets=[report_file, workspace_file],
        output_types=["project_workspace_state"],
        workspace_path=workspace,
        sla_seconds=300,
    ) as run:
        run.guard("read_asset")
        run.guard("update_project_workspace", "project_workspace_state")
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        memory = content.get("memory", {}) if isinstance(content.get("memory", {}), dict) else {}
        strategy = report.content.get("next_chapter_strategy", {}) if isinstance(report.content.get("next_chapter_strategy", {}), dict) else {}
        memory["reader_feedback"] = {
            "latest_report_id": report.id,
            "latest_report_path": _display_path(storage.root, report_file),
            "follow_read_risk": report.content.get("follow_read_risk", {}),
            "character_heat": report.content.get("character_heat", []),
            "next_chapter_strategy": strategy,
            "applied_at": utc_now(),
        }
        content["memory"] = memory
        open_issues = content.get("open_issues", []) if isinstance(content.get("open_issues", []), list) else []
        risk_level = str((report.content.get("follow_read_risk", {}) if isinstance(report.content.get("follow_read_risk", {}), dict) else {}).get("level", "unknown"))
        if risk_level in {"medium", "high"}:
            open_issues.append(
                {
                    "kind": "reader_retention_risk",
                    "status": "open",
                    "severity": risk_level,
                    "source_report_id": report.id,
                    "source_report_path": _display_path(storage.root, report_file),
                    "message": strategy.get("primary_strategy", "repair reader retention pressure"),
                    "created_at": utc_now(),
                }
            )
        content["open_issues"] = _dedupe_issue_rows(open_issues)
        content["feedback_constraints"] = strategy.get("constraints", report.content.get("next_generation_constraints", []))
        content["review_rubric_feedback_constraints"] = [
            f"reader feedback: {item}"
            for item in _dedupe([str(item) for item in content.get("feedback_constraints", []) if str(item).strip()])
        ]
        data["content"] = content
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        metadata["last_feedback_strategy_report_path"] = _display_path(storage.root, report_file)
        data["metadata"] = metadata
        data["updated_at"] = utc_now()
        errors = validate_common_fields(data)
        if errors:
            raise ValueError("; ".join(errors))
        storage.write_json(workspace_file, data)
        run.guard("update_production_feedback_constraints", "outline")
        run.guard("update_production_feedback_constraints", "chapter_plan")
        updated_assets = _apply_feedback_strategy_to_recent_assets(storage, project.get("project_id", ""), workspace, report, _display_path(storage.root, report_file), strategy)
        run.succeed(output_assets=[_display_path(storage.root, workspace_file), *updated_assets])
        return {
            "path": _display_path(storage.root, workspace_file),
            "workspace_path": _display_path(storage.root, workspace_file),
            "asset": data,
            "applied_report_path": _display_path(storage.root, report_file),
            "updated_assets": updated_assets,
        }


def average_rating(rows: list[dict[str, str]]) -> float:
    values: list[float] = []
    for row in rows:
        try:
            values.append(float(row.get("rating", "")))
        except ValueError:
            continue
    return round(sum(values) / len(values), 2) if values else 0.0


def build_chapter_trends(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    grouped: dict[int, list[dict[str, str]]] = {}
    for row in rows:
        chapter = _chapter_number(row.get("chapter", ""))
        if chapter is None:
            continue
        grouped.setdefault(chapter, []).append(row)

    trends: list[dict[str, Any]] = []
    previous_rating: float | None = None
    for chapter in sorted(grouped):
        chapter_rows = grouped[chapter]
        rating = average_rating(chapter_rows)
        comments = [row.get("comment", "") for row in chapter_rows if row.get("comment", "").strip()]
        delta = round(rating - previous_rating, 2) if previous_rating is not None else 0.0
        trends.append(
            {
                "chapter": chapter,
                "average_rating": rating,
                "rating_delta": delta,
                "comment_count": len(comments),
                "positive_signals": _keyword_hits(comments, POSITIVE_KEYWORDS),
                "negative_signals": _keyword_hits(comments, NEGATIVE_KEYWORDS),
            }
        )
        previous_rating = rating
    return trends


def assess_retention_risk(chapter_trends: list[dict[str, Any]], rows: list[dict[str, str]]) -> dict[str, Any]:
    if not chapter_trends:
        return {"level": "unknown", "score": 0.0, "reasons": ["no chapter feedback"], "at_risk_chapters": []}
    at_risk_chapters: list[int] = []
    reasons: list[str] = []
    risk_score = 0.0
    for trend in chapter_trends:
        chapter = int(trend["chapter"])
        rating = float(trend["average_rating"])
        delta = float(trend["rating_delta"])
        negative_count = sum(trend["negative_signals"].values())
        if rating < 3.5 or delta <= -0.75 or negative_count >= 2:
            at_risk_chapters.append(chapter)
            reasons.append(f"chapter {chapter} shows rating/drop/negative signal risk")
        if rating < 3.5:
            risk_score += 1.0
        if delta <= -0.75:
            risk_score += 1.0
        if negative_count >= 2:
            risk_score += 0.75
    low_rating_rows = [row for row in rows if _rating(row) is not None and float(_rating(row) or 0) <= 2.0]
    if low_rating_rows:
        reasons.append("one or more readers rated a chapter at 2 or below")
        risk_score += min(2.0, len(low_rating_rows) * 0.5)
    level = "high" if len(at_risk_chapters) >= 2 or len(low_rating_rows) >= 2 else "medium" if at_risk_chapters else "low"
    return {
        "level": level,
        "score": round(risk_score, 2),
        "reasons": reasons or ["ratings and comments are stable"],
        "at_risk_chapters": at_risk_chapters,
    }


def build_trend_metrics(chapter_trends: list[dict[str, Any]], rows: list[dict[str, str]]) -> dict[str, Any]:
    ratings = [float(trend["average_rating"]) for trend in chapter_trends]
    chapters = [float(trend["chapter"]) for trend in chapter_trends]
    row_ratings = [value for value in (_rating(row) for row in rows) if value is not None]
    return {
        "rating_slope": _linear_slope(chapters, ratings),
        "rating_volatility": _standard_deviation(ratings),
        "low_rating_ratio": round(
            len([rating for rating in row_ratings if rating <= 2.0]) / len(row_ratings),
            4,
        )
        if row_ratings
        else 0.0,
        "chapter_count": len(chapter_trends),
        "row_count": len(rows),
        "confidence": _feedback_confidence(len(rows), len(chapter_trends)),
    }


def mine_sentiment_signals(rows: list[dict[str, str]]) -> dict[str, Any]:
    comments = [row.get("comment", "") for row in rows if row.get("comment", "").strip()]
    positive = _keyword_hits(comments, POSITIVE_KEYWORDS)
    negative = _keyword_hits(comments, NEGATIVE_KEYWORDS)
    signals: list[str] = []
    if positive.get("hook", 0) or positive.get("suspense", 0):
        signals.append("reader noticed hook or suspense")
    if negative.get("motive", 0) or negative.get("confused", 0):
        signals.append("motivation or clarity pressure should increase")
    if negative.get("slow", 0):
        signals.append("pacing may be too slow")
    if negative.get("drop", 0):
        signals.append("explicit drop-risk language detected")
    if not signals:
        signals.append("feedback volume is low or neutral")
    return {"signals": signals, "positive_keywords": positive, "negative_keywords": negative}


def build_plot_adjustment_plan(
    chapter_trends: list[dict[str, Any]],
    retention_risk: dict[str, Any],
    sentiment_signals: dict[str, Any],
    trend_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    trend_metrics = trend_metrics or {}
    constraints: list[str] = []
    actions: list[str] = []
    if retention_risk.get("level") in {"medium", "high"}:
        constraints.append("open the next chapter with a concrete unresolved obligation")
        actions.append("repair at-risk chapter handoff before expanding side plots")
    if float(trend_metrics.get("rating_slope", 0.0)) <= -0.5:
        constraints.append("treat the next chapter as a retention-repair chapter, not a lore-expansion chapter")
        actions.append("front-load conflict, choice cost, and visible payoff in the next chapter")
    if float(trend_metrics.get("rating_volatility", 0.0)) >= 1.0:
        constraints.append("stabilize chapter promise delivery before adding new plot branches")
    if sentiment_signals["negative_keywords"].get("motive", 0):
        constraints.append("make protagonist motivation pressure explicit by beat 2")
        actions.append("add one choice-cost beat tied to the protagonist motive")
    if sentiment_signals["negative_keywords"].get("slow", 0):
        constraints.append("reduce exposition and increase scene-level conflict density")
        actions.append("replace one explanation beat with action or decision")
    if sentiment_signals["positive_keywords"].get("hook", 0):
        constraints.append("preserve visible chapter-end hook clarity")
    if not constraints:
        constraints.append("preserve current hook clarity and monitor next feedback batch")
    trend_direction = _trend_direction(chapter_trends)
    return {
        "trend_direction": trend_direction,
        "next_generation_constraints": _dedupe(constraints),
        "recommended_actions": _dedupe(actions or ["continue current arc and collect more chapter feedback"]),
    }


def _feedback_rows(storage: LocalStorage, primary_id: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in storage.list_json("feedback"):
        if not _is_reader_feedback(storage, path):
            continue
        asset = storage.read_asset(path)
        rows = _merge_rows(rows, asset.content.get("rows", []))
    if rows:
        return rows
    primary = storage.read_asset(storage.latest("feedback"))
    return _merge_rows([], primary.content.get("rows", [])) if primary.id == primary_id else []


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows.append({str(key): str(value) for key, value in dict(row).items()})
    return rows


def _selected_feedback_assets(storage: LocalStorage, feedback_paths: list[str | Path], project_id: str | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    candidates: list[Path] = []
    for item in feedback_paths:
        candidates.append(resolve_path(storage.root, item))
    if not candidates:
        candidates = list(reversed(storage.list_json("feedback")))
    for path in candidates:
        data = storage.read_json(path)
        if not isinstance(data, dict) or data.get("type") != "reader_feedback":
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if project_id and metadata.get("project_id") != project_id:
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        rows.append(
            {
                "path": _display_path(storage.root, path),
                "id": data.get("id", ""),
                "content": content,
                "metadata": metadata,
            }
        )
    return rows


def _sentiment_distribution(rows: list[dict[str, str]]) -> dict[str, int]:
    distribution = {"positive": 0, "neutral": 0, "negative": 0}
    for row in rows:
        comment = row.get("comment", "")
        positive = sum(comment.lower().count(term) for terms in POSITIVE_KEYWORDS.values() for term in terms)
        negative = sum(comment.lower().count(term) for terms in NEGATIVE_KEYWORDS.values() for term in terms)
        rating = _rating(row)
        if rating is not None and rating >= 4:
            positive += 1
        if rating is not None and rating <= 2:
            negative += 1
        if positive > negative:
            distribution["positive"] += 1
        elif negative > positive:
            distribution["negative"] += 1
        else:
            distribution["neutral"] += 1
    return distribution


def _feedback_clusters(signals: dict[str, Any], distribution: dict[str, int], rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    clusters: list[dict[str, Any]] = []
    for label, count in signals.get("positive_keywords", {}).items():
        if count:
            clusters.append({"label": label, "polarity": "positive", "count": int(count), "evidence": "keyword and rating aggregate"})
    for label, count in signals.get("negative_keywords", {}).items():
        if count:
            clusters.append({"label": label, "polarity": "negative", "count": int(count), "evidence": "keyword and rating aggregate"})
    if not clusters:
        clusters.append({"label": "low_signal", "polarity": "neutral", "count": len(rows), "evidence": "insufficient strong keyword signal"})
    clusters.append({"label": "overall_positive", "polarity": "positive", "count": distribution["positive"], "evidence": "row sentiment classification"})
    clusters.append({"label": "overall_negative", "polarity": "negative", "count": distribution["negative"], "evidence": "row sentiment classification"})
    return [cluster for cluster in clusters if int(cluster.get("count", 0)) > 0]


def _reader_expectations(signals: dict[str, Any], retention_risk: dict[str, Any]) -> list[str]:
    expectations = []
    if signals["positive_keywords"].get("hook", 0) or signals["positive_keywords"].get("suspense", 0):
        expectations.append("keep chapter-end hook explicit and concrete")
    if retention_risk.get("level") in {"medium", "high"}:
        expectations.append("repair retention pressure before expanding secondary lore")
    if signals["negative_keywords"].get("motive", 0):
        expectations.append("make protagonist motive and choice cost visible earlier")
    if signals["negative_keywords"].get("slow", 0):
        expectations.append("increase scene conflict density and reduce exposition")
    return expectations or ["collect more feedback and preserve current chapter promise"]


def _character_heat(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for row in rows:
        explicit = row.get("character") or row.get("角色") or row.get("role")
        candidates = [explicit] if explicit else []
        comment = row.get("comment", "")
        for marker in ["林乔", "主角", "女主", "男主", "反派", "师父", "妹妹", "队友"]:
            if marker in comment:
                candidates.append(marker)
        for candidate in candidates:
            name = str(candidate or "").strip()
            if not name:
                continue
            counts[name] = counts.get(name, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    return [{"character": name, "mentions": count, "heat": min(100, count * 20)} for name, count in ranked[:12]]


def _follow_read_risk(distribution: dict[str, int], trend_metrics: dict[str, Any], retention_risk: dict[str, Any]) -> dict[str, Any]:
    negative = int(distribution.get("negative", 0))
    positive = int(distribution.get("positive", 0))
    total = max(1, sum(int(value) for value in distribution.values()))
    negative_ratio = round(negative / total, 4)
    score = float(retention_risk.get("score", 0)) + negative_ratio * 4
    if float(trend_metrics.get("rating_slope", 0)) < -0.25:
        score += 1
    if positive > negative and score > 0:
        score -= 0.5
    level = "high" if score >= 3 else "medium" if score >= 1.5 else "low"
    return {
        "level": level,
        "score": round(max(0.0, score), 2),
        "negative_ratio": negative_ratio,
        "rating_slope": trend_metrics.get("rating_slope", 0),
        "reasons": retention_risk.get("reasons", []),
    }


def _next_chapter_strategy(adjustment_plan: dict[str, Any], follow_read_risk: dict[str, Any], character_heat: list[dict[str, Any]]) -> dict[str, Any]:
    heated = character_heat[0]["character"] if character_heat else ""
    constraints = list(adjustment_plan.get("next_generation_constraints", []))
    actions = list(adjustment_plan.get("recommended_actions", []))
    if heated:
        constraints.append(f"give {heated} a visible pressure or payoff beat")
    if follow_read_risk.get("level") in {"medium", "high"}:
        actions.insert(0, "open with unresolved obligation, then deliver one concrete payoff before adding new setup")
    return {
        "primary_strategy": actions[0] if actions else "continue current arc and collect feedback",
        "constraints": _dedupe([str(item) for item in constraints]),
        "actions": _dedupe([str(item) for item in actions]),
        "focus_character": heated,
        "risk_level": follow_read_risk.get("level", "unknown"),
    }


def _feedback_mkaos_delta(sentiment_content: dict[str, Any]) -> float:
    average = sentiment_content.get("average_rating", 0)
    try:
        average_rating = float(average or 0)
    except (TypeError, ValueError):
        average_rating = 0.0
    follow = sentiment_content.get("follow_read_risk", {}) if isinstance(sentiment_content.get("follow_read_risk", {}), dict) else {}
    level = str(follow.get("level") or "").lower()
    if level == "high" or (average_rating and average_rating < 3.0):
        return -0.1
    if level == "medium" or (average_rating and average_rating < 3.8):
        return -0.04
    return 0.03


def _cluster_labels(clusters: list[dict[str, Any]], *, polarity: str) -> list[str]:
    return [str(cluster.get("label", "")) for cluster in clusters if cluster.get("polarity") == polarity and cluster.get("label")]


def _dedupe_issue_rows(rows: list[Any]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    result: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = (str(row.get("kind", "")), str(row.get("source_report_id", "")), str(row.get("message", "")))
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def _apply_feedback_strategy_to_recent_assets(
    storage: LocalStorage,
    project_id: str,
    workspace_path: str,
    report: Any,
    report_path: str,
    strategy: dict[str, Any],
    *,
    limit_per_type: int = 6,
) -> list[str]:
    constraints = _dedupe([str(item) for item in strategy.get("constraints", []) if str(item).strip()])
    if strategy.get("primary_strategy"):
        constraints.insert(0, f"reader feedback strategy: {strategy.get('primary_strategy')}")
    refs = _dedupe([report.id, report_path, workspace_path])
    updated: list[str] = []
    for category, asset_type in [("outlines", "outline"), ("chapter_plans", "chapter_plan")]:
        count = 0
        for path in reversed(storage.list_json(category)):
            if count >= limit_per_type:
                break
            try:
                data = storage.read_json(path)
            except Exception:
                continue
            if not isinstance(data, dict) or data.get("type") != asset_type:
                continue
            metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
            if project_id and str(metadata.get("project_id", "")) != project_id:
                continue
            content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
            existing = content.get("feedback_constraints", []) if isinstance(content.get("feedback_constraints", []), list) else []
            content["feedback_constraints"] = _dedupe([*[str(item) for item in existing], *constraints])
            content["reader_feedback_strategy"] = {
                "source_report_id": report.id,
                "source_report_path": report_path,
                "primary_strategy": strategy.get("primary_strategy", ""),
                "constraints": constraints,
                "risk_level": strategy.get("risk_level", ""),
                "focus_character": strategy.get("focus_character", ""),
                "applied_at": utc_now(),
            }
            data["content"] = content
            references = data.get("references", []) if isinstance(data.get("references", []), list) else []
            data["references"] = _dedupe([*[str(item) for item in references], *[str(item) for item in refs if str(item).strip()]])
            metadata["feedback_strategy_report_id"] = report.id
            metadata["feedback_strategy_applied_at"] = utc_now()
            data["metadata"] = metadata
            data["updated_at"] = utc_now()
            errors = validate_common_fields(data)
            if errors:
                raise ValueError("; ".join(errors))
            storage.write_json(path, data)
            updated.append(_display_path(storage.root, path))
            count += 1
    return updated


def _first_workspace(feedback_assets: list[dict[str, Any]]) -> str:
    for item in feedback_assets:
        workspace = str(item.get("metadata", {}).get("workspace_path", ""))
        if workspace:
            return workspace
    return ""


def _feedback_recommendation(content: dict[str, Any]) -> str:
    if isinstance(content.get("retention_risk"), dict):
        level = content["retention_risk"].get("level", "unknown")
        return "repair_retention" if level in {"medium", "high"} else "monitor"
    if isinstance(content.get("recommendations"), list) and content["recommendations"]:
        return str(content["recommendations"][0])
    if isinstance(content.get("next_generation_constraints"), list) and content["next_generation_constraints"]:
        return str(content["next_generation_constraints"][0])
    return ""


def _read_metrics(rows: list[dict[str, str]]) -> dict[str, Any]:
    views = [_numeric(row, "views", "view_count", "曝光", "阅读曝光") for row in rows]
    reads = [_numeric(row, "reads", "read_count", "阅读", "有效阅读") for row in rows]
    completions = [_numeric(row, "completion_rate", "completion", "完读率") for row in rows]
    completion_rate = _average([_normalize_rate(value) for value in completions if value > 0])
    return {
        "total_views": int(sum(views)),
        "total_reads": int(sum(reads)),
        "read_through_rate": round(sum(reads) / max(1.0, sum(views)), 4) if views else 0.0,
        "average_completion_rate": completion_rate,
        "chapter_count": len({_chapter_number(row.get("chapter", "")) for row in rows if _chapter_number(row.get("chapter", "")) is not None}),
    }


def _engagement_metrics(rows: list[dict[str, str]], distribution: dict[str, int], trend_metrics: dict[str, Any]) -> dict[str, Any]:
    favorites = sum(_numeric(row, "favorites", "favorite", "收藏") for row in rows)
    collections = sum(_numeric(row, "collections", "bookmark", "bookmarks", "追书", "书架") for row in rows)
    comments = len([row for row in rows if str(row.get("comment", "")).strip()])
    total_sentiment = max(1, sum(int(value) for value in distribution.values()))
    return {
        "favorites": int(favorites),
        "collections": int(collections),
        "comment_count": comments,
        "comment_rate": round(comments / max(1, len(rows)), 4),
        "positive_ratio": round(distribution.get("positive", 0) / total_sentiment, 4),
        "negative_ratio": round(distribution.get("negative", 0) / total_sentiment, 4),
        "rating_slope": trend_metrics.get("rating_slope", 0),
        "rating_volatility": trend_metrics.get("rating_volatility", 0),
    }


def _chapter_dropoffs(rows: list[dict[str, str]], chapter_trends: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[int, list[dict[str, str]]] = {}
    for row in rows:
        chapter = _chapter_number(row.get("chapter", ""))
        if chapter is not None:
            grouped.setdefault(chapter, []).append(row)
    results: list[dict[str, Any]] = []
    previous_reads: float | None = None
    trend_by_chapter = {int(item["chapter"]): item for item in chapter_trends}
    for chapter in sorted(grouped):
        chapter_rows = grouped[chapter]
        reads = sum(_numeric(row, "reads", "read_count", "阅读", "有效阅读") for row in chapter_rows)
        explicit_drop = sum(1 for row in chapter_rows if _contains_drop_signal(row))
        drop_rate = round((previous_reads - reads) / max(1.0, previous_reads), 4) if previous_reads and reads < previous_reads else 0.0
        trend = trend_by_chapter.get(chapter, {})
        risk = "high" if drop_rate >= 0.35 or explicit_drop >= 3 else "medium" if drop_rate >= 0.18 or explicit_drop else "low"
        results.append(
            {
                "chapter": chapter,
                "reads": int(reads),
                "drop_rate": drop_rate,
                "explicit_drop_signals": explicit_drop,
                "average_rating": trend.get("average_rating", 0),
                "risk": risk,
            }
        )
        previous_reads = reads or previous_reads
    return results


def _operational_recommendations(
    read_metrics: dict[str, Any],
    engagement_metrics: dict[str, Any],
    follow_risk: dict[str, Any],
    dropoffs: list[dict[str, Any]],
    heat: list[dict[str, Any]],
) -> list[str]:
    recommendations: list[str] = []
    if follow_risk.get("level") in {"medium", "high"}:
        recommendations.append("treat the next chapter as retention repair before expanding new lore")
    if read_metrics.get("average_completion_rate", 0) and float(read_metrics.get("average_completion_rate", 0)) < 0.55:
        recommendations.append("shorten exposition blocks and move payoff earlier in the chapter")
    high_dropoffs = [item for item in dropoffs if item.get("risk") == "high"]
    if high_dropoffs:
        recommendations.append(f"review chapter {high_dropoffs[0].get('chapter')} as the current strongest drop-off point")
    if engagement_metrics.get("negative_ratio", 0) > 0.35:
        recommendations.append("run chapter audit with reader toxicity and motivation clarity as required dimensions")
    if heat:
        recommendations.append(f"preserve visible pressure or payoff for high-heat character {heat[0].get('character')}")
    return _dedupe(recommendations or ["collect more operational feedback before changing the outline"])


def _reader_simulation_source(
    storage: LocalStorage,
    *,
    draft_path: str | Path | None,
    chapter_text: str | None,
) -> dict[str, Any]:
    if draft_path:
        path = resolve_path(storage.root, draft_path)
        data = storage.read_json(path)
        if not isinstance(data, dict):
            raise ValueError("draft_path must point to a JSON asset")
        asset_type = data.get("type")
        if asset_type in {"source_document", "source_chunk"}:
            raise ValueError("reader simulation must not use source_document or source_chunk raw text")
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        text = str(content.get("text") or content.get("chapter_text") or content.get("draft") or "")
        return {
            "path": _display_path(storage.root, path),
            "asset": data,
            "text": text,
            "chapter": content.get("chapter"),
        }
    return {"path": "", "asset": None, "text": str(chapter_text or ""), "chapter": None}


def _simulate_reader_persona(persona: dict[str, Any], text: str, *, platform: str) -> dict[str, Any]:
    positive_hits = _text_keyword_count(text, persona.get("positive_keywords", []))
    negative_hits = _text_keyword_count(text, persona.get("negative_keywords", []))
    length = len(text.strip())
    length_penalty = 0
    if length < 450:
        length_penalty = 8
    elif length > 6500:
        length_penalty = 6
    structure_bonus = 4 if any(term in text for term in ["但是", "突然", "然而", "没想到", "与此同时", "决定"]) else 0
    hook_bonus = 5 if any(term in text[-180:] for term in ["？", "!", "！", "真相", "下一步", "决定", "门外", "来人"]) else 0
    platform_bonus = 4 if _platform_persona_match(platform, str(persona.get("persona_id", ""))) else 0
    score = _clamp(58 + positive_hits * 5 - negative_hits * 7 - length_penalty + structure_bonus + hook_bonus + platform_bonus, 0, 100)
    risk = _risk_from_score(score)
    focus = persona.get("focus", []) if isinstance(persona.get("focus"), list) else []
    gap = "" if score >= 78 else f"{persona.get('gap_label', 'reader gap')}: {focus[0] if focus else 'reader motivation'} needs clearer payoff"
    suggestions = _persona_revision_suggestions(persona, score, risk)
    return {
        "persona_id": persona.get("persona_id", ""),
        "persona_name": persona.get("name", ""),
        "focus": focus,
        "predicted_score": score,
        "dropout_risk": risk,
        "follow_read_motivation": _follow_read_motivation(persona, score),
        "pleasure_gap": gap,
        "next_chapter_expectation": _next_expectation_for_persona(persona, platform),
        "revision_suggestions": suggestions,
        "signals": {
            "positive_keyword_hits": positive_hits,
            "negative_keyword_hits": negative_hits,
            "length": length,
            "structure_bonus": structure_bonus,
            "hook_bonus": hook_bonus,
            "platform_bonus": platform_bonus,
        },
    }


def _aggregate_reader_simulation(personas: list[dict[str, Any]]) -> dict[str, Any]:
    scores = [float(item.get("predicted_score", 0)) for item in personas]
    average = round(sum(scores) / len(scores), 2) if scores else 0.0
    risk_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    risk = max((str(item.get("dropout_risk", "unknown")) for item in personas), key=lambda value: risk_order.get(value, -1), default="unknown")
    gaps = _dedupe([str(item.get("pleasure_gap", "")) for item in personas if str(item.get("pleasure_gap", "")).strip()])
    expectations = _dedupe([str(item.get("next_chapter_expectation", "")) for item in personas if str(item.get("next_chapter_expectation", "")).strip()])
    suggestions = _dedupe([str(suggestion) for item in personas for suggestion in item.get("revision_suggestions", []) if str(suggestion).strip()])
    return {
        "predicted_score": average,
        "dropout_risk": risk,
        "reader_count": len(personas),
        "pleasure_gaps": gaps[:8],
        "next_chapter_expectations": expectations[:8],
        "revision_suggestions": suggestions[:10],
        "recommendation": "block release and revise" if risk in {"high", "critical"} else "revise before publish" if risk == "medium" else "ready for gate review",
    }


def _normalize_real_feedback_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    comments = _normalize_comments(metrics.get("comments", []))
    negative_keywords = [str(item).strip() for item in metrics.get("negative_keywords", []) if str(item).strip()] if isinstance(metrics.get("negative_keywords", []), list) else []
    drop_points = _normalize_drop_points(metrics.get("chapter_drop_points", metrics.get("drop_points", [])))
    return {
        "completion_rate": _normalize_rate(_metric_float(metrics, "completion_rate", "read_completion_rate", "finish_rate")),
        "follow_read_rate": _normalize_rate(_metric_float(metrics, "follow_read_rate", "retention_rate", "next_chapter_rate")),
        "comment_count": int(_metric_float(metrics, "comment_count", "comments_count") or len(comments)),
        "favorites": int(_metric_float(metrics, "favorites", "favorite_count", "收藏")),
        "bookshelf_adds": int(_metric_float(metrics, "bookshelf_adds", "bookshelf_add_count", "加书架")),
        "reward_count": int(_metric_float(metrics, "reward_count", "rewards", "打赏")),
        "reward_amount": round(_metric_float(metrics, "reward_amount", "reward_total"), 2),
        "reads": int(_metric_float(metrics, "reads", "read_count", "阅读")),
        "average_rating": round(_metric_float(metrics, "average_rating", "rating"), 2),
        "comments": comments,
        "negative_keywords": negative_keywords,
        "chapter_drop_points": drop_points,
        "character_mentions": metrics.get("character_mentions", {}),
        "raw_metric_keys": sorted(str(key) for key in metrics.keys()),
    }


def _real_feedback_signals(normalized: dict[str, Any]) -> dict[str, Any]:
    comments = normalized.get("comments", []) if isinstance(normalized.get("comments", []), list) else []
    comment_text = "\n".join(str(item) for item in comments)
    negative_keywords = normalized.get("negative_keywords", []) if isinstance(normalized.get("negative_keywords", []), list) else []
    negative_hits = _text_keyword_count(comment_text, [*negative_keywords, *[term for terms in NEGATIVE_KEYWORDS.values() for term in terms]])
    negative_ratio = round(min(1.0, negative_hits / max(1, len(comments) or 1)), 4)
    labels: list[str] = []
    if normalized.get("completion_rate", 0) and normalized.get("completion_rate", 0) < 0.55:
        labels.append("completion_rate_low")
    if normalized.get("follow_read_rate", 0) and normalized.get("follow_read_rate", 0) < 0.45:
        labels.append("follow_read_rate_low")
    if negative_keywords or negative_ratio >= 0.25:
        labels.append("negative_comment_keywords")
    high_drop_points = [point for point in normalized.get("chapter_drop_points", []) if point.get("risk") in {"high", "critical"} or point.get("drop_rate", 0) >= 0.3]
    if high_drop_points:
        labels.append("chapter_drop_point")
    if normalized.get("bookshelf_adds", 0) or normalized.get("favorites", 0):
        labels.append("collection_signal")
    risk_score = 0
    risk_score += 30 if "completion_rate_low" in labels else 0
    risk_score += 28 if "follow_read_rate_low" in labels else 0
    risk_score += min(24, int(negative_ratio * 60))
    risk_score += 18 if high_drop_points else 0
    risk_score -= 8 if "collection_signal" in labels else 0
    risk_level = "critical" if risk_score >= 78 else "high" if risk_score >= 55 else "medium" if risk_score >= 30 else "low"
    recommendations = _dedupe(
        [
            "repair chapter drop-off before widening plot scope" if high_drop_points else "",
            "move payoff and conflict earlier in the next chapter" if "completion_rate_low" in labels else "",
            "strengthen next-chapter promise and paid value" if "follow_read_rate_low" in labels else "",
            "update review rules with reader toxicity and comprehension checks" if "negative_comment_keywords" in labels else "",
            "preserve the current topic promise while tuning rhythm" if "collection_signal" in labels else "",
        ]
    )
    return {
        "labels": labels or ["stable_feedback_signal"],
        "risk_score": _clamp(risk_score, 0, 100),
        "risk_level": risk_level,
        "negative_ratio": negative_ratio,
        "high_drop_points": high_drop_points,
        "recommendations": recommendations or ["keep monitoring real feedback before changing production strategy"],
    }


def _real_feedback_metric_snapshot(
    storage: LocalStorage,
    project_id: str,
    workspace_path: str,
    platform: str,
    normalized: dict[str, Any],
    signals: dict[str, Any],
    *,
    release_package_path: str | Path | None,
) -> OperationalMetricSnapshot:
    snapshot_id = make_id("operational_metric_snapshot", f"{project_id}-{platform}-{utc_now()}")
    return OperationalMetricSnapshot(
        id=snapshot_id,
        title=f"Real feedback metrics {platform}",
        source=str(release_package_path or "real-feedback-import"),
        tags=["feedback", "real-metrics", platform, signals["risk_level"]],
        content={
            "project_id": project_id,
            "snapshot_at": utc_now(),
            "read_metrics": {
                "total_reads": normalized["reads"],
                "completion_rate": normalized["completion_rate"],
                "average_completion_rate": normalized["completion_rate"],
                "follow_read_rate": normalized["follow_read_rate"],
                "average_rating": normalized["average_rating"],
            },
            "engagement_metrics": {
                "comment_count": normalized["comment_count"],
                "favorite_count": normalized["favorites"],
                "bookshelf_add_count": normalized["bookshelf_adds"],
                "reward_count": normalized["reward_count"],
                "reward_amount": normalized["reward_amount"],
                "negative_ratio": signals["negative_ratio"],
            },
            "character_heat": _character_heat_from_real_metrics(normalized),
            "chapter_dropoffs": normalized["chapter_drop_points"],
            "recommendations": signals["recommendations"],
            "follow_read_risk": {"level": signals["risk_level"], "score": signals["risk_score"], "negative_ratio": signals["negative_ratio"]},
            "signal_labels": signals["labels"],
            "row_count": normalized["comment_count"],
        },
        metadata={
            "project_id": project_id,
            "workspace_path": workspace_path,
            "workflow": "real-feedback-metrics",
            "platform": platform,
            "risk_level": signals["risk_level"],
            "use_in_generation_rag": False,
        },
        references=filter_project_safe_references(storage, project_id, [str(release_package_path or ""), workspace_path]),
    )


def _write_feedback_learning_assets(
    storage: LocalStorage,
    *,
    project_id: str,
    workspace_path: str,
    platform: str,
    normalized: dict[str, Any],
    signals: dict[str, Any],
    snapshot_path: str,
) -> dict[str, Any]:
    suffix = f"{project_id}-{platform}-{signals['risk_level']}"
    review_rule_id = make_id("review_rule_pack", f"reader-feedback-{suffix}")
    review_rule = ReviewRulePack(
        id=review_rule_id,
        title=f"Reader feedback review rules {platform}",
        source=snapshot_path,
        tags=["feedback-backflow", "review-rules", platform],
        content={
            "rule_pack_id": review_rule_id,
            "name": f"Reader feedback retention rules {platform}",
            "dimensions": {
                "reader_retention": {"weight": 0.4, "threshold": 75},
                "platform_fit": {"weight": 0.25, "threshold": 72},
                "comprehension": {"weight": 0.2, "threshold": 70},
                "payoff_density": {"weight": 0.15, "threshold": 70},
            },
            "checks": [
                {"id": "completion_repair", "dimension": "reader_retention", "rule": "if completion or follow-read falls below threshold, next chapter must open with conflict and payoff"},
                {"id": "negative_keyword_repair", "dimension": "comprehension", "rule": "negative keywords must map to explicit revision tasks before publish gate"},
                {"id": "drop_point_repair", "dimension": "payoff_density", "rule": "chapter drop points must be reviewed for exposition length and delayed payoff"},
            ],
            "severity_policy": {"critical": ["follow_read_rate_low", "chapter_drop_point"], "high": ["completion_rate_low", "negative_comment_keywords"]},
            "feedback_source": {"metric_snapshot_path": snapshot_path, "signals": signals["labels"]},
        },
        metadata={"project_id": project_id, "workspace_path": workspace_path, "use_in_generation_rag": False},
        references=[snapshot_path],
    )
    topic_id = make_id("topic_seed", f"reader-feedback-topic-{suffix}")
    topic_seed = TopicSeed(
        id=topic_id,
        title=f"Reader feedback topic adjustment {platform}",
        source=snapshot_path,
        tags=["feedback-backflow", "topic-library", platform],
        content={
            "logline": "反馈驱动的题材承诺校准：保留当前卖点，优先修复真实读者掉点。",
            "reader_attraction": signals["recommendations"],
            "differentiation": f"{platform} feedback calibrated promise with completion={normalized['completion_rate']} follow={normalized['follow_read_rate']}",
            "feedback_signals": signals["labels"],
            "metric_snapshot_path": snapshot_path,
        },
        metadata={"project_id": project_id, "workspace_path": workspace_path, "use_in_generation_rag": False},
        references=[snapshot_path],
    )
    character_template = _feedback_writing_template(
        project_id,
        workspace_path,
        platform,
        snapshot_path,
        template_kind="character_feedback_template",
        name="Reader feedback character repair template",
        structure=[
            "identify high-heat characters and weak-motivation complaints",
            "turn negative relationship comments into one concrete motivation repair",
            "carry the repaired motivation into the next chapter scene goal",
        ],
        usage_constraints=["do not overwrite existing character canon without ReviewIssue or RevisionTask", "keep changes project-scoped"],
    )
    rhythm_template = _feedback_writing_template(
        project_id,
        workspace_path,
        platform,
        snapshot_path,
        template_kind="chapter_rhythm_feedback_template",
        name="Reader feedback rhythm repair template",
        structure=[
            "start with conflict or unresolved promise",
            "reduce exposition before the strongest drop point",
            "deliver a visible payoff before adding new lore",
            "end with a next-chapter expectation tied to the platform strategy",
        ],
        usage_constraints=["must not use source_chunk.raw_text", "must pass publish gate after feedback repair"],
    )
    results = {
        "review_rule_pack_path": _write(storage, review_rule)["path"],
        "topic_seed_path": _write(storage, topic_seed)["path"],
        "character_template_path": _write(storage, character_template)["path"],
        "rhythm_template_path": _write(storage, rhythm_template)["path"],
    }
    results["paths"] = list(results.values())
    return results


def _feedback_writing_template(
    project_id: str,
    workspace_path: str,
    platform: str,
    snapshot_path: str,
    *,
    template_kind: str,
    name: str,
    structure: list[str],
    usage_constraints: list[str],
) -> WritingTemplate:
    template_id = make_id("writing_template", f"{template_kind}-{project_id}-{platform}")
    return WritingTemplate(
        id=template_id,
        title=name,
        source=snapshot_path,
        tags=["feedback-backflow", template_kind, platform],
        content={
            "template_id": template_id,
            "name": name,
            "template_kind": template_kind,
            "structure": structure,
            "usage_constraints": usage_constraints,
            "anti_copy_rules": ["feedback assets are operational signals, not source prose", "never copy reader comments into draft prose"],
            "feedback_source": {"metric_snapshot_path": snapshot_path, "platform": platform},
        },
        metadata={
            "project_id": project_id,
            "workspace_path": workspace_path,
            "copyright_boundary": "abstract structure only",
            "use_in_generation_rag": False,
        },
        references=[snapshot_path],
    )


def _apply_real_feedback_mkaos_updates(
    storage: LocalStorage,
    *,
    project_id: str,
    normalized: dict[str, Any],
    signals: dict[str, Any],
    source_path: str,
    enabled: bool,
) -> list[dict[str, Any]]:
    if not enabled:
        return []
    from novel_forge.modules.mkaos import apply_weight_update, list_usage_events

    usage_events = list_usage_events(storage, project_id=project_id, limit=30)
    delta = _feedback_mkaos_delta_from_real_metrics(normalized, signals)
    updates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for event in usage_events:
        content = event.get("content", {}) if isinstance(event.get("content", {}), dict) else {}
        knowledge_id = str(content.get("knowledge_id") or "").strip()
        if not knowledge_id or knowledge_id in seen:
            continue
        seen.add(knowledge_id)
        updates.append(
            apply_weight_update(
                storage,
                {
                    "knowledge_id": knowledge_id,
                    "project_id": project_id,
                    "flow": str(content.get("flow") or "feedback"),
                    "delta": delta,
                    "reason": "real_feedback_backflow",
                    "feedback_paths": [source_path],
                    "signals": signals["labels"],
                },
            )
        )
        if len(updates) >= 8:
            break
    return updates


def _feedback_mkaos_delta_from_real_metrics(normalized: dict[str, Any], signals: dict[str, Any]) -> float:
    risk = str(signals.get("risk_level", "low"))
    if risk == "critical":
        return -0.16
    if risk == "high":
        return -0.1
    if risk == "medium":
        return -0.04
    if normalized.get("completion_rate", 0) >= 0.75 and normalized.get("follow_read_rate", 0) >= 0.6:
        return 0.05
    return 0.02


def _normalize_comments(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    comments: list[str] = []
    for item in value:
        if isinstance(item, dict):
            text = str(item.get("comment") or item.get("text") or item.get("content") or "").strip()
        else:
            text = str(item).strip()
        if text:
            comments.append(text)
    return comments


def _normalize_drop_points(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    points: list[dict[str, Any]] = []
    for index, item in enumerate(value, start=1):
        if isinstance(item, dict):
            drop_rate = _normalize_rate(_metric_float(item, "drop_rate", "dropoff_rate", "流失率"))
            risk = str(item.get("risk") or ("high" if drop_rate >= 0.3 else "medium" if drop_rate >= 0.15 else "low"))
            points.append(
                {
                    "chapter": int(_metric_float(item, "chapter", "chapter_index", "章节") or index),
                    "reads": int(_metric_float(item, "reads", "read_count", "阅读")),
                    "drop_rate": drop_rate,
                    "explicit_drop_signals": int(_metric_float(item, "explicit_drop_signals", "drop_signals") or (1 if drop_rate else 0)),
                    "average_rating": round(_metric_float(item, "average_rating", "rating"), 2),
                    "risk": risk,
                    "reason": str(item.get("reason") or item.get("comment") or ""),
                }
            )
        else:
            points.append({"chapter": index, "reads": 0, "drop_rate": 0.0, "explicit_drop_signals": 1, "average_rating": 0.0, "risk": "medium", "reason": str(item)})
    return points


def _character_heat_from_real_metrics(normalized: dict[str, Any]) -> list[dict[str, Any]]:
    mentions = normalized.get("character_mentions", {})
    rows: list[dict[str, Any]] = []
    if isinstance(mentions, dict):
        for character, count in mentions.items():
            try:
                value = int(count)
            except (TypeError, ValueError):
                value = 0
            if character and value:
                rows.append({"character": str(character), "mentions": value, "heat": value})
    elif isinstance(mentions, list):
        for item in mentions:
            if isinstance(item, dict) and item.get("character"):
                rows.append({"character": str(item.get("character")), "mentions": int(item.get("mentions", 0) or 0), "heat": int(item.get("heat", item.get("mentions", 0)) or 0)})
    return sorted(rows, key=lambda item: item.get("heat", 0), reverse=True)[:20]


def _metric_float(data: dict[str, Any], *keys: str) -> float:
    for key in keys:
        if key not in data:
            continue
        value = data.get(key)
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).replace("%", "").replace(",", "").strip()
        if not text:
            continue
        try:
            return float(text)
        except ValueError:
            continue
    return 0.0


def _text_keyword_count(text: str, keywords: list[str]) -> int:
    lowered = text.lower()
    return sum(lowered.count(str(term).lower()) for term in keywords if str(term).strip())


def _platform_persona_match(platform: str, persona_id: str) -> bool:
    normalized = platform.lower()
    return (
        ("qidian" in normalized or "起点" in platform) and persona_id == "qidian_veteran"
        or ("fanqie" in normalized or "番茄" in platform) and persona_id == "fanqie_reader"
        or ("jinjiang" in normalized or "晋江" in platform) and persona_id == "relationship_reader"
        or ("zhihu" in normalized or "知乎" in platform) and persona_id == "mystery_reader"
        or ("feilu" in normalized or "飞卢" in platform) and persona_id == "shuangwen_reader"
    )


def _persona_revision_suggestions(persona: dict[str, Any], score: float, risk: str) -> list[str]:
    if score >= 82:
        return [f"preserve {persona.get('name', 'reader')} strengths and avoid over-repair"]
    focus = persona.get("focus", []) if isinstance(persona.get("focus"), list) else []
    primary = str(focus[0]) if focus else "reader motivation"
    secondary = str(focus[1]) if len(focus) > 1 else primary
    action = "block and revise" if risk in {"high", "critical"} else "revise locally"
    return [f"{action}: strengthen {primary}", f"add one visible beat for {secondary} before the ending hook"]


def _follow_read_motivation(persona: dict[str, Any], score: float) -> str:
    if score >= 82:
        return f"{persona.get('name', 'reader')} has clear motivation to continue"
    if score >= 68:
        return f"{persona.get('name', 'reader')} may continue if next chapter pays off the current promise"
    return f"{persona.get('name', 'reader')} has weak follow-read motivation without immediate repair"


def _next_expectation_for_persona(persona: dict[str, Any], platform: str) -> str:
    focus = persona.get("focus", []) if isinstance(persona.get("focus"), list) else []
    expected = focus[0] if focus else "payoff"
    return f"next chapter should deliver {expected} for {platform}"


def _risk_from_score(score: float) -> str:
    if score < 45:
        return "critical"
    if score < 62:
        return "high"
    if score < 76:
        return "medium"
    return "low"


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return round(max(minimum, min(maximum, float(value))), 2)


def _numeric(row: dict[str, str], *keys: str) -> float:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        text = str(value).replace("%", "").replace(",", "").strip()
        if not text:
            continue
        try:
            return float(text)
        except ValueError:
            continue
    return 0.0


def _average(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def _normalize_rate(value: float) -> float:
    return round(value / 100, 4) if value > 1 else round(value, 4)


def _contains_drop_signal(row: dict[str, str]) -> bool:
    comment = str(row.get("comment", "")).lower()
    return any(term in comment for term in ["drop", "弃", "不追", "退订", "流失"])


def _write(storage: LocalStorage, asset: Any) -> dict[str, Any]:
    data = asset.to_dict()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset_auto(asset)
    return {"path": _display_path(storage.root, path), "asset": data, "validation": {"ok": True, "errors": []}}


def _record_feedback_span(
    storage: LocalStorage,
    *,
    trace_id: str,
    name: str,
    path: str,
    project_id: str,
    workspace_path: str,
    attributes: dict[str, Any],
) -> None:
    try:
        record_trace_span(
            storage,
            trace_id=trace_id or path,
            span_type="feedback",
            name=name,
            status="succeeded",
            attributes={**attributes, "path": path},
            references=[path],
            project_id=project_id,
            workspace_path=workspace_path,
        )
    except Exception:
        return


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _is_reader_feedback(storage: LocalStorage, path: Path) -> bool:
    try:
        data = storage.read_json(path)
    except Exception:
        return False
    return isinstance(data, dict) and data.get("type") == "reader_feedback"


def _merge_rows(left: Any, right: Any) -> list[dict[str, str]]:
    merged: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for rows in [left, right]:
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            normalized = {str(key): str(value) for key, value in row.items()}
            identity = (
                normalized.get("reader", ""),
                normalized.get("chapter", ""),
                normalized.get("rating", ""),
                normalized.get("comment", ""),
            )
            if identity in seen:
                continue
            seen.add(identity)
            merged.append(normalized)
    return merged


def _chapter_number(value: str) -> int | None:
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def _rating(row: dict[str, str]) -> float | None:
    try:
        return float(row.get("rating", ""))
    except ValueError:
        return None


def _keyword_hits(comments: list[str], keywords: dict[str, list[str]]) -> dict[str, int]:
    joined = "\n".join(comments).lower()
    return {label: sum(joined.count(keyword) for keyword in terms) for label, terms in keywords.items()}


def _trend_direction(chapter_trends: list[dict[str, Any]]) -> str:
    if len(chapter_trends) < 2:
        return "insufficient_data"
    delta = float(chapter_trends[-1]["average_rating"]) - float(chapter_trends[0]["average_rating"])
    if delta >= 0.5:
        return "improving"
    if delta <= -0.5:
        return "declining"
    return "stable"


def _linear_slope(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 2 or len(xs) != len(ys):
        return 0.0
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    denominator = sum((x - x_mean) ** 2 for x in xs)
    if denominator == 0:
        return 0.0
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    return round(numerator / denominator, 4)


def _standard_deviation(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return round(variance**0.5, 4)


def _feedback_confidence(row_count: int, chapter_count: int) -> str:
    if row_count >= 20 and chapter_count >= 5:
        return "high"
    if row_count >= 6 and chapter_count >= 3:
        return "medium"
    if row_count > 0 and chapter_count > 0:
        return "low"
    return "none"


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


POSITIVE_KEYWORDS = {
    "hook": ["hook", "钩子", "悬念", "追读"],
    "suspense": ["suspense", "悬疑", "紧张"],
    "payoff": ["爽", "爽点", "reveal", "反转"],
}

NEGATIVE_KEYWORDS = {
    "motive": ["motive", "motivation", "动机", "压力"],
    "confused": ["confused", "unclear", "疑惑", "看不懂"],
    "slow": ["slow", "拖", "水", "节奏慢"],
    "drop": ["drop", "弃", "弃文", "不追"],
}

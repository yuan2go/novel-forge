from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.agent_runs import AgentExecutionContext
from novel_forge.modules.common import read_previous, resolve_path
from novel_forge.modules.production_context import filter_project_safe_references, project_scope_from_asset
from novel_forge.modules.runtime_ledger import record_trace_span
from novel_forge.schemas import FeedbackImportBatch, FeedbackInsight, OperationalMetricSnapshot, ReaderFeedback, ReaderSentimentReport, validate_common_fields
from novel_forge.storage.local import LocalStorage


FEEDBACK_TYPES = {
    "feedback_import_batch",
    "reader_feedback",
    "feedback_insight",
    "reader_sentiment_report",
    "operational_metric_snapshot",
}


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
                "next_chapter_strategy": content.get("next_chapter_strategy", {}),
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

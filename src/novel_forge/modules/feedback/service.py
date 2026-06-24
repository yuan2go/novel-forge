from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from novel_forge.core.ids import utc_now
from novel_forge.modules.common import read_previous, resolve_path
from novel_forge.schemas import FeedbackInsight, ReaderFeedback
from novel_forge.storage.local import LocalStorage


def import_feedback(storage: LocalStorage, input_path: str) -> Path:
    path = resolve_path(storage.root, input_path)
    if not path.exists():
        raise FileNotFoundError(f"feedback file not found: {path}")
    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows.append(dict(row))
    asset = ReaderFeedback(
        title=path.stem,
        source=str(path),
        tags=["feedback", "reader"],
        content={"rows": rows},
        metadata={"imported_at": utc_now(), "row_count": len(rows)},
    )
    return storage.write_asset("feedback", asset)


def analyze_feedback(storage: LocalStorage, input_path: str | None = None) -> Path:
    feedback = read_previous(storage, "feedback", input_path)
    rows = _feedback_rows(storage, feedback.id)
    if input_path:
        rows = _merge_rows(feedback.content.get("rows", []), rows)
    comments = " ".join(row.get("comment", "") for row in rows)
    chapter_trends = build_chapter_trends(rows)
    retention_risk = assess_retention_risk(chapter_trends, rows)
    sentiment_signals = mine_sentiment_signals(rows)
    adjustment_plan = build_plot_adjustment_plan(chapter_trends, retention_risk, sentiment_signals)
    asset = FeedbackInsight(
        title=f"Insight from {feedback.title}",
        source=feedback.id,
        tags=["feedback", "insight"],
        content={
            "signals": sentiment_signals["signals"],
            "average_rating": average_rating(rows),
            "next_generation_constraints": adjustment_plan["next_generation_constraints"],
            "chapter_trends": chapter_trends,
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
    return storage.write_asset("feedback", asset)


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
        return {"level": "unknown", "reasons": ["no chapter feedback"], "at_risk_chapters": []}
    at_risk_chapters: list[int] = []
    reasons: list[str] = []
    for trend in chapter_trends:
        chapter = int(trend["chapter"])
        rating = float(trend["average_rating"])
        delta = float(trend["rating_delta"])
        negative_count = sum(trend["negative_signals"].values())
        if rating < 3.5 or delta <= -0.75 or negative_count >= 2:
            at_risk_chapters.append(chapter)
            reasons.append(f"chapter {chapter} shows rating/drop/negative signal risk")
    low_rating_rows = [row for row in rows if _rating(row) is not None and float(_rating(row) or 0) <= 2.0]
    if low_rating_rows:
        reasons.append("one or more readers rated a chapter at 2 or below")
    level = "high" if len(at_risk_chapters) >= 2 or len(low_rating_rows) >= 2 else "medium" if at_risk_chapters else "low"
    return {"level": level, "reasons": reasons or ["ratings and comments are stable"], "at_risk_chapters": at_risk_chapters}


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
) -> dict[str, Any]:
    constraints: list[str] = []
    actions: list[str] = []
    if retention_risk.get("level") in {"medium", "high"}:
        constraints.append("open the next chapter with a concrete unresolved obligation")
        actions.append("repair at-risk chapter handoff before expanding side plots")
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

from __future__ import annotations

import re
from itertools import combinations
from pathlib import Path
from typing import Any

from novel_forge.core.constants import DATA_DIRS
from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.common import resolve_path
from novel_forge.modules.review_issue import list_review_issues
from novel_forge.schemas import BookPotentialScore, CrossBookSimilarityReport, PortfolioProject, ResourceAllocationPlan
from novel_forge.storage.local import LocalStorage


def create_portfolio_project(
    storage: LocalStorage,
    *,
    title: str,
    project_ids: list[str],
    portfolio_id: str = "",
    strategy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ids = _clean_ids(project_ids)
    if not ids:
        raise ValueError("project_ids is required")
    resolved_portfolio_id = portfolio_id or make_id("portfolio_project", f"{title}:{','.join(ids)}")
    asset = PortfolioProject(
        id=resolved_portfolio_id,
        title=title or "Portfolio Project",
        tags=["portfolio-os", "portfolio-project"],
        content={
            "portfolio_id": resolved_portfolio_id,
            "title": title or "Portfolio Project",
            "project_ids": ids,
            "book_count": len(ids),
            "status": "active",
            "strategy": strategy or {},
            "lifecycle": {
                "state": "planning",
                "book_level_scheduler_enabled": False,
                "requires_operator_approval_for_parallel_dispatch": True,
            },
            "isolation_contract": _portfolio_isolation_contract(ids),
            "created_at": utc_now(),
        },
        metadata={"project_id": resolved_portfolio_id, "portfolio_os": True, "use_in_generation_rag": False},
        references=[f"project:{project_id}" for project_id in ids],
    )
    path = _write_asset(storage, asset)
    return {"path": path, "asset": storage.read_json(storage.root / path)}


def build_book_potential_scores(
    storage: LocalStorage,
    *,
    portfolio_ref: str | Path = "",
    project_ids: list[str] | None = None,
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    portfolio = _portfolio_from_ref(storage, portfolio_ref)
    ids = _clean_ids(project_ids or portfolio.get("content", {}).get("project_ids", []))
    if not ids:
        raise ValueError("project_ids or portfolio_ref is required")
    score_weights = _score_weights(weights or {})
    score_paths: list[str] = []
    scores: list[dict[str, Any]] = []
    portfolio_id = str(portfolio.get("content", {}).get("portfolio_id") or portfolio.get("id") or "portfolio")
    for project_id in ids:
        evidence = _book_evidence(storage, project_id)
        dimensions = _potential_dimensions(evidence)
        total = round(sum(dimensions[key] * score_weights[key] for key in score_weights), 3)
        score = BookPotentialScore(
            title=f"Book potential score {project_id}",
            source=str(portfolio.get("id") or portfolio_ref or ""),
            tags=["portfolio-os", "book-potential-score", _recommendation(total, evidence)],
            content={
                "score_id": make_id("book_potential_score", f"{project_id}:{total}"),
                "portfolio_id": str(portfolio.get("content", {}).get("portfolio_id") or portfolio.get("id") or ""),
                "project_id": project_id,
                "score_total": total,
                "weights": score_weights,
                "dimensions": dimensions,
                "evidence": evidence,
                "recommendation": _recommendation(total, evidence),
                "isolation_policy": {"memory_scope": "project_id", "context_scope": "project_id", "cross_book_assets_allowed": False},
                "created_at": utc_now(),
            },
            metadata={"project_id": portfolio_id, "book_project_id": project_id, "portfolio_id": portfolio_id, "portfolio_os": True, "use_in_generation_rag": False},
            references=_dedupe([str(portfolio.get("path") or "")]),
        )
        path = _write_asset(storage, score)
        score_paths.append(path)
        scores.append(storage.read_json(storage.root / path))
    return {"score_paths": score_paths, "scores": scores, "portfolio": portfolio}


def build_cross_book_similarity_report(
    storage: LocalStorage,
    *,
    portfolio_ref: str | Path = "",
    project_ids: list[str] | None = None,
    medium_threshold: float = 0.35,
    high_threshold: float = 0.55,
) -> dict[str, Any]:
    portfolio = _portfolio_from_ref(storage, portfolio_ref)
    ids = _clean_ids(project_ids or portfolio.get("content", {}).get("project_ids", []))
    if len(ids) < 2:
        raise ValueError("at least two project_ids are required for cross-book similarity")
    thresholds = _similarity_thresholds(medium_threshold, high_threshold)
    fingerprints = [_project_fingerprint(storage, project_id) for project_id in ids]
    pairs = [_compare_project_fingerprints(left, right, thresholds) for left, right in combinations(fingerprints, 2)]
    high_pairs = [row for row in pairs if row["risk_level"] == "high"]
    medium_pairs = [row for row in pairs if row["risk_level"] == "medium"]
    max_similarity = max((float(row.get("overall_similarity") or 0.0) for row in pairs), default=0.0)
    risk_level = "high" if high_pairs else ("medium" if medium_pairs else "low")
    guard_decision = {
        "status": "blocked" if high_pairs else "passed",
        "risk_level": risk_level,
        "shared_context_allowed": not high_pairs,
        "shared_assets_allowed": not high_pairs,
        "requires_operator_review": bool(high_pairs or medium_pairs),
        "blocking_pair_count": len(high_pairs),
        "medium_pair_count": len(medium_pairs),
        "reason": "high cross-book overlap" if high_pairs else ("medium cross-book overlap requires review" if medium_pairs else "no high-risk overlap detected"),
    }
    portfolio_id = str(portfolio.get("content", {}).get("portfolio_id") or portfolio.get("id") or make_id("portfolio", ",".join(ids)))
    report = CrossBookSimilarityReport(
        title=f"Cross-book similarity report {portfolio.get('title') or portfolio_id}",
        source=str(portfolio.get("id") or portfolio_ref or ""),
        tags=["portfolio-os", "cross-book-similarity", risk_level],
        content={
            "report_id": make_id("cross_book_similarity_report", f"{portfolio_id}:{max_similarity}:{utc_now()}"),
            "portfolio_id": portfolio_id,
            "project_ids": ids,
            "thresholds": thresholds,
            "risk_level": risk_level,
            "max_similarity": round(max_similarity, 4),
            "pair_count": len(pairs),
            "pairwise_similarity": pairs,
            "project_fingerprints": [_redacted_fingerprint(row) for row in fingerprints],
            "guard_decision": guard_decision,
            "generation_context_boundary": {
                "raw_drafts_included": False,
                "raw_reference_sources_included": False,
                "stores_fingerprint_only": True,
                "block_shared_context_when_status_blocked": True,
            },
            "created_at": utc_now(),
        },
        metadata={"project_id": portfolio_id, "portfolio_id": portfolio_id, "portfolio_os": True, "use_in_generation_rag": False},
        references=_dedupe([str(portfolio.get("path") or "")]),
    )
    path = _write_asset(storage, report)
    return {"path": path, "asset": storage.read_json(storage.root / path)}


def build_resource_allocation_plan(
    storage: LocalStorage,
    *,
    portfolio_ref: str | Path = "",
    project_ids: list[str] | None = None,
    provider_budget: float = 0.0,
    max_parallel_books: int = 2,
    daily_chapter_goal: int = 1,
) -> dict[str, Any]:
    score_result = build_book_potential_scores(storage, portfolio_ref=portfolio_ref, project_ids=project_ids)
    scores = score_result["scores"]
    portfolio = score_result["portfolio"]
    ranked = sorted(scores, key=lambda row: float(row.get("content", {}).get("score_total") or 0.0), reverse=True)
    budget = float(provider_budget or 0.0)
    per_book_budget = round(budget / max(1, len(ranked)), 4)
    allocations = []
    for index, score in enumerate(ranked, start=1):
        content = score.get("content", {}) if isinstance(score.get("content", {}), dict) else {}
        evidence = content.get("evidence", {}) if isinstance(content.get("evidence", {}), dict) else {}
        blocked = int(evidence.get("blocking_review_issue_count") or 0) > 0
        allocations.append(
            {
                "rank": index,
                "lane": index if index <= max(1, max_parallel_books) and not blocked else 0,
                "project_id": content.get("project_id", ""),
                "score_total": content.get("score_total", 0.0),
                "recommended_action": "resolve_blocking_review_issues" if blocked else _schedule_action(evidence),
                "daily_chapter_goal": daily_chapter_goal if not blocked else 0,
                "provider_budget_cap": 0.0 if blocked else per_book_budget,
                "memory_scope": "project_id",
                "context_scope": "project_id",
                "blocked": blocked,
                "score_path": score.get("path", ""),
            }
        )
    plan = ResourceAllocationPlan(
        title=f"Portfolio resource allocation {portfolio.get('title') or 'portfolio'}",
        source=str(portfolio.get("id") or ""),
        tags=["portfolio-os", "resource-allocation-plan"],
        content={
            "plan_id": make_id("resource_allocation_plan", f"{portfolio.get('id', '')}:{utc_now()}"),
            "portfolio_id": str(portfolio.get("content", {}).get("portfolio_id") or portfolio.get("id") or ""),
            "status": "ready" if any(not row["blocked"] for row in allocations) else "blocked",
            "provider_budget": budget,
            "per_book_budget": per_book_budget,
            "max_parallel_books": max_parallel_books,
            "daily_chapter_goal": daily_chapter_goal,
            "allocations": allocations,
            "isolation_contract": _portfolio_isolation_contract([str(row["project_id"]) for row in allocations]),
            "cost_quality_rollup": _cost_quality_rollup(scores),
            "dispatch_boundary": {
                "automatic_dispatch": False,
                "requires_operator_approval": True,
                "requires_per_book_context_scope": True,
                "requires_cross_book_similarity_guard_before_shared_assets": True,
            },
            "created_at": utc_now(),
        },
        metadata={"project_id": str(portfolio.get("id") or "portfolio"), "portfolio_os": True, "use_in_generation_rag": False},
        references=_dedupe([str(portfolio.get("path") or ""), *[str(row.get("path") or "") for row in scores]]),
    )
    path = _write_asset(storage, plan)
    return {"path": path, "asset": storage.read_json(storage.root / path), "score_paths": score_result["score_paths"]}


def _book_evidence(storage: LocalStorage, project_id: str) -> dict[str, Any]:
    rows = _project_assets(storage, project_id)
    type_counts = _type_counts(rows)
    blocking = list_review_issues(storage, project_id=project_id or None, blocking=True, limit=500)
    quality_score, quality_path = _latest_quality_score(rows)
    cost = _project_cost(rows)
    return {
        "project_id": project_id,
        "asset_counts": type_counts,
        "chapter_plan_count": type_counts.get("chapter_plan", 0),
        "draft_count": type_counts.get("draft_chapter", 0),
        "review_report_count": type_counts.get("review_report", 0),
        "release_package_count": type_counts.get("release_package", 0),
        "longform_recap_count": type_counts.get("longform_recap_report", 0),
        "blocking_review_issue_count": len(blocking),
        "latest_quality_score": quality_score,
        "model_cost": cost,
        "cost_quality_ratio": round(cost / max(0.01, quality_score), 4) if quality_score else cost,
        "evidence_paths": _dedupe([quality_path, *[str(row.get("path") or "") for row in blocking[:10]]]),
    }


def _project_fingerprint(storage: LocalStorage, project_id: str) -> dict[str, Any]:
    rows = _project_assets(storage, project_id)
    buckets = {"premise": [], "style": [], "mechanism": []}
    evidence_paths: list[str] = []
    type_counts = _type_counts(rows)
    for row in rows:
        asset_type = str(row.get("type") or "")
        if asset_type not in _fingerprint_source_types():
            continue
        content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
        title = str(row.get("title") or "")
        text = _fingerprint_text(content, title=title)
        if not text:
            continue
        if asset_type in {"genre_profile", "genre_strategy_pack", "subgenre_mechanic", "outline", "outline_version", "chapter_plan", "chapter_plan_version"}:
            buckets["premise"].append(text)
            buckets["mechanism"].append(_selected_text(content, ["genre", "subgenre", "mechanic", "beat", "hook", "conflict", "promise", "system", "rule"]))
        if asset_type in {"style_profile", "style_fingerprint", "style_generation_policy", "style_review_rule", "draft_chapter", "draft_version"}:
            buckets["style"].append(_selected_text(content, ["style", "voice", "tone", "rhythm", "sentence", "dialogue", "perspective", "pace", "distance"]))
        if asset_type in {"knowledge_pack", "rule_card", "template_card", "review_rule", "quality_rubric_pack"}:
            buckets["mechanism"].append(text)
        evidence_paths.append(str(row.get("path") or ""))
    return {
        "project_id": project_id,
        "asset_type_counts": type_counts,
        "fingerprint_tokens": {bucket: _top_tokens(" ".join(parts), limit=36) for bucket, parts in buckets.items()},
        "evidence_paths": _dedupe(evidence_paths)[:20],
        "fingerprint_source_count": len(evidence_paths),
    }


def _compare_project_fingerprints(left: dict[str, Any], right: dict[str, Any], thresholds: dict[str, float]) -> dict[str, Any]:
    left_tokens = left.get("fingerprint_tokens", {}) if isinstance(left.get("fingerprint_tokens", {}), dict) else {}
    right_tokens = right.get("fingerprint_tokens", {}) if isinstance(right.get("fingerprint_tokens", {}), dict) else {}
    dimensions: dict[str, dict[str, Any]] = {}
    for key in ["premise", "style", "mechanism"]:
        left_set = set(left_tokens.get(key, []) if isinstance(left_tokens.get(key, []), list) else [])
        right_set = set(right_tokens.get(key, []) if isinstance(right_tokens.get(key, []), list) else [])
        overlap = sorted(left_set.intersection(right_set))[:12]
        dimensions[key] = {
            "similarity": _jaccard(left_set, right_set),
            "overlap_terms": overlap,
            "left_token_count": len(left_set),
            "right_token_count": len(right_set),
        }
    premise = float(dimensions["premise"]["similarity"])
    style = float(dimensions["style"]["similarity"])
    mechanism = float(dimensions["mechanism"]["similarity"])
    overall = round((premise * 0.4) + (style * 0.25) + (mechanism * 0.35), 4)
    strongest = max(dimensions.items(), key=lambda item: float(item[1].get("similarity") or 0.0), default=("premise", {}))
    high_threshold = float(thresholds["high"])
    medium_threshold = float(thresholds["medium"])
    risk_level = "high" if overall >= high_threshold or float(strongest[1].get("similarity") or 0.0) >= high_threshold else ("medium" if overall >= medium_threshold else "low")
    return {
        "left_project_id": left.get("project_id", ""),
        "right_project_id": right.get("project_id", ""),
        "overall_similarity": overall,
        "risk_level": risk_level,
        "strongest_dimension": strongest[0],
        "dimension_scores": dimensions,
        "contamination_guard": {
            "block_shared_context": risk_level == "high",
            "requires_operator_review": risk_level in {"high", "medium"},
            "recommended_action": _similarity_recommendation(risk_level, strongest[0]),
        },
        "evidence_paths": _dedupe([*(left.get("evidence_paths", [])[:6]), *(right.get("evidence_paths", [])[:6])]),
    }


def _potential_dimensions(evidence: dict[str, Any]) -> dict[str, float]:
    plan_count = int(evidence.get("chapter_plan_count") or 0)
    draft_count = int(evidence.get("draft_count") or 0)
    blocking = int(evidence.get("blocking_review_issue_count") or 0)
    quality = float(evidence.get("latest_quality_score") or 0.0)
    release_count = int(evidence.get("release_package_count") or 0)
    recap_count = int(evidence.get("longform_recap_count") or 0)
    return {
        "production_readiness": min(1.0, (plan_count + draft_count + release_count) / 10.0),
        "quality_signal": max(0.0, min(1.0, quality)),
        "risk_clearance": max(0.0, 1.0 - min(1.0, blocking / 5.0)),
        "longform_stability": min(1.0, recap_count / 3.0),
        "cost_efficiency": max(0.0, 1.0 - min(1.0, float(evidence.get("cost_quality_ratio") or 0.0) / 10.0)),
    }


def _score_weights(weights: dict[str, float]) -> dict[str, float]:
    defaults = {"production_readiness": 0.25, "quality_signal": 0.3, "risk_clearance": 0.25, "longform_stability": 0.1, "cost_efficiency": 0.1}
    merged = {key: float(weights.get(key, defaults[key])) for key in defaults}
    total = sum(max(0.0, value) for value in merged.values()) or 1.0
    return {key: round(max(0.0, value) / total, 4) for key, value in merged.items()}


def _similarity_thresholds(medium_threshold: float, high_threshold: float) -> dict[str, float]:
    medium = max(0.0, min(1.0, float(medium_threshold)))
    high = max(medium, min(1.0, float(high_threshold)))
    return {"medium": round(medium, 4), "high": round(high, 4)}


def _fingerprint_source_types() -> set[str]:
    return {
        "genre_profile",
        "subgenre_mechanic",
        "genre_strategy_pack",
        "style_profile",
        "style_fingerprint",
        "style_generation_policy",
        "style_review_rule",
        "outline",
        "outline_version",
        "chapter_plan",
        "chapter_plan_version",
        "draft_chapter",
        "draft_version",
        "knowledge_pack",
        "rule_card",
        "template_card",
        "review_rule",
        "quality_rubric_pack",
    }


def _redacted_fingerprint(row: dict[str, Any]) -> dict[str, Any]:
    tokens = row.get("fingerprint_tokens", {}) if isinstance(row.get("fingerprint_tokens", {}), dict) else {}
    return {
        "project_id": row.get("project_id", ""),
        "fingerprint_source_count": row.get("fingerprint_source_count", 0),
        "asset_type_counts": row.get("asset_type_counts", {}),
        "fingerprint_tokens": {key: list(value)[:12] for key, value in tokens.items() if isinstance(value, list)},
        "evidence_paths": row.get("evidence_paths", [])[:8],
    }


def _fingerprint_text(value: Any, *, title: str = "") -> str:
    parts = [title] if title else []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"raw_text", "body", "content", "draft_text", "text"} and isinstance(item, str):
                parts.append(item[:1200])
            elif isinstance(item, (dict, list)):
                parts.append(_fingerprint_text(item))
            elif isinstance(item, (str, int, float, bool)):
                parts.append(str(item))
    elif isinstance(value, list):
        parts.extend(_fingerprint_text(item) for item in value[:30])
    elif isinstance(value, (str, int, float, bool)):
        parts.append(str(value))
    return " ".join(part for part in parts if part)


def _selected_text(value: Any, keys: list[str]) -> str:
    parts: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).lower()
            if any(marker in lowered for marker in keys):
                parts.append(_fingerprint_text(item))
            elif isinstance(item, (dict, list)):
                nested = _selected_text(item, keys)
                if nested:
                    parts.append(nested)
    elif isinstance(value, list):
        parts.extend(_selected_text(item, keys) for item in value[:30])
    return " ".join(part for part in parts if part)


def _top_tokens(text: str, *, limit: int) -> list[str]:
    normalized = text.lower()
    words = re.findall(r"[a-z0-9_]{3,}|[\u4e00-\u9fff]{2,}", normalized)
    tokens: dict[str, int] = {}
    for word in words:
        if re.fullmatch(r"[\u4e00-\u9fff]+", word) and len(word) > 4:
            candidates = [word[index : index + 4] for index in range(0, max(1, len(word) - 3))]
        else:
            candidates = [word]
        for candidate in candidates:
            if candidate in _stop_tokens() or len(candidate) < 2:
                continue
            tokens[candidate] = tokens.get(candidate, 0) + 1
    ranked = sorted(tokens.items(), key=lambda item: (-item[1], item[0]))
    return [token for token, _count in ranked[:limit]]


def _stop_tokens() -> set[str]:
    return {
        "the",
        "and",
        "with",
        "from",
        "this",
        "that",
        "chapter",
        "project",
        "style",
        "genre",
        "content",
        "true",
        "false",
        "一个",
        "一种",
        "这个",
        "那个",
        "他们",
        "自己",
        "故事",
        "章节",
        "主角",
    }


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return round(len(left.intersection(right)) / len(left.union(right)), 4)


def _similarity_recommendation(risk_level: str, dimension: str) -> str:
    if risk_level == "high":
        return f"block shared context and rewrite {dimension} identity before parallel scheduling"
    if risk_level == "medium":
        return f"operator review required; differentiate {dimension} signals before shared assets"
    return "safe to keep books isolated; no shared context expansion implied"


def _project_assets(storage: LocalStorage, project_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for category in DATA_DIRS:
        for path in storage.list_json(category):
            data = _read_json_safe(storage, path)
            if not data:
                continue
            metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
            content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
            row_project = str(metadata.get("project_id") or content.get("project_id") or "")
            if row_project == project_id:
                rows.append({**data, "path": _display_path(storage.root, path)})
    return rows


def _portfolio_from_ref(storage: LocalStorage, portfolio_ref: str | Path) -> dict[str, Any]:
    if portfolio_ref:
        path = resolve_path(storage.root, portfolio_ref)
        if path.exists():
            data = storage.read_json(path)
            return {**data, "path": _display_path(storage.root, path)}
        ref = str(portfolio_ref)
        for path in reversed(storage.list_json("workspaces")):
            data = storage.read_json(path)
            if data.get("type") != "portfolio_project":
                continue
            content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
            if ref in {str(data.get("id") or ""), str(content.get("portfolio_id") or "")}:
                return {**data, "path": _display_path(storage.root, path)}
        raise FileNotFoundError(f"portfolio project not found: {portfolio_ref}")
    return {"id": "", "title": "adhoc portfolio", "content": {"project_ids": []}, "path": ""}


def _latest_quality_score(rows: list[dict[str, Any]]) -> tuple[float, str]:
    quality_rows = [row for row in rows if row.get("type") in {"quality_score_report", "model_judge_result", "evaluation_result"}]
    if not quality_rows:
        return 0.0, ""
    row = quality_rows[-1]
    content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
    value = content.get("score") or content.get("overall_score") or content.get("score_total") or content.get("quality_score") or 0.0
    try:
        return max(0.0, min(1.0, float(value))), str(row.get("path") or "")
    except (TypeError, ValueError):
        return 0.0, str(row.get("path") or "")


def _project_cost(rows: list[dict[str, Any]]) -> float:
    total = 0.0
    for row in rows:
        content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
        for key in ["cost", "cost_usd", "estimated_cost", "total_cost"]:
            try:
                total += float(content.get(key) or 0.0)
            except (TypeError, ValueError):
                continue
    return round(total, 4)


def _type_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        asset_type = str(row.get("type") or "")
        if asset_type:
            counts[asset_type] = counts.get(asset_type, 0) + 1
    return counts


def _cost_quality_rollup(scores: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [row.get("content", {}) for row in scores if isinstance(row.get("content", {}), dict)]
    return {
        "book_count": len(rows),
        "average_score": round(sum(float(row.get("score_total") or 0.0) for row in rows) / max(1, len(rows)), 3),
        "total_model_cost": round(sum(float((row.get("evidence", {}) if isinstance(row.get("evidence", {}), dict) else {}).get("model_cost") or 0.0) for row in rows), 4),
        "blocked_book_count": sum(1 for row in rows if int((row.get("evidence", {}) if isinstance(row.get("evidence", {}), dict) else {}).get("blocking_review_issue_count") or 0) > 0),
    }


def _portfolio_isolation_contract(project_ids: list[str]) -> dict[str, Any]:
    return {
        "project_ids": _clean_ids(project_ids),
        "memory_scope": "project_id",
        "context_scope": "project_id",
        "canon_scope": "project_id",
        "style_scope": "project_id",
        "cross_book_assets_allowed": False,
        "requires_cross_book_similarity_guard_before_shared_assets": True,
    }


def _schedule_action(evidence: dict[str, Any]) -> str:
    plan_count = int(evidence.get("chapter_plan_count") or 0)
    draft_count = int(evidence.get("draft_count") or 0)
    if plan_count > draft_count:
        return "generate_next_chapter"
    return "build_next_chapter_plan"


def _recommendation(total: float, evidence: dict[str, Any]) -> str:
    if int(evidence.get("blocking_review_issue_count") or 0) > 0:
        return "hold_until_blockers_clear"
    if total >= 0.75:
        return "prioritize"
    if total >= 0.45:
        return "continue_watch"
    return "incubate"


def _clean_ids(project_ids: list[str]) -> list[str]:
    return _dedupe([str(item).strip() for item in project_ids if str(item).strip()])


def _read_json_safe(storage: LocalStorage, path: Path) -> dict[str, Any]:
    try:
        data = storage.read_json(path)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_asset(storage: LocalStorage, asset: Any) -> str:
    storage.ensure_layout()
    return _display_path(storage.root, storage.write_asset_auto(asset))


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result

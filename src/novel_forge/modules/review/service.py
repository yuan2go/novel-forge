from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from novel_forge.evaluation.quality import QUALITY_DIMENSIONS
from novel_forge.evaluation.creative_gate import evaluate_draft_quality, gate_issues
from novel_forge.model_adapters import ModelAdapter, model_from_env, validate_model_output
from novel_forge.model_adapters.mock import MockModelAdapter
from novel_forge.modules.common import read_previous, run_metadata
from novel_forge.schemas import ReviewReport
from novel_forge.storage.local import LocalStorage
from novel_forge.storage.rag_context import build_rag_context, retrieval_metadata, retrieval_reference_ids


def review(storage: LocalStorage, input_path: str | None = None, model: ModelAdapter | None = None) -> Path:
    model = model or model_from_env("review")
    draft_asset = read_previous(storage, "drafts", input_path)
    retrieved_context = build_rag_context(
        storage,
        draft_asset,
        input_path=input_path,
        query=f"review draft {draft_asset.title} {draft_asset.content.get('chapter', '')}",
    )
    result = validate_model_output(
        "review",
        model.review(
            draft_asset.content.get("text", ""),
            {
                "rubric": QUALITY_DIMENSIONS,
                "draft_asset_id": draft_asset.id,
                "copyright_boundary": draft_asset.content.get("copyright_boundary", ""),
                "retrieved_context": retrieved_context,
            },
        ),
    )
    quality_gate = evaluate_draft_quality(draft_asset.content.get("text", ""))
    issues = [*result["issues"], *gate_issues(quality_gate)]
    asset = ReviewReport(
        title=f"Review for {draft_asset.title}",
        source=draft_asset.id,
        tags=["review", "quality"],
        content={
            "rubric": QUALITY_DIMENSIONS,
            "summary": f"{model.name} review completed",
            "quality_gates": quality_gate,
            "retrieved_context": retrieved_context,
            "model_output": result,
        },
        metadata={
            "model": model.name,
            "provider": result.get("provider", model.name),
            **retrieval_metadata(retrieved_context),
            "run_metadata": run_metadata(
                "review",
                draft_asset,
                provider=result.get("provider", model.name),
                model=result.get("model", model.name),
            ),
        },
        score=float(result["score"]),
        strengths=result["strengths"],
        weaknesses=result["weaknesses"],
        issues=issues,
        risk_level="high" if any(issue.get("severity") == "high" for issue in gate_issues(quality_gate)) else result["risk_level"],
        revision_suggestions=_dedupe(
            [
                *result["revision_suggestions"],
                *[
                    str(issue.get("recommendation", ""))
                    for issue in gate_issues(quality_gate)
                    if issue.get("recommendation")
                ],
            ]
        ),
        next_action=result["next_action"],
        references=retrieval_reference_ids(draft_asset.id, retrieved_context),
    )
    return storage.write_asset("reviews", asset)


@dataclass(frozen=True)
class MockReviewProfile:
    name: str
    role: str
    score_delta: int = 0
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    issues: list[dict[str, Any]] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    risk_level: str = "medium"


DEFAULT_REVIEW_PROFILES = [
    MockReviewProfile(
        name="mock-structure-reviewer",
        role="structure_and_causality",
        score_delta=0,
        strengths=["clear forward motion", "visible chapter hook"],
        weaknesses=["causal chain can be made more explicit"],
        issues=[
            {
                "dimension": "causal_chain",
                "severity": "medium",
                "message": "Make the decision-consequence link visible before the final hook.",
            }
        ],
        suggestions=["add one explicit consequence after the protagonist's key choice"],
    ),
    MockReviewProfile(
        name="mock-commercial-reviewer",
        role="commercial_readability",
        score_delta=4,
        strengths=["visible chapter hook", "reader-retention pressure is present"],
        weaknesses=["payoff density can be higher in the middle beat"],
        issues=[
            {
                "dimension": "payoff_density",
                "severity": "medium",
                "message": "Add one concrete reward, reveal, or status shift before the hook.",
            }
        ],
        suggestions=["increase one mid-scene payoff before escalating to the next obligation"],
    ),
    MockReviewProfile(
        name="mock-compliance-reviewer",
        role="originality_boundary",
        score_delta=-3,
        strengths=["copyright boundary is declared"],
        weaknesses=["reference abstraction should remain explicit in revision notes"],
        issues=[
            {
                "dimension": "originality_and_copyright_boundary",
                "severity": "medium",
                "message": "Confirm generated beats do not reproduce source names, settings, or sequence combinations.",
            }
        ],
        suggestions=["keep an originality self-check in the revision plan"],
    ),
]


def compare_reviews(storage: LocalStorage, input_path: str | None = None) -> Path:
    draft_asset = read_previous(storage, "drafts", input_path)
    draft_text = draft_asset.content.get("text", "")
    model_reviews = [_run_profile_review(profile, draft_text) for profile in DEFAULT_REVIEW_PROFILES]
    score_summary = _score_summary([float(review["score"]) for review in model_reviews])
    consensus = _build_consensus(model_reviews)
    disagreements = _build_disagreements(model_reviews)
    risk_level = _aggregate_risk(model_reviews)

    asset = ReviewReport(
        title=f"Multi-model review comparison for {draft_asset.title}",
        source=draft_asset.id,
        tags=["review", "review-comparison", "multi-model", "mock"],
        content={
            "rubric": QUALITY_DIMENSIONS,
            "summary": "mock multi-model review comparison completed",
            "model_reviews": model_reviews,
            "score_summary": score_summary,
            "consensus": consensus,
            "disagreements": disagreements,
            "decision": "revise before final draft",
        },
        metadata={
            "workflow": "multi-model-review-comparison",
            "reviewer_count": len(model_reviews),
            "external_api": False,
            "mock_only": True,
        },
        score=score_summary["average"],
        strengths=consensus["shared_strengths"],
        weaknesses=consensus["shared_weaknesses"],
        issues=_flatten_issues(model_reviews),
        risk_level=risk_level,
        revision_suggestions=consensus["revision_priorities"],
        next_action="revise",
        references=[draft_asset.id],
    )
    return storage.write_asset("reviews", asset)


def _run_profile_review(profile: MockReviewProfile, content: str) -> dict[str, Any]:
    base = MockModelAdapter().review(content, {"rubric": QUALITY_DIMENSIONS, "role": profile.role})
    score = max(0, min(100, int(base["score"]) + profile.score_delta))
    strengths = _dedupe([*base["strengths"], *profile.strengths])
    weaknesses = _dedupe([*base["weaknesses"], *profile.weaknesses])
    suggestions = _dedupe([*base["revision_suggestions"], *profile.suggestions])
    issues = [*_copy_issues(base["issues"], profile.name), *_copy_issues(profile.issues, profile.name)]
    return {
        "model": profile.name,
        "role": profile.role,
        "score": score,
        "risk_level": profile.risk_level or base["risk_level"],
        "strengths": strengths,
        "weaknesses": weaknesses,
        "issues": issues,
        "revision_suggestions": suggestions,
        "next_action": base["next_action"],
    }


def _score_summary(scores: list[float]) -> dict[str, float]:
    if not scores:
        return {"average": 0.0, "minimum": 0.0, "maximum": 0.0, "spread": 0.0}
    minimum = min(scores)
    maximum = max(scores)
    return {
        "average": round(sum(scores) / len(scores), 2),
        "minimum": round(minimum, 2),
        "maximum": round(maximum, 2),
        "spread": round(maximum - minimum, 2),
    }


def _build_consensus(model_reviews: list[dict[str, Any]]) -> dict[str, list[str]]:
    strengths = _dedupe(_shared_or_frequent(model_reviews, "strengths"))
    weaknesses = _dedupe(_shared_or_frequent(model_reviews, "weaknesses"))
    revision_priorities = _dedupe(_shared_or_frequent(model_reviews, "revision_suggestions"))
    return {
        "shared_strengths": strengths[:5],
        "shared_weaknesses": weaknesses[:5],
        "revision_priorities": revision_priorities[:5],
    }


def _build_disagreements(model_reviews: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scores = {review["model"]: float(review["score"]) for review in model_reviews}
    score_values = list(scores.values())
    disagreements: list[dict[str, Any]] = []
    if score_values and max(score_values) - min(score_values) >= 5:
        disagreements.append(
            {
                "dimension": "overall_score",
                "models": sorted(scores),
                "reason": "mock reviewers disagree on commercial upside versus originality risk.",
            }
        )
    dimensions = sorted(
        {
            str(issue.get("dimension", "unknown"))
            for review in model_reviews
            for issue in review.get("issues", [])
            if isinstance(issue, dict)
        }
    )
    for dimension in dimensions[:3]:
        models = sorted(
            review["model"]
            for review in model_reviews
            if any(isinstance(issue, dict) and issue.get("dimension") == dimension for issue in review.get("issues", []))
        )
        if len(models) == 1:
            disagreements.append(
                {
                    "dimension": dimension,
                    "models": models,
                    "reason": "only one reviewer raised this issue, so confirm before major rewrite.",
                }
            )
    return disagreements


def _aggregate_risk(model_reviews: list[dict[str, Any]]) -> str:
    levels = {str(review.get("risk_level", "medium")) for review in model_reviews}
    if "high" in levels:
        return "high"
    if "medium" in levels:
        return "medium"
    return "low"


def _flatten_issues(model_reviews: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [issue for review in model_reviews for issue in review.get("issues", []) if isinstance(issue, dict)]


def _shared_or_frequent(model_reviews: list[dict[str, Any]], field_name: str) -> list[str]:
    counts: dict[str, int] = {}
    for review in model_reviews:
        values = review.get(field_name, [])
        if not isinstance(values, list):
            continue
        for value in values:
            if isinstance(value, str) and value.strip():
                counts[value] = counts.get(value, 0) + 1
    return [item for item, _ in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))]


def _copy_issues(issues: Any, reviewer: str) -> list[dict[str, Any]]:
    if not isinstance(issues, list):
        return []
    copied: list[dict[str, Any]] = []
    for issue in issues:
        if isinstance(issue, dict):
            copied_issue = dict(issue)
            copied_issue["reviewer"] = reviewer
            copied.append(copied_issue)
    return copied


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result

from __future__ import annotations

from typing import Any, Iterable


BRIEF_FIELDS = (
    "target_genre", "subgenre", "target_platform", "target_audience", "reading_promise",
    "core_fantasy", "core_conflict", "protagonist_mechanism", "antagonist_mechanism",
    "world_novelty", "emotional_engine", "pleasure_engine", "suspense_engine",
    "theme_question", "serialization_strategy", "prohibited_elements", "source_boundaries",
    "quality_targets",
)
FINGERPRINT_FIELDS = (
    "protagonist_advantage_mechanism", "conflict_loop", "growth_loop", "reward_loop",
    "information_asymmetry", "world_constraint", "relationship_engine",
    "antagonist_response_pattern", "chapter_payoff_pattern",
)
EVALUATION_FIELDS = (
    "novelty", "genre_fit", "platform_fit", "conflict_sustainability", "longform_capacity",
    "protagonist_agency", "antagonist_pressure", "pleasure_potential", "suspense_potential",
    "theme_potential", "serialization_potential", "similarity_risk", "production_difficulty",
)


def validate_creative_brief(brief: dict[str, Any]) -> dict[str, Any]:
    if brief.get("creative_brief_contract_version") == "creative-brief-v2":
        if set(brief) != {"creative_brief_contract_version", "idea", "genre", "audience", "constraints", "source_boundaries"}:
            raise ValueError("Natural-language CreativeBrief fields must match exactly")
        if any(not isinstance(brief[field], str) or not brief[field].strip() or len(brief[field]) > 12000 for field in ("idea", "genre", "audience")):
            raise ValueError("CreativeBrief needs a bounded idea, genre and audience")
        if any(not isinstance(brief[field], list) or not brief[field] or len(brief[field]) > 32 or any(not isinstance(item, str) or not item.strip() or len(item) > 2000 for item in brief[field]) for field in ("constraints", "source_boundaries")):
            raise ValueError("CreativeBrief needs bounded author constraints and source boundaries")
        return dict(brief)
    missing = [field for field in BRIEF_FIELDS if brief.get(field) in (None, "", [])]
    if missing:
        raise ValueError("CreativeBrief missing: " + ", ".join(missing))
    if "?" not in str(brief["theme_question"]) and "？" not in str(brief["theme_question"]):
        raise ValueError("theme_question must be a testable question")
    return {**brief, "creative_brief_contract_version": "creative-brief-v1"}


def evaluate_candidate(*, project_id: str, brief: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    validate_creative_brief(brief)
    if candidate.get("project_id") != project_id:
        raise ValueError("creative candidate is outside project scope")
    missing = [field for field in FINGERPRINT_FIELDS if not candidate.get("fingerprint", {}).get(field)]
    if missing:
        raise ValueError("CreativeFingerprint missing: " + ", ".join(missing))
    scores = candidate.get("scores", {})
    invalid = [field for field in EVALUATION_FIELDS if not isinstance(scores.get(field), (int, float))]
    if invalid:
        raise ValueError("CandidateEvaluation missing scores: " + ", ".join(invalid))
    positive = [field for field in EVALUATION_FIELDS if field not in {"similarity_risk", "production_difficulty"}]
    total = sum(float(scores[field]) for field in positive) / len(positive)
    total -= 0.25 * float(scores["similarity_risk"]) + 0.10 * float(scores["production_difficulty"])
    gates = {
        "novelty": scores["novelty"] >= 0.55 and scores["similarity_risk"] <= 0.55,
        "commercial_readability": scores["genre_fit"] >= 0.5 and scores["platform_fit"] >= 0.5,
        "longform": scores["longform_capacity"] >= 0.6 and scores["conflict_sustainability"] >= 0.6,
        "originality": scores["similarity_risk"] <= 0.55,
    }
    return {
        "candidate_id": candidate["candidate_id"], "project_id": project_id,
        "fingerprint": dict(candidate["fingerprint"]), "scores": dict(scores),
        "total_score": round(total, 6), "gates": gates, "passed": all(gates.values()),
        "known_risks": list(candidate.get("known_risks", [])),
        "evaluation_contract_version": "creative-candidate-evaluation-v1",
    }


def fingerprint_similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    matches = sum(str(left.get(field)) == str(right.get(field)) for field in FINGERPRINT_FIELDS)
    return matches / len(FINGERPRINT_FIELDS)


def cluster_candidates(evaluations: Iterable[dict[str, Any]], *, threshold: float = 0.7) -> list[dict[str, Any]]:
    clusters: list[dict[str, Any]] = []
    for evaluation in sorted(evaluations, key=lambda item: (-item["total_score"], item["candidate_id"])):
        cluster = next((item for item in clusters if fingerprint_similarity(item["representative_fingerprint"], evaluation["fingerprint"]) >= threshold), None)
        if cluster:
            cluster["candidate_ids"].append(evaluation["candidate_id"])
            cluster["duplicate_candidate_ids"].append(evaluation["candidate_id"])
        else:
            clusters.append({
                "cluster_id": f"candidate-cluster-{len(clusters) + 1}",
                "representative_candidate_id": evaluation["candidate_id"],
                "representative_fingerprint": evaluation["fingerprint"],
                "candidate_ids": [evaluation["candidate_id"]], "duplicate_candidate_ids": [],
            })
    return clusters


def build_project_proposal(*, project_id: str, brief_version_id: str, evaluations: list[dict[str, Any]]) -> dict[str, Any]:
    passed = sorted((item for item in evaluations if item["passed"]), key=lambda item: -item["total_score"])
    if not passed:
        raise ValueError("no creative candidate passed project gates")
    selected = passed[0]
    return {
        "project_id": project_id, "creative_brief_version_id": brief_version_id,
        "selected_candidate_id": selected["candidate_id"],
        "rejected_alternatives": [item["candidate_id"] for item in evaluations if item["candidate_id"] != selected["candidate_id"]],
        "selection_reasons": [name for name, value in selected["gates"].items() if value],
        "known_risks": selected["known_risks"],
        "required_knowledge": ["genre", "world rules", "theme evidence"],
        "required_world_assets": ["world_bible", "world_rule"],
        "required_character_assets": ["character_card", "relationship_state"],
        "expected_longform_size": "long_serial", "initial_quality_strategy": "gated chapter loop",
        "approval_status": "REQUIRES_OPERATOR_APPROVAL",
    }


__all__ = ["build_project_proposal", "cluster_candidates", "evaluate_candidate", "fingerprint_similarity", "validate_creative_brief"]

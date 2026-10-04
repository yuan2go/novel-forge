"""INVARIANT: candidate selection never treats the newest Revision as the best candidate."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError


class CandidateStopReason(StrEnum):
    QUALITY_SATISFIED = "QUALITY_SATISFIED"
    MARGINAL_IMPROVEMENT = "MARGINAL_IMPROVEMENT"
    DETERMINISTIC_BLOCKER = "DETERMINISTIC_BLOCKER"
    MAX_CORRECTION_BUDGET = "MAX_CORRECTION_BUDGET"
    CONTINUE_CORRECTION = "CONTINUE_CORRECTION"
    ESCALATION_REQUIRED = "ESCALATION_REQUIRED"


@dataclass(frozen=True, slots=True)
class CandidateEvidence:
    asset_version_id: str
    content: dict[str, Any]
    score: float
    blocker_codes: tuple[str, ...]
    review_asset_version_id: str
    diagnostic_contract_version: str = ""
    resolution_checks: tuple[dict[str, Any], ...] = ()
    workspace_asset_version_id: str = ""
    cross_chapter_review: bool = False
    preservation_checks: tuple[dict[str, Any], ...] = ()
    quality_resolution_checks: tuple[dict[str, Any], ...] = ()


def retained_candidate_evidence(workspace_id: str, content: dict[str, Any]) -> CandidateEvidence:
    from novel_forge.modules.review.diagnostics import blocking_diagnosis_codes, require_review_score
    comparison = content.get("candidate_comparison")
    selected_id = content.get("selected_source_asset_version_id")
    review = content.get("selected_review")
    if (not isinstance(comparison, dict) or not selected_id or not isinstance(review, dict)
        or any(not isinstance(comparison.get(key), dict) for key in ("previous", "challenger"))
        or comparison.get("selected_asset_version_id") != selected_id):
        raise KernelError("BEST_CANDIDATE_EVIDENCE_REQUIRED", "retained workspace requires exact prose, review and comparison identities")
    matches = [comparison[key] for key in ("previous", "challenger") if comparison[key].get("asset_version_id") == selected_id]
    if len(matches) != 1:
        raise KernelError("BEST_CANDIDATE_EVIDENCE_REQUIRED", "selected prose must identify one comparison subject")
    selected = matches[0]
    blockers = selected.get("blocker_codes")
    review_id = selected.get("review_asset_version_id")
    if (not isinstance(blockers, list) or any(not isinstance(code, str) or not code for code in blockers)
        or not review_id or review.get("selection_review_source_asset_version_id") != review_id
        or not set(blocking_diagnosis_codes(review)).issubset(blockers)):
        raise KernelError("BEST_CANDIDATE_EVIDENCE_REQUIRED", "retained blockers and selected review must remain traceable")
    score = require_review_score(selected)
    if score != require_review_score(review):
        raise KernelError("BEST_CANDIDATE_EVIDENCE_REQUIRED", "comparison score must match its immutable selected review")
    bind_selected_review(candidate=content, candidate_id=str(selected_id), review=review, review_id=str(review_id))
    return CandidateEvidence(str(selected_id), content, score, tuple(blockers), str(review_id),
                             workspace_asset_version_id=workspace_id)


def compare_candidates(
    *,
    project_id: str,
    chapter_root_operation_id: str,
    previous: CandidateEvidence,
    challenger: CandidateEvidence,
    minimum_net_improvement: float,
    correction_generation: int = 0,
    maximum_correction_generations: int = 1,
) -> dict[str, Any]:
    previous_baseline = previous.content.get("creative_baseline")
    challenger_baseline = challenger.content.get("creative_baseline")
    if previous_baseline is not None or challenger_baseline is not None:
        from .chapter_plan_views import validate_creative_baseline

        if validate_creative_baseline(previous_baseline) != validate_creative_baseline(
            challenger_baseline
        ):
            raise KernelError(
                "BEST_CANDIDATE_BASELINE_DRIFT",
                "Candidate comparison requires the same effective work contract; changed requirements need fresh evaluation",
            )
    if (not math.isfinite(minimum_net_improvement) or minimum_net_improvement < 0
        or not previous.asset_version_id or not challenger.asset_version_id
        or previous.asset_version_id == challenger.asset_version_id
        or any(type(item.score) not in {float, int} or not math.isfinite(item.score)
               or not 0 <= item.score <= 100 or not item.review_asset_version_id for item in (previous, challenger))):
        raise KernelError(
            "BEST_CANDIDATE_INPUT_INVALID",
            "candidate selection requires immutable candidate and policy identities",
        )
    new_blockers = sorted(set(challenger.blocker_codes) - set(previous.blocker_codes))
    resolved_blockers = sorted(
        set(previous.blocker_codes) - set(challenger.blocker_codes)
    )
    net_improvement = challenger.score - previous.score
    diagnostic_selection = challenger.diagnostic_contract_version == "actionable-diagnostics.v1"
    supported_improvement = any(check.get("status") == "SATISFIED" and check.get("preservation") == "PRESERVED" for check in challenger.resolution_checks)
    from novel_forge.modules.review.diagnostics import prose_hash

    quality_supported = (bool(challenger.quality_resolution_checks)
        and {check.get("observation") for check in challenger.quality_resolution_checks} == set(challenger.content.get("quality_action_observations") or [])
        and all(check.get("status") == "SATISFIED" and check.get("preservation") == "PRESERVED"
            and check.get("target_asset_version_id") == challenger.asset_version_id
            and check.get("target_text_hash") == prose_hash(str(challenger.content.get("text") or ""))
            and check.get("source_quality_asset_version_id") == challenger.content.get("source_quality_asset_version_id")
            and check.get("source_quality_asset_version_id")
            for check in challenger.quality_resolution_checks))
    supported_improvement = supported_improvement or quality_supported
    preservation_regressed = any(check.get("preservation") != "PRESERVED"
        for check in (*challenger.resolution_checks, *challenger.quality_resolution_checks))
    from novel_forge.modules.review.prose_window import PRESERVATION_DIMENSIONS

    if challenger.cross_chapter_review and (
        set(previous.blocker_codes) & set(challenger.blocker_codes)
        or any(check.get("status") != "PRESERVED" for check in challenger.preservation_checks)
        or len(challenger.preservation_checks) != len(PRESERVATION_DIMENSIONS)
    ):
        selected = previous
        reason = CandidateStopReason.ESCALATION_REQUIRED
        improved = False
    elif challenger.quality_resolution_checks and not quality_supported:
        selected = previous
        reason = CandidateStopReason.ESCALATION_REQUIRED
        improved = False
    elif diagnostic_selection and (not supported_improvement or preservation_regressed):
        selected = previous
        reason = CandidateStopReason.ESCALATION_REQUIRED if preservation_regressed else CandidateStopReason.MARGINAL_IMPROVEMENT
        improved = False
    elif new_blockers:
        selected = previous
        reason = CandidateStopReason.DETERMINISTIC_BLOCKER
        improved = False
    elif resolved_blockers:
        selected = challenger
        improved = True
        reason = (
            CandidateStopReason.QUALITY_SATISFIED
            if not challenger.blocker_codes and challenger.score >= 80
            else CandidateStopReason.CONTINUE_CORRECTION
        )
    elif net_improvement + 1e-9 < minimum_net_improvement:
        selected = previous
        reason = CandidateStopReason.MARGINAL_IMPROVEMENT
        improved = False
    else:
        selected = challenger
        improved = True
        if not challenger.blocker_codes and challenger.score >= 80:
            reason = CandidateStopReason.QUALITY_SATISFIED
        elif correction_generation >= maximum_correction_generations:
            reason = CandidateStopReason.MAX_CORRECTION_BUDGET
        else:
            reason = CandidateStopReason.CONTINUE_CORRECTION
    identity = "|".join(
        (
            project_id,
            chapter_root_operation_id,
            previous.asset_version_id,
            challenger.asset_version_id,
            str(correction_generation),
        )
    )
    comparison = {
        "type": "CandidateComparison",
        "contract_version": "candidate-comparison-v1",
        "comparison_id": "candidate-comparison:"
        + hashlib.sha256(identity.encode()).hexdigest(),
        "project_id": project_id,
        "chapter_root_operation_id": chapter_root_operation_id,
        "previous": _evidence(previous),
        "challenger": _evidence(challenger),
        "diagnostic_contract_version": challenger.diagnostic_contract_version,
        "resolution_checks": list(challenger.resolution_checks),
        "minimum_net_improvement": minimum_net_improvement,
        "net_improvement": net_improvement,
        "new_blocker_codes": new_blockers,
        "resolved_blocker_codes": resolved_blockers,
        "selected_asset_version_id": selected.asset_version_id,
        "improved": improved,
        "stop_reason": reason.value,
        "correction_generation": correction_generation,
        "maximum_correction_generations": maximum_correction_generations,
    }
    comparison["comparison_hash"] = "sha256:" + hashlib.sha256(
        json.dumps(comparison, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return comparison


def bind_selected_review(
    *,
    candidate: Mapping[str, Any],
    candidate_id: str,
    review: Mapping[str, Any],
    review_id: str,
) -> dict[str, Any]:
    from novel_forge.modules.review.diagnostics import prose_hash

    expected = prose_hash(str(candidate.get("text") or ""))
    if "creative_baseline" in candidate:
        from .chapter_plan_views import validate_creative_baseline

        if (
            review.get("creative_baseline_digest")
            != validate_creative_baseline(candidate["creative_baseline"])[
                "baseline_digest"
            ]
        ):
            raise KernelError(
                "SELECTED_REVIEW_BASELINE_DRIFT",
                "Selected prose must retain its exact reviewed work contract",
            )
    if review.get("diagnostic_contract_version") == "actionable-diagnostics.v1" and (
        review.get("target_text_hash") != expected
        or (review.get("revision_version_id") or review.get("target_asset_version_id")) != candidate_id
    ):
        raise KernelError("SELECTED_REVIEW_STALE", "selected candidate must retain its exact reviewed prose")
    return {
        **dict(review), "revision_version_id": candidate_id,
        "target_text_hash": expected,
        "selection_review_source_asset_version_id": review_id,
        "selection_review_contract": "immutable-review-projection.v1",
        "resolved_issue_codes": list(review.get("resolved_issue_codes") or []),
    }


def build_best_candidate(
    *, comparison: Mapping[str, Any], candidates: Mapping[str, Mapping[str, Any]]
) -> tuple[dict[str, Any], dict[str, Any]]:
    selected_id = str(comparison.get("selected_asset_version_id") or "")
    selected = candidates.get(selected_id)
    if selected is None:
        raise KernelError(
            "BEST_CANDIDATE_SELECTION_INVALID",
            "comparison selected a candidate outside the immutable input set",
        )
    snapshot = {
        "type": "BestCandidateSnapshot",
        "contract_version": "best-candidate-snapshot-v1",
        "best_candidate_snapshot_id": "best-candidate:"
        + hashlib.sha256(
            f"{comparison['comparison_id']}:{selected_id}".encode()
        ).hexdigest(),
        "selected_asset_version_id": selected_id,
        "previous_best_asset_version_id": str(
            (comparison.get("previous") or {}).get("workspace_asset_version_id")
            or (comparison.get("previous") or {}).get("asset_version_id") or ""
        ),
        "comparison_id": str(comparison["comparison_id"]),
        "comparison_hash": str(comparison["comparison_hash"]),
        "minimum_net_improvement": float(comparison["minimum_net_improvement"]),
        "stop_reason": str(comparison["stop_reason"]),
        "rollback_asset_version_id": str(
            (comparison.get("previous") or {}).get("workspace_asset_version_id")
            or (comparison.get("previous") or {}).get("asset_version_id") or ""
        ),
        "selection_policy_ref": "minimum-net-improvement-v1",
    }
    best = {
        **dict(selected),
        "best_candidate_snapshot": snapshot,
        "selected_source_asset_version_id": selected_id,
        "candidate_comparison": dict(comparison),
    }
    return best, snapshot


def _evidence(value: CandidateEvidence) -> dict[str, Any]:
    return {
        "asset_version_id": value.asset_version_id,
        "workspace_asset_version_id": value.workspace_asset_version_id
        or value.asset_version_id,
        "score": value.score,
        "blocker_codes": list(value.blocker_codes),
        "review_asset_version_id": value.review_asset_version_id,
        **(
            {
                "creative_baseline_digest": value.content["creative_baseline"][
                    "baseline_digest"
                ]
            }
            if "creative_baseline" in value.content
            else {}
        ),
        **(
            {"quality_resolution_checks": list(value.quality_resolution_checks)}
            if value.quality_resolution_checks
            else {}
        ),
    }


__all__ = [
    "CandidateEvidence",
    "CandidateStopReason",
    "build_best_candidate",
    "compare_candidates",
]

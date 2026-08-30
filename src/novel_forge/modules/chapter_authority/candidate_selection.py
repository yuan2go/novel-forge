"""INVARIANT: candidate selection never treats the newest Revision as the best candidate."""

from __future__ import annotations

import hashlib
import json
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
    if minimum_net_improvement < 0 or not previous.asset_version_id or not challenger.asset_version_id:
        raise KernelError(
            "BEST_CANDIDATE_INPUT_INVALID",
            "candidate selection requires immutable candidate and policy identities",
        )
    new_blockers = sorted(set(challenger.blocker_codes) - set(previous.blocker_codes))
    resolved_blockers = sorted(
        set(previous.blocker_codes) - set(challenger.blocker_codes)
    )
    net_improvement = challenger.score - previous.score
    if new_blockers:
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
            (comparison.get("previous") or {}).get("asset_version_id") or ""
        ),
        "comparison_id": str(comparison["comparison_id"]),
        "comparison_hash": str(comparison["comparison_hash"]),
        "minimum_net_improvement": float(comparison["minimum_net_improvement"]),
        "stop_reason": str(comparison["stop_reason"]),
        "rollback_asset_version_id": str(
            (comparison.get("previous") or {}).get("asset_version_id") or ""
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
        "score": value.score,
        "blocker_codes": list(value.blocker_codes),
        "review_asset_version_id": value.review_asset_version_id,
    }


__all__ = [
    "CandidateEvidence",
    "CandidateStopReason",
    "build_best_candidate",
    "compare_candidates",
]

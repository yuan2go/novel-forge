from __future__ import annotations

import math
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError

SEMANTICS_VERSION = "work-quality.v2"
QUALIFIED = frozenset(
    {
        "DETERMINISTIC",
        "HUMAN_CALIBRATED",
        "GOLDEN_SET_CALIBRATED",
        "REFERENCE_CALIBRATED",
    }
)
PASSING = frozenset({"PASSED", "PASSED_WITH_WARNINGS"})


def finalize_work_dimension(
    report: Mapping[str, Any],
    *,
    policy: Mapping[str, Any],
    requirement: Mapping[str, Any] | None,
    baseline_digest: str,
) -> dict[str, Any]:
    result = dict(report)
    applicability = (requirement or {}).get("status", "APPLICABLE")
    if applicability not in {
        "APPLICABLE",
        "NOT_APPLICABLE",
        "PROHIBITED",
        "UNDETERMINED",
    }:
        raise KernelError(
            "QUALITY_APPLICABILITY_INVALID",
            "Work requirement has an unknown applicability",
        )
    verdict = result["gate_status"]
    score = result.get("score")
    if score is not None and (
        type(score) not in {int, float}
        or not math.isfinite(score)
        or not 0 <= score <= 100
    ):
        raise KernelError(
            "QUALITY_SCORE_INVALID",
            "Scores must be finite numbers on the declared 0 to 100 scale",
        )
    result.update(
        contract_version="chapter-quality-evidence-v4",
        evaluation_semantics_version=SEMANTICS_VERSION,
        quality_policy_digest=policy["policy_digest"],
        creative_baseline_digest=baseline_digest,
        applicability=applicability,
        semantic_verdict=verdict,
        threshold_evaluation="NOT_EVALUATED",
        required_action="NONE",
        evidence_status="NOT_REQUIRED",
    )
    if applicability in {"NOT_APPLICABLE", "PROHIBITED"}:
        result.update(
            gate_status="NOT_APPLICABLE",
            score=None,
            threshold=None,
            weight=0.0,
            blocking=False,
            revision_strategy=[],
        )
        return result
    if applicability == "UNDETERMINED":
        result.update(
            gate_status="INSUFFICIENT_EVIDENCE",
            score=None,
            threshold=None,
            weight=0.0,
            blocking=True,
            required_action="EVIDENCE_REASSESSMENT",
            evidence_status="UNDETERMINED",
        )
        return result
    threshold = (
        result.get("threshold")
        if result["calibration_status"] == "DETERMINISTIC"
        else policy["thresholds"].get(result["dimension"])
    )
    result["threshold"] = threshold
    result["blocking"] = bool(
        result["blocking"] or requirement or threshold is not None
    )
    if result["calibration_status"] == "DETERMINISTIC":
        result["threshold_evaluation"] = verdict
    elif result["score"] is not None and threshold is not None:
        result["threshold_evaluation"] = (
            "PASSED" if result["score"] >= threshold else "FAILED"
        )
    calibrated = result["calibration_status"] in QUALIFIED
    result["evidence_status"] = "QUALIFIED" if calibrated else "UNQUALIFIED"
    if verdict == "FAILED":
        result["gate_status"] = "FAILED"
    elif verdict == "WAIVED_BY_APPROVAL":
        result["gate_status"] = verdict
    elif verdict in PASSING | {"PASSED_WITH_UNCALIBRATED"}:
        if (
            not calibrated
            or verdict == "PASSED_WITH_UNCALIBRATED"
            or threshold is not None
            and result["threshold_evaluation"] == "NOT_EVALUATED"
        ):
            result["gate_status"] = "INSUFFICIENT_EVIDENCE"
        elif result["threshold_evaluation"] == "FAILED":
            result["gate_status"] = "FAILED"
        else:
            result["gate_status"] = verdict
    if not calibrated or result["gate_status"] not in PASSING | {
        "FAILED",
        "WAIVED_BY_APPROVAL",
    }:
        result["weight"] = 0.0
    else:
        result["weight"] = (
            float(policy["dimension_weights"].get(result["dimension"], 1.0))
            if result["score"] is not None
            else 0.0
        )
    if result["blocking"] and result["gate_status"] not in PASSING | {
        "WAIVED_BY_APPROVAL"
    }:
        located = any(
            item.get("quote") for item in result.get("evidence_locations", [])
        )
        result["required_action"] = (
            "LOCAL_REPAIR"
            if result["gate_status"] == "FAILED" and located and calibrated
            else "EVIDENCE_REASSESSMENT"
        )
    return result

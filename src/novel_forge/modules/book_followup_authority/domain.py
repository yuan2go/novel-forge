"""Pure decision logic for governed post-chapter operations.

This module intentionally cannot write assets, mutate Canon, or activate plans.
Handlers persist its outputs through the shared Authority handler runtime.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Mapping, Sequence

from novel_forge.modules.reader_calibration.domain import (
    ReaderJudgeQualificationStatus,
    evaluate_reader_outcome_consumption,
)


class ReaderOutcomeGate(str, Enum):
    PASS = "PASS"
    PASS_WITH_WARNINGS = "PASS_WITH_WARNINGS"
    REVISION_RECOMMENDED = "REVISION_RECOMMENDED"
    REVISION_REQUIRED = "REVISION_REQUIRED"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"
    BLOCKED = "BLOCKED"


class LongformCheckpointType(str, Enum):
    CHAPTER_CADENCE = "CHAPTER_CADENCE"
    CHAPTER_GROUP_COMPLETE = "CHAPTER_GROUP_COMPLETE"
    ARC_CHECKPOINT = "ARC_CHECKPOINT"
    VOLUME_CHECKPOINT = "VOLUME_CHECKPOINT"
    MANUAL = "MANUAL"
    READER_OUTCOME_RISK = "READER_OUTCOME_RISK"
    CANON_RISK = "CANON_RISK"
    DEBT_THRESHOLD = "DEBT_THRESHOLD"
    QUALITY_TREND = "QUALITY_TREND"
    BOOK_AUTHORITY_REQUEST = "BOOK_AUTHORITY_REQUEST"


READER_STATE_DIMENSIONS = (
    "continue_intent",
    "curiosity",
    "satisfaction",
    "confusion",
    "trust",
    "character_attachment",
    "antagonist_pressure",
    "promise_expectation",
    "payoff_satisfaction",
    "drop_risk",
    "repetition_fatigue",
)


def evaluate_reader_outcome(
    state: Mapping[str, Any],
    *,
    evidence: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Return an explainable gate without reducing the state to one average."""

    missing = [name for name in READER_STATE_DIMENSIONS if name not in state]
    if missing:
        raise ValueError(f"reader outcome missing dimensions: {', '.join(missing)}")
    if not evidence:
        raise ValueError("reader outcome requires evidence")
    normalized: dict[str, float] = {}
    for name in READER_STATE_DIMENSIONS:
        value = state[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"reader outcome dimension {name} must be numeric")
        score = float(value)
        if not 0 <= score <= 1:
            raise ValueError(f"reader outcome dimension {name} must be between 0 and 1")
        normalized[name] = score

    issues: list[dict[str, Any]] = []
    for name, code, high_is_bad, blocking, threshold in (
        ("confusion", "READER_CONFUSION_RISE", True, True, 0.75),
        ("drop_risk", "DROP_RISK_HIGH", True, True, 0.75),
        ("repetition_fatigue", "REPETITION_FATIGUE", True, False, 0.65),
        ("continue_intent", "CONTINUE_INTENT_LOW", False, True, 0.35),
        ("trust", "READER_TRUST_LOW", False, False, 0.45),
        ("character_attachment", "CHARACTER_ATTACHMENT_LOW", False, False, 0.45),
        ("antagonist_pressure", "ANTAGONIST_PRESSURE_DROP", False, False, 0.40),
        ("payoff_satisfaction", "PAYOFF_SATISFACTION_LOW", False, False, 0.45),
    ):
        value = normalized[name]
        breached = value >= threshold if high_is_bad else value <= threshold
        if breached:
            issues.append(
                {
                    "code": code,
                    "dimension": name,
                    "severity": "BLOCKING" if blocking else "MAJOR",
                    "observed": value,
                    "threshold": threshold,
                    "evidence": [dict(item) for item in evidence],
                }
            )

    blocking_count = sum(item["severity"] == "BLOCKING" for item in issues)
    major_count = len(issues) - blocking_count
    if blocking_count >= 2:
        gate = ReaderOutcomeGate.REVISION_REQUIRED
    elif blocking_count == 1:
        gate = ReaderOutcomeGate.REVISION_RECOMMENDED
    elif major_count >= 3:
        gate = ReaderOutcomeGate.HUMAN_REVIEW_REQUIRED
    elif major_count:
        gate = ReaderOutcomeGate.PASS_WITH_WARNINGS
    else:
        gate = ReaderOutcomeGate.PASS
    return {
        "contract_version": "reader-outcome-decision-v1",
        "reader_state": normalized,
        "gate": gate.value,
        "issues": issues,
        "evidence": [dict(item) for item in evidence],
        "body_mutation_allowed": False,
        "decision_explanation": {
            "blocking_issue_count": blocking_count,
            "major_issue_count": major_count,
            "aggregate_score_used": False,
        },
    }


def should_trigger_longform_recap(
    *,
    chapter_number: int,
    light_cadence: int,
    formal_cadence: int,
    chapter_group_complete: bool = False,
    arc_checkpoint: bool = False,
    volume_checkpoint: bool = False,
    manual: bool = False,
    reader_outcome_declining: bool = False,
    canon_risk: bool = False,
    debt_threshold_exceeded: bool = False,
    quality_trend_declining: bool = False,
    authority_requested: bool = False,
) -> dict[str, Any]:
    if chapter_number <= 0 or light_cadence <= 0 or formal_cadence <= 0:
        raise ValueError("chapter and recap cadences must be positive")
    reasons: list[str] = []
    checkpoint = LongformCheckpointType.CHAPTER_CADENCE
    level = "NONE"
    if chapter_number % formal_cadence == 0:
        reasons.append("FORMAL_CHAPTER_CADENCE")
        level = "FORMAL"
    elif chapter_number % light_cadence == 0:
        reasons.append("LIGHT_CHAPTER_CADENCE")
        level = "LIGHT"
    for condition, reason, kind in (
        (chapter_group_complete, "CHAPTER_GROUP_COMPLETE", LongformCheckpointType.CHAPTER_GROUP_COMPLETE),
        (arc_checkpoint, "ARC_CHECKPOINT", LongformCheckpointType.ARC_CHECKPOINT),
        (volume_checkpoint, "VOLUME_CHECKPOINT", LongformCheckpointType.VOLUME_CHECKPOINT),
        (manual, "MANUAL_TRIGGER", LongformCheckpointType.MANUAL),
        (reader_outcome_declining, "READER_OUTCOME_CONTINUOUS_DECLINE", LongformCheckpointType.READER_OUTCOME_RISK),
        (canon_risk, "CANON_RISK", LongformCheckpointType.CANON_RISK),
        (debt_threshold_exceeded, "NARRATIVE_DEBT_THRESHOLD", LongformCheckpointType.DEBT_THRESHOLD),
        (quality_trend_declining, "QUALITY_TREND_DECLINE", LongformCheckpointType.QUALITY_TREND),
        (authority_requested, "BOOK_AUTHORITY_REQUEST", LongformCheckpointType.BOOK_AUTHORITY_REQUEST),
    ):
        if condition:
            reasons.append(reason)
            checkpoint = kind
            if level == "NONE":
                level = "EXCEPTION"
    return {
        "should_trigger": bool(reasons),
        "checkpoint_type": checkpoint.value,
        "level": level,
        "chapter_number": chapter_number,
        "reasons": reasons,
    }


def build_longform_recap_outputs(
    *,
    project_id: str,
    book_id: str,
    chapter_range: tuple[int, int],
    checkpoint_type: LongformCheckpointType,
    observations: Mapping[str, Any],
) -> dict[str, Any]:
    start, end = chapter_range
    if not project_id or not book_id or start <= 0 or end < start:
        raise ValueError("valid project, book, and chapter range are required")
    deviations: list[dict[str, Any]] = []

    reader = _mapping(observations.get("reader_state"))
    reader_qualification = _mapping(observations.get("reader_qualification"))
    reader_consumption = evaluate_reader_outcome_consumption(
        qualification_status=ReaderJudgeQualificationStatus(
            str(reader_qualification.get("qualification_status") or "SHADOW")
        ),
        sample_size=int(reader_qualification.get("sample_size") or 0),
        confidence=float(reader_qualification.get("confidence") or 0),
        recent_reports=list(reader_qualification.get("recent_reports") or []),
        current_chapter=end,
        last_adjustment_chapter=(
            int(reader_qualification["last_adjustment_chapter"])
            if reader_qualification.get("last_adjustment_chapter") is not None
            else None
        ),
        disagreement=bool(reader_qualification.get("disagreement", True)),
        position_bias=bool(reader_qualification.get("position_bias", True)),
        ood=bool(reader_qualification.get("ood", True)),
        drift_detected=bool(reader_qualification.get("drift_detected", False)),
    )
    quality = _mapping(observations.get("quality_trend"))
    canon = _mapping(observations.get("canon"))
    rewards = _mapping(observations.get("reward_ledger"))
    promises = _mapping(observations.get("promise_ledger"))
    ending_reachability = _mapping(observations.get("ending_reachability"))
    arc_checkpoint = _mapping(observations.get("accepted_arc_checkpoint"))
    _add_if(deviations, bool(canon.get("conflicts")), "CANON_CONFLICT", "BLOCKING", canon)
    _add_if(
        deviations,
        bool(ending_reachability.get("replan_required")),
        "ENDING_REACHABILITY_AT_RISK",
        "BLOCKING",
        ending_reachability,
    )
    checkpoint_decision = str(arc_checkpoint.get("decision") or "")
    _add_if(
        deviations,
        checkpoint_decision == "REPLAN_REQUIRED",
        "ARC_CHECKPOINT_REPLAN_REQUIRED",
        "BLOCKING",
        arc_checkpoint,
    )
    _add_if(
        deviations,
        checkpoint_decision == "CORRECT",
        "ARC_CHECKPOINT_CORRECTION",
        "MAJOR",
        arc_checkpoint,
    )
    reader_allowed = bool(
        reader_consumption["future_production_influence_allowed"]
    )
    _add_if(deviations, reader_allowed and float(reader.get("confusion") or 0) >= 0.65, "READER_CONFUSION_RISE", "MAJOR", reader)
    _add_if(deviations, reader_allowed and float(reader.get("repetition_fatigue") or 0) >= 0.65, "REPETITION_FATIGUE", "MAJOR", reader)
    _add_if(deviations, str(quality.get("direction") or "").upper() == "DECLINING", "QUALITY_TREND_DECLINE", "MAJOR", quality)
    _add_if(deviations, int(rewards.get("overdue") or 0) > 0, "REWARD_CADENCE_FAILURE", "MAJOR", rewards)
    _add_if(deviations, int(promises.get("overdue") or 0) > 0, "PROMISE_DEBT", "MAJOR", promises)

    for key, deviation_type in (
        ("main_plot_stagnation", "MAIN_PLOT_STAGNATION"),
        ("arc_goal_drift", "ARC_GOAL_DRIFT"),
        ("character_arc_drift", "CHARACTER_ARC_DRIFT"),
        ("character_disappearance", "CHARACTER_DISAPPEARANCE"),
        ("power_inflation", "POWER_INFLATION"),
        ("timeline_conflict", "TIMELINE_CONFLICT"),
        ("foreshadowing_debt", "FORESHADOWING_DEBT"),
        ("style_drift", "STYLE_DRIFT"),
        ("pacing_drift", "PACING_DRIFT"),
        ("antagonist_pressure_drop", "ANTAGONIST_PRESSURE_DROP"),
        ("protagonist_charm_drop", "PROTAGONIST_CHARM_DROP"),
    ):
        value = observations.get(key)
        _add_if(deviations, bool(value), deviation_type, "MAJOR", value)

    blocking = [item for item in deviations if item["severity"] == "BLOCKING"]
    recap = {
        "contract_version": "longform-recap-v1",
        "project_id": project_id,
        "book_id": book_id,
        "chapter_range": [start, end],
        "checkpoint_type": checkpoint_type.value,
        "observation_snapshot": dict(observations),
        "deviation_count": len(deviations),
        "plan_mutation_allowed": False,
        "reader_outcome_consumption": reader_consumption,
    }
    deviation_report = {
        "contract_version": "longform-deviation-report-v1",
        "deviations": deviations,
        "blocking_count": len(blocking),
    }
    required_actions = [
        _required_action_for_deviation(item, chapter_range=(start, end))
        for item in deviations
    ]
    adjustment = {
        "contract_version": "plan-adjustment-proposal-v2",
        "decision_status": "AUTHORITY_PENDING",
        "mutates_plan": False,
        "reader_outcome_consumption": reader_consumption,
        "decision_chain": {
            "observation_range": [start, end],
            "evidence": [item["evidence"] for item in deviations],
            "issues": [
                {"code": item["type"], "severity": item["severity"]}
                for item in deviations
            ],
            "required_actions": required_actions,
            "reevaluation_gate": "longform.recap",
        },
        "proposed_actions": required_actions,
    }
    blocking_actions = [
        action
        for action in required_actions
        if action["severity"] == "BLOCKING"
    ]
    affected_scope = _widest_scope(blocking_actions)
    if checkpoint_decision in {"CORRECT", "REPLAN_REQUIRED"}:
        replan = {
            "type": "ArcRevisionCandidate",
            "contract_version": "arc-revision-candidate-v1",
            "decision_status": "AUTHORITY_PENDING",
            "based_on_checkpoint_id": str(arc_checkpoint.get("checkpoint_id") or ""),
            "projection_set_id": str(arc_checkpoint.get("projection_set_id") or ""),
            "future_from_chapter": end + 1,
            "reason_refs": [item["type"] for item in deviations],
            "reason_evidence": dict(arc_checkpoint.get("reason_evidence") or {}),
            "target_plan_version_ids": list(
                arc_checkpoint.get("target_plan_version_ids") or ()
            ),
            "affected_scope": "ARC",
            "impact_scope": {
                "chapter_range": [end + 1, end + 1],
                "future_only": True,
            },
            "preserved_invariants": [
                "accepted_canon",
                "executed_chapter_history",
                "accepted_arc_actual_state",
                "unaffected_active_plan_versions",
            ],
            "decision_evidence": [dict(arc_checkpoint)],
            "required_authority": "PLAN_CHANGE_AUTHORITY",
            "candidate_only": True,
            "plan_mutation_allowed": False,
        }
    else:
        replan = (
            {
            "contract_version": "book-replan-request-v2",
            "decision_status": "AUTHORITY_PENDING",
            "reason_refs": [item["type"] for item in blocking],
            "affected_scope": affected_scope,
            "impact_scope": {
                "chapter_range": [start, end],
                "future_only": True,
            },
            "preserved_invariants": [
                "accepted_canon",
                "executed_chapter_history",
                "unaffected_active_plan_versions",
            ],
            "decision_evidence": blocking,
            "required_authority": _authority_for_scope(affected_scope),
        }
            if blocking
            else None
        )
    return {
        "recap": recap,
        "deviation_report": deviation_report,
        "adjustment_proposal": adjustment,
        "replan_request": replan,
    }


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _add_if(
    deviations: list[dict[str, Any]],
    condition: bool,
    deviation_type: str,
    severity: str,
    evidence: Any,
) -> None:
    if condition:
        deviations.append(
            {
                "type": deviation_type,
                "severity": severity,
                "evidence": dict(evidence) if isinstance(evidence, Mapping) else evidence,
            }
        )


def _required_action_for_deviation(
    deviation: Mapping[str, Any],
    *,
    chapter_range: tuple[int, int],
) -> dict[str, Any]:
    deviation_type = str(deviation["type"])
    scope = {
        "READER_CONFUSION_RISE": "CHAPTER",
        "REPETITION_FATIGUE": "CHAPTER_GROUP",
        "QUALITY_TREND_DECLINE": "CHAPTER_GROUP",
        "REWARD_CADENCE_FAILURE": "ARC",
        "PROMISE_DEBT": "ARC",
        "ARC_CHECKPOINT_CORRECTION": "ARC",
        "ARC_CHECKPOINT_REPLAN_REQUIRED": "ARC",
        "MAIN_PLOT_STAGNATION": "ARC",
        "ARC_GOAL_DRIFT": "ARC",
        "CHARACTER_ARC_DRIFT": "ARC",
        "CHARACTER_DISAPPEARANCE": "ARC",
        "POWER_INFLATION": "ARC",
        "TIMELINE_CONFLICT": "ARC",
        "FORESHADOWING_DEBT": "ARC",
        "STYLE_DRIFT": "CHAPTER_GROUP",
        "PACING_DRIFT": "CHAPTER_GROUP",
        "ANTAGONIST_PRESSURE_DROP": "ARC",
        "PROTAGONIST_CHARM_DROP": "ARC",
        "CANON_CONFLICT": _canon_conflict_scope(deviation.get("evidence")),
        "ENDING_REACHABILITY_AT_RISK": "BOOK",
    }.get(deviation_type, "CHAPTER")
    action = {
        "CHAPTER": "CHAPTER_ADJUSTMENT",
        "CHAPTER_GROUP": "CHAPTER_GROUP_REPLAN",
        "ARC": "ARC_REPLAN",
        "VOLUME": "VOLUME_REPLAN",
        "BOOK": "BOOK_STRATEGIC_REPLAN",
    }[scope]
    return {
        "deviation_type": deviation_type,
        "severity": str(deviation["severity"]),
        "requested_action": action,
        "affected_scope": scope,
        "impact_scope": {
            "observed_chapter_range": list(chapter_range),
            "future_only": True,
        },
        "preserved_invariants": [
            "accepted_canon",
            "executed_chapter_history",
        ],
        "evidence": deviation["evidence"],
        "requires_authority": _authority_for_scope(scope),
    }


def _widest_scope(actions: Sequence[Mapping[str, Any]]) -> str:
    order = {"CHAPTER": 1, "CHAPTER_GROUP": 2, "ARC": 3, "VOLUME": 4, "BOOK": 5}
    return max(
        (str(item["affected_scope"]) for item in actions),
        key=order.__getitem__,
        default="CHAPTER",
    )


def _canon_conflict_scope(evidence: Any) -> str:
    value = dict(evidence) if isinstance(evidence, Mapping) else {}
    conflicts = [
        dict(item)
        for item in value.get("conflicts") or []
        if isinstance(item, Mapping)
    ]
    if conflicts and all(
        not bool(item.get("executed_content_affected"))
        and str(item.get("target") or "").startswith("chapter:")
        for item in conflicts
    ):
        return "CHAPTER_GROUP"
    return "ARC"


def _authority_for_scope(scope: str) -> str:
    return "CHAPTER_AUTHORITY" if scope == "CHAPTER" else "PLAN_CHANGE_AUTHORITY"


__all__ = [
    "LongformCheckpointType",
    "READER_STATE_DIMENSIONS",
    "ReaderOutcomeGate",
    "build_longform_recap_outputs",
    "evaluate_reader_outcome",
    "should_trigger_longform_recap",
]

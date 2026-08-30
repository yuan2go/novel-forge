from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import math
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from novel_forge.modules.command_kernel.errors import KernelError


class PreferenceChoice(StrEnum):
    A = "A"
    B = "B"
    TIE = "TIE"
    REJECT_BOTH = "REJECT_BOTH"
    CANNOT_JUDGE = "CANNOT_JUDGE"


class BlindScope(StrEnum):
    CHAPTER = "CHAPTER"
    ARC = "ARC"


class EvaluatorIdentityClass(StrEnum):
    PROFESSIONAL_EDITOR = "PROFESSIONAL_EDITOR"
    AUTHOR_EDITOR = "AUTHOR_EDITOR"
    EXPERIENCED_READER = "EXPERIENCED_READER"
    GENERAL_READER = "GENERAL_READER"


BLIND_EVALUATION_DIMENSIONS = (
    "overall_preference",
    "readability",
    "character_credibility",
    "scene_effectiveness",
    "tension_momentum",
    "emotional_impact",
    "prose_quality",
    "continuity",
    "payoff_satisfaction",
    "desire_to_continue",
)


@dataclass(frozen=True, slots=True)
class HumanBlindDecision:

    decision_id: str
    pair_token: str
    reviewer_id: str
    evaluator_identity_class: EvaluatorIdentityClass
    protocol_version: str
    evaluation_version: str
    scope_type: BlindScope
    chapter_start: int
    chapter_end: int
    choice: PreferenceChoice
    dimension_scores: Mapping[str, Mapping[str, int | None]]
    confidence: float
    rationale: str
    evidence_spans: tuple[dict[str, Any], ...]

    def __post_init__(self) -> None:
        for name in (
            "decision_id",
            "pair_token",
            "reviewer_id",
            "protocol_version",
            "evaluation_version",
        ):
            if not str(getattr(self, name) or "").strip():
                raise ValueError(f"{name} is required")
        try:
            identity_class = EvaluatorIdentityClass(self.evaluator_identity_class)
        except ValueError as exc:
            raise ValueError("evaluator identity class is invalid") from exc
        try:
            scope = BlindScope(self.scope_type)
        except ValueError as exc:
            raise ValueError("blind evaluation scope is invalid") from exc
        try:
            choice = PreferenceChoice(self.choice)
        except ValueError as exc:
            raise ValueError("blind preference choice is invalid") from exc
        if choice is PreferenceChoice.REJECT_BOTH:
            raise ValueError("REJECT_BOTH is historical-only in the blind protocol")
        if self.chapter_start <= 0 or self.chapter_end < self.chapter_start:
            raise ValueError("blind evaluation chapter scope is invalid")
        if scope is BlindScope.CHAPTER and self.chapter_start != self.chapter_end:
            raise ValueError("Chapter scope must cover exactly one chapter")
        if not 0 <= self.confidence <= 1:
            raise ValueError("blind evaluation confidence must be between 0 and 1")
        if set(self.dimension_scores) != set(BLIND_EVALUATION_DIMENSIONS):
            raise ValueError(
                "dimension_scores must contain the exact frozen dimensions"
            )
        frozen_scores: dict[str, Mapping[str, int | None]] = {}
        for dimension in BLIND_EVALUATION_DIMENSIONS:
            raw = self.dimension_scores[dimension]
            if not isinstance(raw, Mapping) or set(raw) != {"a", "b"}:
                raise ValueError(f"{dimension} must score candidate a and b")
            a, b = raw["a"], raw["b"]
            if choice is PreferenceChoice.CANNOT_JUDGE and a is None and b is None:
                frozen_scores[dimension] = MappingProxyType({"a": None, "b": None})
                continue
            if (
                not isinstance(a, int)
                or isinstance(a, bool)
                or not isinstance(b, int)
                or isinstance(b, bool)
                or not 1 <= a <= 5
                or not 1 <= b <= 5
            ):
                raise ValueError("dimension scores must be between 1 and 5")
            frozen_scores[dimension] = MappingProxyType({"a": a, "b": b})
        for span in self.evidence_spans:
            if not isinstance(span, dict):
                raise ValueError("evidence spans must be typed objects")
            candidate = str(span.get("candidate") or "")
            start, end = span.get("start"), span.get("end")
            if (
                candidate not in {"A", "B"}
                or not isinstance(start, int)
                or isinstance(start, bool)
                or not isinstance(end, int)
                or isinstance(end, bool)
                or start < 0
                or end <= start
            ):
                raise ValueError("evidence span is outside a blinded candidate")
        object.__setattr__(self, "evaluator_identity_class", identity_class)
        object.__setattr__(self, "scope_type", scope)
        object.__setattr__(self, "choice", choice)
        object.__setattr__(self, "dimension_scores", MappingProxyType(frozen_scores))

    @property
    def preferred_candidate(self) -> str | None:
        return (
            self.choice.value
            if self.choice in {PreferenceChoice.A, PreferenceChoice.B}
            else None
        )


@dataclass(frozen=True, slots=True)
class BlindAdjudication:
    status: str
    adjudicator_id: str
    resolved_choice: PreferenceChoice | None
    rationale: str
    raw_decisions: tuple[HumanBlindDecision, ...]
    evidence_class: str = "SUBJECTIVE_ADJUDICATION_NOT_GROUND_TRUTH"


def reviewer_visible_decisions(
    decisions: Iterable[HumanBlindDecision], reviewer_id: str
) -> tuple[HumanBlindDecision, ...]:

    return tuple(item for item in decisions if item.reviewer_id == reviewer_id)


def adjudicate_blind_decisions(
    decisions: Iterable[HumanBlindDecision],
    *,
    adjudicator_id: str,
    resolved_choice: PreferenceChoice | None,
    rationale: str,
) -> BlindAdjudication:
    rows = tuple(decisions)
    if (
        len(rows) < 2
        or len({item.reviewer_id for item in rows}) < 2
        or len({item.pair_token for item in rows}) != 1
        or not adjudicator_id
        or not rationale.strip()
    ):
        raise ValueError("adjudication requires two independent scoped decisions")
    if resolved_choice is not None:
        resolved_choice = PreferenceChoice(resolved_choice)
        if resolved_choice is PreferenceChoice.REJECT_BOTH:
            raise ValueError("REJECT_BOTH cannot adjudicate the current protocol")
        status = "ADJUDICATED"
    elif len({item.choice for item in rows}) == 1:
        status = "AGREED"
    else:
        status = "DISAGREED"
    return BlindAdjudication(
        status=status,
        adjudicator_id=adjudicator_id,
        resolved_choice=resolved_choice,
        rationale=rationale,
        raw_decisions=rows,
    )


class CalibrationStatus(StrEnum):
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    VALID = "VALID"
    DRIFTED = "DRIFTED"
    INVALID = "INVALID"


class JudgeMode(StrEnum):
    SHADOW = "SHADOW"
    ADVISORY = "ADVISORY"
    BOUNDED_PRODUCTION = "BOUNDED_PRODUCTION"


class ReaderJudgeQualificationStatus(StrEnum):
    UNQUALIFIED = "UNQUALIFIED"
    SHADOW = "SHADOW"
    CALIBRATION_PENDING = "CALIBRATION_PENDING"
    CALIBRATED = "CALIBRATED"
    QUALIFIED = "QUALIFIED"
    DRIFTED = "DRIFTED"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


_QUALIFICATION_TRANSITIONS = {
    ReaderJudgeQualificationStatus.UNQUALIFIED: {
        ReaderJudgeQualificationStatus.SHADOW,
        ReaderJudgeQualificationStatus.RETIRED,
    },
    ReaderJudgeQualificationStatus.SHADOW: {
        ReaderJudgeQualificationStatus.CALIBRATION_PENDING,
        ReaderJudgeQualificationStatus.SUSPENDED,
        ReaderJudgeQualificationStatus.RETIRED,
    },
    ReaderJudgeQualificationStatus.CALIBRATION_PENDING: {
        ReaderJudgeQualificationStatus.CALIBRATED,
        ReaderJudgeQualificationStatus.SHADOW,
        ReaderJudgeQualificationStatus.SUSPENDED,
    },
    ReaderJudgeQualificationStatus.CALIBRATED: {
        ReaderJudgeQualificationStatus.QUALIFIED,
        ReaderJudgeQualificationStatus.DRIFTED,
        ReaderJudgeQualificationStatus.SUSPENDED,
    },
    ReaderJudgeQualificationStatus.QUALIFIED: {
        ReaderJudgeQualificationStatus.DRIFTED,
        ReaderJudgeQualificationStatus.SUSPENDED,
        ReaderJudgeQualificationStatus.RETIRED,
    },
    ReaderJudgeQualificationStatus.DRIFTED: {
        ReaderJudgeQualificationStatus.SHADOW,
        ReaderJudgeQualificationStatus.CALIBRATION_PENDING,
        ReaderJudgeQualificationStatus.SUSPENDED,
        ReaderJudgeQualificationStatus.RETIRED,
    },
    ReaderJudgeQualificationStatus.SUSPENDED: {
        ReaderJudgeQualificationStatus.SHADOW,
        ReaderJudgeQualificationStatus.RETIRED,
    },
    ReaderJudgeQualificationStatus.RETIRED: set(),
}


@dataclass(frozen=True, slots=True)
class ReaderOutcomeDecisionPolicy:
    policy_version: str
    minimum_sample_size: int
    minimum_confidence: float
    minimum_consecutive_chapters: int
    cooldown_chapters: int
    maximum_adjustment_chapters: int
    human_approval_required: bool = True

    def __post_init__(self) -> None:
        if (
            not self.policy_version
            or self.minimum_sample_size <= 0
            or self.minimum_consecutive_chapters <= 0
            or self.cooldown_chapters < 0
            or self.maximum_adjustment_chapters <= 0
            or not 0 <= self.minimum_confidence <= 1
        ):
            raise ValueError("Reader Outcome decision policy is invalid")


DEFAULT_READER_OUTCOME_DECISION_POLICY = ReaderOutcomeDecisionPolicy(
    policy_version="reader-outcome-decision-policy-v1",
    minimum_sample_size=100,
    minimum_confidence=0.8,
    minimum_consecutive_chapters=3,
    cooldown_chapters=3,
    maximum_adjustment_chapters=3,
)


@dataclass(frozen=True, slots=True)
class CalibrationScope:
    platform: str
    genre: str
    subgenre: str
    chapter_type: str
    reader_segment: str
    judge_profile: str
    model_version: str


@dataclass(frozen=True, slots=True)
class CalibrationCandidate:
    profile_id: str
    scope: CalibrationScope
    sample_size: int
    minimum_sample_size: int
    status: CalibrationStatus


def blind_pair_order(
    asset_a_version_id: str,
    asset_b_version_id: str,
    *,
    randomization_key: str,
) -> tuple[str, str]:
    if (
        not asset_a_version_id
        or not asset_b_version_id
        or asset_a_version_id == asset_b_version_id
        or not randomization_key
    ):
        raise ValueError("blind preference pair identity is invalid")
    digest = hashlib.sha256(randomization_key.encode()).digest()
    return (
        (asset_a_version_id, asset_b_version_id)
        if digest[0] % 2 == 0
        else (asset_b_version_id, asset_a_version_id)
    )


def preference_bias_report(
    decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    decisive = [item for item in decisions if item.get("choice") in {"A", "B"}]
    left_choices = sum(
        1
        for item in decisive
        if (item["choice"] == "A" and item.get("asset_a_position") == "LEFT")
        or (item["choice"] == "B" and item.get("asset_b_position") == "LEFT")
    )
    left_rate = left_choices / len(decisive) if decisive else 0.0
    position_bias = bool(decisive) and abs(left_rate - 0.5) >= 0.25
    by_pair: dict[str, list[dict[str, Any]]] = {}
    for item in decisive:
        by_pair.setdefault(str(item.get("canonical_pair_key") or ""), []).append(item)
    reversals = [
        pair
        for pair in by_pair.values()
        if {item.get("presentation_order") for item in pair} >= {"AB", "BA"}
    ]
    consistent = sum(
        1
        for pair in reversals
        if len({item.get("preferred_asset_version_id") for item in pair}) == 1
    )
    return {
        "decision_count": len(decisive),
        "left_choice_rate": left_rate,
        "position_bias_detected": position_bias,
        "reversal_pair_count": len(reversals),
        "reversal_consistency": (consistent / len(reversals) if reversals else None),
    }


def human_agreement_report(
    decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    by_pair: dict[str, list[str]] = {}
    for item in decisions:
        by_pair.setdefault(str(item["pair_id"]), []).append(str(item["choice"]))
    comparable = [items for items in by_pair.values() if len(items) >= 2]
    agreements = 0
    comparisons = 0
    for items in comparable:
        for index, left in enumerate(items):
            for right in items[index + 1 :]:
                comparisons += 1
                agreements += int(left == right)
    return {
        "pair_count": len(by_pair),
        "multi_judge_pair_count": len(comparable),
        "pairwise_comparisons": comparisons,
        "agreement_rate": agreements / comparisons if comparisons else None,
        "status": "MEASURED" if comparisons else "INSUFFICIENT_DATA",
    }


def resolve_calibration_profile(
    scope: CalibrationScope,
    candidates: list[CalibrationCandidate],
) -> CalibrationCandidate | None:
    eligible = [
        item
        for item in candidates
        if item.status is CalibrationStatus.VALID
        and item.sample_size >= item.minimum_sample_size
        and _scope_matches(scope, item.scope)
    ]
    if not eligible:
        return None
    return max(
        eligible,
        key=lambda item: (
            _specificity(scope, item.scope),
            item.sample_size,
            item.profile_id,
        ),
    )


def calibration_metrics(
    observations: list[tuple[float, int]],
    *,
    minimum_sample_size: int,
) -> dict[str, Any]:
    if minimum_sample_size <= 0:
        raise ValueError("minimum sample size must be positive")
    count = len(observations)
    for probability, outcome in observations:
        if not 0 <= probability <= 1 or outcome not in {0, 1}:
            raise ValueError("calibration observations are invalid")
    if count < minimum_sample_size:
        return {
            "sample_size": count,
            "minimum_sample_size": minimum_sample_size,
            "calibration_status": CalibrationStatus.INSUFFICIENT_DATA.value,
            "brier_score": None,
            "log_loss": None,
            "calibration_error": None,
            "behavior_probability_allowed": False,
        }
    epsilon = 1e-12
    brier = sum((p - y) ** 2 for p, y in observations) / count
    log_loss = (
        -sum(
            y * math.log(max(p, epsilon)) + (1 - y) * math.log(max(1 - p, epsilon))
            for p, y in observations
        )
        / count
    )
    predicted = sum(p for p, _ in observations) / count
    observed = sum(y for _, y in observations) / count
    return {
        "sample_size": count,
        "minimum_sample_size": minimum_sample_size,
        "calibration_status": CalibrationStatus.VALID.value,
        "brier_score": brier,
        "log_loss": log_loss,
        "calibration_error": abs(predicted - observed),
        "behavior_probability_allowed": True,
    }


def require_exposure_denominator(
    *, exposure_id: str, project_id: str, reader_segment: str
) -> None:
    if not exposure_id or not project_id or not reader_segment:
        raise KernelError(
            "READER_EXPOSURE_REQUIRED",
            "Reader outcomes require a Project- and Segment-scoped exposure",
        )


def calibrated_probability(
    raw_score: float,
    *,
    calibration_status: CalibrationStatus,
) -> float:
    if calibration_status is not CalibrationStatus.VALID:
        raise KernelError(
            "CALIBRATED_PROBABILITY_FORBIDDEN",
            "uncalibrated or drifted scores remain RAW_SCORE",
        )
    return max(0.0, min(1.0, raw_score))


def mode_after_drift(current_mode: JudgeMode, *, severe_drift: bool) -> JudgeMode:
    return JudgeMode.SHADOW if severe_drift else current_mode


def reader_decision_policy(
    *,
    hard_gate_passed: bool,
    blocking_quality_issues: int,
    calibration_status: CalibrationStatus,
    ood: bool,
    disagreement: bool,
    long_term_outcome: str,
    short_term_outcome: str,
) -> dict[str, Any]:
    if not hard_gate_passed:
        return {"decision": "BLOCKED", "reason": "HARD_GATE"}
    if blocking_quality_issues > 0:
        return {"decision": "BLOCKED", "reason": "BLOCKING_QUALITY"}
    if calibration_status is not CalibrationStatus.VALID:
        return {"decision": "SHADOW_ONLY", "reason": "CALIBRATION_INVALID"}
    if ood or disagreement:
        return {"decision": "HUMAN_REVIEW", "reason": "OOD_OR_DISAGREEMENT"}
    return {
        "decision": "ADVISORY",
        "reason": "CALIBRATED_EVIDENCE",
        "long_term_outcome": long_term_outcome,
        "short_term_outcome": short_term_outcome,
    }


def transition_reader_judge_qualification(
    current: ReaderJudgeQualificationStatus,
    target: ReaderJudgeQualificationStatus,
    *,
    evidence_level: str,
    sample_size: int,
    minimum_sample_size: int,
    drift_detected: bool,
) -> ReaderJudgeQualificationStatus:
    current = ReaderJudgeQualificationStatus(current)
    target = ReaderJudgeQualificationStatus(target)
    if target not in _QUALIFICATION_TRANSITIONS[current]:
        raise KernelError(
            "READER_JUDGE_QUALIFICATION_TRANSITION_INVALID",
            f"Reader Judge cannot transition from {current.value} to {target.value}",
        )
    if target is ReaderJudgeQualificationStatus.QUALIFIED and (
        evidence_level != "BEHAVIOR_CALIBRATED"
        or sample_size < minimum_sample_size
        or drift_detected
    ):
        raise KernelError(
            "READER_JUDGE_QUALIFICATION_EVIDENCE_INSUFFICIENT",
            "QUALIFIED Reader Judge requires enough behavior evidence and no drift",
        )
    if evidence_level == "FIXTURE" and target in {
        ReaderJudgeQualificationStatus.CALIBRATED,
        ReaderJudgeQualificationStatus.QUALIFIED,
    }:
        raise KernelError(
            "READER_JUDGE_FIXTURE_QUALIFICATION_FORBIDDEN",
            "Fixture evidence cannot qualify a Reader Judge",
        )
    return target


def evaluate_reader_outcome_consumption(
    *,
    qualification_status: ReaderJudgeQualificationStatus,
    sample_size: int,
    confidence: float,
    recent_reports: list[dict[str, Any]],
    current_chapter: int,
    last_adjustment_chapter: int | None,
    disagreement: bool,
    position_bias: bool,
    ood: bool,
    drift_detected: bool,
    policy: ReaderOutcomeDecisionPolicy = DEFAULT_READER_OUTCOME_DECISION_POLICY,
) -> dict[str, Any]:
    status = ReaderJudgeQualificationStatus(qualification_status)
    activation_blockers: list[str] = []
    if status is not ReaderJudgeQualificationStatus.QUALIFIED:
        activation_blockers.append("JUDGE_NOT_QUALIFIED")
    if sample_size < policy.minimum_sample_size:
        activation_blockers.append("MINIMUM_SAMPLE_NOT_MET")
    if confidence < policy.minimum_confidence:
        activation_blockers.append("CONFIDENCE_BELOW_POLICY")
    if disagreement:
        activation_blockers.append("JUDGE_DISAGREEMENT")
    if position_bias:
        activation_blockers.append("POSITION_BIAS")
    if ood:
        activation_blockers.append("OOD")
    if drift_detected or status is ReaderJudgeQualificationStatus.DRIFTED:
        activation_blockers.append("DRIFT")
    if current_chapter <= 0:
        raise ValueError("Reader Outcome consumption requires a positive chapter")
    if (
        last_adjustment_chapter is not None
        and current_chapter - last_adjustment_chapter < policy.cooldown_chapters
    ):
        activation_blockers.append("COOLDOWN_ACTIVE")
    trend_blockers: list[str] = []
    usable_reports = recent_reports[-policy.minimum_consecutive_chapters :]
    if len(usable_reports) < policy.minimum_consecutive_chapters:
        trend_blockers.append("TREND_WINDOW_INSUFFICIENT")
    elif not all(bool(item.get("declining")) for item in usable_reports):
        trend_blockers.append("NO_CONSECUTIVE_DECLINE")
    advisory_allowed = not trend_blockers
    activation_eligible = advisory_allowed and not activation_blockers
    if activation_eligible:
        decision = "PLAN_ADJUSTMENT_CANDIDATE"
    elif advisory_allowed:
        decision = "ADVISORY_RECOMMENDATION"
    else:
        decision = "SHADOW_ONLY"
    return {
        "contract_version": "reader-outcome-consumption-decision-v2",
        "policy_version": policy.policy_version,
        "evidence_class": "READER_PROXY_ADVISORY",
        "decision": decision,
        "advisory_recommendation_allowed": advisory_allowed,
        "activation_eligible": activation_eligible,
        # Compatibility field: influence means eligibility to enter the
        # governed future-plan change path, never direct mutation.
        "future_production_influence_allowed": activation_eligible,
        "direct_plan_activation_allowed": False,
        "direct_body_mutation_allowed": False,
        "direct_canon_mutation_allowed": False,
        "future_intent_actualization_allowed": False,
        "human_approval_required": policy.human_approval_required,
        "maximum_adjustment_chapters": policy.maximum_adjustment_chapters,
        "activation_blockers": activation_blockers,
        "trend_blockers": trend_blockers,
        "reasons": [*activation_blockers, *trend_blockers],
    }


def _scope_matches(requested: CalibrationScope, candidate: CalibrationScope) -> bool:
    return all(
        getattr(candidate, field) in {"*", getattr(requested, field)}
        for field in CalibrationScope.__dataclass_fields__
    )


def _specificity(requested: CalibrationScope, candidate: CalibrationScope) -> int:
    return sum(
        getattr(candidate, field) == getattr(requested, field)
        for field in CalibrationScope.__dataclass_fields__
    )


__all__ = [
    "BLIND_EVALUATION_DIMENSIONS",
    "BlindAdjudication",
    "BlindScope",
    "CalibrationCandidate",
    "CalibrationScope",
    "CalibrationStatus",
    "JudgeMode",
    "EvaluatorIdentityClass",
    "HumanBlindDecision",
    "ReaderJudgeQualificationStatus",
    "ReaderOutcomeDecisionPolicy",
    "DEFAULT_READER_OUTCOME_DECISION_POLICY",
    "PreferenceChoice",
    "blind_pair_order",
    "adjudicate_blind_decisions",
    "calibrated_probability",
    "calibration_metrics",
    "human_agreement_report",
    "mode_after_drift",
    "preference_bias_report",
    "reader_decision_policy",
    "evaluate_reader_outcome_consumption",
    "require_exposure_denominator",
    "resolve_calibration_profile",
    "reviewer_visible_decisions",
    "transition_reader_judge_qualification",
]

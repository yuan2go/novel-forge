from __future__ import annotations

import json

import pytest

from novel_forge.modules.reader_calibration.blind_export import (
    BlindComparisonSubject,
    BlindEvaluator,
    export_blind_evaluation_packs,
)
from novel_forge.modules.reader_calibration.domain import (
    BLIND_EVALUATION_DIMENSIONS,
    BlindScope,
    EvaluatorIdentityClass,
    HumanBlindDecision,
    PreferenceChoice,
    adjudicate_blind_decisions,
    reviewer_visible_decisions,
)


def _scores(a: int = 4, b: int = 3) -> dict[str, dict[str, int]]:
    return {
        dimension: {"a": a, "b": b}
        for dimension in BLIND_EVALUATION_DIMENSIONS
    }


def _decision(
    reviewer: str,
    choice: PreferenceChoice = PreferenceChoice.A,
    *,
    scores: dict[str, object] | None = None,
    confidence: float = 0.8,
) -> HumanBlindDecision:
    return HumanBlindDecision(
        decision_id=f"decision:{reviewer}",
        pair_token="pair:opaque",
        reviewer_id=reviewer,
        evaluator_identity_class=EvaluatorIdentityClass.PROFESSIONAL_EDITOR,
        protocol_version="human-blind-comparison-v1",
        evaluation_version="editorial-pairwise-v1",
        scope_type=BlindScope.CHAPTER,
        chapter_start=1,
        chapter_end=1,
        choice=choice,
        dimension_scores=scores if scores is not None else _scores(),
        confidence=confidence,
        rationale="The choice follows the visible scene evidence.",
        evidence_spans=({"candidate": "A", "start": 0, "end": 12},),
    )


def _subjects() -> tuple[BlindComparisonSubject, ...]:
    chapters = tuple(
        BlindComparisonSubject(
            subject_id=f"subject:chapter:{chapter}",
            scope_type=BlindScope.CHAPTER,
            chapter_start=chapter,
            chapter_end=chapter,
            canonical_asset_version_id=f"canonical:chapter:{chapter}:v1",
            baseline_asset_version_id=f"baseline:chapter:{chapter}:v1",
            canonical_text=f"The first rendered story sequence reaches chapter {chapter}.",
            baseline_text=f"The alternate rendered story sequence reaches chapter {chapter}.",
            arc_plan_version_ids=("arc:primary:v1",),
        )
        for chapter in range(1, 7)
    )
    arc = BlindComparisonSubject(
        subject_id="subject:arc:primary",
        scope_type=BlindScope.ARC,
        chapter_start=1,
        chapter_end=6,
        canonical_asset_version_id="canonical:arc:primary:v1",
        baseline_asset_version_id="baseline:arc:primary:v1",
        canonical_text="The first complete story sequence closes its primary turn.",
        baseline_text="The alternate complete story sequence closes its primary turn.",
        arc_plan_version_ids=("arc:primary:v1",),
    )
    return (*chapters, arc)


def _evaluators() -> tuple[BlindEvaluator, BlindEvaluator]:
    return (
        BlindEvaluator(
            reviewer_id="human-reviewer-1",
            identity_class=EvaluatorIdentityClass.PROFESSIONAL_EDITOR,
        ),
        BlindEvaluator(
            reviewer_id="human-reviewer-2",
            identity_class=EvaluatorIdentityClass.EXPERIENCED_READER,
        ),
    )


def test_cannot_judge_has_no_preferred_candidate_and_allows_null_scores() -> None:
    decision = _decision(
        "reviewer-1",
        PreferenceChoice.CANNOT_JUDGE,
        scores={
            dimension: {"a": None, "b": None}
            for dimension in BLIND_EVALUATION_DIMENSIONS
        },
        confidence=0.2,
    )

    assert decision.preferred_candidate is None
    assert decision.choice is PreferenceChoice.CANNOT_JUDGE


@pytest.mark.parametrize(
    ("scores", "message"),
    [
        (
            {key: value for key, value in _scores().items() if key != "continuity"},
            "exact frozen dimensions",
        ),
        (
            {**_scores(), "continuity": {"a": 6, "b": 3}},
            "between 1 and 5",
        ),
        (
            {**_scores(), "continuity": {"a": 4}},
            "candidate a and b",
        ),
    ],
)
def test_dimension_scores_are_exact_and_ordinal(
    scores: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _decision("reviewer-invalid", scores=scores)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("protocol_version", "", "protocol_version"),
        ("evaluation_version", "", "evaluation_version"),
        ("evaluator_identity_class", "UNKNOWN", "evaluator identity"),
        ("scope_type", BlindScope.CHAPTER, "Chapter scope"),
        ("confidence", 1.1, "confidence"),
    ],
)
def test_decision_validates_version_identity_scope_and_confidence(
    field: str, value: object, message: str
) -> None:
    values = {
        "decision_id": "decision:invalid",
        "pair_token": "pair:opaque",
        "reviewer_id": "reviewer-invalid",
        "evaluator_identity_class": EvaluatorIdentityClass.PROFESSIONAL_EDITOR,
        "protocol_version": "human-blind-comparison-v1",
        "evaluation_version": "editorial-pairwise-v1",
        "scope_type": BlindScope.ARC,
        "chapter_start": 1,
        "chapter_end": 6,
        "choice": PreferenceChoice.A,
        "dimension_scores": _scores(),
        "confidence": 0.8,
        "rationale": "evidence",
        "evidence_spans": (),
    }
    values[field] = value
    if field == "scope_type":
        values["chapter_end"] = 6
    with pytest.raises((ValueError, TypeError), match=message):
        HumanBlindDecision(**values)  # type: ignore[arg-type]


def test_two_reviewer_packs_are_balanced_complementary_and_story_ordered() -> None:
    bundle = export_blind_evaluation_packs(
        campaign_token="campaign:opaque",
        campaign_version=1,
        protocol_version="human-blind-comparison-v1",
        evaluation_version="editorial-pairwise-v1",
        campaign_secret="secret-that-never-leaves-authority",
        evaluators=_evaluators(),
        subjects=_subjects(),
    )
    first = bundle.packs["human-reviewer-1"]
    second = bundle.packs["human-reviewer-2"]
    first_chapters = [item for item in first.private_mapping if item.scope_type is BlindScope.CHAPTER]
    second_by_subject = {item.subject_id: item for item in second.private_mapping}

    assert len(first_chapters) == 6
    assert sum(item.canonical_position == "A" for item in first_chapters) == 3
    assert [item.chapter_start for item in first_chapters] == list(range(1, 7))
    assert all(
        second_by_subject[item.subject_id].canonical_position
        != item.canonical_position
        for item in first.private_mapping
    )
    assert first.public_payload["pairs"][-1]["scope"]["type"] == "ARC"


def test_pack_replay_is_deterministic_and_new_campaign_version_changes_order() -> None:
    common = {
        "campaign_token": "campaign:opaque",
        "protocol_version": "human-blind-comparison-v1",
        "evaluation_version": "editorial-pairwise-v1",
        "campaign_secret": "frozen-secret",
        "evaluators": _evaluators(),
        "subjects": _subjects(),
    }
    first = export_blind_evaluation_packs(campaign_version=1, **common)
    replay = export_blind_evaluation_packs(campaign_version=1, **common)
    next_version = export_blind_evaluation_packs(campaign_version=2, **common)

    assert first.packs["human-reviewer-1"].content_hash == replay.packs["human-reviewer-1"].content_hash
    assert first.packs["human-reviewer-1"].public_payload == replay.packs["human-reviewer-1"].public_payload
    assert [item.canonical_position for item in first.packs["human-reviewer-1"].private_mapping] != [
        item.canonical_position
        for item in next_version.packs["human-reviewer-1"].private_mapping
    ]


def test_export_contains_only_opaque_tokens_and_no_system_identity_leakage() -> None:
    bundle = export_blind_evaluation_packs(
        campaign_token="campaign:opaque",
        campaign_version=1,
        protocol_version="human-blind-comparison-v1",
        evaluation_version="editorial-pairwise-v1",
        campaign_secret="frozen-secret",
        evaluators=_evaluators(),
        subjects=_subjects(),
    )

    for pack in bundle.packs.values():
        rendered = json.dumps(pack.public_payload, ensure_ascii=False).lower()
        for forbidden in (
            "canonical:",
            "baseline:",
            "asset_version",
            "provider",
            "model",
            "prompt",
            "judge_score",
            "judge_model",
            "automated_judge",
            "system_score",
            "branch",
            "private_mapping",
            "frozen-secret",
        ):
            assert forbidden not in rendered
        assert "candidate_a" in rendered
        assert "candidate_b" in rendered
        assert pack.content_hash.startswith("sha256:")
        assert pack.private_mapping_hash.startswith("sha256:")


def test_reviewer_visibility_and_adjudication_preserve_raw_decisions() -> None:
    first = _decision("reviewer-1", PreferenceChoice.A)
    second = _decision("reviewer-2", PreferenceChoice.B)

    assert reviewer_visible_decisions((first, second), "reviewer-1") == (first,)
    disagreement = adjudicate_blind_decisions(
        (first, second),
        adjudicator_id="adjudicator-1",
        resolved_choice=None,
        rationale="Independent reviewers disagree.",
    )
    resolved = adjudicate_blind_decisions(
        (first, second),
        adjudicator_id="adjudicator-1",
        resolved_choice=PreferenceChoice.TIE,
        rationale="Both versions have material strengths and weaknesses.",
    )

    assert disagreement.status == "DISAGREED"
    assert disagreement.raw_decisions == (first, second)
    assert resolved.status == "ADJUDICATED"
    assert resolved.resolved_choice is PreferenceChoice.TIE
    assert resolved.raw_decisions == (first, second)

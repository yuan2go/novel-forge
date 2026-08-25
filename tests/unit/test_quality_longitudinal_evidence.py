from __future__ import annotations

from dataclasses import asdict

from novel_forge.modules.chapter_quality_authority.longitudinal import (
    READER_OUTCOME_DIMENSIONS,
    REPETITION_DIMENSIONS,
    build_arc_quality_evaluation,
    build_longitudinal_quality_evidence,
    build_volume_slice_quality_evaluation,
)


def _observation(chapter: int, **overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "project_id": "project:quality",
        "book_id": "book:quality",
        "chapter_number": chapter,
        "acceptance_id": f"acceptance:{chapter}",
        "accepted_asset_version_id": f"outcome:{chapter}:v1",
        "acceptance_status": "COMMITTED",
        "activity_event_count": 1,
        "causal_progress_event_ids": [f"cause:{chapter}"],
        "irreversible_state_change_ids": [],
        "goal_progress_units": 1,
        "obstacle_escalation": chapter > 1,
        "protagonist_decision_ids": [f"decision:{chapter}"],
        "antagonist_response_ids": [f"response:{chapter}"],
        "ending_propulsion": True,
        "arc_evidence": [
            {
                "arc_plan_version_id": "arc:primary:v1",
                "observation_status": "OBSERVED",
                "progress_units": 1,
                "actual_consequences": [f"consequence:{chapter}"],
                "milestone_ids": [],
                "completion_criterion_ids": [],
                "phase_to": "RISING",
            }
        ],
        "obligation_states": [],
        "semantic_repetition_signatures": {},
        "lexical_fingerprints": [],
        "reader_outcome": {},
        "reader_outcome_asset_version_ids": [],
    }
    value.update(overrides)
    return value


def test_activity_without_causal_progress_is_stagnation() -> None:
    rows = [
        _observation(
            chapter,
            activity_event_count=5,
            causal_progress_event_ids=[],
            irreversible_state_change_ids=[],
            goal_progress_units=0,
            protagonist_decision_ids=[],
            antagonist_response_ids=[],
            obstacle_escalation=False,
            ending_propulsion=False,
            arc_evidence=[],
        )
        for chapter in range(1, 5)
    ]

    report = build_longitudinal_quality_evidence(rows)

    assert report.momentum.status == "STAGNATING"
    assert report.momentum.activity_chapters == (1, 2, 3, 4)
    assert report.momentum.progress_chapters == ()
    assert report.momentum.stagnation_chapters == (1, 2, 3, 4)


def test_momentum_retains_causal_change_decision_and_antagonist_evidence() -> None:
    rows = [
        _observation(
            chapter,
            irreversible_state_change_ids=(
                [f"irreversible:{chapter}"] if chapter in {2, 6} else []
            ),
            protagonist_decision_ids=[f"decision:{chapter}:1", f"decision:{chapter}:2"],
            antagonist_response_ids=([f"response:{chapter}"] if chapter >= 3 else []),
        )
        for chapter in range(1, 9)
    ]

    momentum = build_longitudinal_quality_evidence(rows).momentum

    assert momentum.status == "SUSTAINED"
    assert momentum.causal_event_coverage == 1.0
    assert momentum.irreversible_change_chapters == (2, 6)
    assert momentum.protagonist_decision_count == 16
    assert momentum.antagonist_response_count == 6
    assert momentum.ending_propulsion_chapters == tuple(range(1, 9))


def test_promise_ledger_tracks_full_lifecycle_without_inventing_memory() -> None:
    rows = []
    for chapter in range(1, 9):
        promises: list[dict[str, object]] = []
        if chapter <= 4:
            promises.append(
                {
                    "obligation_id": "promise:paid",
                    "status": (
                        "FULFILLED"
                        if chapter == 4
                        else "DEVELOPING"
                        if chapter >= 2
                        else "OPEN"
                    ),
                    "opened_chapter": 1,
                    "target_window": {"from_chapter": 3, "to_chapter": 4},
                    "development_history": [
                        {"chapter": value} for value in range(1, min(chapter, 3) + 1)
                    ],
                    "payoff_evidence": (
                        {"asset_version_id": "draft:4", "event_id": "payoff:4"}
                        if chapter == 4
                        else {}
                    ),
                    "linked_arc_ids": ["arc:primary:v1"],
                }
            )
        if chapter <= 6:
            promises.append(
                {
                    "obligation_id": "promise:abandoned",
                    "status": "CANCELLED" if chapter == 6 else "OPEN",
                    "opened_chapter": 1,
                    "target_window": {"from_chapter": 2, "to_chapter": 2},
                    "development_history": [{"chapter": 1}],
                    "payoff_evidence": {},
                    "linked_arc_ids": ["arc:primary:v1"],
                }
            )
        if chapter >= 2 and chapter <= 4:
            promises.append(
                {
                    "obligation_id": "promise:partial",
                    "status": "FULFILLED" if chapter == 4 else "OPEN",
                    "opened_chapter": 2,
                    "target_window": {"from_chapter": 4, "to_chapter": 4},
                    "actual_payoff": {"complete": False} if chapter == 4 else {},
                    "payoff_evidence": (
                        {"asset_version_id": "draft:4", "event_id": "payoff:partial"}
                        if chapter == 4
                        else {}
                    ),
                    "linked_arc_ids": ["arc:primary:v1"],
                }
            )
        rows.append(_observation(chapter, obligation_states=promises))

    evidence = build_longitudinal_quality_evidence(rows).promise_payoff
    timelines = {item.obligation_id: item for item in evidence.timelines}

    assert timelines["promise:paid"].transitions == (
        "CREATED",
        "ESCALATED",
        "ESCALATED",
        "PAID",
    )
    assert "DUE" in timelines["promise:paid"].chapter_states[2][1]
    assert "OVERDUE" in timelines["promise:abandoned"].transitions
    assert timelines["promise:abandoned"].transitions[-1] == "ABANDONED"
    assert timelines["promise:partial"].transitions[-1] == "PARTIALLY_PAID"
    assert evidence.payoff_latencies == (2, 3)
    assert evidence.payoff_chapters == (4, 4)
    assert evidence.payoff_clustering is True
    assert evidence.repeated_delay_ids == ("promise:abandoned",)
    assert evidence.false_promise_ids == ("promise:abandoned",)


def test_semantic_repetition_dimensions_stay_separate_from_lexical_similarity() -> None:
    rows = [
        _observation(
            chapter,
            semantic_repetition_signatures={
                "scene_function": ["INTERROGATION"],
                "conflict_solution": [f"solution:{chapter}"],
                "plot_pattern": [f"plot:{chapter}"],
            },
            lexical_fingerprints=["lexical:same"],
        )
        for chapter in range(1, 5)
    ]

    repetition = build_longitudinal_quality_evidence(rows).repetition

    assert set(repetition) == set(REPETITION_DIMENSIONS)
    assert repetition["scene_function"].status == "FATIGUE_RISK"
    assert repetition["conflict_solution"].status == "DIVERSE"
    assert repetition["plot_pattern"].status == "DIVERSE"
    assert repetition["plot_pattern"].lexical_similarity_decides is False
    assert repetition["protagonist_reaction"].status == "NOT_OBSERVED"


def test_reader_proxy_trends_keep_all_dimensions_and_source_lineage() -> None:
    rows = [
        _observation(
            chapter,
            reader_outcome={
                dimension: (
                    chapter / 10
                    if dimension not in {"confusion", "drop_risk", "repetition_fatigue"}
                    else (9 - chapter) / 10
                )
                for dimension in READER_OUTCOME_DIMENSIONS
            },
            reader_outcome_asset_version_ids=[f"reader-outcome:{chapter}:v3"],
        )
        for chapter in range(1, 9)
    ]

    report = build_longitudinal_quality_evidence(rows)

    assert set(report.reader_trends) == set(READER_OUTCOME_DIMENSIONS)
    assert report.reader_trends["continue_intent"].trend == "IMPROVING"
    assert report.reader_trends["confusion"].trend == "IMPROVING"
    assert report.reader_trends["continue_intent"].evidence_class == "READER_PROXY_ADVISORY"
    assert report.source_acceptance_ids == tuple(f"acceptance:{i}" for i in range(1, 9))
    assert report.reader_source_asset_version_ids == tuple(
        f"reader-outcome:{i}:v3" for i in range(1, 9)
    )


def test_missing_semantic_dimensions_are_not_observed_not_zero() -> None:
    row = _observation(
        1,
        activity_event_count=None,
        causal_progress_event_ids=None,
        irreversible_state_change_ids=None,
        goal_progress_units=None,
        protagonist_decision_ids=None,
        antagonist_response_ids=None,
        obstacle_escalation=None,
        ending_propulsion=None,
        arc_evidence=None,
    )

    report = build_longitudinal_quality_evidence([row])

    assert report.momentum.status == "NOT_OBSERVED"
    assert report.promise_payoff.status == "NOT_OBSERVED"
    assert all(item.status == "NOT_OBSERVED" for item in report.repetition.values())
    assert all(item.status == "NOT_OBSERVED" for item in report.reader_trends.values())


def test_arc_evaluation_uses_causal_progress_not_chapter_score_average() -> None:
    rows = [
        _observation(
            chapter,
            automated_editorial_score=99,
            causal_progress_event_ids=[],
            goal_progress_units=0,
            antagonist_response_ids=[],
            arc_evidence=[
                {
                    "arc_plan_version_id": "arc:stagnant:v1",
                    "observation_status": "OBSERVED",
                    "progress_units": 0,
                    "actual_consequences": [],
                    "milestone_ids": [],
                    "completion_criterion_ids": [],
                    "phase_to": "RISING",
                }
            ],
        )
        for chapter in range(1, 5)
    ]

    arc = build_arc_quality_evaluation(rows, arc_plan_version_id="arc:stagnant:v1")

    assert arc.status == "STAGNATING"
    assert arc.causal_progression is False
    assert "average_chapter_score" not in asdict(arc)


def test_volume_slice_evaluation_does_not_average_arc_or_chapter_scores() -> None:
    rows = [_observation(chapter, automated_editorial_score=100) for chapter in range(1, 9)]
    primary = build_arc_quality_evaluation(rows, arc_plan_version_id="arc:primary:v1")
    volume = build_volume_slice_quality_evaluation(
        rows,
        arc_evaluations=(primary,),
        volume_scope_id="volume:slice:1-8",
    )

    assert volume.status == "PROGRESSING"
    payload = asdict(volume)
    assert "average_chapter_score" not in payload
    assert "average_arc_score" not in payload
    assert volume.chapter_range == (1, 8)
    assert volume.ending_reachability == "IMPROVING"


from __future__ import annotations

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_planning_runtime.narrative_search import (
    CREATIVE_INTELLIGENCE_DIMENSIONS,
    NARRATIVE_SEARCH_PROJECTION_VERSION,
    NarrativeSearchCandidate,
    NarrativeSearchProjection,
    compare_narrative_futures,
)
from novel_forge.modules.story_planning_runtime.domain import (
    GENERATOR_INPUT_ROLES,
    StoryPlanningGenerationCommand,
)
from novel_forge.modules.story_planning_runtime.search_application import (
    NarrativeSearchRequest,
)


def _projection(fingerprint: str, score: float) -> dict[str, object]:
    return {
        "contract_version": NARRATIVE_SEARCH_PROJECTION_VERSION,
        "strategy_fingerprint": fingerprint,
        "assumptions": ["accepted reality remains immutable"],
        "projected_consequences": ["the protagonist pays for a chosen action"],
        "narrative_opportunities": ["the relationship pressure opens a new path"],
        "narrative_risks": ["one payoff window becomes narrower"],
        "irreversible_decisions": [],
        "future_options": ["world consequence", "relationship reversal"],
        "repetition_keys": [fingerprint],
        "creative_intelligence": {
            dimension: score for dimension in CREATIVE_INTELLIGENCE_DIMENSIONS
        },
        "selection_summary": f"qualified {fingerprint}",
    }


def _candidate(
    identity: str, fingerprint: str, score: float
) -> NarrativeSearchCandidate:
    return NarrativeSearchCandidate(
        candidate_asset_version_id=identity,
        generation_operation_id=f"generation:{identity}",
        branch_key=f"branch:{identity}",
        projection=NarrativeSearchProjection.from_mapping(
            _projection(fingerprint, score)
        ),
        qualification_hash="sha256:" + identity * 64,
    )


def test_search_compares_qualified_futures_and_preserves_rejected_lineage() -> None:
    comparison = compare_narrative_futures(
        (_candidate("a", "agency", 0.72), _candidate("b", "consequence", 0.91))
    )

    assert comparison.selected_candidate_asset_version_id == "b"
    assert comparison.rejected_candidate_asset_version_ids == ("a",)
    assert [item["rank"] for item in comparison.ranked_candidates] == [1, 2]
    assert comparison.to_dict()["policy_version"]


def test_search_rejects_superficial_non_divergence() -> None:
    with pytest.raises(KernelError, match="NARRATIVE_SEARCH_NOT_DIVERGENT"):
        compare_narrative_futures(
            (_candidate("a", "same", 0.7), _candidate("b", "same", 0.8))
        )


@pytest.mark.parametrize(
    "field",
    [
        "source_plot",
        "source_event_sequence",
        "source_character_replacement",
        "raw_expression",
        "ready_made_plot",
    ],
)
def test_search_projection_rejects_source_specific_reuse(field: str) -> None:
    value = _projection("safe-abstraction", 0.8)
    value[field] = "distinctive source sequence"

    with pytest.raises(
        KernelError, match="NARRATIVE_SEARCH_SOURCE_ISOLATION_VIOLATION"
    ):
        NarrativeSearchProjection.from_mapping(value)


def test_search_projection_requires_complete_creative_intelligence() -> None:
    value = _projection("incomplete", 0.8)
    del value["creative_intelligence"]["future_optionality"]  # type: ignore[index]

    with pytest.raises(KernelError, match="NARRATIVE_SEARCH_INTELLIGENCE_INVALID"):
        NarrativeSearchProjection.from_mapping(value)


def test_continuing_search_requires_exact_book_run_identity() -> None:
    command = StoryPlanningGenerationCommand(
        project_id="project:test",
        workspace_id="workspace:test",
        book_id="book:test",
        actor_id="planner:test",
        generator_operation_name="book_plan.generate",
        logical_key="book:test:main",
        input_versions={
            role: f"asset:{role}:v1"
            for role in GENERATOR_INPUT_ROLES["book_plan.generate"]
        },
        idempotency_key="search:test",
        trace_id="trace:test",
        correlation_id="correlation:test",
    )

    with pytest.raises(ValueError, match="Book Run"):
        NarrativeSearchRequest(
            generation=command,
            planning_horizon={"level": "BOOK"},
            desired_transformation={"goal": "escalate"},
            hard_constraints=("accepted reality is immutable",),
            accepted_through_chapter=1,
            parent_state_asset_version_id="story-state:v1",
        )


def test_work_selection_does_not_call_a_small_score_difference_best() -> None:
    policy = {
        "contract_version": "narrative-search-comparison.v2",
        "dimension_weights": {key: 1 for key in CREATIVE_INTELLIGENCE_DIMENSIONS},
        "uncertainty_margin": 0.03,
        "tie_break": "STABLE_ID",
    }
    a, b = _candidate("a", "agency", 0.8), _candidate("b", "consequence", 0.81)
    comparison = compare_narrative_futures((b, a), selection_policy=policy)
    assert comparison.selected_candidate_asset_version_id == "a"
    assert (
        comparison.selection_evidence["selection_basis"]
        == "AUTHORIZED_STABLE_TIE_BREAK"
    )
    assert comparison.selection_evidence["literary_superiority"] == "NOT_PROVEN"
    assert (
        comparison.to_dict()
        == compare_narrative_futures((a, b), selection_policy=policy).to_dict()
    )
    assert "selection_evidence" not in compare_narrative_futures((a, b)).to_dict()


def test_work_selection_rejects_nonfinite_weights_and_unapproved_tie_policy() -> None:
    policy = {
        "contract_version": "narrative-search-comparison.v2",
        "dimension_weights": {key: 1 for key in CREATIVE_INTELLIGENCE_DIMENSIONS},
        "uncertainty_margin": 0.03,
        "tie_break": "STABLE_ID",
    }
    candidates = (_candidate("a", "agency", 0.8), _candidate("b", "consequence", 0.81))
    for invalid in (
        {**policy, "tie_break": "FIRST"},
        {**policy, "uncertainty_margin": float("nan")},
        {
            **policy,
            "dimension_weights": {key: 0 for key in CREATIVE_INTELLIGENCE_DIMENSIONS},
        },
    ):
        with pytest.raises(
            KernelError, match="NARRATIVE_SEARCH_SELECTION_POLICY_INVALID"
        ):
            compare_narrative_futures(candidates, selection_policy=invalid)

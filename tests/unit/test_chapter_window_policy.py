from dataclasses import replace

import pytest

from novel_forge.modules.hierarchical_planning.window_policy import ChapterWindowPolicy
from novel_forge.modules.chapter_group_authority.domain import ChapterGroupRange


def test_window_policy_accepts_terminal_and_risk_driven_positive_sizes() -> None:
    policy = ChapterWindowPolicy(maximum_chapters=12)
    for count in (1, 2, 3, 8, 9, 12):
        policy.require_range(11, 10 + count)
        assert ChapterGroupRange(11, 10 + count).count == count
    assert policy.select(start=12, target=12, preferred=8) == (12, 12)
    assert policy.select(start=11, target=12, preferred=8) == (11, 12)


def test_window_policy_is_versioned_and_fails_closed_on_invalid_budgets() -> None:
    policy = ChapterWindowPolicy()
    assert policy.digest != replace(policy, maximum_chapters=12).digest
    assert policy.digest != replace(policy, version="2.0.0").digest
    with pytest.raises(ValueError, match="operating policy"):
        policy.require_range(1, 9)
    for count in (0, -1, True, 2.5):
        with pytest.raises(ValueError):
            ChapterWindowPolicy(maximum_chapters=count)
    for bounds in ((0, 1), (2, 1), (True, 1)):
        with pytest.raises(ValueError):
            policy.require_range(*bounds)


def test_provider_schema_and_search_validate_one_frozen_execution_window() -> None:
    from novel_forge.modules.hierarchical_planning import PlanContractType
    from novel_forge.modules.story_planning_runtime.execution import (
        planning_provider_output_schema,
    )
    from novel_forge.modules.story_planning_runtime.search_application import (
        NarrativeSearchRequest,
    )
    from tests.unit.test_story_planning_runtime import _command

    horizon = {
        "level": "CHAPTER_GROUP",
        "chapter_range": [1, 9],
        "starts_at_chapter": 1,
        "ends_at_chapter": 9,
    }
    command = _command("chapter_group_plan.generate")
    with pytest.raises(ValueError, match="operating policy"):
        NarrativeSearchRequest(
            generation=command,
            accepted_through_chapter=0,
            planning_horizon=horizon,
            desired_transformation={"change": "costly alliance"},
            hard_constraints=("accepted reality is immutable",),
        )
    with pytest.raises(ValueError, match="operating policy"):
        planning_provider_output_schema(
            PlanContractType.CHAPTER_GROUP,
            narrative_search=True,
            narrative_search_horizon=horizon,
        )
    policy = ChapterWindowPolicy(maximum_chapters=12)
    command = replace(command, chapter_window_policy=policy.snapshot())
    request = NarrativeSearchRequest(
        generation=command,
        accepted_through_chapter=0,
        planning_horizon=horizon,
        desired_transformation={"change": "costly alliance"},
        hard_constraints=("accepted reality is immutable",),
    )
    schema = planning_provider_output_schema(
        PlanContractType.CHAPTER_GROUP,
        narrative_search=True,
        narrative_search_horizon=request.planning_horizon,
        chapter_window_policy=command.chapter_window_policy,
    )
    assert schema["properties"]["chapter_function_matrix"]["maxItems"] == 9
    ordinary = planning_provider_output_schema(
        PlanContractType.CHAPTER_GROUP,
        chapter_window_policy=command.chapter_window_policy,
    )
    assert ordinary["properties"]["chapter_function_matrix"]["maxItems"] == 12
    from novel_forge.modules.story_planning_runtime.application import (
        _command_payload,
        _command_from_payload,
    )

    assert (
        _command_from_payload(_command_payload(command)).chapter_window_policy
        == policy.snapshot()
    )
    legacy = _command("chapter_group_plan.generate")
    assert "chapter_window_policy" not in _command_payload(
        _command_from_payload(_command_payload(legacy))
    )


def test_non_search_candidate_cannot_exceed_frozen_execution_policy() -> None:
    from novel_forge.modules.story_planning_runtime.application import (
        _validate_narrative_search_horizon,
    )
    from novel_forge.modules.command_kernel.errors import KernelError
    from tests.unit.test_story_planning_runtime import _command

    command = replace(
        _command("chapter_group_plan.generate"),
        chapter_window_policy=ChapterWindowPolicy(maximum_chapters=2).snapshot(),
    )
    for bounds in ([1, 3], [True, 2], [1.5, 2.5], [1, 1000000000]):
        with pytest.raises(
            KernelError, match="CHAPTER_WINDOW_CANDIDATE_POLICY_EXCEEDED"
        ):
            _validate_narrative_search_horizon(command, {"chapter_range": bounds})
    _validate_narrative_search_horizon(command, {"chapter_range": [1, 2]})

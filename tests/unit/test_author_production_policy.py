from copy import deepcopy

import pytest

from novel_forge.modules.book_authority.production_policy import chapter_context_policy, validate_author_configuration
from novel_forge.modules.command_kernel.errors import KernelError


def policy():
    return {"author_configuration_version": "book-author-configuration.v1", "chapter_context_policy": {"version": "book-chapter-context.v1", "draft_profile": "draft-context-profile-v3", "draft_token_budget": 20000, "quality_token_budget": 28000}, "craft_budget_policy": {"schema_version": "narrative-craft-budget.v4"}}


def test_author_choices_materialize_native_contracts_without_mutating_source():
    value = policy()
    original = deepcopy(value)
    result = validate_author_configuration(value)
    assert value == original
    assert result["craft_budget_policy"]["reselection_policy"]["maximum_reselections"] == 2
    assert result["world_production_policy"]["version"] == "world-production-policy.v1"
    assert "world_actor_experiment" not in result
    assert chapter_context_policy({}) is None


@pytest.mark.parametrize("profile,budget", [("draft-context-profile-v2", 16001), ("draft-context-profile-v3", 24001), ("unknown", 1000), ("draft-context-profile-v3", True)])
def test_context_selection_rejects_incompatible_or_invalid_budget(profile, budget):
    value = policy()
    value["chapter_context_policy"].update(draft_profile=profile, draft_token_budget=budget)
    with pytest.raises(KernelError, match="Context budgets"):
        validate_author_configuration(value)


def test_actor_selection_requires_matching_bounded_world_contract():
    value = policy()
    value["world_actor_experiment"] = {"version": "world-actor-experiment.v2", "actor_ids": ["a"], "max_rounds": 1, "max_actions_per_actor": 1, "max_intent_steps": 4}
    with pytest.raises(KernelError, match="at most three"):
        validate_author_configuration(value)
    value["world_production_policy"] = {"version": "world-production-policy.v3", "max_candidates": 1, "max_paths_per_candidate": 1, "max_preparation_steps": 1, "planning_window_chapters": 1, "max_provider_stages": 3}
    assert validate_author_configuration(value)["world_actor_experiment"]["actor_ids"] == ["a"]

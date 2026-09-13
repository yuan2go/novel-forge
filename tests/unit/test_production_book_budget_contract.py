from copy import deepcopy

import pytest

from novel_forge.modules.command_kernel.creative_budget_contract import (
    PRODUCTION_BOOK_VERSION, V3_POLICY_SCHEMA, contract_hash, validate_policy,
)
from novel_forge.modules.command_kernel.creative_budget_runtime import _validate_reallocation
from novel_forge.modules.command_kernel.creative_budget_scope import classify_business_scope, require_business_scope
from novel_forge.storage.versioned_policy_repository import policy_hash
from tests.unit.test_single_book_budget_contract import chapter_identity, single_book_policy


def production_book_policy(previous=None, *, chapters=40):
    previous = previous or single_book_policy()
    policy = deepcopy(previous)
    policy["policy_version"] = previous["policy_version"] + ":production"
    plan = policy["comparison_budget"]
    plan.update(contract_version=PRODUCTION_BOOK_VERSION, previous_policy={
        "policy_version": previous["policy_version"], "policy_hash": policy_hash(previous),
        "contract_hash": contract_hash(previous["comparison_budget"]),
    })
    plan["arms"][0]["book_id"] += ":new"
    plan["arms"][0]["chapter_ranges"] = {"CREATION_EARLY": [1, chapters // 2], "CREATION_LATE": [chapters // 2 + 1, chapters]}
    policy["authorization"]["book_id"] = plan["arms"][0]["book_id"]
    policy["authorization"]["authorization_ref"] += ":production"
    policy["authorization"]["business_scope"].update(source_allowed=False, max_chapter_number=chapters)
    return policy


@pytest.mark.parametrize("chapters", [30, 40, 50])
def test_production_schema_and_frozen_phases_admit_thirteen_and_stop_exactly(chapters):
    from novel_forge.modules.authority_handler_runtime.policy_commands import owned_policy_definition
    from novel_forge.modules.chapter_authority.provider_output_contracts import _validate
    policy = production_book_policy(chapters=chapters)
    assert validate_policy(policy) == policy
    _validate(V3_POLICY_SCHEMA, policy, path="$")
    definition = owned_policy_definition(owner="CREATIVE_EXPERIMENT_BUDGET", content=policy,
                                        application_build_id="fixture", commit_sha="a" * 40)
    assert definition["definition_version"] == "1.3.0"
    assert definition["command_schema"]["properties"]["policy"] == V3_POLICY_SCHEMA
    ranges = policy["comparison_budget"]["arms"][0]["chapter_ranges"]
    for chapter in (13, chapters):
        scope = classify_business_scope(chapter_identity(chapter), chapter_ranges=ranges)
        require_business_scope(policy, scope)
        assert scope["origin_phase"] == ("CREATION_EARLY" if chapter <= chapters // 2 else "CREATION_LATE")
    with pytest.raises(ValueError):
        classify_business_scope(chapter_identity(chapters + 1), chapter_ranges=ranges)


@pytest.mark.parametrize("ranges", [
    {"CREATION_EARLY": [1, 20], "CREATION_LATE": [20, 40]},
    {"CREATION_EARLY": [1, 20], "CREATION_LATE": [22, 40]},
    {"CREATION_EARLY": [2, 20], "CREATION_LATE": [21, 40]},
    {"CREATION_EARLY": [True, 20], "CREATION_LATE": [21, 40]},
    {"CREATION_EARLY": [1], "CREATION_LATE": [21, 40]},
])
def test_production_range_cannot_overlap_skip_or_coerce(ranges):
    policy = production_book_policy()
    policy["comparison_budget"]["arms"][0]["chapter_ranges"] = ranges
    with pytest.raises(ValueError):
        validate_policy(policy)


def test_reallocation_preserves_exact_cumulative_ownership_and_predecessor():
    previous = single_book_policy()
    policy = production_book_policy(previous)
    project = previous["authorization"]["project_id"]
    _validate_reallocation(policy["comparison_budget"], previous, project_id=project)
    for mutate in (
        lambda p: p["previous_policy"].update(policy_hash="b" * 64),
        lambda p: p.update(experiment_id="reset-lifetime"),
        lambda p: p["shared_total"].update(calls=481),
        lambda p: p["arms"][0].update(project_id="another-project"),
    ):
        changed = deepcopy(policy["comparison_budget"])
        mutate(changed)
        with pytest.raises(ValueError):
            _validate_reallocation(changed, previous, project_id=project)


def test_production_auth_cannot_expand_frozen_last_chapter():
    policy = production_book_policy()
    policy["authorization"]["business_scope"]["max_chapter_number"] = 41
    with pytest.raises(ValueError, match="frozen chapter range"):
        validate_policy(policy)

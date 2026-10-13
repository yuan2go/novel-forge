from copy import deepcopy

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_planning_runtime.runtime_deployment import (
    binding_identity,
    deployment_target,
)


def runtime():
    return {
        "model_id": "same-model",
        "reasoning_effort": "high",
        "account": {"identity": "original"},
        "pack_snapshot": {
            "pack_id": "pack",
            "pack_version": "1",
            "manifest_hash": "old",
            "prompt_bundle_hash": "prompt",
            "route_policy_hash": "route",
            "context_policy_hash": "context",
            "skill_bundle_hash": "skill",
            "tool_policy_hash": "tools",
            "operation_definition_hash": "definition",
        },
        "planning_capacity": {
            "allocated_task_tokens": 128000,
            "projection_hash": "frozen-view",
        },
        "generation_isolation": {"original_remote_outcome": "UNKNOWN"},
    }


@pytest.mark.parametrize("field", ["model_id", "reasoning_effort", "account"])
def test_deployment_cannot_change_creative_route_or_account(field):
    old = runtime()
    new = {
        key: deepcopy(value)
        for key, value in old.items()
        if key not in {"planning_capacity", "generation_isolation"}
    }
    new[field] = "changed"
    with pytest.raises(
        KernelError, match="PLANNING_DEPLOYMENT_REVALIDATION_ROUTE_DRIFT"
    ):
        deployment_target(None, project_id="project", original=old, target=new)


@pytest.mark.parametrize(
    "field",
    [
        "prompt_bundle_hash",
        "context_policy_hash",
        "skill_bundle_hash",
        "tool_policy_hash",
        "operation_definition_hash",
        "capability_hash",
        "execution_capability_hash",
        "evaluation_policy_hash",
        "approval_policy_hash",
        "budget_policy_hash",
        "commit_authority",
    ],
)
def test_deployment_cannot_replace_story_contracts(field):
    old = runtime()
    new = {
        key: deepcopy(value)
        for key, value in old.items()
        if key not in {"planning_capacity", "generation_isolation"}
    }
    new["pack_snapshot"][field] = "changed"
    with pytest.raises(
        KernelError, match="PLANNING_DEPLOYMENT_REVALIDATION_CONTRACT_DRIFT"
    ):
        deployment_target(None, project_id="project", original=old, target=new)


def test_version_only_deployment_preserves_capacity_projection_and_unknown_history(
    monkeypatch,
):
    from novel_forge.modules.story_planning_runtime import runtime_continuation

    monkeypatch.setattr(
        runtime_continuation,
        "_require_version_only_pack_successor",
        lambda *args, **kwargs: {"verified": "same persisted contracts"},
    )
    old = runtime()
    new = {
        key: deepcopy(value)
        for key, value in old.items()
        if key not in {"planning_capacity", "generation_isolation"}
    }
    new["pack_snapshot"].update(
        pack_version="2", manifest_hash="new", release_sha="actual-new-release"
    )
    result, proof = deployment_target(
        None, project_id="project", original=old, target=new
    )
    assert result["planning_capacity"] == old["planning_capacity"]
    assert result["generation_isolation"] == old["generation_isolation"]
    assert result["pack_snapshot"] == new["pack_snapshot"]
    assert old == runtime() and proof["verified"]


def test_binding_digest_ignores_only_successor_attachment():
    old = {
        "source_operation_id": "source",
        "successor_operation_id": None,
        "successor_command": {"input": "original"},
    }
    assert binding_identity(old) == binding_identity(
        {**old, "successor_operation_id": "started"}
    )
    assert binding_identity(old) != binding_identity(
        {**old, "successor_command": {"input": "changed"}}
    )

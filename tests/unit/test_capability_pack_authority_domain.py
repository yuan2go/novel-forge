from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from novel_forge.modules.capability_pack_authority.domain import (
    CapabilityPackExecutionSnapshot,
    CapabilityPackScope,
    ScopeType,
    canonical_hash,
    stable_rollout_bucket,
)


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
RELEASE_SHA = "c" * 40


def test_scope_contract_enforces_exact_hierarchy() -> None:
    assert CapabilityPackScope(ScopeType.SYSTEM).subject_key == "system"
    assert CapabilityPackScope(
        ScopeType.PROJECT, project_id="project-1"
    ).subject_key == "project-1"
    assert CapabilityPackScope(
        ScopeType.WORKSPACE,
        project_id="project-1",
        workspace_id="workspace-1",
    ).subject_key == "project-1:workspace-1"
    assert CapabilityPackScope(
        ScopeType.BOOK,
        project_id="project-1",
        workspace_id="workspace-1",
        book_id="book-1",
    ).subject_key == "book-1"

    with pytest.raises(ValueError, match="WORKSPACE scope"):
        CapabilityPackScope(ScopeType.WORKSPACE, project_id="project-1")
    with pytest.raises(ValueError, match="BOOK scope"):
        CapabilityPackScope(
            ScopeType.BOOK, project_id="project-1", book_id="book-1"
        )
    with pytest.raises(ValueError, match="SYSTEM scope"):
        CapabilityPackScope(ScopeType.SYSTEM, project_id="project-1")


def test_stable_canary_bucket_uses_a_known_deterministic_vector() -> None:
    assert stable_rollout_bucket("rollout-1", "book-1") == 9190
    assert stable_rollout_bucket("rollout-1", "book-2") == 2532
    assert stable_rollout_bucket("rollout-1", "book-1") == 9190


def test_execution_snapshot_is_immutable_and_content_addressed() -> None:
    snapshot = CapabilityPackExecutionSnapshot(
        deployment_id="deployment-1",
        activation_version=3,
        selected_scope_type=ScopeType.BOOK,
        selection_reason="BOOK deployment selected",
        pack_id="chapter_generation_pack",
        pack_version="1.0.0",
        manifest_hash=HASH_A,
        compilation_id="compilation-1",
        compilation_hash=HASH_B,
        catalog_snapshot_hash=HASH_A,
        binding_set_id="binding-set-1",
        binding_set_hash=HASH_B,
        workflow_definition_ref="chapter_authority_slice@2.2.0",
        workflow_node_id="draft",
        operation_definition_ref="chapter.draft.generate@2.2.0",
        operation_definition_hash=HASH_A,
        agent_definition_ref="chapter-draft-agent@1",
        agent_definition_hash=HASH_B,
        capability_ref="prose.chapter.draft@1",
        capability_hash=HASH_A,
        execution_capability_id="prose.chapter.draft",
        execution_capability_hash=HASH_B,
        prompt_bundle_ref="prompt-system:chapter-generation-pack@v1",
        prompt_bundle_hash=HASH_B,
        skill_bundle_ref="prose-generation@prose-generation-v1",
        skill_bundle_hash=HASH_A,
        tool_policy_ref="tool-policy:chapter@v1",
        tool_policy_hash=HASH_B,
        context_policy_ref="context-policy:chapter@v1",
        context_policy_hash=HASH_A,
        evaluation_policy_ref="evaluation:chapter@v1",
        evaluation_policy_hash=HASH_B,
        route_policy_ref="route:chapter@v1",
        route_policy_hash=HASH_A,
        approval_policy_ref="approval:chapter@v1",
        approval_policy_hash=HASH_B,
        budget_policy_ref="budget:chapter@v1",
        budget_policy_hash=HASH_A,
        input_contract_ref="schema:chapter-draft-input@1",
        output_contract_ref="schema:chapter-draft-candidate@1",
        domain_acceptance_policy_ref="chapter-authority:draft-acceptance@1",
        commit_authority="CHAPTER_AUTHORITY",
        release_sha=RELEASE_SHA,
        rollout_id="rollout-1",
        assignment_ref="assignment-1",
    )

    assert snapshot.snapshot_hash == canonical_hash(snapshot.to_dict())
    with pytest.raises(FrozenInstanceError):
        snapshot.pack_version = "2.0.0"  # type: ignore[misc]


def test_execution_snapshot_rejects_missing_content_identity() -> None:
    values = {
        field: "value"
        for field in CapabilityPackExecutionSnapshot.__dataclass_fields__
        if field not in {"activation_version", "selected_scope_type"}
    }
    values.update(
        activation_version=1,
        selected_scope_type=ScopeType.PROJECT,
        manifest_hash=HASH_A,
        compilation_hash=HASH_A,
        catalog_snapshot_hash=HASH_A,
        binding_set_hash=HASH_A,
        operation_definition_hash=HASH_A,
        agent_definition_hash=HASH_A,
        capability_hash=HASH_A,
        prompt_bundle_hash=HASH_A,
        skill_bundle_hash=HASH_A,
        tool_policy_hash=HASH_A,
        context_policy_hash=HASH_A,
        evaluation_policy_hash=HASH_A,
        route_policy_hash=HASH_A,
        approval_policy_hash=HASH_A,
        budget_policy_hash=HASH_A,
        commit_authority="CHAPTER_AUTHORITY",
        release_sha=RELEASE_SHA,
        rollout_id="",
        assignment_ref="",
    )
    values["binding_set_hash"] = "not-a-hash"
    with pytest.raises(ValueError, match="binding_set_hash"):
        CapabilityPackExecutionSnapshot(**values)

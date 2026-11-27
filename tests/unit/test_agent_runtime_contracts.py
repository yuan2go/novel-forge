from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from novel_forge.modules.agent_runtime.contracts import (
    AgentRunStatus,
    AgentRuntimeBinding,
    ChapterNodeExecutionBinding,
    derive_agent_run_status,
)
from novel_forge.modules.agent_runtime.queries import _domain_resolution_projection


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64


def test_candidate_only_and_embedded_domain_resolution_are_distinct() -> None:
    collaboration = {
        "candidate": {"candidate_version_id": "candidate-1"},
        "decision": {},
        "commit": {},
    }

    standalone = _domain_resolution_projection(collaboration, standalone=True)
    embedded = _domain_resolution_projection(collaboration, standalone=False)

    assert standalone["candidate_status"] == "CANDIDATE_READY"
    assert standalone["domain_commit_status"] == "NOT_REQUESTED"
    assert embedded["domain_commit_status"] == "DOMAIN_DECISION_PENDING"


def test_agent_run_status_is_derived_from_kernel_facts() -> None:
    assert (
        derive_agent_run_status(
            operation_status="EXECUTING", attempt_status="RUNNING"
        )
        is AgentRunStatus.RUNNING
    )
    assert (
        derive_agent_run_status(
            operation_status="WAITING_EXTERNAL_RESULT",
            attempt_status="RESULT_SUBMITTED",
            external_effect_status="UNKNOWN",
        )
        is AgentRunStatus.RECONCILIATION_REQUIRED
    )
    assert (
        derive_agent_run_status(
            operation_status="SUCCEEDED", attempt_status="SUCCEEDED"
        )
        is AgentRunStatus.SUCCEEDED
    )
    assert (
        derive_agent_run_status(
            operation_status="FAILED_RETRYABLE",
            attempt_status="FAILED_RETRYABLE",
        )
        is AgentRunStatus.RETRYABLE
    )
    assert (
        derive_agent_run_status(
            operation_status="EXECUTING",
            attempt_status="RUNNING",
            lease_status="EXPIRED",
            external_effect_status="SUCCEEDED",
        )
        is AgentRunStatus.RECONCILIATION_REQUIRED
    )


def test_runtime_binding_freezes_existing_authority_identities() -> None:
    binding = AgentRuntimeBinding(
        binding_id="agent-runtime-binding:attempt-1",
        project_id="project-1",
        workspace_id="workspace-1",
        book_id="book-1",
        workflow_definition_ref="chapter-generation@1",
        workflow_node_id="chapter-draft",
        operation_definition_ref="chapter.draft@1",
        operation_definition_hash=HASH_A,
        operation_id="operation-1",
        attempt_id="attempt-1",
        fencing_token=7,
        work_order_id="work-order-1",
        agent_id="chapter-draft-agent",
        agent_definition_version=3,
        agent_definition_hash=HASH_B,
        capability_id="chapter.draft.generate",
        capability_version=2,
        capability_hash=HASH_C,
        execution_capability_id="MODEL_DRAFT_GENERATION",
        chapter_node_binding_ref="chapter-binding:chapter-draft@1",
        capability_pack_ref="chapter-generation-pack@1",
        capability_pack_compilation_hash=HASH_A,
        context_bundle_asset_version_id="asset-version-context-1",
        context_bundle_hash=HASH_C,
        prompt_bundle_ref="prompt-bundle:chapter-draft@1",
        prompt_bundle_hash=HASH_B,
        skill_bundle_ref="skill-bundle:prose-generation@1",
        skill_bundle_hash=HASH_C,
        tool_policy_ref="tool-policy:no-tools@1",
        tool_policy_hash=HASH_A,
        tool_permission_snapshot_ref="tool-policy:no-tools@1",
        tool_permission_snapshot_hash=HASH_A,
        context_policy_ref="context-policy:chapter@1",
        context_policy_hash=HASH_B,
        route_snapshot_ref="route-snapshot:attempt-1",
        route_snapshot_hash=HASH_B,
        input_manifest_ref="input-manifest:attempt-1",
        input_manifest_hash=HASH_C,
        budget_policy_ref="budget-policy:chapter-draft@1",
        timeout_policy_ref="timeout-policy:chapter-draft@1",
        approval_policy_ref="approval-policy:chapter-draft@1",
        validation_policy_ref="validation-policy:chapter-draft@1",
        commit_policy_ref="commit-policy:chapter-draft@1",
        commit_authority="CHAPTER_AUTHORITY",
        release_sha="a3c59277d05a00cec79dfccd9d39236e88809f19",
    )

    assert binding.operation_id == "operation-1"
    assert binding.attempt_id == "attempt-1"
    assert binding.fencing_token == 7
    assert binding.binding_hash.startswith("sha256:")
    with pytest.raises(FrozenInstanceError):
        binding.fencing_token = 8  # type: ignore[misc]


def test_runtime_binding_rejects_missing_hash_or_fence() -> None:
    with pytest.raises(ValueError, match="hash"):
        AgentRuntimeBinding(
            binding_id="binding-1",
            project_id="project-1",
            workspace_id="workspace-1",
            book_id="book-1",
            workflow_definition_ref="workflow@1",
            workflow_node_id="draft",
            operation_definition_ref="chapter.draft@1",
            operation_definition_hash="",
            operation_id="operation-1",
            attempt_id="attempt-1",
            fencing_token=1,
            work_order_id="work-order-1",
            agent_id="draft-agent",
            agent_definition_version=1,
            agent_definition_hash=HASH_A,
            capability_id="chapter.draft.generate",
            capability_version=1,
            capability_hash=HASH_B,
            execution_capability_id="MODEL_DRAFT_GENERATION",
            chapter_node_binding_ref="binding:draft@1",
            capability_pack_ref="pack@1",
            capability_pack_compilation_hash=HASH_C,
            context_bundle_asset_version_id="context-version-1",
            context_bundle_hash=HASH_A,
            prompt_bundle_ref="prompt@1",
            prompt_bundle_hash=HASH_A,
            skill_bundle_ref="skill@1",
            skill_bundle_hash=HASH_B,
            tool_policy_ref="tool-policy@1",
            tool_policy_hash=HASH_A,
            tool_permission_snapshot_ref="tools@1",
            tool_permission_snapshot_hash=HASH_C,
            context_policy_ref="context@1",
            context_policy_hash=HASH_C,
            route_snapshot_ref="route-1",
            route_snapshot_hash=HASH_A,
            input_manifest_ref="manifest-1",
            input_manifest_hash=HASH_B,
            budget_policy_ref="budget@1",
            timeout_policy_ref="timeout@1",
            approval_policy_ref="approval@1",
            validation_policy_ref="validation@1",
            commit_policy_ref="commit@1",
            commit_authority="CHAPTER_AUTHORITY",
            release_sha="a3c59277d05a00cec79dfccd9d39236e88809f19",
        )


def test_chapter_binding_requires_candidate_only_agent_boundary() -> None:
    binding = ChapterNodeExecutionBinding(
        binding_id="chapter-binding:draft@1",
        binding_version=1,
        workflow_definition_ref="chapter-generation@1",
        workflow_node_id="chapter-draft",
        operation_definition_ref="chapter.draft@1",
        operation_definition_hash=HASH_A,
        agent_definition_ref="chapter-draft-agent@1",
        agent_definition_hash=HASH_B,
        capability_ref="chapter.draft.generate@1",
        capability_hash=HASH_C,
        execution_capability_id="MODEL_DRAFT_GENERATION",
        capability_pack_ref="chapter-generation-pack@1",
        capability_pack_compilation_hash=HASH_A,
        input_contract_ref="schema:chapter-draft-input@1",
        output_contract_ref="schema:chapter-draft-candidate@1",
        domain_acceptance_policy_ref="acceptance:chapter-draft@1",
        commit_authority="CHAPTER_AUTHORITY",
        status="ACTIVE",
        release_sha="a3c59277d05a00cec79dfccd9d39236e88809f19",
        created_by_operation_id="operation-register-binding-1",
    )

    assert binding.agent_definition_ref == "chapter-draft-agent@1"
    assert binding.binding_hash.startswith("sha256:")

    with pytest.raises(ValueError, match="Domain Authority"):
        replace(binding, commit_authority="AGENT")

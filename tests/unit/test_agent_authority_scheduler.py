from __future__ import annotations

from typing import Any

import pytest

from novel_forge.modules.agent_runtime.scheduler import (
    PreparedAgentExecution,
    build_agent_work_order,
    build_runtime_binding,
)


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64


class _ExternalEffectPepPort:
    external_effect_backed = True
    production_execution_gateway_backed = True

    def execute(self, command: Any) -> Any:  # pragma: no cover - contract fake
        raise AssertionError(command)


def _prepared(port: Any | None = None) -> PreparedAgentExecution:
    return PreparedAgentExecution(
        execution_port=port or _ExternalEffectPepPort(),
        route_snapshot_ref="route:attempt-1",
        route_snapshot_hash=HASH_A,
        input_manifest_ref="input:attempt-1",
        input_manifest_hash=HASH_B,
        prompt_bundle_ref="prompt:attempt-1",
        prompt_bundle_hash=HASH_C,
        skill_bundle_ref="skill:attempt-1",
        skill_bundle_hash=HASH_A,
        tool_permission_snapshot_ref="tools:attempt-1",
        tool_permission_snapshot_hash=HASH_B,
        context_policy_ref="context-policy:draft@1",
        context_policy_hash=HASH_C,
    )


def _operation() -> dict[str, Any]:
    return {
        "operation_id": "operation-agent-1",
        "project_id": "project-1",
        "workspace_id": "workspace-1",
        "definition_name": "agent.candidate.execute",
        "definition_version": "2.0.0",
        "definition_snapshot": {"definition_hash": HASH_A},
        "command_payload": {
            "agent_id": "draft-agent",
            "agent_definition_version": 2,
            "agent_definition_hash": HASH_B,
            "capability_id": "chapter.draft.generate",
            "capability_version": 3,
            "capability_hash": HASH_C,
            "execution_capability_id": "prose.chapter.draft",
            "capability_pack_ref": "chapter-pack@7",
            "capability_pack_compilation_hash": HASH_A,
            "workflow_definition_ref": "chapter-generation@7",
            "workflow_node_id": "draft",
            "chapter_node_binding_ref": "chapter-binding:draft@5",
            "collaboration_session_id": "session-1",
            "scope_snapshot_ref": "scope-1",
            "participant_snapshot_ref": "participants-1",
            "book_id": "book-1",
            "chapter_number": 1,
            "context_bundle_asset_version_id": "asset-context-1",
            "context_bundle_hash": HASH_C,
            "tool_policy_ref": "tool-policy:draft@1",
            "tool_policy_hash": HASH_A,
            "input_asset_versions": ["asset-context-1", "asset-plan-1"],
            "evidence_refs": ["asset-plan-1"],
            "message_type": "PROPOSAL",
            "business_goal": "produce a draft candidate",
            "current_issue": "draft chapter one",
            "candidate_version_ref": "",
            "must_preserve": ["canon"],
            "must_change": [],
            "forbidden_changes": ["published chapters"],
            "acceptance_criteria": ["schema valid"],
            "risk_level": "HIGH",
            "budget_policy_ref": "budget:draft@1",
            "timeout_policy_ref": "timeout:draft@1",
            "approval_policy_ref": "approval:draft@1",
            "validation_policy_ref": "validation:draft@1",
            "commit_policy_ref": "commit:draft@1",
            "commit_authority": "CHAPTER_AUTHORITY",
            "failure_policy": "retry_then_repair",
            "continuation_policy": "domain_acceptance",
            "release_sha": "a" * 40,
        },
    }


def test_work_order_and_runtime_binding_reuse_attempt_and_fence() -> None:
    operation = _operation()
    prepared = _prepared()
    first = build_agent_work_order(
        operation=operation,
        attempt_id="attempt-1",
        fencing_token=9,
        prepared=prepared,
    )
    replay = build_agent_work_order(
        operation=operation,
        attempt_id="attempt-1",
        fencing_token=9,
        prepared=prepared,
    )
    binding = build_runtime_binding(
        operation=operation, work_order=first, prepared=prepared
    )

    assert first == replay
    assert first.operation_id == "operation-agent-1"
    assert first.attempt_id == "attempt-1"
    assert first.fencing_token == 9
    assert binding.attempt_id == first.attempt_id
    assert binding.work_order_id == first.work_order_id
    assert binding.operation_definition_ref == "agent.candidate.execute@2.0.0"
    assert binding.chapter_node_binding_ref == "chapter-binding:draft@5"
    assert binding.tool_policy_ref == "tool-policy:draft@1"
    assert binding.tool_permission_snapshot_ref == "tools:attempt-1"
    assert binding.binding_hash.startswith("sha256:")


def test_prepared_execution_rejects_a_pep_or_external_effect_bypass() -> None:
    class _DirectPort:
        pass

    with pytest.raises(ValueError, match="ExternalEffect"):
        _prepared(_DirectPort())

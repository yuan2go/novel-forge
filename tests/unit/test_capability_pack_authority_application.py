from __future__ import annotations

import pytest

from novel_forge.modules.capability_pack_authority.application import (
    CapabilityPackAuthorityCommand,
    build_binding_set,
)
from novel_forge.modules.capability_pack_authority.domain import canonical_hash
from novel_forge.modules.command_kernel.errors import KernelError


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


def _command(**changes):
    values = {
        "definition_name": "capability_pack.compile",
        "project_id": "project-1",
        "workspace_id": "workspace-1",
        "actor_id": "compiler-1",
        "pack_id": "chapter_generation_pack",
        "pack_version": "1.0.0",
        "idempotency_key": "compile-1",
        "trace_id": "trace-1",
        "correlation_id": "correlation-1",
        "payload": {
            "target_runtime_profile": "validation",
            "novel_forge_version": "6.0.0",
            "release_channel": "VALIDATION",
            "release_sha": "a" * 40,
        },
    }
    values.update(changes)
    return CapabilityPackAuthorityCommand(**values)


def test_compile_command_forbids_caller_supplied_compiled_payload() -> None:
    for forbidden in ("compiled_payload", "compiled_capability_pack"):
        with pytest.raises(ValueError, match="caller-supplied compiled"):
            _command(payload={forbidden: {"compilation_hash": HASH_A}})


def test_command_requires_exact_pack_version_for_non_registration_actions() -> None:
    with pytest.raises(ValueError, match="pack_version"):
        _command(pack_version="")


def test_binding_set_cross_binds_agent_runtime_contract_to_compilation() -> None:
    compiled = {
        "pack_id": "chapter_generation_pack",
        "pack_version": "1.0.0",
        "compilation_hash": HASH_A,
        "workflow_nodes": [
            {
                "ordinal": 1,
                "node_id": "draft",
                "definition_name": "chapter.draft.generate",
                "definition_version": "2.2.0",
                "definition_hash": HASH_A,
                "capability_id": "prose.chapter.draft",
                "capability_contract_hash": HASH_B,
                "agent_definition_ref": "chapter-draft-agent@1",
            }
        ],
        "resolved_artifacts": [
            {
                "kind": "PROMPT_SYSTEM_INSTRUCTION",
                "ref": "prompt-system:chapter-generation-pack",
                "version": "v1",
                "content_hash": HASH_A,
            },
            {
                "kind": "PROMPT_TEMPLATE",
                "ref": "prompt-template:chapter-generation-pack",
                "version": "v1",
                "content_hash": HASH_B,
            },
            {
                "kind": "SKILL",
                "ref": "prose-generation",
                "version": "prose-generation-v1",
                "content_hash": HASH_B,
            },
            {
                "kind": "APPROVAL_POLICY",
                "ref": "chapter.stage.route.policy:v1",
                "version": "v1",
                "content_hash": HASH_A,
            },
            {
                "kind": "APPROVAL_POLICY",
                "ref": "domain-decision-record:v1",
                "version": "v1",
                "content_hash": HASH_B,
            },
            {
                "kind": "BUDGET_POLICY",
                "ref": "budget:chapter-generation-pack:v1",
                "version": "v1",
                "content_hash": HASH_A,
            },
        ],
        "tool_permission_snapshot": {
            "policy_id": "tools:chapter-generation-pack:v1",
            "external_models": {
                "route_policy_ref": "chapter.stage.route.policy:v1"
            },
        },
        "context_source_snapshot": {
            "policy_id": "context-policy:chapter-generation-pack:v1"
        },
        "evaluation_gate_snapshot": {
            "evaluation_id": "chapter-generation-evaluation-v1"
        },
    }
    manifest = {
        "identity": {"pack_id": "chapter_generation_pack", "version": "1.0.0"},
        "workflow_template": {
            "workflow_id": "chapter_authority_slice",
            "workflow_version": "2.2.0",
        },
        "runtime_contract": {"commit_policy_ref": "commit:chapter:v1"},
        "prompt_binding": {
            "system_instruction_ref": "prompt-system:chapter-generation-pack",
            "system_instruction_version": "v1",
            "system_instruction_hash": HASH_A,
            "template_ref": "prompt-template:chapter-generation-pack",
            "template_version": "v1",
            "template_hash": HASH_B,
            "compiler_version": "chapter-prompt-compiler:v1",
        },
        "skill_binding": {
            "skills": [
                {
                    "skill_ref": "prose-generation",
                    "version": "prose-generation-v1",
                    "content_hash": HASH_B,
                }
            ]
        },
        "governance": {
            "approval_policy_ref": "domain-decision-record:v1",
            "cost_tracking": {
                "budget_policy_ref": "budget:chapter-generation-pack:v1"
            },
        },
    }
    definitions = {
        "chapter-draft-agent@1": {
            "agent_id": "chapter-draft-agent",
            "definition_version": 1,
            "definition_hash": HASH_A,
            "capability_pack_ref": "chapter_generation_pack@1.0.0",
            "prompt_bundle_ref": "prompt-system:chapter-generation-pack@v1",
            "prompt_bundle_hash": HASH_A,
            "skill_bundle_ref": "prose-generation@prose-generation-v1",
            "skill_bundle_hash": HASH_B,
            "tool_policy_ref": "tools:chapter-generation-pack:v1",
            "tool_policy_hash": canonical_hash(compiled["tool_permission_snapshot"]),
            "context_policy_ref": "context-policy:chapter-generation-pack:v1",
            "context_policy_hash": canonical_hash(compiled["context_source_snapshot"]),
            "input_contract_ref": "schema:draft-input@1",
            "output_contract_ref": "schema:draft-candidate@1",
            "approval_policy_ref": "approval:chapter-domain-authority:v1",
            "capabilities": [
                {
                    "capability_id": "prose.chapter.draft",
                    "capability_version": 1,
                    "capability_hash": HASH_B,
                    "execution_capability_id": "prose.chapter.draft",
                    "execution_capability_hash": HASH_B,
                }
            ],
        }
    }

    result = build_binding_set(
        compiled=compiled, manifest=manifest, agent_definitions=definitions
    )

    node = result["node_bindings"][0]
    assert node["operation_definition_ref"] == "chapter.draft.generate@2.2.0"
    assert node["agent_definition_hash"] == HASH_A
    assert node["prompt_bundle_hash"] == HASH_A
    assert node["skill_bundle_hash"] == HASH_B
    assert result["binding_set_hash"].startswith("sha256:")


def test_binding_set_rejects_prompt_hash_not_frozen_by_compilation() -> None:
    compiled = {
        "pack_id": "pack",
        "pack_version": "1.0.0",
        "compilation_hash": HASH_A,
        "workflow_nodes": [
            {
                "ordinal": 1,
                "node_id": "draft",
                "definition_name": "chapter.draft.generate",
                "definition_version": "2.2.0",
                "definition_hash": HASH_A,
                "capability_id": "prose.chapter.draft",
                "capability_contract_hash": HASH_B,
                "agent_definition_ref": "agent@1",
            }
        ],
        "resolved_artifacts": [
            {
                "kind": "APPROVAL_POLICY",
                "ref": "route:v1",
                "version": "v1",
                "content_hash": HASH_A,
            },
            {
                "kind": "APPROVAL_POLICY",
                "ref": "approval:v1",
                "version": "v1",
                "content_hash": HASH_A,
            },
            {
                "kind": "BUDGET_POLICY",
                "ref": "budget:v1",
                "version": "v1",
                "content_hash": HASH_A,
            },
        ],
        "tool_permission_snapshot": {
            "policy_id": "tools:v1",
            "external_models": {"route_policy_ref": "route:v1"},
        },
        "context_source_snapshot": {"policy_id": "context:v1"},
        "evaluation_gate_snapshot": {"evaluation_id": "evaluation:v1"},
    }
    manifest = {
        "workflow_template": {"workflow_id": "chapter", "workflow_version": "1"},
        "runtime_contract": {"commit_policy_ref": "commit:v1"},
        "governance": {
            "approval_policy_ref": "approval:v1",
            "cost_tracking": {"budget_policy_ref": "budget:v1"},
        },
    }
    definitions = {
        "agent@1": {
            "agent_id": "agent",
            "definition_version": 1,
            "definition_hash": HASH_A,
            "capability_pack_ref": "pack@1.0.0",
            "prompt_bundle_ref": "missing@v1",
            "prompt_bundle_hash": HASH_A,
            "skill_bundle_ref": "missing-skill@v1",
            "skill_bundle_hash": HASH_B,
            "tool_policy_ref": "tools:v1",
            "tool_policy_hash": canonical_hash(compiled["tool_permission_snapshot"]),
            "context_policy_ref": "context:v1",
            "context_policy_hash": canonical_hash(compiled["context_source_snapshot"]),
            "capabilities": [
                {
                    "capability_id": "prose.chapter.draft",
                    "capability_version": 1,
                    "capability_hash": HASH_B,
                    "execution_capability_id": "prose.chapter.draft",
                    "execution_capability_hash": HASH_B,
                }
            ],
        }
    }
    with pytest.raises(KernelError) as raised:
        build_binding_set(
            compiled=compiled, manifest=manifest, agent_definitions=definitions
        )
    assert raised.value.code == "CAPABILITY_PACK_RUNTIME_ARTIFACT_DRIFT"

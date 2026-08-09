from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from novel_forge.modules.agent_runtime.contracts import ChapterNodeExecutionBinding
from novel_forge.modules.capability_packs.compiler import (
    CompiledCapabilityPack,
    CompiledWorkflowNode,
)
from novel_forge.modules.capability_packs.runtime_binding import (
    bind_compiled_pack_for_admission,
    compiled_capability_pack_from_payload,
)
from novel_forge.modules.command_kernel.errors import KernelError


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64


def _node() -> CompiledWorkflowNode:
    return CompiledWorkflowNode(
        ordinal=3,
        node_id="draft",
        definition_name="chapter.draft.generate",
        definition_version="2.3.0",
        definition_hash=HASH_A,
        handler_key="novel_forge.chapter_authority.draft",
        handler_contract_version="1.0.0",
        capability_id="prose.chapter.draft",
        capability_contract_hash=HASH_C,
        agent_definition_ref="chapter-draft-agent@1",
        depends_on=("context",),
        authoritative_retry_policy_json='{"max_attempts":2}',
        authoritative_timeout_policy_json='{"operation_timeout_seconds":300}',
        authoritative_approval_policy_json='{"required":false}',
        authoritative_compensation_policy_json='{"supported":false}',
        authoritative_completion_contract_json='{"version":"draft.v1"}',
    )


def _binding() -> ChapterNodeExecutionBinding:
    return ChapterNodeExecutionBinding(
        binding_id="chapter-binding:draft",
        binding_version=1,
        workflow_definition_ref="chapter_authority_slice@2.3.0",
        workflow_node_id="draft",
        operation_definition_ref="chapter.draft.generate@2.3.0",
        operation_definition_hash=HASH_A,
        agent_definition_ref="chapter-draft-agent@1",
        agent_definition_hash=HASH_B,
        capability_ref="prose.chapter.draft@1",
        capability_hash=HASH_C,
        execution_capability_id="prose.chapter.draft",
        capability_pack_ref="chapter_generation_pack@1.1.0",
        capability_pack_compilation_hash=HASH_B,
        input_contract_ref="schema:draft-input@1",
        output_contract_ref="schema:draft-candidate@1",
        domain_acceptance_policy_ref="acceptance:draft@1",
        commit_authority="CHAPTER_AUTHORITY",
        status="ACTIVE",
        release_sha="a" * 40,
        created_by_operation_id="operation-register-binding",
    )


def _authority() -> dict[str, object]:
    return {
        "name": "chapter.draft.generate",
        "definition_version": "2.3.0",
        "definition_hash": HASH_A,
        "handler_key": "novel_forge.chapter_authority.draft",
        "handler_contract_version": "1.0.0",
        "retry_policy": {"max_attempts": 2},
        "timeout_policy": {"operation_timeout_seconds": 300},
        "approval_policy": {"required": False},
        "compensation_policy": {"supported": False},
        "completion_contract": {"version": "draft.v1"},
    }


def test_compiled_pack_binds_configuration_to_existing_authority() -> None:
    compiled = SimpleNamespace(
        pack_id="chapter_generation_pack",
        pack_version="1.1.0",
        compilation_hash=HASH_B,
        release_sha="a" * 40,
        workflow_nodes=(_node(),),
    )

    result = bind_compiled_pack_for_admission(
        compiled=compiled,
        workflow_node_id="draft",
        chapter_binding=_binding(),
        authority_operation_definition=_authority(),
    )

    assert result.capability_pack_compilation_hash == HASH_B
    assert result.agent_definition_ref == "chapter-draft-agent@1"
    assert result.operation_definition_ref == "chapter.draft.generate@2.3.0"


def test_pack_cannot_override_authority_retry_policy() -> None:
    compiled = SimpleNamespace(
        pack_id="chapter_generation_pack",
        pack_version="1.1.0",
        compilation_hash=HASH_B,
        release_sha="a" * 40,
        workflow_nodes=(_node(),),
    )
    authority = _authority()
    authority["retry_policy"] = {"max_attempts": 9}

    with pytest.raises(KernelError) as raised:
        bind_compiled_pack_for_admission(
            compiled=compiled,
            workflow_node_id="draft",
            chapter_binding=_binding(),
            authority_operation_definition=authority,
        )

    assert raised.value.code == "CAPABILITY_PACK_OPERATION_AUTHORITY_CONFLICT"


def _compiled_payload() -> dict[str, object]:
    compiled = CompiledCapabilityPack(
        schema_version="novelos.capability_pack.compiled.v1",
        pack_id="chapter_generation_pack",
        pack_version="1.1.0",
        manifest_hash=HASH_A,
        protocol_version="novelos.capability_pack.v1",
        target_runtime_profile="controlled",
        novel_forge_version="7.0.0",
        release_channel="fixture",
        release_sha="a" * 40,
        catalog_snapshot_hash=HASH_B,
        compilation_hash="",
        capability_type_policy_json="{}",
        resolved_capabilities_json="[]",
        resolved_operations_json="[]",
        resolved_artifacts_json="[]",
        workflow_nodes=(_node(),),
        external_input_asset_contract=("context_bundle",),
        completion_contract_json="{}",
        tool_permission_snapshot_json="{}",
        context_source_snapshot_json="{}",
        evaluation_gate_snapshot_json="{}",
        audit_requirement_snapshot_json="{}",
        version_resolution_snapshot_json="{}",
    )
    payload = compiled.to_dict()
    payload.pop("compilation_hash")
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    payload["compilation_hash"] = "sha256:" + hashlib.sha256(encoded).hexdigest()
    return payload


def test_compiled_payload_is_content_authenticated_at_admission() -> None:
    payload = _compiled_payload()
    loaded = compiled_capability_pack_from_payload(payload)
    assert loaded.compilation_hash == payload["compilation_hash"]

    payload["release_channel"] = "tampered"
    with pytest.raises(KernelError) as raised:
        compiled_capability_pack_from_payload(payload)
    assert raised.value.code == "CAPABILITY_PACK_COMPILATION_HASH_DRIFT"

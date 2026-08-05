"""OperationDefinitions for Agent Runtime administration and candidate work."""

from __future__ import annotations

from typing import Any


AGENT_RUNTIME_DEFINITION_VERSION = "1.0.0"
AGENT_RUNTIME_ADMIN_HANDLER_KEY = "novel_forge.agent_runtime.admin"
AGENT_RUNTIME_EXECUTION_HANDLER_KEY = "novel_forge.agent_runtime.candidate"

AGENT_RUNTIME_ADMIN_OPERATIONS = (
    "agent.definition.register",
    "agent.definition.activate",
    "agent.definition.disable",
    "agent.chapter_binding.register",
    "agent.chapter_binding.activate",
)
AGENT_RUNTIME_OPERATIONS = (*AGENT_RUNTIME_ADMIN_OPERATIONS, "agent.candidate.execute")
AGENT_RUNTIME_MODEL_EFFECT_CAPABILITIES = (
    "model.draft",
    "model.review",
    "model.revision",
    "model.rereview",
    "model.canon_extraction",
    "model.quality_structural",
    "model.quality_commercial",
    "model.quality_source_originality",
    "model.quality_longform",
    "model.quality_platform",
    "model.reader_outcome",
)


def agent_runtime_operation_definitions(
    *, application_build_id: str, commit_sha: str
) -> tuple[dict[str, Any], ...]:
    if not application_build_id or len(commit_sha) != 40:
        raise ValueError(
            "Agent Runtime requires application_build_id and a full commit SHA"
        )
    return tuple(
        _definition(
            name,
            application_build_id=application_build_id,
            commit_sha=commit_sha,
        )
        for name in AGENT_RUNTIME_OPERATIONS
    )


def _definition(
    name: str, *, application_build_id: str, commit_sha: str
) -> dict[str, Any]:
    execution = name == "agent.candidate.execute"
    command_schema = _execution_schema() if execution else _admin_schema()
    result_schema = (
        {
            "type": "object",
            "required": ["candidate_version_id", "validation_status"],
            "properties": {
                "candidate_version_id": {"type": "string"},
                "validation_status": {"type": "string"},
                "execution_evidence_ref": {"type": "string"},
            },
            "additionalProperties": False,
        }
        if execution
        else {"type": "object"}
    )
    permission = "agent.authority.execute" if execution else "agent.authority.admin"
    completion = (
        {
            "version": "agent.candidate.execute.completion.v1",
            "required_gates": [{"gate_key": "agent_candidate_validated"}],
            "required_evidence": ["trace", "audit", "cost_when_provider_used"],
            "required_outbox_events": ["authority.agent.candidate.validated"],
        }
        if execution
        else {
            "version": f"{name}.completion.v1",
            "required_evidence": ["trace", "audit"],
            "required_outbox_events": [f"authority.{name}.committed"],
        }
    )
    return {
        "name": name,
        "definition_version": AGENT_RUNTIME_DEFINITION_VERSION,
        "family": "agent_runtime_authority",
        "enabled": True,
        "command_schema": command_schema,
        "result_schema": result_schema,
        "input_contract": command_schema,
        "output_contract": result_schema,
        "handler_key": (
            AGENT_RUNTIME_EXECUTION_HANDLER_KEY
            if execution
            else AGENT_RUNTIME_ADMIN_HANDLER_KEY
        ),
        "handler_contract_version": "1.0.0",
        "application_build_id": application_build_id,
        "commit_sha": commit_sha,
        "execution_mode": "worker" if execution else "transactional",
        "permissions": [permission],
        "approval_policy": {"required": False},
        "idempotency_scope": (
            "project:agent-runtime" if execution else "system:agent-definition"
        ),
        "concurrency_key_template": (
            "project:{project_id}:book:{book_id}:agent:{agent_id}"
            if execution
            else "agent-definition:{agent_id}"
        ),
        "retry_policy": {
            "max_attempts": 3 if execution else 1,
            "dead_letter_on_exhausted": execution,
        },
        "timeout_policy": {
            "operation_timeout_seconds": 300 if execution else 30,
        },
        "cancellation_policy": {
            "mode": "cancel_active_attempt" if execution else "not_applicable",
        },
        "compensation_policy": {
            "supported": False,
            "reason": "append_only_definition_and_candidate_evidence",
        },
        "irreversible_effect_policy": {"allowed": False},
        "external_capabilities": (
            list(AGENT_RUNTIME_MODEL_EFFECT_CAPABILITIES) if execution else []
        ),
        "definition_status": "enabled",
        "evidence_status": {
            "documented": True,
            "implemented": True,
            "handler_bound": True,
            "integration_proven": False,
            "real_provider_proven": False,
            "longform_proven": False,
        },
        "projection_consumers": ["agent_run_query", "operation_timeline"],
        "migration_owner": "agent-runtime-authority",
        "legacy_entrypoints": [],
        "policy": {
            "execution_classification": (
                "durable_job" if execution else "transaction_command"
            ),
            "authority": "postgresql",
            "agent_run_status_owner": "projection",
            "attempt_owner": "command_kernel",
            "capability_pack_controls_operation": False,
            "candidate_only": execution,
            "domain_commit_required": execution,
            "local_storage_writes": "forbidden",
        },
        "completion_contract": completion,
    }


def _admin_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["agent_id", "payload"],
        "properties": {
            "agent_id": {"type": "string"},
            "payload": {"type": "object"},
            "expected_activation_version": {"type": "integer"},
        },
        "additionalProperties": False,
    }


def _execution_schema() -> dict[str, Any]:
    hash_schema = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
    properties: dict[str, Any] = {
        "agent_id": {"type": "string"},
        "agent_definition_version": {"type": "integer"},
        "agent_definition_hash": hash_schema,
        "capability_id": {"type": "string"},
        "capability_version": {"type": "integer"},
        "capability_hash": hash_schema,
        "execution_capability_id": {"type": "string"},
        "execution_capability_hash": hash_schema,
        "capability_pack_ref": {"type": "string"},
        "capability_pack_compilation_hash": hash_schema,
        "workflow_definition_ref": {"type": "string"},
        "workflow_node_id": {"type": "string"},
        "operation_definition_ref": {"type": "string"},
        "operation_definition_hash": hash_schema,
        "chapter_node_binding_ref": {"type": "string"},
        "collaboration_session_id": {"type": "string"},
        "scope_snapshot_ref": {"type": "string"},
        "participant_snapshot_ref": {"type": "string"},
        "book_id": {"type": "string"},
        "chapter_number": {"type": "integer", "minimum": 1},
        "context_bundle_asset_version_id": {"type": "string"},
        "context_bundle_hash": hash_schema,
        "input_asset_versions": {
            "type": "array",
            "items": {"type": "string"},
        },
        "prompt_bundle_ref": {"type": "string"},
        "prompt_bundle_hash": hash_schema,
        "skill_bundle_ref": {"type": "string"},
        "skill_bundle_hash": hash_schema,
        "tool_policy_ref": {"type": "string"},
        "tool_policy_hash": hash_schema,
        "context_policy_ref": {"type": "string"},
        "context_policy_hash": hash_schema,
        "evaluation_policy_ref": {"type": "string"},
        "evaluation_policy_hash": hash_schema,
        "route_policy_ref": {"type": "string"},
        "model_profile_ref": {"type": "string"},
        "budget_policy_ref": {"type": "string"},
        "timeout_policy_ref": {"type": "string"},
        "approval_policy_ref": {"type": "string"},
        "validation_policy_ref": {"type": "string"},
        "commit_policy_ref": {"type": "string"},
        "commit_authority": {"type": "string"},
        "message_type": {"type": "string"},
        "business_goal": {"type": "string"},
        "current_issue": {"type": "string"},
        "candidate_version_ref": {"type": "string"},
        "evidence_refs": {"type": "array", "items": {"type": "string"}},
        "must_preserve": {"type": "array", "items": {"type": "string"}},
        "must_change": {"type": "array", "items": {"type": "string"}},
        "forbidden_changes": {"type": "array", "items": {"type": "string"}},
        "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
        "risk_level": {"type": "string"},
        "failure_policy": {"type": "string"},
        "continuation_policy": {"type": "string"},
        "release_sha": {"type": "string"},
        "capability_pack_deployment_id": {"type": "string"},
        "capability_pack_activation_version": {"type": "integer", "minimum": 1},
        "capability_pack_binding_set_id": {"type": "string"},
        "capability_pack_binding_set_hash": hash_schema,
        "capability_pack_scope_type": {
            "type": "string",
            "enum": ["SYSTEM", "PROJECT", "WORKSPACE", "BOOK"],
        },
        "capability_pack_assignment_ref": {"type": "string"},
    }
    required = tuple(properties)
    return {
        "type": "object",
        "required": list(required),
        "properties": properties,
        "additionalProperties": False,
    }


__all__ = [
    "AGENT_RUNTIME_ADMIN_HANDLER_KEY",
    "AGENT_RUNTIME_ADMIN_OPERATIONS",
    "AGENT_RUNTIME_DEFINITION_VERSION",
    "AGENT_RUNTIME_EXECUTION_HANDLER_KEY",
    "AGENT_RUNTIME_MODEL_EFFECT_CAPABILITIES",
    "AGENT_RUNTIME_OPERATIONS",
    "agent_runtime_operation_definitions",
]

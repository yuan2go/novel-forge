"""OperationDefinitions for typed Content Authority execution."""
from __future__ import annotations

from typing import Any, Collection

from novel_forge.modules.content_authority.codecs import CONTENT_CODECS


CONTENT_DEFINITION_VERSION = "2.1.0"
CONTENT_INTEGRATION_PROVEN = frozenset(CONTENT_CODECS)


def content_operation_definitions(
    *,
    application_build_id: str,
    commit_sha: str,
    integration_proven: Collection[str] | None = None,
) -> tuple[dict[str, Any], ...]:
    proven = (
        CONTENT_INTEGRATION_PROVEN
        if integration_proven is None
        else frozenset(integration_proven)
    )
    unknown = proven - CONTENT_CODECS.keys()
    if unknown:
        raise ValueError(f"unknown content definition maturity: {sorted(unknown)}")
    command = {
        "type": "object",
        "required": ["project_id", "input_asset_version_ids", "payload"],
        "properties": {
            "project_id": {"type": "string"},
            "input_asset_version_ids": {"type": "array", "items": {"type": "string"}},
            "payload": {"type": "object"},
        },
        "additionalProperties": False,
    }
    result = {
        "type": "object",
        "required": ["asset_version_id", "content_hash"],
        "properties": {
            "asset_version_id": {"type": "string"},
            "content_hash": {"type": "string"},
        },
        "additionalProperties": False,
    }
    definitions = []
    for name, codec in CONTENT_CODECS.items():
        is_proven = name in proven
        status = "integration_proven" if is_proven else "handler_bound"
        completion_topic = f"content.{name}.materialized"
        definitions.append(
            {
                "name": name,
                "definition_version": CONTENT_DEFINITION_VERSION,
                "family": name.split(".")[0],
                "command_schema_version": f"{name}.command.v2",
                "result_schema_version": f"{name}.result.v2",
                "enabled": is_proven,
                "definition_status": status,
                "command_schema": command,
                "result_schema": result,
                "input_contract": command,
                "output_contract": {
                    **result,
                    "asset_type": codec.output_asset_type,
                    "output_key": codec.output_key,
                    "role": "primary",
                },
                "handler_key": f"novel_forge.content_authority.{name}",
                "handler_contract_version": "content-authority-handler-v2",
                "application_build_id": application_build_id,
                "commit_sha": commit_sha,
                "execution_mode": "worker",
                "permissions": [name],
                "approval_policy": {
                    "required": name == "creative.project.approve",
                    "policy_key": (
                        "operator.project.approval.v1"
                        if name == "creative.project.approve"
                        else "none"
                    ),
                },
                "policy": {
                    "project_scope_required": True,
                    "frozen_inputs_required": True,
                    "non_eligible_inputs": "fail_closed",
                    "side_effects": "external_effect_only",
                },
                "idempotency_scope": "project:content-domain",
                "concurrency_key_template": f"project:{{project_id}}:{name}",
                "retry_policy": {"max_attempts": 2},
                "timeout_policy": {"operation_timeout_seconds": 120},
                "cancellation_policy": {"mode": "cancel_active_attempt"},
                "compensation_policy": {
                    "supported": False,
                    "reason": "append_only_asset_versions",
                },
                "irreversible_effect_policy": {"allowed": False},
                "external_capabilities": [],
                "projection_consumers": [f"{name.split('.')[0]}_console"],
                "migration_owner": "content-intelligence-authority",
                "legacy_entrypoints": [],
                "evidence_status": {
                    "documented": True,
                    "implemented": True,
                    "handler_bound": True,
                    "integration_proven": is_proven,
                    "product_entrypoint_integrated": True,
                    "real_provider_proven": False,
                    "longform_proven": False,
                },
                "completion_contract": {
                    "version": f"{name}.completion.v2",
                    "required_asset_selectors": [
                        {
                            "selector": codec.output_asset_type,
                            "output_key": codec.output_key,
                            "role": "primary",
                            "lifecycle": "ACTIVE",
                            "eligibility": "ELIGIBLE",
                            "governance": "CLEAR",
                        }
                    ],
                    "required_qualifications": [{"decision": "ELIGIBLE"}],
                    "required_evidence": ["trace", "audit"],
                    "required_outbox_events": [completion_topic],
                },
                "current_entrypoints": [
                    "POST /product/content-authority/commands",
                    f"agent-capability:{name}",
                    f"workflow-operation:{name}",
                ],
                "agent_capability": {
                    "capability_key": name,
                    "execution_authority": "authority_operation",
                    "agent_run_role": "dispatch_projection",
                },
                "workflow_binding": {
                    "operation_definition": name,
                    "workflow_run_role": "operator_projection",
                },
                "current_handlers": [f"novel_forge.content_authority.{name}"],
                "migration_status": status,
            }
        )
    return tuple(definitions)


__all__ = [
    "CONTENT_DEFINITION_VERSION",
    "CONTENT_INTEGRATION_PROVEN",
    "content_operation_definitions",
]

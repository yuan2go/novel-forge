from __future__ import annotations

from typing import Any


PROJECT_AUTHORITY_DEFINITION_VERSION = "1.0.2"
PROJECT_AUTHORITY_OPERATIONS = (
    "project_lifecycle.create",
    "project_lifecycle.update",
    "project_lifecycle.transition",
    "project_binding.assign",
    "project_binding.remove",
)
PROJECT_AUTHORITY_HANDLER_KEY = "novel_forge.project_authority.lifecycle"


def project_authority_definitions(
    *, application_build_id: str, commit_sha: str
) -> tuple[dict[str, Any], ...]:
    command_schema = {
        "type": "object",
        "required": [
            "project_id",
            "workspace_id",
            "expected_version",
            "payload",
        ],
        "properties": {
            "project_id": {"type": "string"},
            "workspace_id": {"type": "string"},
            "expected_version": {"type": "integer"},
            "expected_current_asset_version_id": {"type": "string"},
            "payload": {"type": "object"},
        },
        "additionalProperties": False,
    }
    definitions: list[dict[str, Any]] = []
    for name in PROJECT_AUTHORITY_OPERATIONS:
        create = name.endswith(".create")
        selectors = [
            {
                "selector": "project_record",
                "output_key": "project.record",
                "role": "primary",
                "lifecycle": "ACTIVE",
                "eligibility": "ELIGIBLE",
                "governance": "CLEAR",
            }
        ]
        if name.startswith("project_binding."):
            selectors.append(
                {
                    "selector": "project_binding_record",
                    "output_key": "project.binding",
                    "role": "primary_binding",
                    "lifecycle": "ACTIVE",
                    "eligibility": "ELIGIBLE",
                    "governance": "CLEAR",
                }
            )
        if create:
            selectors.append(
                {
                    "selector": "workspace_record",
                    "output_key": "workspace.record",
                    "role": "primary_workspace",
                    "lifecycle": "ACTIVE",
                    "eligibility": "ELIGIBLE",
                    "governance": "CLEAR",
                }
            )
        event = f"authority.{name}.committed"
        definitions.append(
            {
                "name": name,
                "definition_version": PROJECT_AUTHORITY_DEFINITION_VERSION,
                "family": "project_lifecycle",
                "enabled": True,
                "command_schema": command_schema,
                "result_schema": {
                    "type": "object",
                    "required": ["project_id", "asset_version_id"],
                    "properties": {
                        "project_id": {"type": "string"},
                        "workspace_id": {"type": "string"},
                        "version": {"type": "integer"},
                        "asset_version_id": {"type": "string"},
                        "content_hash": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                "handler_key": PROJECT_AUTHORITY_HANDLER_KEY,
                "handler_contract_version": "project-authority-handler-v1",
                "application_build_id": application_build_id,
                "commit_sha": commit_sha,
                "execution_mode": "transactional",
                "permissions": ["project.authority.execute"],
                "approval_policy": {"required": False, "policy_key": "none"},
                "idempotency_scope": "project:lifecycle",
                "concurrency_key_template": "project:{project_id}",
                "retry_policy": {"max_attempts": 1, "mode": "client_replay_only"},
                "timeout_policy": {"operation_timeout_seconds": 60},
                "cancellation_policy": {"mode": "not_applicable_atomic_transaction"},
                "compensation_policy": {
                    "supported": False,
                    "reason": "append_only_project_asset_versions",
                },
                "irreversible_effect_policy": {"allowed": False},
                "external_capabilities": [],
                "policy": {
                    "execution_classification": "transaction_command",
                    "project_scope_required": True,
                    "filesystem_authority_forbidden": True,
                    "side_effects": "none",
                },
                "completion_contract": {
                    "version": f"{name}.completion.v1",
                    "required_asset_selectors": selectors,
                    "required_qualifications": [{"decision": "ELIGIBLE"}],
                    "required_evidence": ["trace", "audit"],
                    "required_outbox_events": [event],
                },
            }
        )
    return tuple(definitions)


__all__ = [
    "PROJECT_AUTHORITY_DEFINITION_VERSION",
    "PROJECT_AUTHORITY_HANDLER_KEY",
    "PROJECT_AUTHORITY_OPERATIONS",
    "project_authority_definitions",
]

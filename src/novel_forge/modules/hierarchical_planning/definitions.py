"""Operation definition for formal Planning binding activation."""
from __future__ import annotations

from typing import Any


PLAN_BINDING_DEFINITION_VERSION = "1.0.0"
PLAN_BINDING_HANDLER_KEY = "novel_forge.hierarchical_planning.binding.transaction"


def plan_binding_definitions(
    *, application_build_id: str, commit_sha: str
) -> tuple[dict[str, Any], ...]:
    return (
        {
            "name": "planning.binding.activate",
            "definition_version": PLAN_BINDING_DEFINITION_VERSION,
            "family": "hierarchical_planning",
            "enabled": True,
            "command_schema": {
                "type": "object",
                "required": [
                    "project_id",
                    "workspace_id",
                    "book_id",
                    "asset_version_id",
                    "contract_type",
                    "parent_version_id",
                    "execution_scope",
                    "expected_active_asset_version_id",
                    "replacement_approved",
                    "decision_evidence",
                ],
                "properties": {
                    "project_id": {"type": "string"},
                    "workspace_id": {"type": "string"},
                    "book_id": {"type": "string"},
                    "asset_version_id": {"type": "string"},
                    "contract_type": {"type": "string"},
                    "parent_version_id": {"type": "string"},
                    "execution_scope": {"type": "string"},
                    "expected_active_asset_version_id": {"type": "string"},
                    "replacement_approved": {"type": "boolean"},
                    "decision_evidence": {"type": "object"},
                },
                "additionalProperties": False,
            },
            "result_schema": {
                "type": "object",
                "required": [
                    "binding_id",
                    "book_id",
                    "asset_version_id",
                    "logical_key",
                ],
                "properties": {
                    "binding_id": {"type": "string"},
                    "book_id": {"type": "string"},
                    "asset_version_id": {"type": "string"},
                    "logical_key": {"type": "string"},
                    "previous_asset_version_id": {"type": "string"},
                },
                "additionalProperties": False,
            },
            "handler_key": PLAN_BINDING_HANDLER_KEY,
            "handler_contract_version": "planning-binding-handler-v1",
            "application_build_id": application_build_id,
            "commit_sha": commit_sha,
            "execution_mode": "transactional",
            "permissions": ["book.authority.execute"],
            "approval_policy": {
                "required": False,
                "policy_key": "replacement-decision-evidence",
            },
            "idempotency_scope": "book:planning-binding",
            "concurrency_key_template": "book:{book_id}:planning-binding",
            "retry_policy": {"max_attempts": 1, "mode": "client_replay_only"},
            "timeout_policy": {"operation_timeout_seconds": 60},
            "cancellation_policy": {"mode": "not_applicable_atomic_transaction"},
            "compensation_policy": {
                "supported": False,
                "reason": "binding activation is atomically version-checked",
            },
            "irreversible_effect_policy": {"allowed": False},
            "external_capabilities": [],
            "policy": {
                "execution_classification": "transaction_command",
                "book_scope_required": True,
                "expected_active_version_required": True,
                "legacy_writer": "disabled",
            },
            "completion_contract": {
                "version": "planning.binding.activate.completion.v1",
                "required_asset_selectors": [],
                "required_qualifications": [],
                "required_evidence": ["trace", "audit"],
                "required_outbox_events": ["story_plan.bound"],
            },
        },
    )


__all__ = [
    "PLAN_BINDING_DEFINITION_VERSION",
    "PLAN_BINDING_HANDLER_KEY",
    "plan_binding_definitions",
]

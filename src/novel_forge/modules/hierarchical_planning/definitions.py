from __future__ import annotations

from typing import Any


PLAN_BINDING_DEFINITION_VERSION = "1.2.0"
PLAN_BINDING_HANDLER_KEY = "novel_forge.hierarchical_planning.binding.transaction"
NARRATIVE_REALIZATION_DEFINITION_VERSION = "1.0.0"
NARRATIVE_REALIZATION_HANDLER_KEY = (
    "novel_forge.hierarchical_planning.realization.transaction"
)
NARRATIVE_REALIZATION_OPERATIONS = (
    "planning.realization.qualify",
    "planning.realization.approve",
    "planning.realization.freeze",
    "planning.realization.mark_stale",
)


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
                    "story_design_transition_operation_id",
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
                    "story_design_transition_operation_id": {"type": "string"},
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
            "handler_contract_version": "planning-binding-handler-v3",
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
                "atomic_story_design_activation": True,
                "chapter_contract_schema_version": "chapter-mission-scene.v2",
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


def narrative_realization_definitions(
    *, application_build_id: str, commit_sha: str
) -> tuple[dict[str, Any], ...]:
    definitions: list[dict[str, Any]] = []
    for name in NARRATIVE_REALIZATION_OPERATIONS:
        definitions.append(
            {
                "name": name,
                "definition_version": NARRATIVE_REALIZATION_DEFINITION_VERSION,
                "family": "hierarchical_planning",
                "enabled": True,
                "command_schema": {
                    "type": "object",
                    "required": [
                        "project_id",
                        "workspace_id",
                        "book_id",
                        "realization_id",
                        "expected_version",
                        "contract",
                        "reason",
                    ],
                    "properties": {
                        "project_id": {"type": "string"},
                        "workspace_id": {"type": "string"},
                        "book_id": {"type": "string"},
                        "realization_id": {"type": "string"},
                        "expected_version": {"type": "integer"},
                        "contract": {"type": "object"},
                        "reason": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                "result_schema": {
                    "type": "object",
                    "required": [
                        "realization_id",
                        "lifecycle",
                        "version",
                        "contract_digest",
                    ],
                    "properties": {
                        "realization_id": {"type": "string"},
                        "lifecycle": {"type": "string"},
                        "version": {"type": "integer"},
                        "contract_digest": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                "handler_key": NARRATIVE_REALIZATION_HANDLER_KEY,
                "handler_contract_version": "narrative-realization-handler-v1",
                "application_build_id": application_build_id,
                "commit_sha": commit_sha,
                "execution_mode": "transactional",
                "permissions": ["book.authority.execute"],
                "approval_policy": {
                    # INVARIANT: The explicit approve Operation is the Planning Authority
                    # decision and can only follow a qualified immutable proof.
                    # Command-Kernel admission approval is reserved for an
                    # external governance gate, not duplicated here.
                    "required": False,
                    "policy_key": "qualified-realization-transition-v1",
                },
                "idempotency_scope": "book:narrative-realization",
                "concurrency_key_template": "book:{book_id}:narrative-realization",
                "retry_policy": {"max_attempts": 1, "mode": "client_replay_only"},
                "timeout_policy": {"operation_timeout_seconds": 60},
                "cancellation_policy": {"mode": "not_applicable_atomic_transaction"},
                "compensation_policy": {
                    "supported": False,
                    "reason": "immutable evidence and versioned lifecycle transitions",
                },
                "irreversible_effect_policy": {"allowed": False},
                "external_capabilities": [],
                "policy": {
                    "execution_classification": "transaction_command",
                    "book_scope_required": True,
                    "separate_plan_scale": False,
                    "accepted_actual_mutation": False,
                    "frozen_input_drift_fails_closed": True,
                },
                "completion_contract": {
                    "version": f"{name}.completion.v1",
                    "required_asset_selectors": [],
                    "required_qualifications": [],
                    "required_evidence": ["trace", "audit"],
                    "required_outbox_events": ["narrative_realization.transitioned"],
                },
            }
        )
    return tuple(definitions)


__all__ = [
    "NARRATIVE_REALIZATION_DEFINITION_VERSION",
    "NARRATIVE_REALIZATION_HANDLER_KEY",
    "NARRATIVE_REALIZATION_OPERATIONS",
    "PLAN_BINDING_DEFINITION_VERSION",
    "PLAN_BINDING_HANDLER_KEY",
    "plan_binding_definitions",
    "narrative_realization_definitions",
]

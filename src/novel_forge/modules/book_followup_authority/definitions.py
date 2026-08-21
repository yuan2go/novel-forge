"""OperationDefinitions for governed post-chapter decisions."""
from __future__ import annotations

from typing import Any

from .contracts import (
    BOOK_FOLLOWUP_DEFINITION_VERSION,
    LONGFORM_RECAP_DEFINITION,
    READER_OUTCOME_DEFINITION,
)


def book_followup_operation_definitions(
    *, application_build_id: str, commit_sha: str
) -> tuple[dict[str, Any], ...]:
    if not application_build_id or len(commit_sha) != 40:
        raise ValueError("Book follow-up definitions require build id and full commit SHA")
    command = {
        "type": "object",
        "required": ["project_id", "input_asset_version_ids", "payload"],
        "properties": {
            "project_id": {"type": "string"},
            "input_asset_version_ids": {
                "type": "array",
                "items": {"type": "string"},
            },
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
    specifications = (
        (
            READER_OUTCOME_DEFINITION,
            "reader_outcome_report",
            "reader_outcome.report",
            ("reader_state_transition", "reader_issue_set"),
            ("model.reader_outcome",),
            180,
        ),
        (
            LONGFORM_RECAP_DEFINITION,
            "longform_recap",
            "longform.recap.report",
            ("longform_deviation_report", "plan_adjustment_proposal"),
            (),
            120,
        ),
    )
    definitions: list[dict[str, Any]] = []
    for name, asset_type, output_key, auxiliary_types, capabilities, timeout in specifications:
        definitions.append(
            {
                "name": name,
                "definition_version": BOOK_FOLLOWUP_DEFINITION_VERSION,
                "family": "book_followup_authority",
                "enabled": True,
                "definition_status": "integration_proven",
                "command_schema_version": f"{name}.command.v1",
                "result_schema_version": f"{name}.result.v1",
                "command_schema": command,
                "result_schema": result,
                "input_contract": command,
                "output_contract": {
                    **result,
                    "asset_type": asset_type,
                    "output_key": output_key,
                    "role": "primary",
                    "auxiliary_asset_types": list(auxiliary_types),
                    "optional_auxiliary_asset_types": (
                        ["replan_request", "arc_revision_candidate"]
                        if name == LONGFORM_RECAP_DEFINITION
                        else []
                    ),
                },
                "handler_key": f"novel_forge.book_followup_authority.{name}",
                "handler_contract_version": "book-followup-handler-v2",
                "application_build_id": application_build_id,
                "commit_sha": commit_sha,
                "execution_mode": "worker",
                "permissions": [f"book.followup:{name}"],
                "approval_policy": {"required": False, "policy_key": "none"},
                "policy": {
                    "frozen_inputs_required": True,
                    "body_mutation_allowed": False,
                    "plan_mutation_allowed": False,
                    "authority_decision_required_for_proposals": True,
                },
                "idempotency_scope": "project:book-followup",
                "concurrency_key_template": f"project:{{project_id}}:{name}",
                "retry_policy": {"max_attempts": 2},
                "timeout_policy": {"operation_timeout_seconds": timeout},
                "cancellation_policy": {"mode": "cancel_active_attempt"},
                "compensation_policy": {
                    "supported": False,
                    "reason": "append_only_asset_versions",
                },
                "irreversible_effect_policy": {"allowed": False},
                "external_capabilities": list(capabilities),
                "projection_consumers": [
                    "reader_outcome_projection"
                    if name == READER_OUTCOME_DEFINITION
                    else "longform_recap_projection",
                    "book_followup_progress_projection"
                    if name == READER_OUTCOME_DEFINITION
                    else "advisory_plan_change_proposal",
                ],
                "migration_owner": "book-followup-authority",
                "legacy_entrypoints": (
                    []
                    if name == READER_OUTCOME_DEFINITION
                    else [
                        "novel_forge.modules.longform_recap.service.run_longform_recap"
                    ]
                ),
                "evidence_status": {
                    "documented": True,
                    "implemented": True,
                    "handler_bound": True,
                    "integration_proven": True,
                    "real_provider_proven": False,
                    "longform_proven": False,
                    "production_verified": False,
                },
                "completion_contract": {
                    "version": f"{name}.completion.v1",
                    "required_asset_selectors": [
                        {
                            "selector": asset_type,
                            "output_key": output_key,
                            "role": "primary",
                            "lifecycle": "ACTIVE",
                            "eligibility": "ELIGIBLE",
                            "governance": "CLEAR",
                        }
                    ],
                    "required_qualifications": [{"decision": "ELIGIBLE"}],
                    "required_evidence": ["trace", "audit"],
                    "required_outbox_events": [f"book_followup.{name}.materialized"],
                },
            }
        )
    return tuple(definitions)


__all__ = ["book_followup_operation_definitions"]

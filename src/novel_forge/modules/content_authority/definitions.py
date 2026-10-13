from __future__ import annotations

from typing import Any, Collection

from novel_forge.modules.content_authority.codecs import CONTENT_CODECS


CONTENT_DEFINITION_VERSION = "2.1.1"
CONTENT_AUTHOR_REVIEW_VERSION = "2.1.2"
CONTENT_EDITORIAL_BRIEF_VERSION = "2.1.3"
CONTENT_WORK_STYLE_VERSION = "2.1.4"
CONTENT_SCOPED_STYLE_VERSION = "2.1.6"
CONTENT_INPUT_SELECTION_VERSION = "2.1.5"
CONTENT_INTEGRATION_PROVEN = frozenset(CONTENT_CODECS)


def content_operation_definitions(
    *,
    application_build_id: str,
    commit_sha: str,
    integration_proven: Collection[str] | None = None,
    reference_annotations: bool = False,
    world_reference_annotations: bool = False,
    planning_reference_annotations: bool = False,
    prose_reference_annotations: bool = False,
    screenplay_reference_annotations: bool = False,
    model_reference_annotations: bool = False,
) -> tuple[dict[str, Any], ...]:
    from novel_forge.modules.chapter_quality_authority.reference_subject import (
        REFERENCE_ANNOTATION_DEFINITIONS, REFERENCE_ANNOTATION_VERSION, WORLD_REFERENCE_ANNOTATION_VERSION,
        PLANNING_REFERENCE_ANNOTATION_VERSION,
    )
    from novel_forge.modules.book_followup_authority.prose_sample_feedback import PROSE_ANNOTATION_VERSION

    from novel_forge.modules.book_followup_authority.screenplay_sample_feedback import SCREENPLAY_ANNOTATION_VERSION
    from novel_forge.modules.chapter_quality_authority.model_reference import (
        MODEL_REFERENCE_ADJUDICATION, MODEL_REFERENCE_EVALUATION, MODEL_REFERENCE_VERSION,
    )
    if screenplay_reference_annotations and (not reference_annotations or any((prose_reference_annotations, world_reference_annotations, planning_reference_annotations))):
        raise ValueError("Screenplay sample annotations require their own reference annotation contract")
    if prose_reference_annotations and (not reference_annotations or world_reference_annotations or planning_reference_annotations):
        raise ValueError("Prose sample annotations require their own reference annotation contract")
    if world_reference_annotations and not reference_annotations:
        raise ValueError("World sample annotations require the native reference annotation contract")
    if planning_reference_annotations and (not reference_annotations or world_reference_annotations):
        raise ValueError("Planning sample annotations require their own reference annotation contract")
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
        if name in {MODEL_REFERENCE_EVALUATION, MODEL_REFERENCE_ADJUDICATION} and not model_reference_annotations:
            continue
        if reference_annotations and name not in REFERENCE_ANNOTATION_DEFINITIONS:
            continue
        if model_reference_annotations and name not in {MODEL_REFERENCE_EVALUATION, MODEL_REFERENCE_ADJUDICATION}:
            continue
        is_proven = name in proven
        status = "integration_proven" if is_proven else "handler_bound"
        completion_topic = f"content.{name}.materialized"
        definitions.append(
            {
                "name": name,
                "definition_version": MODEL_REFERENCE_VERSION if model_reference_annotations else SCREENPLAY_ANNOTATION_VERSION if screenplay_reference_annotations else PROSE_ANNOTATION_VERSION if prose_reference_annotations else PLANNING_REFERENCE_ANNOTATION_VERSION if planning_reference_annotations else
                    WORLD_REFERENCE_ANNOTATION_VERSION if world_reference_annotations else
                    REFERENCE_ANNOTATION_VERSION if reference_annotations else
                    CONTENT_AUTHOR_REVIEW_VERSION if name == "story_design.review.author" else
                    CONTENT_INPUT_SELECTION_VERSION if name == "creative.brief.create" else
                    CONTENT_SCOPED_STYLE_VERSION if name == "chapter.style_policy.compile" else CONTENT_DEFINITION_VERSION,
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
                "permissions": [f"content.operation:{name}"],
                "approval_policy": {
                    "required": name == "creative.project.approve",
                    "policy_key": (
                        "operator.project.approval.v1"
                        if name == "creative.project.approve"
                        else "none"
                    ),
                },
                "policy": {
                    **({"reference_sample_annotation_input_allowed": True} if reference_annotations else {}),
                    **({"model_reference_annotation_input_allowed": True} if model_reference_annotations else {}),
                    **({"world_reference_sample_annotation": True} if world_reference_annotations else {}),
                    **({"planning_reference_sample_annotation": True} if planning_reference_annotations else {}),
                    **({"prose_reference_sample_annotation": True} if prose_reference_annotations else {}),
                    **({"screenplay_reference_sample_annotation": True} if screenplay_reference_annotations else {}),
                    **({"evaluation_candidate_asset_input_allowed": True}
                       if name == "story_design.review.author" else {}),
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

"""Versioned OperationDefinitions for the PostgreSQL-only chapter slice."""
from __future__ import annotations

from typing import Any

from novel_forge.modules.chapter_authority.contracts import ChapterNode


CHAPTER_SLICE_DEFINITION_VERSION = "2.0.2"
CHAPTER_MODEL_EFFECT_DEFINITION_VERSION = "2.1.2"
CHAPTER_SLICE_HANDLER_CONTRACT_VERSION = "2.0.2"
CHAPTER_SLICE_ROOT_DEFINITION_NAME = "chapter.slice.run"
CHAPTER_SLICE_ROOT_HANDLER_KEY = "novel_forge.chapter_authority.root"
CHAPTER_PROJECTION_CONSUMERS = [
    "chapter_production_run",
    "operation_timeline",
    "project_cockpit",
]


def chapter_operation_definitions(
    *,
    application_build_id: str,
    commit_sha: str,
    model_effects_required: bool = False,
) -> tuple[dict[str, Any], ...]:
    if not application_build_id or len(commit_sha) != 40:
        raise ValueError("application_build_id and a 40-character commit_sha are required")
    return tuple(
        _definition(
            node,
            application_build_id=application_build_id,
            commit_sha=commit_sha,
            model_effects_required=model_effects_required,
        )
        for node in ChapterNode
    )


def chapter_root_operation_definition(
    *,
    application_build_id: str,
    commit_sha: str,
    model_effects_required: bool = False,
) -> dict[str, Any]:
    if not application_build_id or len(commit_sha) != 40:
        raise ValueError("application_build_id and a 40-character commit_sha are required")
    command_schema = _chapter_command_schema()
    result_schema = {"type": "object"}
    return {
        "name": CHAPTER_SLICE_ROOT_DEFINITION_NAME,
        "definition_version": chapter_definition_version(model_effects_required),
        "family": "chapter_authority",
        "enabled": True,
        "command_schema": command_schema,
        "result_schema": result_schema,
        "input_contract": command_schema,
        "output_contract": result_schema,
        "handler_key": CHAPTER_SLICE_ROOT_HANDLER_KEY,
        "handler_contract_version": CHAPTER_SLICE_HANDLER_CONTRACT_VERSION,
        "application_build_id": application_build_id,
        "commit_sha": commit_sha,
        "execution_mode": "saga",
        "permissions": ["chapter.authority.execute"],
        "approval_policy": {"required": False},
        "idempotency_scope": "project:chapter-slice",
        "concurrency_key_template": "project:{project_id}:chapter-slice:root",
        "retry_policy": {"max_attempts": 1},
        "timeout_policy": {"operation_timeout_seconds": 600},
        "cancellation_policy": {"mode": "cancel_children"},
        "compensation_policy": {"supported": False, "reason": "append_only_evidence"},
        "irreversible_effect_policy": {"allowed": False},
        "external_capabilities": [],
        **_definition_maturity_metadata(),
        "policy": {
            "authority": "postgresql",
            "local_storage_writes": "forbidden",
            "orchestration": "dynamic_fenced_saga_v1",
        },
        "completion_contract": {
            "version": "chapter.slice.run.completion.v1",
            "required_child_operations": [
                {"definition_name": node.definition_name, "allowed_states": ["SUCCEEDED"]}
                for node in ChapterNode
            ],
            "required_evidence": ["trace", "audit"],
        },
    }


def _definition(
    node: ChapterNode,
    *,
    application_build_id: str,
    commit_sha: str,
    model_effects_required: bool,
) -> dict[str, Any]:
    command_schema = _chapter_command_schema()
    completion: dict[str, Any] = {
        "version": f"{node.definition_name}.completion.v1",
        "required_asset_selectors": [
            {
                "selector": node.asset_type,
                "output_key": node.output_key,
                "role": "primary",
                "lifecycle": "ACTIVE",
                "eligibility": "ELIGIBLE",
                "governance": "CLEAR",
            }
        ],
        "required_qualifications": ["production_eligible"],
        "required_evidence": ["trace", "audit"],
        "required_audit_actions": [node.completion_topic],
        "required_outbox_events": [node.completion_topic],
    }
    external_capabilities: list[str] = []
    model_capability = {
        ChapterNode.DRAFT: "model.draft",
        ChapterNode.REVIEW: "model.review",
        ChapterNode.REVISION: "model.revision",
        ChapterNode.REREVIEW: "model.review",
    }.get(node)
    if model_effects_required and model_capability:
        completion["required_external_effects"] = [
            {"capability": model_capability, "allowed_states": ["SUCCEEDED"]}
        ]
        external_capabilities = [model_capability]
    if node is ChapterNode.EXPORT:
        completion.update(
            {
                "required_blobs": [
                    {"status": "AVAILABLE", "role": "content", "min_count": 1}
                ],
                "required_external_effects": [
                    {
                        "capability": "object_store.put",
                        "allowed_states": ["SUCCEEDED"],
                    }
                ],
            }
        )
        external_capabilities = [*external_capabilities, "object_store.put"]
    result_schema = {
        "type": "object",
        "required": ["asset_version_id", "content_hash"],
        "properties": {
            "asset_version_id": {"type": "string"},
            "content_hash": {"type": "string"},
        },
        "additionalProperties": False,
    }
    return {
        "name": node.definition_name,
        "definition_version": chapter_definition_version(model_effects_required),
        "family": "chapter_authority",
        "enabled": True,
        "command_schema": command_schema,
        "result_schema": result_schema,
        "input_contract": command_schema,
        "output_contract": result_schema,
        "handler_key": node.handler_key,
        "handler_contract_version": (
            "2.1.0" if model_effects_required else CHAPTER_SLICE_HANDLER_CONTRACT_VERSION
        ),
        "application_build_id": application_build_id,
        "commit_sha": commit_sha,
        "execution_mode": "worker",
        "permissions": ["chapter.authority.execute"],
        "approval_policy": {"required": False},
        "idempotency_scope": "project:chapter-slice",
        "concurrency_key_template": "project:{project_id}:chapter-slice",
        "retry_policy": {"max_attempts": 2},
        "timeout_policy": {"operation_timeout_seconds": 60},
        "cancellation_policy": {"mode": "cancel_active_attempt"},
        "compensation_policy": {"supported": False, "reason": "append_only_evidence"},
        "irreversible_effect_policy": {"allowed": False},
        "external_capabilities": external_capabilities,
        **_definition_maturity_metadata(),
        "policy": {
            "authority": "postgresql",
            "local_storage_writes": "forbidden",
            "handler_output_policy": "chapter-authority-output-v1",
        },
        "completion_contract": completion,
    }


def _definition_maturity_metadata() -> dict[str, Any]:
    """Describe runtime binding without claiming test/provider proof here.

    The generated catalog may promote this to ``integration_proven`` when it
    attaches the committed PostgreSQL evidence suite.  Runtime definitions
    themselves only assert that a concrete handler is bound and enabled.
    """

    return {
        "definition_status": "enabled",
        "evidence_status": {
            "documented": True,
            "implemented": True,
            "handler_bound": True,
            "integration_proven": False,
            "real_provider_proven": False,
            "longform_proven": False,
        },
        "projection_consumers": list(CHAPTER_PROJECTION_CONSUMERS),
        "migration_owner": "chapter-authority",
        "legacy_entrypoints": [],
    }


def chapter_definition_version(model_effects_required: bool) -> str:
    return (
        CHAPTER_MODEL_EFFECT_DEFINITION_VERSION
        if model_effects_required
        else CHAPTER_SLICE_DEFINITION_VERSION
    )


def _chapter_command_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["chapter"],
        "properties": {
            "chapter": {"type": "integer"},
            "premise": {"type": "string"},
            "title": {"type": "string"},
            "context_candidates": {
                "type": "array",
                "items": {"type": "object"},
            },
            "context_version_refs": {"type": "object"},
            "context_token_budget": {"type": "integer"},
        },
        "additionalProperties": False,
    }

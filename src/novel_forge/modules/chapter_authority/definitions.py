"""Versioned OperationDefinitions for the PostgreSQL-only chapter slice."""
from __future__ import annotations

from typing import Any

from novel_forge.modules.chapter_authority.contracts import ChapterNode


CHAPTER_SLICE_DEFINITION_VERSION = "1.0.0"
CHAPTER_SLICE_HANDLER_CONTRACT_VERSION = "1.0.0"
CHAPTER_SLICE_ROOT_DEFINITION_NAME = "chapter.slice.run"
CHAPTER_SLICE_ROOT_HANDLER_KEY = "novel_forge.chapter_authority.root"


def chapter_operation_definitions(
    *,
    application_build_id: str,
    commit_sha: str,
) -> tuple[dict[str, Any], ...]:
    if not application_build_id or len(commit_sha) != 40:
        raise ValueError("application_build_id and a 40-character commit_sha are required")
    return tuple(
        _definition(node, application_build_id=application_build_id, commit_sha=commit_sha)
        for node in ChapterNode
    )


def chapter_root_operation_definition(
    *,
    application_build_id: str,
    commit_sha: str,
) -> dict[str, Any]:
    if not application_build_id or len(commit_sha) != 40:
        raise ValueError("application_build_id and a 40-character commit_sha are required")
    return {
        "name": CHAPTER_SLICE_ROOT_DEFINITION_NAME,
        "definition_version": CHAPTER_SLICE_DEFINITION_VERSION,
        "family": "chapter_authority",
        "enabled": True,
        "command_schema": _chapter_command_schema(),
        "result_schema": {"type": "object"},
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
) -> dict[str, Any]:
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
        external_capabilities = ["object_store.put"]
    return {
        "name": node.definition_name,
        "definition_version": CHAPTER_SLICE_DEFINITION_VERSION,
        "family": "chapter_authority",
        "enabled": True,
        "command_schema": _chapter_command_schema(),
        "result_schema": {
            "type": "object",
            "required": ["asset_version_id", "content_hash"],
            "properties": {
                "asset_version_id": {"type": "string"},
                "content_hash": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "handler_key": node.handler_key,
        "handler_contract_version": CHAPTER_SLICE_HANDLER_CONTRACT_VERSION,
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
        "policy": {
            "authority": "postgresql",
            "local_storage_writes": "forbidden",
            "handler_output_policy": "chapter-authority-output-v1",
        },
        "completion_contract": completion,
    }


def _chapter_command_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["chapter"],
        "properties": {
            "chapter": {"type": "integer"},
            "premise": {"type": "string"},
            "title": {"type": "string"},
        },
        "additionalProperties": False,
    }

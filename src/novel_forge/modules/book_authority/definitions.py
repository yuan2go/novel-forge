from __future__ import annotations

from typing import Any

from .codecs import BOOK_CODECS

BOOK_DEFINITION_VERSION = "1.0.1"
BOOK_ROOT_DEFINITION = "book.production.run"
BOOK_ROOT_HANDLER = "novel_forge.book_authority.root"


def book_definitions(*, application_build_id: str, commit_sha: str) -> tuple[dict[str, Any], ...]:
    if not application_build_id or len(commit_sha) != 40:
        raise ValueError("book definitions require build id and full commit SHA")
    command = {
        "type": "object", "required": ["project_id", "input_asset_version_ids", "payload"],
        "properties": {"project_id": {"type": "string"}, "input_asset_version_ids": {"type": "array"}, "payload": {"type": "object"}},
        "additionalProperties": False,
    }
    common = {
        "definition_version": BOOK_DEFINITION_VERSION, "family": "book_authority",
        "enabled": True, "command_schema": command, "input_contract": command,
        "application_build_id": application_build_id, "commit_sha": commit_sha,
        "permissions": ["book.authority.execute"], "idempotency_scope": "project:book-production",
        "approval_policy": {"required": False},
        "concurrency_key_template": "project:{project_id}:book-production",
        "retry_policy": {"max_attempts": 2}, "timeout_policy": {"operation_timeout_seconds": 300},
        "cancellation_policy": {"mode": "cancel_children"}, "external_capabilities": [],
        "compensation_policy": {"supported": False, "reason": "append_only_assets"},
        "irreversible_effect_policy": {"allowed": False},
        "definition_status": "integration_proven", "production_verified": False,
    }
    root = {
        **common, "name": BOOK_ROOT_DEFINITION, "execution_mode": "saga",
        "command_schema_version": "book.production.run.command.v1",
        "result_schema_version": "book.production.run.result.v1",
        "handler_key": BOOK_ROOT_HANDLER, "handler_contract_version": "book-root-v1",
        "result_schema": {"type": "object"}, "output_contract": {"type": "object"},
        "projection_consumers": ["book_production_timeline", "operation_timeline"],
        "migration_owner": "book-authority",
        "completion_contract": {
            "version": "book.production.run.completion.v1",
            "required_evidence": ["trace", "audit"],
            "required_child_operations": [
                {"definition_name": name, "allowed_states": ["SUCCEEDED"]}
                for name in BOOK_CODECS
            ],
        },
        "policy": {"execution_classification": "saga", "fixture_protocol_only": True, "real_provider_proven": False},
    }
    children = []
    for name, codec in BOOK_CODECS.items():
        topic = f"content.{name}.materialized"
        children.append({
            **common, "name": name, "execution_mode": "worker",
            "command_schema_version": f"{name}.command.v1",
            "result_schema_version": f"{name}.result.v1",
            "handler_key": f"novel_forge.content_authority.{name}",
            "handler_contract_version": "content-authority-handler-v2",
            "result_schema": {"type": "object"},
            "output_contract": {"asset_type": codec.output_asset_type, "output_key": codec.output_key},
            "projection_consumers": ["book_production_timeline", "operation_timeline"],
            "migration_owner": "book-authority",
            "completion_contract": {
                "version": f"{name}.completion.v1",
                "required_asset_selectors": [{"selector": codec.output_asset_type, "output_key": codec.output_key, "role": "primary", "lifecycle": "ACTIVE", "eligibility": "ELIGIBLE", "governance": "CLEAR"}],
                "required_qualifications": ["production_eligible"],
                "required_audit_actions": [topic], "required_outbox_events": [topic],
                "required_evidence": ["trace", "audit"],
            },
            "policy": {"execution_classification": "durable_job", "fixture_protocol_only": True, "real_model_call": False},
        })
    return (root, *children)

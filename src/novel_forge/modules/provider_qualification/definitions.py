from __future__ import annotations

from typing import Any


D0_OPERATION = "provider.qualification.d0"
D0_DEFINITION_VERSION = "1.0.1"
D0_HANDLER_KEY = "novel_forge.provider_qualification.d0"


def d0_operation_definition(*, application_build_id: str, commit_sha: str) -> dict[str, Any]:
    return {
        "name": D0_OPERATION,
        "definition_version": D0_DEFINITION_VERSION,
        "family": "provider_qualification",
        "enabled": True,
        "command_schema": {
            "type": "object",
            "required": ["project_id", "workspace_id", "config"],
            "properties": {
                "project_id": {"type": "string"},
                "workspace_id": {"type": "string"},
                "config": {"type": "object"},
            },
            "additionalProperties": False,
        },
        "result_schema": {
            "type": "object",
            "required": ["qualification_run_id", "report_asset_version_id", "status"],
            "properties": {
                "qualification_run_id": {"type": "string"},
                "report_asset_version_id": {"type": "string"},
                "status": {"type": "string"},
            },
            "additionalProperties": True,
        },
        "handler_key": D0_HANDLER_KEY,
        "handler_contract_version": "d0-provider-qualification-handler.v1",
        "application_build_id": application_build_id,
        "commit_sha": commit_sha,
        "execution_mode": "worker",
        "permissions": ["provider.qualification.execute"],
        "approval_policy": {"required": False},
        "idempotency_scope": "project:provider-qualification",
        "concurrency_key_template": "project:{project_id}:provider-qualification",
        "retry_policy": {"max_attempts": 2},
        "timeout_policy": {"operation_timeout_seconds": 900},
        "cancellation_policy": {"mode": "cancel_external_effect"},
        "compensation_policy": {"supported": False},
        "irreversible_effect_policy": {"allowed": True, "receipt_required": True},
        "external_capabilities": ["structured.echo", "responses.retrieve", "responses.cancel"],
        "policy": {
            "execution_classification": "durable_job",
            "project_scope_required": True,
            "authority_evidence_required": True,
            "sdk_max_retries": 0,
        },
        "completion_contract": {
            "version": "provider.qualification.d0.completion.v1",
            "required_asset_selectors": [
                {
                    "selector": "d0_report",
                    "output_key": "provider.qualification.d0.report",
                    "role": "primary",
                    "lifecycle": "ACTIVE",
                    "eligibility": "INELIGIBLE",
                    "governance": "CLEAR",
                }
            ],
            "required_evidence": ["trace", "audit"],
            "required_outbox_events": ["authority.asset.materialized"],
        },
    }


__all__ = ["D0_DEFINITION_VERSION", "D0_HANDLER_KEY", "D0_OPERATION", "d0_operation_definition"]

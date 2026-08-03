from __future__ import annotations

from typing import Any


LEGACY_IMPORT_DEFINITION_NAME = "legacy_migration.asset.import"
LEGACY_IMPORT_DEFINITION_VERSION = "1.0.0"
LEGACY_IMPORT_HANDLER_KEY = "novel_forge.legacy_migration.asset_import"


def legacy_import_definition(
    *, application_build_id: str, commit_sha: str
) -> dict[str, Any]:
    return {
        "name": LEGACY_IMPORT_DEFINITION_NAME,
        "definition_version": LEGACY_IMPORT_DEFINITION_VERSION,
        "family": "legacy_migration",
        "enabled": True,
        "command_schema": {
            "type": "object",
            "required": [
                "project_id", "workspace_id", "source_ref", "source_hash",
                "source_asset_type", "stable_business_key", "payload",
            ],
            "properties": {
                "project_id": {"type": "string"},
                "workspace_id": {"type": "string"},
                "source_ref": {"type": "string"},
                "source_hash": {"type": "string"},
                "source_asset_type": {"type": "string"},
                "stable_business_key": {"type": "string"},
                "payload": {"type": "object"},
            },
            "additionalProperties": False,
        },
        "result_schema": {
            "type": "object",
            "required": ["asset_version_id", "content_hash"],
            "properties": {
                "asset_version_id": {"type": "string"},
                "content_hash": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "handler_key": LEGACY_IMPORT_HANDLER_KEY,
        "handler_contract_version": "legacy-import-handler-v1",
        "application_build_id": application_build_id,
        "commit_sha": commit_sha,
        "execution_mode": "worker",
        "permissions": ["legacy_migration.import"],
        "approval_policy": {"required": False, "policy_key": "migration-intake-v1"},
        "idempotency_scope": "project:legacy-migration",
        "concurrency_key_template": "project:{project_id}:legacy-migration",
        "retry_policy": {"max_attempts": 2},
        "timeout_policy": {"operation_timeout_seconds": 120},
        "cancellation_policy": {"mode": "cancel_active_attempt"},
        "compensation_policy": {
            "supported": False,
            "reason": "imported candidates are immutable and ineligible",
        },
        "irreversible_effect_policy": {"allowed": False},
        "external_capabilities": [],
        "policy": {
            "frozen_snapshot_required": True,
            "auto_activation_forbidden": True,
            "production_context_eligibility": "fail_closed",
        },
        "completion_contract": {
            "version": "legacy-migration.asset.import.completion.v1",
            "required_asset_selectors": [
                {
                    "selector": "legacy_import_candidate",
                    "output_key": "legacy.import.candidate",
                    "role": "primary",
                    "lifecycle": "IMPORTED",
                    "eligibility": "PENDING_EVALUATION",
                    "governance": "CLEAR",
                }
            ],
            "required_qualifications": [{"decision": "PENDING_EVALUATION"}],
            "required_evidence": ["trace", "audit"],
            "required_outbox_events": ["legacy_migration.asset.imported"],
        },
    }


__all__ = [
    "LEGACY_IMPORT_DEFINITION_NAME",
    "LEGACY_IMPORT_DEFINITION_VERSION",
    "LEGACY_IMPORT_HANDLER_KEY",
    "legacy_import_definition",
]

from __future__ import annotations

from typing import Any


SOURCE_AUTHORITY_DEFINITION_VERSION = "1.0.2"
SOURCE_AUTHORITY_HANDLER_KEY = "novel_forge.source_authority.document_register"
SOURCE_AUTHORITY_OPERATION = "source.document.register"
SOURCE_TRANSFORM_DEFINITION_VERSION = "1.0.1"
SOURCE_TRANSFORM_HANDLER_KEY = "novel_forge.source_authority.transform_commit"
SOURCE_TRANSFORM_OPERATION = "source.transform.commit"
SOURCE_OBSERVATION_DEFINITION_VERSION = "1.1.0"
SOURCE_OBSERVATION_HANDLER_KEY = (
    "novel_forge.source_authority.deconstruction_observation_commit"
)
SOURCE_OBSERVATION_OPERATION = "source.deconstruction.observation.commit"
SOURCE_REPROCESSING_DEFINITION_VERSION = "1.0.1"
SOURCE_REPROCESSING_HANDLER_KEY = (
    "novel_forge.source_authority.reprocessing_plan_commit"
)
SOURCE_REPROCESSING_OPERATION = "source.deconstruction.reprocessing.plan"
SOURCE_CONTENT_PROFILE_DEFINITION_VERSION = "1.1.0"
SOURCE_CONTENT_PROFILE_HANDLER_KEY = (
    "novel_forge.source_authority.content_profile_commit"
)
SOURCE_CONTENT_PROFILE_OPERATION = "source.content.profile.commit"
SOURCE_ANALYSIS_PLAN_DEFINITION_VERSION = "1.0.0"
SOURCE_ANALYSIS_PLAN_HANDLER_KEY = "novel_forge.source_authority.analysis_plan_commit"
SOURCE_ANALYSIS_PLAN_OPERATION = "source.analysis.plan.commit"
SOURCE_AUTHORITY_OPERATIONS = frozenset(
    {
        SOURCE_AUTHORITY_OPERATION,
        SOURCE_TRANSFORM_OPERATION,
        SOURCE_OBSERVATION_OPERATION,
        SOURCE_REPROCESSING_OPERATION,
        SOURCE_CONTENT_PROFILE_OPERATION,
        SOURCE_ANALYSIS_PLAN_OPERATION,
    }
)


def source_authority_definitions(
    *, application_build_id: str, commit_sha: str
) -> tuple[dict[str, Any], ...]:
    event = "authority.source.document.registered"
    return (
        {
            "name": SOURCE_AUTHORITY_OPERATION,
            "definition_version": SOURCE_AUTHORITY_DEFINITION_VERSION,
            "family": "source_governance",
            "enabled": True,
            "command_schema": {
                "type": "object",
                "required": ["project_id", "workspace_id", "blob_id", "payload"],
                "properties": {
                    "project_id": {"type": "string"},
                    "workspace_id": {"type": "string"},
                    "blob_id": {"type": "string"},
                    "payload": {"type": "object"},
                },
                "additionalProperties": False,
            },
            "result_schema": {
                "type": "object",
                "required": ["source_document_id", "asset_version_id"],
                "properties": {
                    "source_document_id": {"type": "string"},
                    "asset_version_id": {"type": "string"},
                },
                "additionalProperties": False,
            },
            "handler_key": SOURCE_AUTHORITY_HANDLER_KEY,
            "handler_contract_version": "source-authority-handler-v1",
            "application_build_id": application_build_id,
            "commit_sha": commit_sha,
            "execution_mode": "worker",
            "permissions": ["source.authority.execute"],
            "approval_policy": {"required": False, "policy_key": "rights-policy-v1"},
            "idempotency_scope": "project:source-document",
            "concurrency_key_template": "project:{project_id}:source-document",
            "retry_policy": {"max_attempts": 2},
            "timeout_policy": {"operation_timeout_seconds": 60},
            "cancellation_policy": {"mode": "cancel_active_attempt"},
            "compensation_policy": {
                "supported": False,
                "reason": "immutable object and AssetVersion evidence",
            },
            "irreversible_effect_policy": {"allowed": False},
            "external_capabilities": [],
            "policy": {
                "execution_classification": "durable_job",
                "project_scope_required": True,
                "verified_blob_required": True,
                "raw_source_in_postgresql_forbidden": True,
                "raw_source_in_generation_context_forbidden": True,
            },
            "completion_contract": {
                "version": "source.document.register.completion.v1",
                "required_asset_selectors": [
                    {
                        "selector": "source_document",
                        "output_key": "source.document",
                        "role": "primary",
                        "allowed_lifecycles": ["ACTIVE", "CANDIDATE"],
                        "allowed_eligibility": [
                            "ELIGIBLE",
                            "PENDING_EVALUATION",
                            "INELIGIBLE",
                        ],
                        "allowed_governance": ["CLEAR", "QUARANTINED"],
                    }
                ],
                "required_blobs": [{"status": "AVAILABLE", "role": "raw_source"}],
                "required_evidence": ["trace", "audit"],
                "required_outbox_events": [event],
            },
        },
        {
            "name": SOURCE_TRANSFORM_OPERATION,
            "definition_version": SOURCE_TRANSFORM_DEFINITION_VERSION,
            "family": "source_governance",
            "enabled": True,
            "command_schema": {
                "type": "object",
                "required": [
                    "project_id",
                    "workspace_id",
                    "source_document_id",
                    "payload",
                ],
                "properties": {
                    "project_id": {"type": "string"},
                    "workspace_id": {"type": "string"},
                    "source_document_id": {"type": "string"},
                    "payload": {"type": "object"},
                },
                "additionalProperties": False,
            },
            "result_schema": {
                "type": "object",
                "required": ["source_transform_id", "asset_version_id"],
                "properties": {
                    "source_transform_id": {"type": "string"},
                    "asset_version_id": {"type": "string"},
                },
                "additionalProperties": True,
            },
            "handler_key": SOURCE_TRANSFORM_HANDLER_KEY,
            "handler_contract_version": "source-transform-handler-v1",
            "application_build_id": application_build_id,
            "commit_sha": commit_sha,
            "execution_mode": "worker",
            "permissions": ["source.authority.execute"],
            "approval_policy": {
                "required": False,
                "policy_key": "source-transform-commit-v1",
            },
            "idempotency_scope": "project:source-transform",
            "concurrency_key_template": "project:{project_id}:source-transform",
            "retry_policy": {"max_attempts": 2},
            "timeout_policy": {"operation_timeout_seconds": 120},
            "cancellation_policy": {"mode": "cancel_active_attempt"},
            "compensation_policy": {
                "supported": False,
                "reason": "immutable transform manifest and chunk AssetVersions",
            },
            "irreversible_effect_policy": {"allowed": False},
            "external_capabilities": [],
            "policy": {
                "execution_classification": "durable_job",
                "project_scope_required": True,
                "verified_chunk_blobs_required": True,
                "prepared_transform_manifest_only": True,
                "raw_source_in_postgresql_forbidden": True,
                "source_chunks_are_evidence_only": True,
            },
            "completion_contract": {
                "version": "source.transform.commit.completion.v1",
                "required_asset_selectors": [
                    {
                        "selector": "source_transform_manifest",
                        "output_key": "source.transform.manifest",
                        "role": "primary",
                        "lifecycle": "ACTIVE",
                        "eligibility": "ELIGIBLE",
                        "governance": "CLEAR",
                    },
                    {
                        "selector": "source_chunk",
                        "role": "evidence",
                        "min_count": 1,
                        "lifecycle": "ACTIVE",
                        "eligibility": "INELIGIBLE",
                        "governance": "CLEAR",
                    },
                ],
                "required_blobs": [
                    {
                        "status": "AVAILABLE",
                        "role": "clean_source_chunk",
                        "min_count": 1,
                    }
                ],
                "required_evidence": ["trace", "audit"],
                "required_outbox_events": ["authority.source.transform.committed"],
            },
        },
        {
            "name": SOURCE_OBSERVATION_OPERATION,
            "definition_version": SOURCE_OBSERVATION_DEFINITION_VERSION,
            "family": "source_deconstruction",
            "enabled": True,
            "command_schema": {
                "type": "object",
                "required": ["project_id", "workspace_id", "payload"],
                "properties": {
                    "project_id": {"type": "string"},
                    "workspace_id": {"type": "string"},
                    "payload": {"type": "object"},
                },
                "additionalProperties": False,
            },
            "result_schema": {
                "type": "object",
                "required": ["observation_id", "asset_version_id"],
                "properties": {
                    "observation_id": {"type": "string"},
                    "asset_version_id": {"type": "string"},
                },
                "additionalProperties": True,
            },
            "handler_key": SOURCE_OBSERVATION_HANDLER_KEY,
            "handler_contract_version": "source-observation-handler-v1",
            "application_build_id": application_build_id,
            "commit_sha": commit_sha,
            "execution_mode": "worker",
            "permissions": ["source.authority.execute"],
            "approval_policy": {
                "required": False,
                "policy_key": "source-observation-commit-v1",
            },
            "idempotency_scope": "project:source-observation",
            "concurrency_key_template": "project:{project_id}:source-observation",
            "retry_policy": {"max_attempts": 2},
            "timeout_policy": {"operation_timeout_seconds": 120},
            "cancellation_policy": {"mode": "cancel_active_attempt"},
            "compensation_policy": {
                "supported": False,
                "reason": "Observation versions and evidence lineage are immutable",
            },
            "irreversible_effect_policy": {"allowed": False},
            "external_capabilities": [],
            "policy": {
                "execution_classification": "durable_job",
                "project_scope_required": True,
                "source_evidence_or_lower_observation_required": True,
                "provider_execution_evidence_required": True,
                "raw_source_in_postgresql_forbidden": True,
                "observation_is_not_reusable_knowledge": True,
                "source_observation_generation_context_forbidden": True,
            },
            "completion_contract": {
                "version": "source.deconstruction.observation.commit.completion.v1",
                "required_asset_selectors": [
                    {
                        "selector": "source_deconstruction_observation",
                        "output_key": "source.deconstruction.observation",
                        "role": "evidence",
                        "lifecycle": "ACTIVE",
                        "eligibility": "INELIGIBLE",
                        "governance": "CLEAR",
                    }
                ],
                "required_evidence": ["trace", "audit"],
                "required_outbox_events": [
                    "authority.source.deconstruction.observation.committed"
                ],
            },
        },
        {
            "name": SOURCE_REPROCESSING_OPERATION,
            "definition_version": SOURCE_REPROCESSING_DEFINITION_VERSION,
            "family": "source_deconstruction",
            "enabled": True,
            "command_schema": {
                "type": "object",
                "required": ["project_id", "workspace_id", "payload"],
                "properties": {
                    "project_id": {"type": "string"},
                    "workspace_id": {"type": "string"},
                    "payload": {"type": "object"},
                },
                "additionalProperties": False,
            },
            "result_schema": {
                "type": "object",
                "required": ["reprocessing_plan_id", "asset_version_id", "items"],
                "properties": {
                    "reprocessing_plan_id": {"type": "string"},
                    "asset_version_id": {"type": "string"},
                    "items": {"type": "array"},
                },
                "additionalProperties": True,
            },
            "handler_key": SOURCE_REPROCESSING_HANDLER_KEY,
            "handler_contract_version": "source-reprocessing-plan-handler-v1",
            "application_build_id": application_build_id,
            "commit_sha": commit_sha,
            "execution_mode": "worker",
            "permissions": ["source.authority.execute"],
            "approval_policy": {
                "required": False,
                "policy_key": "source-selective-reprocessing-v1",
            },
            "idempotency_scope": "project:source-reprocessing-plan",
            "concurrency_key_template": "project:{project_id}:source-reprocessing",
            "retry_policy": {"max_attempts": 2},
            "timeout_policy": {"operation_timeout_seconds": 120},
            "cancellation_policy": {"mode": "cancel_active_attempt"},
            "compensation_policy": {
                "supported": False,
                "reason": "plan and invalidation records are immutable evidence",
            },
            "irreversible_effect_policy": {"allowed": False},
            "external_capabilities": [],
            "policy": {
                "execution_classification": "durable_job",
                "project_scope_required": True,
                "lineage_driven": True,
                "unchanged_upstream_reuse_required": True,
                "selective_invalidation_required": True,
                "plan_does_not_execute_provider": True,
            },
            "completion_contract": {
                "version": "source.deconstruction.reprocessing.plan.completion.v1",
                "required_asset_selectors": [
                    {
                        "selector": "source_reprocessing_plan",
                        "output_key": "source.reprocessing.plan",
                        "role": "operational",
                        "lifecycle": "ACTIVE",
                        "eligibility": "INELIGIBLE",
                        "governance": "CLEAR",
                    }
                ],
                "required_evidence": ["trace", "audit"],
                "required_outbox_events": [
                    "authority.source.deconstruction.reprocessing.planned"
                ],
            },
        },
        _source_intelligence_definition(
            name=SOURCE_CONTENT_PROFILE_OPERATION,
            version=SOURCE_CONTENT_PROFILE_DEFINITION_VERSION,
            handler=SOURCE_CONTENT_PROFILE_HANDLER_KEY,
            output_key="source.content.profile",
            asset_type="source_content_profile",
            selector="source_content_profile",
            event="authority.source.content.profile.committed",
            application_build_id=application_build_id,
            commit_sha=commit_sha,
            handler_contract_version="source-intelligence-authority-v2",
        ),
        _source_intelligence_definition(
            name=SOURCE_ANALYSIS_PLAN_OPERATION,
            version=SOURCE_ANALYSIS_PLAN_DEFINITION_VERSION,
            handler=SOURCE_ANALYSIS_PLAN_HANDLER_KEY,
            output_key="source.analysis.plan",
            asset_type="source_analysis_plan",
            selector="source_analysis_plan",
            event="authority.source.analysis.plan.committed",
            application_build_id=application_build_id,
            commit_sha=commit_sha,
        ),
    )


def _source_intelligence_definition(
    *,
    name: str,
    version: str,
    handler: str,
    output_key: str,
    asset_type: str,
    selector: str,
    event: str,
    application_build_id: str,
    commit_sha: str,
    handler_contract_version: str = "source-intelligence-authority-v1",
) -> dict[str, Any]:
    return {
        "name": name,
        "definition_version": version,
        "family": "source_intelligence",
        "enabled": True,
        "command_schema": {
            "type": "object",
            "required": ["project_id", "workspace_id", "payload"],
            "properties": {
                "project_id": {"type": "string"},
                "workspace_id": {"type": "string"},
                "payload": {"type": "object"},
            },
            "additionalProperties": False,
        },
        "result_schema": {
            "type": "object",
            "required": ["asset_version_id"],
            "properties": {"asset_version_id": {"type": "string"}},
            "additionalProperties": True,
        },
        "handler_key": handler,
        "handler_contract_version": handler_contract_version,
        "application_build_id": application_build_id,
        "commit_sha": commit_sha,
        "execution_mode": "worker",
        "permissions": ["source.authority.execute"],
        "approval_policy": {"required": False, "policy_key": "source-intelligence-v1"},
        "idempotency_scope": f"project:{asset_type}",
        "concurrency_key_template": f"project:{{project_id}}:{asset_type}",
        "retry_policy": {"max_attempts": 2},
        "timeout_policy": {"operation_timeout_seconds": 120},
        "cancellation_policy": {"mode": "cancel_active_attempt"},
        "compensation_policy": {
            "supported": False,
            "reason": "immutable AssetVersion analysis lineage",
        },
        "irreversible_effect_policy": {"allowed": False},
        "external_capabilities": [],
        "policy": {
            "execution_classification": "durable_job",
            "project_scope_required": True,
            "postgresql_authority_required": True,
            "raw_source_in_postgresql_forbidden": True,
            "generation_context_forbidden": True,
            "exact_replay_required": True,
        },
        "completion_contract": {
            "version": f"{name}.completion.v1",
            "required_asset_selectors": [
                {
                    "selector": selector,
                    "output_key": output_key,
                    "role": "evidence",
                    "lifecycle": "ACTIVE",
                    "eligibility": "INELIGIBLE",
                    "governance": "CLEAR",
                }
            ],
            "required_evidence": ["trace", "audit"],
            "required_outbox_events": [event],
        },
    }


__all__ = [
    "SOURCE_AUTHORITY_DEFINITION_VERSION",
    "SOURCE_AUTHORITY_HANDLER_KEY",
    "SOURCE_AUTHORITY_OPERATION",
    "SOURCE_AUTHORITY_OPERATIONS",
    "SOURCE_TRANSFORM_DEFINITION_VERSION",
    "SOURCE_TRANSFORM_HANDLER_KEY",
    "SOURCE_TRANSFORM_OPERATION",
    "SOURCE_OBSERVATION_DEFINITION_VERSION",
    "SOURCE_OBSERVATION_HANDLER_KEY",
    "SOURCE_OBSERVATION_OPERATION",
    "SOURCE_REPROCESSING_DEFINITION_VERSION",
    "SOURCE_REPROCESSING_HANDLER_KEY",
    "SOURCE_REPROCESSING_OPERATION",
    "SOURCE_CONTENT_PROFILE_DEFINITION_VERSION",
    "SOURCE_CONTENT_PROFILE_HANDLER_KEY",
    "SOURCE_CONTENT_PROFILE_OPERATION",
    "SOURCE_ANALYSIS_PLAN_DEFINITION_VERSION",
    "SOURCE_ANALYSIS_PLAN_HANDLER_KEY",
    "SOURCE_ANALYSIS_PLAN_OPERATION",
    "source_authority_definitions",
]

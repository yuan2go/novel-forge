"""MKAOS Operation definitions over the shared PostgreSQL Command Kernel."""
from __future__ import annotations

from typing import Any


MKAOS_CANDIDATE_OPERATION = "mkaos.knowledge_candidate.commit"
MKAOS_CANDIDATE_DEFINITION_VERSION = "1.0.2"
MKAOS_CANDIDATE_HANDLER_KEY = "novel_forge.mkaos_authority.candidate_commit"
MKAOS_APPROVE_OPERATION = "mkaos.knowledge.approve"
MKAOS_APPROVE_DEFINITION_VERSION = "1.0.1"
MKAOS_APPROVE_HANDLER_KEY = "novel_forge.mkaos_authority.knowledge_approve"
MKAOS_PACK_OPERATION = "mkaos.knowledge_pack.build"
MKAOS_PACK_DEFINITION_VERSION = "1.0.1"
MKAOS_PACK_HANDLER_KEY = "novel_forge.mkaos_authority.pack_build"
MKAOS_AUTHORITY_OPERATIONS = frozenset(
    {MKAOS_CANDIDATE_OPERATION, MKAOS_APPROVE_OPERATION, MKAOS_PACK_OPERATION}
)


def mkaos_authority_definitions(
    *, application_build_id: str, commit_sha: str
) -> tuple[dict[str, Any], ...]:
    common = {
        "family": "mkaos_authority",
        "enabled": True,
        "application_build_id": application_build_id,
        "commit_sha": commit_sha,
        "execution_mode": "worker",
        "retry_policy": {"max_attempts": 2},
        "cancellation_policy": {"mode": "cancel_active_attempt"},
        "compensation_policy": {
            "supported": False,
            "reason": "immutable Candidate, Decision and AssetVersion evidence",
        },
        "irreversible_effect_policy": {"allowed": False},
        "external_capabilities": [],
    }
    return (
        {
            **common,
            "name": MKAOS_CANDIDATE_OPERATION,
            "definition_version": MKAOS_CANDIDATE_DEFINITION_VERSION,
            "command_schema": _schema(
                "project_id",
                "workspace_id",
                "execution_asset_version_id",
                "payload",
            ),
            "result_schema": _result_schema(
                "knowledge_candidate_id", "asset_version_id"
            ),
            "handler_key": MKAOS_CANDIDATE_HANDLER_KEY,
            "handler_contract_version": "mkaos-candidate-handler-v1",
            "permissions": ["mkaos.authority.execute"],
            "approval_policy": {
                "required": False,
                "policy_key": "mkaos-candidate-validation-v1",
            },
            "idempotency_scope": "project:mkaos-knowledge-candidate",
            "concurrency_key_template": "project:{project_id}:mkaos-candidate",
            "timeout_policy": {"operation_timeout_seconds": 120},
            "policy": {
                "execution_classification": "durable_job",
                "project_scope_required": True,
                "candidate_only": True,
                "gateway_execution_evidence_required": True,
                "canonical_observation_asset_versions_required": True,
                "direct_source_chunk_mode": "MIGRATION_ONLY",
                "raw_source_expression_forbidden": True,
            },
            "completion_contract": {
                "version": "mkaos.knowledge-candidate.commit.completion.v1",
                "required_asset_selectors": [
                    {
                        "selector": "knowledge_card_candidate",
                        "output_key": "mkaos.knowledge.candidate",
                        "role": "candidate",
                        "lifecycle": "CANDIDATE",
                        "eligibility": "PENDING_EVALUATION",
                        "governance": "CLEAR",
                    }
                ],
                "required_evidence": ["trace", "audit"],
                "required_outbox_events": [
                    "authority.mkaos.knowledge_candidate.committed"
                ],
            },
        },
        {
            **common,
            "name": MKAOS_APPROVE_OPERATION,
            "definition_version": MKAOS_APPROVE_DEFINITION_VERSION,
            "command_schema": _schema(
                "project_id", "workspace_id", "candidate_asset_version_id", "payload"
            ),
            "result_schema": _result_schema(
                "knowledge_card_id",
                "asset_version_id",
                "governance_decision_asset_version_id",
            ),
            "handler_key": MKAOS_APPROVE_HANDLER_KEY,
            "handler_contract_version": "mkaos-approve-handler-v1",
            "permissions": ["mkaos.authority.approve"],
            "approval_policy": {
                "required": False,
                "policy_key": "mkaos-governance-decision-v1",
            },
            "idempotency_scope": "project:mkaos-knowledge-approve",
            "concurrency_key_template": "project:{project_id}:mkaos-approve",
            "timeout_policy": {"operation_timeout_seconds": 60},
            "policy": {
                "execution_classification": "durable_job",
                "project_scope_required": True,
                "candidate_active_isolation": True,
                "authority_decision_required": True,
                "raw_source_expression_forbidden": True,
            },
            "completion_contract": {
                "version": "mkaos.knowledge.approve.completion.v1",
                "required_asset_selectors": [
                    {
                        "selector": "knowledge_governance_decision",
                        "output_key": "mkaos.knowledge.decision",
                        "role": "decision",
                        "lifecycle": "ACTIVE",
                        "eligibility": "ELIGIBLE",
                        "governance": "CLEAR",
                    },
                    {
                        "selector": "knowledge_card",
                        "output_key": "mkaos.knowledge.card",
                        "role": "primary",
                        "lifecycle": "ACTIVE",
                        "eligibility": "ELIGIBLE",
                        "governance": "CLEAR",
                    },
                ],
                "required_evidence": ["trace", "audit"],
                "required_outbox_events": [
                    "authority.mkaos.knowledge.approved"
                ],
            },
        },
        {
            **common,
            "name": MKAOS_PACK_OPERATION,
            "definition_version": MKAOS_PACK_DEFINITION_VERSION,
            "command_schema": _schema(
                "project_id", "workspace_id", "target_asset_version_id", "payload"
            ),
            "result_schema": _result_schema(
                "knowledge_pack_id", "asset_version_id"
            ),
            "handler_key": MKAOS_PACK_HANDLER_KEY,
            "handler_contract_version": "mkaos-pack-handler-v1",
            "permissions": ["mkaos.authority.execute"],
            "approval_policy": {
                "required": False,
                "policy_key": "mkaos-deterministic-pack-v1",
            },
            "idempotency_scope": "project:mkaos-knowledge-pack",
            "concurrency_key_template": "project:{project_id}:mkaos-pack",
            "timeout_policy": {"operation_timeout_seconds": 120},
            "policy": {
                "execution_classification": "durable_job",
                "project_scope_required": True,
                "explicit_asset_versions_only": True,
                "directory_selection_forbidden": True,
                "raw_source_expression_forbidden": True,
                "weights_are_frozen_not_learned": True,
            },
            "completion_contract": {
                "version": "mkaos.knowledge-pack.build.completion.v1",
                "required_asset_selectors": [
                    {
                        "selector": "knowledge_pack",
                        "output_key": "mkaos.knowledge.pack",
                        "role": "primary",
                        "lifecycle": "ACTIVE",
                        "eligibility": "ELIGIBLE",
                        "governance": "CLEAR",
                    }
                ],
                "required_evidence": ["trace", "audit"],
                "required_outbox_events": [
                    "authority.mkaos.knowledge_pack.built"
                ],
            },
        },
    )


def _schema(*required: str) -> dict[str, Any]:
    return {
        "type": "object",
        "required": list(required),
        "properties": {field: {"type": "object" if field == "payload" else "string"} for field in required},
        "additionalProperties": False,
    }


def _result_schema(*required: str) -> dict[str, Any]:
    return {
        "type": "object",
        "required": list(required),
        "properties": {field: {"type": "string"} for field in required},
        "additionalProperties": True,
    }


__all__ = [
    "MKAOS_APPROVE_DEFINITION_VERSION",
    "MKAOS_APPROVE_HANDLER_KEY",
    "MKAOS_APPROVE_OPERATION",
    "MKAOS_AUTHORITY_OPERATIONS",
    "MKAOS_CANDIDATE_DEFINITION_VERSION",
    "MKAOS_CANDIDATE_HANDLER_KEY",
    "MKAOS_CANDIDATE_OPERATION",
    "MKAOS_PACK_DEFINITION_VERSION",
    "MKAOS_PACK_HANDLER_KEY",
    "MKAOS_PACK_OPERATION",
    "mkaos_authority_definitions",
]

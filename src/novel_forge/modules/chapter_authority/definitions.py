"""Versioned OperationDefinitions for the PostgreSQL-only chapter slice."""

from __future__ import annotations

from typing import Any

from novel_forge.modules.chapter_authority.contracts import ChapterNode


CHAPTER_SLICE_DEFINITION_VERSION = "2.0.11"
CHAPTER_MODEL_EFFECT_DEFINITION_VERSION = "2.3.2"
CHAPTER_MODEL_WORKFLOW_DEFINITION_ID = "chapter_authority_slice"
CHAPTER_MODEL_WORKFLOW_DEFINITION_VERSION = CHAPTER_MODEL_EFFECT_DEFINITION_VERSION
CHAPTER_MODEL_WORKFLOW_DEFINITION_REF = (
    f"{CHAPTER_MODEL_WORKFLOW_DEFINITION_ID}@"
    f"{CHAPTER_MODEL_WORKFLOW_DEFINITION_VERSION}"
)
CHAPTER_SLICE_HANDLER_CONTRACT_VERSION = "2.0.9"
CHAPTER_SLICE_ROOT_DEFINITION_NAME = "chapter.slice.run"
CHAPTER_SLICE_ROOT_HANDLER_KEY = "novel_forge.chapter_authority.root"
CHAPTER_MODEL_OPERATION_TIMEOUT_SECONDS = 600
CHAPTER_MODEL_ROOT_TIMEOUT_SECONDS = 3_600
CHAPTER_QUALITY_PROVIDER_NODES = frozenset(
    {
        ChapterNode.QUALITY_STRUCTURAL,
        ChapterNode.QUALITY_COMMERCIAL,
        ChapterNode.QUALITY_SOURCE_ORIGINALITY,
        ChapterNode.QUALITY_LONGFORM,
        ChapterNode.QUALITY_PLATFORM,
    }
)
CHAPTER_QUALITY_GROUP_TIMEOUT_SECONDS = (
    CHAPTER_MODEL_OPERATION_TIMEOUT_SECONDS * len(CHAPTER_QUALITY_PROVIDER_NODES)
)
CHAPTER_LONG_TIMEOUT_POLICY_NODES = frozenset(
    {
        ChapterNode.DRAFT,
        ChapterNode.REVIEW,
        ChapterNode.REVISION,
        ChapterNode.REREVIEW,
        ChapterNode.CANON_EXTRACTION,
        ChapterNode.CANON_PROPOSAL,
        ChapterNode.CANON,
        ChapterNode.QUALITY_STRUCTURAL,
        ChapterNode.QUALITY_COMMERCIAL,
        ChapterNode.QUALITY_SOURCE_ORIGINALITY,
        ChapterNode.QUALITY_LONGFORM,
        ChapterNode.QUALITY_PLATFORM,
        ChapterNode.QUALITY,
    }
)
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
        raise ValueError(
            "application_build_id and a 40-character commit_sha are required"
        )
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
        raise ValueError(
            "application_build_id and a 40-character commit_sha are required"
        )
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
        "timeout_policy": {
            "operation_timeout_seconds": (
                CHAPTER_MODEL_ROOT_TIMEOUT_SECONDS if model_effects_required else 600
            )
        },
        "cancellation_policy": {"mode": "cancel_children"},
        "compensation_policy": {"supported": False, "reason": "append_only_evidence"},
        "irreversible_effect_policy": {"allowed": False},
        "external_capabilities": [],
        **_definition_maturity_metadata(),
        "policy": {
            "execution_classification": "saga",
            "authority": "postgresql",
            "local_storage_writes": "forbidden",
            "orchestration": "dynamic_fenced_saga_v1",
            "expected_saga_steps": len(ChapterNode),
        },
        "completion_contract": {
            "version": "chapter.slice.run.completion.v1",
            "required_child_operations": [
                {
                    "definition_name": node.definition_name,
                    "allowed_states": ["SUCCEEDED"],
                }
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
        ChapterNode.REREVIEW: "model.rereview",
        ChapterNode.CANON_EXTRACTION: "model.canon_extraction",
        ChapterNode.QUALITY_STRUCTURAL: "model.quality_structural",
        ChapterNode.QUALITY_COMMERCIAL: "model.quality_commercial",
        ChapterNode.QUALITY_SOURCE_ORIGINALITY: "model.quality_source_originality",
        ChapterNode.QUALITY_LONGFORM: "model.quality_longform",
        ChapterNode.QUALITY_PLATFORM: "model.quality_platform",
    }.get(node)
    if model_effects_required and model_capability:
        completion["required_external_effects"] = [
            {"capability": model_capability, "allowed_states": ["SUCCEEDED"]}
        ]
        external_capabilities = [model_capability]
    if node is ChapterNode.CANON:
        completion["required_asset_selectors"].append(
            {
                "selector": "deterministic_continuity_report",
                "output_key": "chapter.canon.deterministic_continuity",
                "role": "completion_evidence",
                "lifecycle": "ACTIVE",
                "eligibility": "ELIGIBLE",
                "governance": "CLEAR",
            }
        )
    if node is ChapterNode.QUALITY_COMMERCIAL:
        completion["required_asset_selectors"].extend(
            (
                {
                    "selector": "hook_analysis",
                    "output_key": "chapter.quality.commercial.hook_analysis",
                    "role": "longform_observation",
                    "lifecycle": "ACTIVE",
                    "eligibility": "ELIGIBLE",
                    "governance": "CLEAR",
                },
                {
                    "selector": "pacing_observation",
                    "output_key": "chapter.quality.commercial.pacing_observation",
                    "role": "longform_observation",
                    "lifecycle": "ACTIVE",
                    "eligibility": "ELIGIBLE",
                    "governance": "CLEAR",
                },
            )
        )
    if node is ChapterNode.PLAN:
        completion["required_asset_selectors"].extend(
            (
                {
                    "selector": "production_input_manifest",
                    "output_key": "chapter.production_input_manifest",
                    "role": "production_input_manifest",
                    "lifecycle": "ACTIVE",
                    "eligibility": "ELIGIBLE",
                    "governance": "CLEAR",
                },
                {
                    "selector": "chapter_plan_qualification_report",
                    "output_key": "chapter.plan.qualification",
                    "role": "completion_evidence",
                    "lifecycle": "ACTIVE",
                    "eligibility": "ELIGIBLE",
                    "governance": "CLEAR",
                },
            )
        )
    if node is ChapterNode.CONTEXT:
        completion["required_asset_selectors"].append(
            {
                "selector": "context_manifest_consistency_report",
                "output_key": "chapter.context.manifest_consistency",
                "role": "completion_evidence",
                "lifecycle": "ACTIVE",
                "eligibility": "ELIGIBLE",
                "governance": "CLEAR",
            }
        )
    if node is ChapterNode.QUALITY:
        from novel_forge.modules.chapter_quality_authority import QUALITY_DIMENSIONS

        completion["required_asset_selectors"].extend(
            {
                "selector": "chapter_quality_evidence",
                "output_key": f"chapter.quality.evidence.{dimension}",
                "role": "quality_evidence",
                "lifecycle": "ACTIVE",
                "eligibility": "ELIGIBLE",
                "governance": "CLEAR",
            }
            for dimension in QUALITY_DIMENSIONS
        )
        completion["required_asset_selectors"].append(
            {
                "selector": "narrative_runtime_measurement",
                "output_key": "chapter.quality.narrative_runtime_measurement",
                "role": "proof_observation",
                "lifecycle": "ACTIVE",
                "eligibility": "ELIGIBLE",
                "governance": "CLEAR",
            }
        )
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
            CHAPTER_MODEL_EFFECT_DEFINITION_VERSION
            if model_effects_required
            else CHAPTER_SLICE_HANDLER_CONTRACT_VERSION
        ),
        "application_build_id": application_build_id,
        "commit_sha": commit_sha,
        "execution_mode": "worker",
        "permissions": ["chapter.authority.execute"],
        "approval_policy": {"required": False},
        "idempotency_scope": "project:chapter-slice",
        "concurrency_key_template": "project:{project_id}:chapter-slice",
        "retry_policy": {"max_attempts": 2},
        "timeout_policy": {
            "operation_timeout_seconds": (
                CHAPTER_QUALITY_GROUP_TIMEOUT_SECONDS
                if model_effects_required and node in CHAPTER_QUALITY_PROVIDER_NODES
                else (
                    CHAPTER_MODEL_OPERATION_TIMEOUT_SECONDS
                    if model_effects_required
                    and node in CHAPTER_LONG_TIMEOUT_POLICY_NODES
                    else 60
                )
            )
        },
        "cancellation_policy": {"mode": "cancel_active_attempt"},
        "compensation_policy": {"supported": False, "reason": "append_only_evidence"},
        "irreversible_effect_policy": {"allowed": False},
        "external_capabilities": external_capabilities,
        **_definition_maturity_metadata(),
        "policy": {
            "execution_classification": "durable_job",
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
        "required": [
            "chapter",
            "chapter_plan_asset_version_id",
            "chapter_plan_content_hash",
        ],
        "properties": {
            "chapter": {"type": "integer"},
            "premise": {"type": "string"},
            "title": {"type": "string"},
            "chapter_plan_asset_version_id": {"type": "string", "minLength": 1},
            "chapter_plan_content_hash": {"type": "string", "minLength": 1},
            "context_candidates": {
                "type": "array",
                "items": {"type": "object"},
            },
            "context_version_refs": {"type": "object"},
            "context_token_budget": {"type": "integer"},
            "preparation_report": {"type": "object"},
            "chapter_idempotency_key": {"type": "string"},
            "canon_reextraction_generation": {"type": "integer", "minimum": 1},
            "supersedes_proposal_asset_version_id": {"type": "string"},
        },
        "additionalProperties": False,
    }

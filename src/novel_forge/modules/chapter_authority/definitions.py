from __future__ import annotations
from typing import Any
from novel_forge.modules.chapter_authority.contracts import ChapterNode
from novel_forge.modules.command_kernel.routing_bootstrap import (
    CHAPTER_BOOTSTRAP_TASKS,
    CHAPTER_REFERENCE_SAMPLE_SOURCES,
    CHAPTER_REFERENCE_SAMPLE_VERSION,
    CHAPTER_SAMPLE_DEFINITION_VERSION,
    CHAPTER_SAMPLE_IDEMPOTENCY_SCOPE,
    CHAPTER_SAMPLE_SOURCE_VERSION,
    chapter_sample_definition_name,
)

CHAPTER_SLICE_DEFINITION_VERSION = "2.2.1"
CHAPTER_MODEL_EFFECT_DEFINITION_VERSION = "3.9.0"
CHAPTER_DRAFT_DEFINITION_VERSION = "3.9.2"
CHAPTER_REVIEW_DEFINITION_VERSION = "3.9.3"
CHAPTER_REVISION_DEFINITION_VERSION = "3.9.4"
CHAPTER_CANON_REDUCTION_DEFINITION_VERSION = "3.9.10"
CHAPTER_CANON_DEFINITION_VERSION = "3.9.7"
CHAPTER_SUPPORT_DEFINITION_VERSION = "3.9.8"
CHAPTER_QUALITY_DEFINITION_VERSION = "3.9.9"
CHAPTER_INTERNAL_QUALITY_DEFINITION_VERSION = "3.9.11"
CHAPTER_LONGFORM_QUALITY_DEFINITION_VERSION = "3.9.12"
CHAPTER_INTERNAL_PUBLISH_DEFINITION_VERSION = "3.9.13"
CHAPTER_INTERNAL_EXPORT_DEFINITION_VERSION = "3.9.14"
CHAPTER_INTERNAL_FINALIZE_DEFINITION_VERSION = "3.9.15"
CHAPTER_RECOVERABLE_MODEL_DEFINITION_VERSIONS = frozenset({"3.4.1", "3.5.0", "3.6.0", "3.7.0", "3.8.0"})
CHAPTER_RECOVERABLE_MODEL_DEFINITION_VERSION = "3.4.1"
CHAPTER_AUTHOR_INPUT_DEFINITION_VERSION = "3.9.0-author-input.v2"
CHAPTER_LEGACY_AUTHOR_INPUT_DEFINITION_VERSION = "3.4.1-author-input.v1"
CHAPTER_MODEL_WORKFLOW_DEFINITION_ID = "chapter_authority_slice"
CHAPTER_MODEL_WORKFLOW_DEFINITION_VERSION = CHAPTER_MODEL_EFFECT_DEFINITION_VERSION
CHAPTER_MODEL_WORKFLOW_DEFINITION_REF = (
    f"{CHAPTER_MODEL_WORKFLOW_DEFINITION_ID}@"
    f"{CHAPTER_MODEL_WORKFLOW_DEFINITION_VERSION}"
)
CHAPTER_SLICE_HANDLER_CONTRACT_VERSION = "2.1.1"
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
CHAPTER_QUALITY_GROUP_TIMEOUT_SECONDS = CHAPTER_MODEL_OPERATION_TIMEOUT_SECONDS * len(
    CHAPTER_QUALITY_PROVIDER_NODES
)
CHAPTER_LONG_TIMEOUT_POLICY_NODES = frozenset(
    {
        ChapterNode.CONTEXT,
        ChapterNode.MEMO,
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

CHAPTER_SAMPLE_OUTPUT_KEY = "chapter.provider.sample"
CHAPTER_SAMPLE_COMPLETION_TOPIC = "chapter.provider.sample.materialized"
CHAPTER_SAMPLE_WORKFLOW_ID = "chapter_provider_sampling"
CHAPTER_SAMPLE_WORKFLOW_REF = f"{CHAPTER_SAMPLE_WORKFLOW_ID}@{CHAPTER_SAMPLE_DEFINITION_VERSION}"
CHAPTER_REFERENCE_WORKFLOW_ID = "chapter_reference_sampling"
CHAPTER_REFERENCE_WORKFLOW_REF = f"{CHAPTER_REFERENCE_WORKFLOW_ID}@{CHAPTER_SAMPLE_DEFINITION_VERSION}"


def chapter_provider_sample_definitions(
    *, application_build_id: str, commit_sha: str, reference_samples: bool = False,
    definition_version: str | None = None,
) -> tuple[dict[str, Any], ...]:
    if not application_build_id or len(commit_sha) != 40:
        raise ValueError("Chapter sampling requires an exact implementation identity")
    command_schema = {
        "type": "object",
        "required": ["project_id", "input_asset_version_ids", "payload"],
        "properties": {
            "project_id": {"type": "string", "minLength": 1},
            "input_asset_version_ids": {"type": "array", "minItems": 1, "items": {"type": "string"}},
            "payload": {"type": "object"},
        },
        "additionalProperties": False,
    }
    selected_version = definition_version or (CHAPTER_REFERENCE_SAMPLE_VERSION if reference_samples else CHAPTER_SAMPLE_DEFINITION_VERSION)
    historical = selected_version in {"1.0.0", "1.1.0", "2.0.0", "2.1.0", "2.2.0", "2.3.0"}
    source_versions = (
        ["3.4.1", "3.5.0"] if selected_version in {"2.0.0", "2.1.0"}
        else ["3.4.1", "3.8.0", "3.8.0-author-input.v2"] if historical
        else sorted({CHAPTER_SAMPLE_SOURCE_VERSION, "3.8.0", "3.8.0-author-input.v2", CHAPTER_MODEL_EFFECT_DEFINITION_VERSION, CHAPTER_AUTHOR_INPUT_DEFINITION_VERSION})
    )
    formal = {item["name"]: item for item in chapter_operation_definitions(
        application_build_id=application_build_id, commit_sha=commit_sha, model_effects_required=True,
    )}
    definitions = []
    for node in ChapterNode:
        stage = CHAPTER_BOOTSTRAP_TASKS.get(node.definition_name)
        if stage is None:
            continue
        if reference_samples and stage not in CHAPTER_REFERENCE_SAMPLE_SOURCES:
            continue
        name = chapter_sample_definition_name(stage)
        definitions.append({
            "name": name,
            "definition_version": selected_version,
            "family": "chapter_authority",
            "enabled": True,
            "command_schema": command_schema,
            "result_schema": {"type": "object"},
            "input_contract": command_schema,
            "output_contract": {"asset_type": "chapter_provider_sample", "output_key": CHAPTER_SAMPLE_OUTPUT_KEY},
            "handler_key": "novel_forge.chapter_authority.sample." + stage,
            "handler_contract_version": "chapter-provider-sample.v1",
            "application_build_id": application_build_id,
            "commit_sha": commit_sha,
            "execution_mode": "worker",
            "permissions": ["chapter.authority.execute"],
            "approval_policy": {"required": False},
            "idempotency_scope": CHAPTER_SAMPLE_IDEMPOTENCY_SCOPE,
            "concurrency_key_template": "book:{book_id}:chapter-sample:{logical_key}",
            "retry_policy": {"max_attempts": 1, "dead_letter_on_exhausted": True},
            "timeout_policy": {"operation_timeout_seconds": 60} if historical and node is ChapterNode.MEMO else dict(formal[node.definition_name]["timeout_policy"]),
            "cancellation_policy": {"mode": "cancel_active_attempt"},
            "compensation_policy": {"supported": False, "reason": "append_only_sample_evidence"},
            "irreversible_effect_policy": {"allowed": False},
            "external_capabilities": ["model." + stage],
            "definition_status": "implemented",
            "migration_owner": "chapter-authority",
            "projection_consumers": ["operation_timeline", "provider_routing_campaign"],
            "policy": {
                "source_definition_name": node.definition_name,
                "source_definition_versions": source_versions,
                "routing_bootstrap_sample": True,
                "production_eligible": False,
                **({"chapter_reference_sample_input_allowed": True} if reference_samples else {}),
            },
            "completion_contract": {
                "version": name + ".completion.v1",
                "required_asset_selectors": [{
                    "selector": "chapter_provider_sample", "output_key": CHAPTER_SAMPLE_OUTPUT_KEY,
                    "role": "primary", "lifecycle": "ACTIVE", "eligibility": "INELIGIBLE", "governance": "CLEAR",
                }],
                "required_external_effects": [{"capability": "model." + stage, "allowed_states": ["SUCCEEDED"]}],
                "required_evidence": ["trace", "audit"],
                "required_audit_actions": [CHAPTER_SAMPLE_COMPLETION_TOPIC],
                "required_outbox_events": [CHAPTER_SAMPLE_COMPLETION_TOPIC],
            },
        })
    return tuple(definitions)


def chapter_operation_definitions(
    *,
    application_build_id: str,
    commit_sha: str,
    model_effects_required: bool = False,
    semantic_retrieval_available: bool = False,
    author_input: bool = False,
) -> tuple[dict[str, Any], ...]:
    if not application_build_id or len(commit_sha) != 40:
        raise ValueError(
            "application_build_id and a 40-character commit_sha are required"
        )
    definitions = tuple(
        _definition(
            node,
            application_build_id=application_build_id,
            commit_sha=commit_sha,
            model_effects_required=model_effects_required,
            semantic_retrieval_available=semantic_retrieval_available,
        )
        for node in ChapterNode
    )
    if not author_input:
        return definitions
    from copy import deepcopy
    author = deepcopy(next(item for item in definitions if item["name"] == ChapterNode.DRAFT.definition_name))
    author["policy"].pop("scene_core_projection", None)
    author["policy"].pop("scene_information_flow", None)
    author["definition_version"] = CHAPTER_AUTHOR_INPUT_DEFINITION_VERSION
    author["external_capabilities"] = []
    completion = author["completion_contract"]
    completion.pop("required_external_effects", None)
    completion["version"] = "chapter.draft.author-input.completion.v1"
    completion["required_asset_selectors"].append({
        "selector": "author_draft_adoption_evidence", "output_key": "chapter.draft.author_adoption",
        "role": "completion_evidence", "lifecycle": "ACTIVE", "eligibility": "ELIGIBLE", "governance": "CLEAR",
    })
    return (*definitions, author)


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
    semantic_retrieval_available: bool,
) -> dict[str, Any]:
    # WHY: Provider availability is runtime policy, not OperationDefinition
    # identity.  In particular Retrieval may use its declared model capability
    # when semantic projection is ready, or complete under an explicitly
    # frozen FTS/graph/temporal fallback policy without a model effect.
    del semantic_retrieval_available
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
        ChapterNode.MEMO: "model.memo",
        ChapterNode.RETRIEVAL: "model.retrieval",
        ChapterNode.DRAFT: "model.draft",
        ChapterNode.REVIEW: "model.review",
        ChapterNode.REVISION: "model.revision",
        ChapterNode.REREVIEW: "model.rereview",
        ChapterNode.CANON_EXTRACTION: "model.canon_extraction",
        ChapterNode.CANON_PROPOSAL: "model.canon_support",
        ChapterNode.QUALITY_STRUCTURAL: "model.quality_structural",
        ChapterNode.QUALITY_COMMERCIAL: "model.quality_commercial",
        ChapterNode.QUALITY_SOURCE_ORIGINALITY: "model.quality_source_originality",
        ChapterNode.QUALITY_LONGFORM: "model.quality_longform",
        ChapterNode.QUALITY_PLATFORM: "model.quality_platform",
    }.get(node)
    if model_effects_required and model_capability:
        external_capabilities = [model_capability]
        if node is ChapterNode.RETRIEVAL:
            external_capabilities.append("model.retrieval_query_expansion")
        if node is not ChapterNode.RETRIEVAL:
            completion["required_external_effects"] = [
                {"capability": model_capability, "allowed_states": ["SUCCEEDED"]}
            ]
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
        if model_effects_required:
            external_capabilities = ["model.context_compress", "model.context_fidelity"]
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
    if node is ChapterNode.RETRIEVAL:
        completion["required_asset_selectors"].append(
            {
                "selector": "retrieval_result",
                "output_key": "chapter.retrieval",
                "role": "primary",
                "lifecycle": "ACTIVE",
                "eligibility": "ELIGIBLE",
                "governance": "CLEAR",
            }
        )
    if node is ChapterNode.BEST_CANDIDATE:
        completion["required_asset_selectors"].extend(
            (
                {
                    "selector": "re_review_report",
                    "output_key": "chapter.best_candidate.selected_review",
                    "role": "selection_evidence",
                    "lifecycle": "ACTIVE",
                    "eligibility": "ELIGIBLE",
                    "governance": "CLEAR",
                },
                {
                    "selector": "candidate_comparison",
                    "output_key": "chapter.best_candidate.comparison",
                    "role": "selection_evidence",
                    "lifecycle": "ACTIVE",
                    "eligibility": "ELIGIBLE",
                    "governance": "CLEAR",
                },
                {
                    "selector": "best_candidate_snapshot",
                    "output_key": "chapter.best_candidate.snapshot",
                    "role": "selection_evidence",
                    "lifecycle": "ACTIVE",
                    "eligibility": "ELIGIBLE",
                    "governance": "CLEAR",
                },
            )
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
        "definition_version": CHAPTER_INTERNAL_EXPORT_DEFINITION_VERSION if model_effects_required and node is ChapterNode.EXPORT and CHAPTER_MODEL_EFFECT_DEFINITION_VERSION == "3.9.0" else CHAPTER_INTERNAL_FINALIZE_DEFINITION_VERSION if model_effects_required and node is ChapterNode.FINAL_RELEASE_GATE and CHAPTER_MODEL_EFFECT_DEFINITION_VERSION == "3.9.0" else CHAPTER_INTERNAL_QUALITY_DEFINITION_VERSION if model_effects_required and node is ChapterNode.QUALITY and CHAPTER_MODEL_EFFECT_DEFINITION_VERSION == "3.9.0" else CHAPTER_LONGFORM_QUALITY_DEFINITION_VERSION if model_effects_required and node is ChapterNode.QUALITY_LONGFORM and CHAPTER_MODEL_EFFECT_DEFINITION_VERSION == "3.9.0" else CHAPTER_INTERNAL_PUBLISH_DEFINITION_VERSION if model_effects_required and node is ChapterNode.PUBLISH_GATE and CHAPTER_MODEL_EFFECT_DEFINITION_VERSION == "3.9.0" else CHAPTER_CANON_REDUCTION_DEFINITION_VERSION if model_effects_required and node is ChapterNode.CANON and CHAPTER_MODEL_EFFECT_DEFINITION_VERSION == "3.9.0" else CHAPTER_DRAFT_DEFINITION_VERSION if model_effects_required and node is ChapterNode.DRAFT and CHAPTER_MODEL_EFFECT_DEFINITION_VERSION == "3.9.0" else CHAPTER_REVIEW_DEFINITION_VERSION if model_effects_required and node in {ChapterNode.REVIEW, ChapterNode.REREVIEW} and CHAPTER_MODEL_EFFECT_DEFINITION_VERSION == "3.9.0" else CHAPTER_REVISION_DEFINITION_VERSION if model_effects_required and node is ChapterNode.REVISION and CHAPTER_MODEL_EFFECT_DEFINITION_VERSION == "3.9.0" else CHAPTER_CANON_DEFINITION_VERSION if model_effects_required and node is ChapterNode.CANON_EXTRACTION and CHAPTER_MODEL_EFFECT_DEFINITION_VERSION == "3.9.0" else CHAPTER_QUALITY_DEFINITION_VERSION if model_effects_required and node in {ChapterNode.QUALITY_STRUCTURAL, ChapterNode.QUALITY_COMMERCIAL, ChapterNode.QUALITY_SOURCE_ORIGINALITY, ChapterNode.QUALITY_LONGFORM, ChapterNode.QUALITY_PLATFORM} and CHAPTER_MODEL_EFFECT_DEFINITION_VERSION == "3.9.0" else CHAPTER_SUPPORT_DEFINITION_VERSION if model_effects_required and node is ChapterNode.CANON_PROPOSAL and CHAPTER_MODEL_EFFECT_DEFINITION_VERSION == "3.9.0" else chapter_definition_version(model_effects_required),
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
            **({"internal_quality_disposition":"creative-quality-disposition.v2"} if model_effects_required and node is ChapterNode.QUALITY and CHAPTER_MODEL_EFFECT_DEFINITION_VERSION == "3.9.0" else {}),
            **({"quality_foundation_contract":"quality-frozen-world-foundation.v1"} if model_effects_required and node is ChapterNode.QUALITY_LONGFORM and CHAPTER_MODEL_EFFECT_DEFINITION_VERSION == "3.9.0" else {}),
            **({"internal_quality_input_contract":"creative-quality-admission.v2"} if model_effects_required and node in {ChapterNode.PUBLISH_GATE,ChapterNode.EXPORT,ChapterNode.FINAL_RELEASE_GATE} and CHAPTER_MODEL_EFFECT_DEFINITION_VERSION == "3.9.0" else {}),
            **({"canon_validation_contract":"grounded-canon-validation.v2"} if model_effects_required and node is ChapterNode.CANON and CHAPTER_MODEL_EFFECT_DEFINITION_VERSION=="3.9.0" else {}),
            **({"quality_applicability_contract":"quality-host-applicability.v1"} if model_effects_required and node in {ChapterNode.QUALITY_STRUCTURAL,ChapterNode.QUALITY_COMMERCIAL,ChapterNode.QUALITY_SOURCE_ORIGINALITY,ChapterNode.QUALITY_LONGFORM,ChapterNode.QUALITY_PLATFORM} and CHAPTER_MODEL_EFFECT_DEFINITION_VERSION=="3.9.0" and CHAPTER_QUALITY_DEFINITION_VERSION=="3.9.9" else {}),
            **({"support_kind_contract": "canon-support-kinds.v2"} if model_effects_required and node is ChapterNode.CANON_PROPOSAL and CHAPTER_MODEL_EFFECT_DEFINITION_VERSION == "3.9.0" and CHAPTER_SUPPORT_DEFINITION_VERSION == "3.9.8" else {}),
            **({"canon_wire_projection": "codex-canonical-json.v1"} if model_effects_required and node is ChapterNode.CANON_EXTRACTION and CHAPTER_MODEL_EFFECT_DEFINITION_VERSION == "3.9.0" and CHAPTER_CANON_DEFINITION_VERSION == "3.9.7" else {}),
            **({"canon_wire_projection": "codex-structured-schema.v4"} if model_effects_required and node is ChapterNode.CANON_EXTRACTION and CHAPTER_MODEL_EFFECT_DEFINITION_VERSION == "3.9.0" and CHAPTER_CANON_DEFINITION_VERSION == "3.9.6" else {}),
            **({"canon_schema_projection": "canon-provider-shared-types.v1"} if model_effects_required and node is ChapterNode.CANON_EXTRACTION and CHAPTER_MODEL_EFFECT_DEFINITION_VERSION == "3.9.0" and CHAPTER_CANON_DEFINITION_VERSION in {"3.9.5", "3.9.6", "3.9.7"} else {}),
            **({"chapter_length_scope": "chapter-length-repair.v1"} if model_effects_required and node is ChapterNode.REVISION and CHAPTER_MODEL_EFFECT_DEFINITION_VERSION == "3.9.0" and CHAPTER_REVISION_DEFINITION_VERSION == "3.9.4" else {}),
            **({"review_knowledge_scope": "delivered-card-scope.v1"} if model_effects_required and node in {ChapterNode.REVIEW, ChapterNode.REREVIEW} and CHAPTER_MODEL_EFFECT_DEFINITION_VERSION == "3.9.0" and CHAPTER_REVIEW_DEFINITION_VERSION == "3.9.3" else {}),
            **({"scene_information_flow": "scene-information-flow.v1"} if model_effects_required and node is ChapterNode.DRAFT and CHAPTER_MODEL_EFFECT_DEFINITION_VERSION == "3.9.0" and CHAPTER_DRAFT_DEFINITION_VERSION == "3.9.2" else {}),
            **({"scene_core_projection": "scene-core-slots.v1"} if model_effects_required and node is ChapterNode.DRAFT and CHAPTER_MODEL_EFFECT_DEFINITION_VERSION == "3.9.0" and CHAPTER_DRAFT_DEFINITION_VERSION in {"3.9.1", "3.9.2"} else {}),
        },
        "completion_contract": completion,
    }


def _definition_maturity_metadata() -> dict[str, Any]:
    """INVARIANT: runtime bindings cannot promote their own qualification evidence."""

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
            "book_id": {"type": "string"},
            "premise": {"type": "string"},
            "title": {"type": "string"},
            "chapter_plan_asset_version_id": {"type": "string", "minLength": 1},
            "chapter_plan_content_hash": {"type": "string", "minLength": 1},
            "context_candidates": {
                "type": "array",
                "items": {"type": "object"},
            },
            "context_version_refs": {"type": "object"},
            "retrieval_snapshot": {"type": "object"},
            "context_token_budget": {"type": "integer"},
            "preparation_report": {"type": "object"},
            "chapter_idempotency_key": {"type": "string"},
            "chapter_root_operation_id": {"type": "string"},
            "correction_generation": {"type": "integer", "minimum": 0},
            "canon_reextraction_generation": {"type": "integer", "minimum": 1},
            "supersedes_proposal_asset_version_id": {"type": "string"},
        },
        "additionalProperties": False,
    }

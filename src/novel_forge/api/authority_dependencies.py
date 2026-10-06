from __future__ import annotations

from novel_forge.modules.book_design_authority.formation_generation import (
    FormationGeneration,
)
from novel_forge.modules.story_planning_runtime.foundation_generation import (
    FOUNDATION_GENERATORS,
)

import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

from novel_forge.infrastructure.environment import RuntimeEnvironment
from novel_forge.infrastructure.production_execution_composition import (
    ProductionExecutionComposition,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.command_kernel.routing_bootstrap import WORLD_SAMPLE_TASKS
from novel_forge.modules.chapter_authority.application import (
    ChapterAuthorityApplication,
)
from novel_forge.modules.chapter_authority.execution_gateway import (
    ChapterExecutionGatewaySession,
    ChapterExecutionRoute,
    PostgresChapterExecutionContractBinder,
    PostgresProductionExecutionPayloadResolver,
    PostgresRetrievalProjectionExecutionContractBinder,
    ProductionExecutionGatewayExternalEffectAdapter,
    chapter_stage_capability,
    default_chapter_fixture_response,
)
from novel_forge.modules.chapter_authority.model_effects import (
    ExternalEffectChapterModelPort,
    normalize_model_output,
)
from novel_forge.modules.chapter_authority.provider_output_contracts import (
    validate_chapter_provider_output_against_schema,
    validate_chapter_provider_output_semantics,
)
from novel_forge.modules.capability_packs.artifacts import (
    ArtifactKind,
    default_chapter_artifact_resolver,
)
from novel_forge.modules.capability_packs import (
    CapabilityPackCompiler,
    PackCatalogEntry,
    ReadOnlyPackCatalog,
    chapter_operation_definition_catalog,
    chapter_workflow_binding_catalog,
    default_capability_type_catalog,
    default_tool_definition_catalog,
    load_capability_pack,
)
from novel_forge.modules.chapter_authority.queries import ChapterAuthorityQuery
from novel_forge.modules.book_authority.production import (
    ChapterAuthorityCommandAdapter,
    PostgresBookAuthority,
)
from novel_forge.modules.book_authority.composition import BookProductionComposition
from novel_forge.modules.book_authority.input_resolver import (
    BookProductionInputResolver,
)
from novel_forge.modules.book_authority.supervisor import (
    PostgresBookProductionSupervisor,
)
from novel_forge.modules.book_authority.queries import PostgresBookProductionQuery
from novel_forge.modules.book_authority.projection_repair import (
    PostgresBookProjectionRepairAuthority,
)
from novel_forge.modules.book_authority.opening import PostgresBookOpeningApplication
from novel_forge.modules.corrective_action import CorrectiveActionQuery
from novel_forge.modules.book_replan import BookReplanCoordinator
from novel_forge.modules.chapter_group_authority import PostgresChapterGroupAuthority
from novel_forge.modules.plan_change_authority import PostgresPlanChangeAuthority
from novel_forge.modules.book_design_authority import (
    BookDesignAuthorityApplication,
    BookDesignAuthorityQuery,
)
from novel_forge.modules.book_followup_authority.application import (
    BookFollowupAuthorityApplication,
)
from novel_forge.modules.book_followup_authority.execution import (
    PostgresReaderOutcomeExecutionContractBinder,
)
from novel_forge.modules.story_planning_runtime import (
    CapabilityPackBackedPlanningExecutionBinder,
    PlanningExecutionRoute,
    PostgresPlanningExecutionBundleResolver,
    PostgresPlanningExecutionPreparer,
    PostgresNarrativeSearchApplication,
    STORY_PLANNING_WORKFLOW_DEFINITION_REF,
    StoryPlanningGenerationApplication,
)
from novel_forge.modules.story_planning_runtime.execution import (
    planning_fixture_response,
)
from novel_forge.modules.story_design_authority.evaluation_execution import (
    GatewayNarrativeSemanticEvaluationExecutionPort,
    PostgresNarrativeEvaluationExecutionContractBinder,
)
from novel_forge.modules.source_import.execution_contracts import (
    CLASSIFICATION_STAGE,
    DECONSTRUCTION_STAGE,
    MKAOS_STAGE,
    content_intelligence_fixture_response,
    validate_content_intelligence_output,
)
from novel_forge.modules.source_import.object_reader import (
    LocalObjectStoreReader,
    MinioObjectStoreReader,
)
from novel_forge.modules.source_import import (
    GitRepositoryExternalEffectAdapter,
    PostgresContentIntelligenceExecutionPort,
    SourceImportApplication,
)
from novel_forge.modules.agent_runtime.application import (
    AgentRuntimeAuthorityApplication,
)
from novel_forge.modules.agent_runtime.execution import (
    ChapterGatewayAgentExecutionPreparer,
)
from novel_forge.modules.agent_runtime.harness_runtime import (
    build_scripted_agent_harness_factory,
)
from novel_forge.modules.agent_runtime.production import (
    PostgresAgentExecutionContractBinder,
    agent_route_execution_identity,
    build_production_agent_harness_factory,
)
from novel_forge.modules.agent_runtime.queries import AgentRuntimeQuery
from novel_forge.modules.agent_runtime.scheduler import AgentAuthorityScheduler
from novel_forge.modules.capability_pack_authority.application import (
    CapabilityPackAuthorityApplication,
)
from novel_forge.modules.capability_pack_authority.query import (
    CapabilityPackAuthorityQuery,
)
from novel_forge.modules.chapter_quality_authority.qualification_application import (
    PostgresQualityQualificationAuthority,
)
from novel_forge.modules.authority_security import Principal, TrustedPrincipalResolver
from novel_forge.modules.command_kernel.external_effect_adapters import (
    LocalFileObjectStoreAdapter,
    MinioObjectStoreExternalEffectAdapter,
)
from novel_forge.modules.production_preparation import (
    PostgresProductionAssetResolver,
    ProductionPreparationService,
)
from novel_forge.modules.content_authority import (
    CONTENT_INTEGRATION_PROVEN,
    ContentAuthorityApplication,
    ContentAuthorityQuery,
)
from novel_forge.modules.provider_control import (
    ProviderAdapterRegistry,
    build_provider_adapter_registry,
    configured_chapter_provider_ids,
    configured_router_provider_ids,
    normalize_provider_id,
)
from novel_forge.modules.provider_control.contracts import ProviderControlLevel
from novel_forge.modules.provider_callback_authority import ProviderCallbackAuthorityService
from novel_forge.modules.production_execution import (
    CapabilityId,
    AdmissionController,
    AuthorityExecutionRecoveryStore,
    CodexAccountEntitlementSnapshot,
    CodexCliExecutionBackend,
    CodexPricingSnapshot,
    CodexProcessSupervisor,
    CompletionMode,
    ExecutionBackendRegistry,
    ExecutionCapabilityProfile,
    ExecutionRuntimeClass,
    FallbackPolicy,
    ModelProfile,
    ModelProfileStatus,
    LocalProcessExecutionPolicy,
    PersistentExecutionDirectory,
    PostgresAttemptFenceVerifier,
    PostgresExecutionContractSource,
    ProductionExecutionGateway,
    RemoteProviderExecutionBackend,
    RoutePolicy,
    ScriptedFixtureExecutionBackend,
    default_capability_registry,
    observe_codex_cli_version,
)


_PACK_SKILL_FOR_STAGE = {
    "draft": "prose-generation",
    "revision": "prose-generation",
    "canon_extraction": "canon-continuity-graph",
    "canon_support": "canon-continuity-graph",
    "memo": "chapter-outline",
    "review": "quality-review",
    "rereview": "quality-review",
    "quality_structural": "quality-review",
    "quality_commercial": "quality-review",
    "quality_source_originality": "quality-review",
    "quality_longform": "quality-review",
    "quality_platform": "quality-review",
    "reader_outcome": "quality-review",
    "longform_prose_review": "quality-review",
    "screenplay_generate": "prose-generation",
    "screenplay_review": "quality-review",
    "screenplay_revision": "prose-generation",
    "narrative_semantic_evaluation": "quality-review",
    "model_reference_evaluate": "quality-review",
    "model_reference_adjudicate": "quality-review",
    "agent_session": "agent-loop-governance",
    "retrieval": "context-builder-source-isolation",
    "retrieval_query_expansion": "context-builder-source-isolation",
    "context_compress": "context-builder-source-isolation",
    "context_fidelity": "context-builder-source-isolation",
}


def _execution_content_hash(
    values: Mapping[str, str],
    *,
    stage: str,
    specific_key: str,
    common_key: str,
    controlled: bool,
    fixture_identity: str,
) -> str:
    configured = str(values.get(specific_key) or values.get(common_key) or "").strip()
    if not configured:
        if controlled:
            raise RuntimeError(
                f"{specific_key} or {common_key} is required in a controlled environment"
            )
        configured = (
            "sha256:"
            + hashlib.sha256(
                f"fixture-protocol:{stage}:{fixture_identity}".encode("utf-8")
            ).hexdigest()
        )
    normalized = configured.removeprefix("sha256:")
    if len(normalized) != 64 or any(
        character not in "0123456789abcdefABCDEF" for character in normalized
    ):
        raise RuntimeError(f"{specific_key} must be a SHA-256 content hash")
    return "sha256:" + normalized.lower()


def authority_release_identity(
    *, env: Mapping[str, str] | None = None
) -> tuple[str, str]:
    values = os.environ if env is None else env
    build_id = str(values.get("NOVEL_FORGE_APPLICATION_BUILD_ID") or "").strip()
    commit_sha = str(values.get("NOVEL_FORGE_COMMIT_SHA") or "").strip().lower()
    if not build_id:
        raise RuntimeError("NOVEL_FORGE_APPLICATION_BUILD_ID is required")
    if len(commit_sha) != 40 or any(
        character not in "0123456789abcdef" for character in commit_sha
    ):
        raise RuntimeError(
            "NOVEL_FORGE_COMMIT_SHA must be a full 40-character hexadecimal commit id"
        )
    return build_id, commit_sha


def _scripted_narrative_evaluation_fixture_enabled(
    runtime_environment: RuntimeEnvironment,
    values: Mapping[str, str],
) -> bool:
    """SECURITY: Require an explicit test-only switch for scripted semantic receipts.

    ``development`` may use other deterministic fixtures, but a Narrative
    Qualification can admit canonical production input.  It therefore needs a
    narrower boundary than the general runtime fixture flag.
    """
    explicit = (
        str(
            values.get("NOVEL_FORGE_TEST_ALLOW_SCRIPTED_NARRATIVE_EVALUATION_FIXTURE")
            or ""
        )
        .strip()
        .lower()
    )
    return runtime_environment is RuntimeEnvironment.TEST and explicit in {
        "1",
        "true",
        "yes",
    }


def build_book_design_authority_application(
    settings: IndustrialSettings,
    *,
    execution: ProductionExecutionComposition,
    env: Mapping[str, str] | None = None,
) -> BookDesignAuthorityApplication:
    if settings.storage_authority != "postgresql" or not settings.database_url:
        raise RuntimeError("BookDesign Authority requires PostgreSQL authority")
    values = os.environ if env is None else env
    build_id, commit_sha = authority_release_identity(env=values)
    runtime_environment = RuntimeEnvironment.parse(
        str(values.get("NOVEL_FORGE_ENVIRONMENT") or settings.environment)
    )
    return BookDesignAuthorityApplication(
        settings.database_url,
        application_build_id=build_id,
        commit_sha=commit_sha,
        semantic_evaluation_execution_port=(
            build_narrative_semantic_evaluation_execution_port(
                settings,
                execution=execution,
                env=values,
            )
        ),
        allow_scripted_evaluation_fixture=(
            _scripted_narrative_evaluation_fixture_enabled(runtime_environment, values)
        ),
        narrative_evaluator_principal=(
            build_trusted_principal_resolver(
                env=values
            ).resolve_narrative_evaluator_principal()
        ),
    )


def build_book_design_authority_query(
    settings: IndustrialSettings,
) -> BookDesignAuthorityQuery:
    if settings.storage_authority != "postgresql" or not settings.database_url:
        raise RuntimeError("BookDesign Authority requires PostgreSQL authority")
    return BookDesignAuthorityQuery(settings.database_url)


def validate_production_structured_result(
    stage: str,
    output_schema: Mapping[str, object],
    value: Mapping[str, object],
    *,
    output_schema_ref: str = "",
) -> Mapping[str, object]:
    if stage in {CLASSIFICATION_STAGE, DECONSTRUCTION_STAGE, MKAOS_STAGE}:
        return validate_content_intelligence_output(stage, output_schema, value)
    if stage in WORLD_SAMPLE_TASKS and "$schema" not in output_schema:
        from novel_forge.modules.chapter_authority.provider_output_contracts import validate_native_world_schema_fragment
        validated = validate_native_world_schema_fragment(stage, output_schema, value, output_schema_ref=output_schema_ref)
    else:
        validated = validate_chapter_provider_output_against_schema(stage, output_schema, value)
    if stage in {
        *FOUNDATION_GENERATORS,
        "book_plan.generate", "volume_plan.generate", "arc_plan.generate",
        "chapter_group_plan.generate", "chapter_plan.generate",
        "narrative_semantic_evaluation", *WORLD_SAMPLE_TASKS,
    }:
        return validated
    semantic = validate_chapter_provider_output_semantics(
        stage, validated, output_schema_ref=output_schema_ref,
    )
    return normalize_model_output(stage, semantic, output_schema_ref=output_schema_ref)


def build_production_execution_composition(
    settings: IndustrialSettings,
    *,
    env: Mapping[str, str] | None = None,
    provider_registry: ProviderAdapterRegistry | None = None,
    planning_fixture_factory: (
        Callable[[str, Mapping[str, object]], dict[str, object]] | None
    ) = None,
    chapter_fixture_factory: (
        Callable[[str, Mapping[str, object]], dict[str, object]] | None
    ) = None,
) -> ProductionExecutionComposition:
    values = os.environ if env is None else env
    if not settings.database_url:
        raise RuntimeError("PostgreSQL database is required for chapter authority")
    runtime_environment = RuntimeEnvironment.parse(
        str(values.get("NOVEL_FORGE_ENVIRONMENT") or settings.environment)
    )
    environment = runtime_environment.value
    router_providers = configured_router_provider_ids(runtime_environment, values)
    channel_resources = str(values.get("NOVEL_FORGE_RESOURCE_CONTROL_VERSION") or "") == "billing-channel-resources.v1"
    disabled_provider_reasons = {}
    if channel_resources and {"codex-cli", "deepseek"}.issubset(router_providers):
        values = dict(values)
        from novel_forge.modules.production_execution.execution_template import load_paid_configuration
        paid, unavailable = load_paid_configuration(values)
        if unavailable or not values.get("DEEPSEEK_API_KEY"):
            disabled_provider_reasons["deepseek"] = unavailable or "PAID_CREDENTIAL_UNAVAILABLE"
            router_providers = tuple(provider for provider in router_providers if provider != "deepseek")
            values["NOVEL_FORGE_ROUTER_PROVIDERS"] = ",".join(router_providers)
            if "NOVEL_FORGE_ROUTER_PROVIDER_TASK_SCOPE" in values:
                scope = json.loads(values["NOVEL_FORGE_ROUTER_PROVIDER_TASK_SCOPE"])
                if not isinstance(scope, dict):
                    raise ValueError("ROUTING_PROVIDER_TASK_SCOPE_INVALID")
                scope.pop("deepseek", None)
                values["NOVEL_FORGE_ROUTER_PROVIDER_TASK_SCOPE"] = json.dumps(scope)
        else:
            values.setdefault("NOVEL_FORGE_PROVIDER_MAX_COST_PER_CALL", paid["maximum_amount"])
    router_enabled = bool(router_providers)
    deepseek_enabled = "deepseek" in router_providers
    codex_router_enabled = "codex-cli" in router_providers
    provider_task_scope = None
    if "NOVEL_FORGE_ROUTER_PROVIDER_TASK_SCOPE" in values:
        provider_task_scope = json.loads(values["NOVEL_FORGE_ROUTER_PROVIDER_TASK_SCOPE"])
        if not router_enabled or not isinstance(provider_task_scope, dict):
            raise ValueError("ROUTING_PROVIDER_TASK_SCOPE_INVALID")
    codex_router_reasoning = "high"
    codex_catalog = ()
    if "NOVEL_FORGE_CODEX_ROUTER_MODELS" in values:
        from novel_forge.modules.production_execution.codex_model_catalog import parse_codex_model_catalog
        if not codex_router_enabled:
            raise ValueError("Codex model catalog requires the formal Codex Router")
        codex_catalog = parse_codex_model_catalog(values["NOVEL_FORGE_CODEX_ROUTER_MODELS"])
    if codex_router_enabled:
        codex_router_reasoning = str(values.get(
            "NOVEL_FORGE_CODEX_ROUTER_REASONING_EFFORT", "high"
        )).strip()
        if codex_router_reasoning not in {"low", "medium", "high", "xhigh", "max"}:
            raise ValueError(
                "NOVEL_FORGE_CODEX_ROUTER_REASONING_EFFORT must be low, medium, high, xhigh, or max"
            )
    if router_enabled:
        templates = dict(values)
        if deepseek_enabled:
            from novel_forge.modules.production_execution.routing_catalog import deepseek_candidates

            default_candidate = deepseek_candidates(available=True)[0]
            provider, model, reasoning = (
                default_candidate.provider, default_candidate.model, default_candidate.reasoning
            )
            context_limit = default_candidate.context_limit
            output_limit = default_candidate.output_limit
            accounting_method = "DEEPSEEK_UTF8_BYTES_UPPER_BOUND_V1"
            accounting_evidence = default_candidate.capability_version
        else:
            provider = "codex-cli"
            model = str(values.get("NOVEL_FORGE_CODEX_ESCALATION_MODEL") or "").strip()
            reasoning = codex_router_reasoning
            context_limit = int(values.get("NOVEL_FORGE_CODEX_ESCALATION_CONTEXT_LIMIT") or 0)
            catalog_model = next((entry for entry in codex_catalog
                if entry["model"] == model and entry["reasoning"] == reasoning), None)
            output_limit = int(catalog_model["output_limit"] if catalog_model
                else values.get("NOVEL_FORGE_CODEX_ESCALATION_OUTPUT_LIMIT") or 0)
            accounting_method = "CODEX_CLI_APPLICATION_UTF8_BYTES_UPPER_BOUND_V1"
            accounting_evidence = str(values.get("NOVEL_FORGE_CODEX_CONFIGURATION_REF") or "")
        for stage_name in ("MODEL", "MEMO", "DRAFT", "REVIEW", "REVISION", "REREVIEW",
                           "CANON_EXTRACTION", "CANON_SUPPORT", "QUALITY", "READER_OUTCOME",
                           "NARRATIVE_EVALUATOR", "MODEL_REFERENCE", "AGENT", "PLANNING"):
            templates[f"NOVEL_FORGE_{stage_name}_PROVIDER"] = provider
            templates[f"NOVEL_FORGE_{stage_name}_MODEL"] = model
        templates["NOVEL_FORGE_REASONING_EFFORT"] = reasoning
        templates["NOVEL_FORGE_AGENT_REASONING_EFFORT"] = reasoning
        templates["NOVEL_FORGE_NARRATIVE_SEMANTIC_EVALUATION_REASONING_EFFORT"] = reasoning
        templates["NOVEL_FORGE_MODEL_REFERENCE_REASONING_EFFORT"] = reasoning
        templates["NOVEL_FORGE_PROVIDER_MODEL_CONTEXT_LIMIT"] = str(context_limit)
        templates.setdefault("NOVEL_FORGE_PROVIDER_MODEL_OUTPUT_LIMIT", str(output_limit))
        templates["NOVEL_FORGE_PROVIDER_TOKEN_ACCOUNTING_METHOD"] = accounting_method
        templates["NOVEL_FORGE_PROVIDER_TOKEN_ACCOUNTING_EVIDENCE_REF"] = accounting_evidence
        values = templates
    registry = provider_registry or build_provider_adapter_registry(
        environment=runtime_environment,
        provider_ids=configured_chapter_provider_ids(values),
        env=values,
    )
    controlled = runtime_environment.controlled
    if controlled:
        release_sha = str(values.get("NOVEL_FORGE_COMMIT_SHA") or "0" * 40).lower()
    else:
        release_sha = str(values.get("NOVEL_FORGE_COMMIT_SHA") or "0" * 40).lower()
        if len(release_sha) != 40:
            raise RuntimeError(
                "NOVEL_FORGE_COMMIT_SHA must be a full 40-character commit id"
            )
    runtime_host_id = str(
        values.get("NOVEL_FORGE_RUNTIME_HOST_ID")
        or ("host:fixture" if not controlled else "host:unverified")
    ).strip()
    auth_profile_ref = str(
        values.get("NOVEL_FORGE_PROVIDER_AUTH_PROFILE")
        or ("auth:fixture" if not controlled else "auth:unverified")
    ).strip()
    routes: dict[str, ChapterExecutionRoute] = {}
    provider_adapters: dict[str, object] = {}
    backend_capabilities: dict[str, ExecutionCapabilityProfile] = {}
    codex_models: set[str] = set()
    repository_artifacts = (
        default_chapter_artifact_resolver(settings.root) if controlled else None
    )
    pack_binding = (
        json.loads((settings.root / "config/capability_packs/chapter_generation_pack.json").read_text())
        if controlled else {}
    )
    prompt_binding = dict(pack_binding.get("prompt_binding") or {})
    skill_versions = {
        str(item["skill_ref"]): str(item["version"])
        for item in (pack_binding.get("skill_binding") or {}).get("skills") or ()
    }
    stage_routes = [
        ("memo", "NOVEL_FORGE_MEMO_PROVIDER", "NOVEL_FORGE_MEMO_MODEL"),
        (
            "canon_support",
            "NOVEL_FORGE_CANON_SUPPORT_PROVIDER",
            "NOVEL_FORGE_CANON_SUPPORT_MODEL",
        ),
        ("draft", "NOVEL_FORGE_DRAFT_PROVIDER", "NOVEL_FORGE_DRAFT_MODEL"),
        ("review", "NOVEL_FORGE_REVIEW_PROVIDER", "NOVEL_FORGE_REVIEW_MODEL"),
        ("revision", "NOVEL_FORGE_REVISION_PROVIDER", "NOVEL_FORGE_REVISION_MODEL"),
        ("rereview", "NOVEL_FORGE_REREVIEW_PROVIDER", "NOVEL_FORGE_REREVIEW_MODEL"),
        (
            "canon_extraction",
            "NOVEL_FORGE_CANON_EXTRACTION_PROVIDER",
            "NOVEL_FORGE_CANON_EXTRACTION_MODEL",
        ),
        (
            "quality_structural",
            "NOVEL_FORGE_QUALITY_PROVIDER",
            "NOVEL_FORGE_QUALITY_MODEL",
        ),
        (
            "quality_commercial",
            "NOVEL_FORGE_QUALITY_PROVIDER",
            "NOVEL_FORGE_QUALITY_MODEL",
        ),
        (
            "quality_source_originality",
            "NOVEL_FORGE_QUALITY_PROVIDER",
            "NOVEL_FORGE_QUALITY_MODEL",
        ),
        (
            "quality_longform",
            "NOVEL_FORGE_QUALITY_PROVIDER",
            "NOVEL_FORGE_QUALITY_MODEL",
        ),
        (
            "quality_platform",
            "NOVEL_FORGE_QUALITY_PROVIDER",
            "NOVEL_FORGE_QUALITY_MODEL",
        ),
        (
            "longform_prose_review",
            "NOVEL_FORGE_REVIEW_PROVIDER",
            "NOVEL_FORGE_REVIEW_MODEL",
        ),
        (
            "reader_outcome",
            "NOVEL_FORGE_READER_OUTCOME_PROVIDER",
            "NOVEL_FORGE_READER_OUTCOME_MODEL",
        ),
        (
            "narrative_semantic_evaluation",
            "NOVEL_FORGE_NARRATIVE_EVALUATOR_PROVIDER",
            "NOVEL_FORGE_NARRATIVE_EVALUATOR_MODEL",
        ),
    ]
    model_reference_provider = str(values.get("NOVEL_FORGE_MODEL_REFERENCE_PROVIDER") or "").strip()
    model_reference_model = str(values.get("NOVEL_FORGE_MODEL_REFERENCE_MODEL") or "").strip()
    if bool(model_reference_provider) != bool(model_reference_model):
        raise RuntimeError("model reference route requires both explicit Provider and model")
    if model_reference_provider:
        stage_routes.extend((
            ("model_reference_evaluate", "NOVEL_FORGE_MODEL_REFERENCE_PROVIDER", "NOVEL_FORGE_MODEL_REFERENCE_MODEL"),
            ("model_reference_adjudicate", "NOVEL_FORGE_MODEL_REFERENCE_PROVIDER", "NOVEL_FORGE_MODEL_REFERENCE_MODEL"),
        ))
    stage_routes.extend([
        ("context_compress", "NOVEL_FORGE_REVIEW_PROVIDER", "NOVEL_FORGE_REVIEW_MODEL"),
        ("context_fidelity", "NOVEL_FORGE_REVIEW_PROVIDER", "NOVEL_FORGE_REVIEW_MODEL"),
        ("screenplay_generate", "NOVEL_FORGE_DRAFT_PROVIDER", "NOVEL_FORGE_DRAFT_MODEL"),
        ("screenplay_review", "NOVEL_FORGE_REVIEW_PROVIDER", "NOVEL_FORGE_REVIEW_MODEL"),
        ("screenplay_revision", "NOVEL_FORGE_REVISION_PROVIDER", "NOVEL_FORGE_REVISION_MODEL"),
    ])
    agent_provider = str(values.get("NOVEL_FORGE_AGENT_PROVIDER") or "").strip()
    agent_model = str(values.get("NOVEL_FORGE_AGENT_MODEL") or "").strip()
    agent_binding_enabled = bool(agent_provider and agent_model)
    if bool(agent_provider) != bool(agent_model):
        raise RuntimeError(
            "Agent production binding requires both NOVEL_FORGE_AGENT_PROVIDER "
            "and NOVEL_FORGE_AGENT_MODEL"
        )
    if agent_binding_enabled:
        stage_routes.extend(
            (
                (
                    "agent_session",
                    "NOVEL_FORGE_AGENT_PROVIDER",
                    "NOVEL_FORGE_AGENT_MODEL",
                ),
                (
                    "retrieval_query_expansion",
                    "NOVEL_FORGE_AGENT_PROVIDER",
                    "NOVEL_FORGE_AGENT_MODEL",
                ),
            )
        )
    embedding_provider = str(values.get("NOVEL_FORGE_EMBEDDING_PROVIDER") or "").strip()
    embedding_model = str(values.get("NOVEL_FORGE_EMBEDDING_MODEL") or "").strip()
    if bool(embedding_provider) != bool(embedding_model):
        raise RuntimeError(
            "semantic retrieval binding requires both "
            "NOVEL_FORGE_EMBEDDING_PROVIDER and NOVEL_FORGE_EMBEDDING_MODEL"
        )
    if embedding_provider and embedding_model:
        raw_embedding_dimensions = str(
            values.get("NOVEL_FORGE_EMBEDDING_DIMENSIONS") or ""
        ).strip()
        if controlled and not raw_embedding_dimensions:
            raise RuntimeError(
                "controlled semantic retrieval requires "
                "NOVEL_FORGE_EMBEDDING_DIMENSIONS"
            )
        try:
            embedding_dimensions = int(raw_embedding_dimensions or "8")
        except ValueError as exc:
            raise RuntimeError(
                "NOVEL_FORGE_EMBEDDING_DIMENSIONS must be an integer"
            ) from exc
        if not 1 <= embedding_dimensions <= 8192:
            raise RuntimeError(
                "NOVEL_FORGE_EMBEDDING_DIMENSIONS must be between 1 and 8192"
            )
        stage_routes.append(
            (
                "retrieval",
                "NOVEL_FORGE_EMBEDDING_PROVIDER",
                "NOVEL_FORGE_EMBEDDING_MODEL",
            )
        )
    for stage, provider_key, model_key in stage_routes:
        capability_definition = default_capability_registry().resolve(
            chapter_stage_capability(stage)
        )
        if (
            stage
            in {
                "narrative_semantic_evaluation",
                "model_reference_evaluate", "model_reference_adjudicate",
                "agent_session",
                "retrieval_query_expansion",
            }
            and controlled
        ):
            if not all(
                str(values.get(key) or "").strip()
                for key in (
                    provider_key,
                    model_key,
                    (
                        "NOVEL_FORGE_AGENT_REASONING_EFFORT"
                        if stage in {"agent_session", "retrieval_query_expansion"}
                        else "NOVEL_FORGE_MODEL_REFERENCE_REASONING_EFFORT"
                        if stage in {"model_reference_evaluate", "model_reference_adjudicate"}
                        else "NOVEL_FORGE_NARRATIVE_SEMANTIC_EVALUATION_REASONING_EFFORT"
                    ),
                )
            ):
                raise RuntimeError(
                    "controlled evaluator requires an explicit Provider, model, and reasoning effort"
                )
        provider = str(
            values.get(provider_key)
            or (
                values.get("NOVEL_FORGE_REVIEW_PROVIDER")
                if stage in {"rereview", "canon_support", "memo"}
                else values.get("NOVEL_FORGE_REVISION_PROVIDER")
                if stage == "canon_extraction"
                else values.get("NOVEL_FORGE_REVIEW_PROVIDER")
                if stage.startswith("quality_")
                or stage in {"reader_outcome", "longform_prose_review", "narrative_semantic_evaluation", "model_reference_evaluate", "model_reference_adjudicate"}
                else ""
            )
            or values.get("NOVEL_FORGE_MODEL_PROVIDER")
            or ""
        ).strip()
        if not provider:
            raise RuntimeError(
                f"explicit chapter model provider is required for {stage}"
            )
        normalized_provider = normalize_provider_id(provider)
        model_name = str(
            values.get(model_key)
            or (
                values.get("NOVEL_FORGE_REVIEW_MODEL")
                if stage in {"rereview", "canon_support", "memo"}
                else values.get("NOVEL_FORGE_REVISION_MODEL")
                if stage == "canon_extraction"
                else values.get("NOVEL_FORGE_REVIEW_MODEL")
                if stage.startswith("quality_")
                or stage in {"reader_outcome", "longform_prose_review", "narrative_semantic_evaluation", "model_reference_evaluate", "model_reference_adjudicate"}
                else ""
            )
            or ""
        ).strip()
        codex_cli = normalized_provider == "codex-cli"
        if codex_cli:
            if not model_name:
                raise RuntimeError(f"explicit Codex model is required for {stage}")
            resolved_model = model_name
            scripted = False
            backend_id = "codex-cli"
            provider_identity = "codex-cli"
            runtime_class = ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE
            real_provider_eligible = True
            qualification_ref = "capability-probe:codex-cli:real-runtime-v1"
            reasoning_effort = str(
                values.get(f"NOVEL_FORGE_{stage.upper()}_REASONING_EFFORT")
                or (values.get("NOVEL_FORGE_MODEL_REFERENCE_REASONING_EFFORT")
                    if stage in {"model_reference_evaluate", "model_reference_adjudicate"} else "")
                or values.get("NOVEL_FORGE_REASONING_EFFORT")
                or "high"
            )
            codex_models.add(resolved_model)
        else:
            try:
                adapter = registry.resolve(normalized_provider)
            except ValueError as exc:
                raise RuntimeError(str(exc)) from exc
            resolved_model = model_name or f"{normalized_provider}-{stage}"
            qualification = registry.qualify(
                normalized_provider,
                resolved_model,
                environment=environment,
            )
            if not qualification.qualified:
                raise RuntimeError(
                    "provider v2 route qualification failed: "
                    + "; ".join(qualification.reasons)
                )
            provider_profile = adapter.capability_profile
            scripted = (
                provider_profile.control_level
                is ProviderControlLevel.FIXTURE_CONTROLLED
            )
            backend_id = (
                "scripted-fixture"
                if scripted
                else "remote-provider-" + adapter.provider.replace("_", "-")
            )
            provider_identity = adapter.provider
            runtime_class = (
                ExecutionRuntimeClass.SCRIPTED_FIXTURE
                if scripted
                else ExecutionRuntimeClass.REMOTE_PROVIDER_API
            )
            real_provider_eligible = provider_profile.real_provider_validation_eligible
            qualification_ref = (
                "capability-probe:scripted-fixture:1"
                if scripted
                else f"capability-probe:{adapter.provider}:"
                f"{provider_profile.contract_version}"
            )
            reasoning_effort = str(
                values.get(f"NOVEL_FORGE_{stage.upper()}_REASONING_EFFORT")
                or values.get("NOVEL_FORGE_REASONING_EFFORT")
                or "high"
            )
        backend_version = "1.0.0"
        if not scripted and not codex_cli:
            provider_adapters[backend_id] = adapter
            backend_capabilities[backend_id] = ExecutionCapabilityProfile(
                backend_id=backend_id,
                backend_version=backend_version,
                runtime_class=ExecutionRuntimeClass.REMOTE_PROVIDER_API,
                supported_completion_modes=(
                    CompletionMode.SYNCHRONOUS,
                    CompletionMode.POLL,
                    CompletionMode.CALLBACK,
                ),
                supported_reasoning_efforts=("low", "medium", "high", "xhigh", "max"),
                supports_query=provider_profile.supports_query,
                supports_cancel=provider_profile.supports_cancel,
                supports_callback=provider_profile.supports_callback,
                supports_usage_receipt=provider_profile.supports_usage_receipt,
                supports_cost_receipt=provider_profile.supports_cost_receipt,
                supports_structured_output=True,
                supports_process_group_control=False,
                supports_persistent_execution_directory=False,
                supports_provider_idempotency=provider_profile.supports_provider_idempotency,
                real_provider_validation_eligible=(
                    provider_profile.real_provider_validation_eligible
                ),
                qualification_ref=qualification_ref,
            )
        profile_id = (
            "story-design.narrative-semantic-evaluator.default"
            if stage == "narrative_semantic_evaluation"
            else f"chapter.{stage}.default"
        )
        profile = ModelProfile(
            profile_id=profile_id,
            profile_version=2 if capability_definition.capability_id is CapabilityId.PLANNING_CHAPTER_MEMO else 1,
            backend_id=backend_id,
            runtime_class=runtime_class,
            model_provider=provider_identity,
            model_id=resolved_model,
            reasoning_effort=reasoning_effort,
            timeout_policy_ref=capability_definition.timeout_policy_ref,
            workspace_policy_ref="workspace:chapter-authority:v1",
            output_policy_ref=f"output:chapter:{stage}:json:v1",
            fallback_policy="FAIL_CLOSED",
            status=ModelProfileStatus.ACTIVE,
            capability_probe_ref=qualification_ref,
        )
        policy = RoutePolicy(
            policy_id=(
                "story-design.narrative-semantic-evaluator.route"
                if stage == "narrative_semantic_evaluation"
                else "chapter.agent_session.route"
                if stage == "agent_session"
                else f"chapter.{stage}.route"
            ),
            policy_version=1,
            default_model_profile_id=profile_id,
            allowed_model_profile_ids=(profile_id,),
            rule_set_ref=(
                "route-rules:story-design:narrative-semantic-evaluator:v1"
                if stage == "narrative_semantic_evaluation"
                else f"route-rules:chapter:{stage}:v1"
            ),
            fallback_policy="FAIL_CLOSED",
            fallback_policy_ref=(
                "story-design.narrative-semantic-evaluator.fail-closed"
                if stage == "narrative_semantic_evaluation"
                else f"chapter.{stage}.fail-closed"
            ),
            fallback_policy_version=1,
            reasoning_downgrade_policy="PROHIBITED",
            status="ACTIVE",
        )
        fallback_policy = FallbackPolicy.fail_closed(
            policy.fallback_policy_ref,
            policy.fallback_policy_version,
        )
        if (codex_cli or router_enabled) and repository_artifacts is not None and stage != "agent_session":
            system_artifact = repository_artifacts.resolve(
                ArtifactKind.PROMPT_SYSTEM_INSTRUCTION,
                "prompt-system:chapter-generation-pack",
                str(prompt_binding["system_instruction_version"]),
            )
            template_artifact = repository_artifacts.resolve(
                ArtifactKind.PROMPT_TEMPLATE,
                "prompt-template:chapter-generation-pack",
                str(prompt_binding["template_version"]),
            )
            skill_artifact = repository_artifacts.resolve(
                ArtifactKind.SKILL,
                _PACK_SKILL_FOR_STAGE[stage],
                skill_versions[_PACK_SKILL_FOR_STAGE[stage]],
            )
            prompt_version = f"{system_artifact.ref}@{system_artifact.version}"
            skill_version = f"{skill_artifact.ref}@{skill_artifact.version}"
            system_instruction_hash = system_artifact.content_hash
            template_hash = template_artifact.content_hash
            skill_content_hash = skill_artifact.content_hash
        else:
            prompt_version = str(
                values.get(f"NOVEL_FORGE_{stage.upper()}_PROMPT_VERSION")
                or f"chapter-{stage}-prompt-v1"
            )
            skill_version = str(
                values.get(f"NOVEL_FORGE_{stage.upper()}_SKILL_VERSION")
                or f"chapter-{stage}-skill-v1"
            )
            system_instruction_hash = _execution_content_hash(
                values,
                stage=stage,
                specific_key=(f"NOVEL_FORGE_{stage.upper()}_SYSTEM_INSTRUCTION_HASH"),
                common_key="NOVEL_FORGE_PROMPT_SYSTEM_INSTRUCTION_HASH",
                controlled=controlled,
                fixture_identity=prompt_version + ":system",
            )
            template_hash = _execution_content_hash(
                values,
                stage=stage,
                specific_key=f"NOVEL_FORGE_{stage.upper()}_PROMPT_TEMPLATE_HASH",
                common_key="NOVEL_FORGE_PROMPT_TEMPLATE_HASH",
                controlled=controlled,
                fixture_identity=prompt_version + ":template",
            )
            skill_content_hash = _execution_content_hash(
                values,
                stage=stage,
                specific_key=f"NOVEL_FORGE_{stage.upper()}_SKILL_BUNDLE_HASH",
                common_key="NOVEL_FORGE_SKILL_BUNDLE_HASH",
                controlled=controlled,
                fixture_identity=skill_version,
            )
        routes[stage] = ChapterExecutionRoute(
            stage=stage,
            model_profile=profile,
            route_policy=policy,
            fallback_policy=fallback_policy,
            backend_version=backend_version,
            runtime_host_id=runtime_host_id,
            auth_profile_ref=auth_profile_ref,
            prompt_version=prompt_version,
            skill_version=skill_version,
            system_instruction_hash=system_instruction_hash,
            template_hash=template_hash,
            skill_content_hash=skill_content_hash,
            prompt_compiler_version=(
                str(prompt_binding["compiler_version"])
                if prompt_binding else str(values.get("NOVEL_FORGE_PROMPT_COMPILER_VERSION") or "chapter-prompt-compiler:v2")
            ),
            output_schema_ref=capability_definition.output_schema_ref,
            release_sha=release_sha,
            real_provider_validation_eligible=real_provider_eligible,
            embedding_dimensions=(embedding_dimensions if stage == "retrieval" else 0),
            model_context_limit=int(
                values.get(f"NOVEL_FORGE_{stage.upper()}_MODEL_CONTEXT_LIMIT")
                or values.get("NOVEL_FORGE_PROVIDER_MODEL_CONTEXT_LIMIT")
                or 0
            ),
            model_output_limit=int(
                values.get(f"NOVEL_FORGE_{stage.upper()}_MODEL_OUTPUT_LIMIT")
                or values.get("NOVEL_FORGE_PROVIDER_MODEL_OUTPUT_LIMIT")
                or 0
            ),
            token_accounting_method=str(
                values.get(f"NOVEL_FORGE_{stage.upper()}_TOKEN_ACCOUNTING_METHOD")
                or values.get("NOVEL_FORGE_PROVIDER_TOKEN_ACCOUNTING_METHOD")
                or ""
            ).strip(),
            token_accounting_evidence_ref=str(
                values.get(f"NOVEL_FORGE_{stage.upper()}_TOKEN_ACCOUNTING_EVIDENCE_REF")
                or values.get("NOVEL_FORGE_PROVIDER_TOKEN_ACCOUNTING_EVIDENCE_REF")
                or ""
            ).strip(),
            token_safety_margin=int(
                values.get("NOVEL_FORGE_PROVIDER_TOKEN_SAFETY_MARGIN") or 256
            ),
            token_framing_overhead=int(
                values.get("NOVEL_FORGE_PROVIDER_TOKEN_FRAMING_OVERHEAD") or 16
            ),
        )
    if controlled:
        _build_id, verified_release_sha = authority_release_identity(env=values)
        verified_runtime_host = str(
            values.get("NOVEL_FORGE_RUNTIME_HOST_ID") or ""
        ).strip()
        verified_auth_profile = str(
            values.get("NOVEL_FORGE_PROVIDER_AUTH_PROFILE") or ""
        ).strip()
        if not verified_runtime_host or not verified_auth_profile:
            raise RuntimeError(
                "controlled Chapter execution requires runtime host and Provider auth profile"
            )
        routes = {
            stage: replace(
                route,
                release_sha=verified_release_sha,
                runtime_host_id=verified_runtime_host,
                auth_profile_ref=verified_auth_profile,
            )
            for stage, route in routes.items()
        }
    codex_escalation_enabled = codex_router_enabled and not codex_catalog
    if codex_router_enabled:
        escalation_model = str(values.get("NOVEL_FORGE_CODEX_ESCALATION_MODEL") or "").strip()
        if not escalation_model or (not channel_resources and int(values.get("NOVEL_FORGE_CODEX_ESCALATION_CALL_LIMIT") or 0) <= 0):
            raise RuntimeError("Codex Router lane requires an explicit model and finite call allowance")
        if codex_catalog and not any(entry["model"] == escalation_model and entry["role"] == "PRIMARY" for entry in codex_catalog):
            raise RuntimeError("Codex model catalog must explicitly bind the configured primary model")
        codex_models.add(escalation_model)
        codex_models.update(entry["model"] for entry in codex_catalog)
    if codex_models:
        if len(codex_models) != 1 and not codex_catalog:
            raise RuntimeError("this phase requires one explicit Codex model")
        if not router_enabled and any(
            route.model_profile.runtime_class
            is not ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE
            for route in routes.values()
        ):
            raise RuntimeError(
                "mixed Codex and alternate Provider routing is not supported in this phase"
            )
    cost_accounting_basis = (
        str(values.get("NOVEL_FORGE_CODEX_ACCOUNTING_MODE") or ("ACCOUNT_ENTITLEMENT" if channel_resources else "PRICED")).strip().upper()
    )
    codex_accounting_basis = cost_accounting_basis
    if codex_router_enabled:
        if codex_accounting_basis != "ACCOUNT_ENTITLEMENT":
            raise RuntimeError("Codex Router lane requires governed account entitlement")
        if deepseek_enabled:
            cost_accounting_basis = "PRICED"
    if cost_accounting_basis not in {"PRICED", "ACCOUNT_ENTITLEMENT"}:
        raise RuntimeError("unsupported Codex cost accounting mode")
    if cost_accounting_basis == "ACCOUNT_ENTITLEMENT" and not codex_models:
        raise RuntimeError(
            "account entitlement is supported only by the Codex CLI route"
        )
    object_root_value = str(
        values.get("NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT") or ""
    ).strip()
    if not object_root_value:
        raise RuntimeError("explicit authority object-store root is required")
    max_cost_per_call = str(
        values.get("NOVEL_FORGE_PROVIDER_MAX_COST_PER_CALL") or ""
    ).strip()
    if controlled and cost_accounting_basis == "PRICED":
        if not max_cost_per_call:
            raise RuntimeError(
                "NOVEL_FORGE_PROVIDER_MAX_COST_PER_CALL is required for production providers"
            )
    object_root = Path(object_root_value).expanduser()
    if not object_root.is_absolute():
        object_root = settings.root / object_root
    object_store_backend = (
        str(values.get("NOVEL_FORGE_AUTHORITY_OBJECT_STORE_BACKEND") or "local")
        .strip()
        .lower()
    )
    if object_store_backend == "minio":
        from novel_forge.storage.object_store import MinioObjectStore

        store = MinioObjectStore(settings)
        object_store_adapter = MinioObjectStoreExternalEffectAdapter(
            store.client, bucket=settings.minio_artifact_bucket
        )
        source_object_reader = MinioObjectStoreReader(
            store.client, bucket=settings.minio_artifact_bucket
        )
    elif object_store_backend == "local" and runtime_environment.fixture_allowed:
        object_store_adapter = LocalFileObjectStoreAdapter(object_root)
        source_object_reader = LocalObjectStoreReader(object_root)
    else:
        raise RuntimeError(
            "controlled Authority runtime requires the MinIO object-store backend"
        )

    codex_executable = ""
    codex_home = ""
    codex_workspace: Path | None = None
    codex_execution_root: Path | None = None
    codex_pricing: CodexPricingSnapshot | None = None
    codex_entitlement: CodexAccountEntitlementSnapshot | None = None
    codex_model = str(values.get("NOVEL_FORGE_CODEX_ESCALATION_MODEL") or "") if codex_catalog else next(iter(codex_models), "")
    if codex_models:
        from novel_forge.modules.production_execution.codex_configuration import (
            codex_local_binding_hash,
            require_codex_home,
        )

        codex_home = require_codex_home(str(values.get("NOVEL_FORGE_CODEX_HOME") or ""))
        codex_executable = str(values.get("NOVEL_FORGE_CODEX_EXECUTABLE") or "").strip()
        workspace_value = str(values.get("NOVEL_FORGE_CODEX_WORKSPACE") or "").strip()
        execution_root_value = str(
            values.get("NOVEL_FORGE_CODEX_EXECUTION_ROOT") or ""
        ).strip()
        executable_path = Path(codex_executable).expanduser()
        codex_workspace = Path(workspace_value).expanduser()
        codex_execution_root = Path(execution_root_value).expanduser()
        if (
            not codex_executable
            or not executable_path.is_absolute()
            or not executable_path.is_file()
            or not codex_workspace.is_absolute()
            or not codex_workspace.is_dir()
            or any(codex_workspace.iterdir())
            or not codex_execution_root.is_absolute()
        ):
            raise RuntimeError(
                "controlled Codex requires an absolute executable, empty isolated "
                "workspace, and absolute persistent execution root"
            )
        if channel_resources and codex_accounting_basis != "ACCOUNT_ENTITLEMENT":
            raise RuntimeError("membership resource policy forbids priced Codex execution")
        if codex_accounting_basis == "PRICED":
            if codex_catalog:
                raise RuntimeError("Codex model catalog requires account entitlement")
            required_pricing = {
                "pricing_ref": str(
                    values.get("NOVEL_FORGE_CODEX_PRICING_REF") or ""
                ).strip(),
                "currency": str(
                    values.get("NOVEL_FORGE_CODEX_PRICING_CURRENCY") or ""
                ).strip(),
                "input_per_million": str(
                    values.get("NOVEL_FORGE_CODEX_INPUT_PER_MILLION") or ""
                ).strip(),
                "cached_input_per_million": str(
                    values.get("NOVEL_FORGE_CODEX_CACHED_INPUT_PER_MILLION") or ""
                ).strip(),
                "output_per_million": str(
                    values.get("NOVEL_FORGE_CODEX_OUTPUT_PER_MILLION") or ""
                ).strip(),
            }
            if any(not value for value in required_pricing.values()):
                raise RuntimeError(
                    "controlled Codex requires an explicit immutable pricing snapshot"
                )
            codex_pricing = CodexPricingSnapshot(
                model_id=codex_model,
                **required_pricing,
            )
        else:
            entitlement_values = {
                "authorization_ref": str(
                    values.get("NOVEL_FORGE_CODEX_ACCOUNT_AUTHORIZATION_REF") or ""
                ).strip(),
                "account_identity_ref": str(
                    values.get("NOVEL_FORGE_CODEX_ACCOUNT_IDENTITY_REF") or ""
                ).strip(),
                "cli_version": str(
                    values.get("NOVEL_FORGE_CODEX_CLI_VERSION") or ""
                ).strip(),
                "executable_sha256": str(
                    values.get("NOVEL_FORGE_CODEX_EXECUTABLE_SHA256") or ""
                ).strip(),
                "configuration_ref": str(
                    values.get("NOVEL_FORGE_CODEX_CONFIGURATION_REF") or ""
                ).strip(),
            }
            if any(not value for value in entitlement_values.values()):
                raise RuntimeError(
                    "controlled Codex account entitlement requires frozen authorization, account, CLI and configuration identity"
                )
            with executable_path.open("rb") as executable_stream:
                executable_digest = (
                    "sha256:"
                    + hashlib.file_digest(executable_stream, "sha256").hexdigest()
                )
            if executable_digest != entitlement_values["executable_sha256"]:
                raise RuntimeError(
                    "controlled Codex executable differs from its frozen digest"
                )
            observed_cli_version = observe_codex_cli_version(
                executable_path,
                working_directory=codex_workspace,
            )
            if observed_cli_version != entitlement_values["cli_version"]:
                raise RuntimeError(
                    "controlled Codex CLI version differs from its frozen identity"
                )
            if channel_resources:
                from novel_forge.modules.production_execution.membership_identity import observe_membership_identity
                billing_identity = observe_membership_identity(codex_home)
                if entitlement_values["account_identity_ref"] != billing_identity["account_ref"]:
                    raise RuntimeError("Codex account reference differs from observed membership identity")
                entitlement_values["billing_identity"] = billing_identity
            codex_entitlement = CodexAccountEntitlementSnapshot(**entitlement_values)
        local_binding = codex_local_binding_hash(
            codex_home=codex_home, executable=codex_executable,
            entitlement=codex_entitlement.to_dict() if codex_entitlement else None,
            retry_policy=str(values.get("NOVEL_FORGE_CODEX_RETRY_POLICY") or ""),
        )
        routes = {
            stage: replace(
                route,
                auth_profile_ref=route.auth_profile_ref + ":codex:" + local_binding,
            )
            for stage, route in routes.items()
        }

    def fixture_response(stage: str, inputs: Mapping[str, object]) -> dict[str, object]:
        if stage in {
            CLASSIFICATION_STAGE,
            DECONSTRUCTION_STAGE,
            MKAOS_STAGE,
        }:
            return content_intelligence_fixture_response(stage, inputs)
        if stage in {
            *FOUNDATION_GENERATORS,
            "book_plan.generate",
            "volume_plan.generate",
            "arc_plan.generate",
            "chapter_group_plan.generate",
            "chapter_plan.generate",
        }:
            fixture = planning_fixture_factory or planning_fixture_response
            return fixture(stage, inputs)
        if stage in WORLD_SAMPLE_TASKS:
            if planning_fixture_factory is None:
                raise ValueError(
                    "world preparation requires an explicit fixture transport"
                )
            return planning_fixture_factory(stage, inputs)
        fixture = chapter_fixture_factory or default_chapter_fixture_response
        return fixture(stage, inputs)

    def execution_session(project_id: str) -> ChapterExecutionGatewaySession:
        contracts = PostgresExecutionContractSource(
            settings.database_url, project_id=project_id
        )
        admission = AdmissionController(
            contracts,
            PostgresAttemptFenceVerifier(settings.database_url),
            environment=environment,
        )
        store = AuthorityExecutionRecoveryStore(
            settings.database_url,
            project_id=project_id,
        )
        backends = ExecutionBackendRegistry()
        if any(
            route.model_profile.runtime_class is ExecutionRuntimeClass.SCRIPTED_FIXTURE
            for route in routes.values()
        ):
            backends.register(
                ScriptedFixtureExecutionBackend(
                    admission=admission,
                    payload_resolver=PostgresProductionExecutionPayloadResolver(
                        settings.database_url,
                        fixture_response_factory=fixture_response,
                        source_object_reader=source_object_reader,
                        working_directory=settings.root,
                    ),
                    record_store=store,
                )
            )
        if codex_models:
            assert codex_workspace is not None
            assert codex_execution_root is not None
            assert (codex_pricing is None) != (codex_entitlement is None)
            backends.register(
                CodexCliExecutionBackend(
                    admission=admission,
                    payload_resolver=PostgresProductionExecutionPayloadResolver(
                        settings.database_url,
                        source_object_reader=source_object_reader,
                        working_directory=codex_workspace,
                    ),
                    record_store=store,
                    supervisor=CodexProcessSupervisor(
                        PersistentExecutionDirectory(codex_execution_root)
                    ),
                    execution_policy=LocalProcessExecutionPolicy(
                        fixed_working_directory=str(codex_workspace),
                        allowed_command_prefixes=((codex_executable, "exec"),),
                        maximum_result_bytes=int(
                            values.get("NOVEL_FORGE_CODEX_MAX_RESULT_BYTES")
                            or 2_000_000
                        ),
                    ),
                    codex_executable=codex_executable,
                    codex_home=codex_home,
                    pricing=codex_pricing,
                    account_entitlement=codex_entitlement,
                    retry_policy=str(values.get("NOVEL_FORGE_CODEX_RETRY_POLICY") or ""),
                    structured_result_validator=validate_production_structured_result,
                    qualification_ref="capability-probe:codex-cli:real-runtime-v1",
                )
            )
        for backend_id, adapter in provider_adapters.items():
            backends.register(
                RemoteProviderExecutionBackend(
                    backend_id=backend_id,
                    capability_profile=backend_capabilities[backend_id],
                    provider_adapter=adapter,
                    admission=admission,
                    payload_resolver=PostgresProductionExecutionPayloadResolver(
                        settings.database_url,
                        source_object_reader=source_object_reader,
                        working_directory=settings.root,
                    ),
                    record_store=store,
                    structured_result_validator=validate_production_structured_result,
                    callback_consumer=ProviderCallbackAuthorityService(
                        settings.database_url, registry
                    ).consume_pending,
                )
            )
        gateway = ProductionExecutionGateway(backends, admission)
        return ChapterExecutionGatewaySession(gateway, store)

    call_cap_environment = {
        "project_total": "NOVEL_FORGE_PROJECT_PROVIDER_CALL_LIMIT",
        "operation_total": "NOVEL_FORGE_OPERATION_PROVIDER_CALL_LIMIT",
        "provider_project_total": "NOVEL_FORGE_PROVIDER_PROJECT_CALL_LIMIT",
        "project_daily": "NOVEL_FORGE_PROJECT_DAILY_PROVIDER_CALL_LIMIT",
        "provider_project_daily": "NOVEL_FORGE_PROVIDER_DAILY_CALL_LIMIT",
        "global_daily": "NOVEL_FORGE_GLOBAL_DAILY_PROVIDER_CALL_LIMIT",
        "global_total": "NOVEL_FORGE_GLOBAL_PROVIDER_CALL_LIMIT",
        "global_monthly": "NOVEL_FORGE_GLOBAL_MONTHLY_PROVIDER_CALL_LIMIT",
        "work_total": "NOVEL_FORGE_WORK_PROVIDER_CALL_LIMIT",
        "model_project_total": "NOVEL_FORGE_MODEL_PROJECT_CALL_LIMIT",
    }
    token_cap_environment = {
        "project_total": "NOVEL_FORGE_PROJECT_PROVIDER_TOKEN_LIMIT",
        "operation_total": "NOVEL_FORGE_OPERATION_PROVIDER_TOKEN_LIMIT",
        "provider_project_total": "NOVEL_FORGE_PROVIDER_PROJECT_TOKEN_LIMIT",
        "project_daily": "NOVEL_FORGE_PROJECT_DAILY_PROVIDER_TOKEN_LIMIT",
        "provider_project_daily": "NOVEL_FORGE_PROVIDER_DAILY_TOKEN_LIMIT",
        "global_daily": "NOVEL_FORGE_GLOBAL_DAILY_PROVIDER_TOKEN_LIMIT",
        "global_total": "NOVEL_FORGE_GLOBAL_PROVIDER_TOKEN_LIMIT",
        "global_monthly": "NOVEL_FORGE_GLOBAL_MONTHLY_PROVIDER_TOKEN_LIMIT",
        "work_total": "NOVEL_FORGE_WORK_PROVIDER_TOKEN_LIMIT",
        "model_project_total": "NOVEL_FORGE_MODEL_PROJECT_TOKEN_LIMIT",
    }
    provider_call_caps = {
        dimension: int(str(values[environment_name]))
        for dimension, environment_name in call_cap_environment.items()
        if str(values.get(environment_name) or "").strip()
    }
    provider_token_caps = {
        dimension: int(str(values[environment_name]))
        for dimension, environment_name in token_cap_environment.items()
        if str(values.get(environment_name) or "").strip()
    }
    if not channel_resources and codex_accounting_basis == "ACCOUNT_ENTITLEMENT" and (
        provider_call_caps.get("project_total", 0) <= 0
        or provider_token_caps.get("project_total", 0) <= 0
    ):
        raise RuntimeError(
            "account entitlement requires positive project Provider call and token limits"
        )
    model_gateway = ProductionExecutionGatewayExternalEffectAdapter(
        database_url=settings.database_url,
        routes=routes,
        session_factory=execution_session,
        provider_adapters={
            adapter.provider: adapter for adapter in provider_adapters.values()
        },
        cost_accounting_basis=cost_accounting_basis,
        account_authorization_ref=(
            codex_entitlement.authorization_ref if codex_entitlement else ""
        ),
        provider_call_caps=provider_call_caps,
        provider_token_caps=provider_token_caps,
        resource_control_version="billing-channel-resources.v1" if channel_resources else "",
    )
    if router_enabled:
        from novel_forge.modules.production_execution.routing_runtime import ProductionProviderRouter
        from novel_forge.modules.production_execution.routing_catalog import deepseek_candidates
        from novel_forge.modules.authority_handler_runtime.routing_feedback import domain_gate_outcomes
        from novel_forge.modules.production_execution.membership_identity import observed_paid_binding

        candidates = list(deepseek_candidates(available=True)) if deepseek_enabled else []
        if codex_router_enabled:
            from novel_forge.modules.production_execution.cost_routing import ModelCandidate, PricingSnapshot
            assert codex_entitlement is not None
            context_limit = int(values.get("NOVEL_FORGE_CODEX_ESCALATION_CONTEXT_LIMIT") or 0)
            output_limit = int(values.get("NOVEL_FORGE_CODEX_ESCALATION_OUTPUT_LIMIT") or 0)
            if codex_catalog:
                from novel_forge.modules.production_execution.codex_model_catalog import codex_catalog_candidates
                candidates.extend(codex_catalog_candidates(codex_catalog,
                    entitlement=codex_entitlement.to_dict(),
                    quota=None if channel_resources else int(values["NOVEL_FORGE_CODEX_ESCALATION_CALL_LIMIT"]),
                    valid_from=str(values.get("NOVEL_FORGE_CODEX_ESCALATION_VALID_FROM") or ""),
                    valid_until=str(values.get("NOVEL_FORGE_CODEX_ESCALATION_VALID_UNTIL") or "")))
            else:
                candidates.append(ModelCandidate(
                    candidate_id=f"codex-cli:{codex_model}:{codex_router_reasoning}", provider="codex-cli", model=codex_model,
                    reasoning=codex_router_reasoning, tier="escalation", capabilities=("structured_output", "text"),
                    context_limit=context_limit, output_limit=output_limit,
                    pricing=PricingSnapshot(
                        version=codex_entitlement.configuration_ref,
                        effective_from=str(values.get("NOVEL_FORGE_CODEX_ESCALATION_VALID_FROM") or ""),
                        effective_until=str(values.get("NOVEL_FORGE_CODEX_ESCALATION_VALID_UNTIL") or ""),
                        input_miss_per_million="0", input_hit_per_million="0", output_per_million="0",
                        currency="UNKNOWN", source=codex_entitlement.authorization_ref,
                        accounting_basis="ACCOUNT_ENTITLEMENT"),
                    capability_version=codex_entitlement.configuration_ref,
                    model_revision=codex_entitlement.configuration_ref,
                    escalation_only=codex_escalation_enabled,
                    quota_remaining=None if channel_resources else int(values["NOVEL_FORGE_CODEX_ESCALATION_CALL_LIMIT"]),
                    authorization_ref=codex_entitlement.authorization_ref,
                ))
        from novel_forge.modules.review.cross_model_binding import freeze_review_requirement
        model_gateway.provider_router = ProductionProviderRouter(
            settings.database_url, candidates=candidates, execution_environment=environment,
            provider_task_scope=provider_task_scope,
            task_money_limit=max_cost_per_call or "0",
            task_token_limit=int(values.get("NOVEL_FORGE_PROVIDER_MODEL_CONTEXT_LIMIT") or 0) if channel_resources else int(values.get("NOVEL_FORGE_OPERATION_PROVIDER_TOKEN_LIMIT") or 0),
            soft_money_limit=str(values.get("NOVEL_FORGE_ROUTER_SOFT_COST_PER_TASK") or "") or None,
            outcome_projection=domain_gate_outcomes,
            review_requirement_resolver=freeze_review_requirement,
            membership_identity=codex_entitlement.billing_identity if codex_entitlement else None,
            disabled_provider_reasons=disabled_provider_reasons,
            provider_billing_accounts={"deepseek": str(values.get("NOVEL_FORGE_DEEPSEEK_BILLING_ACCOUNT_REF") or "").strip()},
            provider_billing_identities={"deepseek": observed_paid_binding(
                str(values.get("NOVEL_FORGE_DEEPSEEK_BILLING_ACCOUNT_REF") or "").strip(), str(values.get("DEEPSEEK_API_KEY") or ""))},
            provider_auth_profiles={
                **({"codex-cli": next(iter(routes.values())).auth_profile_ref} if codex_router_enabled else {}),
                **({"deepseek": "provider-account:deepseek:credential-sha256:"
                    + hashlib.sha256(str(values["DEEPSEEK_API_KEY"]).strip().encode()).hexdigest()}
                   if deepseek_enabled else {}),
            },
        )
    from novel_forge.modules.production_execution.provider_admission import SHARED_PROVIDER_MONEY_CAP_ENVIRONMENT

    shared_budget_caps = {} if channel_resources else {
        key: str(values[value])
        for key, value in SHARED_PROVIDER_MONEY_CAP_ENVIRONMENT
        if str(values.get(value) or "").strip()
    }
    if cost_accounting_basis == "ACCOUNT_ENTITLEMENT" and shared_budget_caps:
        raise RuntimeError(
            "account entitlement cannot use monetary Provider cap configuration"
        )
    if model_gateway.provider_router is not None:
        model_gateway.provider_router.money_caps = dict(shared_budget_caps)
        model_gateway.provider_router.token_caps = dict(provider_token_caps)
        model_gateway.provider_router.call_caps = dict(provider_call_caps)
    chapter_total_budget_cap = "" if channel_resources else str(
        values.get("NOVEL_FORGE_CHAPTER_PROVIDER_CAP") or ""
    ).strip()
    if cost_accounting_basis == "ACCOUNT_ENTITLEMENT" and chapter_total_budget_cap:
        raise RuntimeError(
            "account entitlement cannot use a monetary Chapter Provider cap"
        )
    return ProductionExecutionComposition(
        gateway=model_gateway,
        object_store=object_store_adapter,
        source_object_reader=source_object_reader,
        runtime_environment=runtime_environment,
        max_cost_per_call=max_cost_per_call or "0",
        shared_budget_caps=shared_budget_caps,
        chapter_total_budget_cap=chapter_total_budget_cap,
        cost_accounting_basis=cost_accounting_basis,
        account_authorization_ref=(
            codex_entitlement.authorization_ref if codex_entitlement else ""
        ),
        provider_call_caps=provider_call_caps,
        provider_token_caps=provider_token_caps,
    )


def build_chapter_authority_application(
    settings: IndustrialSettings,
    *,
    execution: ProductionExecutionComposition,
    env: Mapping[str, str] | None = None,
    runtime_fault_injector: Callable[[str], None] | None = None,
) -> ChapterAuthorityApplication:
    if not settings.database_url:
        raise RuntimeError("PostgreSQL database is required for chapter authority")
    values = os.environ if env is None else env
    runtime_environment = RuntimeEnvironment.parse(
        str(values.get("NOVEL_FORGE_ENVIRONMENT") or settings.environment)
    )
    if runtime_environment is not execution.runtime_environment:
        raise RuntimeError("Chapter and Production Execution environments must match")
    environment = runtime_environment.value
    controlled = runtime_environment.controlled
    binder = PostgresChapterExecutionContractBinder(
        settings.database_url,
        execution.gateway.routes,
        capability_pack_id=str(
            values.get("NOVEL_FORGE_CHAPTER_CAPABILITY_PACK_ID")
            or "chapter_generation_pack"
        ),
        pack_environment=environment,
        pack_runtime_profile=environment,
        pack_release_channel=str(
            values.get("NOVEL_FORGE_RELEASE_CHANNEL") or "VALIDATION"
        ),
        pack_required=controlled,
    )
    execution.gateway.register_execution_binder("chapter", binder)
    embedding_binder = None
    if "retrieval" in execution.gateway.routes:
        if controlled:
            artifacts = default_chapter_artifact_resolver(settings.root)
            embedding_binder = PostgresRetrievalProjectionExecutionContractBinder(
                settings.database_url,
                execution.gateway.routes,
                frozen_artifacts={
                    "system_instruction": artifacts.resolve(
                        ArtifactKind.PROMPT_SYSTEM_INSTRUCTION,
                        "prompt-system:chapter-generation-pack",
                        "v1",
                    ),
                    "prompt_template": artifacts.resolve(
                        ArtifactKind.PROMPT_TEMPLATE,
                        "prompt-template:chapter-generation-pack",
                        "v2",
                    ),
                    "skill": artifacts.resolve(
                        ArtifactKind.SKILL,
                        "context-builder-source-isolation",
                        "context-builder-source-isolation-v1",
                    ),
                },
            )
        else:
            embedding_binder = PostgresChapterExecutionContractBinder(
                settings.database_url,
                execution.gateway.routes,
                capability_pack_id="",
                pack_environment=environment,
                pack_runtime_profile=environment,
                pack_required=False,
            )
        execution.gateway.register_execution_binder(
            "retrieval_projection", embedding_binder
        )
    if runtime_environment.controlled:
        application_build_id, commit_sha = authority_release_identity(env=env)
    else:
        application_build_id = str(
            values.get("NOVEL_FORGE_APPLICATION_BUILD_ID")
            or "chapter-authority-fixture"
        )
        commit_sha = str(values.get("NOVEL_FORGE_COMMIT_SHA") or "0" * 40)
    return ChapterAuthorityApplication(
        settings.database_url,
        model_adapter=execution.gateway,
        object_store_adapter=execution.object_store,
        capability_binder=binder,
        # INVARIANT: projection is not a Chapter Saga node. Its domain contract freezes
        # Provider materialization without borrowing Chapter Pack authority.
        embedding_capability_binder=(embedding_binder if controlled else None),
        worker_id=str(
            values.get("NOVEL_FORGE_AUTHORITY_WORKER_ID") or "chapter-authority-api"
        ),
        allow_synchronous_fixture=runtime_environment.fixture_allowed
        and str(
            values.get("NOVEL_FORGE_ENABLE_SYNCHRONOUS_AUTHORITY_FIXTURE") or ""
        ).lower()
        in {"1", "true", "yes"},
        max_cost_per_model_call=execution.max_cost_per_call,
        budget_caps=execution.budget_caps(include_chapter_total=True),
        # INVARIANT: retrieval projection is project/operation/provider governed but is
        # not a Chapter-stage model effect.  Applying the Chapter aggregate
        # cap here creates a cap with no Chapter budget lineage to charge.
        embedding_budget_caps=execution.budget_caps(),
        agent_binding_recorder=None,
        agent_binding_required=False,
        runtime_fault_injector=runtime_fault_injector,
        application_build_id=application_build_id,
        commit_sha=commit_sha,
    )


def build_agent_runtime_authority_application(
    settings: IndustrialSettings,
    *,
    execution: ProductionExecutionComposition | None = None,
    env: Mapping[str, str] | None = None,
) -> AgentRuntimeAuthorityApplication:
    if settings.storage_authority != "postgresql" or not settings.database_url:
        raise RuntimeError("Agent Runtime Authority requires PostgreSQL authority")
    build_id, commit_sha = authority_release_identity(env=env)
    values = os.environ if env is None else env
    route = execution.gateway.routes.get("agent_session") if execution else None
    agent_pack_id = str(
        values.get("NOVEL_FORGE_AGENT_CAPABILITY_PACK_ID") or "agent_session_pack"
    )
    return AgentRuntimeAuthorityApplication(
        settings.database_url,
        application_build_id=build_id,
        commit_sha=commit_sha,
        runtime_environment=RuntimeEnvironment.parse(
            str(values.get("NOVEL_FORGE_ENVIRONMENT") or settings.environment)
        ).value,
        release_channel=str(values.get("NOVEL_FORGE_RELEASE_CHANNEL") or "VALIDATION"),
        production_agent_model_binding=(
            agent_route_execution_identity(route, capability_pack_id=agent_pack_id)
            if route is not None
            else None
        ),
    )


def build_agent_runtime_query(settings: IndustrialSettings) -> AgentRuntimeQuery:
    if settings.storage_authority != "postgresql" or not settings.database_url:
        raise RuntimeError("Agent Runtime query requires PostgreSQL authority")
    return AgentRuntimeQuery(settings.database_url)


def build_capability_pack_authority_application(
    settings: IndustrialSettings,
    *,
    env: Mapping[str, str] | None = None,
) -> CapabilityPackAuthorityApplication:
    if settings.storage_authority != "postgresql" or not settings.database_url:
        raise RuntimeError("Capability Pack Authority requires PostgreSQL authority")
    build_id, commit_sha = authority_release_identity(env=env)
    return CapabilityPackAuthorityApplication(
        settings.database_url,
        application_build_id=build_id,
        commit_sha=commit_sha,
    )


def build_capability_pack_authority_query(
    settings: IndustrialSettings,
    *,
    env: Mapping[str, str] | None = None,
) -> CapabilityPackAuthorityQuery:
    if settings.storage_authority != "postgresql" or not settings.database_url:
        raise RuntimeError("Capability Pack Authority query requires PostgreSQL")
    _, commit_sha = authority_release_identity(env=env)
    values = os.environ if env is None else env
    return CapabilityPackAuthorityQuery(
        settings.database_url,
        current_release_sha=commit_sha,
        current_runtime_profile=RuntimeEnvironment.parse(
            str(values.get("NOVEL_FORGE_ENVIRONMENT") or settings.environment)
        ).value,
        current_release_channel=str(
            values.get("NOVEL_FORGE_RELEASE_CHANNEL") or "VALIDATION"
        ),
    )


def build_quality_qualification_authority(
    settings: IndustrialSettings,
    *,
    env: Mapping[str, str] | None = None,
) -> PostgresQualityQualificationAuthority:
    if settings.storage_authority != "postgresql" or not settings.database_url:
        raise RuntimeError("Quality Qualification requires PostgreSQL authority")
    build_id, commit_sha = authority_release_identity(env=env)
    return PostgresQualityQualificationAuthority(
        settings.database_url,
        application_build_id=build_id,
        commit_sha=commit_sha,
    )


def build_agent_authority_scheduler(
    settings: IndustrialSettings,
    *,
    execution: ProductionExecutionComposition,
    worker_id: str,
    env: Mapping[str, str] | None = None,
) -> AgentAuthorityScheduler:
    if not settings.database_url:
        raise RuntimeError("Agent worker requires PostgreSQL authority")
    values = os.environ if env is None else env
    runtime_environment = RuntimeEnvironment.parse(
        str(values.get("NOVEL_FORGE_ENVIRONMENT") or settings.environment)
    )
    if runtime_environment is not execution.runtime_environment:
        raise RuntimeError("Agent and Production Execution environments must match")
    environment = execution.runtime_environment.value
    binder = PostgresChapterExecutionContractBinder(
        settings.database_url,
        execution.gateway.routes,
        capability_pack_id=str(
            values.get("NOVEL_FORGE_CHAPTER_CAPABILITY_PACK_ID")
            or "chapter_generation_pack"
        ),
        pack_environment=environment,
        pack_runtime_profile=environment,
        pack_release_channel=str(
            values.get("NOVEL_FORGE_RELEASE_CHANNEL") or "VALIDATION"
        ),
        pack_required=execution.runtime_environment.controlled,
    )
    preparer = ChapterGatewayAgentExecutionPreparer(
        settings.database_url,
        adapter=execution.gateway,
        capability_binder=binder,
        worker_id=worker_id,
        max_cost_per_call=execution.max_cost_per_call,
        budget_caps=execution.budget_caps(include_chapter_total=True),
    )
    harness_factory = None
    if runtime_environment.fixture_allowed:
        harness_factory = build_scripted_agent_harness_factory(
            settings.database_url,
            worker_id=worker_id,
        )
    elif "agent_session" in execution.gateway.routes:
        agent_binder = PostgresAgentExecutionContractBinder(
            settings.database_url,
            execution.gateway.routes,
            capability_pack_id=str(
                values.get("NOVEL_FORGE_AGENT_CAPABILITY_PACK_ID")
                or "agent_session_pack"
            ),
            pack_environment=environment,
            pack_runtime_profile=environment,
            pack_release_channel=str(
                values.get("NOVEL_FORGE_RELEASE_CHANNEL") or "VALIDATION"
            ),
            pack_required=True,
        )
        planning = build_story_planning_generation_application(
            settings,
            execution=execution,
            env=values,
        )
        plan_change = PostgresPlanChangeAuthority(
            settings.database_url,
            story_design=planning.story_design,
            planning=planning.planning,
            application_build_id=planning.application_build_id,
            commit_sha=planning.commit_sha,
            worker_id=f"{worker_id}:plan-change",
        )
        principal = build_trusted_principal_resolver(env=values).resolve_api_principal()
        harness_factory = build_production_agent_harness_factory(
            settings.database_url,
            adapter=execution.gateway,
            capability_binder=agent_binder,
            planning=planning,
            plan_change=plan_change,
            principal=principal,
            worker_id=worker_id,
            max_cost_per_call=execution.max_cost_per_call,
            budget_caps=execution.budget_caps(),
        )
    return AgentAuthorityScheduler(
        settings.database_url,
        execution_preparer=preparer,
        worker_id=worker_id,
        harness_factory=harness_factory,
    )


def build_production_preparation_service(
    settings: IndustrialSettings,
) -> ProductionPreparationService:
    if not settings.database_url:
        raise RuntimeError("PostgreSQL database is required for production preparation")
    return ProductionPreparationService(
        PostgresProductionAssetResolver(settings.database_url)
    )


def build_trusted_principal_resolver(
    *,
    env: Mapping[str, str] | None = None,
) -> TrustedPrincipalResolver:
    return TrustedPrincipalResolver.from_environment(os.environ if env is None else env)


def build_content_authority_application(
    settings: IndustrialSettings,
    *,
    env: Mapping[str, str] | None = None,
) -> ContentAuthorityApplication:
    if not settings.database_url:
        raise RuntimeError("PostgreSQL database is required for Content Authority")
    build_id, commit_sha = authority_release_identity(env=env)
    return ContentAuthorityApplication(
        settings.database_url,
        application_build_id=build_id,
        commit_sha=commit_sha,
        integration_proven=CONTENT_INTEGRATION_PROVEN,
        trusted_only=True,
    )


def build_content_authority_query(
    settings: IndustrialSettings,
) -> ContentAuthorityQuery:
    if not settings.database_url:
        raise RuntimeError("PostgreSQL database is required for Content Authority")
    return ContentAuthorityQuery(settings.database_url)


def build_source_import_application(
    settings: IndustrialSettings,
    *,
    execution: ProductionExecutionComposition,
    env: Mapping[str, str] | None = None,
) -> SourceImportApplication:

    if settings.storage_authority != "postgresql" or not settings.database_url:
        raise RuntimeError("Source Import runtime requires PostgreSQL authority")
    values = os.environ if env is None else env
    runtime_environment = RuntimeEnvironment.parse(
        str(values.get("NOVEL_FORGE_ENVIRONMENT") or settings.environment)
    )
    if runtime_environment is not execution.runtime_environment:
        raise RuntimeError(
            "Source Import and Production Execution environments must match"
        )
    build_id, commit_sha = authority_release_identity(env=values)
    worker_id = str(
        values.get("NOVEL_FORGE_SOURCE_IMPORT_WORKER_ID") or "source-import-worker"
    ).strip()
    git_cache_value = str(
        values.get("NOVEL_FORGE_SOURCE_IMPORT_GIT_CACHE_ROOT") or ""
    ).strip()
    if runtime_environment.controlled and not git_cache_value:
        raise RuntimeError(
            "controlled Source Import requires NOVEL_FORGE_SOURCE_IMPORT_GIT_CACHE_ROOT"
        )
    git_cache = Path(git_cache_value or ".local/source-import/git-cache").expanduser()
    if not git_cache.is_absolute():
        git_cache = settings.root / git_cache
    file_fixture_root = str(
        values.get("NOVEL_FORGE_SOURCE_IMPORT_FILE_FIXTURE_ROOT") or ""
    ).strip()
    allow_file = runtime_environment.fixture_allowed and bool(file_fixture_root)
    git_adapter = GitRepositoryExternalEffectAdapter(
        git_cache,
        allow_file_repositories=allow_file,
        allowed_file_roots=(Path(file_fixture_root).expanduser(),)
        if allow_file
        else (),
        timeout_seconds=int(
            values.get("NOVEL_FORGE_SOURCE_IMPORT_GIT_TIMEOUT_SECONDS") or "120"
        ),
    )
    execution_port = PostgresContentIntelligenceExecutionPort(
        settings.database_url,
        transport=execution.gateway,
        worker_id=worker_id,
        lease_seconds=int(values.get("NOVEL_FORGE_AUTHORITY_LEASE_SECONDS") or "30"),
        max_cost_per_call=execution.max_cost_per_call,
        budget_caps=execution.budget_caps(),
        source_object_reader=execution.source_object_reader,
        provider_output_token_reserve=int(
            values.get("NOVEL_FORGE_SOURCE_PROVIDER_OUTPUT_TOKEN_RESERVE") or 4_096
        ),
        provider_timeout_seconds=int(
            values.get("NOVEL_FORGE_SOURCE_PROVIDER_TIMEOUT_SECONDS") or 300
        ),
    )
    return SourceImportApplication(
        settings.database_url,
        application_build_id=build_id,
        commit_sha=commit_sha,
        worker_id=worker_id,
        git_adapter=git_adapter,
        corpus_adapter=_build_corpus_acquisition_adapter(git_adapter, values),
        object_store_adapter=execution.object_store,
        object_store_reader=execution.source_object_reader,
        execution_port=execution_port,
        allow_fixture_intelligence=runtime_environment.fixture_allowed,
        allow_file_repositories=allow_file,
    )


def build_chapter_authority_query(
    settings: IndustrialSettings,
) -> ChapterAuthorityQuery:
    if not settings.database_url:
        raise RuntimeError("PostgreSQL database is required for chapter authority")
    return ChapterAuthorityQuery(settings.database_url)


def chapter_capability_pack_compilation_report(
    settings: IndustrialSettings,
    *,
    env: Mapping[str, str] | None = None,
) -> dict[str, object]:

    values = os.environ if env is None else env
    _build_id, release_sha = authority_release_identity(env=values)
    manifest = load_capability_pack(
        settings.root / "config/capability_packs/chapter_generation_pack.json"
    )
    compiler = CapabilityPackCompiler(
        capability_registry=default_capability_registry(),
        capability_type_catalog=default_capability_type_catalog(),
        operation_catalog=chapter_operation_definition_catalog(release_sha=release_sha),
        workflow_catalog=chapter_workflow_binding_catalog(),
        artifact_resolver=default_chapter_artifact_resolver(settings.root),
        tool_catalog=default_tool_definition_catalog(),
        pack_catalog=ReadOnlyPackCatalog((PackCatalogEntry(manifest),)),
    )
    environment = (
        str(values.get("NOVEL_FORGE_ENVIRONMENT") or settings.environment)
        .strip()
        .lower()
    )
    result = compiler.compile(
        manifest,
        target_runtime_profile=environment,
        novel_forge_version="7.0.0",
        release_sha=release_sha,
        release_channel=str(
            values.get("NOVEL_FORGE_RELEASE_CHANNEL") or "VALIDATION"
        ).upper(),
    )
    return {
        "ok": result.report.ok,
        "pack_id": result.report.pack_id,
        "pack_version": result.report.version,
        "manifest_hash": result.report.manifest_hash,
        "compilation_hash": result.report.compilation_hash,
        "errors": [
            {"code": item.code, "path": item.path, "message": item.message}
            for item in result.report.errors
        ],
    }


def build_book_authority_application(
    settings: IndustrialSettings,
    *,
    execution: ProductionExecutionComposition,
    chapter_application: ChapterAuthorityApplication,
    env: Mapping[str, str] | None = None,
) -> PostgresBookAuthority:
    if not settings.database_url:
        raise RuntimeError("PostgreSQL database is required for Book Authority")
    build_id, commit_sha = authority_release_identity(env=env)
    followup = build_book_followup_authority_application(
        settings,
        execution=execution,
        env=env,
    )
    return PostgresBookAuthority(
        settings.database_url,
        chapter_port=ChapterAuthorityCommandAdapter(
            chapter_application,
            external_effect_adapters=execution.external_effect_adapters,
        ),
        followup_application=followup,
        application_build_id=build_id,
        commit_sha=commit_sha,
        legacy_fixture_input_allowed=RuntimeEnvironment.parse(
            str(
                (os.environ if env is None else env).get("NOVEL_FORGE_ENVIRONMENT")
                or settings.environment
            )
        ).fixture_allowed,
    )


def build_book_followup_authority_application(
    settings: IndustrialSettings,
    *,
    execution: ProductionExecutionComposition,
    env: Mapping[str, str] | None = None,
) -> BookFollowupAuthorityApplication:

    if not settings.database_url:
        raise RuntimeError("PostgreSQL database is required for Book Followup")
    values = os.environ if env is None else env
    build_id, commit_sha = authority_release_identity(env=values)
    from novel_forge.modules.book_followup_authority.screenplay_execution import build_screenplay_model_ports
    return BookFollowupAuthorityApplication(
        settings.database_url,
        application_build_id=build_id,
        commit_sha=commit_sha,
        model_port=build_reader_outcome_model_port(
            settings,
            execution=execution,
            env=values,
        ),
        prose_model_port=build_longform_prose_review_model_port(settings, execution=execution, env=values),
        screenplay_model_ports=build_screenplay_model_ports(settings, execution=execution, env=values),
        worker_id=str(
            values.get("NOVEL_FORGE_BOOK_FOLLOWUP_WORKER_ID")
            or "book-followup-authority-worker"
        ),
    )


def _book_opening_provider_budget_policy(
    execution: Any, values: Mapping[str, str],
) -> dict[str, Any]:
    if values.get("NOVEL_FORGE_RESOURCE_CONTROL_VERSION") == "billing-channel-resources.v1":
        if not execution.account_authorization_ref:
            raise RuntimeError("Membership resource controls require authenticated account authorization")
        return {"resource_control_version": "billing-channel-resources.v1", "execution_mode": "PROVIDER_ALLOWED",
            "accounting_basis": "ACCOUNT_ENTITLEMENT", "authorization_ref": execution.account_authorization_ref,
            "cost_observability": "UNKNOWN", "per_call_token_limit": int(values.get("NOVEL_FORGE_PROVIDER_MODEL_CONTEXT_LIMIT") or values.get("NOVEL_FORGE_CODEX_ESCALATION_CONTEXT_LIMIT") or 0)}
    opening_budget_policy: dict[str, Any] = {
        "execution_mode": "PROVIDER_ALLOWED",
        "provider_call_limit": int(
            values.get("NOVEL_FORGE_BOOK_OPENING_PROVIDER_CALL_LIMIT") or 48
        ),
        "token_limit": int(
            values.get("NOVEL_FORGE_BOOK_OPENING_PROVIDER_TOKEN_LIMIT") or 4_800_000
        ),
        "per_call_token_limit": int(
            values.get("NOVEL_FORGE_BOOK_OPENING_PROVIDER_PER_CALL_TOKEN_LIMIT")
            or 100_000
        ),
    }
    if execution.cost_accounting_basis == "ACCOUNT_ENTITLEMENT":
        opening_budget_policy.update(
            {
                "accounting_basis": "ACCOUNT_ENTITLEMENT",
                "authorization_ref": execution.account_authorization_ref,
                "cost_observability": "UNKNOWN",
            }
        )
        forbidden_cost_settings = (
            "NOVEL_FORGE_BOOK_OPENING_PROVIDER_COST_LIMIT",
            "NOVEL_FORGE_BOOK_OPENING_PROVIDER_PER_CALL_COST_LIMIT",
        )
        if any(str(values.get(name) or "").strip() for name in forbidden_cost_settings):
            raise RuntimeError(
                "account entitlement Book Opening cannot declare monetary limits"
            )
    else:
        opening_budget_policy.update(
            {
                "cost_limit_usd": str(
                    values.get("NOVEL_FORGE_BOOK_OPENING_PROVIDER_COST_LIMIT") or "96"
                ),
                "per_call_cost_limit_usd": str(
                    values.get("NOVEL_FORGE_BOOK_OPENING_PROVIDER_PER_CALL_COST_LIMIT")
                    or "2"
                ),
            }
        )

    raw_lane = str(values.get("NOVEL_FORGE_BOOK_OPENING_ACCOUNT_ENTITLEMENT_POLICY") or "").strip()
    if raw_lane:
        import json
        from novel_forge.modules.command_kernel.budget_runtime import canonical_budget_policy

        lane = json.loads(raw_lane)
        if not isinstance(lane, dict) or execution.cost_accounting_basis != "PRICED":
            raise ValueError("Book Opening entitlement lane requires a priced parent and explicit policy")
        router = execution.gateway.provider_router
        matching = [candidate for candidate in (router.candidates if router else ())
                    if candidate.provider == "codex-cli" and (candidate.escalation_only or candidate.entitlement_role == "PRIMARY")
                    and candidate.model == lane.get("model_id")
                    and candidate.authorization_ref == lane.get("authorization_ref")
                    and candidate.capability_version == lane.get("authorization_version")
                    and candidate.pricing.version == lane.get("authorization_version")
                    and candidate.pricing.accounting_basis == "ACCOUNT_ENTITLEMENT"
                    and candidate.pricing.currency == "UNKNOWN"]
        if len(matching) != 1 or int(lane.get("provider_call_limit") or 0) > matching[0].quota_remaining:
            raise ValueError("Book Opening entitlement lane differs from the configured authorized route")
        opening_budget_policy["account_entitlement_lane"] = lane
        opening_budget_policy = canonical_budget_policy(opening_budget_policy)["policy_snapshot"]
    return opening_budget_policy


def build_book_production_composition(
    settings: IndustrialSettings,
    *,
    principal: Principal,
    execution: ProductionExecutionComposition,
    chapter_application: ChapterAuthorityApplication,
    env: Mapping[str, str] | None = None,
    planning_post_provider_fault_injector: Callable[[str], None] | None = None,
) -> BookProductionComposition:

    if not settings.database_url:
        raise RuntimeError("PostgreSQL database is required for Book production")
    values = os.environ if env is None else env
    authority = build_book_authority_application(
        settings,
        execution=execution,
        chapter_application=chapter_application,
        env=values,
    )
    planning = build_story_planning_generation_application(
        settings,
        execution=execution,
        env=values,
        post_provider_fault_injector=planning_post_provider_fault_injector,
    )
    preparation = build_production_preparation_service(settings)
    chapter_groups = PostgresChapterGroupAuthority(
        settings.database_url,
        book_authority=authority,
        application_build_id=authority.application_build_id,
        commit_sha=authority.commit_sha,
        worker_id=str(
            values.get("NOVEL_FORGE_CHAPTER_GROUP_WORKER_ID")
            or "chapter-group-authority-worker"
        ),
    )
    plan_change = PostgresPlanChangeAuthority(
        settings.database_url,
        story_design=planning.story_design,
        planning=planning.planning,
        application_build_id=authority.application_build_id,
        commit_sha=authority.commit_sha,
        worker_id=str(
            values.get("NOVEL_FORGE_PLAN_CHANGE_WORKER_ID")
            or "plan-change-authority-worker"
        ),
    )
    input_resolver = BookProductionInputResolver(
        settings.database_url,
        application_build_id=authority.application_build_id,
        commit_sha=authority.commit_sha,
        allow_scripted_qualification_fixture=(
            _scripted_narrative_evaluation_fixture_enabled(
                RuntimeEnvironment.parse(
                    str(values.get("NOVEL_FORGE_ENVIRONMENT") or settings.environment)
                ),
                values,
            )
        ),
    )
    query = PostgresBookProductionQuery(settings.database_url)
    narrative_search = PostgresNarrativeSearchApplication(
        settings.database_url, planning=planning
    )
    from novel_forge.modules.hierarchical_planning import (
        PostgresNarrativeRealizationApplication,
    )

    realizations = PostgresNarrativeRealizationApplication(
        settings.database_url,
        application_build_id=authority.application_build_id,
        commit_sha=authority.commit_sha,
    )
    replan = BookReplanCoordinator(
        settings.database_url,
        book_authority=authority,
        planning=planning,
        plan_change=plan_change,
        input_resolver=input_resolver,
        principal=principal,
        narrative_search=narrative_search,
    )
    supervisor = PostgresBookProductionSupervisor(
        authority,
        planning=planning,
        chapter_groups=chapter_groups,
        query=query,
        principal=principal,
        replan=replan,
        production_preparation=preparation,
        realizations=realizations,
        narrative_search=narrative_search,
        draft_context_profile_version=values.get("NOVEL_FORGE_BOOK_DRAFT_CONTEXT_PROFILE_VERSION") or "draft-context-profile-v2",
        context_token_budget=int(
            values.get("NOVEL_FORGE_BOOK_CONTEXT_TOKEN_BUDGET") or 16_000
        ),
        quality_context_token_budget=int(
            values.get("NOVEL_FORGE_BOOK_QUALITY_CONTEXT_TOKEN_BUDGET")
            or values.get("NOVEL_FORGE_BOOK_CONTEXT_TOKEN_BUDGET")
            or 16_000
        ),
    )
    from novel_forge.modules.book_design_authority import StoryFormationApplication

    opening_budget_policy = _book_opening_provider_budget_policy(execution, values)

    return BookProductionComposition(
        authority=authority,
        query=query,
        planning=planning,
        chapter_groups=chapter_groups,
        production_preparation=preparation,
        followup=authority.followup,
        plan_change=plan_change,
        input_resolver=input_resolver,
        replan=replan,
        corrective_actions=CorrectiveActionQuery(settings.database_url),
        supervisor=supervisor,
        principal=principal,
        projection_repair=PostgresBookProjectionRepairAuthority(
            settings.database_url,
            application_build_id=authority.application_build_id,
            commit_sha=authority.commit_sha,
            worker_id=str(
                values.get("NOVEL_FORGE_BOOK_REPAIR_WORKER_ID")
                or "book-projection-repair-worker"
            ),
        ),
        opening=PostgresBookOpeningApplication(
            settings.database_url,
            narrative_search=narrative_search,
            input_resolver=input_resolver,
            application_build_id=authority.application_build_id,
            commit_sha=authority.commit_sha,
            provider_budget_policy=opening_budget_policy,
            provider_budget_window_seconds=int(
                values.get("NOVEL_FORGE_BOOK_OPENING_PROVIDER_WINDOW_SECONDS") or 3_600
            ),
        ),
        formation=StoryFormationApplication(
            settings.database_url,
            application_build_id=authority.application_build_id,
            commit_sha=authority.commit_sha,
            generation=FormationGeneration(
                planning,
                book_design=build_book_design_authority_application(
                    settings, execution=execution, env=values
                ),
            ),
        ),
    )


def build_reader_outcome_model_port(
    settings: IndustrialSettings,
    *,
    execution: ProductionExecutionComposition,
    env: Mapping[str, str] | None = None,
) -> ExternalEffectChapterModelPort:

    if not settings.database_url:
        raise RuntimeError("PostgreSQL database is required for Reader Outcome")
    values = os.environ if env is None else env
    runtime_environment = RuntimeEnvironment.parse(
        str(values.get("NOVEL_FORGE_ENVIRONMENT") or settings.environment)
    )
    if runtime_environment is not execution.runtime_environment:
        raise RuntimeError(
            "Reader Outcome and Production Execution environments must match"
        )
    environment = runtime_environment.value
    binder = PostgresReaderOutcomeExecutionContractBinder(
        settings.database_url,
        execution.gateway.routes,
        capability_pack_id=str(
            values.get("NOVEL_FORGE_READER_OUTCOME_CAPABILITY_PACK_ID")
            or "reader_outcome_pack"
        ),
        pack_environment=environment,
        pack_runtime_profile=environment,
        pack_release_channel=str(
            values.get("NOVEL_FORGE_RELEASE_CHANNEL") or "VALIDATION"
        ).upper(),
        pack_required=runtime_environment.controlled,
    )
    execution.gateway.register_execution_binder("reader_outcome", binder)
    return ExternalEffectChapterModelPort(
        settings.database_url,
        adapter=execution.gateway,
        worker_id=str(
            values.get("NOVEL_FORGE_BOOK_FOLLOWUP_WORKER_ID")
            or "book-followup-authority-worker"
        ),
        max_cost_per_call=execution.max_cost_per_call,
        budget_caps=execution.budget_caps(),
        capability_binder=binder,
        execution_binding_domain="reader_outcome",
    )


def build_longform_prose_review_model_port(
    settings: IndustrialSettings,
    *,
    execution: ProductionExecutionComposition,
    env: Mapping[str, str] | None = None,
) -> ExternalEffectChapterModelPort:

    from novel_forge.modules.book_followup_authority.prose_execution import PostgresLongformProseReviewExecutionContractBinder

    if not settings.database_url:
        raise RuntimeError("PostgreSQL database is required for Reader Outcome")
    values = os.environ if env is None else env
    runtime_environment = RuntimeEnvironment.parse(
        str(values.get("NOVEL_FORGE_ENVIRONMENT") or settings.environment)
    )
    if runtime_environment is not execution.runtime_environment:
        raise RuntimeError(
            "Reader Outcome and Production Execution environments must match"
        )
    environment = runtime_environment.value
    binder = PostgresLongformProseReviewExecutionContractBinder(
        settings.database_url,
        execution.gateway.routes,
        capability_pack_id=str(
            values.get("NOVEL_FORGE_LONGFORM_PROSE_REVIEW_CAPABILITY_PACK_ID")
            or "longform_prose_review_pack"
        ),
        pack_environment=environment,
        pack_runtime_profile=environment,
        pack_release_channel=str(
            values.get("NOVEL_FORGE_RELEASE_CHANNEL") or "VALIDATION"
        ).upper(),
        pack_required=runtime_environment.controlled,
    )
    execution.gateway.register_execution_binder("longform_prose_review", binder)
    return ExternalEffectChapterModelPort(
        settings.database_url,
        adapter=execution.gateway,
        worker_id=str(
            values.get("NOVEL_FORGE_BOOK_FOLLOWUP_WORKER_ID")
            or "book-followup-authority-worker"
        ),
        max_cost_per_call=execution.max_cost_per_call,
        budget_caps=execution.budget_caps(),
        capability_binder=binder,
        execution_binding_domain="longform_prose_review",
    )


def build_narrative_semantic_evaluation_execution_port(
    settings: IndustrialSettings,
    *,
    execution: ProductionExecutionComposition,
    env: Mapping[str, str] | None = None,
    post_provider_fault_injector: Callable[[str], None] | None = None,
) -> GatewayNarrativeSemanticEvaluationExecutionPort:

    if not settings.database_url:
        raise RuntimeError("PostgreSQL is required for Narrative Evaluation")
    values = os.environ if env is None else env
    runtime_environment = RuntimeEnvironment.parse(
        str(values.get("NOVEL_FORGE_ENVIRONMENT") or settings.environment)
    )
    if runtime_environment is not execution.runtime_environment:
        raise RuntimeError(
            "Narrative Evaluation and Production Execution environments must match"
        )
    environment = runtime_environment.value
    registered = execution.gateway.execution_binders.get("narrative_evaluation")
    if registered is None:
        binder = PostgresNarrativeEvaluationExecutionContractBinder(
            settings.database_url,
            execution.gateway.routes,
            capability_pack_id=str(
                values.get("NOVEL_FORGE_NARRATIVE_EVALUATION_CAPABILITY_PACK_ID")
                or "narrative_semantic_evaluation_pack"
            ),
            pack_environment=environment,
            pack_runtime_profile=environment,
            pack_release_channel=str(
                values.get("NOVEL_FORGE_RELEASE_CHANNEL") or "VALIDATION"
            ).upper(),
            pack_required=runtime_environment.controlled,
        )
        execution.gateway.register_execution_binder("narrative_evaluation", binder)
    elif isinstance(registered, PostgresNarrativeEvaluationExecutionContractBinder):
        binder = registered
    else:
        raise RuntimeError(
            "Narrative Evaluation execution binder domain is already owned"
        )
    model_port = ExternalEffectChapterModelPort(
        settings.database_url,
        adapter=execution.gateway,
        worker_id=str(
            values.get("NOVEL_FORGE_NARRATIVE_EVALUATION_WORKER_ID")
            or "narrative-semantic-evaluation-worker"
        ),
        max_cost_per_call=execution.max_cost_per_call,
        budget_caps=execution.budget_caps(),
        capability_binder=binder,
        execution_binding_domain="narrative_evaluation",
        fault_injector=post_provider_fault_injector,
    )
    return GatewayNarrativeSemanticEvaluationExecutionPort(
        settings.database_url,
        model_port=model_port,
    )


def build_model_reference_execution_port(
    settings: IndustrialSettings, *, execution: ProductionExecutionComposition,
    env: Mapping[str, str] | None = None,
):
    """CONSTRAINT: model reference calls use the existing Gateway and validation Pack gate."""
    from novel_forge.modules.chapter_quality_authority.model_reference_execution import (
        ModelReferenceExecutionContractBinder, ModelReferenceExecutionPort,
    )

    if not settings.database_url:
        raise RuntimeError("PostgreSQL is required for model reference execution")
    values = os.environ if env is None else env
    runtime_environment = RuntimeEnvironment.parse(
        str(values.get("NOVEL_FORGE_ENVIRONMENT") or settings.environment))
    if runtime_environment is not execution.runtime_environment or runtime_environment.value != "validation":
        raise RuntimeError("model reference creation requires the validation runtime")
    if not {"model_reference_evaluate", "model_reference_adjudicate"}.issubset(execution.gateway.routes):
        raise RuntimeError("model reference creation requires explicit evaluator Provider/model routes")
    registered = execution.gateway.execution_binders.get("model_reference")
    if registered is None:
        binder = ModelReferenceExecutionContractBinder(settings.database_url,
            execution.gateway.routes,
            capability_pack_id=str(values.get("NOVEL_FORGE_CHAPTER_CAPABILITY_PACK_ID") or "chapter_generation_pack") + ".model_reference_creation",
            pack_environment="validation", pack_runtime_profile="validation",
            pack_release_channel=str(values.get("NOVEL_FORGE_RELEASE_CHANNEL") or "VALIDATION").upper(),
            pack_required=True)
        execution.gateway.register_execution_binder("model_reference", binder)
    elif isinstance(registered, ModelReferenceExecutionContractBinder):
        binder = registered
    else:
        raise RuntimeError("model reference execution binder domain is already owned")
    model_port = ExternalEffectChapterModelPort(settings.database_url,
        adapter=execution.gateway, worker_id="model-reference-worker",
        max_cost_per_call=execution.max_cost_per_call,
        budget_caps=execution.budget_caps(), capability_binder=binder,
        execution_binding_domain="model_reference")
    return ModelReferenceExecutionPort(settings.database_url, model_port=model_port)


def build_model_reference_creation_application(
    settings: IndustrialSettings, *, execution: ProductionExecutionComposition,
    env: Mapping[str, str] | None = None,
):
    """CONSTRAINT: creation remains diagnostic and inherits the governed execution composition."""
    from novel_forge.modules.chapter_quality_authority.model_reference_execution import ModelReferenceCreationApplication

    values = os.environ if env is None else env
    build_id, commit_sha = authority_release_identity(env=values)
    return ModelReferenceCreationApplication(settings.database_url,
        application_build_id=build_id, commit_sha=commit_sha,
        execution_port=build_model_reference_execution_port(settings,
            execution=execution, env=values))


def build_story_planning_generation_application(
    settings: IndustrialSettings,
    *,
    execution: ProductionExecutionComposition,
    env: Mapping[str, str] | None = None,
    post_provider_fault_injector: Callable[[str], None] | None = None,
) -> StoryPlanningGenerationApplication:

    if not settings.database_url:
        raise RuntimeError("PostgreSQL database is required for Story Planning")
    values = os.environ if env is None else env
    build_id, commit_sha = authority_release_identity(env=values)
    transport = execution.gateway
    worker_id = str(
        values.get("NOVEL_FORGE_STORY_PLANNING_WORKER_ID")
        or "story-planning-generation-worker"
    )
    runtime_environment = RuntimeEnvironment.parse(
        str(values.get("NOVEL_FORGE_ENVIRONMENT") or settings.environment)
    )
    if runtime_environment is not execution.runtime_environment:
        raise RuntimeError("Planning and Production Execution environments must match")
    environment = runtime_environment.value
    base_route = transport.routes["draft"]
    planning_model = str(values.get("NOVEL_FORGE_PLANNING_MODEL") or "").strip()
    planning_reasoning_effort = (
        str(values.get("NOVEL_FORGE_PLANNING_REASONING_EFFORT") or "").strip().lower()
    )
    planning_provider = (
        str(values.get("NOVEL_FORGE_PLANNING_PROVIDER") or "").strip().lower()
    )
    if transport.provider_router is not None:
        planning_model = base_route.model_profile.model_id
        planning_reasoning_effort = base_route.model_profile.reasoning_effort
        planning_provider = base_route.model_profile.model_provider
    if runtime_environment.controlled:
        if not planning_model or not planning_reasoning_effort or not planning_provider:
            raise RuntimeError(
                "controlled Planning requires explicit Provider, model, and reasoning effort"
            )
    planning_model = planning_model or base_route.model_profile.model_id
    planning_reasoning_effort = (
        planning_reasoning_effort or base_route.model_profile.reasoning_effort
    )
    planning_provider = planning_provider or base_route.model_profile.model_provider
    if planning_provider != base_route.model_profile.model_provider:
        raise RuntimeError(
            "Planning Provider must use the shared Production Execution Gateway backend"
        )
    planning_model_capability_bound = (
        planning_model == base_route.model_profile.model_id
        or (
            base_route.model_profile.backend_id == "scripted-fixture"
            and base_route.model_profile.runtime_class
            is ExecutionRuntimeClass.SCRIPTED_FIXTURE
        )
    )
    planning_definition = default_capability_registry().resolve(
        "planning.book.generate"
    )
    planning_profile = ModelProfile(
        profile_id="story-planning.default",
        profile_version=1,
        backend_id=base_route.model_profile.backend_id,
        runtime_class=base_route.model_profile.runtime_class,
        model_provider=planning_provider,
        model_id=planning_model,
        reasoning_effort=planning_reasoning_effort,
        timeout_policy_ref=planning_definition.timeout_policy_ref,
        workspace_policy_ref="workspace:story-planning:v1",
        output_policy_ref="output:story-planning:structured:v1",
        fallback_policy="FAIL_CLOSED",
        status=ModelProfileStatus.ACTIVE if planning_model_capability_bound else ModelProfileStatus.CANDIDATE,
        capability_probe_ref=base_route.model_profile.capability_probe_ref if planning_model_capability_bound else "",
    )
    planning_policy = RoutePolicy(
        policy_id="story-planning.route",
        policy_version=1,
        default_model_profile_id=planning_profile.profile_id,
        allowed_model_profile_ids=(planning_profile.profile_id,),
        rule_set_ref="route-rules:story-planning:v1",
        fallback_policy="FAIL_CLOSED",
        fallback_policy_ref="story-planning.fail-closed",
        fallback_policy_version=1,
        reasoning_downgrade_policy="PROHIBITED",
        status="ACTIVE",
    )
    planning_fallback = FallbackPolicy.fail_closed(
        planning_policy.fallback_policy_ref,
        planning_policy.fallback_policy_version,
    )
    planning_route = PlanningExecutionRoute(
        model_profile=planning_profile,
        route_policy=planning_policy,
        fallback_policy=planning_fallback,
        backend_version=base_route.backend_version,
        runtime_host_id=base_route.runtime_host_id,
        auth_profile_ref=base_route.auth_profile_ref,
        release_sha=base_route.release_sha,
        model_context_limit=base_route.model_context_limit if planning_model_capability_bound else 0,
        model_output_limit=base_route.model_output_limit if planning_model_capability_bound else 0,
        token_accounting_method=base_route.token_accounting_method if planning_model_capability_bound else "",
        token_accounting_evidence_ref=base_route.token_accounting_evidence_ref if planning_model_capability_bound else "",
        token_safety_margin=base_route.token_safety_margin,
        token_framing_overhead=base_route.token_framing_overhead,
    )
    preparer = PostgresPlanningExecutionPreparer(
        settings.database_url,
        execution_transport=transport,
        planning_route=planning_route,
        worker_id=worker_id,
        max_cost_per_call=execution.max_cost_per_call,
        budget_caps=execution.budget_caps(),
        post_provider_fault_injector=post_provider_fault_injector,
    )
    resolver = PostgresPlanningExecutionBundleResolver(
        settings.database_url,
        execution_preparer=preparer,
        workflow_definition_ref=STORY_PLANNING_WORKFLOW_DEFINITION_REF,
        pack_id=str(
            values.get("NOVEL_FORGE_PLANNING_CAPABILITY_PACK_ID")
            or "story_planning_pack"
        ),
        environment=environment,
        runtime_profile=environment,
        release_channel=str(
            values.get("NOVEL_FORGE_RELEASE_CHANNEL") or "VALIDATION"
        ).upper(),
        release_sha=commit_sha,
    )
    return StoryPlanningGenerationApplication(
        settings.database_url,
        execution_binder=CapabilityPackBackedPlanningExecutionBinder(resolver),
        application_build_id=build_id,
        commit_sha=commit_sha,
        worker_id=worker_id,
        semantic_evaluation_execution_port=(
            build_narrative_semantic_evaluation_execution_port(
                settings,
                execution=execution,
                env=values,
            )
        ),
        allow_scripted_evaluation_fixture=(
            _scripted_narrative_evaluation_fixture_enabled(runtime_environment, values)
        ),
        narrative_evaluator_principal=(
            build_trusted_principal_resolver(
                env=values
            ).resolve_narrative_evaluator_principal()
        ),
    )


__all__ = [
    "authority_release_identity",
    "build_production_execution_composition",
    "build_chapter_authority_application",
    "build_chapter_authority_query",
    "chapter_capability_pack_compilation_report",
    "build_production_preparation_service",
    "build_trusted_principal_resolver",
    "build_content_authority_application",
    "build_content_authority_query",
    "build_book_authority_application",
    "build_book_followup_authority_application",
    "build_book_production_composition",
    "build_reader_outcome_model_port",
    "build_narrative_semantic_evaluation_execution_port",
    "build_model_reference_execution_port",
    "build_model_reference_creation_application",
    "build_story_planning_generation_application",
    "build_capability_pack_authority_application",
    "build_capability_pack_authority_query",
    "build_quality_qualification_authority",
]


def _build_corpus_acquisition_adapter(git_adapter: Any, values: Mapping[str, str]) -> Any:
    from novel_forge.modules.source_import.corpus_ingestion.acquisition import CorpusAcquisitionAdapter
    from novel_forge.modules.source_import.corpus_ingestion.http_transport import CorpusHttpTransport
    root = str(values.get("NOVEL_FORGE_CORPUS_CACHE_ROOT") or "").strip()
    if not root:
        return None
    path = Path(root).expanduser()
    if not path.is_absolute():
        raise ValueError("Corpus cache must be an explicit absolute directory outside the source checkout")
    if any((parent / ".git").exists() for parent in (path.resolve(), *path.resolve().parents)):
        raise ValueError("Corpus cache cannot be inside a Git checkout")
    local_roots = json.loads(str(values.get("NOVEL_FORGE_CORPUS_LOCAL_ROOTS") or "[]"))
    if not isinstance(local_roots, list) or any(not isinstance(item, str) or not Path(item).expanduser().is_absolute() for item in local_roots):
        raise ValueError("Corpus local roots must be a JSON list of absolute paths")
    return CorpusAcquisitionAdapter(path, local_roots=tuple(Path(item) for item in local_roots), git_adapter=git_adapter,
        http=CorpusHttpTransport(token=str(values.get("HF_TOKEN") or "")))

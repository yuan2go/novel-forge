"""Fail-closed dependency construction for PostgreSQL authority entrypoints."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Mapping

from novel_forge.infrastructure.environment import RuntimeEnvironment
from novel_forge.infrastructure.production_execution_composition import (
    ProductionExecutionComposition,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.chapter_authority.application import (
    ChapterAuthorityApplication,
)
from novel_forge.modules.chapter_authority.execution_gateway import (
    ChapterExecutionGatewaySession,
    ChapterExecutionRoute,
    PostgresChapterExecutionContractBinder,
    PostgresProductionExecutionPayloadResolver,
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
    STORY_PLANNING_WORKFLOW_DEFINITION_REF,
    StoryPlanningGenerationApplication,
)
from novel_forge.modules.story_planning_runtime.execution import (
    planning_fixture_response,
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
from novel_forge.modules.agent_runtime.chapter_binding import (
    AGENT_BOUND_CHAPTER_STAGES,
    PostgresChapterAgentBindingRecorder,
)
from novel_forge.modules.agent_runtime.execution import (
    ChapterGatewayAgentExecutionPreparer,
)
from novel_forge.modules.agent_runtime.queries import AgentRuntimeQuery
from novel_forge.modules.agent_runtime.scheduler import AgentAuthorityScheduler
from novel_forge.modules.capability_pack_authority.application import (
    CapabilityPackAuthorityApplication,
)
from novel_forge.modules.capability_pack_authority.query import (
    CapabilityPackAuthorityQuery,
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
    normalize_provider_id,
)
from novel_forge.modules.provider_control.contracts import ProviderControlLevel
from novel_forge.modules.production_execution import (
    AdmissionController,
    AuthorityExecutionRecoveryStore,
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
)


_PACK_SKILL_FOR_STAGE = {
    "draft": "prose-generation",
    "revision": "prose-generation",
    "canon_extraction": "canon-continuity-graph",
    "review": "quality-review",
    "rereview": "quality-review",
    "quality_structural": "quality-review",
    "quality_commercial": "quality-review",
    "quality_source_originality": "quality-review",
    "quality_longform": "quality-review",
    "quality_platform": "quality-review",
    "reader_outcome": "quality-review",
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


def build_book_design_authority_application(
    settings: IndustrialSettings,
) -> BookDesignAuthorityApplication:
    if settings.storage_authority != "postgresql" or not settings.database_url:
        raise RuntimeError("BookDesign Authority requires PostgreSQL authority")
    build_id, commit_sha = authority_release_identity()
    return BookDesignAuthorityApplication(
        settings.database_url,
        application_build_id=build_id,
        commit_sha=commit_sha,
    )


def build_book_design_authority_query(
    settings: IndustrialSettings,
) -> BookDesignAuthorityQuery:
    if settings.storage_authority != "postgresql" or not settings.database_url:
        raise RuntimeError("BookDesign Authority requires PostgreSQL authority")
    return BookDesignAuthorityQuery(settings.database_url)


def build_production_execution_composition(
    settings: IndustrialSettings,
    *,
    env: Mapping[str, str] | None = None,
    provider_registry: ProviderAdapterRegistry | None = None,
) -> ProductionExecutionComposition:
    values = os.environ if env is None else env
    if not settings.database_url:
        raise RuntimeError("PostgreSQL database is required for chapter authority")
    runtime_environment = RuntimeEnvironment.parse(
        str(values.get("NOVEL_FORGE_ENVIRONMENT") or settings.environment)
    )
    environment = runtime_environment.value
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
    for stage, provider_key, model_key in (
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
            "reader_outcome",
            "NOVEL_FORGE_READER_OUTCOME_PROVIDER",
            "NOVEL_FORGE_READER_OUTCOME_MODEL",
        ),
    ):
        capability_definition = default_capability_registry().resolve(
            chapter_stage_capability(stage)
        )
        provider = str(
            values.get(provider_key)
            or (
                values.get("NOVEL_FORGE_REVIEW_PROVIDER")
                if stage == "rereview"
                else values.get("NOVEL_FORGE_REVISION_PROVIDER")
                if stage == "canon_extraction"
                else values.get("NOVEL_FORGE_REVIEW_PROVIDER")
                if stage.startswith("quality_") or stage == "reader_outcome"
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
                if stage == "rereview"
                else values.get("NOVEL_FORGE_REVISION_MODEL")
                if stage == "canon_extraction"
                else values.get("NOVEL_FORGE_REVIEW_MODEL")
                if stage.startswith("quality_") or stage == "reader_outcome"
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
        profile_id = f"chapter.{stage}.default"
        profile = ModelProfile(
            profile_id=profile_id,
            profile_version=1,
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
            policy_id=f"chapter.{stage}.route",
            policy_version=1,
            default_model_profile_id=profile_id,
            allowed_model_profile_ids=(profile_id,),
            rule_set_ref=f"route-rules:chapter:{stage}:v1",
            fallback_policy="FAIL_CLOSED",
            fallback_policy_ref=f"chapter.{stage}.fail-closed",
            fallback_policy_version=1,
            reasoning_downgrade_policy="PROHIBITED",
            status="ACTIVE",
        )
        fallback_policy = FallbackPolicy.fail_closed(
            policy.fallback_policy_ref,
            policy.fallback_policy_version,
        )
        if codex_cli and repository_artifacts is not None:
            system_artifact = repository_artifacts.resolve(
                ArtifactKind.PROMPT_SYSTEM_INSTRUCTION,
                "prompt-system:chapter-generation-pack",
                "v1",
            )
            template_artifact = repository_artifacts.resolve(
                ArtifactKind.PROMPT_TEMPLATE,
                "prompt-template:chapter-generation-pack",
                "v1",
            )
            skill_artifact = next(
                item
                for item in repository_artifacts.artifacts()
                if item.kind is ArtifactKind.SKILL
                and item.ref == _PACK_SKILL_FOR_STAGE[stage]
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
            prompt_compiler_version=str(
                values.get("NOVEL_FORGE_PROMPT_COMPILER_VERSION")
                or "chapter-prompt-compiler:v1"
            ),
            output_schema_ref=capability_definition.output_schema_ref,
            release_sha=release_sha,
            real_provider_validation_eligible=real_provider_eligible,
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
    if codex_models:
        if len(codex_models) != 1:
            raise RuntimeError("this phase requires one explicit Codex model")
        if any(
            route.model_profile.runtime_class
            is not ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE
            for route in routes.values()
        ):
            raise RuntimeError(
                "mixed Codex and alternate Provider routing is not supported in this phase"
            )
    object_root_value = str(
        values.get("NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT") or ""
    ).strip()
    if not object_root_value:
        raise RuntimeError("explicit authority object-store root is required")
    max_cost_per_call = str(
        values.get("NOVEL_FORGE_PROVIDER_MAX_COST_PER_CALL") or ""
    ).strip()
    if controlled:
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
    codex_workspace: Path | None = None
    codex_execution_root: Path | None = None
    codex_pricing: CodexPricingSnapshot | None = None
    codex_model = next(iter(codex_models), "")
    if codex_models:
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

    def validate_codex_result(
        stage: str,
        output_schema: Mapping[str, object],
        value: Mapping[str, object],
    ) -> Mapping[str, object]:
        if stage in {
            CLASSIFICATION_STAGE,
            DECONSTRUCTION_STAGE,
            MKAOS_STAGE,
        }:
            return validate_content_intelligence_output(stage, output_schema, value)
        validated = validate_chapter_provider_output_against_schema(
            stage,
            output_schema,
            value,
        )
        if stage in {
            "book_plan.generate",
            "volume_plan.generate",
            "arc_plan.generate",
            "chapter_group_plan.generate",
            "chapter_plan.generate",
        }:
            return validated
        semantic = validate_chapter_provider_output_semantics(stage, validated)
        return normalize_model_output(stage, semantic)

    def fixture_response(stage: str, inputs: Mapping[str, object]) -> dict[str, object]:
        if stage in {
            CLASSIFICATION_STAGE,
            DECONSTRUCTION_STAGE,
            MKAOS_STAGE,
        }:
            return content_intelligence_fixture_response(stage, inputs)
        if stage in {
            "book_plan.generate",
            "volume_plan.generate",
            "arc_plan.generate",
            "chapter_group_plan.generate",
            "chapter_plan.generate",
        }:
            return planning_fixture_response(stage, inputs)
        return default_chapter_fixture_response(stage, inputs)

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
            assert codex_pricing is not None
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
                    pricing=codex_pricing,
                    structured_result_validator=validate_codex_result,
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
                )
            )
        gateway = ProductionExecutionGateway(backends, admission)
        return ChapterExecutionGatewaySession(gateway, store)

    model_gateway = ProductionExecutionGatewayExternalEffectAdapter(
        database_url=settings.database_url,
        routes=routes,
        session_factory=execution_session,
        provider_adapters={
            adapter.provider: adapter for adapter in provider_adapters.values()
        },
    )
    shared_budget_caps = {
        key: str(values[value])
        for key, value in (
            ("project_daily", "NOVEL_FORGE_PROJECT_DAILY_PROVIDER_CAP"),
            ("operation_total", "NOVEL_FORGE_OPERATION_PROVIDER_CAP"),
            ("provider_project_daily", "NOVEL_FORGE_PROVIDER_DAILY_CAP"),
            ("global_daily", "NOVEL_FORGE_DAILY_PROVIDER_CAP"),
        )
        if str(values.get(value) or "").strip()
    }
    return ProductionExecutionComposition(
        gateway=model_gateway,
        object_store=object_store_adapter,
        source_object_reader=source_object_reader,
        runtime_environment=runtime_environment,
        max_cost_per_call=max_cost_per_call or "0",
        shared_budget_caps=shared_budget_caps,
        chapter_total_budget_cap=str(
            values.get("NOVEL_FORGE_CHAPTER_PROVIDER_CAP") or ""
        ).strip(),
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
    return ChapterAuthorityApplication(
        settings.database_url,
        model_adapter=execution.gateway,
        object_store_adapter=execution.object_store,
        capability_binder=binder,
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
        agent_binding_recorder=PostgresChapterAgentBindingRecorder(
            settings.database_url,
            bound_stages=AGENT_BOUND_CHAPTER_STAGES,
            required_stages=(AGENT_BOUND_CHAPTER_STAGES if controlled else frozenset()),
            compatibility_allowed=not controlled,
            environment=environment,
            runtime_profile=environment,
            release_channel=str(
                values.get("NOVEL_FORGE_RELEASE_CHANNEL") or "VALIDATION"
            ).upper(),
            capability_pack_id=str(
                values.get("NOVEL_FORGE_CHAPTER_CAPABILITY_PACK_ID")
                or "chapter_generation_pack"
            ),
            fault_injector=runtime_fault_injector,
        ),
        agent_binding_required=controlled,
        runtime_fault_injector=runtime_fault_injector,
    )


def build_agent_runtime_authority_application(
    settings: IndustrialSettings,
    *,
    env: Mapping[str, str] | None = None,
) -> AgentRuntimeAuthorityApplication:
    if settings.storage_authority != "postgresql" or not settings.database_url:
        raise RuntimeError("Agent Runtime Authority requires PostgreSQL authority")
    build_id, commit_sha = authority_release_identity(env=env)
    values = os.environ if env is None else env
    return AgentRuntimeAuthorityApplication(
        settings.database_url,
        application_build_id=build_id,
        commit_sha=commit_sha,
        runtime_environment=RuntimeEnvironment.parse(
            str(values.get("NOVEL_FORGE_ENVIRONMENT") or settings.environment)
        ).value,
        release_channel=str(values.get("NOVEL_FORGE_RELEASE_CHANNEL") or "VALIDATION"),
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
    return AgentAuthorityScheduler(
        settings.database_url,
        execution_preparer=preparer,
        worker_id=worker_id,
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
    """Compose Source Import as a peer consumer of the shared PEP."""

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
    )
    return SourceImportApplication(
        settings.database_url,
        application_build_id=build_id,
        commit_sha=commit_sha,
        worker_id=worker_id,
        git_adapter=git_adapter,
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
    """Compile the shipped Chapter Pack from repository facts without activation."""

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
    reader_model_port = build_reader_outcome_model_port(
        settings,
        execution=execution,
        env=env,
    )
    followup = BookFollowupAuthorityApplication(
        settings.database_url,
        application_build_id=build_id,
        commit_sha=commit_sha,
        model_port=reader_model_port,
        worker_id=str(
            (os.environ if env is None else env).get(
                "NOVEL_FORGE_BOOK_FOLLOWUP_WORKER_ID"
            )
            or "book-followup-authority-worker"
        ),
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


def build_book_production_composition(
    settings: IndustrialSettings,
    *,
    principal: Principal,
    execution: ProductionExecutionComposition,
    chapter_application: ChapterAuthorityApplication,
    env: Mapping[str, str] | None = None,
) -> BookProductionComposition:
    """Build the one Book production graph consumed by API and Worker."""

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
    )
    replan = BookReplanCoordinator(
        settings.database_url,
        book_authority=authority,
        planning=planning,
        plan_change=plan_change,
        input_resolver=input_resolver,
        principal=principal,
    )
    supervisor = PostgresBookProductionSupervisor(
        authority,
        planning=planning,
        chapter_groups=chapter_groups,
        principal=principal,
        replan=replan,
        production_preparation=preparation,
        context_token_budget=int(
            values.get("NOVEL_FORGE_BOOK_CONTEXT_TOKEN_BUDGET") or 16_000
        ),
        quality_context_token_budget=int(
            values.get("NOVEL_FORGE_BOOK_QUALITY_CONTEXT_TOKEN_BUDGET")
            or values.get("NOVEL_FORGE_BOOK_CONTEXT_TOKEN_BUDGET")
            or 16_000
        ),
    )
    return BookProductionComposition(
        authority=authority,
        planning=planning,
        chapter_groups=chapter_groups,
        production_preparation=preparation,
        followup=authority.followup,
        plan_change=plan_change,
        input_resolver=input_resolver,
        replan=replan,
        supervisor=supervisor,
        principal=principal,
    )


def build_reader_outcome_model_port(
    settings: IndustrialSettings,
    *,
    execution: ProductionExecutionComposition,
    env: Mapping[str, str] | None = None,
) -> ExternalEffectChapterModelPort:
    """Compose Reader Outcome with a Reader-owned Pack binder and shared PEP."""

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


def build_story_planning_generation_application(
    settings: IndustrialSettings,
    *,
    execution: ProductionExecutionComposition,
    env: Mapping[str, str] | None = None,
    post_provider_fault_injector: Callable[[str], None] | None = None,
) -> StoryPlanningGenerationApplication:
    """Compose Story Planning as a peer consumer of the shared PEP."""

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
        status=ModelProfileStatus.ACTIVE,
        capability_probe_ref=base_route.model_profile.capability_probe_ref,
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
    "build_book_production_composition",
    "build_reader_outcome_model_port",
    "build_story_planning_generation_application",
    "build_capability_pack_authority_application",
    "build_capability_pack_authority_query",
]

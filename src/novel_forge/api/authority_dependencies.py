"""Fail-closed dependency construction for PostgreSQL authority entrypoints."""
from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from typing import Mapping

from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.chapter_authority.application import ChapterAuthorityApplication
from novel_forge.modules.chapter_authority.execution_gateway import (
    ChapterExecutionGatewaySession,
    ChapterExecutionRoute,
    ExternalEffectExecutionSessionStore,
    PostgresChapterExecutionPayloadResolver,
    ProductionExecutionGatewayExternalEffectAdapter,
    default_chapter_fixture_response,
)
from novel_forge.modules.chapter_authority.queries import ChapterAuthorityQuery
from novel_forge.modules.authority_security import TrustedPrincipalResolver
from novel_forge.modules.command_kernel.external_effect_adapters import (
    LocalFileObjectStoreAdapter,
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
    ScriptedProviderAdapterV2,
)
from novel_forge.modules.provider_control.contracts import ProviderControlLevel
from novel_forge.modules.production_execution import (
    AdmissionController,
    CompletionMode,
    ExecutionBackendRegistry,
    ExecutionCapabilityProfile,
    ExecutionRuntimeClass,
    ModelProfile,
    ModelProfileStatus,
    PostgresAttemptFenceVerifier,
    PostgresExecutionContractSource,
    ProductionExecutionGateway,
    RemoteProviderExecutionBackend,
    RoutePolicy,
    ScriptedFixtureExecutionBackend,
)


def authority_release_identity(
    *, env: Mapping[str, str] | None = None
) -> tuple[str, str]:
    values = env or os.environ
    build_id = str(values.get("NOVEL_FORGE_APPLICATION_BUILD_ID") or "").strip()
    commit_sha = str(values.get("NOVEL_FORGE_COMMIT_SHA") or "").strip().lower()
    if not build_id:
        raise RuntimeError("NOVEL_FORGE_APPLICATION_BUILD_ID is required")
    if len(commit_sha) != 40 or any(
        character not in "0123456789abcdef" for character in commit_sha
    ):
        raise RuntimeError("NOVEL_FORGE_COMMIT_SHA must be a full 40-character hexadecimal commit id")
    return build_id, commit_sha


def build_chapter_authority_application(
    settings: IndustrialSettings,
    *,
    env: Mapping[str, str] | None = None,
    provider_registry: ProviderAdapterRegistry | None = None,
) -> ChapterAuthorityApplication:
    values = env or os.environ
    if not settings.database_url:
        raise RuntimeError("PostgreSQL database is required for chapter authority")
    environment = str(values.get("NOVEL_FORGE_ENVIRONMENT") or "development").strip().lower()
    registry = provider_registry or ProviderAdapterRegistry()
    if provider_registry is None and environment in {"test", "development"}:
        registry.register(ScriptedProviderAdapterV2("success"))
    controlled = environment in {"validation", "provider-validation", "production"}
    if controlled:
        release_sha = str(values.get("NOVEL_FORGE_COMMIT_SHA") or "0" * 40).lower()
    else:
        release_sha = str(values.get("NOVEL_FORGE_COMMIT_SHA") or "0" * 40).lower()
        if len(release_sha) != 40:
            raise RuntimeError("NOVEL_FORGE_COMMIT_SHA must be a full 40-character commit id")
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
        ("quality_structural", "NOVEL_FORGE_QUALITY_PROVIDER", "NOVEL_FORGE_QUALITY_MODEL"),
        ("quality_commercial", "NOVEL_FORGE_QUALITY_PROVIDER", "NOVEL_FORGE_QUALITY_MODEL"),
        ("quality_source_originality", "NOVEL_FORGE_QUALITY_PROVIDER", "NOVEL_FORGE_QUALITY_MODEL"),
        ("quality_longform", "NOVEL_FORGE_QUALITY_PROVIDER", "NOVEL_FORGE_QUALITY_MODEL"),
        ("quality_platform", "NOVEL_FORGE_QUALITY_PROVIDER", "NOVEL_FORGE_QUALITY_MODEL"),
    ):
        provider = str(
            values.get(provider_key)
            or (
                values.get("NOVEL_FORGE_REVIEW_PROVIDER")
                if stage == "rereview"
                else
                values.get("NOVEL_FORGE_REVISION_PROVIDER")
                if stage == "canon_extraction"
                else values.get("NOVEL_FORGE_REVIEW_PROVIDER")
                if stage.startswith("quality_")
                else ""
            )
            or values.get("NOVEL_FORGE_MODEL_PROVIDER")
            or ""
        ).strip()
        if not provider:
            raise RuntimeError(f"explicit chapter model provider is required for {stage}")
        normalized_provider = provider.lower()
        if normalized_provider in {"mock", "local", "offline"}:
            normalized_provider = "scripted_provider_v2"
        model_name = str(
            values.get(model_key)
            or (
                values.get("NOVEL_FORGE_REVIEW_MODEL")
                if stage == "rereview"
                else
                values.get("NOVEL_FORGE_REVISION_MODEL")
                if stage == "canon_extraction"
                else values.get("NOVEL_FORGE_REVIEW_MODEL")
                if stage.startswith("quality_")
                else ""
            )
            or ""
        ).strip()
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
                "provider v2 route qualification failed: " + "; ".join(qualification.reasons)
            )
        provider_profile = adapter.capability_profile
        scripted = provider_profile.control_level is ProviderControlLevel.FIXTURE_CONTROLLED
        backend_id = (
            "scripted-fixture"
            if scripted
            else "remote-provider-" + adapter.provider.replace("_", "-")
        )
        qualification_ref = (
            "capability-probe:scripted-fixture:1"
            if scripted
            else f"capability-probe:{adapter.provider}:{provider_profile.contract_version}"
        )
        backend_version = "1.0.0"
        if not scripted:
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
            runtime_class=(
                ExecutionRuntimeClass.SCRIPTED_FIXTURE
                if scripted
                else ExecutionRuntimeClass.REMOTE_PROVIDER_API
            ),
            model_provider=adapter.provider,
            model_id=resolved_model,
            reasoning_effort=str(
                values.get(f"NOVEL_FORGE_{stage.upper()}_REASONING_EFFORT")
                or values.get("NOVEL_FORGE_REASONING_EFFORT")
                or "high"
            ),
            timeout_policy_ref=f"timeout:chapter:{stage}:v1",
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
            reasoning_downgrade_policy="PROHIBITED",
            status="ACTIVE",
        )
        routes[stage] = ChapterExecutionRoute(
            stage=stage,
            model_profile=profile,
            route_policy=policy,
            backend_version=backend_version,
            runtime_host_id=runtime_host_id,
            auth_profile_ref=auth_profile_ref,
            prompt_bundle_ref=str(
                values.get(f"NOVEL_FORGE_{stage.upper()}_PROMPT_VERSION")
                or f"chapter-{stage}-prompt-v1"
            ),
            skill_bundle_ref=str(
                values.get(f"NOVEL_FORGE_{stage.upper()}_SKILL_VERSION")
                or f"chapter-{stage}-skill-v1"
            ),
            output_schema_ref=f"chapter-{stage}.v1",
            release_sha=release_sha,
            real_provider_validation_eligible=(
                provider_profile.real_provider_validation_eligible
            ),
        )
    if controlled:
        _build_id, verified_release_sha = authority_release_identity(env=values)
        verified_runtime_host = str(values.get("NOVEL_FORGE_RUNTIME_HOST_ID") or "").strip()
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
    object_root_value = str(
        values.get("NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT") or ""
    ).strip()
    if not object_root_value:
        raise RuntimeError("explicit authority object-store root is required")
    max_cost_per_call = str(
        values.get("NOVEL_FORGE_PROVIDER_MAX_COST_PER_CALL") or ""
    ).strip()
    if environment in {"validation", "provider-validation", "production"}:
        if not max_cost_per_call:
            raise RuntimeError(
                "NOVEL_FORGE_PROVIDER_MAX_COST_PER_CALL is required for production providers"
            )
    object_root = Path(object_root_value).expanduser()
    if not object_root.is_absolute():
        object_root = settings.root / object_root

    def execution_session(project_id: str) -> ChapterExecutionGatewaySession:
        contracts = PostgresExecutionContractSource(
            settings.database_url, project_id=project_id
        )
        admission = AdmissionController(
            contracts,
            PostgresAttemptFenceVerifier(settings.database_url),
        )
        store = ExternalEffectExecutionSessionStore()
        backends = ExecutionBackendRegistry()
        if any(
            route.model_profile.runtime_class
            is ExecutionRuntimeClass.SCRIPTED_FIXTURE
            for route in routes.values()
        ):
            backends.register(
                ScriptedFixtureExecutionBackend(
                    admission=admission,
                    payload_resolver=PostgresChapterExecutionPayloadResolver(
                        settings.database_url,
                        fixture_response_factory=default_chapter_fixture_response,
                        working_directory=settings.root,
                    ),
                    record_store=store,
                )
            )
        for backend_id, adapter in provider_adapters.items():
            backends.register(
                RemoteProviderExecutionBackend(
                    backend_id=backend_id,
                    capability_profile=backend_capabilities[backend_id],
                    provider_adapter=adapter,
                    admission=admission,
                    payload_resolver=PostgresChapterExecutionPayloadResolver(
                        settings.database_url,
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
    return ChapterAuthorityApplication(
        settings.database_url,
        model_adapter=model_gateway,
        object_store_adapter=LocalFileObjectStoreAdapter(object_root),
        worker_id=str(values.get("NOVEL_FORGE_AUTHORITY_WORKER_ID") or "chapter-authority-api"),
        allow_synchronous_fixture=environment in {"test", "development"}
        and str(values.get("NOVEL_FORGE_ENABLE_SYNCHRONOUS_AUTHORITY_FIXTURE") or "").lower()
        in {"1", "true", "yes"},
        max_cost_per_model_call=max_cost_per_call or "0",
        budget_caps={
            key: str(values[value])
            for key, value in (
                ("project_daily", "NOVEL_FORGE_PROJECT_DAILY_PROVIDER_CAP"),
                ("operation_total", "NOVEL_FORGE_OPERATION_PROVIDER_CAP"),
                ("provider_project_daily", "NOVEL_FORGE_PROVIDER_DAILY_CAP"),
                ("global_daily", "NOVEL_FORGE_DAILY_PROVIDER_CAP"),
                ("chapter_total", "NOVEL_FORGE_CHAPTER_PROVIDER_CAP"),
            )
            if str(values.get(value) or "").strip()
        },
    )


def build_production_preparation_service(
    settings: IndustrialSettings,
) -> ProductionPreparationService:
    if not settings.database_url:
        raise RuntimeError("PostgreSQL database is required for production preparation")
    return ProductionPreparationService(PostgresProductionAssetResolver(settings.database_url))


def build_trusted_principal_resolver(
    *, env: Mapping[str, str] | None = None,
) -> TrustedPrincipalResolver:
    return TrustedPrincipalResolver.from_environment(env or os.environ)


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


def build_content_authority_query(settings: IndustrialSettings) -> ContentAuthorityQuery:
    if not settings.database_url:
        raise RuntimeError("PostgreSQL database is required for Content Authority")
    return ContentAuthorityQuery(settings.database_url)


def build_chapter_authority_query(settings: IndustrialSettings) -> ChapterAuthorityQuery:
    if not settings.database_url:
        raise RuntimeError("PostgreSQL database is required for chapter authority")
    return ChapterAuthorityQuery(settings.database_url)


__all__ = [
    "authority_release_identity",
    "build_chapter_authority_application",
    "build_chapter_authority_query",
    "build_production_preparation_service",
    "build_trusted_principal_resolver",
    "build_content_authority_application",
    "build_content_authority_query",
]

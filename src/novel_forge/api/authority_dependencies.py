"""Fail-closed dependency construction for PostgreSQL authority entrypoints."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.chapter_authority.application import ChapterAuthorityApplication
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
    ChapterProviderV2Gateway,
    ChapterProviderV2Route,
    ProviderAdapterRegistry,
    ProviderRouteDefinition,
    ScriptedProviderAdapterV2,
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
    routes: dict[str, ChapterProviderV2Route] = {}
    for stage, provider_key, model_key in (
        ("draft", "NOVEL_FORGE_DRAFT_PROVIDER", "NOVEL_FORGE_DRAFT_MODEL"),
        ("review", "NOVEL_FORGE_REVIEW_PROVIDER", "NOVEL_FORGE_REVIEW_MODEL"),
        ("revision", "NOVEL_FORGE_REVISION_PROVIDER", "NOVEL_FORGE_REVISION_MODEL"),
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
        definition = ProviderRouteDefinition(
            stage=stage,
            provider_id=adapter.provider,
            model_id=resolved_model,
            adapter_contract_version=adapter.capability_profile.contract_version,
            prompt_version=str(
                values.get(f"NOVEL_FORGE_{stage.upper()}_PROMPT_VERSION")
                or f"chapter-{stage}-prompt-v1"
            ),
            skill_version=str(
                values.get(f"NOVEL_FORGE_{stage.upper()}_SKILL_VERSION")
                or f"chapter-{stage}-skill-v1"
            ),
            timeout_seconds=int(
                values.get(f"NOVEL_FORGE_{stage.upper()}_TIMEOUT_SECONDS") or 300
            ),
            environment=environment,
            idempotency_policy=(
                "provider" if adapter.capability_profile.supports_provider_idempotency
                else "unsupported"
            ),
            query_policy=("query" if adapter.capability_profile.supports_query else "unsupported"),
            cancel_policy=("cancel" if adapter.capability_profile.supports_cancel else "unsupported"),
            callback_policy=("callback" if adapter.capability_profile.supports_callback else "unsupported"),
            usage_receipt_policy=("required" if adapter.capability_profile.supports_usage_receipt else "unsupported"),
            cost_receipt_policy=("required" if adapter.capability_profile.supports_cost_receipt else "unsupported"),
        )
        routes[stage] = ChapterProviderV2Route(definition=definition, adapter=adapter)
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
    return ChapterAuthorityApplication(
        settings.database_url,
        model_adapter=ChapterProviderV2Gateway(routes),
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

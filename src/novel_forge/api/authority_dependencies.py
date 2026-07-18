"""Fail-closed dependency construction for PostgreSQL authority entrypoints."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.model_adapters.selection import model_for_explicit_route
from novel_forge.modules.chapter_authority.application import ChapterAuthorityApplication
from novel_forge.modules.chapter_authority.model_effects import (
    ChapterModelExternalEffectAdapter,
    ChapterModelRoute,
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


def authority_release_identity(
    *, env: Mapping[str, str] | None = None
) -> tuple[str, str]:
    values = env or os.environ
    build_id = str(values.get("NOVEL_FORGE_APPLICATION_BUILD_ID") or "").strip()
    commit_sha = str(values.get("NOVEL_FORGE_COMMIT_SHA") or "").strip().lower()
    if not build_id:
        raise RuntimeError("NOVEL_FORGE_APPLICATION_BUILD_ID is required")
    if len(commit_sha) < 7 or len(commit_sha) > 64 or any(
        character not in "0123456789abcdef" for character in commit_sha
    ):
        raise RuntimeError("NOVEL_FORGE_COMMIT_SHA must be a 7-64 character hexadecimal commit id")
    return build_id, commit_sha


def build_chapter_authority_application(
    settings: IndustrialSettings,
    *,
    env: Mapping[str, str] | None = None,
) -> ChapterAuthorityApplication:
    values = env or os.environ
    if not settings.database_url:
        raise RuntimeError("PostgreSQL database is required for chapter authority")
    environment = str(values.get("NOVEL_FORGE_ENVIRONMENT") or "development").strip().lower()
    routes: dict[str, ChapterModelRoute] = {}
    for stage, provider_key, model_key in (
        ("draft", "NOVEL_FORGE_DRAFT_PROVIDER", "NOVEL_FORGE_DRAFT_MODEL"),
        ("review", "NOVEL_FORGE_REVIEW_PROVIDER", "NOVEL_FORGE_REVIEW_MODEL"),
        ("revision", "NOVEL_FORGE_REVISION_PROVIDER", "NOVEL_FORGE_REVISION_MODEL"),
    ):
        provider = str(
            values.get(provider_key)
            or values.get("NOVEL_FORGE_MODEL_PROVIDER")
            or ""
        ).strip()
        if not provider:
            raise RuntimeError(f"explicit chapter model provider is required for {stage}")
        normalized_provider = provider.lower()
        real_model_call = normalized_provider not in {"mock", "local", "offline"}
        if environment == "production" and not real_model_call:
            raise RuntimeError("mock model routes are forbidden in production chapter authority")
        model_name = str(values.get(model_key) or "").strip()
        adapter = model_for_explicit_route(provider, model_name)
        resolved_model = model_name or str(getattr(adapter, "name", "")) or f"{provider}-{stage}"
        routes[stage] = ChapterModelRoute(
            adapter=adapter,
            provider_id=normalized_provider,
            model_id=resolved_model,
            prompt_version=str(
                values.get(f"NOVEL_FORGE_{stage.upper()}_PROMPT_VERSION")
                or f"chapter-{stage}-prompt-v1"
            ),
            skill_version=str(
                values.get(f"NOVEL_FORGE_{stage.upper()}_SKILL_VERSION")
                or f"chapter-{stage}-skill-v1"
            ),
            real_model_call=real_model_call,
        )
    object_root_value = str(
        values.get("NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT") or ""
    ).strip()
    if not object_root_value:
        raise RuntimeError("explicit authority object-store root is required")
    max_cost_per_call = str(
        values.get("NOVEL_FORGE_PROVIDER_MAX_COST_PER_CALL") or ""
    ).strip()
    if environment == "production" and any(route.real_model_call for route in routes.values()):
        if not max_cost_per_call:
            raise RuntimeError(
                "NOVEL_FORGE_PROVIDER_MAX_COST_PER_CALL is required for production providers"
            )
    object_root = Path(object_root_value).expanduser()
    if not object_root.is_absolute():
        object_root = settings.root / object_root
    return ChapterAuthorityApplication(
        settings.database_url,
        model_adapter=ChapterModelExternalEffectAdapter(routes),
        object_store_adapter=LocalFileObjectStoreAdapter(object_root),
        worker_id=str(values.get("NOVEL_FORGE_AUTHORITY_WORKER_ID") or "chapter-authority-api"),
        allow_synchronous_fixture=environment in {"test", "development"}
        and str(values.get("NOVEL_FORGE_ENABLE_SYNCHRONOUS_AUTHORITY_FIXTURE") or "").lower()
        in {"1", "true", "yes"},
        max_cost_per_model_call=max_cost_per_call or "0",
        budget_caps={
            key: str(values[value])
            for key, value in (
                ("project", "NOVEL_FORGE_PROJECT_DAILY_PROVIDER_CAP"),
                ("operation", "NOVEL_FORGE_OPERATION_PROVIDER_CAP"),
                ("provider", "NOVEL_FORGE_PROVIDER_DAILY_CAP"),
                ("daily", "NOVEL_FORGE_DAILY_PROVIDER_CAP"),
                ("chapter", "NOVEL_FORGE_CHAPTER_PROVIDER_CAP"),
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
]

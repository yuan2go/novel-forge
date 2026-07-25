"""PostgreSQL-only production API surface.

This module deliberately has no dependency on LocalStorage, the legacy product
service, projection synchronization, or filesystem routing policy.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from novel_forge.api.authority_dependencies import (
    authority_release_identity,
    build_chapter_authority_application,
    build_chapter_authority_query,
    build_content_authority_application,
    build_content_authority_query,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.chapter_authority.application import ChapterAuthorityApplication
from novel_forge.modules.chapter_authority.queries import ChapterAuthorityQuery
from novel_forge.modules.content_authority import ContentAuthorityApplication, ContentAuthorityQuery
from novel_forge.modules.provider_callback_authority import ProviderCallbackAuthorityService
from novel_forge.modules.provider_control import ProviderAdapterRegistry


@dataclass(frozen=True, slots=True)
class AuthorityApiServices:
    chapter_application: ChapterAuthorityApplication
    chapter_query: ChapterAuthorityQuery
    content_authority_application: ContentAuthorityApplication
    content_authority_query: ContentAuthorityQuery
    provider_callback_service: ProviderCallbackAuthorityService


def create_authority_app(settings: IndustrialSettings):
    try:
        from fastapi import FastAPI
        from fastapi.middleware.cors import CORSMiddleware
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency-gated path
        raise RuntimeError(
            "Authority API requires optional dependencies: fastapi and uvicorn[standard]"
        ) from exc

    if settings.storage_authority != "postgresql":
        raise RuntimeError("authority API requires PostgreSQL storage authority")
    authority_release_identity()
    application = build_chapter_authority_application(settings)
    provider_registry = ProviderAdapterRegistry()
    registered: set[str] = set()
    for adapter in application.model_port.adapter.provider_adapters.values():
        if adapter.provider not in registered:
            provider_registry.register(adapter)
            registered.add(adapter.provider)
    services = AuthorityApiServices(
        chapter_application=application,
        chapter_query=build_chapter_authority_query(settings),
        content_authority_application=build_content_authority_application(settings),
        content_authority_query=build_content_authority_query(settings),
        provider_callback_service=ProviderCallbackAuthorityService(
            settings.database_url or "", provider_registry
        ),
    )
    app = FastAPI(
        title="Novel Forge PostgreSQL Authority API",
        version="7.0.0-authority",
        description="Novel OS command and strong-query authority runtime.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.api_cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from novel_forge.api.models import product_model_map
    from novel_forge.api.routers.chapter_authority import create_router as create_chapter_router
    from novel_forge.api.routers.content_authority import create_router as create_content_router
    from novel_forge.api.routers.canon_authority import create_router as create_canon_router
    from novel_forge.api.routers.provider_callback_authority import (
        create_router as create_provider_callback_router,
    )
    from novel_forge.api.routers.context import ProductRouterContext

    app.include_router(
        create_chapter_router(
            ProductRouterContext(
                app_settings=settings,
                models=product_model_map(),
                services=services,
            )
        )
    )
    app.include_router(
        create_content_router(
            ProductRouterContext(
                app_settings=settings,
                models=product_model_map(),
                services=services,
            )
        )
    )
    app.include_router(
        create_canon_router(
            ProductRouterContext(
                app_settings=settings,
                models=product_model_map(),
                services=services,
            )
        )
    )
    app.include_router(
        create_provider_callback_router(
            ProductRouterContext(
                app_settings=settings,
                models=product_model_map(),
                services=services,
            )
        )
    )

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ready",
            "storage_authority": "postgresql",
            "legacy_localstorage_loaded": False,
        }

    return app


__all__ = ["AuthorityApiServices", "create_authority_app"]

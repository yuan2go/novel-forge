"""PostgreSQL-only production API surface.

This module deliberately has no dependency on the legacy product service,
projection synchronization, or filesystem routing policy.
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
    build_book_authority_application,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.chapter_authority.application import ChapterAuthorityApplication
from novel_forge.modules.chapter_authority.queries import ChapterAuthorityQuery
from novel_forge.modules.content_authority import ContentAuthorityApplication, ContentAuthorityQuery
from novel_forge.modules.book_authority.production import PostgresBookAuthority
from novel_forge.modules.project_authority import (
    ProjectAuthorityApplication,
    ProjectAuthorityQuery,
)
from novel_forge.modules.task_authority import AuthorityTaskQuery
from novel_forge.modules.source_authority import (
    SourceAuthorityApplication,
    SourceAuthorityQuery,
)
from novel_forge.modules.mkaos_authority import (
    MkaosAuthorityApplication,
    MkaosAuthorityQuery,
)
from novel_forge.modules.provider_callback_authority import ProviderCallbackAuthorityService
from novel_forge.modules.provider_control import ProviderAdapterRegistry


@dataclass(frozen=True, slots=True)
class AuthorityApiServices:
    chapter_application: ChapterAuthorityApplication
    chapter_query: ChapterAuthorityQuery
    content_authority_application: ContentAuthorityApplication
    content_authority_query: ContentAuthorityQuery
    provider_callback_service: ProviderCallbackAuthorityService
    book_authority_application: PostgresBookAuthority
    project_authority_application: ProjectAuthorityApplication
    project_authority_query: ProjectAuthorityQuery
    task_authority_query: AuthorityTaskQuery
    source_authority_application: SourceAuthorityApplication
    source_authority_query: SourceAuthorityQuery
    mkaos_authority_application: MkaosAuthorityApplication
    mkaos_authority_query: MkaosAuthorityQuery


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
    build_id, commit_sha = authority_release_identity()
    services = AuthorityApiServices(
        chapter_application=application,
        chapter_query=build_chapter_authority_query(settings),
        content_authority_application=build_content_authority_application(settings),
        content_authority_query=build_content_authority_query(settings),
        provider_callback_service=ProviderCallbackAuthorityService(
            settings.database_url or "", provider_registry
        ),
        book_authority_application=build_book_authority_application(
            settings, chapter_application=application
        ),
        project_authority_application=ProjectAuthorityApplication(
            settings.database_url,
            application_build_id=build_id,
            commit_sha=commit_sha,
        ),
        project_authority_query=ProjectAuthorityQuery(settings.database_url),
        task_authority_query=AuthorityTaskQuery(settings.database_url),
        source_authority_application=SourceAuthorityApplication(
            settings.database_url,
            application_build_id=build_id,
            commit_sha=commit_sha,
        ),
        source_authority_query=SourceAuthorityQuery(settings.database_url),
        mkaos_authority_application=MkaosAuthorityApplication(
            settings.database_url,
            application_build_id=build_id,
            commit_sha=commit_sha,
        ),
        mkaos_authority_query=MkaosAuthorityQuery(settings.database_url),
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
    from novel_forge.api.routers.book_authority import create_router as create_book_router
    from novel_forge.api.routers.context import ProductRouterContext
    from novel_forge.api.routers.authority_projects import (
        create_router as create_project_router,
    )
    from novel_forge.api.routers.authority_tasks import (
        create_router as create_task_router,
    )
    from novel_forge.api.routers.authority_assets import (
        create_router as create_asset_router,
    )
    from novel_forge.api.routers.source_authority import (
        create_router as create_source_router,
    )
    from novel_forge.api.routers.mkaos_authority import (
        create_router as create_mkaos_router,
    )

    app.include_router(
        create_project_router(
            ProductRouterContext(
                app_settings=settings,
                models=product_model_map(),
                services=services,
            )
        )
    )
    app.include_router(
        create_task_router(
            ProductRouterContext(
                app_settings=settings,
                models=product_model_map(),
                services=services,
            )
        )
    )
    app.include_router(
        create_asset_router(
            ProductRouterContext(
                app_settings=settings,
                models=product_model_map(),
                services=services,
            )
        )
    )
    app.include_router(
        create_source_router(
            ProductRouterContext(
                app_settings=settings,
                models=product_model_map(),
                services=services,
            )
        )
    )
    app.include_router(
        create_mkaos_router(
            ProductRouterContext(
                app_settings=settings,
                models=product_model_map(),
                services=services,
            )
        )
    )
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
        create_book_router(
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

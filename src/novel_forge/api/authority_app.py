"""PostgreSQL-only production API surface.

This module deliberately has no dependency on the legacy product service,
projection synchronization, or filesystem routing policy.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any

from novel_forge.api.authority_dependencies import (
    authority_release_identity,
    build_chapter_authority_application,
    build_chapter_authority_query,
    build_content_authority_application,
    build_content_authority_query,
    build_book_authority_application,
    build_book_design_authority_application,
    build_book_design_authority_query,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.chapter_authority.application import ChapterAuthorityApplication
from novel_forge.modules.chapter_authority.queries import ChapterAuthorityQuery
from novel_forge.modules.content_authority import ContentAuthorityApplication, ContentAuthorityQuery
from novel_forge.modules.book_authority.production import PostgresBookAuthority
from novel_forge.modules.book_design_authority import (
    BookDesignAuthorityApplication,
    BookDesignAuthorityQuery,
)
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
from novel_forge.storage.database_runtime import (
    authority_role_instances_from_env,
    close_all_database_runtimes,
    database_runtime_report,
    get_database_runtime,
    validate_connection_budget,
)
from novel_forge.storage.migrations import get_migration_status


REQUIRED_RUNTIME_GROUPS = (
    "chapter",
    "content",
    "source",
    "mkaos",
    "book",
    "outbox",
    "maintenance",
)


def _install_database_runtime_routes(app: Any, settings: IndustrialSettings) -> None:
    @app.get("/runtime/database")
    def runtime_database() -> dict[str, Any]:
        return database_runtime_report(settings.database_url, role="api")

    @app.get("/runtime/metrics")
    def runtime_metrics() -> dict[str, Any]:
        report = database_runtime_report(settings.database_url, role="api")
        return {
            key: report[key]
            for key in (
                "type",
                "contract_version",
                "database_status",
                "pool_size",
                "pool_available",
                "pool_in_use",
                "pool_waiting",
                "connection_acquire_latency",
                "transaction_count",
                "transaction_duration_ms",
                "rollback_count",
                "retry_count",
                "timeout_count",
                "deadlock_count",
                "serialization_failure_count",
                "long_transaction_count",
            )
        }


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
    book_design_authority_application: BookDesignAuthorityApplication
    book_design_authority_query: BookDesignAuthorityQuery


@dataclass(frozen=True, slots=True)
class TrackBMinimalAuthorityServices:
    """Only the services exercised by the first Track B vertical slice."""

    project_authority_application: ProjectAuthorityApplication
    project_authority_query: ProjectAuthorityQuery
    task_authority_query: AuthorityTaskQuery
    book_design_authority_application: BookDesignAuthorityApplication
    book_design_authority_query: BookDesignAuthorityQuery


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
    role_instances = authority_role_instances_from_env()
    configured_connection_budget = validate_connection_budget(
        role_instances,
        postgres_max_connections=int(
            os.environ.get("NOVEL_FORGE_POSTGRES_MAX_CONNECTIONS") or "100"
        ),
    )
    if settings.authority_runtime_profile == "track-b-minimal":
        return _create_track_b_minimal_app(settings, FastAPI, CORSMiddleware)
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
        book_design_authority_application=build_book_design_authority_application(settings),
        book_design_authority_query=build_book_design_authority_query(settings),
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
    from novel_forge.api.routers.book_design_authority import (
        create_router as create_book_design_router,
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
        create_book_design_router(
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
            "status": "alive",
            "storage_authority": "postgresql",
            "legacy_localstorage_loaded": False,
        }

    @app.get("/liveness")
    def liveness() -> dict[str, Any]:
        return {
            "status": "alive",
            "runtime_profile": settings.authority_runtime_profile,
            "storage_authority": "postgresql",
        }

    def readiness_payload() -> dict[str, Any]:
        database_error = ""
        database_health: dict[str, Any] = {}
        connection_budget: dict[str, Any] = configured_connection_budget
        migration: dict[str, Any] = {"ok": False, "current": ""}
        try:
            database_runtime = get_database_runtime(
                settings.database_url, role="api"
            )
            database_health = database_runtime.health()
            with database_runtime.connection() as connection:
                postgres_max_connections = int(
                    connection.execute("SHOW max_connections").fetchone()[0]
                )
            connection_budget = validate_connection_budget(
                role_instances,
                postgres_max_connections=postgres_max_connections,
            )
            migration = get_migration_status(settings.database_url)
        except Exception as exc:
            database_error = f"{type(exc).__name__}: {exc}"
        object_store_error = ""
        try:
            from novel_forge.storage.object_store import MinioObjectStore

            MinioObjectStore(settings).client.list_buckets()
            object_store_ready = True
        except Exception as exc:
            object_store_ready = False
            object_store_error = f"{type(exc).__name__}: {exc}"
        provider_name = str(
            os.environ.get("NOVEL_FORGE_MODEL_PROVIDER") or ""
        ).strip().lower()
        fixture_provider = provider_name in {"", "mock", "local", "offline"}
        provider_status = (
            "FIXTURE_ONLY"
            if settings.environment in {"development", "test"} and fixture_provider
            else "CONFIGURED"
            if provider_name
            else "BLOCKED"
        )
        definitions = {
            "chapter_handler_count": len(application.registry.available_handler_keys),
            "content_definition_count": len(
                services.content_authority_application.registry.definition_names
            ),
        }
        ready = bool(
            migration.get("ok")
            and database_health.get("status") == "ready"
            and connection_budget.get("within_budget")
            and object_store_ready
            and provider_status != "BLOCKED"
            and all(definitions.values())
        )
        return {
            "status": "ready" if ready else "not_ready",
            "runtime_profile": settings.authority_runtime_profile,
            "postgresql": {
                "authority": True,
                "reachable": database_health.get("status") == "ready",
                "migration_head": migration.get("current", ""),
                "migration_chain_current": bool(migration.get("ok")),
                "pool": database_health,
                "connection_budget": connection_budget,
                "error": database_error,
            },
            "object_store": {
                "configured": True,
                "reachable": object_store_ready,
                "error": object_store_error,
            },
            "operation_definitions": definitions,
            "runtime_groups": {
                "registered": list(REQUIRED_RUNTIME_GROUPS),
                "registration_status": "REGISTERED",
                "heartbeat_status_endpoint": "/runtime/readiness",
            },
            "provider": {
                "status": provider_status,
                "real_provider_proven": False,
            },
            "legacy_write_enabled": False,
            "silent_fallback_enabled": False,
        }

    @app.get("/startup")
    def startup() -> dict[str, Any]:
        result = readiness_payload()
        if result["status"] != "ready":
            from fastapi import HTTPException

            raise HTTPException(status_code=503, detail=result)
        return result

    @app.get("/readiness")
    def readiness() -> dict[str, Any]:
        return startup()

    @app.get("/ready")
    def ready() -> dict[str, Any]:
        return startup()

    @app.get("/runtime/readiness")
    def runtime_readiness() -> dict[str, Any]:
        from novel_forge.storage.worker_health import runtime_health_report

        result = runtime_health_report(settings.database_url)
        if result["readiness"] != "READY":
            from fastapi import HTTPException

            raise HTTPException(status_code=503, detail=result)
        return result

    @app.on_event("shutdown")
    def shutdown_database_runtime() -> None:
        close_all_database_runtimes()

    _install_database_runtime_routes(app, settings)
    return app


def create_authority_app_from_env():
    """Zero-argument Uvicorn reload factory for the Authority-only app."""

    return create_authority_app(IndustrialSettings.from_env())


def _create_track_b_minimal_app(settings: IndustrialSettings, FastAPI: Any, CORSMiddleware: Any):
    """Compose an Authority-only API without Provider or Legacy construction."""

    if settings.legacy_write_enabled or settings.silent_legacy_fallback_enabled:
        raise RuntimeError("Track B runtime forbids Legacy writes and silent fallback")
    build_id, commit_sha = authority_release_identity()
    services = TrackBMinimalAuthorityServices(
        project_authority_application=ProjectAuthorityApplication(
            settings.database_url,
            application_build_id=build_id,
            commit_sha=commit_sha,
        ),
        project_authority_query=ProjectAuthorityQuery(settings.database_url),
        task_authority_query=AuthorityTaskQuery(settings.database_url),
        book_design_authority_application=build_book_design_authority_application(settings),
        book_design_authority_query=build_book_design_authority_query(settings),
    )
    app = FastAPI(
        title="Novel Forge Track B Authority API",
        version="7.0.0-track-b-minimal",
        description="Book + BookDesign PostgreSQL Authority-only runtime.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.api_cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from novel_forge.api.models import product_model_map
    from novel_forge.api.routers.authority_assets import create_router as create_asset_router
    from novel_forge.api.routers.authority_projects import create_router as create_project_router
    from novel_forge.api.routers.authority_tasks import create_router as create_task_router
    from novel_forge.api.routers.book_design_authority import (
        create_router as create_book_design_router,
    )
    from novel_forge.api.routers.context import ProductRouterContext
    from novel_forge.storage.object_store import MinioObjectStore

    context = ProductRouterContext(
        app_settings=settings,
        models=product_model_map(),
        services=services,
    )
    for router_factory in (
        create_project_router,
        create_task_router,
        create_asset_router,
        create_book_design_router,
    ):
        app.include_router(router_factory(context))

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "running",
            "runtime_profile": "track-b-minimal",
            "storage_authority": "postgresql",
            "queue_authority": False,
            "legacy_write_enabled": False,
            "silent_fallback_enabled": False,
        }

    @app.get("/liveness")
    def liveness() -> dict[str, Any]:
        return health()

    @app.get("/ready")
    def ready() -> dict[str, Any]:
        database = get_migration_status(settings.database_url)
        object_store_error = ""
        try:
            MinioObjectStore(settings).client.list_buckets()
            object_store_ready = True
        except Exception as exc:  # dependency/network boundary is reported, never hidden
            object_store_ready = False
            object_store_error = f"{type(exc).__name__}: {exc}"
        status = "ready" if database["ok"] and object_store_ready else "not_ready"
        result = {
            "status": status,
            "runtime_profile": "track-b-minimal",
            "postgresql": {
                "authority": True,
                "migration_head": database["current"],
                "migration_chain_current": database["ok"],
            },
            "object_store": {
                "configured": True,
                "reachable": object_store_ready,
                "error": object_store_error,
            },
            "outbox": {"authority": "postgresql"},
            "queue": {"role": "delivery_only", "authority": False},
            "legacy_write_enabled": False,
            "silent_fallback_enabled": False,
        }
        if status != "ready":
            from fastapi import HTTPException

            raise HTTPException(status_code=503, detail=result)
        return result

    @app.get("/startup")
    def startup() -> dict[str, Any]:
        return ready()

    @app.get("/readiness")
    def readiness() -> dict[str, Any]:
        return ready()

    @app.on_event("shutdown")
    def shutdown_database_runtime() -> None:
        close_all_database_runtimes()

    _install_database_runtime_routes(app, settings)
    return app


__all__ = [
    "AuthorityApiServices",
    "TrackBMinimalAuthorityServices",
    "create_authority_app",
    "create_authority_app_from_env",
]

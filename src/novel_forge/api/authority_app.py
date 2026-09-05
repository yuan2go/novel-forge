from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any

from novel_forge.api.authority_dependencies import (
    authority_release_identity,
    build_production_execution_composition,
    build_chapter_authority_application,
    build_chapter_authority_query,
    build_content_authority_application,
    build_content_authority_query,
    build_book_production_composition,
    build_trusted_principal_resolver,
    build_book_design_authority_application,
    build_book_design_authority_query,
    build_agent_runtime_authority_application,
    build_agent_runtime_query,
    build_capability_pack_authority_application,
    build_capability_pack_authority_query,
    build_quality_qualification_authority,
    chapter_capability_pack_compilation_report,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.infrastructure.environment import RuntimeEnvironment
from novel_forge.infrastructure.production_execution_composition import (
    ProductionExecutionComposition,
)
from novel_forge.modules.chapter_authority.application import (
    ChapterAuthorityApplication,
)
from novel_forge.modules.chapter_authority.queries import ChapterAuthorityQuery
from novel_forge.modules.authoring import PostgresAuthoringQuery
from novel_forge.modules.content_authority import (
    ContentAuthorityApplication,
    ContentAuthorityQuery,
)
from novel_forge.modules.book_authority.production import PostgresBookAuthority
from novel_forge.modules.book_authority.completion import PostgresBookCompletionAuthority
from novel_forge.modules.book_authority.composition import BookProductionComposition
from novel_forge.modules.book_design_authority import (
    BookDesignAuthorityApplication,
    BookDesignAuthorityQuery,
)
from novel_forge.modules.agent_runtime.application import (
    AgentRuntimeAuthorityApplication,
)
from novel_forge.modules.agent_runtime.definitions import AGENT_RUNTIME_OPERATIONS
from novel_forge.modules.agent_runtime.queries import AgentRuntimeQuery
from novel_forge.modules.capability_pack_authority.application import (
    CapabilityPackAuthorityApplication,
)
from novel_forge.modules.capability_pack_authority.query import (
    CapabilityPackAuthorityQuery,
)
from novel_forge.modules.chapter_quality_authority.qualification_application import (
    PostgresQualityQualificationAuthority,
)
from novel_forge.modules.temporal_query import TemporalQueryService
from novel_forge.modules.content_intelligence import PacingAnalysisService
from novel_forge.modules.project_authority import (
    ProjectAuthorityApplication,
    ProjectAuthorityQuery,
)
from novel_forge.modules.task_authority import AuthorityTaskQuery
from novel_forge.modules.source_authority import (
    SourceAuthorityApplication,
    SourceAuthorityQuery,
)
from novel_forge.modules.source_import import (
    SourceImportApplication,
    SourceImportQuery,
)
from novel_forge.modules.mkaos_authority import (
    MkaosAuthorityApplication,
    MkaosAuthorityQuery,
)
from novel_forge.modules.provider_callback_authority import (
    ProviderCallbackAuthorityService,
)
from novel_forge.modules.provider_control import (
    build_provider_adapter_registry,
    configured_chapter_provider_ids,
)
from novel_forge.storage.database_runtime import (
    authority_role_instances_from_env,
    close_all_database_runtimes,
    database_runtime_report,
    get_database_runtime,
    validate_connection_budget,
)
from novel_forge.storage.migrations import get_migration_status


REQUIRED_RUNTIME_GROUPS = (
    "agent",
    "chapter",
    "content",
    "source",
    "source_import",
    "mkaos",
    "book",
    "book_followup",
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
    production_execution: ProductionExecutionComposition
    chapter_application: ChapterAuthorityApplication
    chapter_query: ChapterAuthorityQuery
    authoring_query: PostgresAuthoringQuery
    content_authority_application: ContentAuthorityApplication
    content_authority_query: ContentAuthorityQuery
    provider_callback_service: ProviderCallbackAuthorityService
    book_authority_application: PostgresBookAuthority
    book_completion_authority: PostgresBookCompletionAuthority
    book_production: BookProductionComposition
    project_authority_application: ProjectAuthorityApplication
    project_authority_query: ProjectAuthorityQuery
    task_authority_query: AuthorityTaskQuery
    source_authority_application: SourceAuthorityApplication
    source_authority_query: SourceAuthorityQuery
    source_import_application: SourceImportApplication
    source_import_query: SourceImportQuery
    mkaos_authority_application: MkaosAuthorityApplication
    mkaos_authority_query: MkaosAuthorityQuery
    book_design_authority_application: BookDesignAuthorityApplication
    book_design_authority_query: BookDesignAuthorityQuery
    agent_runtime_authority_application: AgentRuntimeAuthorityApplication
    agent_runtime_query: AgentRuntimeQuery
    capability_pack_authority_application: CapabilityPackAuthorityApplication
    capability_pack_authority_query: CapabilityPackAuthorityQuery
    quality_qualification_authority: PostgresQualityQualificationAuthority
    temporal_query_service: TemporalQueryService
    pacing_analysis_service: PacingAnalysisService


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
    provider_registry = build_provider_adapter_registry(
        environment=settings.environment,
        provider_ids=configured_chapter_provider_ids(os.environ),
        env=os.environ,
    )
    production_execution = build_production_execution_composition(
        settings, provider_registry=provider_registry
    )
    application = build_chapter_authority_application(
        settings, execution=production_execution
    )
    book_principal = build_trusted_principal_resolver().resolve_api_principal()
    book_production = build_book_production_composition(
        settings,
        principal=book_principal,
        execution=production_execution,
        chapter_application=application,
    )
    build_id, commit_sha = authority_release_identity()
    runtime_environment = RuntimeEnvironment.parse(
        str(os.environ.get("NOVEL_FORGE_ENVIRONMENT") or settings.environment)
    )
    source_fixture_root = str(
        os.environ.get("NOVEL_FORGE_SOURCE_IMPORT_FILE_FIXTURE_ROOT") or ""
    ).strip()
    services = AuthorityApiServices(
        production_execution=production_execution,
        chapter_application=application,
        chapter_query=build_chapter_authority_query(settings),
        authoring_query=PostgresAuthoringQuery(settings.database_url),
        content_authority_application=build_content_authority_application(settings),
        content_authority_query=build_content_authority_query(settings),
        provider_callback_service=ProviderCallbackAuthorityService(
            settings.database_url or "", provider_registry
        ),
        book_authority_application=book_production.authority,
        book_completion_authority=PostgresBookCompletionAuthority(
            settings.database_url, application_build_id=build_id, commit_sha=commit_sha,
        ),
        book_production=book_production,
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
        source_import_application=SourceImportApplication(
            settings.database_url,
            application_build_id=build_id,
            commit_sha=commit_sha,
            allow_file_repositories=(
                runtime_environment.fixture_allowed and bool(source_fixture_root)
            ),
        ),
        source_import_query=SourceImportQuery(settings.database_url),
        mkaos_authority_application=MkaosAuthorityApplication(
            settings.database_url,
            application_build_id=build_id,
            commit_sha=commit_sha,
        ),
        mkaos_authority_query=MkaosAuthorityQuery(settings.database_url),
        book_design_authority_application=build_book_design_authority_application(
            settings,
            execution=production_execution,
        ),
        book_design_authority_query=build_book_design_authority_query(settings),
        agent_runtime_authority_application=(
            build_agent_runtime_authority_application(
                settings, execution=production_execution
            )
        ),
        agent_runtime_query=build_agent_runtime_query(settings),
        capability_pack_authority_application=(
            build_capability_pack_authority_application(settings)
        ),
        capability_pack_authority_query=build_capability_pack_authority_query(settings),
        quality_qualification_authority=build_quality_qualification_authority(settings),
        temporal_query_service=TemporalQueryService(settings.database_url),
        pacing_analysis_service=PacingAnalysisService(settings.database_url),
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
    from novel_forge.api.routers.chapter_authority import (
        create_router as create_chapter_router,
    )
    from novel_forge.api.routers.content_authority import (
        create_router as create_content_router,
    )
    from novel_forge.api.routers.canon_authority import (
        create_router as create_canon_router,
    )
    from novel_forge.api.routers.provider_callback_authority import (
        create_router as create_provider_callback_router,
    )
    from novel_forge.api.routers.book_authority import (
        create_router as create_book_router,
    )
    from novel_forge.api.routers.book_completion import create_router as create_book_completion_router
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
    from novel_forge.api.routers.source_import import (
        create_router as create_source_import_router,
    )
    from novel_forge.api.routers.mkaos_authority import (
        create_router as create_mkaos_router,
    )
    from novel_forge.api.routers.book_design_authority import (
        create_router as create_book_design_router,
    )
    from novel_forge.api.routers.agent_runtime import (
        create_router as create_agent_runtime_router,
    )
    from novel_forge.api.routers.capability_pack_authority import (
        create_router as create_capability_pack_router,
    )
    from novel_forge.api.routers.quality_qualification import (
        create_router as create_quality_qualification_router,
    )
    from novel_forge.api.routers.temporal_query import (
        create_router as create_temporal_query_router,
    )
    from novel_forge.api.routers.content_intelligence import (
        create_router as create_content_intelligence_router,
    )
    from novel_forge.api.routers.authoring import (
        create_router as create_authoring_router,
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
        create_source_import_router(
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
        create_agent_runtime_router(
            ProductRouterContext(
                app_settings=settings,
                models=product_model_map(),
                services=services,
            )
        )
    )
    app.include_router(
        create_capability_pack_router(
            ProductRouterContext(
                app_settings=settings,
                models=product_model_map(),
                services=services,
            )
        )
    )
    app.include_router(
        create_quality_qualification_router(
            ProductRouterContext(
                app_settings=settings,
                models=product_model_map(),
                services=services,
            )
        )
    )
    app.include_router(
        create_book_completion_router(
            ProductRouterContext(app_settings=settings, models=product_model_map(), services=services)
        )
    )
    app.include_router(
        create_temporal_query_router(
            ProductRouterContext(
                app_settings=settings,
                models=product_model_map(),
                services=services,
            )
        )
    )
    app.include_router(
        create_content_intelligence_router(
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
        create_authoring_router(
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
        }

    @app.get("/liveness")
    def liveness() -> dict[str, Any]:
        return {
            "status": "alive",
            "runtime_profile": "full",
            "storage_authority": "postgresql",
        }

    def readiness_payload() -> dict[str, Any]:
        database_error = ""
        database_health: dict[str, Any] = {}
        connection_budget: dict[str, Any] = configured_connection_budget
        migration: dict[str, Any] = {"ok": False, "current": ""}
        try:
            database_runtime = get_database_runtime(settings.database_url, role="api")
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
        routes = dict(production_execution.gateway.routes)
        route_runtime_classes = {
            route.model_profile.runtime_class.value for route in routes.values()
        }
        provider_route_buildable = bool(routes) and all(
            route.model_profile.backend_id
            and route.model_profile.model_id
            and route.model_profile.capability_probe_ref
            for route in routes.values()
        )
        fixture_only = route_runtime_classes == {"SCRIPTED_FIXTURE"}
        provider_status = (
            "FIXTURE_ONLY"
            if provider_route_buildable and fixture_only
            else "ROUTE_BUILT"
            if provider_route_buildable
            else "BLOCKED"
        )
        try:
            pack_report = chapter_capability_pack_compilation_report(settings)
        except Exception as exc:
            pack_report = {
                "ok": False,
                "pack_id": "chapter_generation_pack",
                "pack_version": "",
                "manifest_hash": "",
                "compilation_hash": "",
                "errors": [
                    {
                        "code": type(exc).__name__,
                        "path": "$",
                        "message": str(exc),
                    }
                ],
            }
        controlled = settings.environment.controlled
        pack_activation_ready = not controlled
        pack_activation_error = ""
        if controlled and database_health.get("status") == "ready":
            try:
                from novel_forge.storage.authority_uow import AuthorityUnitOfWork

                with AuthorityUnitOfWork(settings.database_url) as uow:
                    uow.cursor.execute(
                        """
                        SELECT COUNT(*)
                        FROM authority_capability_pack_activation AS activation
                        JOIN authority_capability_pack_deployment AS deployment
                          ON deployment.deployment_id=
                             activation.active_deployment_id
                        JOIN authority_capability_pack_compilation AS compilation
                          ON compilation.compilation_id=deployment.compilation_id
                        WHERE activation.pack_id=%s
                          AND activation.environment=%s
                          AND deployment.deployment_status='ACTIVE'
                          AND deployment.pack_version=%s
                          AND compilation.compilation_hash=%s
                          AND compilation.manifest_hash=%s
                          AND compilation.compilation_status='TRUSTED'
                        """,
                        [
                            str(pack_report["pack_id"]),
                            settings.environment,
                            str(pack_report["pack_version"]),
                            str(pack_report["compilation_hash"]),
                            str(pack_report["manifest_hash"]),
                        ],
                    )
                    pack_activation_ready = int(uow.cursor.fetchone()[0]) > 0
            except Exception as exc:
                pack_activation_error = f"{type(exc).__name__}: {exc}"
        definitions = {
            "chapter_handler_count": len(application.registry.available_handler_keys),
            "content_definition_count": len(
                services.content_authority_application.registry.definition_names
            ),
            "agent_runtime_definition_count": len(AGENT_RUNTIME_OPERATIONS),
        }
        ready = bool(
            migration.get("ok")
            and database_health.get("status") == "ready"
            and connection_budget.get("within_budget")
            and object_store_ready
            and provider_route_buildable
            and pack_report["ok"]
            and pack_activation_ready
            and all(definitions.values())
        )
        return {
            "status": "ready" if ready else "not_ready",
            "api_ready": ready,
            "runtime_ready": False,
            "fixture_only": fixture_only,
            "real_provider_qualified": False,
            "real_provider_proven": False,
            "longform_proven": False,
            "production_verified": False,
            "runtime_profile": "full",
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
                "route_buildable": provider_route_buildable,
                "runtime_classes": sorted(route_runtime_classes),
                "real_provider_qualified": False,
                "real_provider_proven": False,
            },
            "capability_pack": {
                **pack_report,
                "compilable": bool(pack_report["ok"]),
                "activation_required": controlled,
                "activation_checked": controlled,
                "activation_ready": pack_activation_ready,
                "activation_error": pack_activation_error,
            },
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

        api = readiness_payload()
        fleet = runtime_health_report(
            settings.database_url,
            required_worker_kinds=REQUIRED_RUNTIME_GROUPS,
        )
        runtime_ready = bool(api["api_ready"] and fleet["worker_fleet_ready"])
        result = {
            **fleet,
            "api_ready": bool(api["api_ready"]),
            "runtime_ready": runtime_ready,
            "fixture_only": bool(api["fixture_only"]),
            "real_provider_qualified": bool(api["real_provider_qualified"]),
            "real_provider_proven": bool(api["real_provider_proven"]),
            "longform_proven": bool(api["longform_proven"]),
            "production_verified": bool(api["production_verified"]),
            "capability_pack": api["capability_pack"],
            "provider": api["provider"],
            "api_dependencies": {
                "postgresql": api["postgresql"],
                "object_store": api["object_store"],
            },
            "readiness": "READY" if runtime_ready else "DEGRADED",
        }
        if not runtime_ready:
            from fastapi import HTTPException

            raise HTTPException(status_code=503, detail=result)
        return result

    @app.on_event("shutdown")
    def shutdown_database_runtime() -> None:
        production_execution.close()
        close_all_database_runtimes()

    _install_database_runtime_routes(app, settings)
    return app


def create_authority_app_from_env():

    return create_authority_app(IndustrialSettings.from_env())


__all__ = [
    "AuthorityApiServices",
    "create_authority_app",
    "create_authority_app_from_env",
]

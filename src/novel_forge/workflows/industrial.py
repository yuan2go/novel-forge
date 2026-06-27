from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.infrastructure.settings import IndustrialSettings, optional_dependency_status
from novel_forge.model_adapters import embedding_provider_health, provider_health
from novel_forge.storage.graph import neo4j_status as neo4j_status_service
from novel_forge.storage.local import LocalStorage
from novel_forge.storage.object_store import sync_minio_assets
from novel_forge.storage.migrations import downgrade_migrations
from novel_forge.storage.postgres import PostgresAssetStore, postgres_available, sync_postgres_from_local
from novel_forge.storage.qdrant_index import build_qdrant_index, qdrant_search_assets


def settings_for(root: str | Path = ".") -> IndustrialSettings:
    return IndustrialSettings.from_env(root=root)


def industrial_status(root: str | Path = ".") -> dict[str, Any]:
    storage = LocalStorage(root)
    storage.ensure_layout()
    settings = settings_for(storage.root)
    return {
        "root": str(storage.root),
        "local_counts": storage.counts(),
        "configured_services": settings.configured_services(),
        "optional_dependencies": optional_dependency_status(),
        "model_providers": provider_health(),
        "embedding_provider": embedding_provider_health(require_semantic=True),
        "postgresql": {
            "configured": bool(settings.database_url),
            "available": postgres_available(settings),
            "api_index_mode": "postgres-primary-json-fallback" if settings.database_url else "json-local",
        },
        "neo4j": neo4j_status_service(settings),
    }


def postgres_init(root: str | Path = ".") -> dict[str, Any]:
    settings = settings_for(root)
    store = PostgresAssetStore.from_settings(settings)
    store.initialize()
    return {"postgresql": "initialized"}


def postgres_migrations(root: str | Path = ".") -> dict[str, Any]:
    settings = settings_for(root)
    store = PostgresAssetStore.from_settings(settings)
    return store.migration_status()


def postgres_downgrade(root: str | Path = ".", target_revision: str | None = None, execute: bool = False) -> dict[str, Any]:
    settings = settings_for(root)
    if not settings.database_url:
        raise ValueError("DATABASE_URL is required for postgres-downgrade")
    return downgrade_migrations(settings.database_url, target_revision=target_revision, execute=execute)


def postgres_sync(root: str | Path = ".") -> dict[str, int]:
    storage = LocalStorage(root)
    storage.ensure_layout()
    return sync_postgres_from_local(storage, settings_for(storage.root))


def qdrant_index(
    root: str | Path = ".",
    recreate_collection: bool = False,
    batch_size: int = 32,
    resume: bool = True,
    force_reembed: bool = False,
) -> dict[str, Any]:
    storage = LocalStorage(root)
    storage.ensure_layout()
    return build_qdrant_index(
        storage,
        settings_for(storage.root),
        recreate_collection=recreate_collection,
        batch_size=batch_size,
        resume=resume,
        force_reembed=force_reembed,
    )


def qdrant_search(
    root: str | Path,
    query: str,
    category: str | None = None,
    asset_type: str | None = None,
    tags: list[str] | None = None,
    project_id: str | None = None,
    workspace_path: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    storage = LocalStorage(root)
    storage.ensure_layout()
    return qdrant_search_assets(
        storage,
        settings_for(storage.root),
        query=query,
        category=category,
        asset_type=asset_type,
        tags=tags,
        project_id=project_id,
        workspace_path=workspace_path,
        limit=limit,
    )


def minio_sync(root: str | Path = ".", categories: list[str] | None = None) -> dict[str, Any]:
    storage = LocalStorage(root)
    storage.ensure_layout()
    return sync_minio_assets(storage, settings_for(storage.root), categories=categories)


def neo4j_status(root: str | Path = ".") -> dict[str, Any]:
    return neo4j_status_service(settings_for(root))

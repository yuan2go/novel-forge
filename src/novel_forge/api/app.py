"""API runtime selector with a fail-closed PostgreSQL authority boundary."""
from __future__ import annotations

from novel_forge.infrastructure.settings import IndustrialSettings


def create_app(settings: IndustrialSettings | None = None):
    resolved = settings or IndustrialSettings.from_env()
    if resolved.storage_authority == "postgresql":
        from novel_forge.api.authority_app import create_authority_app

        return create_authority_app(resolved)
    if resolved.environment == "production":
        raise RuntimeError(
            "production API requires NOVEL_FORGE_STORAGE_AUTHORITY=postgresql"
        )
    from novel_forge.api.legacy_app import create_app as create_legacy_app

    return create_legacy_app(resolved)


try:
    app = create_app()
except RuntimeError:  # pragma: no cover - optional dependency/config boundary
    if IndustrialSettings.from_env().environment == "production":
        raise
    app = None


__all__ = ["app", "create_app"]

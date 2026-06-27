from __future__ import annotations

from typing import Any

from novel_forge.api.services import product as product_service
from novel_forge.api.services.product import *  # noqa: F401,F403


def register_product_routes(app: Any, app_settings: Any, models: dict[str, Any]) -> None:
    from fastapi import Request

    from novel_forge.api.routers import product_routers
    from novel_forge.api.routers.context import ProductRouterContext

    @app.middleware("http")
    async def postgres_index_sync_middleware(request: Request, call_next):
        response = await call_next(request)
        if request.method in {"POST", "PATCH", "DELETE"} and response.status_code < 500:
            product_service._sync_postgres_best_effort(app_settings)
        return response

    ctx = ProductRouterContext(app_settings=app_settings, models=models, services=product_service)
    for router in product_routers(ctx):
        app.include_router(router)

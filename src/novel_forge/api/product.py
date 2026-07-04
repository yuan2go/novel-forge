from __future__ import annotations

from typing import Any

from novel_forge.api.services import product as product_service
from novel_forge.api.services.product import *  # noqa: F401,F403


def register_product_routes(app: Any, app_settings: Any, models: dict[str, Any]) -> None:
    from fastapi import Request
    from fastapi.responses import JSONResponse

    from novel_forge.api.routers import product_routers
    from novel_forge.api.routers.context import ProductRouterContext
    from novel_forge.api.routers.runtime_request import (
        normalize_product_api_request_state,
        product_api_policy_response_headers,
        product_api_policy_violation,
    )

    @app.middleware("http")
    async def product_runtime_policy_middleware(request: Request, call_next):
        if not request.url.path.startswith("/product/"):
            return await call_next(request)
        policy = await normalize_product_api_request_state(request)
        request.state.runtime_request_policy = policy
        request.state.os_envelope = policy.get("envelope", {})
        request.state.source_policy = policy.get("source_policy", {})
        violation = product_api_policy_violation(policy)
        if violation:
            return JSONResponse(
                status_code=400,
                content={
                    "detail": violation,
                    "runtime_policy": {
                        "environment": policy.get("environment", ""),
                        "production": bool(policy.get("production", False)),
                        "operation": policy.get("operation", ""),
                    },
                },
                headers=product_api_policy_response_headers(policy),
            )
        response = await call_next(request)
        for key, value in product_api_policy_response_headers(policy).items():
            response.headers[key] = value
        return response

    @app.middleware("http")
    async def postgres_index_sync_middleware(request: Request, call_next):
        response = await call_next(request)
        if request.method in {"POST", "PATCH", "DELETE"} and response.status_code < 500:
            product_service._sync_postgres_best_effort(app_settings)
        return response

    ctx = ProductRouterContext(app_settings=app_settings, models=models, services=product_service)
    for router in product_routers(ctx):
        app.include_router(router)

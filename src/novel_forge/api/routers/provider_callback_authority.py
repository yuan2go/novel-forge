from __future__ import annotations

import os
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Request

from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.provider_callback_authority import ProviderCallbackAcceptCommand


def create_router(ctx: ProductRouterContext) -> APIRouter:
    router = APIRouter(
        prefix="/product/provider-callback-authority",
        tags=["provider-callback-authority"],
    )

    @router.post("/{provider}/callbacks", status_code=202)
    async def accept_callback(
        provider: str,
        request: Request,
        provider_message_id: str = Header(..., alias="X-Provider-Message-Id"),
    ) -> dict[str, object]:
        service = getattr(ctx.services, "provider_callback_service", None)
        if service is None:
            raise HTTPException(status_code=503, detail="provider callback authority is unavailable")
        secret_name = f"NOVEL_FORGE_{provider.upper().replace('-', '_')}_CALLBACK_SECRET"
        secret = str(os.environ.get(secret_name) or "")
        if not secret:
            raise HTTPException(status_code=503, detail="provider callback secret is not configured")
        body = await request.body()
        try:
            return service.accept(
                ProviderCallbackAcceptCommand(
                    provider=provider,
                    provider_message_id=provider_message_id,
                    body=body,
                    headers=dict(request.headers),
                    signature_secret=secret,
                    actor_id="service:provider-callback",
                    worker_id="api:provider-callback",
                    trace_id=str(request.headers.get("x-trace-id") or f"trace:{uuid4()}"),
                    correlation_id=str(
                        request.headers.get("x-correlation-id") or f"correlation:{uuid4()}"
                    ),
                )
            )
        except KernelError as exc:
            status = 401 if "SIGNATURE" in exc.code else 404 if "UNKNOWN" in exc.code else 409
            raise HTTPException(
                status_code=status,
                detail={"code": exc.code, "message": exc.message},
            ) from exc

    return router


__all__ = ["create_router"]

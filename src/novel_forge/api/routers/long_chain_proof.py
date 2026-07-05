from __future__ import annotations

from fastapi import APIRouter, HTTPException

from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.long_chain_proof import run_long_chain_proof
from novel_forge.storage.local import LocalStorage


def create_router(ctx: ProductRouterContext) -> APIRouter:
    app_settings = ctx.app_settings
    models = ctx.models
    globals().update(models)
    router = APIRouter(tags=["product-long-chain-proof"])
    LongChainProofRunRequest = models["LongChainProofRunRequest"]

    @router.post("/product/long-chain-proof/run")
    def long_chain_proof_run_endpoint(request: LongChainProofRunRequest) -> dict:
        try:
            return run_long_chain_proof(
                LocalStorage(app_settings.root),
                project_id=request.project_id,
                mode=request.mode,
                target_chapter_count=request.target_chapter_count,
                environment=request.environment,
                envelope=request.envelope or None,
                opt_in_slow_provider=request.opt_in_slow_provider,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router

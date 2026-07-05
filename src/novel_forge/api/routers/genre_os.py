from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.genre_os import build_genre_strategy_pack, inspect_genre_catalog, run_genre_risk_gate
from novel_forge.storage.local import LocalStorage


def create_router(ctx: ProductRouterContext) -> APIRouter:
    app_settings = ctx.app_settings
    models = ctx.models
    globals().update(models)
    router = APIRouter(tags=["product-genre-os"])
    GenreStrategyPackRequest = models["GenreStrategyPackRequest"]
    GenreRiskGateRequest = models["GenreRiskGateRequest"]

    @router.get("/product/genre/catalog")
    def genre_catalog() -> dict[str, Any]:
        return inspect_genre_catalog()

    @router.post("/product/genre/strategy-pack")
    def genre_strategy_pack_endpoint(request: GenreStrategyPackRequest) -> dict[str, Any]:
        try:
            return build_genre_strategy_pack(
                LocalStorage(app_settings.root),
                genre=request.genre,
                subgenre=request.subgenre,
                project_id=request.project_id,
                platform_id=request.platform_id,
                title=request.title,
                environment=request.environment,
                envelope=request.envelope or None,
                source_policy=request.source_policy or None,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/genre/risk-gate")
    def genre_risk_gate_endpoint(request: GenreRiskGateRequest) -> dict[str, Any]:
        try:
            return run_genre_risk_gate(
                LocalStorage(app_settings.root),
                strategy_pack_path=request.strategy_pack_path,
                target_path=request.target_path,
                evidence=request.evidence,
                environment=request.environment,
                envelope=request.envelope or None,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router

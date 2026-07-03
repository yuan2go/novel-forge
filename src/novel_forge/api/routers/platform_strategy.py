from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException

from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.platform_strategy import (
    assess_platform_retention_risk,
    build_platform_strategy_pack,
    create_platform_feedback_backflow,
    ensure_default_platform_strategy_assets,
    evaluate_platform_chapter_gate,
    evaluate_platform_opening_gate,
    list_platform_strategy_assets,
    prepare_platform_publish_adapter,
)
from novel_forge.storage.local import LocalStorage


def create_router(ctx: ProductRouterContext) -> APIRouter:
    app_settings = ctx.app_settings
    router = APIRouter(tags=["product-platform-strategy"])

    def storage() -> LocalStorage:
        store = LocalStorage(app_settings.root)
        store.ensure_layout()
        return store

    @router.get("/product/platform-strategy/assets")
    def assets(platform: str | None = None, asset_type: str | None = None) -> list[dict[str, Any]]:
        return list_platform_strategy_assets(storage(), platform=platform, asset_type=asset_type)

    @router.post("/product/platform-strategy/defaults")
    def defaults() -> dict[str, Any]:
        try:
            return ensure_default_platform_strategy_assets(storage())
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/platform-strategy/pack")
    def strategy_pack(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return build_platform_strategy_pack(storage(), payload)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/platform-strategy/opening-gate")
    def opening_gate(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return evaluate_platform_opening_gate(storage(), payload)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/platform-strategy/chapter-gate")
    def chapter_gate(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return evaluate_platform_chapter_gate(storage(), payload)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/platform-strategy/retention-risk")
    def retention_risk(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return assess_platform_retention_risk(storage(), payload)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/platform-strategy/publish-adapter")
    def publish_adapter(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return prepare_platform_publish_adapter(storage(), payload)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/platform-strategy/feedback-backflow")
    def feedback_backflow(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return create_platform_feedback_backflow(storage(), payload)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router

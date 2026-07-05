from __future__ import annotations

from fastapi import APIRouter, HTTPException

from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.quality_eval import build_quality_rubric_pack, run_quality_gate, run_quality_suite
from novel_forge.storage.local import LocalStorage


def create_router(ctx: ProductRouterContext) -> APIRouter:
    app_settings = ctx.app_settings
    models = ctx.models
    globals().update(models)
    router = APIRouter(tags=["product-quality-eval-v2"])
    QualityRubricPackRequest = models["QualityRubricPackRequest"]
    QualitySuiteRunRequest = models["QualitySuiteRunRequest"]
    QualityGateRunRequest = models["QualityGateRunRequest"]

    @router.post("/product/quality/rubric-pack")
    def quality_rubric_pack_endpoint(request: QualityRubricPackRequest) -> dict:
        try:
            return build_quality_rubric_pack(
                LocalStorage(app_settings.root),
                genre_id=request.genre_id,
                platform_id=request.platform_id,
                style_profile_path=request.style_profile_path,
                scope=request.scope,
                environment=request.environment,
                envelope=request.envelope or None,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/quality/suite")
    def quality_suite_endpoint(request: QualitySuiteRunRequest) -> dict:
        try:
            return run_quality_suite(
                LocalStorage(app_settings.root),
                suite_type=request.suite_type,
                target_paths=request.target_paths,
                rubric_path=request.rubric_path,
                genre_strategy_pack_path=request.genre_strategy_pack_path,
                style_profile_path=request.style_profile_path,
                platform_id=request.platform_id,
                environment=request.environment,
                envelope=request.envelope or None,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/quality/gate")
    def quality_gate_endpoint(request: QualityGateRunRequest) -> dict:
        try:
            return run_quality_gate(
                LocalStorage(app_settings.root),
                quality_report_path=request.quality_report_path,
                environment=request.environment,
                envelope=request.envelope or None,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.style_os import build_style_profile, extract_style_fingerprint, ingest_style_sample, run_style_drift_gate
from novel_forge.storage.local import LocalStorage


def create_router(ctx: ProductRouterContext) -> APIRouter:
    app_settings = ctx.app_settings
    models = ctx.models
    globals().update(models)
    router = APIRouter(tags=["product-style-os"])
    StyleSampleIngestRequest = models["StyleSampleIngestRequest"]
    StyleFingerprintRequest = models["StyleFingerprintRequest"]
    StyleProfileBuildRequest = models["StyleProfileBuildRequest"]
    StyleDriftGateRequest = models["StyleDriftGateRequest"]

    @router.get("/product/style/health")
    def style_health() -> dict[str, Any]:
        return {"status": "ready", "raw_sample_context_policy": "excluded_from_generation_context"}

    @router.post("/product/style/sample")
    def style_sample_endpoint(request: StyleSampleIngestRequest) -> dict[str, Any]:
        try:
            return ingest_style_sample(
                LocalStorage(app_settings.root),
                sample_text=request.sample_text,
                project_id=request.project_id,
                rights=request.rights or None,
                title=request.title,
                source=request.source,
                environment=request.environment,
                envelope=request.envelope or None,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/style/fingerprint")
    def style_fingerprint_endpoint(request: StyleFingerprintRequest) -> dict[str, Any]:
        try:
            return extract_style_fingerprint(
                LocalStorage(app_settings.root),
                sample_path=request.sample_path,
                environment=request.environment,
                envelope=request.envelope or None,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/style/profile")
    def style_profile_endpoint(request: StyleProfileBuildRequest) -> dict[str, Any]:
        try:
            return build_style_profile(
                LocalStorage(app_settings.root),
                fingerprint_path=request.fingerprint_path,
                style_name=request.style_name,
                scope=request.scope,
                environment=request.environment,
                envelope=request.envelope or None,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/style/drift-gate")
    def style_drift_gate_endpoint(request: StyleDriftGateRequest) -> dict[str, Any]:
        try:
            return run_style_drift_gate(
                LocalStorage(app_settings.root),
                style_profile_path=request.style_profile_path,
                target_path=request.target_path,
                environment=request.environment,
                envelope=request.envelope or None,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router

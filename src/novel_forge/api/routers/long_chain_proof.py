from __future__ import annotations

from fastapi import APIRouter, HTTPException

from novel_forge.api.provider_adapters import adapter_from_provider_payload, ensure_model_route_from_payload
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
        storage = LocalStorage(app_settings.root)
        payload = request.model_dump()
        try:
            route = ensure_model_route_from_payload(
                storage,
                task_type="chapter_draft",
                payload=payload,
                project_id=request.project_id,
                environment=request.environment,
            )
            provider_adapter = None
            if str(request.mode).startswith("provider_"):
                provider_adapter = adapter_from_provider_payload(
                    {
                        **payload,
                        "fixture_response": request.fixture_chapter_response or None,
                        "allow_mock_fixture": request.allow_mock_fixture,
                    },
                    default_operation="generate",
                )
            return run_long_chain_proof(
                storage,
                project_id=request.project_id,
                mode=request.mode,
                target_chapter_count=request.target_chapter_count,
                environment=request.environment,
                envelope=request.envelope or None,
                opt_in_slow_provider=request.opt_in_slow_provider,
                provider_adapter=provider_adapter,
                provider_runtime_guard=request.provider_runtime_guard or None,
                require_external_provider_proof=request.require_external_provider_proof,
            ) | (
                {"model_route_path": route["path"]}
                if route
                else {}
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router

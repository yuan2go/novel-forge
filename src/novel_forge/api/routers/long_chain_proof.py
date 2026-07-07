from __future__ import annotations

from fastapi import APIRouter, HTTPException

from novel_forge.api.provider_adapters import adapter_from_provider_payload, ensure_model_route_from_payload
from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.long_chain_proof import run_long_chain_proof
from novel_forge.modules.v7_provider_proof import run_v7_provider_proof
from novel_forge.storage.local import LocalStorage


def create_router(ctx: ProductRouterContext) -> APIRouter:
    app_settings = ctx.app_settings
    models = ctx.models
    globals().update(models)
    router = APIRouter(tags=["product-long-chain-proof"])
    LongChainProofRunRequest = models["LongChainProofRunRequest"]
    V7ProviderProofRequest = models["V7ProviderProofRequest"]

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

    @router.post("/product/provider-proof/v7")
    def v7_provider_proof_endpoint(request: V7ProviderProofRequest) -> dict:
        storage = LocalStorage(app_settings.root)
        payload = request.model_dump()
        try:
            routes = [
                ensure_model_route_from_payload(
                    storage,
                    task_type=task_type,
                    payload=_provider_payload_for_task(payload, task_type),
                    project_id=request.project_id,
                    environment=request.environment,
                )
                for task_type in ["chapter_draft", "quality_judge"]
            ]
            adapter = _v7_provider_proof_adapter(payload)
            result = run_v7_provider_proof(
                storage,
                provider_adapter=adapter,
                project_id=request.project_id,
                draft_path=request.draft_path or None,
                genre_strategy_pack_path=request.genre_strategy_pack_path or None,
                style_profile_path=request.style_profile_path or None,
                platform_id=request.platform_id,
                provider_runtime_guard=request.provider_runtime_guard or None,
                require_external_provider_proof=request.require_external_provider_proof,
                environment=request.environment,
                envelope=request.envelope or None,
                target_chapter_count=request.target_chapter_count,
            )
            result["model_route_paths"] = [route["path"] for route in routes if route]
            return result
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router


class _V7ProviderProofPayloadAdapter:
    def __init__(self, *, generate_response: dict, review_response: dict, provider_name: str, external_provider_evidence: dict[str, object]) -> None:
        self.generate_response = generate_response
        self.review_response = review_response
        self.name = provider_name
        self.external_provider_evidence = external_provider_evidence

    def generate(self, payload: str, context: dict | None = None) -> dict:
        response = dict(self.generate_response)
        response.setdefault("external_provider_evidence", self.external_provider_evidence)
        return response

    def review(self, payload: str, context: dict | None = None) -> dict:
        response = dict(self.review_response)
        response.setdefault("external_provider_evidence", self.external_provider_evidence)
        return response


def _v7_provider_proof_adapter(payload: dict) -> object:
    chapter = payload.get("fixture_chapter_response") if isinstance(payload.get("fixture_chapter_response"), dict) else {}
    review = payload.get("fixture_review_response") if isinstance(payload.get("fixture_review_response"), dict) else {}
    if chapter or review:
        if not (chapter and review):
            raise ValueError("v7 provider proof fixture mode requires both fixture_chapter_response and fixture_review_response")
        if str(payload.get("mode") or "fixture") == "real" and not payload.get("allow_mock_fixture"):
            raise ValueError("v7 provider proof fixture responses require allow_mock_fixture=true unless mode is fixture")
        provider_config = payload.get("provider_config", {}) if isinstance(payload.get("provider_config", {}), dict) else {}
        return _V7ProviderProofPayloadAdapter(
            generate_response=chapter,
            review_response=review,
            provider_name=str(provider_config.get("provider") or payload.get("provider") or "fixture-provider"),
            external_provider_evidence=provider_config.get("external_provider_evidence") if isinstance(provider_config.get("external_provider_evidence"), dict) else {},
        )
    adapter = adapter_from_provider_payload(payload, default_operation="generate")
    if adapter is None:
        raise ValueError("v7 provider proof requires provider_config.provider or explicit fixture responses")
    return adapter


def _provider_payload_for_task(payload: dict, task_type: str) -> dict:
    route = payload.get("provider_route", {}) if isinstance(payload.get("provider_route"), dict) else {}
    return {**payload, "provider_route": {**route, "task_type": task_type}}

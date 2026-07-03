from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException

from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules import mkaos as mkaos_service
from novel_forge.storage.local import LocalStorage


def create_router(ctx: ProductRouterContext) -> APIRouter:
    app_settings = ctx.app_settings
    router = APIRouter(tags=["product-mkaos"])

    def storage() -> LocalStorage:
        store = LocalStorage(app_settings.root)
        store.ensure_layout()
        return store

    @router.get("/product/mkaos/overview")
    @router.get("/api/mkaos/overview")
    def overview(project_id: str | None = None) -> dict[str, Any]:
        try:
            store = storage()
            sources = mkaos_service.list_source_documents(store, project_id=project_id, limit=200)
            knowledge = mkaos_service.list_knowledge_cards(store, project_id=project_id, limit=500)
            bindings = mkaos_service.list_usage_bindings(store, limit=500)
            rules = mkaos_service.ensure_default_rule_cards(store)
            usage = mkaos_service.list_usage_events(store, project_id=project_id, limit=500)
            risks = mkaos_service.list_risk_knowledge(store, project_id=project_id, limit=200)
            return {
                "summary": {
                    "source_documents": len(sources),
                    "knowledge_cards": len(knowledge),
                    "usage_bindings": len(bindings),
                    "rule_cards": len(rules),
                    "usage_events": len(usage),
                    "risk_items": len(risks),
                },
                "sources": sources[:10],
                "knowledge": knowledge[:10],
                "bindings": bindings[:20],
                "rules": rules[:20],
                "usage_events": usage[:20],
                "risks": risks[:20],
            }
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/mkaos/query/knowledge")
    @router.post("/api/mkaos/query/knowledge")
    def query_knowledge(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return mkaos_service.query_knowledge(storage(), payload)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/mkaos/convert/assets")
    @router.post("/api/mkaos/convert/assets")
    def convert_assets(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return mkaos_service.convert_assets(storage(), payload)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/mkaos/convert/rules")
    @router.post("/api/mkaos/convert/rules")
    def convert_rules(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return mkaos_service.convert_rules(storage(), payload)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/mkaos/sources")
    @router.post("/api/mkaos/sources")
    def create_source(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return mkaos_service.import_source_document(storage(), payload)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/mkaos/sources")
    @router.get("/api/mkaos/sources")
    def sources(project_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        return mkaos_service.list_source_documents(storage(), project_id=project_id, limit=limit)

    @router.get("/product/mkaos/sources/{source_id}")
    @router.get("/api/mkaos/sources/{source_id}")
    def source_detail(source_id: str) -> dict[str, Any]:
        try:
            store = storage()
            rows = [row for row in mkaos_service.list_source_documents(store, limit=1000) if row["id"] == source_id or row["path"] == source_id]
            if not rows:
                raise FileNotFoundError(source_id)
            return {**rows[0], "chunks": mkaos_service.list_source_chunks(store, rows[0]["id"])}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/mkaos/sources/{source_id}/chunks/rebuild")
    @router.post("/api/mkaos/sources/{source_id}/chunks/rebuild")
    def rebuild_chunks(source_id: str) -> dict[str, Any]:
        try:
            return mkaos_service.rebuild_source_chunks(storage(), source_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/mkaos/sources/{source_id}/chunks")
    @router.get("/api/mkaos/sources/{source_id}/chunks")
    def source_chunks(source_id: str, limit: int = 200) -> list[dict[str, Any]]:
        try:
            return mkaos_service.list_source_chunks(storage(), source_id, limit=limit)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/product/mkaos/knowledge")
    @router.post("/api/mkaos/knowledge")
    def create_knowledge(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return mkaos_service.create_knowledge_card(storage(), payload)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/mkaos/knowledge")
    @router.get("/api/mkaos/knowledge")
    def knowledge(project_id: str | None = None, include_deprecated: bool = True, limit: int = 200) -> list[dict[str, Any]]:
        return mkaos_service.list_knowledge_cards(storage(), project_id=project_id, include_deprecated=include_deprecated, limit=limit)

    @router.get("/product/mkaos/knowledge/{knowledge_id}")
    @router.get("/api/mkaos/knowledge/{knowledge_id}")
    def knowledge_detail(knowledge_id: str) -> dict[str, Any]:
        try:
            rows = [row for row in mkaos_service.list_knowledge_cards(storage(), limit=1000) if row["id"] == knowledge_id or row["path"] == knowledge_id]
            if not rows:
                raise FileNotFoundError(knowledge_id)
            return rows[0]
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.patch("/product/mkaos/knowledge/{knowledge_id}")
    @router.patch("/api/mkaos/knowledge/{knowledge_id}")
    def patch_knowledge(knowledge_id: str, payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return mkaos_service.update_knowledge_card(storage(), knowledge_id, payload)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/mkaos/knowledge/{knowledge_id}/usage-bindings")
    @router.post("/api/mkaos/knowledge/{knowledge_id}/usage-bindings")
    def create_binding(knowledge_id: str, payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return mkaos_service.create_usage_binding(storage(), knowledge_id, payload)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/mkaos/knowledge/{knowledge_id}/usage-bindings")
    @router.get("/api/mkaos/knowledge/{knowledge_id}/usage-bindings")
    def knowledge_bindings(knowledge_id: str) -> list[dict[str, Any]]:
        return mkaos_service.list_usage_bindings(storage(), knowledge_id)

    @router.get("/product/mkaos/usage-bindings")
    @router.get("/api/mkaos/usage-bindings")
    def usage_bindings(flow: str | None = None, enabled: bool | None = None) -> list[dict[str, Any]]:
        return mkaos_service.list_usage_bindings(storage(), flow=flow, enabled=enabled)

    @router.patch("/product/mkaos/usage-bindings/{binding_id}")
    @router.patch("/api/mkaos/usage-bindings/{binding_id}")
    def patch_binding(binding_id: str, payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return mkaos_service.update_usage_binding(storage(), binding_id, payload)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/mkaos/rules")
    @router.post("/api/mkaos/rules")
    def create_rule(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return mkaos_service.create_rule_card(storage(), payload)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/mkaos/rules")
    @router.get("/api/mkaos/rules")
    def rules(flow: str | None = None) -> list[dict[str, Any]]:
        store = storage()
        mkaos_service.ensure_default_rule_cards(store)
        return mkaos_service.list_rule_cards(store, flow=flow)

    @router.post("/product/mkaos/templates")
    @router.post("/api/mkaos/templates")
    def create_template(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return mkaos_service.create_template_card(storage(), payload)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/mkaos/templates")
    @router.get("/api/mkaos/templates")
    def templates(flow: str | None = None) -> list[dict[str, Any]]:
        return mkaos_service.list_template_cards(storage(), flow=flow)

    @router.post("/product/mkaos/packs/build")
    @router.post("/api/mkaos/packs/build")
    def build_pack(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return mkaos_service.build_knowledge_pack(storage(), payload)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/mkaos/packs/{pack_id}")
    @router.get("/api/mkaos/packs/{pack_id}")
    def pack_detail(pack_id: str) -> dict[str, Any]:
        try:
            return mkaos_service.get_knowledge_pack(storage(), pack_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/product/mkaos/packs/{pack_id}/prompt-preview")
    @router.get("/api/mkaos/packs/{pack_id}/prompt-preview")
    def pack_preview(pack_id: str) -> dict[str, Any]:
        try:
            return mkaos_service.pack_prompt_preview(storage(), pack_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/product/mkaos/packs/{pack_id}/adapter")
    @router.get("/api/mkaos/packs/{pack_id}/adapter")
    def pack_adapter(pack_id: str, flow: str | None = None) -> dict[str, Any]:
        try:
            return mkaos_service.adapt_pack_for_flow(storage(), pack_id, flow=flow)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/mkaos/validate/artifact")
    @router.post("/api/mkaos/validate/artifact")
    def validate_artifact(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        return mkaos_service.validate_artifact(storage(), payload)

    @router.post("/product/mkaos/validate/canon-conflict")
    @router.post("/api/mkaos/validate/canon-conflict")
    def validate_canon(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        return mkaos_service.validate_canon_conflict(storage(), payload)

    @router.post("/product/mkaos/usage-events")
    @router.post("/api/mkaos/usage-events")
    def usage_event(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return mkaos_service.record_usage_event(storage(), payload)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/mkaos/usage-events")
    @router.get("/api/mkaos/usage-events")
    def usage_events(project_id: str | None = None, flow: str | None = None, chapter_id: str | None = None) -> list[dict[str, Any]]:
        return mkaos_service.list_usage_events(storage(), project_id=project_id, flow=flow, chapter_id=chapter_id)

    @router.post("/product/mkaos/feedback/review")
    @router.post("/api/mkaos/feedback/review")
    def feedback_review(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return mkaos_service.record_review_feedback(storage(), payload)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/mkaos/feedback/apply-weight-update")
    @router.post("/api/mkaos/feedback/apply-weight-update")
    def feedback_weight(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return mkaos_service.apply_weight_update(storage(), payload)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/mkaos/risks")
    @router.get("/api/mkaos/risks")
    def risks(project_id: str | None = None) -> list[dict[str, Any]]:
        return mkaos_service.list_risk_knowledge(storage(), project_id=project_id)

    @router.post("/product/mkaos/acceptance/minimal")
    @router.post("/api/mkaos/acceptance/minimal")
    def minimal_acceptance() -> dict[str, Any]:
        try:
            return mkaos_service.run_minimal_acceptance_fixture(storage())
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router

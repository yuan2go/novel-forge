from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException

from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules import mkaos as mkaos_service
from novel_forge.storage.local import LocalStorage


def _mkaos_response(result: Any, *, warnings: list[str] | None = None) -> dict[str, Any]:
    if isinstance(result, dict) and result.get("success") is True and "data" in result:
        envelope = result.get("envelope") if isinstance(result.get("envelope"), dict) else {}
        response = {
            **result,
            "envelope_id": str(envelope.get("envelope_id") or result.get("envelope_id") or result.get("request_id") or ""),
            "error": result.get("error") or None,
            "warnings": warnings if warnings is not None else result.get("warnings", []),
        }
        data = result.get("data")
        if isinstance(data, dict):
            for key, value in data.items():
                response.setdefault(key, value)
        return response
    response = {
        "success": True,
        "request_id": make_id("mkaos_request", utc_now()),
        "trace_id": "",
        "envelope_id": "",
        "envelope": {},
        "data": result,
        "error": None,
        "warnings": warnings or [],
    }
    if isinstance(result, dict):
        for key, value in result.items():
            response.setdefault(key, value)
    return response


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
            return _mkaos_response(mkaos_service.query_knowledge(storage(), payload))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/mkaos/knowledge-graph/build")
    @router.post("/api/mkaos/knowledge-graph/build")
    def build_knowledge_graph(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return _mkaos_response(mkaos_service.build_knowledge_graph(storage(), payload))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/mkaos/knowledge-graph/explorer")
    @router.post("/api/mkaos/knowledge-graph/explorer")
    def build_knowledge_graph_explorer(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return _mkaos_response(mkaos_service.build_knowledge_graph_explorer(storage(), payload))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/mkaos/knowledge-graph/query")
    @router.post("/api/mkaos/knowledge-graph/query")
    def query_knowledge_graph(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return _mkaos_response(mkaos_service.query_knowledge_graph(storage(), payload))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/mkaos/knowledge-graph/paths")
    @router.post("/api/mkaos/knowledge-graph/paths")
    def query_knowledge_graph_paths(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return _mkaos_response(mkaos_service.query_knowledge_graph_paths(storage(), payload))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/mkaos/learning/effects")
    @router.post("/api/mkaos/learning/effects")
    def learn_from_knowledge_effects(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return _mkaos_response(mkaos_service.learn_from_knowledge_effects(storage(), payload))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/mkaos/evolution/run")
    @router.post("/api/mkaos/evolution/run")
    def run_knowledge_evolution(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return _mkaos_response(mkaos_service.run_knowledge_evolution_cycle(storage(), payload))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/mkaos/governance/approvals")
    @router.post("/api/mkaos/governance/approvals")
    def create_governance_approval(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return _mkaos_response(mkaos_service.create_governance_approval(storage(), payload))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/mkaos/governance/approvals")
    @router.get("/api/mkaos/governance/approvals")
    def list_governance_approvals(project_id: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        return mkaos_service.list_governance_approvals(storage(), project_id=project_id, status=status)

    @router.post("/product/mkaos/governance/approvals/{approval_id}/resolve")
    @router.post("/api/mkaos/governance/approvals/{approval_id}/resolve")
    def resolve_governance_approval(approval_id: str, payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return _mkaos_response(mkaos_service.resolve_governance_approval(storage(), approval_id, payload))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/mkaos/convert/assets")
    @router.post("/api/mkaos/convert/assets")
    def convert_assets(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return _mkaos_response(mkaos_service.convert_assets(storage(), payload))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/mkaos/convert/rules")
    @router.post("/api/mkaos/convert/rules")
    def convert_rules(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return _mkaos_response(mkaos_service.convert_rules(storage(), payload))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/mkaos/sources")
    @router.post("/api/mkaos/sources")
    def create_source(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return _mkaos_response(mkaos_service.import_source_document(storage(), payload))
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
            return _mkaos_response(mkaos_service.rebuild_source_chunks(storage(), source_id))
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
            return _mkaos_response(mkaos_service.create_knowledge_card(storage(), payload))
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
            return _mkaos_response(mkaos_service.update_knowledge_card(storage(), knowledge_id, payload))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/mkaos/knowledge/{knowledge_id}/usage-bindings")
    @router.post("/api/mkaos/knowledge/{knowledge_id}/usage-bindings")
    def create_binding(knowledge_id: str, payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return _mkaos_response(mkaos_service.create_usage_binding(storage(), knowledge_id, payload))
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
            return _mkaos_response(mkaos_service.update_usage_binding(storage(), binding_id, payload))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/mkaos/rules")
    @router.post("/api/mkaos/rules")
    def create_rule(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return _mkaos_response(mkaos_service.create_rule_card(storage(), payload))
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
            return _mkaos_response(mkaos_service.create_template_card(storage(), payload))
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
            return _mkaos_response(mkaos_service.build_knowledge_pack(storage(), payload))
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

    @router.get("/product/mkaos/packs/{pack_id}/debug")
    @router.get("/api/mkaos/packs/{pack_id}/debug")
    def pack_debug(pack_id: str) -> dict[str, Any]:
        try:
            return mkaos_service.pack_debug_report(storage(), pack_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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
        return _mkaos_response(mkaos_service.validate_artifact(storage(), payload))

    @router.post("/product/mkaos/validate/canon-conflict")
    @router.post("/api/mkaos/validate/canon-conflict")
    def validate_canon(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        return _mkaos_response(mkaos_service.validate_canon_conflict(storage(), payload))

    @router.post("/product/mkaos/conflicts/check")
    @router.post("/api/mkaos/conflicts/check")
    def conflicts_check(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return _mkaos_response(mkaos_service.detect_knowledge_conflicts(storage(), payload))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/mkaos/conflicts/semantic-review")
    @router.post("/api/mkaos/conflicts/semantic-review")
    def semantic_conflict_review(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return _mkaos_response(mkaos_service.run_semantic_conflict_review(storage(), payload))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/mkaos/cross-discipline/fusion")
    @router.post("/api/mkaos/cross-discipline/fusion")
    def cross_discipline_fusion(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return _mkaos_response(mkaos_service.create_cross_discipline_fusion_path(storage(), payload))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/mkaos/evidence-spans/{chunk_id}")
    @router.post("/api/mkaos/evidence-spans/{chunk_id}")
    def create_evidence_span(chunk_id: str, payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return _mkaos_response(mkaos_service.create_evidence_span(storage(), chunk_id, payload))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/mkaos/evidence-spans")
    @router.get("/api/mkaos/evidence-spans")
    def evidence_spans(source_chunk_id: str | None = None, project_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        return mkaos_service.list_evidence_spans(storage(), source_chunk_id=source_chunk_id, project_id=project_id, limit=limit)

    @router.post("/product/mkaos/quality/{knowledge_id}/recalculate")
    @router.post("/api/mkaos/quality/{knowledge_id}/recalculate")
    def recalculate_quality(knowledge_id: str, payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return _mkaos_response(mkaos_service.recalculate_knowledge_quality(storage(), knowledge_id, payload))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/mkaos/quality/{knowledge_id}/history")
    @router.get("/api/mkaos/quality/{knowledge_id}/history")
    def quality_history(knowledge_id: str, limit: int = 200) -> dict[str, Any]:
        return mkaos_service.knowledge_quality_history(storage(), knowledge_id, limit=limit)

    @router.get("/product/mkaos/quality/low")
    @router.get("/api/mkaos/quality/low")
    def low_quality(project_id: str | None = None, threshold: float = 0.45) -> list[dict[str, Any]]:
        return mkaos_service.list_low_quality_knowledge(storage(), project_id=project_id, threshold=threshold)

    @router.get("/product/mkaos/quality/high-copyright-risk")
    @router.get("/api/mkaos/quality/high-copyright-risk")
    def high_copyright_risk(project_id: str | None = None, threshold: float = 0.7) -> list[dict[str, Any]]:
        return mkaos_service.list_high_copyright_risk_knowledge(storage(), project_id=project_id, threshold=threshold)

    @router.post("/product/mkaos/relations")
    @router.post("/api/mkaos/relations")
    def create_relation(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return _mkaos_response(mkaos_service.create_knowledge_relation(storage(), payload))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/mkaos/relations")
    @router.get("/api/mkaos/relations")
    def relations(knowledge_id: str | None = None, relation_type: str | None = None, project_id: str | None = None) -> list[dict[str, Any]]:
        return mkaos_service.list_knowledge_relations(storage(), knowledge_id=knowledge_id, relation_type=relation_type, project_id=project_id)

    @router.post("/product/mkaos/lineage/query")
    @router.post("/api/mkaos/lineage/query")
    def lineage_query(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return _mkaos_response(mkaos_service.query_lineage_audit(storage(), payload))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/mkaos/mutations")
    @router.get("/api/mkaos/mutations")
    def mutations(asset_id: str | None = None, asset_type: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        return mkaos_service.list_mkaos_mutations(storage(), asset_id=asset_id, asset_type=asset_type, limit=limit)

    @router.get("/product/mkaos/versions/{asset_id}")
    @router.get("/api/mkaos/versions/{asset_id}")
    def versions(asset_id: str, limit: int = 100) -> list[dict[str, Any]]:
        return mkaos_service.list_knowledge_versions(storage(), asset_id, limit=limit)

    @router.post("/product/mkaos/versions/diff")
    @router.post("/api/mkaos/versions/diff")
    def versions_diff(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return _mkaos_response(mkaos_service.diff_knowledge_versions(storage(), str(payload.get("left_version_id") or ""), str(payload.get("right_version_id") or "")))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/mkaos/versions/{version_id}/rollback")
    @router.post("/api/mkaos/versions/{version_id}/rollback")
    def versions_rollback(version_id: str, payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return _mkaos_response(mkaos_service.rollback_knowledge_version(storage(), version_id, payload))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/mkaos/usage-events")
    @router.post("/api/mkaos/usage-events")
    def usage_event(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return _mkaos_response(mkaos_service.record_usage_event(storage(), payload))
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
            return _mkaos_response(mkaos_service.record_review_feedback(storage(), payload))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/mkaos/feedback/apply-weight-update")
    @router.post("/api/mkaos/feedback/apply-weight-update")
    def feedback_weight(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return _mkaos_response(mkaos_service.apply_weight_update(storage(), payload))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/mkaos/feedback/reader-attribution")
    @router.post("/api/mkaos/feedback/reader-attribution")
    def feedback_reader_attribution(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return _mkaos_response(mkaos_service.attribute_reader_feedback_to_knowledge(storage(), payload))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/mkaos/review-issues/persist")
    @router.post("/api/mkaos/review-issues/persist")
    def persist_review_issues(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return _mkaos_response(mkaos_service.persist_mkaos_review_issues(storage(), payload))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/mkaos/revision-task")
    @router.post("/api/mkaos/revision-task")
    def revision_task(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return _mkaos_response(mkaos_service.create_revision_task_from_mkaos_issue(storage(), payload))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/mkaos/import-pipeline")
    @router.post("/api/mkaos/import-pipeline")
    def import_pipeline(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return _mkaos_response(mkaos_service.import_source_with_pipeline(storage(), payload))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/mkaos/professional-book/import-run")
    @router.post("/api/mkaos/professional-book/import-run")
    def professional_book_import_run(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return _mkaos_response(mkaos_service.run_professional_book_import(storage(), payload))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/mkaos/extraction/candidates")
    @router.post("/api/mkaos/extraction/candidates")
    def extraction_candidates(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return _mkaos_response(mkaos_service.extract_knowledge_candidates(storage(), payload))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/mkaos/extraction/provider-quality")
    @router.post("/api/mkaos/extraction/provider-quality")
    def extraction_provider_quality(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return _mkaos_response(mkaos_service.validate_extraction_provider_quality(storage(), payload))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/mkaos/provider/e2e-probe")
    @router.post("/api/mkaos/provider/e2e-probe")
    def provider_e2e_probe(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return _mkaos_response(mkaos_service.run_mkaos_provider_e2e_probe(storage(), payload))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/mkaos/extraction/candidates/{candidate_id}/approve")
    @router.post("/api/mkaos/extraction/candidates/{candidate_id}/approve")
    def approve_candidate(candidate_id: str, payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return _mkaos_response(mkaos_service.approve_knowledge_candidate(storage(), candidate_id, payload))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/mkaos/templates/from-knowledge/{knowledge_id}")
    @router.post("/api/mkaos/templates/from-knowledge/{knowledge_id}")
    def template_from_knowledge(knowledge_id: str, payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return _mkaos_response(mkaos_service.knowledge_to_application_template(storage(), knowledge_id, payload))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/mkaos/anti-encyclopedia/diagnose")
    @router.post("/api/mkaos/anti-encyclopedia/diagnose")
    def anti_encyclopedia(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        return _mkaos_response(mkaos_service.anti_encyclopedia_diagnostics(storage(), payload))

    @router.post("/product/mkaos/knowledge/{knowledge_id}/status")
    @router.post("/api/mkaos/knowledge/{knowledge_id}/status")
    def status_change(knowledge_id: str, payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return _mkaos_response(mkaos_service.change_knowledge_status(storage(), knowledge_id, payload))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/mkaos/regression/cases")
    @router.post("/api/mkaos/regression/cases")
    def regression_case(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return _mkaos_response(mkaos_service.create_knowledge_regression_case(storage(), payload))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/mkaos/regression/run")
    @router.post("/api/mkaos/regression/run")
    def regression_run(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            if payload.get("case_id"):
                return _mkaos_response(mkaos_service.run_knowledge_regression_case(storage(), str(payload.get("case_id"))))
            return _mkaos_response(mkaos_service.run_knowledge_regression_suite(storage(), payload))
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
            return _mkaos_response(mkaos_service.run_minimal_acceptance_fixture(storage()))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/mkaos/acceptance/knowledge-asset-os")
    @router.post("/api/mkaos/acceptance/knowledge-asset-os")
    def knowledge_asset_os_acceptance(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return _mkaos_response(mkaos_service.run_mkaos_acceptance_suite(storage(), payload))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router

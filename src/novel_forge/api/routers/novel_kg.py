from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.novel_kg import (
    adjudicate_kg_identity_candidate,
    analyze_novel_kg_conflicts,
    build_novel_kg,
    build_novel_kg_context,
    build_novel_kg_cypher,
    create_kg_identity_resolution,
    create_novel_kg_snapshot,
    evaluate_novel_kg_gate,
    novel_kg_dirty_status,
    query_novel_kg,
    query_novel_kg_impact,
    query_novel_kg_paths,
    refresh_novel_kg,
)
from novel_forge.modules.semantic_enhancement import create_semantic_extraction_report
from novel_forge.storage.local import LocalStorage


def create_router(ctx: ProductRouterContext) -> APIRouter:
    app_settings = ctx.app_settings
    models = ctx.models
    globals().update(models)
    router = APIRouter(tags=["product-novel-kg"])
    NovelKGSnapshotRequest = models["NovelKGSnapshotRequest"]
    NovelKGRefreshRequest = models["NovelKGRefreshRequest"]
    NovelKGGateRequest = models["NovelKGGateRequest"]
    NovelKGSemanticExtractionRequest = models["NovelKGSemanticExtractionRequest"]
    NovelKGIdentityResolutionRequest = models["NovelKGIdentityResolutionRequest"]
    NovelKGIdentityAdjudicationRequest = models["NovelKGIdentityAdjudicationRequest"]

    @router.get("/product/novel-kg/graph")
    def novel_kg_graph(
        project_id: str | None = None,
        workspace_path: str | None = None,
        limit: int = Query(default=1000, ge=1, le=5000),
        include_content_snapshot: bool = False,
    ) -> dict[str, Any]:
        try:
            return build_novel_kg(
                LocalStorage(app_settings.root),
                project_id=project_id,
                workspace_path=workspace_path,
                limit=limit,
                include_content_snapshot=include_content_snapshot,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/novel-kg/snapshot")
    def novel_kg_snapshot(request: NovelKGSnapshotRequest) -> dict[str, Any]:
        try:
            return create_novel_kg_snapshot(
                LocalStorage(app_settings.root),
                project_id=request.project_id,
                workspace_path=request.workspace_path,
                limit=request.limit,
                include_content_snapshot=request.include_content_snapshot,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/novel-kg/query")
    def novel_kg_query(
        snapshot_path: str | None = None,
        project_id: str | None = None,
        workspace_path: str | None = None,
        kind: str | None = None,
        entity_type: str | None = None,
        q: str | None = None,
        source_asset_id: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        try:
            return query_novel_kg(
                LocalStorage(app_settings.root),
                snapshot_path=snapshot_path,
                project_id=project_id,
                workspace_path=workspace_path,
                kind=kind,
                entity_type=entity_type,
                q=q,
                source_asset_id=source_asset_id,
                limit=limit,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/novel-kg/paths")
    def novel_kg_paths(
        snapshot_path: str | None = None,
        project_id: str | None = None,
        workspace_path: str | None = None,
        source: str = "",
        target: str = "",
        max_depth: int = Query(default=4, ge=1, le=8),
        relation_type: str | None = None,
        limit: int = Query(default=20, ge=1, le=100),
    ) -> dict[str, Any]:
        try:
            return query_novel_kg_paths(
                LocalStorage(app_settings.root),
                snapshot_path=snapshot_path,
                project_id=project_id,
                workspace_path=workspace_path,
                source=source,
                target=target,
                max_depth=max_depth,
                relation_type=relation_type,
                limit=limit,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/novel-kg/impact")
    def novel_kg_impact(
        snapshot_path: str | None = None,
        project_id: str | None = None,
        workspace_path: str | None = None,
        node: str = "",
        max_depth: int = Query(default=3, ge=1, le=8),
        direction: str = "out",
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        try:
            return query_novel_kg_impact(
                LocalStorage(app_settings.root),
                snapshot_path=snapshot_path,
                project_id=project_id,
                workspace_path=workspace_path,
                node=node,
                max_depth=max_depth,
                direction=direction,
                limit=limit,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/novel-kg/conflicts")
    def novel_kg_conflicts(
        snapshot_path: str | None = None,
        project_id: str | None = None,
        workspace_path: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        try:
            return analyze_novel_kg_conflicts(
                LocalStorage(app_settings.root),
                snapshot_path=snapshot_path,
                project_id=project_id,
                workspace_path=workspace_path,
                limit=limit,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/novel-kg/cypher")
    def novel_kg_cypher(
        q: str | None = None,
        kind: str | None = None,
        source: str | None = None,
        target: str | None = None,
        relation_type: str | None = None,
        max_depth: int = Query(default=4, ge=1, le=8),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        try:
            return build_novel_kg_cypher(q=q, kind=kind, source=source, target=target, relation_type=relation_type, max_depth=max_depth, limit=limit)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/novel-kg/context")
    def novel_kg_context(
        target_path: str | None = None,
        q: str = "",
        project_id: str | None = None,
        workspace_path: str | None = None,
        limit: int = Query(default=8, ge=1, le=100),
    ) -> dict[str, Any]:
        try:
            return build_novel_kg_context(
                LocalStorage(app_settings.root),
                target_path=target_path,
                query=q,
                project_id=project_id,
                workspace_path=workspace_path,
                limit=limit,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/novel-kg/gate")
    def novel_kg_gate(request: NovelKGGateRequest) -> dict[str, Any]:
        try:
            return evaluate_novel_kg_gate(
                LocalStorage(app_settings.root),
                target_path=request.target_path,
                project_id=request.project_id,
                workspace_path=request.workspace_path,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/novel-kg/semantic-extraction")
    def novel_kg_semantic_extraction(request: NovelKGSemanticExtractionRequest) -> dict[str, Any]:
        try:
            return create_semantic_extraction_report(
                LocalStorage(app_settings.root),
                target_path=request.target_path,
                project_id=request.project_id,
                workspace_path=request.workspace_path,
                extractor_model=request.extractor_model,
                limit=request.limit,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/novel-kg/identity-resolution")
    def novel_kg_identity_resolution(request: NovelKGIdentityResolutionRequest) -> dict[str, Any]:
        try:
            storage = LocalStorage(app_settings.root)
            graph = None
            if not request.snapshot_path:
                graph = build_novel_kg(
                    storage,
                    project_id=request.project_id,
                    workspace_path=request.workspace_path,
                    limit=1000,
                    include_content_snapshot=False,
                )
            return create_kg_identity_resolution(
                storage,
                snapshot_path=request.snapshot_path,
                graph=graph,
                project_id=request.project_id,
                workspace_path=request.workspace_path,
                min_confidence=request.min_confidence,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/novel-kg/identity-resolution/adjudicate")
    def novel_kg_identity_adjudication(request: NovelKGIdentityAdjudicationRequest) -> dict[str, Any]:
        try:
            return adjudicate_kg_identity_candidate(
                LocalStorage(app_settings.root),
                resolution_path_or_id=request.resolution_path_or_id,
                candidate_id=request.candidate_id,
                decision=request.decision,
                actor=request.actor,
                note=request.note,
                apply_merge=request.apply_merge,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/novel-kg/dirty")
    def novel_kg_dirty(project_id: str | None = None, workspace_path: str | None = None) -> dict[str, Any]:
        try:
            return novel_kg_dirty_status(LocalStorage(app_settings.root), project_id=project_id, workspace_path=workspace_path)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/novel-kg/refresh")
    def novel_kg_refresh(request: NovelKGRefreshRequest) -> dict[str, Any]:
        try:
            return refresh_novel_kg(
                LocalStorage(app_settings.root),
                project_id=request.project_id,
                workspace_path=request.workspace_path,
                changed_asset_path=request.changed_asset_path,
                apply_invalidation=request.apply_invalidation,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router

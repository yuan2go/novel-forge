from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request

from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.canon_graph import (
    build_canon_graph,
    check_canon_graph_conflicts,
    create_canon_change_approval,
    diff_canon_graph,
    locate_canon_graph_impacted_chapters,
    persist_canon_graph_issues,
    propagate_canon_graph_conflicts,
    query_canon_graph,
    query_canon_graph_paths,
    reason_canon_graph,
    resolve_canon_change_approval,
    run_canon_graph_plugin,
)
from novel_forge.storage.local import LocalStorage


def create_router(ctx: ProductRouterContext) -> APIRouter:
    router = APIRouter(tags=["product-canon-graph"])
    app_settings = ctx.app_settings

    @router.get("/product/canon-graph/query")
    def canon_graph_query(
        project_id: str | None = None,
        workspace_path: str | None = None,
        query: str = "",
        node_type: list[str] | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        return query_canon_graph(
            LocalStorage(app_settings.root),
            {
                "project_id": project_id or "",
                "workspace_path": workspace_path or "",
                "query": query,
                "node_types": node_type or [],
                "limit": limit,
            },
        )

    @router.get("/product/canon-graph/snapshot")
    def canon_graph_snapshot(project_id: str | None = None, workspace_path: str | None = None, persist: bool = False) -> dict[str, Any]:
        return build_canon_graph(LocalStorage(app_settings.root), project_id=project_id, workspace_path=workspace_path, persist=persist)

    @router.post("/product/canon-graph/reason")
    async def canon_graph_reason(request: Request) -> dict[str, Any]:
        return reason_canon_graph(LocalStorage(app_settings.root), await request.json())

    @router.post("/product/canon-graph/paths")
    async def canon_graph_paths(request: Request) -> dict[str, Any]:
        return query_canon_graph_paths(LocalStorage(app_settings.root), await request.json())

    @router.post("/product/canon-graph/check")
    async def canon_graph_check(request: Request) -> dict[str, Any]:
        return check_canon_graph_conflicts(LocalStorage(app_settings.root), await request.json())

    @router.post("/product/canon-graph/plugin")
    async def canon_graph_plugin(request: Request) -> dict[str, Any]:
        return run_canon_graph_plugin(LocalStorage(app_settings.root), await request.json())

    @router.post("/product/canon-graph/issues")
    async def canon_graph_issues(request: Request) -> dict[str, Any]:
        return persist_canon_graph_issues(LocalStorage(app_settings.root), await request.json())

    @router.post("/product/canon-graph/diff")
    async def canon_graph_diff(request: Request) -> dict[str, Any]:
        return diff_canon_graph(LocalStorage(app_settings.root), await request.json())

    @router.post("/product/canon-graph/propagate-conflicts")
    async def canon_graph_propagate_conflicts(request: Request) -> dict[str, Any]:
        return propagate_canon_graph_conflicts(LocalStorage(app_settings.root), await request.json())

    @router.post("/product/canon-graph/impact-chapters")
    async def canon_graph_impact_chapters(request: Request) -> dict[str, Any]:
        return locate_canon_graph_impacted_chapters(LocalStorage(app_settings.root), await request.json())

    @router.post("/product/canon-graph/approvals")
    async def canon_graph_create_approval(request: Request) -> dict[str, Any]:
        return create_canon_change_approval(LocalStorage(app_settings.root), await request.json())

    @router.post("/product/canon-graph/approvals/{approval_id}/resolve")
    async def canon_graph_resolve_approval(approval_id: str, request: Request) -> dict[str, Any]:
        return resolve_canon_change_approval(LocalStorage(app_settings.root), approval_id, await request.json())

    return router

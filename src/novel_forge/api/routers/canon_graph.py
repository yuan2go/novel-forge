from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request

from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.canon_graph import build_canon_graph, check_canon_graph_conflicts, persist_canon_graph_issues, query_canon_graph, query_canon_graph_paths, reason_canon_graph
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

    @router.post("/product/canon-graph/issues")
    async def canon_graph_issues(request: Request) -> dict[str, Any]:
        return persist_canon_graph_issues(LocalStorage(app_settings.root), await request.json())

    return router

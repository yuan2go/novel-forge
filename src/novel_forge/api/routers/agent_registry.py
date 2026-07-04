from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query

from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.agent_registry import (
    agent_registry_coverage,
    create_agent_capability,
    create_agent_evaluation_binding,
    create_agent_registry_snapshot,
    create_agent_version,
    list_agent_registry_entries,
    record_agent_lifecycle_event,
    resolve_agent_registry_entry,
    sync_runtime_profiles,
    upsert_agent_registry_entry,
)
from novel_forge.storage.local import LocalStorage


def create_router(ctx: ProductRouterContext) -> APIRouter:
    app_settings = ctx.app_settings
    router = APIRouter(prefix="/product/agent-registry", tags=["product-agent-registry"])

    @router.get("/entries")
    def entries(lifecycle_state: str | None = None, limit: int = Query(default=500, ge=1, le=2000)) -> list[dict[str, Any]]:
        try:
            return list_agent_registry_entries(LocalStorage(app_settings.root), lifecycle_state=lifecycle_state, limit=limit)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/sync-runtime-profiles")
    def sync_profiles(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return sync_runtime_profiles(LocalStorage(app_settings.root), default_state=str(payload.get("default_state") or "active"))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/entry")
    def create_entry(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return upsert_agent_registry_entry(LocalStorage(app_settings.root), payload)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.patch("/entry/{agent_id}")
    def patch_entry(agent_id: str, payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return upsert_agent_registry_entry(LocalStorage(app_settings.root), {**payload, "agent_id": agent_id})
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/version")
    def version(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return create_agent_version(
                LocalStorage(app_settings.root),
                agent_id=str(payload.get("agent_id") or ""),
                version=str(payload.get("version") or "v1"),
                status=str(payload.get("status") or "active"),
                runtime_profile=payload.get("runtime_profile") if isinstance(payload.get("runtime_profile"), dict) else {},
                notes=str(payload.get("notes") or ""),
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/lifecycle")
    def lifecycle(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return record_agent_lifecycle_event(
                LocalStorage(app_settings.root),
                agent_id=str(payload.get("agent_id") or ""),
                to_state=str(payload.get("to_state") or payload.get("lifecycle_state") or "draft"),
                reason=str(payload.get("reason") or ""),
                actor=str(payload.get("actor") or "operator"),
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/capability")
    def capability(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return create_agent_capability(
                LocalStorage(app_settings.root),
                agent_id=str(payload.get("agent_id") or ""),
                capability_id=str(payload.get("capability_id") or ""),
                capability_type=str(payload.get("capability_type") or "operation"),
                status=str(payload.get("status") or "active"),
                payload=payload.get("payload") if isinstance(payload.get("payload"), dict) else {},
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/evaluation-binding")
    def evaluation_binding(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return create_agent_evaluation_binding(
                LocalStorage(app_settings.root),
                agent_id=str(payload.get("agent_id") or ""),
                evaluation_suite_id=str(payload.get("evaluation_suite_id") or ""),
                gate_policy=payload.get("gate_policy") if isinstance(payload.get("gate_policy"), dict) else {},
                status=str(payload.get("status") or "active"),
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/snapshot")
    def snapshot(project_id: str | None = None) -> dict[str, Any]:
        try:
            return create_agent_registry_snapshot(LocalStorage(app_settings.root), project_id=project_id or "")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/resolve")
    def resolve(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return resolve_agent_registry_entry(
                LocalStorage(app_settings.root),
                agent_id=str(payload.get("agent_id") or ""),
                operation=str(payload.get("operation") or ""),
                environment=str(payload.get("environment") or ""),
                require_schedulable=bool(payload.get("require_schedulable", False)),
                auto_sync=bool(payload.get("auto_sync", True)),
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/coverage")
    def coverage() -> dict[str, Any]:
        try:
            return agent_registry_coverage(LocalStorage(app_settings.root))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router

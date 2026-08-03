"""Project/Workspace routes backed exclusively by PostgreSQL Authority."""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query

from novel_forge.api.authority_dependencies import (
    authority_release_identity,
    build_trusted_principal_resolver,
)
from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.project_authority import (
    ProjectAuthorityApplication,
    ProjectAuthorityCommand,
    ProjectAuthorityQuery,
)


def create_router(ctx: ProductRouterContext) -> APIRouter:
    router = APIRouter(tags=["authority-projects"])
    models = ctx.models
    globals().update(models)
    ProjectCreateRequest = models["ProjectCreateRequest"]
    ProjectConfigRequest = models["ProjectConfigRequest"]
    ProjectDuplicateRequest = models["ProjectDuplicateRequest"]
    ProjectBindingAssignRequest = models["ProjectBindingAssignRequest"]
    ProjectBindingRemoveRequest = models["ProjectBindingRemoveRequest"]
    ProjectScopeAuditRequest = models["ProjectScopeAuditRequest"]

    @router.get("/product/projects")
    def projects(include_deleted: bool = False) -> list[dict[str, Any]]:
        rows = _query(ctx).list_projects(include_deleted=include_deleted)
        principal = build_trusted_principal_resolver().resolve_api_principal()
        return [
            row for row in rows
            if principal.allows("project.authority.query", row["project_id"])
        ]

    @router.get("/product/projects/operating-dashboard")
    def operating_dashboard(
        limit: int = Query(default=20, ge=1, le=100)
    ) -> dict[str, Any]:
        dashboard = _query(ctx).operating_dashboard(limit=limit)
        principal = build_trusted_principal_resolver().resolve_api_principal()
        allowed = {
            row["project_id"] for row in dashboard["projects"]
            if principal.allows("project.authority.query", row["project_id"])
        }
        dashboard["projects"] = [
            row for row in dashboard["projects"] if row["project_id"] in allowed
        ]
        dashboard["today_priorities"] = [
            row for row in dashboard["today_priorities"]
            if row["project_id"] in allowed
        ]
        dashboard["bottlenecks"] = [
            row for row in dashboard["bottlenecks"] if row["project_id"] in allowed
        ]
        dashboard["summary"] = {
            "project_count": len(dashboard["projects"]),
            "active_project_count": sum(
                row["status"] == "ACTIVE" for row in dashboard["projects"]
            ),
            "high_risk_project_count": sum(
                row["risk_score"] >= 60 for row in dashboard["projects"]
            ),
            "blocked_project_count": sum(
                row["health"] == "BLOCKED" for row in dashboard["projects"]
            ),
            "average_investment_score": 0,
        }
        return dashboard

    @router.get("/product/series")
    def series(include_deleted: bool = False) -> list[dict[str, Any]]:
        projects = _query(ctx).list_projects(include_deleted=include_deleted)
        principal = build_trusted_principal_resolver().resolve_api_principal()
        projects = [
            project for project in projects
            if principal.allows("project.authority.query", project["project_id"])
        ]
        grouped: dict[str, list[dict[str, Any]]] = {}
        for project in projects:
            title = str(project.get("series_title") or "").strip()
            if title:
                grouped.setdefault(title, []).append(project)
        return [
            {
                "series_title": title,
                "project_count": len(items),
                "projects": sorted(
                    items, key=lambda row: (row.get("book_number") or 0, row["project_id"])
                ),
            }
            for title, items in sorted(grouped.items())
        ]

    @router.post("/product/projects")
    def create_project(request: ProjectCreateRequest) -> dict[str, Any]:
        payload = _model_data(request)
        project_id = str(payload.pop("project_id", None) or f"prj_{uuid4().hex}")
        workspace_id = str(payload.pop("workspace_id", None) or f"ws_{uuid4().hex}")
        idempotency_key = str(
            payload.pop("idempotency_key", None) or f"project-create:{project_id}"
        )
        return _execute(
            ctx,
            definition_name="project_lifecycle.create",
            project_id=project_id,
            workspace_id=workspace_id,
            payload=payload,
            expected_version=0,
            expected_asset_version_id="",
            idempotency_key=idempotency_key,
        )

    @router.patch("/product/projects/{project_id}/config")
    def update_project(project_id: str, request: ProjectConfigRequest) -> dict[str, Any]:
        _authorize_project(project_id, "project.authority.execute")
        current = _query(ctx).require_project(project_id)
        payload = {
            key: value
            for key, value in _model_data(request).items()
            if value is not None
        }
        requested_status = payload.pop("status", None)
        if requested_status is not None:
            raise HTTPException(
                status_code=422,
                detail="status changes must use the lifecycle transition endpoints",
            )
        return _execute(
            ctx,
            definition_name="project_lifecycle.update",
            project_id=project_id,
            workspace_id=current["workspace_id"],
            payload={"config": payload},
            expected_version=current["version"],
            expected_asset_version_id=current["asset_version_id"],
            idempotency_key=f"project-update:{project_id}:{current['version'] + 1}",
        )

    @router.post("/product/projects/{project_id}/duplicate")
    def duplicate_project(
        project_id: str, request: ProjectDuplicateRequest
    ) -> dict[str, Any]:
        _authorize_project(project_id, "project.authority.query")
        source = _query(ctx).require_project(project_id)
        override = _model_data(request)
        new_project_id = f"prj_{uuid4().hex}"
        new_workspace_id = f"ws_{uuid4().hex}"
        content = dict(source["content"])
        content.update(
            {key: value for key, value in override.items() if value is not None}
        )
        content["title"] = str(override.get("title") or f"{source['title']} Copy")
        content["source_project_id"] = project_id
        return _execute(
            ctx,
            definition_name="project_lifecycle.create",
            project_id=new_project_id,
            workspace_id=new_workspace_id,
            payload=content,
            expected_version=0,
            expected_asset_version_id="",
            idempotency_key=f"project-clone:{project_id}:{new_project_id}",
        )

    def lifecycle(project_id: str, target: str) -> dict[str, Any]:
        _authorize_project(project_id, "project.authority.execute")
        current = _query(ctx).require_project(project_id)
        return _execute(
            ctx,
            definition_name="project_lifecycle.transition",
            project_id=project_id,
            workspace_id=current["workspace_id"],
            payload={"target_status": target},
            expected_version=current["version"],
            expected_asset_version_id=current["asset_version_id"],
            idempotency_key=f"project-transition:{project_id}:{current['version']}:{target}",
        )

    @router.post("/product/projects/{project_id}/archive")
    def archive_project(project_id: str) -> dict[str, Any]:
        return lifecycle(project_id, "ARCHIVED")

    @router.post("/product/projects/{project_id}/pause")
    def pause_project(project_id: str) -> dict[str, Any]:
        return lifecycle(project_id, "PAUSED")

    @router.post("/product/projects/{project_id}/restore")
    def restore_project(project_id: str) -> dict[str, Any]:
        return lifecycle(project_id, "ACTIVE")

    @router.delete("/product/projects/{project_id}")
    def delete_project(project_id: str) -> dict[str, Any]:
        return lifecycle(project_id, "DELETED")

    @router.get("/product/projects/{project_id}/assets")
    def project_assets(
        project_id: str,
        category: str | None = None,
        asset_type: str | None = Query(default=None, alias="type"),
        keyword: str | None = None,
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> list[dict[str, Any]]:
        _authorize_project(project_id, "project.authority.query")
        return _query(ctx).list_assets(
            project_id=project_id,
            category=category,
            asset_type=asset_type,
            keyword=keyword,
            limit=limit,
        )

    @router.get("/product/projects/{project_id}/bindings")
    def project_bindings(project_id: str) -> list[dict[str, Any]]:
        _authorize_project(project_id, "project.authority.query")
        return _query(ctx).list_bindings(project_id=project_id)

    @router.put("/product/projects/{project_id}/bindings/{binding_type}")
    def assign_project_binding(
        project_id: str,
        binding_type: str,
        request: ProjectBindingAssignRequest,
    ) -> dict[str, Any]:
        _authorize_project(project_id, "project.authority.execute")
        current = _query(ctx).require_project(project_id)
        if (
            request.expected_project_version != current["version"]
            or request.expected_project_asset_version_id != current["asset_version_id"]
        ):
            raise HTTPException(
                status_code=409,
                detail="expected Project version does not match PostgreSQL Authority",
            )
        normalized_type = binding_type.strip().upper()
        result = _execute(
            ctx,
            definition_name="project_binding.assign",
            project_id=project_id,
            workspace_id=current["workspace_id"],
            payload={
                "binding_type": normalized_type,
                "target_asset_version_id": request.target_asset_version_id,
                "expected_binding_asset_version_id": (
                    request.expected_binding_asset_version_id
                ),
            },
            expected_version=current["version"],
            expected_asset_version_id=current["asset_version_id"],
            idempotency_key=(
                request.idempotency_key
                or (
                    f"project-binding:{project_id}:{normalized_type}:"
                    f"{request.target_asset_version_id}:"
                    f"{request.expected_binding_asset_version_id or 'initial'}"
                )
            ),
        )
        return {**result, "bindings": _query(ctx).list_bindings(project_id=project_id)}

    @router.post("/product/projects/{project_id}/bindings/{binding_type}/remove")
    def remove_project_binding(
        project_id: str,
        binding_type: str,
        request: ProjectBindingRemoveRequest,
    ) -> dict[str, Any]:
        _authorize_project(project_id, "project.authority.execute")
        current = _query(ctx).require_project(project_id)
        if (
            request.expected_project_version != current["version"]
            or request.expected_project_asset_version_id != current["asset_version_id"]
        ):
            raise HTTPException(
                status_code=409,
                detail="expected Project version does not match PostgreSQL Authority",
            )
        normalized_type = binding_type.strip().upper()
        result = _execute(
            ctx,
            definition_name="project_binding.remove",
            project_id=project_id,
            workspace_id=current["workspace_id"],
            payload={
                "binding_type": normalized_type,
                "expected_binding_asset_version_id": (
                    request.expected_binding_asset_version_id
                ),
            },
            expected_version=current["version"],
            expected_asset_version_id=current["asset_version_id"],
            idempotency_key=(
                request.idempotency_key
                or (
                    f"project-binding-remove:{project_id}:{normalized_type}:"
                    f"{request.expected_binding_asset_version_id}"
                )
            ),
        )
        return {**result, "bindings": _query(ctx).list_bindings(project_id=project_id)}

    @router.get("/product/projects/{project_id}")
    def project_detail(project_id: str) -> dict[str, Any]:
        _authorize_project(project_id, "project.authority.query")
        return _query(ctx).require_project(project_id)

    @router.get("/product/projects/audit/scope")
    def scope_audit(project_id: str | None = None) -> dict[str, Any]:
        _authorize_project(project_id or "", "project.authority.query")
        return _query(ctx).scope_audit(project_id=project_id)

    @router.post("/product/projects/audit/scope")
    def repair_scope(request: ProjectScopeAuditRequest) -> dict[str, Any]:
        _authorize_project(request.project_id or "", "project.authority.query")
        if request.repair:
            raise HTTPException(
                status_code=409,
                detail="Authority scope violations require a traceable repair Operation",
            )
        return _query(ctx).scope_audit(project_id=request.project_id)

    return router


def _application(ctx: ProductRouterContext) -> ProjectAuthorityApplication:
    application = getattr(ctx.services, "project_authority_application", None)
    if application is not None:
        return application
    build_id, commit_sha = authority_release_identity()
    return ProjectAuthorityApplication(
        ctx.app_settings.database_url,
        application_build_id=build_id,
        commit_sha=commit_sha,
    )


def _query(ctx: ProductRouterContext) -> ProjectAuthorityQuery:
    query = getattr(ctx.services, "project_authority_query", None)
    return query or ProjectAuthorityQuery(ctx.app_settings.database_url)


def _authorize_project(project_id: str, permission: str) -> None:
    principal = build_trusted_principal_resolver().resolve_api_principal()
    if not project_id:
        if "*" not in principal.project_scope:
            raise HTTPException(
                status_code=403,
                detail="a project_id is required for a project-scoped Authority principal",
            )
        return
    try:
        principal.require(permission, project_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _execute(
    ctx: ProductRouterContext,
    *,
    definition_name: str,
    project_id: str,
    workspace_id: str,
    payload: dict[str, Any],
    expected_version: int,
    expected_asset_version_id: str,
    idempotency_key: str,
) -> dict[str, Any]:
    try:
        principal = build_trusted_principal_resolver().resolve_api_principal()
        result = _application(ctx).execute(
            ProjectAuthorityCommand(
                definition_name=definition_name,
                project_id=project_id,
                workspace_id=workspace_id,
                actor_id=principal.principal_id,
                idempotency_key=idempotency_key,
                trace_id=f"trace:{uuid4()}",
                correlation_id=f"correlation:{uuid4()}",
                payload=payload,
                expected_version=expected_version,
                expected_current_asset_version_id=expected_asset_version_id,
            ),
            principal=principal,
        )
        return {**result, **_query(ctx).require_project(project_id)}
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except KernelError as exc:
        status = 404 if exc.code == "PROJECT_NOT_FOUND" else 409
        raise HTTPException(
            status_code=status, detail={"code": exc.code, "message": exc.message}
        ) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _model_data(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


__all__ = ["create_router"]

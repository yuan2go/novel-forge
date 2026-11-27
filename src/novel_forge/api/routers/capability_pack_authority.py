from __future__ import annotations

from datetime import datetime
from typing import Any, Callable
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from novel_forge.api.authority_dependencies import build_trusted_principal_resolver
from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.capability_pack_authority.application import (
    CapabilityPackAuthorityCommand,
)
from novel_forge.modules.command_kernel.errors import KernelError


class CapabilityPackCommandRequest(BaseModel):
    project_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    pack_id: str = Field(min_length=1)
    pack_version: str = ""
    compilation_id: str = ""
    deployment_id: str = ""
    rollout_id: str = ""
    expected_activation_version: int = Field(default=0, ge=0)
    idempotency_key: str = Field(min_length=1)
    trace_id: str = ""
    correlation_id: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


def create_router(ctx: ProductRouterContext) -> APIRouter:
    router = APIRouter(prefix="/api/capability-packs", tags=["capability-packs"])
    application = ctx.services.capability_pack_authority_application
    query = ctx.services.capability_pack_authority_query

    def execute(
        action: str,
        request: CapabilityPackCommandRequest,
        *,
        pack_id: str = "",
        pack_version: str = "",
        compilation_id: str = "",
        deployment_id: str = "",
        rollout_id: str = "",
    ) -> dict[str, Any]:
        try:
            principal = build_trusted_principal_resolver().resolve_api_principal()
            return application.execute(
                CapabilityPackAuthorityCommand(
                    definition_name=action,
                    project_id=request.project_id,
                    workspace_id=request.workspace_id,
                    actor_id=principal.principal_id,
                    pack_id=pack_id or request.pack_id,
                    pack_version=pack_version or request.pack_version,
                    compilation_id=compilation_id or request.compilation_id,
                    deployment_id=deployment_id or request.deployment_id,
                    rollout_id=rollout_id or request.rollout_id,
                    expected_activation_version=request.expected_activation_version,
                    idempotency_key=request.idempotency_key,
                    trace_id=request.trace_id or f"trace:capability-pack:{uuid4()}",
                    correlation_id=(
                        request.correlation_id
                        or f"correlation:capability-pack:{uuid4()}"
                    ),
                    payload=request.payload,
                ),
                principal=principal,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KernelError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def authorize_query(project_id: str) -> None:
        principal = build_trusted_principal_resolver().resolve_api_principal()
        principal.require("capability_pack.authority.query", project_id)

    def execute_query(
        project_id: str, operation: Callable[[], Any]
    ) -> Any:
        try:
            authorize_query(project_id)
            return operation()
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KernelError as exc:
            raise HTTPException(
                status_code=404,
                detail={"code": exc.code, "message": exc.message},
            ) from exc

    @router.post("/register")
    def register(request: CapabilityPackCommandRequest) -> dict[str, Any]:
        return execute("capability_pack.manifest.register", request)

    @router.post("/{pack_id}/{pack_version}/validate")
    def validate(
        pack_id: str, pack_version: str, request: CapabilityPackCommandRequest
    ) -> dict[str, Any]:
        return execute(
            "capability_pack.manifest.validate",
            request,
            pack_id=pack_id,
            pack_version=pack_version,
        )

    @router.post("/{pack_id}/{pack_version}/compile")
    def compile_pack(
        pack_id: str, pack_version: str, request: CapabilityPackCommandRequest
    ) -> dict[str, Any]:
        return execute(
            "capability_pack.compile",
            request,
            pack_id=pack_id,
            pack_version=pack_version,
        )

    @router.post("/compilations/{compilation_id}/approve")
    def approve(
        compilation_id: str, request: CapabilityPackCommandRequest
    ) -> dict[str, Any]:
        return execute(
            "capability_pack.approval.decide",
            request,
            compilation_id=compilation_id,
        )

    @router.post("/compilations/{compilation_id}/validation-admission")
    def validation_admission(compilation_id: str, request: CapabilityPackCommandRequest) -> dict[str, Any]:
        return execute("capability_pack.validation.admit", request, compilation_id=compilation_id)

    @router.post("/deployments")
    def create_deployment(
        request: CapabilityPackCommandRequest,
    ) -> dict[str, Any]:
        return execute("capability_pack.deployment.create", request)

    @router.post("/deployments/{deployment_id}/activate")
    def activate(
        deployment_id: str, request: CapabilityPackCommandRequest
    ) -> dict[str, Any]:
        return execute(
            "capability_pack.deployment.activate",
            request,
            deployment_id=deployment_id,
        )

    @router.post("/deployments/{deployment_id}/disable")
    def disable(
        deployment_id: str, request: CapabilityPackCommandRequest
    ) -> dict[str, Any]:
        return execute(
            "capability_pack.deployment.disable",
            request,
            deployment_id=deployment_id,
        )

    @router.post("/rollouts")
    def start_rollout(request: CapabilityPackCommandRequest) -> dict[str, Any]:
        return execute("capability_pack.rollout.start", request)

    @router.post("/rollouts/{rollout_id}/{control}")
    def control_rollout(
        rollout_id: str, control: str, request: CapabilityPackCommandRequest
    ) -> dict[str, Any]:
        if control not in {"pause", "resume", "complete"}:
            raise HTTPException(status_code=404, detail="unsupported rollout control")
        return execute(
            f"capability_pack.rollout.{control}",
            request,
            rollout_id=rollout_id,
        )

    @router.post("/deployments/{deployment_id}/rollback")
    def rollback(
        deployment_id: str, request: CapabilityPackCommandRequest
    ) -> dict[str, Any]:
        return execute(
            "capability_pack.rollback",
            request,
            deployment_id=deployment_id,
        )

    @router.post("/{pack_id}/{pack_version}/{lifecycle_action}")
    def lifecycle(
        pack_id: str,
        pack_version: str,
        lifecycle_action: str,
        request: CapabilityPackCommandRequest,
    ) -> dict[str, Any]:
        if lifecycle_action not in {"deprecate", "retire", "revoke"}:
            raise HTTPException(status_code=404, detail="unsupported lifecycle action")
        return execute(
            f"capability_pack.{lifecycle_action}",
            request,
            pack_id=pack_id,
            pack_version=pack_version,
        )

    @router.get("/versions")
    def list_versions(
        project_id: str = Query(..., min_length=1), pack_id: str = ""
    ) -> list[dict[str, Any]]:
        return execute_query(
            project_id,
            lambda: query.list_versions(project_id=project_id, pack_id=pack_id),
        )

    @router.get("/versions/{pack_id}/{pack_version}")
    def version_detail(
        pack_id: str, pack_version: str, project_id: str = Query(..., min_length=1)
    ) -> dict[str, Any]:
        return execute_query(
            project_id,
            lambda: query.version_detail(
                project_id=project_id,
                pack_id=pack_id,
                pack_version=pack_version,
            ),
        )

    @router.get("/deployments/list")
    def list_deployments(
        project_id: str = Query(..., min_length=1),
        pack_id: str = "",
        environment: str = "",
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return execute_query(
            project_id,
            lambda: query.list_deployments(
                pack_id=pack_id,
                project_id=project_id,
                environment=environment,
                limit=limit,
            ),
        )

    @router.get("/deployments/{deployment_id}")
    def deployment_detail(
        deployment_id: str, project_id: str = Query(..., min_length=1)
    ) -> dict[str, Any]:
        return execute_query(
            project_id,
            lambda: query.deployment_detail(
                deployment_id, project_id=project_id
            ),
        )

    @router.get("/rollouts/{rollout_id}")
    def rollout_detail(
        rollout_id: str, project_id: str = Query(..., min_length=1)
    ) -> dict[str, Any]:
        return execute_query(
            project_id,
            lambda: query.rollout_detail(rollout_id, project_id=project_id),
        )

    @router.get("/deployments/{deployment_id}/drift")
    def drift(
        deployment_id: str, project_id: str = Query(..., min_length=1)
    ) -> dict[str, Any]:
        return execute_query(
            project_id,
            lambda: query.drift_report(deployment_id, project_id=project_id),
        )

    @router.get("/deployments/{deployment_id}/usage")
    def usage(
        deployment_id: str,
        project_id: str = Query(..., min_length=1),
        workspace_id: str = "",
        book_id: str = "",
        workflow_node_id: str = "",
        agent_id: str = "",
        provider_id: str = "",
        model_id: str = "",
        started_after: datetime | None = None,
        started_before: datetime | None = None,
    ) -> dict[str, Any]:
        return execute_query(
            project_id,
            lambda: query.usage_metrics(
                deployment_id,
                project_id=project_id,
                workspace_id=workspace_id,
                book_id=book_id,
                workflow_node_id=workflow_node_id,
                agent_id=agent_id,
                provider_id=provider_id,
                model_id=model_id,
                started_after=started_after,
                started_before=started_before,
            ),
        )

    @router.get("/usage")
    def usage_by_dimensions(
        project_id: str = Query(..., min_length=1),
        pack_id: str = "",
        pack_version: str = "",
        compilation_hash: str = "",
        deployment_id: str = "",
        binding_set_hash: str = "",
        workspace_id: str = "",
        book_id: str = "",
        workflow_node_id: str = "",
        agent_id: str = "",
        provider_id: str = "",
        model_id: str = "",
        started_after: datetime | None = None,
        started_before: datetime | None = None,
    ) -> dict[str, Any]:
        return execute_query(
            project_id,
            lambda: query.usage_metrics_by_dimensions(
                project_id=project_id,
                pack_id=pack_id,
                pack_version=pack_version,
                compilation_hash=compilation_hash,
                deployment_id=deployment_id,
                binding_set_hash=binding_set_hash,
                workspace_id=workspace_id,
                book_id=book_id,
                workflow_node_id=workflow_node_id,
                agent_id=agent_id,
                provider_id=provider_id,
                model_id=model_id,
                started_after=started_after,
                started_before=started_before,
            ),
        )

    return router


__all__ = ["CapabilityPackCommandRequest", "create_router"]

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from novel_forge.api.authority_dependencies import build_trusted_principal_resolver
from novel_forge.api.models import (
    AuthorityOperationCancelRequest,
    AuthorityOperationControlRequest,
    AuthorityOutboxRecoveryRequest,
)
from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.command_kernel.cancellation import CancelCommand, request_cancellation
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.recovery import (
    RecoverOperationCommand,
    recover_operation,
)
from novel_forge.modules.authority_security import Principal
from novel_forge.modules.task_authority import (
    OutboxRecoveryCommand,
    requeue_outbox_dead_letter,
)


def create_router(ctx: ProductRouterContext) -> APIRouter:
    query = ctx.services.task_authority_query
    database_url = ctx.app_settings.database_url
    router = APIRouter(tags=["authority-tasks"])

    @router.get("/product/tasks")
    def tasks(
        status: str = "",
        task_type: str = "",
        project_id: str = "",
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        _authorize("task.authority.query", project_id)
        try:
            return query.list_tasks(
                project_id=project_id,
                status=status,
                definition_name=task_type,
                offset=offset,
                limit=limit,
            )
        except (KernelError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/tasks/timeline")
    def timeline(
        project_id: str = "",
        operation_id: str = "",
        limit: int = Query(default=200, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        _authorize("task.authority.query", project_id)
        return query.timeline(
            project_id=project_id, operation_id=operation_id, limit=limit
        )

    @router.get("/product/tasks/recovery-workbench")
    def recovery_workbench(
        project_id: str = "", limit: int = Query(default=100, ge=1, le=500)
    ) -> dict[str, Any]:
        _authorize("task.authority.query", project_id)
        return query.recovery_workbench(project_id=project_id, limit=limit)

    @router.get("/product/tasks/control")
    def task_control(project_id: str = "") -> dict[str, Any]:
        _authorize("system.authority.query", project_id)
        health = query.system_health(project_id=project_id)
        return {
            "authority": "postgresql",
            "celery": health["celery"],
            "config": health["task_control"],
            "queue_trend": [],
            "scheduler": {
                "kind": "authority_worker",
                "workers": health["workers"],
                "readiness": health["readiness"],
                "outbox_lag": health["outbox_lag"],
            },
            "dead_letters": {"count": health["dead_letter_count"]},
        }

    @router.get("/product/tasks/dead-letters")
    def dead_letters(
        project_id: str = "", limit: int = Query(default=100, ge=1, le=500)
    ) -> list[dict[str, Any]]:
        _authorize("task.authority.query", project_id)
        workbench = query.recovery_workbench(project_id=project_id, limit=limit)
        rows = [
            {
                **item,
                "id": item["operation_id"],
                "path": f"authority://operation/{item['operation_id']}",
                "task_id": item["operation_id"],
                "task_name": item["definition_name"],
                "error_message": str((item.get("metadata") or {}).get("error") or ""),
                "created_at": item["updated_at"],
                "kind": "operation",
            }
            for item in workbench["operations"]
            if item["status"] == "DEAD_LETTER"
        ]
        rows.extend(
            {
                **item,
                "id": item["outbox_id"],
                "path": f"authority://outbox/{item['outbox_id']}",
                "task_id": item["outbox_id"],
                "task_name": item["topic"],
                "error_message": item["last_error"],
                "created_at": item["updated_at"],
                "kind": "outbox",
            }
            for item in workbench["outbox_dead_letters"]
        )
        return rows[:limit]

    @router.post("/product/tasks/cancel")
    def cancel(request: AuthorityOperationCancelRequest) -> dict[str, Any]:
        principal = _authorize("task.authority.cancel", request.project_id)
        try:
            return request_cancellation(
                database_url,
                CancelCommand(
                    operation_id=request.operation_id,
                    project_id=request.project_id,
                    actor_id=principal.principal_id,
                    reason=request.reason,
                    expected_version=request.expected_version,
                    idempotency_key=request.idempotency_key,
                    trace_id=request.trace_id,
                    correlation_id=request.correlation_id,
                ),
            )
        except KernelError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/product/tasks/{operation_id}/recover", status_code=202)
    def recover(
        operation_id: str, request: AuthorityOperationControlRequest
    ) -> dict[str, Any]:
        principal = _authorize("task.authority.recover", request.project_id)
        if request.expected_version is None:
            raise HTTPException(status_code=422, detail="expected_version is required")
        try:
            result = recover_operation(
                database_url,
                RecoverOperationCommand(
                    operation_id=operation_id,
                    project_id=request.project_id,
                    actor_id=principal.principal_id,
                    expected_version=request.expected_version,
                    idempotency_key=request.idempotency_key,
                    reason=request.reason,
                    trace_id=(
                        request.trace_id.strip()
                        or f"trace:task-recovery:{request.idempotency_key}"
                    ),
                    correlation_id=(
                        request.correlation_id.strip()
                        or f"correlation:task-recovery:{request.idempotency_key}"
                    ),
                    gate_evidence_id=request.gate_evidence_id,
                ),
            )
            return {
                **result,
                "task": query.require_task(
                    project_id=request.project_id, operation_id=operation_id
                ),
            }
        except KernelError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": exc.message},
            ) from exc

    @router.post("/product/tasks/outbox/{outbox_id}/requeue", status_code=202)
    def requeue_outbox(
        outbox_id: str, request: AuthorityOutboxRecoveryRequest
    ) -> dict[str, Any]:
        principal = _authorize("task.authority.recover", request.project_id)
        try:
            return requeue_outbox_dead_letter(
                database_url,
                OutboxRecoveryCommand(
                    outbox_id=outbox_id,
                    project_id=request.project_id,
                    actor_id=principal.principal_id,
                    expected_attempt_count=request.expected_attempt_count,
                    idempotency_key=request.idempotency_key,
                    reason=request.reason,
                    trace_id=(
                        request.trace_id.strip()
                        or f"trace:outbox-recovery:{request.idempotency_key}"
                    ),
                    correlation_id=(
                        request.correlation_id.strip()
                        or f"correlation:outbox-recovery:{request.idempotency_key}"
                    ),
                ),
                principal=principal,
            )
        except (KernelError, PermissionError) as exc:
            if isinstance(exc, PermissionError):
                raise HTTPException(status_code=403, detail=str(exc)) from exc
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": exc.message},
            ) from exc

    @router.get("/product/system/health")
    def system_health(project_id: str = "") -> dict[str, Any]:
        _authorize("system.authority.query", project_id)
        try:
            return query.system_health(project_id=project_id)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.get("/product/system/authority-health")
    def authority_health(project_id: str = "") -> dict[str, Any]:
        return system_health(project_id=project_id)

    # Keep the dynamic path after all fixed /product/tasks/* routes.
    @router.get("/product/tasks/{operation_id}")
    def task(operation_id: str, project_id: str) -> dict[str, Any]:
        _authorize("task.authority.query", project_id)
        try:
            return query.require_task(project_id=project_id, operation_id=operation_id)
        except KernelError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return router


def _authorize(permission: str, project_id: str) -> Principal:
    principal = build_trusted_principal_resolver().resolve_api_principal()
    if not project_id:
        if "*" not in principal.project_scope:
            raise HTTPException(
                status_code=403,
                detail="a project_id is required for a project-scoped Authority principal",
            )
        return principal
    try:
        principal.require(permission, project_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return principal


__all__ = ["create_router"]

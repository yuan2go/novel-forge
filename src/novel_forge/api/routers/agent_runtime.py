from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from novel_forge.api.authority_dependencies import build_trusted_principal_resolver
from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.agent_runtime.application import (
    AgentHarnessAdmissionRequest,
    AgentRuntimeAdminCommand,
)
from novel_forge.modules.agent_runtime.unsent_recovery import AgentUnsentRecoveryRequest
from novel_forge.modules.agent_runtime.harness import (
    AcceptedBoundaryRef,
    AgentHarnessBudget,
    AgentToolKind,
    AgentToolSpec,
    AutonomousAgentRole,
)
from novel_forge.modules.command_kernel.cancellation import (
    CancelCommand,
    request_cancellation,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_runtime import (
    cancel_operation_external_effects,
)
from novel_forge.modules.command_kernel.recovery import (
    RecoverOperationCommand,
    recover_operation,
)


class AgentAdminRequest(BaseModel):
    definition_name: str
    project_id: str
    workspace_id: str
    agent_id: str
    actor_id: str
    idempotency_key: str
    payload: dict[str, Any]
    expected_activation_version: int = Field(default=0, ge=0)
    trace_id: str = ""
    correlation_id: str = ""


class AgentHarnessRequest(BaseModel):
    project_id: str
    workspace_id: str
    book_id: str
    actor_id: str
    agent_session_id: str
    agent_id: str = ""
    agent_role: AutonomousAgentRole
    instruction: str = Field(min_length=1)
    accepted_boundary: dict[str, Any]
    tool_policy: list[dict[str, Any]] = Field(min_length=1)
    skill_bindings: list[dict[str, Any]] = Field(default_factory=list)
    requested_skill_ids: list[str] = Field(default_factory=list)
    budget: dict[str, Any]
    idempotency_key: str
    trace_id: str = ""
    correlation_id: str = ""
    reference_prose: bool = False


class AgentControlRequest(BaseModel):
    project_id: str
    actor_id: str
    expected_version: int = Field(ge=0)
    idempotency_key: str
    reason: str
    trace_id: str = ""
    correlation_id: str = ""


class AgentUnsentRecoveryBody(BaseModel):
    project_id: str
    expected_operation_version: int = Field(ge=1)
    expected_session_version: int = Field(ge=1)
    expected_request_digest: str = Field(pattern="^[0-9a-f]{64}$")
    target_release_sha: str = Field(pattern="^[0-9a-f]{40}$")
    reason: str = Field(min_length=1)
    reference_prose: bool = False


def create_router(ctx: ProductRouterContext) -> APIRouter:
    router = APIRouter(
        prefix="/product/production/agent-runtime",
        tags=["product-agent-runtime"],
    )
    application = ctx.services.agent_runtime_authority_application
    query = ctx.services.agent_runtime_query

    @router.post("/agent-sessions/{source_session_id}/recover-unsent", status_code=202)
    def recover_unsent_session(source_session_id: str, request: AgentUnsentRecoveryBody) -> dict[str, Any]:
        try:
            principal = build_trusted_principal_resolver().resolve_api_principal()
            return application.recover_unsent_harness_session(AgentUnsentRecoveryRequest(
                source_session_id=source_session_id, **request.model_dump()), principal=principal)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KernelError as exc:
            raise HTTPException(status_code=409, detail={"code": exc.code, "message": exc.message}) from exc

    @router.post("/agent-sessions", status_code=202)
    def admit_agent_session(request: AgentHarnessRequest) -> dict[str, Any]:
        try:
            principal = build_trusted_principal_resolver().resolve_api_principal(
                claimed_actor_id=request.actor_id
            )
            tools = tuple(
                AgentToolSpec(
                    tool_name=str(item["tool_name"]),
                    kind=AgentToolKind(str(item["kind"])),
                    input_schema_ref=str(item["input_schema_ref"]),
                    output_schema_ref=str(item["output_schema_ref"]),
                    allowed_roles=tuple(
                        AutonomousAgentRole(str(role)) for role in item["allowed_roles"]
                    ),
                    external_effect_required=bool(
                        item.get("external_effect_required", False)
                    ),
                    authority_command_type=str(
                        item.get("authority_command_type") or ""
                    ),
                )
                for item in request.tool_policy
            )
            result = application.admit_harness_session(
                AgentHarnessAdmissionRequest(
                    project_id=request.project_id,
                    workspace_id=request.workspace_id,
                    book_id=request.book_id,
                    actor_id=request.actor_id,
                    agent_session_id=request.agent_session_id,
                    agent_role=request.agent_role,
                    instruction=request.instruction,
                    accepted_boundary=AcceptedBoundaryRef(**request.accepted_boundary),
                    tool_policy=tools,
                    skill_bindings=tuple(request.skill_bindings),
                    requested_skill_ids=tuple(request.requested_skill_ids),
                    budget=AgentHarnessBudget(**request.budget),
                    idempotency_key=request.idempotency_key,
                    trace_id=request.trace_id or f"trace:agent-session:{uuid4()}",
                    correlation_id=(
                        request.correlation_id or f"correlation:agent-session:{uuid4()}"
                    ),
                    agent_id=request.agent_id,
                    reference_prose=request.reference_prose,
                ),
                principal=principal,
            )
            return {
                **result,
                "query_url": (
                    "/product/production/agent-runtime/agent-sessions/"
                    + request.agent_session_id
                    + f"?project_id={request.project_id}"
                ),
            }
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KernelError as exc:
            raise HTTPException(
                status_code=409, detail={"code": exc.code, "message": exc.message}
            ) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/agent-sessions/{agent_session_id}")
    def require_agent_session(
        agent_session_id: str, project_id: str = Query(..., min_length=1)
    ) -> dict[str, Any]:
        _authorize("agent.authority.query", project_id)
        try:
            return query.require_harness_session(
                project_id=project_id, agent_session_id=agent_session_id
            )
        except KernelError as exc:
            raise HTTPException(
                status_code=(
                    404 if exc.code == "AGENT_HARNESS_SESSION_NOT_FOUND" else 409
                ),
                detail={"code": exc.code, "message": exc.message},
            ) from exc

    @router.get("/migration/agent-runs")
    def list_agent_runs(
        project_id: str = Query(..., min_length=1),
        agent_id: str = "",
        book_id: str = "",
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        _authorize("agent.authority.query", project_id)
        return query.list_runs(
            project_id=project_id,
            agent_id=agent_id,
            book_id=book_id,
            limit=limit,
        )

    @router.get("/health/recovery")
    def agent_runtime_recovery_health(
        project_id: str = Query(..., min_length=1),
    ) -> dict[str, Any]:
        _authorize("agent.authority.query", project_id)
        return query.recovery_health(project_id=project_id)

    @router.get("/migration/agent-runs/{agent_run_id}")
    def require_agent_run(
        agent_run_id: str, project_id: str = Query(..., min_length=1)
    ) -> dict[str, Any]:
        _authorize("agent.authority.query", project_id)
        try:
            return query.require_run(project_id=project_id, agent_run_id=agent_run_id)
        except KernelError as exc:
            raise HTTPException(
                status_code=404 if exc.code == "AGENT_RUN_NOT_FOUND" else 409,
                detail={"code": exc.code, "message": exc.message},
            ) from exc

    @router.post("/migration/agent-runs/{agent_run_id}/cancel", status_code=202)
    def cancel_agent_run(
        agent_run_id: str, request: AgentControlRequest
    ) -> dict[str, Any]:
        principal = _authorize(
            "agent.authority.cancel", request.project_id, request.actor_id
        )
        trace_id, correlation_id = _trace(request)
        try:
            result = request_cancellation(
                application.database_url,
                CancelCommand(
                    operation_id=agent_run_id,
                    project_id=request.project_id,
                    actor_id=principal.principal_id,
                    reason=request.reason,
                    expected_version=request.expected_version,
                    idempotency_key=request.idempotency_key,
                    trace_id=trace_id,
                    correlation_id=correlation_id,
                ),
            )
            effects = cancel_operation_external_effects(
                application.database_url,
                root_operation_id=agent_run_id,
                project_id=request.project_id,
                actor_id=principal.principal_id,
                trace_id=trace_id,
                correlation_id=correlation_id,
                adapters=ctx.services.production_execution.external_effect_adapters,
            )
            return {**result, "external_effect_cancellation": effects}
        except KernelError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/migration/agent-runs/{agent_run_id}/retry", status_code=202)
    def retry_agent_run(
        agent_run_id: str, request: AgentControlRequest
    ) -> dict[str, Any]:
        principal = _authorize(
            "agent.authority.recover", request.project_id, request.actor_id
        )
        trace_id, correlation_id = _trace(request)
        try:
            return recover_operation(
                application.database_url,
                RecoverOperationCommand(
                    operation_id=agent_run_id,
                    project_id=request.project_id,
                    actor_id=principal.principal_id,
                    expected_version=request.expected_version,
                    idempotency_key=request.idempotency_key,
                    reason=request.reason,
                    trace_id=trace_id,
                    correlation_id=correlation_id,
                ),
            )
        except KernelError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": exc.message},
            ) from exc

    @router.get("/agents")
    def list_agents(
        project_id: str = Query(..., min_length=1),
        activation_status: str = "",
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        _authorize("agent.authority.query", project_id)
        return query.list_agents(activation_status=activation_status, limit=limit)

    @router.get("/agents/{agent_id}/versions")
    def list_agent_versions(
        agent_id: str,
        project_id: str = Query(..., min_length=1),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        _authorize("agent.authority.query", project_id)
        return query.list_agents(agent_id=agent_id, limit=limit)

    @router.post("/agents/commands")
    def execute_agent_admin(request: AgentAdminRequest) -> dict[str, Any]:
        principal = _authorize(
            "agent.authority.admin", request.project_id, request.actor_id
        )
        try:
            return application.execute_admin(
                AgentRuntimeAdminCommand(
                    **request.model_dump(exclude={"trace_id", "correlation_id"}),
                    trace_id=request.trace_id or f"trace:agent-admin:{uuid4()}",
                    correlation_id=(
                        request.correlation_id or f"correlation:agent-admin:{uuid4()}"
                    ),
                ),
                principal=principal,
            )
        except KernelError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/agent-collaborations/{session_id}")
    def require_collaboration(
        session_id: str, project_id: str = Query(..., min_length=1)
    ) -> dict[str, Any]:
        _authorize("agent.authority.query", project_id)
        try:
            return query.require_collaboration(
                project_id=project_id, session_id=session_id
            )
        except KernelError as exc:
            raise HTTPException(
                status_code=404, detail={"code": exc.code, "message": exc.message}
            ) from exc

    @router.get("/asset-lineage/{asset_version_id}")
    def require_asset_lineage(
        asset_version_id: str, project_id: str = Query(..., min_length=1)
    ) -> dict[str, Any]:
        _authorize("agent.authority.query", project_id)
        try:
            return query.require_asset_lineage(
                project_id=project_id, asset_version_id=asset_version_id
            )
        except KernelError as exc:
            raise HTTPException(
                status_code=(
                    404 if exc.code == "AGENT_ASSET_LINEAGE_NOT_FOUND" else 409
                ),
                detail={"code": exc.code, "message": exc.message},
            ) from exc

    return router


def _authorize(permission: str, project_id: str, actor_id: str = "") -> Any:
    principal = build_trusted_principal_resolver().resolve_api_principal(
        claimed_actor_id=actor_id
    )
    try:
        principal.require(permission, project_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return principal


def _trace(request: AgentControlRequest) -> tuple[str, str]:
    return (
        request.trace_id or f"trace:agent-control:{uuid4()}",
        request.correlation_id or f"correlation:agent-control:{uuid4()}",
    )


__all__ = ["create_router"]

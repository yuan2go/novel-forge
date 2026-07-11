from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.modules.os_envelope import enforce_os_envelope
from novel_forge.modules.production_kernel.entrypoints import require_production_entrypoint
from novel_forge.storage.local import LocalStorage
from novel_forge.storage.write_budget import WriteBudgetExceeded


def dispatch_chapter_production(storage: LocalStorage, **command: Any) -> dict[str, Any]:
    """Single facade for chapter-production commands.

    The facade deliberately delegates lifecycle ownership to ChapterProductionRun;
    it does not introduce a second Run or Task state machine.
    """
    entrypoint = require_production_entrypoint("chapter_production.start")
    environment = str(command.get("environment") or "")
    envelope_payload = command.get("os_envelope") if isinstance(command.get("os_envelope"), dict) else None
    # The bus repeats this check with project-bound defaults. This early check
    # protects API/worker callers before they resolve or write a run.
    if envelope_payload is not None and str(envelope_payload.get("project_ref") or envelope_payload.get("project_id") or "").strip():
        enforce_os_envelope(
            storage,
            envelope_payload=envelope_payload,
            operation=entrypoint["operation"],
            project_id=str(envelope_payload.get("project_ref") or envelope_payload.get("project_id") or ""),
            task_type="chapter_production",
            asset_type="chapter_production_run",
            actor_type="production_kernel",
            source="production_kernel",
            source_policy=command.get("source_policy") if isinstance(command.get("source_policy"), dict) else None,
            environment=environment,
            require_for_production=True,
            record_trace=False,
        )
    elif envelope_payload is None and environment.strip().lower() in {"production", "prod", "operating_system", "strict"}:
        # Avoid a trace write for a rejected command; the bus independently
        # enforces as a defense-in-depth check for direct service callers.
        raise ValueError("OS envelope required for production operation chapter_production.start")

    from novel_forge.modules.chapter_production_bus import start_chapter_production

    budget_payload = command.pop("write_budget", None)
    environment = str(command.get("environment") or "")
    if budget_payload is None and environment.strip().lower() not in {"production", "prod", "strict", "operating_system"}:
        return start_chapter_production(storage, **command)
    try:
        with storage.write_budget(budget_payload) as budget:
            result = start_chapter_production(storage, **command)
            if isinstance(result, dict):
                result["write_budget"] = budget.snapshot()
            return result
    except WriteBudgetExceeded as exc:
        return {
            "status": "failed",
            "failure_type": "write_budget_exceeded",
            "error": str(exc),
            "write_budget": budget.snapshot() if "budget" in locals() else {},
            "recovery_instruction": "compact runtime artifacts or raise the approved chapter write budget before retrying",
        }


def dispatch_production_operation(storage: LocalStorage, operation: str, **command: Any) -> dict[str, Any]:
    """Route workflow, agent, loop, and chapter commands through one kernel.

    The kernel owns the boundary check and routing decision; the existing
    WorkflowRun, AgentRun, LoopRun, and ChapterProductionRun remain the state
    authorities.  This is a convergence facade, not a fifth state machine.
    """
    entrypoint = require_production_entrypoint(operation)
    payload = dict(command)
    environment = str(payload.get("environment") or "")
    envelope_payload = payload.get("envelope") if isinstance(payload.get("envelope"), dict) else payload.get("os_envelope") if isinstance(payload.get("os_envelope"), dict) else None
    project_id = str(payload.get("project_id") or (envelope_payload or {}).get("project_ref") or (envelope_payload or {}).get("project_id") or "")
    if operation == "chapter_production.start":
        result = dispatch_chapter_production(storage, **payload)
        if isinstance(result, dict):
            result.setdefault("kernel_route", {"operation": operation, "route": entrypoint["kernel_route"], "state_owner": entrypoint["state_owner"]})
        return result

    kernel_envelope = enforce_os_envelope(
        storage,
        envelope_payload=envelope_payload,
        operation=operation,
        project_id=project_id,
        task_type=entrypoint["state_owner"],
        asset_type=entrypoint["state_owner"],
        actor_type="production_kernel",
        source="production_kernel.dispatch_production_operation",
        environment=environment,
        source_policy=payload.get("source_policy") if isinstance(payload.get("source_policy"), dict) else None,
        bypass_reason=str(payload.get("bypass_reason") or "production kernel local compatibility route"),
        require_for_production=True,
    )
    payload.pop("envelope", None)
    payload.pop("os_envelope", None)
    payload.pop("environment", None)
    if operation == "workflow.execute":
        from novel_forge.modules.workflow_nodes import execute_workflow

        payload.pop("project_id", None)
        result = execute_workflow(storage, **payload)
    elif operation == "agent.dispatch":
        from novel_forge.modules.agent_scheduler import dispatch_agent_run

        agent_run_path = payload.pop("agent_run_path", None)
        payload.pop("project_id", None)
        if not agent_run_path:
            raise ValueError("agent.dispatch requires agent_run_path")
        result = dispatch_agent_run(storage, agent_run_path=agent_run_path, **payload)
    elif operation in {"loop.run", "review_revision_publish"}:
        from novel_forge.modules.loop_kernel import run_loop

        if operation == "review_revision_publish":
            payload["loop_type"] = "review_revision_publish"
        result = run_loop(storage, payload)
    else:
        raise ValueError(f"production kernel has no router for operation: {operation}")
    if isinstance(result, dict):
        result.setdefault(
            "kernel_route",
            {
                "operation": operation,
                "route": entrypoint["kernel_route"],
                "state_owner": entrypoint["state_owner"],
                "envelope_id": str(kernel_envelope.get("envelope_id") or ""),
                "trace_id": str(kernel_envelope.get("trace_id") or ""),
            },
        )
    return result

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.os_envelope import enforce_os_envelope
from novel_forge.modules.production_kernel.entrypoints import require_production_entrypoint
from novel_forge.schemas import ProductionOperation, validate_common_fields
from novel_forge.storage.local import LocalStorage
from novel_forge.storage.write_budget import WriteBudgetExceeded

_VOLATILE_COMMAND_KEYS = {"envelope", "os_envelope"}


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
    scope_project_id = project_id or "system"
    kernel_envelope = enforce_os_envelope(
        storage,
        envelope_payload=envelope_payload,
        operation=operation,
        project_id=scope_project_id,
        task_type=entrypoint["state_owner"],
        asset_type=entrypoint["state_owner"],
        actor_type="production_kernel",
        source="production_kernel.dispatch_production_operation",
        environment=environment,
        source_policy=payload.get("source_policy") if isinstance(payload.get("source_policy"), dict) else None,
        bypass_reason=str(payload.get("bypass_reason") or "production kernel local compatibility route"),
        require_for_production=True,
    )
    request_digest = _request_digest(operation, scope_project_id, envelope_payload, payload)
    existing = _find_existing_operation(storage, scope_project_id, kernel_envelope["idempotency_key"])
    if existing:
        existing_content = _content(existing["asset"])
        if str(existing_content.get("request_digest", "")) != request_digest:
            raise ValueError(
                "production operation idempotency conflict: "
                f"{kernel_envelope['idempotency_key']} already belongs to a different request"
            )
        return _parent_response(existing, replayed=True)

    parent = _create_parent_operation(
        storage,
        entrypoint=entrypoint,
        operation=operation,
        project_id=scope_project_id,
        request_digest=request_digest,
        envelope=kernel_envelope,
        command=payload,
    )
    parent_path = parent["path"]
    payload.pop("envelope", None)
    payload.pop("os_envelope", None)
    payload.pop("environment", None)
    try:
        if operation == "chapter_production.start":
            result = dispatch_chapter_production(
                storage,
                **{
                    **payload,
                    # Keep the caller-facing mode for child policy reports
                    # (for example, ``operating_system``), while the Kernel
                    # continues to use the normalized Envelope value for
                    # fail-closed admission.
                    "environment": str(environment or (envelope_payload or {}).get("environment") or ""),
                    "os_envelope": kernel_envelope,
                },
            )
        elif operation == "workflow.execute":
            from novel_forge.modules.workflow_nodes import execute_workflow

            payload.pop("project_id", None)
            result = execute_workflow(storage, **payload)
        elif operation == "agent.dispatch":
            from novel_forge.modules.agent_scheduler import dispatch_agent_run

            agent_run_path = payload.pop("agent_run_path", None)
            payload.pop("project_id", None)
            payload.pop("workspace_path", None)
            if not agent_run_path:
                raise ValueError("agent.dispatch requires agent_run_path")
            result = dispatch_agent_run(storage, agent_run_path=agent_run_path, **payload)
        elif operation in {"loop.run", "review_revision_publish"}:
            from novel_forge.modules.loop_kernel import run_loop

            if operation == "review_revision_publish":
                payload["loop_type"] = "review_revision_publish"
            payload["envelope"] = kernel_envelope
            result = run_loop(storage, payload)
        else:
            raise ValueError(f"production kernel has no router for operation: {operation}")
    except Exception as exc:
        _update_parent_operation(
            storage,
            parent_path,
            status="failed",
            child={"state_owner": entrypoint["state_owner"], "status": "failed"},
            result={},
            error={
                "type": type(exc).__name__,
                "message": str(exc),
                "recovery_instruction": "inspect the persisted ProductionOperation and retry with a new idempotency key after repairing the failed child boundary",
            },
        )
        raise

    result = result if isinstance(result, dict) else {"status": "completed", "value": result}
    result.setdefault(
        "kernel_route",
        {
            "operation": operation,
            "route": entrypoint["kernel_route"],
            "state_owner": entrypoint["state_owner"],
            "parent_state_owner": entrypoint["parent_state_owner"],
            "envelope_id": str(kernel_envelope.get("envelope_id") or ""),
            "trace_id": str(kernel_envelope.get("trace_id") or ""),
        },
    )
    parent_status = _parent_status_from_result(result)
    child = {
        "state_owner": entrypoint["state_owner"],
        "status": str(result.get("status") or parent_status),
        "path": _child_path(result),
        "id": str(result.get("run_id") or result.get("id") or ""),
    }
    _update_parent_operation(storage, parent_path, status=parent_status, child=child, result=result, error={})
    result["production_operation_path"] = parent_path
    result["production_operation_id"] = parent["asset"]["content"]["operation_id"]
    result["idempotency_key"] = kernel_envelope["idempotency_key"]
    return result


def list_production_operations(
    storage: LocalStorage,
    *,
    project_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return parent operation records for the runtime/API workbench."""

    rows: list[dict[str, Any]] = []
    for path in reversed(storage.list_json("runs")):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "production_operation":
            continue
        content = _content(data)
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        stored_project = str(metadata.get("project_id") or content.get("project_id") or "")
        stored_status = str(content.get("status") or "")
        if project_id and stored_project != project_id:
            continue
        if status and stored_status != status:
            continue
        rows.append(
            {
                "path": _display_path(storage, path),
                "operation_id": str(content.get("operation_id") or ""),
                "operation": str(content.get("operation") or ""),
                "status": stored_status,
                "project_id": stored_project,
                "state_owner": str(content.get("state_owner") or ""),
                "idempotency_key": str(content.get("idempotency_key") or ""),
                "child": content.get("child", {}) if isinstance(content.get("child", {}), dict) else {},
                "updated_at": str(content.get("updated_at") or data.get("updated_at") or ""),
            }
        )
        if len(rows) >= max(1, int(limit or 100)):
            break
    return rows


def control_production_operation(
    storage: LocalStorage,
    operation_path_or_id: str | Path,
    *,
    action: str,
    reason: str = "",
    from_step: str | None = None,
    run_to: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Apply a bounded lifecycle command through the Kernel parent boundary."""

    parent = _resolve_parent_operation(storage, operation_path_or_id)
    parent_path = parent["path"]
    data = parent["asset"]
    content = _content(data)
    normalized_action = str(action or "").strip().lower()
    if normalized_action == "retry":
        normalized_action = "recover" if str(content.get("status") or "") in {"failed", "needs_revision"} else "resume"
    supported = {"pause", "resume", "cancel", "recover"}
    if normalized_action not in supported:
        raise ValueError(f"unsupported production operation control action: {normalized_action}")
    child = content.get("child", {}) if isinstance(content.get("child", {}), dict) else {}
    child_path = str(child.get("path") or "")
    if not child_path:
        raise ValueError("production operation has no child run to control")
    state_owner = str(content.get("state_owner") or "")
    try:
        if state_owner == "chapter_production_run":
            from novel_forge.modules.chapter_production_bus import (
                cancel_chapter_production,
                pause_chapter_production,
                recover_chapter_production,
                resume_chapter_production,
            )

            if normalized_action == "pause":
                result = pause_chapter_production(storage, child_path, reason=reason)
            elif normalized_action == "cancel":
                result = cancel_chapter_production(storage, child_path, reason=reason)
            elif normalized_action == "recover":
                result = recover_chapter_production(storage, child_path, run_to=run_to, force=force)
            else:
                result = resume_chapter_production(storage, child_path, from_step=from_step, run_to=run_to, force=force)
        elif state_owner == "workflow_run" and normalized_action in {"resume", "recover"}:
            from novel_forge.modules.workflow_nodes import resume_workflow

            result = resume_workflow(storage, child_path, workspace_path=str(data.get("metadata", {}).get("workspace_path") or "") or None)
        elif state_owner == "loop_run" and normalized_action == "cancel":
            from novel_forge.modules.loop_kernel import cancel_loop_run

            result = cancel_loop_run(storage, child_path, reason=reason)
        elif state_owner == "agent_run" and normalized_action in {"recover", "resume"}:
            from novel_forge.modules.agent_scheduler import recover_agent_dispatch

            result = recover_agent_dispatch(storage, queue_path=child_path, reason=reason)
        else:
            raise ValueError(f"control action {normalized_action} is not supported for state owner {state_owner}")
    except Exception as exc:
        _update_parent_operation(
            storage,
            parent_path,
            status="failed",
            child={**child, "status": "failed"},
            result={},
            error={"type": type(exc).__name__, "message": str(exc), "recovery_instruction": "repair the child run and issue a new lifecycle command"},
        )
        raise

    result = result if isinstance(result, dict) else {"status": "completed", "value": result}
    parent_status = _parent_status_from_result(result)
    if normalized_action == "pause" and parent_status == "completed":
        parent_status = "checkpointed"
    control_history = content.get("control_history", []) if isinstance(content.get("control_history", []), list) else []
    control_history.append({"action": normalized_action, "reason": reason, "status": parent_status, "at": utc_now()})
    _update_parent_operation(
        storage,
        parent_path,
        status=parent_status,
        child={**child, "status": str(result.get("status") or parent_status), "path": _child_path(result) or child_path},
        result=result,
        error={},
        extra_content={"control_history": control_history[-50:]},
    )
    return {**result, "production_operation_path": parent_path, "production_operation_id": str(content.get("operation_id") or ""), "control_action": normalized_action}


def _create_parent_operation(
    storage: LocalStorage,
    *,
    entrypoint: dict[str, str],
    operation: str,
    project_id: str,
    request_digest: str,
    envelope: dict[str, Any],
    command: dict[str, Any],
) -> dict[str, Any]:
    now = utc_now()
    operation_id = make_id("production_operation", f"{project_id}-{operation}")
    input_refs = _string_list(envelope.get("input_refs"))
    expected_outputs = _string_list(envelope.get("expected_output_types"))
    child = {"state_owner": entrypoint["state_owner"], "status": "planned", "path": "", "id": ""}
    asset = ProductionOperation(
        title=f"Production operation: {operation}",
        source=str(envelope.get("envelope_id") or ""),
        tags=["production-operation", operation, "running"],
        content={
            "project_id": project_id,
            "operation_id": operation_id,
            "operation": operation,
            "state_owner": entrypoint["state_owner"],
            "parent_state_owner": entrypoint["parent_state_owner"],
            "status": "running",
            "idempotency_key": str(envelope.get("idempotency_key") or ""),
            "request_digest": request_digest,
            "execution_envelope": envelope,
            "input_refs": input_refs,
            "expected_output_types": expected_outputs,
            "command_summary": _command_summary(command),
            "child": child,
            "result": {},
            "error": {},
            "created_at": now,
            "updated_at": now,
        },
        metadata={
            "project_id": project_id,
            "workspace_path": str(command.get("workspace_path") or ""),
            "scope_kind": "system" if project_id == "system" else "project",
            "execution_envelope_id": str(envelope.get("envelope_id") or ""),
            "trace_id": str(envelope.get("trace_id") or ""),
        },
        references=_safe_references(storage, project_id, [str(envelope.get("trace_span_path") or "")]) if project_id == "system" else _safe_references(storage, project_id, [str(envelope.get("trace_span_path") or ""), *input_refs]),
    )
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("invalid production operation: " + "; ".join(errors))
    path = storage.write_asset_auto(asset)
    return {"path": _display_path(storage, path), "asset": storage.read_json(path)}


def _update_parent_operation(
    storage: LocalStorage,
    path: str,
    *,
    status: str,
    child: dict[str, Any],
    result: dict[str, Any],
    error: dict[str, Any],
    extra_content: dict[str, Any] | None = None,
) -> None:
    resolved = storage.root / path if not Path(path).is_absolute() else Path(path)
    data = storage.read_json(resolved)
    content = _content(data)
    content.update({"status": status, "child": child, "result": result, "error": error, "updated_at": utc_now()})
    if isinstance(extra_content, dict):
        content.update(extra_content)
    data["content"] = content
    data["updated_at"] = content["updated_at"]
    data["tags"] = list(dict.fromkeys([*data.get("tags", []), status]))
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("invalid production operation update: " + "; ".join(errors))
    storage.write_json(resolved, data)


def _find_existing_operation(storage: LocalStorage, project_id: str, idempotency_key: str) -> dict[str, Any] | None:
    if not idempotency_key:
        return None
    for path in reversed(storage.list_json("runs")):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "production_operation":
            continue
        content = _content(data)
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        stored_project = str(metadata.get("project_id") or content.get("project_id") or "")
        if stored_project == project_id and str(content.get("idempotency_key") or "") == idempotency_key:
            return {"path": _display_path(storage, path), "asset": data}
    return None


def _resolve_parent_operation(storage: LocalStorage, operation_path_or_id: str | Path) -> dict[str, Any]:
    candidate = Path(operation_path_or_id)
    if not candidate.is_absolute():
        candidate = storage.root / candidate
    if candidate.exists() and candidate.is_file():
        data = storage.read_json(candidate)
        if isinstance(data, dict) and data.get("type") == "production_operation":
            return {"path": _display_path(storage, candidate), "asset": data}
    target = str(operation_path_or_id)
    for path in storage.list_json("runs"):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "production_operation":
            continue
        content = _content(data)
        if target in {str(data.get("id") or ""), str(content.get("operation_id") or "")}:
            return {"path": _display_path(storage, path), "asset": data}
    raise FileNotFoundError(f"production operation not found: {operation_path_or_id}")


def _parent_response(existing: dict[str, Any], *, replayed: bool) -> dict[str, Any]:
    asset = existing["asset"]
    content = _content(asset)
    result = content.get("result") if isinstance(content.get("result"), dict) else {}
    response = dict(result)
    response.update(
        {
            "production_operation_path": existing["path"],
            "production_operation_id": str(content.get("operation_id") or ""),
            "idempotency_key": str(content.get("idempotency_key") or ""),
            "production_operation_status": str(content.get("status") or ""),
            "replayed": replayed,
        }
    )
    return response


def _request_digest(operation: str, project_id: str, envelope_payload: dict[str, Any] | None, command: dict[str, Any]) -> str:
    stable_envelope = dict(envelope_payload or {})
    for key in ["envelope_id", "created_at", "trace_span_path"]:
        stable_envelope.pop(key, None)
    stable_command = {key: value for key, value in command.items() if key not in _VOLATILE_COMMAND_KEYS}
    payload = {"operation": operation, "project_id": project_id, "envelope": stable_envelope, "command": _jsonable(stable_command)}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _command_summary(command: dict[str, Any]) -> dict[str, Any]:
    return {str(key): _jsonable(value) for key, value in command.items() if key not in _VOLATILE_COMMAND_KEYS and key not in {"write_budget"}}


def _content(data: dict[str, Any]) -> dict[str, Any]:
    return data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}


def _string_list(value: Any) -> list[str]:
    return [str(item) for item in value if str(item).strip()] if isinstance(value, list) else []


def _safe_references(storage: LocalStorage, project_id: str, values: list[str]) -> list[str]:
    from novel_forge.modules.production_context import filter_project_safe_references

    return filter_project_safe_references(storage, project_id, values)


def _child_path(result: dict[str, Any]) -> str:
    for key in ["path", "run_path", "workflow_run_path", "agent_run_path", "loop_run_path", "chapter_production_run_path"]:
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            return value
    for key in ["workflow_run", "run", "agent_run", "loop_run", "chapter_production_run"]:
        value = result.get(key)
        if isinstance(value, dict) and isinstance(value.get("path"), str) and value["path"].strip():
            return str(value["path"])
    return ""


def _parent_status_from_result(result: dict[str, Any]) -> str:
    raw = str(result.get("status") or "").strip().lower()
    if raw in {"failed", "error", "dead_letter"}:
        return "failed"
    if raw in {"cancelled", "canceled"}:
        return "cancelled"
    if raw in {"needs_revision", "waiting_human", "blocked", "needs_review"}:
        return "needs_review" if raw in {"waiting_human", "blocked", "needs_review"} else "needs_revision"
    if raw in {"accepted"}:
        return "accepted"
    if raw == "paused":
        return "checkpointed"
    if raw in {"running", "planned", "checkpointed", "recovering"}:
        return raw
    return "completed"


def _display_path(storage: LocalStorage, path: Path) -> str:
    return str(path.relative_to(storage.root)) if path.is_relative_to(storage.root) else str(path)

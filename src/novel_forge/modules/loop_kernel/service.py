from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.common import resolve_path
from novel_forge.modules.context_builder import build_flow_context_bundle
from novel_forge.modules.os_envelope import enforce_os_envelope, envelope_asset_metadata
from novel_forge.modules.production_context import filter_project_safe_references, project_scope_from_asset
from novel_forge.modules.review_issue import blocking_review_issues, review_issues_to_gate_issues
from novel_forge.modules.runtime_ledger import record_trace_span
from novel_forge.schemas import DraftChapter, EditorPatch, LoopCheckpoint, LoopReport, LoopRun, LoopStep, ReviewReport, RevisionPlan, validate_common_fields
from novel_forge.storage.local import LocalStorage

LOOP_STATES = {"planned", "running", "waiting_human", "succeeded", "failed", "cancelled"}
LOOP_TERMINAL_STATES = {"succeeded", "failed", "cancelled"}
LOOP_TYPES = {"chapter_review", "outline_revision", "longform_recap", "review_revision_publish"}
LOOP_STOP_CONDITIONS = {"quality_passed", "blocking_issue", "budget_exceeded", "provider_timeout", "human_required"}

LOOP_CONTEXT_FLOW = {
    "chapter_review": "review",
    "outline_revision": "revision",
    "longform_recap": "recap",
    "review_revision_publish": "review",
}

DEFAULT_LOOP_STEPS = {
    "chapter_review": [
        {"step_type": "context_build", "operation": "build_context", "token_estimate": 120, "cost_estimate": 0.0},
        {"step_type": "review_issue_gate", "operation": "check_blocking_review_issues", "token_estimate": 20, "cost_estimate": 0.0},
        {"step_type": "quality_gate", "operation": "quality_passed", "token_estimate": 40, "cost_estimate": 0.0},
    ],
    "outline_revision": [
        {"step_type": "context_build", "operation": "build_context", "token_estimate": 100, "cost_estimate": 0.0},
        {"step_type": "revision_plan", "operation": "plan_outline_revision", "token_estimate": 220, "cost_estimate": 0.0},
        {"step_type": "quality_gate", "operation": "quality_passed", "token_estimate": 40, "cost_estimate": 0.0},
    ],
    "longform_recap": [
        {"step_type": "context_build", "operation": "build_context", "token_estimate": 180, "cost_estimate": 0.0},
        {"step_type": "recap_scan", "operation": "scan_longform_state", "token_estimate": 260, "cost_estimate": 0.0},
        {"step_type": "review_issue_gate", "operation": "check_blocking_review_issues", "token_estimate": 30, "cost_estimate": 0.0},
        {"step_type": "recap_report", "operation": "prepare_recap_report", "token_estimate": 160, "cost_estimate": 0.0},
    ],
    "review_revision_publish": [
        {"step_type": "context_build", "operation": "build_context", "token_estimate": 140, "cost_estimate": 0.0},
        {"step_type": "review_run", "operation": "create_structured_review", "token_estimate": 180, "cost_estimate": 0.0},
        {"step_type": "review_issue_gate", "operation": "check_blocking_review_issues", "token_estimate": 30, "cost_estimate": 0.0},
        {"step_type": "revision_plan", "operation": "create_revision_plan", "token_estimate": 160, "cost_estimate": 0.0},
        {"step_type": "revision_apply", "operation": "apply_revision_candidate", "token_estimate": 220, "cost_estimate": 0.0},
        {"step_type": "re_review", "operation": "create_re_review", "token_estimate": 160, "cost_estimate": 0.0},
        {"step_type": "publish_gate", "operation": "create_publish_gate_report", "token_estimate": 120, "cost_estimate": 0.0},
    ],
}

DEFAULT_BUDGET = {"max_steps": 8, "max_tokens": 4000, "max_cost": 1.0, "max_duration_seconds": 1800}


def run_loop(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    storage.ensure_layout()
    loop_type = _loop_type(payload.get("loop_type") or payload.get("type") or "chapter_review")
    budget = _normalize_budget(payload.get("budget") if isinstance(payload.get("budget"), dict) else {})
    target = _target(storage, payload)
    project_id = str(payload.get("project_id") or target.get("project_id") or "local-system")
    workspace_path = str(payload.get("workspace_path") or target.get("workspace_path") or "")
    trace_id = str(payload.get("trace_id") or make_id("trace", f"{loop_type}-{project_id}-{utc_now()}"))
    envelope = enforce_os_envelope(
        storage,
        envelope_payload=payload.get("envelope") if isinstance(payload.get("envelope"), dict) else None,
        operation=f"loop.{loop_type}",
        project_id=project_id,
        task_type=loop_type,
        asset_type="loop_run",
        actor_type=str(payload.get("actor_type") or "loop_kernel"),
        actor_id=str(payload.get("actor_id") or ""),
        source="loop_kernel",
        trace_id=trace_id,
        token_budget=budget,
        source_policy=_source_policy(payload),
        environment=str(payload.get("environment") or ""),
        bypass_reason=str(payload.get("bypass_reason") or "loop_kernel local execution"),
        require_for_production=True,
    )
    run = _create_loop_run(storage, loop_type=loop_type, budget=budget, target=target, project_id=project_id, workspace_path=workspace_path, envelope=envelope)
    run_path = run["path"]
    _update_loop_run(storage, run_path, {"status": "running", "started_at": utc_now(), "trace_id": envelope["trace_id"]})

    context_result = _resolve_context_bundle(storage, payload, loop_type=loop_type, target=target, project_id=project_id, workspace_path=workspace_path, envelope=envelope)
    if context_result.get("path"):
        _update_loop_run(storage, run_path, {"context_bundle_path": context_result["path"], "context_bundle_id": context_result.get("id", "")})

    steps = _step_plan(loop_type, payload.get("steps") if isinstance(payload.get("steps"), list) else None)
    started_at = _utc_now_dt()
    usage = {"steps": 0, "tokens": 0, "cost": 0.0, "duration_seconds": 0}
    step_paths: list[str] = []
    checkpoint_paths: list[str] = []
    stop_condition = ""
    blocking_rows: list[dict[str, Any]] = []
    stop_message = ""
    loop_outputs: dict[str, Any] = {}

    for index, step in enumerate(steps):
        usage["duration_seconds"] = int((_utc_now_dt() - started_at).total_seconds())
        pre_budget = _budget_stop_condition(usage, budget)
        if pre_budget:
            stop_condition = "budget_exceeded"
            stop_message = pre_budget
            break
        if int(usage["steps"]) >= int(budget["max_steps"]):
            stop_condition = "budget_exceeded"
            stop_message = f"max_steps exceeded: {usage['steps']} >= {budget['max_steps']}"
            break

        if bool(payload.get("provider_timeout")):
            step_result = _write_step_and_checkpoint(
                storage,
                run_path=run_path,
                loop_run_id=run["asset"]["content"]["loop_run_id"],
                loop_type=loop_type,
                step_index=index,
                step=step,
                status="failed",
                stop_condition="provider_timeout",
                usage=usage,
                target=target,
                context_result=context_result,
                project_id=project_id,
                workspace_path=workspace_path,
                envelope=envelope,
                message="provider timeout requested by runtime guard",
            )
            step_paths.append(step_result["step_path"])
            checkpoint_paths.append(step_result["checkpoint_path"])
            stop_condition = "provider_timeout"
            stop_message = "provider timeout requested by runtime guard"
            break

        if bool(payload.get("human_required")):
            step_result = _write_step_and_checkpoint(
                storage,
                run_path=run_path,
                loop_run_id=run["asset"]["content"]["loop_run_id"],
                loop_type=loop_type,
                step_index=index,
                step=step,
                status="waiting_human",
                stop_condition="human_required",
                usage=usage,
                target=target,
                context_result=context_result,
                project_id=project_id,
                workspace_path=workspace_path,
                envelope=envelope,
                message="human review required before continuing loop",
            )
            step_paths.append(step_result["step_path"])
            checkpoint_paths.append(step_result["checkpoint_path"])
            stop_condition = "human_required"
            stop_message = "human review required before continuing loop"
            break

        if str(step.get("step_type")) == "review_issue_gate":
            blocking_rows = blocking_review_issues(
                storage,
                target_asset_id=str(target.get("asset_id") or payload.get("target_asset_id") or ""),
                project_id=project_id if project_id != "local-system" else None,
                related_asset_ids=[str(item) for item in payload.get("related_asset_ids", []) if str(item).strip()],
            )
            if blocking_rows:
                step_result = _write_step_and_checkpoint(
                    storage,
                    run_path=run_path,
                    loop_run_id=run["asset"]["content"]["loop_run_id"],
                    loop_type=loop_type,
                    step_index=index,
                    step=step,
                    status="failed",
                    stop_condition="blocking_issue",
                    usage=usage,
                    target=target,
                    context_result=context_result,
                    project_id=project_id,
                    workspace_path=workspace_path,
                    envelope=envelope,
                    message=f"blocked by {len(blocking_rows)} active ReviewIssue(s)",
                    blocking_rows=blocking_rows,
                )
                step_paths.append(step_result["step_path"])
                checkpoint_paths.append(step_result["checkpoint_path"])
                stop_condition = "blocking_issue"
                stop_message = f"blocked by {len(blocking_rows)} active ReviewIssue(s)"
                break

        side_effect = _execute_loop_step_side_effect(
            storage,
            payload,
            loop_type=loop_type,
            step=step,
            loop_outputs=loop_outputs,
            target=target,
            project_id=project_id,
            workspace_path=workspace_path,
            context_result=context_result,
            envelope=envelope,
        )
        if isinstance(side_effect.get("outputs"), dict):
            loop_outputs.update(side_effect["outputs"])
        if side_effect.get("status") == "failed":
            step_result = _write_step_and_checkpoint(
                storage,
                run_path=run_path,
                loop_run_id=run["asset"]["content"]["loop_run_id"],
                loop_type=loop_type,
                step_index=index,
                step=step,
                status="failed",
                stop_condition=str(side_effect.get("stop_condition") or "blocking_issue"),
                usage=usage,
                target=target,
                context_result=context_result,
                project_id=project_id,
                workspace_path=workspace_path,
                envelope=envelope,
                message=str(side_effect.get("message") or ""),
                side_effect=side_effect,
            )
            step_paths.append(step_result["step_path"])
            checkpoint_paths.append(step_result["checkpoint_path"])
            stop_condition = str(side_effect.get("stop_condition") or "blocking_issue")
            stop_message = str(side_effect.get("message") or "loop step failed")
            break

        usage = _add_step_usage(usage, step)
        budget_message = _budget_stop_condition(usage, budget)
        step_status = "failed" if budget_message else "succeeded"
        step_stop = "budget_exceeded" if budget_message else ""
        step_result = _write_step_and_checkpoint(
            storage,
            run_path=run_path,
            loop_run_id=run["asset"]["content"]["loop_run_id"],
            loop_type=loop_type,
            step_index=index,
            step=step,
            status=step_status,
            stop_condition=step_stop,
            usage=usage,
            target=target,
            context_result=context_result,
            project_id=project_id,
            workspace_path=workspace_path,
            envelope=envelope,
            message=budget_message or str(side_effect.get("message") or ""),
            side_effect=side_effect,
        )
        step_paths.append(step_result["step_path"])
        checkpoint_paths.append(step_result["checkpoint_path"])
        if budget_message:
            stop_condition = "budget_exceeded"
            stop_message = budget_message
            break

    if not stop_condition:
        stop_condition = "quality_passed"
        stop_message = "loop completed without blocking issues or budget overrun"
    status = _status_from_stop_condition(stop_condition)
    loop_outputs.setdefault("loop_run_path", run_path)
    report = _write_report(
        storage,
        run_path=run_path,
        loop_run_id=run["asset"]["content"]["loop_run_id"],
        loop_type=loop_type,
        status=status,
        stop_condition=stop_condition,
        stop_message=stop_message,
        usage=usage,
        target=target,
        context_result=context_result,
        project_id=project_id,
        workspace_path=workspace_path,
        envelope=envelope,
        step_paths=step_paths,
        checkpoint_paths=checkpoint_paths,
        blocking_rows=blocking_rows,
        loop_outputs=loop_outputs,
    )
    loop_outputs["loop_report_path"] = report["path"]
    if loop_type == "review_revision_publish" and loop_outputs.get("revision_task_path"):
        task_data = storage.read_json(resolve_path(storage.root, str(loop_outputs.get("revision_task_path"))))
        task_content = task_data.get("content", {}) if isinstance(task_data.get("content", {}), dict) else {}
        _update_loop_revision_task(
            storage,
            str(loop_outputs.get("revision_task_path")),
            status=str(task_content.get("status") or ("failed" if status == "failed" else "running")),
            stage=str(task_content.get("stage") or "loop_report"),
            outputs={"loop_run_path": run_path, "loop_report_path": report["path"]},
        )
    _update_loop_run(
        storage,
        run_path,
        {
            "status": status,
            "finished_at": utc_now() if status in LOOP_TERMINAL_STATES else "",
            "stop_condition": stop_condition,
            "stop_message": stop_message,
            "budget_used": usage,
            "step_paths": step_paths,
            "checkpoint_paths": checkpoint_paths,
            "report_path": report["path"],
            "blocking_review_issue_count": len(blocking_rows),
            "outputs": loop_outputs,
        },
    )
    _record_loop_span(storage, envelope=envelope, loop_type=loop_type, status=status, run_path=run_path, report_path=report["path"], project_id=project_id, workspace_path=workspace_path)
    updated = storage.read_json(resolve_path(storage.root, run_path))
    return {
        "status": status,
        "stop_condition": stop_condition,
        "loop_run_path": run_path,
        "loop_report_path": report["path"],
        "step_paths": step_paths,
        "checkpoint_paths": checkpoint_paths,
        "context_bundle_path": context_result.get("path", ""),
        "budget_used": usage,
        "blocking_review_issues": review_issues_to_gate_issues(blocking_rows),
        "outputs": loop_outputs,
        "envelope": envelope,
        "asset": updated,
        "report": report["asset"],
    }


def list_loop_runs(storage: LocalStorage, *, project_id: str | None = None, status: str | None = None, loop_type: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in reversed(storage.list_json("loops")):
        if len(rows) >= limit:
            break
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "loop_run":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if project_id and str(metadata.get("project_id") or content.get("project_id") or "") != project_id:
            continue
        if status and str(content.get("status") or "") != status:
            continue
        if loop_type and str(content.get("loop_type") or "") != loop_type:
            continue
        rows.append({**data, "path": _display_path(storage.root, path)})
    return rows


def get_loop_run(storage: LocalStorage, loop_ref: str | Path) -> dict[str, Any]:
    path, data = _find_loop_run(storage, loop_ref)
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    return {
        "path": _display_path(storage.root, path),
        "asset": data,
        "steps": _assets_by_paths(storage, content.get("step_paths", [])),
        "checkpoints": _assets_by_paths(storage, content.get("checkpoint_paths", [])),
        "report": storage.read_json(resolve_path(storage.root, content.get("report_path", ""))) if content.get("report_path") else {},
    }


def cancel_loop_run(storage: LocalStorage, loop_ref: str | Path, *, reason: str = "") -> dict[str, Any]:
    path, data = _find_loop_run(storage, loop_ref)
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    status = str(content.get("status") or "planned")
    if status in LOOP_TERMINAL_STATES:
        raise ValueError(f"loop_run already terminal: {status}")
    content["status"] = "cancelled"
    content["stop_condition"] = "human_required"
    content["stop_message"] = reason or "loop cancelled by operator"
    content["finished_at"] = utc_now()
    data["content"] = content
    data["updated_at"] = utc_now()
    data["tags"] = _dedupe([*[str(tag) for tag in data.get("tags", [])], "cancelled"])
    _ensure_valid(data)
    storage.write_json(path, data)
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path)}


def _create_loop_run(
    storage: LocalStorage,
    *,
    loop_type: str,
    budget: dict[str, Any],
    target: dict[str, Any],
    project_id: str,
    workspace_path: str,
    envelope: dict[str, Any],
) -> dict[str, Any]:
    loop_run_id = make_id("loop_run", f"{loop_type}-{project_id}-{target.get('asset_id', '')}-{utc_now()}")
    content = {
        "loop_run_id": loop_run_id,
        "loop_type": loop_type,
        "status": "planned",
        "state": "planned",
        "target_asset_id": target.get("asset_id", ""),
        "target_asset_type": target.get("asset_type", ""),
        "target_asset_path": target.get("path", ""),
        "project_id": project_id,
        "workflow_run_id": "",
        "agent_run_id": "",
        "context_bundle_id": "",
        "context_bundle_path": "",
        "budget": budget,
        "budget_used": {"steps": 0, "tokens": 0, "cost": 0.0, "duration_seconds": 0},
        "stop_conditions": sorted(LOOP_STOP_CONDITIONS),
        "stop_condition": "",
        "stop_message": "",
        "step_paths": [],
        "checkpoint_paths": [],
        "report_path": "",
        "blocking_review_issue_count": 0,
        "os_envelope_id": envelope.get("envelope_id", ""),
        "trace_id": envelope.get("trace_id", ""),
        "started_at": "",
        "finished_at": "",
        "created_at": utc_now(),
    }
    asset = LoopRun(
        title=f"{loop_type} loop for {target.get('asset_id') or project_id}",
        source=str(target.get("asset_id") or project_id),
        tags=["loop-run", loop_type, "planned"],
        content=content,
        metadata={
            "project_id": project_id,
            "workspace_path": workspace_path,
            "loop_type": loop_type,
            "asset_status": "planned",
            "use_in_generation_rag": False,
            **envelope_asset_metadata(envelope),
        },
        references=filter_project_safe_references(storage, project_id, _dedupe([target.get("asset_id", ""), target.get("path", ""), envelope.get("envelope_id", "")])),
    )
    _ensure_valid(asset.to_dict())
    path = storage.write_asset("loops", asset)
    return {"path": _display_path(storage.root, path), "asset": asset.to_dict()}


def _write_step_and_checkpoint(
    storage: LocalStorage,
    *,
    run_path: str,
    loop_run_id: str,
    loop_type: str,
    step_index: int,
    step: dict[str, Any],
    status: str,
    stop_condition: str,
    usage: dict[str, Any],
    target: dict[str, Any],
    context_result: dict[str, Any],
    project_id: str,
    workspace_path: str,
    envelope: dict[str, Any],
    message: str = "",
    blocking_rows: list[dict[str, Any]] | None = None,
    side_effect: dict[str, Any] | None = None,
) -> dict[str, str]:
    now = utc_now()
    loop_step_id = make_id("loop_step", f"{loop_run_id}-{step_index}-{step.get('operation', '')}-{now}")
    content = {
        "loop_step_id": loop_step_id,
        "loop_run_id": loop_run_id,
        "step_index": int(step_index),
        "loop_type": loop_type,
        "step_type": str(step.get("step_type") or "step"),
        "operation": str(step.get("operation") or step.get("step_type") or "step"),
        "status": status,
        "stop_condition": stop_condition,
        "message": message,
        "context_bundle_id": context_result.get("id", ""),
        "context_bundle_path": context_result.get("path", ""),
        "review_issue_gate": review_issues_to_gate_issues(blocking_rows or []),
        "usage": dict(usage),
        "budget_delta": {
            "token_estimate": int(step.get("token_estimate", 0) or 0),
            "cost_estimate": float(step.get("cost_estimate", 0.0) or 0.0),
        },
        "side_effect": side_effect or {},
        "started_at": now,
        "finished_at": now,
        "created_at": now,
    }
    asset = LoopStep(
        title=f"{loop_type} step {step_index}: {content['operation']}",
        source=loop_run_id,
        tags=["loop-step", loop_type, content["step_type"], status],
        content=content,
        metadata={
            "project_id": project_id,
            "workspace_path": workspace_path,
            "loop_run_id": loop_run_id,
            "loop_run_path": run_path,
            "asset_status": status,
            "use_in_generation_rag": False,
            **envelope_asset_metadata(envelope),
        },
        references=filter_project_safe_references(storage, project_id, _dedupe([loop_run_id, run_path, target.get("asset_id", ""), target.get("path", ""), context_result.get("path", "")])),
    )
    _ensure_valid(asset.to_dict())
    step_path = storage.write_asset("loops", asset)
    checkpoint = _write_checkpoint(
        storage,
        run_path=run_path,
        loop_run_id=loop_run_id,
        loop_type=loop_type,
        status=status,
        state={"last_step_id": loop_step_id, "last_step_path": _display_path(storage.root, step_path), "usage": usage, "stop_condition": stop_condition},
        project_id=project_id,
        workspace_path=workspace_path,
        envelope=envelope,
        references=[loop_run_id, run_path, _display_path(storage.root, step_path), target.get("asset_id", ""), target.get("path", "")],
    )
    return {"step_path": _display_path(storage.root, step_path), "checkpoint_path": checkpoint["path"]}


def _write_checkpoint(
    storage: LocalStorage,
    *,
    run_path: str,
    loop_run_id: str,
    loop_type: str,
    status: str,
    state: dict[str, Any],
    project_id: str,
    workspace_path: str,
    envelope: dict[str, Any],
    references: list[str],
) -> dict[str, Any]:
    checkpoint_id = make_id("loop_checkpoint", f"{loop_run_id}-{len(str(state))}-{utc_now()}")
    asset = LoopCheckpoint(
        title=f"{loop_type} checkpoint {status}",
        source=loop_run_id,
        tags=["loop-checkpoint", loop_type, status],
        content={
            "loop_run_id": loop_run_id,
            "checkpoint_id": checkpoint_id,
            "status": status,
            "state": state,
            "created_at": utc_now(),
        },
        metadata={
            "project_id": project_id,
            "workspace_path": workspace_path,
            "loop_run_id": loop_run_id,
            "loop_run_path": run_path,
            "asset_status": status,
            "use_in_generation_rag": False,
            **envelope_asset_metadata(envelope),
        },
        references=filter_project_safe_references(storage, project_id, _dedupe(references)),
    )
    _ensure_valid(asset.to_dict())
    path = storage.write_asset("loops", asset)
    return {"path": _display_path(storage.root, path), "asset": asset.to_dict()}


def _write_report(
    storage: LocalStorage,
    *,
    run_path: str,
    loop_run_id: str,
    loop_type: str,
    status: str,
    stop_condition: str,
    stop_message: str,
    usage: dict[str, Any],
    target: dict[str, Any],
    context_result: dict[str, Any],
    project_id: str,
    workspace_path: str,
    envelope: dict[str, Any],
    step_paths: list[str],
    checkpoint_paths: list[str],
    blocking_rows: list[dict[str, Any]],
    loop_outputs: dict[str, Any],
) -> dict[str, Any]:
    asset = LoopReport(
        title=f"{loop_type} loop report: {status}",
        source=loop_run_id,
        tags=["loop-report", loop_type, status, stop_condition],
        content={
            "loop_run_id": loop_run_id,
            "status": status,
            "loop_type": loop_type,
            "stop_condition": stop_condition,
            "stop_message": stop_message,
            "steps": step_paths,
            "checkpoint_ids": checkpoint_paths,
            "budget_used": usage,
            "context_bundle_id": context_result.get("id", ""),
            "context_bundle_path": context_result.get("path", ""),
            "blocking_review_issues": review_issues_to_gate_issues(blocking_rows),
            "outputs": loop_outputs,
            "recommendation": _report_recommendation(stop_condition),
            "created_at": utc_now(),
        },
        metadata={
            "project_id": project_id,
            "workspace_path": workspace_path,
            "loop_run_id": loop_run_id,
            "loop_run_path": run_path,
            "target_asset_id": target.get("asset_id", ""),
            "target_asset_path": target.get("path", ""),
            "asset_status": status,
            "use_in_generation_rag": False,
            **envelope_asset_metadata(envelope),
        },
        references=filter_project_safe_references(
            storage,
            project_id,
            _dedupe([loop_run_id, run_path, target.get("asset_id", ""), target.get("path", ""), context_result.get("path", ""), *step_paths, *checkpoint_paths]),
        ),
    )
    _ensure_valid(asset.to_dict())
    path = storage.write_asset("loops", asset)
    return {"path": _display_path(storage.root, path), "asset": asset.to_dict()}


def _execute_loop_step_side_effect(
    storage: LocalStorage,
    payload: dict[str, Any],
    *,
    loop_type: str,
    step: dict[str, Any],
    loop_outputs: dict[str, Any],
    target: dict[str, Any],
    project_id: str,
    workspace_path: str,
    context_result: dict[str, Any],
    envelope: dict[str, Any],
) -> dict[str, Any]:
    if loop_type != "review_revision_publish":
        return {}
    step_type = str(step.get("step_type") or "")
    try:
        if step_type == "context_build":
            return {"status": "succeeded", "message": "context bundle attached to review-revision-publish loop", "outputs": {"context_bundle_path": context_result.get("path", ""), "context_bundle_id": context_result.get("id", "")}}
        if step_type == "review_run":
            return _loop_review_run(storage, payload, target=target, project_id=project_id, workspace_path=workspace_path, context_result=context_result, envelope=envelope)
        if step_type == "revision_plan":
            return _loop_revision_plan(storage, payload, target=target, project_id=project_id, workspace_path=workspace_path, loop_outputs=loop_outputs, envelope=envelope)
        if step_type == "revision_apply":
            return _loop_revision_apply(storage, payload, target=target, project_id=project_id, workspace_path=workspace_path, loop_outputs=loop_outputs, context_result=context_result, envelope=envelope)
        if step_type == "re_review":
            return _loop_re_review(storage, payload, target=target, project_id=project_id, workspace_path=workspace_path, loop_outputs=loop_outputs, envelope=envelope)
        if step_type == "publish_gate":
            return _loop_publish_gate(storage, payload, target=target, workspace_path=workspace_path, loop_outputs=loop_outputs)
    except Exception as exc:
        return {"status": "failed", "stop_condition": "blocking_issue", "message": str(exc), "outputs": {}}
    return {}


def _loop_review_run(
    storage: LocalStorage,
    payload: dict[str, Any],
    *,
    target: dict[str, Any],
    project_id: str,
    workspace_path: str,
    context_result: dict[str, Any],
    envelope: dict[str, Any],
) -> dict[str, Any]:
    existing = str(payload.get("review_path") or "").strip()
    if existing:
        return {"status": "succeeded", "message": "existing review report attached", "outputs": {"review_report_path": _display_path(storage.root, resolve_path(storage.root, existing))}}
    draft_path = _required_loop_target_path(target)
    draft = storage.read_asset(resolve_path(storage.root, draft_path))
    initial_issues = payload.get("initial_issues", []) if isinstance(payload.get("initial_issues", []), list) else []
    asset = ReviewReport(
        title=f"Loop review for {draft.title or draft.id}",
        source=draft.id,
        tags=["review", "loop-kernel", "review-revision-publish"],
        content={
            "rubric": "loop_kernel_main_chain_review",
            "summary": "Loop Kernel structured review for governed review-revision-publish chain.",
            "target_asset_id": draft.id,
            "target_asset_path": draft_path,
            "context_bundle_id": context_result.get("id", ""),
            "context_bundle_path": context_result.get("path", ""),
            "issues": initial_issues,
            "review_issue_summary": {"issue_count": len(initial_issues), "blocking_count": 0},
            "os_envelope_id": envelope.get("envelope_id", ""),
            "created_at": utc_now(),
        },
        score=float(payload.get("review_score", 84.0) or 84.0),
        strengths=["structured loop entry preserves traceable draft context"],
        weaknesses=["operator should replace deterministic review with provider-backed review when ready"],
        issues=initial_issues,
        risk_level="medium" if initial_issues else "low",
        revision_suggestions=["apply controlled revision plan before publish gate"],
        next_action="revise",
        metadata={"project_id": project_id, "workspace_path": workspace_path, "context_bundle_path": context_result.get("path", ""), **envelope_asset_metadata(envelope)},
        references=filter_project_safe_references(storage, project_id, [draft.id, draft_path, context_result.get("path", "")]),
    )
    _ensure_valid(asset.to_dict())
    path = storage.write_asset("reviews", asset)
    return {"status": "succeeded", "message": "structured review report created", "outputs": {"review_report_path": _display_path(storage.root, path)}}


def _loop_revision_plan(
    storage: LocalStorage,
    payload: dict[str, Any],
    *,
    target: dict[str, Any],
    project_id: str,
    workspace_path: str,
    loop_outputs: dict[str, Any],
    envelope: dict[str, Any],
) -> dict[str, Any]:
    review_path = str(loop_outputs.get("review_report_path") or payload.get("review_path") or "").strip()
    if not review_path:
        raise ValueError("revision_plan step requires review_report_path")
    from novel_forge.modules.revision import create_revision_task, revise

    review = storage.read_json(resolve_path(storage.root, review_path))
    review_content = review.get("content", {}) if isinstance(review.get("content", {}), dict) else {}
    revision_task_path = str(payload.get("revision_task_path") or loop_outputs.get("revision_task_path") or "").strip()
    if not revision_task_path:
        task = create_revision_task(
            storage,
            review_path,
            draft_path=target.get("path") or None,
            issue_indexes=[int(item) for item in payload.get("issue_indexes", [])] if isinstance(payload.get("issue_indexes", []), list) else None,
            workspace_path=workspace_path or None,
        )
        revision_task_path = task["path"]
    task_data = storage.read_json(resolve_path(storage.root, revision_task_path))
    task_content = task_data.get("content", {}) if isinstance(task_data.get("content", {}), dict) else {}
    issue_indexes = [int(item) for item in task_content.get("issue_indexes", []) if str(item).strip()] if isinstance(task_content.get("issue_indexes", []), list) else []
    revision_model = payload.get("revision_model")
    if revision_model is not None:
        revision_file = revise(storage, review_path, model=revision_model)
        revision_ref = _display_path(storage.root, revision_file)
        _link_loop_revision_plan(storage, revision_ref, revision_task_path=revision_task_path, issue_indexes=issue_indexes, envelope=envelope)
        outputs = {"revision_task_path": revision_task_path, "revision_plan_path": revision_ref}
        _update_loop_revision_task(storage, revision_task_path, status="running", stage="editor_patch", outputs=outputs)
        return {"status": "succeeded", "message": "provider-backed revision plan created through Loop Kernel", "outputs": outputs}

    steps = payload.get("revision_steps", []) if isinstance(payload.get("revision_steps", []), list) else []
    if not steps:
        steps = [str(item) for item in review.get("revision_suggestions", []) if str(item).strip()] or ["tighten continuity and preserve chapter hook"]
    asset = RevisionPlan(
        title=f"Loop revision plan for {review.get('title') or review.get('id')}",
        source=str(review.get("id", "")),
        tags=["revision", "loop-kernel", "review-revision-publish"],
        content={
            "steps": steps,
            "target_score": max(88, int(float(review.get("score", 0) or 0)) + 4),
            "must_preserve": ["project-owned prose", "canon boundaries", "chapter hook"],
            "review_report_path": review_path,
            "source_draft_path": target.get("path", ""),
            "review_issues": review_content.get("issues", []),
            "revision_task_path": revision_task_path,
            "review_issue_indexes": issue_indexes,
            "os_envelope_id": envelope.get("envelope_id", ""),
            "created_at": utc_now(),
        },
        metadata={"project_id": project_id, "workspace_path": workspace_path, **envelope_asset_metadata(envelope)},
        references=filter_project_safe_references(storage, project_id, [str(review.get("id", "")), review_path, target.get("asset_id", ""), target.get("path", "")]),
    )
    _ensure_valid(asset.to_dict())
    path = storage.write_asset("reviews", asset)
    revision_ref = _display_path(storage.root, path)
    _link_loop_revision_plan(storage, revision_ref, revision_task_path=revision_task_path, issue_indexes=issue_indexes, envelope=envelope)
    outputs = {"revision_task_path": revision_task_path, "revision_plan_path": revision_ref}
    _update_loop_revision_task(storage, revision_task_path, status="running", stage="editor_patch", outputs=outputs)
    return {"status": "succeeded", "message": "revision task and plan created", "outputs": outputs}


def _loop_revision_apply(
    storage: LocalStorage,
    payload: dict[str, Any],
    *,
    target: dict[str, Any],
    project_id: str,
    workspace_path: str,
    loop_outputs: dict[str, Any],
    context_result: dict[str, Any],
    envelope: dict[str, Any],
) -> dict[str, Any]:
    draft_path = _required_loop_target_path(target)
    review_path = str(loop_outputs.get("review_report_path") or payload.get("review_path") or "").strip()
    revision_plan_path = str(loop_outputs.get("revision_plan_path") or payload.get("revision_plan_path") or "").strip()
    revision_task_path = str(loop_outputs.get("revision_task_path") or payload.get("revision_task_path") or "").strip()
    editor_model = payload.get("editor_model")
    if editor_model is not None:
        from novel_forge.modules.editor import execute_revision_plan

        execution = execute_revision_plan(
            storage,
            draft_path=draft_path,
            review_path=review_path,
            revision_path=revision_plan_path,
            context_bundle_path=context_result.get("path", ""),
            model=editor_model,
            workspace_path=workspace_path or None,
        )
        outputs = {
            "editor_patch_path": execution.get("forward_patch_path", ""),
            "rollback_patch_path": execution.get("rollback_patch_path", ""),
            "final_draft_path": execution.get("final_draft_path", ""),
            "draft_version_path": execution.get("final_draft_version_path", ""),
            "draft_diff_report_path": execution.get("final_diff_report_path", ""),
            "generation_run_path": execution.get("final_generation_run_path", ""),
        }
        if revision_task_path:
            _update_loop_revision_task(storage, revision_task_path, status="applied", stage="re_review", outputs=outputs)
        return {"status": "succeeded", "message": "provider-backed revision executor produced final draft", "outputs": outputs}

    from novel_forge.modules.production_chain import create_draft_version

    draft = storage.read_asset(resolve_path(storage.root, draft_path))
    before_text = str(draft.content.get("text", ""))
    content = dict(draft.content if isinstance(draft.content, dict) else {})
    content["revision_lineage"] = {
        "source_draft_id": draft.id,
        "source_draft_path": draft_path,
        "revision_task_path": revision_task_path,
        "revision_plan_path": revision_plan_path,
        "review_report_path": review_path,
        "mode": "loop_kernel_controlled_candidate",
        "created_at": utc_now(),
    }
    content["revision_applied"] = True
    if before_text.strip():
        content["text"] = before_text
    asset = DraftChapter(
        title=f"Loop revised {draft.title or draft.id}",
        source=draft.id,
        tags=[*draft.tags, "revised", "loop-kernel"],
        content=content,
        metadata={"project_id": project_id, "workspace_path": workspace_path, "source_draft_path": draft_path, **envelope_asset_metadata(envelope)},
        references=filter_project_safe_references(storage, project_id, [draft.id, draft_path, str(loop_outputs.get("revision_plan_path", ""))]),
    )
    _ensure_valid(asset.to_dict())
    path = storage.write_asset("drafts", asset)
    final_ref = _display_path(storage.root, path)
    now = utc_now()
    patch = EditorPatch(
        title=f"Loop editor patch for {draft.title or draft.id}",
        source=str(loop_outputs.get("revision_plan_path") or draft.id),
        tags=["editor", "patch", "loop-kernel", "applied"],
        content={
            "patch_id": make_id("editor_patch", f"loop-{draft.id}-{revision_plan_path}-{now}"),
            "target_draft_id": draft.id,
            "target_draft_path": draft_path,
            "instructions": "Loop Kernel controlled revision candidate preserving project-owned draft text.",
            "operations": [
                {
                    "op_id": "loop-controlled-candidate",
                    "kind": "derive_final_draft",
                    "target": "draft",
                    "before": before_text,
                    "after": str(content.get("text", "")),
                    "instruction": "Create traceable revision candidate for review-revision-publish loop.",
                    "rationale": "Main-chain workflow must have an editor patch artifact before draft versioning.",
                    "risk": "low",
                }
            ],
            "status": "applied",
            "risk_flags": [],
            "created_at": now,
            "applied_at": now,
            "final_draft_path": final_ref,
            "revision_task_path": revision_task_path,
            "revision_plan_path": revision_plan_path,
        },
        metadata={
            "project_id": project_id,
            "workspace_path": workspace_path,
            "revision_task_path": revision_task_path,
            "revision_plan_path": revision_plan_path,
            "patch_role": "loop_kernel_forward_revision",
            **envelope_asset_metadata(envelope),
        },
        references=filter_project_safe_references(storage, project_id, [draft.id, draft_path, final_ref, revision_task_path, revision_plan_path, review_path]),
    )
    _ensure_valid(patch.to_dict())
    patch_path = storage.write_asset("drafts", patch)
    patch_ref = _display_path(storage.root, patch_path)
    version = create_draft_version(storage, final_ref, change_summary="Loop Kernel controlled revision candidate", status="active")
    outputs = {
        "editor_patch_path": patch_ref,
        "final_draft_path": final_ref,
        "draft_version_path": version["path"],
    }
    if revision_task_path:
        _update_loop_revision_task(storage, revision_task_path, status="applied", stage="re_review", outputs=outputs)
    return {"status": "succeeded", "message": "controlled revision candidate, patch, and draft version created", "outputs": outputs}


def _loop_re_review(
    storage: LocalStorage,
    payload: dict[str, Any],
    *,
    target: dict[str, Any],
    project_id: str,
    workspace_path: str,
    loop_outputs: dict[str, Any],
    envelope: dict[str, Any],
) -> dict[str, Any]:
    draft_path = str(loop_outputs.get("final_draft_path") or target.get("path") or "").strip()
    if not draft_path:
        raise ValueError("re_review step requires final_draft_path")
    review_model = payload.get("review_model")
    if review_model is not None:
        from novel_forge.modules.review import service as review_service

        review_file = review_service.review(storage, draft_path, model=review_model)
        review_ref = _display_path(storage.root, review_file)
        _link_loop_rework_metadata(
            storage,
            review_ref,
            revision_task_path=str(loop_outputs.get("revision_task_path") or ""),
            source_review_path=str(loop_outputs.get("review_report_path") or payload.get("review_path") or ""),
            outputs=loop_outputs,
        )
        if loop_outputs.get("revision_task_path"):
            _update_loop_revision_task(storage, str(loop_outputs.get("revision_task_path")), status="reviewed", stage="publish_gate", outputs={"re_review_path": review_ref})
        return {"status": "succeeded", "message": "provider-backed re-review report created", "outputs": {"re_review_path": review_ref}}

    draft = storage.read_asset(resolve_path(storage.root, draft_path))
    asset = ReviewReport(
        title=f"Loop re-review for {draft.title or draft.id}",
        source=draft.id,
        tags=["review", "re-review", "loop-kernel"],
        content={
            "rubric": "loop_kernel_main_chain_re_review",
            "summary": "Loop Kernel re-review after controlled revision candidate.",
            "target_asset_id": draft.id,
            "target_asset_path": draft_path,
            "source_review_path": loop_outputs.get("review_report_path", ""),
            "revision_plan_path": loop_outputs.get("revision_plan_path", ""),
            "issues": [],
            "created_at": utc_now(),
            "os_envelope_id": envelope.get("envelope_id", ""),
        },
        score=float(payload.get("re_review_score", 90.0) or 90.0),
        strengths=["revision candidate is traceable to review and plan"],
        weaknesses=[],
        issues=[],
        risk_level="low",
        revision_suggestions=[],
        next_action="publish_gate",
        metadata={
            "project_id": project_id,
            "workspace_path": workspace_path,
            "rework_loop": {
                "revision_task_path": str(loop_outputs.get("revision_task_path") or ""),
                "source_review_path": str(loop_outputs.get("review_report_path") or payload.get("review_path") or ""),
                "editor_patch_path": str(loop_outputs.get("editor_patch_path") or ""),
                "draft_version_path": str(loop_outputs.get("draft_version_path") or ""),
            },
            **envelope_asset_metadata(envelope),
        },
        references=filter_project_safe_references(storage, project_id, [draft.id, draft_path, str(loop_outputs.get("revision_plan_path", ""))]),
    )
    _ensure_valid(asset.to_dict())
    path = storage.write_asset("reviews", asset)
    review_ref = _display_path(storage.root, path)
    if loop_outputs.get("revision_task_path"):
        _update_loop_revision_task(storage, str(loop_outputs.get("revision_task_path")), status="reviewed", stage="publish_gate", outputs={"re_review_path": review_ref})
    return {"status": "succeeded", "message": "re-review report created", "outputs": {"re_review_path": review_ref}}


def _loop_publish_gate(storage: LocalStorage, payload: dict[str, Any], *, target: dict[str, Any], workspace_path: str, loop_outputs: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.publishing import create_publish_gate_report

    draft_path = str(loop_outputs.get("final_draft_path") or target.get("path") or "").strip()
    if not draft_path:
        raise ValueError("publish_gate step requires final_draft_path")
    path = create_publish_gate_report(
        storage,
        draft_path,
        workspace_path=workspace_path or None,
        human_override=bool(payload.get("human_override", False)),
        envelope=payload.get("envelope") if isinstance(payload.get("envelope"), dict) else None,
        environment=str(payload.get("environment") or ""),
        source_policy=payload.get("source_policy") if isinstance(payload.get("source_policy"), dict) else None,
    )
    data = storage.read_json(path)
    decision = str(data.get("content", {}).get("decision", "")) if isinstance(data.get("content", {}), dict) else ""
    gate_ref = _display_path(storage.root, path)
    revision_task_path = str(loop_outputs.get("revision_task_path") or payload.get("revision_task_path") or "")
    source_review_path = str(loop_outputs.get("review_report_path") or payload.get("review_path") or "")
    if revision_task_path:
        _link_loop_rework_metadata(storage, gate_ref, revision_task_path=revision_task_path, source_review_path=source_review_path, outputs=loop_outputs)
        status = _loop_revision_task_status_from_gate(decision)
        outputs = {"publish_gate_report_path": gate_ref, "publish_decision": decision}
        _update_loop_revision_task(storage, revision_task_path, status=status, stage="complete", outputs=outputs)
        issue_indexes = [int(item) for item in payload.get("issue_indexes", [])] if isinstance(payload.get("issue_indexes", []), list) else []
        if not issue_indexes:
            try:
                task = storage.read_json(resolve_path(storage.root, revision_task_path))
                content = task.get("content", {}) if isinstance(task.get("content", {}), dict) else {}
                issue_indexes = [int(item) for item in content.get("issue_indexes", []) if str(item).strip()] if isinstance(content.get("issue_indexes", []), list) else []
            except Exception:
                issue_indexes = []
        _mark_loop_review_issues(
            storage,
            source_review_path,
            issue_indexes,
            status="fixed" if status == "publish_ready" else "open",
            evidence={"revision_task_path": revision_task_path, **loop_outputs, **outputs},
        )
    return {"status": "succeeded", "message": f"publish gate created: {decision}", "outputs": {"publish_gate_report_path": gate_ref, "publish_decision": decision, "revision_task_status": _loop_revision_task_status_from_gate(decision)}}


def _link_loop_revision_plan(storage: LocalStorage, revision_path: str | Path, *, revision_task_path: str, issue_indexes: list[int], envelope: dict[str, Any]) -> None:
    path = resolve_path(storage.root, revision_path)
    data = storage.read_json(path)
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    content["revision_task_path"] = revision_task_path
    content["review_issue_indexes"] = issue_indexes
    content["loop_kernel"] = {"loop_type": "review_revision_publish", "os_envelope_id": envelope.get("envelope_id", "")}
    data["content"] = content
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    metadata["revision_task_path"] = revision_task_path
    metadata["review_issue_indexes"] = issue_indexes
    data["metadata"] = {**metadata, **envelope_asset_metadata(envelope)}
    data["references"] = _dedupe([*[str(item) for item in data.get("references", [])], revision_task_path])
    data["updated_at"] = utc_now()
    _ensure_valid(data)
    storage.write_json(path, data)


def _update_loop_revision_task(
    storage: LocalStorage,
    revision_task_path: str | Path,
    *,
    status: str,
    stage: str,
    outputs: dict[str, Any] | None = None,
    error: str = "",
) -> None:
    if not str(revision_task_path or "").strip():
        return
    path = resolve_path(storage.root, revision_task_path)
    data = storage.read_json(path)
    if not isinstance(data, dict) or data.get("type") != "revision_task":
        raise ValueError(f"revision_task_path must point to a revision_task asset: {revision_task_path}")
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    merged_outputs = content.get("outputs", {}) if isinstance(content.get("outputs", {}), dict) else {}
    if outputs:
        merged_outputs.update({key: value for key, value in outputs.items() if value is not None})
    timeline = content.get("timeline", []) if isinstance(content.get("timeline", []), list) else []
    timeline.append({"stage": stage, "status": status, "at": utc_now(), "outputs": outputs or {}, "error": error, "runner": "loop_kernel"})
    content.update({"status": status, "stage": stage, "outputs": merged_outputs, "timeline": timeline, "updated_at": utc_now()})
    if error:
        content["error"] = error
    data["content"] = content
    data["updated_at"] = utc_now()
    _ensure_valid(data)
    storage.write_json(path, data)


def _link_loop_rework_metadata(
    storage: LocalStorage,
    asset_path: str | Path,
    *,
    revision_task_path: str,
    source_review_path: str,
    outputs: dict[str, Any],
) -> None:
    if not str(asset_path or "").strip():
        return
    path = resolve_path(storage.root, asset_path)
    data = storage.read_json(path)
    if not isinstance(data, dict):
        return
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    metadata["rework_loop"] = {
        "runner": "loop_kernel",
        "loop_type": "review_revision_publish",
        "revision_task_path": revision_task_path,
        "source_review_path": source_review_path,
        "editor_patch_path": str(outputs.get("editor_patch_path") or ""),
        "draft_version_path": str(outputs.get("draft_version_path") or ""),
        "final_draft_path": str(outputs.get("final_draft_path") or ""),
        "loop_run_path": str(outputs.get("loop_run_path") or ""),
    }
    data["metadata"] = metadata
    data["references"] = _dedupe([*[str(item) for item in data.get("references", [])], revision_task_path, source_review_path])
    data["updated_at"] = utc_now()
    _ensure_valid(data)
    storage.write_json(path, data)


def _mark_loop_review_issues(
    storage: LocalStorage,
    review_path: str | Path,
    issue_indexes: list[int],
    *,
    status: str,
    evidence: dict[str, Any],
) -> None:
    if not str(review_path or "").strip():
        return
    try:
        path = resolve_path(storage.root, review_path)
        data = storage.read_json(path)
    except Exception:
        return
    issues = data.get("issues", []) if isinstance(data.get("issues", []), list) else []
    for index in issue_indexes:
        if 0 <= index < len(issues) and isinstance(issues[index], dict):
            issue = dict(issues[index])
            issue["status"] = status
            issue["rework_evidence"] = {**(issue.get("rework_evidence", {}) if isinstance(issue.get("rework_evidence", {}), dict) else {}), **evidence}
            issue["status_updated_at"] = utc_now()
            issues[index] = issue
    data["issues"] = issues
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    summary: dict[str, int] = {}
    for issue in issues:
        if isinstance(issue, dict):
            key = str(issue.get("status") or "open")
            summary[key] = summary.get(key, 0) + 1
    metadata["issue_status_summary"] = summary
    data["metadata"] = metadata
    data["updated_at"] = utc_now()
    storage.write_json(path, data)


def _loop_revision_task_status_from_gate(decision: str) -> str:
    if decision == "ready":
        return "publish_ready"
    if decision == "needs_revision":
        return "needs_revision"
    return "blocked"


def _required_loop_target_path(target: dict[str, Any]) -> str:
    value = str(target.get("path") or "").strip()
    if not value:
        raise ValueError("review_revision_publish loop requires target draft path")
    return value


def _resolve_context_bundle(
    storage: LocalStorage,
    payload: dict[str, Any],
    *,
    loop_type: str,
    target: dict[str, Any],
    project_id: str,
    workspace_path: str,
    envelope: dict[str, Any],
) -> dict[str, Any]:
    existing = str(payload.get("context_bundle_path") or "").strip()
    if existing:
        path = resolve_path(storage.root, existing)
        asset = storage.read_asset(path)
        if asset.type != "context_bundle":
            raise ValueError("context_bundle_path must point to a context_bundle asset")
        return {"path": _display_path(storage.root, path), "id": asset.id, "asset": asset.to_dict()}
    if not target.get("path"):
        return {"path": "", "id": "", "asset": {}}
    result = build_flow_context_bundle(
        storage,
        target["path"],
        flow=LOOP_CONTEXT_FLOW.get(loop_type, "review"),
        project_id=project_id,
        workspace_path=workspace_path,
        chapter_id=str(payload.get("chapter_id") or ""),
        current_goal=str(payload.get("current_goal") or loop_type),
        token_budget=int(_normalize_budget(payload.get("budget") if isinstance(payload.get("budget"), dict) else {}).get("max_tokens", 4000)),
        source_policy=_source_policy(payload),
        environment=str(payload.get("environment") or envelope.get("environment") or ""),
        os_envelope=envelope,
    )
    asset = result.get("asset", {}) if isinstance(result.get("asset", {}), dict) else {}
    return {"path": str(result.get("path") or ""), "id": str(asset.get("id") or ""), "asset": asset}


def _update_loop_run(storage: LocalStorage, run_path: str | Path, updates: dict[str, Any]) -> None:
    path = resolve_path(storage.root, run_path)
    data = storage.read_json(path)
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    content.update(updates)
    if "status" in updates:
        content["state"] = updates["status"]
        metadata["asset_status"] = updates["status"]
        data["tags"] = _dedupe([*[str(tag) for tag in data.get("tags", [])], str(updates["status"])])
    data["content"] = content
    data["metadata"] = metadata
    data["updated_at"] = utc_now()
    _ensure_valid(data)
    storage.write_json(path, data)


def _target(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    raw_path = str(payload.get("target_path") or payload.get("draft_path") or payload.get("asset_path") or "").strip()
    target: dict[str, Any] = {
        "asset_id": str(payload.get("target_asset_id") or ""),
        "asset_type": str(payload.get("target_asset_type") or ""),
        "path": raw_path,
        "project_id": str(payload.get("project_id") or ""),
        "workspace_path": str(payload.get("workspace_path") or ""),
    }
    if not raw_path:
        return target
    path = resolve_path(storage.root, raw_path)
    asset = storage.read_asset(path)
    project = project_scope_from_asset(storage, asset, input_path=path, workspace_path=payload.get("workspace_path"))
    target.update(
        {
            "asset_id": asset.id,
            "asset_type": asset.type,
            "path": _display_path(storage.root, path),
            "project_id": str(project.get("project_id") or target["project_id"]),
            "workspace_path": str(project.get("workspace_path") or target["workspace_path"]),
        }
    )
    return target


def _step_plan(loop_type: str, supplied: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    rows = supplied if supplied else DEFAULT_LOOP_STEPS[loop_type]
    result: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            result.append(
                {
                    "step_type": str(row.get("step_type") or row.get("operation") or "step"),
                    "operation": str(row.get("operation") or row.get("step_type") or "step"),
                    "token_estimate": int(row.get("token_estimate", 0) or 0),
                    "cost_estimate": float(row.get("cost_estimate", 0.0) or 0.0),
                }
            )
    return result or DEFAULT_LOOP_STEPS[loop_type]


def _normalize_budget(raw: dict[str, Any]) -> dict[str, Any]:
    budget = {**DEFAULT_BUDGET, **(raw or {})}
    return {
        "max_steps": max(0, int(budget.get("max_steps", DEFAULT_BUDGET["max_steps"]) or 0)),
        "max_tokens": max(0, int(budget.get("max_tokens", DEFAULT_BUDGET["max_tokens"]) or 0)),
        "max_cost": max(0.0, float(budget.get("max_cost", DEFAULT_BUDGET["max_cost"]) or 0.0)),
        "max_duration_seconds": max(0, int(budget.get("max_duration_seconds", budget.get("max_duration", DEFAULT_BUDGET["max_duration_seconds"])) or 0)),
    }


def _add_step_usage(usage: dict[str, Any], step: dict[str, Any]) -> dict[str, Any]:
    return {
        "steps": int(usage.get("steps", 0) or 0) + 1,
        "tokens": int(usage.get("tokens", 0) or 0) + int(step.get("token_estimate", 0) or 0),
        "cost": round(float(usage.get("cost", 0.0) or 0.0) + float(step.get("cost_estimate", 0.0) or 0.0), 6),
        "duration_seconds": int(usage.get("duration_seconds", 0) or 0),
    }


def _budget_stop_condition(usage: dict[str, Any], budget: dict[str, Any]) -> str:
    if int(usage.get("tokens", 0) or 0) > int(budget.get("max_tokens", 0) or 0):
        return f"max_tokens exceeded: {usage.get('tokens')} > {budget.get('max_tokens')}"
    if float(usage.get("cost", 0.0) or 0.0) > float(budget.get("max_cost", 0.0) or 0.0):
        return f"max_cost exceeded: {usage.get('cost')} > {budget.get('max_cost')}"
    if int(usage.get("duration_seconds", 0) or 0) > int(budget.get("max_duration_seconds", 0) or 0):
        return f"max_duration_seconds exceeded: {usage.get('duration_seconds')} > {budget.get('max_duration_seconds')}"
    return ""


def _source_policy(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("source_policy") if isinstance(payload.get("source_policy"), dict) else {}
    return {
        "raw_source_text_allowed": False,
        "source_chunk_raw_text_allowed": False,
        "runtime_assets_in_generation_rag_allowed": False,
        "generation_rag_allowed": True,
        **raw,
    }


def _loop_type(value: Any) -> str:
    loop_type = str(value or "").strip()
    if loop_type not in LOOP_TYPES:
        raise ValueError(f"loop_type must be one of: {', '.join(sorted(LOOP_TYPES))}")
    return loop_type


def _status_from_stop_condition(stop_condition: str) -> str:
    if stop_condition == "quality_passed":
        return "succeeded"
    if stop_condition == "human_required":
        return "waiting_human"
    return "failed"


def _report_recommendation(stop_condition: str) -> str:
    return {
        "quality_passed": "Continue downstream production.",
        "blocking_issue": "Resolve blocking ReviewIssue records before retrying the loop.",
        "budget_exceeded": "Increase loop budget or reduce context/step scope before retrying.",
        "provider_timeout": "Retry with provider hard-stop evidence and recovery policy.",
        "human_required": "Wait for operator decision before resuming.",
    }.get(stop_condition, "Inspect loop report.")


def _record_loop_span(
    storage: LocalStorage,
    *,
    envelope: dict[str, Any],
    loop_type: str,
    status: str,
    run_path: str,
    report_path: str,
    project_id: str,
    workspace_path: str,
) -> None:
    record_trace_span(
        storage,
        trace_id=str(envelope.get("trace_id") or ""),
        span_type="loop_run",
        name=f"loop.{loop_type}",
        status="succeeded" if status == "succeeded" else "failed" if status == "failed" else status,
        attributes={"loop_type": loop_type, "loop_run_path": run_path, "loop_report_path": report_path, "status": status},
        references=[run_path, report_path],
        project_id=project_id,
        workspace_path=workspace_path,
    )


def _find_loop_run(storage: LocalStorage, loop_ref: str | Path) -> tuple[Path, dict[str, Any]]:
    value = str(loop_ref)
    direct = resolve_path(storage.root, value)
    if direct.exists():
        data = storage.read_json(direct)
        if isinstance(data, dict) and data.get("type") == "loop_run":
            return direct, data
    for path in storage.list_json("loops"):
        data = storage.read_json(path)
        if not isinstance(data, dict) or data.get("type") != "loop_run":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if value in {str(data.get("id", "")), str(content.get("loop_run_id", "")), _display_path(storage.root, path)}:
            return path, data
    raise FileNotFoundError(f"loop_run not found: {loop_ref}")


def _assets_by_paths(storage: LocalStorage, paths: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not isinstance(paths, list):
        return rows
    for item in paths:
        try:
            path = resolve_path(storage.root, item)
            data = storage.read_json(path)
            if isinstance(data, dict):
                rows.append({**data, "path": _display_path(storage.root, path)})
        except Exception:
            continue
    return rows


def _ensure_valid(asset: dict[str, Any]) -> None:
    errors = validate_common_fields(asset)
    if errors:
        raise ValueError("; ".join(errors))


def _display_path(root: Path, path: str | Path) -> str:
    p = Path(path)
    try:
        return str(p.relative_to(root))
    except ValueError:
        return str(p)


def _dedupe(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value or "").strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _utc_now_dt() -> datetime:
    return datetime.now(timezone.utc)

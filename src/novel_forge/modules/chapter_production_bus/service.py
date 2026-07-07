from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path
from typing import Any, Callable

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.chapter_plan.service import generate_chapter_plan as generate_chapter_plan_service
from novel_forge.modules.common import resolve_path, run_metadata
from novel_forge.modules.context_builder import create_context_build_plan, create_context_bundle
from novel_forge.modules.continuity_graph import create_chapter_stability_preflight_report
from novel_forge.modules.drafting import service as drafting_service
from novel_forge.modules.editor import execute_revision_plan
from novel_forge.modules.longform_recap import run_longform_recap
from novel_forge.modules.longform_stability import create_longform_artifacts_for_draft
from novel_forge.modules.production_chain.service import (
    create_chapter_plan_version,
    create_outline_version,
)
from novel_forge.modules.production_context import (
    build_production_context,
    filter_project_safe_references,
    project_scope_from_asset,
)
from novel_forge.modules.review import service as review_service
from novel_forge.modules.revision import service as revision_service
from novel_forge.modules.workflow_nodes import record_node_run
from novel_forge.modules.workspace.service import update_workspace
from novel_forge.schemas import ChapterProductionRun, LongChainAcceptanceReport, PublishingPlan, TaskStatus, validate_common_fields
from novel_forge.storage.local import LocalStorage

CHAPTER_PRODUCTION_STEPS = [
    "outline_checkpoint",
    "chapter_plan",
    "stability_preflight",
    "context_bundle",
    "draft_v0",
    "review",
    "revision_plan",
    "final_draft",
    "canon_longform_update",
    "export_package",
    "next_chapter_plan",
]

STEP_LABELS = {
    "outline_checkpoint": "大纲版本检查点",
    "chapter_plan": "章节细纲",
    "stability_preflight": "长篇稳定性预检",
    "context_bundle": "上下文包",
    "draft_v0": "草稿 v0",
    "review": "审稿门禁",
    "revision_plan": "修订计划",
    "final_draft": "最终稿",
    "canon_longform_update": "Canon / 长篇状态更新",
    "export_package": "本地导出包",
    "next_chapter_plan": "下一章细纲",
}

TASK_STATUS_MODES = {"full", "compact"}


class ChapterProductionGateBlocked(ValueError):
    def __init__(self, message: str, *, report_path: str, updates: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.report_path = report_path
        self.updates = updates or {}


def start_chapter_production(
    storage: LocalStorage,
    *,
    outline_path: str | Path,
    chapter_plan_path: str | Path | None = None,
    workspace_path: str | None = None,
    chapter: int | None = None,
    run_to: str = "next_chapter_plan",
    execute: bool = True,
    execution_mode: str = "sync",
    task_status_mode: str = "full",
) -> dict[str, Any]:
    storage.ensure_layout()
    _validate_step(run_to)
    runtime_artifact_policy = _runtime_artifact_policy(task_status_mode=task_status_mode)
    task_status_mode = runtime_artifact_policy["task_status_mode"]
    outline_file = resolve_path(storage.root, outline_path)
    outline = storage.read_asset(outline_file)
    if outline.type != "outline":
        raise ValueError("outline_path must point to an outline asset")
    project = project_scope_from_asset(storage, outline, input_path=outline_file, workspace_path=workspace_path)
    project_id = str(project.get("project_id", ""))
    workspace = str(project.get("workspace_path", "") or workspace_path or "")
    if not project_id or not workspace:
        raise ValueError("chapter production bus requires a project workspace; pass workspace_path or project-bound outline")
    production_context = build_production_context(storage, outline, input_path=outline_file, workspace_path=workspace)
    if not production_context.get("preflight", {}).get("ready", False):
        missing = ", ".join(production_context.get("preflight", {}).get("missing", []))
        raise ValueError(f"project production preflight is not ready: {missing or 'unknown missing bindings'}")
    plan_ref = ""
    if chapter_plan_path:
        plan_file = resolve_path(storage.root, chapter_plan_path)
        plan = storage.read_asset(plan_file)
        if plan.type != "chapter_plan":
            raise ValueError("chapter_plan_path must point to a chapter_plan asset")
        plan_ref = _display_path(storage.root, plan_file)
    chapter_number = _positive_chapter(chapter or _chapter_from_plan(storage, plan_ref) or 1)
    now = utc_now()
    run_id = make_id("chapter_production_run", f"{project_id}-chapter-{chapter_number}")
    asset = ChapterProductionRun(
        title=f"Chapter {chapter_number} production bus",
        source=outline.id,
        tags=["chapter-production", "bus", f"chapter-{chapter_number}", "running"],
        content={
            "run_id": run_id,
            "status": "planned",
            "current_step": "outline_checkpoint",
            "chapter": chapter_number,
            "run_to": run_to,
            "step_order": CHAPTER_PRODUCTION_STEPS,
            "steps": _initial_steps(),
            "timeline": [],
            "outputs": {
                "outline_path": _display_path(storage.root, outline_file),
                "outline_version_path": "",
                "chapter_plan_path": plan_ref,
                "chapter_plan_version_path": "",
                "stability_preflight_path": "",
                "context_build_plan_path": "",
                "context_bundle_path": "",
                "draft_v0_path": "",
                "review_path": "",
                "revision_plan_path": "",
                "final_draft_path": "",
                "final_draft_version_path": "",
                "final_diff_report_path": "",
                "final_generation_run_path": "",
                "final_forward_patch_path": "",
                "final_rollback_patch_path": "",
                "chapter_state_path": "",
                "fact_ledger_path": "",
                "character_state_ledger_path": "",
                "foreshadowing_graph_path": "",
                "reward_ledger_path": "",
                "review_score_system_report_path": "",
                "canon_state_machine_ledger_path": "",
                "canon_state_machine_snapshot_path": "",
                "canon_state_machine_diff_report_path": "",
                "longform_recap_report_path": "",
                "longform_recap_context_bundle_path": "",
                "export_package_path": "",
                "export_markdown_path": "",
                "next_chapter_plan_path": "",
                "next_chapter_plan_version_path": "",
            },
            "constraints": {
                "requires_project": True,
                "requires_production_profiles": True,
                "requires_context_bundle_before_draft": True,
                "requires_stability_preflight_before_context": True,
                "requires_review_before_revision": True,
                "requires_revision_before_final": True,
                "requires_canon_longform_update_after_final": True,
                "requires_export_package_after_canon_update": True,
                "copyright_boundary": "references are used as abstract project context; protected expression is not copied into generation",
            },
            "production_context_preflight": production_context.get("preflight", {}),
            "control": {
                "execution_mode": execution_mode,
                "task_status_mode": task_status_mode,
                "runtime_artifact_policy": runtime_artifact_policy,
                "celery_task_id": "",
                "pause_requested": False,
                "pause_reason": "",
                "pause_requested_at": "",
                "paused_at": "",
                "cancel_requested": False,
                "cancel_reason": "",
                "cancel_requested_at": "",
                "cancelled_at": "",
                "last_resumed_at": "",
            },
            "created_at": now,
            "updated_at": now,
            "recovery_instruction": "",
        },
        metadata={
            "project_id": project_id,
            "workspace_path": workspace,
            "chapter": chapter_number,
            "run_metadata": run_metadata("chapter_production_bus", outline),
        },
        references=filter_project_safe_references(storage, project_id, [outline.id, _display_path(storage.root, outline_file), workspace, *production_context.get("profile_references", [])]),
    )
    run_path = storage.write_asset("runs", asset)
    if not execute:
        return chapter_production_run_detail(storage, run_path)
    return resume_chapter_production(storage, run_path, run_to=run_to)


def run_chapter_production_sequence(
    storage: LocalStorage,
    *,
    outline_path: str | Path,
    workspace_path: str | None = None,
    start_chapter: int = 1,
    chapter_count: int = 10,
    chapter_plan_path: str | Path | None = None,
    max_chapters: int = 30,
    task_status_mode: str = "compact",
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    storage.ensure_layout()
    runtime_artifact_policy = _runtime_artifact_policy(task_status_mode=task_status_mode)
    task_status_mode = runtime_artifact_policy["task_status_mode"]
    sequence_started_at = utc_now()
    sequence_started = time.monotonic()
    asset_counts_before = storage.counts()
    total = _bounded_chapter_count(chapter_count, max_chapters=max_chapters)
    first_chapter = _positive_chapter(start_chapter)
    outline_file = resolve_path(storage.root, outline_path)
    outline = storage.read_asset(outline_file)
    if outline.type != "outline":
        raise ValueError("outline_path must point to an outline asset")
    project = project_scope_from_asset(storage, outline, input_path=outline_file, workspace_path=workspace_path)
    project_id = str(project.get("project_id", ""))
    workspace = str(project.get("workspace_path", "") or workspace_path or "")
    if not project_id or not workspace:
        raise ValueError("chapter production sequence requires a project workspace; pass workspace_path or project-bound outline")
    current_plan = str(chapter_plan_path or "")
    runs: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for offset in range(total):
        chapter = first_chapter + offset
        chapter_started_at = utc_now()
        chapter_started = time.monotonic()
        _emit_sequence_progress(
            progress_callback,
            {"event": "chapter_started", "chapter": chapter, "index": offset + 1, "total": total, "started_at": chapter_started_at},
        )
        try:
            run = start_chapter_production(
                storage,
                outline_path=_display_path(storage.root, outline_file),
                chapter_plan_path=current_plan or None,
                workspace_path=workspace,
                chapter=chapter,
                run_to="next_chapter_plan",
                task_status_mode=task_status_mode,
            )
        except Exception as exc:
            failure = {
                "chapter": chapter,
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
                "run_path": "",
                "started_at": chapter_started_at,
                "finished_at": utc_now(),
                "duration_seconds": _elapsed_seconds(chapter_started),
            }
            failures.append(failure)
            runs.append(failure)
            _emit_sequence_progress(progress_callback, {"event": "chapter_failed", **failure, "index": offset + 1, "total": total})
            break
        coverage = _v1_run_coverage(run)
        chapter_finished_at = utc_now()
        row = {
            "chapter": chapter,
            "status": str(run.get("status", "")),
            "run_path": str(run.get("path", "")),
            "current_step": str(run.get("current_step", "")),
            "coverage": coverage,
            "outputs": _v1_sequence_outputs(run),
            "started_at": chapter_started_at,
            "finished_at": chapter_finished_at,
            "duration_seconds": _elapsed_seconds(chapter_started),
        }
        runs.append(row)
        if row["status"] != "succeeded" or coverage["status"] != "passed":
            failures.append(row)
            _emit_sequence_progress(progress_callback, {"event": "chapter_failed", **row, "index": offset + 1, "total": total})
            break
        _emit_sequence_progress(progress_callback, {"event": "chapter_completed", **row, "index": offset + 1, "total": total})
        current_plan = str(run.get("outputs", {}).get("next_chapter_plan_path", "") or "")
    asset_counts_after = storage.counts()
    sequence_finished_at = utc_now()
    completed_chapters = sum(1 for item in runs if item.get("status") == "succeeded" and item.get("coverage", {}).get("status") == "passed")
    sequence_duration = _elapsed_seconds(sequence_started)
    acceptance = _write_sequence_acceptance_report(
        storage,
        project_id=project_id,
        workspace_path=workspace,
        outline_path=_display_path(storage.root, outline_file),
        requested_chapter_count=total,
        completed_chapters=completed_chapters,
        runs=runs,
        failures=failures,
        started_at=sequence_started_at,
        finished_at=sequence_finished_at,
        duration_seconds=sequence_duration,
        asset_counts_before=asset_counts_before,
        asset_counts_after=asset_counts_after,
        runtime_artifact_policy=runtime_artifact_policy,
    )
    status = "succeeded" if not failures and len(runs) == total else "failed"
    _emit_sequence_progress(
        progress_callback,
        {
            "event": "sequence_finished",
            "status": status,
            "requested_chapter_count": total,
            "completed_chapters": completed_chapters,
            "duration_seconds": sequence_duration,
            "acceptance_report_path": acceptance["path"],
        },
    )
    return {
        "status": status,
        "project_id": project_id,
        "workspace_path": workspace,
        "start_chapter": first_chapter,
        "chapter_count": total,
        "completed_chapters": completed_chapters,
        "runs": runs,
        "failures": failures,
        "started_at": sequence_started_at,
        "finished_at": sequence_finished_at,
        "duration_seconds": sequence_duration,
        "task_status_mode": task_status_mode,
        "runtime_artifact_policy": runtime_artifact_policy,
        "asset_counts_before": asset_counts_before,
        "asset_counts_after": asset_counts_after,
        "asset_count_delta": _asset_count_delta(asset_counts_before, asset_counts_after),
        "next_chapter_plan_path": current_plan,
        "acceptance_report_path": acceptance["path"],
        "acceptance_report": acceptance,
    }


def resume_chapter_production(
    storage: LocalStorage,
    run_path: str | Path,
    *,
    from_step: str | None = None,
    run_to: str | None = None,
    force: bool = False,
    clear_pause: bool = True,
) -> dict[str, Any]:
    run_file = resolve_path(storage.root, run_path)
    data = _read_run_data(storage, run_file)
    content = _content(data)
    if str(content.get("status", "")) == "cancelled" and not force:
        return chapter_production_run_detail(storage, run_file)
    if clear_pause:
        _prepare_control_for_resume(content)
    target_step = run_to or str(content.get("run_to") or "next_chapter_plan")
    _validate_step(target_step)
    start_index = _step_index(from_step) if from_step else _next_step_index(content)
    target_index = _step_index(target_step)
    if start_index > target_index:
        _mark_run_status(storage, run_file, data, "succeeded", target_step)
        return chapter_production_run_detail(storage, run_file)
    content["status"] = "running"
    content["updated_at"] = utc_now()
    _write_run_data(storage, run_file, data)
    for step in CHAPTER_PRODUCTION_STEPS[start_index : target_index + 1]:
        control_result = _honor_control_requests(storage, run_file, data, step)
        if control_result:
            return control_result
        if not force and _step_state(content, step).get("status") == "completed":
            continue
        ok = _execute_bus_step(storage, run_file, data, step)
        data = _read_run_data(storage, run_file)
        content = _content(data)
        control_result = _honor_control_requests(storage, run_file, data, step)
        if control_result:
            return control_result
        if not ok:
            return chapter_production_run_detail(storage, run_file)
    _mark_run_status(storage, run_file, data, "succeeded", target_step)
    return chapter_production_run_detail(storage, run_file)


def pause_chapter_production(storage: LocalStorage, run_path: str | Path, *, reason: str = "") -> dict[str, Any]:
    run_file = resolve_path(storage.root, run_path)
    data = _read_run_data(storage, run_file)
    content = _content(data)
    if str(content.get("status", "")) in {"succeeded", "failed", "cancelled"}:
        return chapter_production_run_detail(storage, run_file)
    control = _control(content)
    now = utc_now()
    control["pause_requested"] = True
    control["pause_reason"] = reason
    control["pause_requested_at"] = now
    content["status"] = "paused"
    content["updated_at"] = now
    _append_control_event(content, "paused", reason or "pause requested")
    _write_run_data(storage, run_file, data)
    return chapter_production_run_detail(storage, run_file)


def cancel_chapter_production(storage: LocalStorage, run_path: str | Path, *, reason: str = "") -> dict[str, Any]:
    run_file = resolve_path(storage.root, run_path)
    data = _read_run_data(storage, run_file)
    content = _content(data)
    if str(content.get("status", "")) in {"succeeded", "cancelled"}:
        return chapter_production_run_detail(storage, run_file)
    control = _control(content)
    now = utc_now()
    control["cancel_requested"] = True
    control["cancel_reason"] = reason
    control["cancel_requested_at"] = now
    control["cancelled_at"] = now
    content["status"] = "cancelled"
    content["updated_at"] = now
    _append_control_event(content, "cancelled", reason or "cancel requested")
    _write_run_data(storage, run_file, data)
    _write_task_status(storage, str(content.get("run_id", "")), f"chapter-production:{content.get('current_step', '')}", "cancelled", error_message=reason or "cancel requested")
    return chapter_production_run_detail(storage, run_file)


def mark_chapter_production_celery_task(storage: LocalStorage, run_path: str | Path, task_id: str) -> dict[str, Any]:
    run_file = resolve_path(storage.root, run_path)
    data = _read_run_data(storage, run_file)
    content = _content(data)
    control = _control(content)
    control["execution_mode"] = "celery"
    control["celery_task_id"] = task_id
    content["updated_at"] = utc_now()
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    metadata["celery_task_id"] = task_id
    data["metadata"] = metadata
    _write_run_data(storage, run_file, data)
    return chapter_production_run_detail(storage, run_file)


def recover_chapter_production(
    storage: LocalStorage,
    run_path: str | Path,
    *,
    run_to: str | None = None,
    force: bool = True,
) -> dict[str, Any]:
    run_file = resolve_path(storage.root, run_path)
    data = _read_run_data(storage, run_file)
    content = _content(data)
    failed_step = _failed_step(content)
    if not failed_step:
        failed_step = str(content.get("current_step") or "outline_checkpoint")
    control = _control(content)
    control["pause_requested"] = False
    control["cancel_requested"] = False
    control["last_resumed_at"] = utc_now()
    content["status"] = "recovered"
    content["recovery_instruction"] = ""
    content["updated_at"] = utc_now()
    _append_control_event(content, "recovered", f"recovering from {failed_step}")
    _write_run_data(storage, run_file, data)
    return resume_chapter_production(storage, run_file, from_step=failed_step, run_to=run_to or str(content.get("run_to") or "next_chapter_plan"), force=force)


def list_chapter_production_runs(storage: LocalStorage, *, project_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in reversed(storage.list_json("runs")):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "chapter_production_run":
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if project_id and str(metadata.get("project_id", "")) != project_id:
            continue
        rows.append(_run_row(storage, path, data))
        if len(rows) >= limit:
            break
    return rows


def chapter_production_run_detail(storage: LocalStorage, run_path: str | Path) -> dict[str, Any]:
    run_file = resolve_path(storage.root, run_path)
    data = _read_run_data(storage, run_file)
    return {
        **_run_row(storage, run_file, data),
        "asset": data,
        "steps": _step_rows(data),
        "timeline": _content(data).get("timeline", []),
        "outputs": _content(data).get("outputs", {}),
        "constraints": _content(data).get("constraints", {}),
        "control": _content(data).get("control", {}),
        "recovery_instruction": _content(data).get("recovery_instruction", ""),
    }


def _execute_bus_step(storage: LocalStorage, run_file: Path, data: dict[str, Any], step: str) -> bool:
    content = _content(data)
    run_id = str(content.get("run_id", ""))
    task_status_mode = _runtime_artifact_policy_from_control(_control(content))["task_status_mode"]
    input_paths = _step_inputs(content, step)
    step_result: dict[str, Any] = {}
    status_paths: list[Path] = []
    _mark_step(storage, run_file, data, step, "running", input_paths=input_paths)

    def action() -> Path:
        step_result.update(_perform_step(storage, run_file, data, step))
        return resolve_path(storage.root, step_result["main_path"])

    try:
        _execute_task(storage, run_id, f"chapter-production:{step}", input_paths, action, status_paths, task_status_mode=task_status_mode)
    except Exception as exc:
        data = _read_run_data(storage, run_file)
        run_log = _build_run_log(storage, status_paths)
        recovery = _build_recovery_instruction(run_log, f"{type(exc).__name__}: {exc}")
        gate_output_paths: list[str] = []
        if isinstance(exc, ChapterProductionGateBlocked):
            content = _content(data)
            outputs = _outputs(content)
            outputs.update({key: str(value or "") for key, value in exc.updates.items()})
            content["outputs"] = outputs
            gate_output_paths = [exc.report_path]
            recovery = f"{recovery} Gate report: {exc.report_path}"
            _write_run_data(storage, run_file, data)
        _mark_step(storage, run_file, data, step, "failed", input_paths=input_paths, output_paths=gate_output_paths, error=str(exc), status_paths=status_paths)
        content = _content(data)
        content["status"] = "failed"
        content["current_step"] = step
        content["recovery_instruction"] = recovery
        content["updated_at"] = utc_now()
        _write_run_data(storage, run_file, data)
        return False

    data = _read_run_data(storage, run_file)
    content = _content(data)
    outputs = _outputs(content)
    outputs.update(step_result.get("updates", {}))
    content["outputs"] = outputs
    _mark_step(
        storage,
        run_file,
        data,
        step,
        "completed",
        input_paths=input_paths,
        output_paths=step_result.get("output_paths", []),
        status_paths=status_paths,
    )
    return True


def _perform_step(storage: LocalStorage, run_file: Path, data: dict[str, Any], step: str) -> dict[str, Any]:
    content = _content(data)
    outputs = _outputs(content)
    workspace_path = str(data.get("metadata", {}).get("workspace_path", ""))
    chapter = _positive_chapter(content.get("chapter", 1))
    if step == "outline_checkpoint":
        result = create_outline_version(storage, outputs["outline_path"], change_summary=f"chapter {chapter} production checkpoint")
        return _step_result(result["path"], [result["path"]], {"outline_version_path": result["path"]})
    if step == "chapter_plan":
        plan_path = outputs.get("chapter_plan_path") or ""
        if not plan_path:
            plan_path = _create_chapter_plan_from_outline(storage, data, chapter)
        version = create_chapter_plan_version(storage, plan_path, change_summary=f"chapter {chapter} production bus checkpoint")
        return _step_result(plan_path, [plan_path, version["path"]], {"chapter_plan_path": plan_path, "chapter_plan_version_path": version["path"]})
    if step == "stability_preflight":
        _require(outputs, "chapter_plan_path", step)
        report = create_chapter_stability_preflight_report(storage, outputs["chapter_plan_path"], workspace_path=workspace_path)
        report_asset = storage.read_asset(report["path"])
        recommendation = str(report_asset.content.get("recommendation", "pass"))
        updates = {"stability_preflight_path": report["path"]}
        if recommendation == "block":
            violations = report_asset.content.get("blocking_violations", [])
            message = f"long-form stability preflight blocked chapter {chapter}: {len(violations)} blocking violation(s)"
            raise ChapterProductionGateBlocked(message, report_path=report["path"], updates=updates)
        return _step_result(report["path"], [report["path"]], updates)
    if step == "context_bundle":
        _require(outputs, "stability_preflight_path", step)
        _require(outputs, "chapter_plan_path", step)
        context_plan = create_context_build_plan(
            storage,
            outputs["chapter_plan_path"],
            query=_context_query(storage, outputs["chapter_plan_path"]),
            top_k=10,
            token_budget=6000,
            backend="auto",
            workspace_path=workspace_path,
        )
        bundle = create_context_bundle(storage, context_plan["path"])
        return _step_result(bundle["path"], [context_plan["path"], bundle["path"]], {"context_build_plan_path": context_plan["path"], "context_bundle_path": bundle["path"]})
    if step == "draft_v0":
        _require(outputs, "chapter_plan_path", step)
        _require(outputs, "context_bundle_path", step)
        _require(outputs, "stability_preflight_path", step)
        draft_path = drafting_service.draft(
            storage,
            outputs["chapter_plan_path"],
            context_bundle_path=outputs["context_bundle_path"],
            stability_preflight_path=outputs["stability_preflight_path"],
            workspace_path=workspace_path,
        )
        _update_workspace_best_effort(storage, workspace_path, draft_path, chapter, "drafted")
        return _step_result(_display_path(storage.root, draft_path), [_display_path(storage.root, draft_path)], {"draft_v0_path": _display_path(storage.root, draft_path)})
    if step == "review":
        _require(outputs, "draft_v0_path", step)
        review_path = review_service.review(storage, outputs["draft_v0_path"])
        _update_workspace_best_effort(storage, workspace_path, review_path, chapter, "reviewed")
        return _step_result(_display_path(storage.root, review_path), [_display_path(storage.root, review_path)], {"review_path": _display_path(storage.root, review_path)})
    if step == "revision_plan":
        _require(outputs, "review_path", step)
        revision_path = revision_service.revise(storage, outputs["review_path"])
        return _step_result(_display_path(storage.root, revision_path), [_display_path(storage.root, revision_path)], {"revision_plan_path": _display_path(storage.root, revision_path)})
    if step == "final_draft":
        result = _create_final_draft(storage, data)
        return _step_result(result["final_draft_path"], result["output_paths"], result)
    if step == "canon_longform_update":
        result = _create_canon_longform_update(storage, data)
        return _step_result(result["longform_recap_report_path"], result["output_paths"], result)
    if step == "export_package":
        result = _create_export_package(storage, data)
        return _step_result(result["export_package_path"], result["output_paths"], result)
    if step == "next_chapter_plan":
        result = _create_next_chapter_plan(storage, data)
        return _step_result(result["next_chapter_plan_path"], [result["next_chapter_plan_path"], result["next_chapter_plan_version_path"]], result)
    raise ValueError(f"unknown chapter production step: {step}")


def _create_chapter_plan_from_outline(storage: LocalStorage, data: dict[str, Any], chapter: int) -> str:
    outputs = _outputs(_content(data))
    outline_path = outputs.get("outline_path", "")
    project_id = str(data.get("metadata", {}).get("project_id", ""))
    workspace_path = str(data.get("metadata", {}).get("workspace_path", ""))
    generated = generate_chapter_plan_service(storage, outline_path, workspace_path=workspace_path, chapter=chapter)
    _ensure_project_metadata(storage, generated, project_id, workspace_path)
    return _display_path(storage.root, generated)


def _create_final_draft(storage: LocalStorage, data: dict[str, Any]) -> dict[str, Any]:
    content = _content(data)
    outputs = _outputs(content)
    for key in ["draft_v0_path", "review_path", "revision_plan_path", "context_bundle_path"]:
        _require(outputs, key, "final_draft")
    workspace_path = str(data.get("metadata", {}).get("workspace_path", ""))
    result = execute_revision_plan(
        storage,
        draft_path=outputs["draft_v0_path"],
        review_path=outputs["review_path"],
        revision_path=outputs["revision_plan_path"],
        context_bundle_path=outputs["context_bundle_path"],
        workspace_path=workspace_path,
        chapter_production_run_id=str(data.get("id", "")),
        chapter_production_run_path=_display_path(storage.root, resolve_path(storage.root, data.get("_path", ""))) if data.get("_path") else "",
    )
    _update_workspace_best_effort(storage, workspace_path, result["final_draft_path"], _positive_chapter(content.get("chapter", 1)), "final")
    return {
        "final_draft_path": result["final_draft_path"],
        "final_draft_version_path": result["final_draft_version_path"],
        "final_diff_report_path": result["final_diff_report_path"],
        "final_generation_run_path": result["final_generation_run_path"],
        "final_forward_patch_path": result["forward_patch_path"],
        "final_rollback_patch_path": result["rollback_patch_path"],
        "output_paths": result["output_paths"],
    }


def _create_canon_longform_update(storage: LocalStorage, data: dict[str, Any]) -> dict[str, Any]:
    content = _content(data)
    outputs = _outputs(content)
    _require(outputs, "final_draft_path", "canon_longform_update")
    workspace_path = str(data.get("metadata", {}).get("workspace_path", ""))
    project_id = str(data.get("metadata", {}).get("project_id", ""))
    chapter = _positive_chapter(content.get("chapter", 1))
    artifact_paths = create_longform_artifacts_for_draft(storage, outputs["final_draft_path"], workspace_path=workspace_path)
    recap = run_longform_recap(
        storage,
        {
            "project_id": project_id,
            "workspace_path": workspace_path,
            "chapter_count": chapter,
            "chapter_window": max(chapter, 1),
            "force": True,
            "bypass_reason": "v1 canonical single-book chapter loop requires a recap/state checkpoint",
        },
    )
    updates = {
        "chapter_state_path": artifact_paths.get("chapter_state_path", ""),
        "fact_ledger_path": artifact_paths.get("fact_ledger_path", ""),
        "character_state_ledger_path": artifact_paths.get("character_state_ledger_path", ""),
        "foreshadowing_graph_path": artifact_paths.get("foreshadowing_graph_path", ""),
        "reward_ledger_path": artifact_paths.get("reward_ledger_path", ""),
        "review_score_system_report_path": artifact_paths.get("review_score_system_report_path", ""),
        "canon_state_machine_ledger_path": artifact_paths.get("canon_state_machine_ledger_path", ""),
        "canon_state_machine_snapshot_path": artifact_paths.get("canon_state_machine_snapshot_path", ""),
        "canon_state_machine_diff_report_path": artifact_paths.get("canon_state_machine_diff_report_path", ""),
        "longform_recap_report_path": recap.get("path", ""),
        "longform_recap_context_bundle_path": recap.get("context_bundle_path", ""),
    }
    output_paths = [path for path in [*artifact_paths.values(), updates["longform_recap_report_path"], updates["longform_recap_context_bundle_path"]] if path]
    return {**updates, "output_paths": output_paths}


def _create_export_package(storage: LocalStorage, data: dict[str, Any]) -> dict[str, Any]:
    content = _content(data)
    outputs = _outputs(content)
    _require(outputs, "final_draft_path", "export_package")
    _require(outputs, "longform_recap_report_path", "export_package")
    draft_file = resolve_path(storage.root, outputs["final_draft_path"])
    draft = storage.read_asset(draft_file)
    project_id = str(data.get("metadata", {}).get("project_id", ""))
    workspace_path = str(data.get("metadata", {}).get("workspace_path", ""))
    chapter = _positive_chapter(content.get("chapter", 1))
    text = str(draft.content.get("text") or draft.content.get("body") or "")
    export_dir = storage.root / "data" / "exports" / "v1"
    export_dir.mkdir(parents=True, exist_ok=True)
    export_file = export_dir / f"{_safe_filename(project_id or 'project')}-chapter-{chapter}.md"
    export_file.write_text(f"# {draft.title or f'Chapter {chapter}'}\n\n{text}\n", encoding="utf-8")
    payload = export_file.read_bytes()
    export_ref = _display_path(storage.root, export_file)
    export_id = make_id("v1_export_package", f"{project_id}-{chapter}-{draft.id}")
    asset = PublishingPlan(
        id=export_id,
        title=f"V1 local export package chapter {chapter}",
        source=draft.id,
        tags=["v1", "single-book-loop", "export", "local"],
        content={
            "plan_id": export_id,
            "project_id": project_id or "local-system",
            "calendar": [],
            "chapter_queue": [
                {
                    "chapter": chapter,
                    "title": draft.title,
                    "draft_id": draft.id,
                    "draft_path": _display_path(storage.root, draft_file),
                    "export_path": export_ref,
                    "status": "ready_for_operator_review",
                }
            ],
            "platform_targets": [{"channel": "local_export", "cadence": "manual", "status": "not_submitted"}],
            "platform_rules": {
                "mode": "local_export_only",
                "publish_side_effects_allowed": False,
                "manual_review_required": True,
            },
            "gate_policy": {
                "v1_contract_export_only": True,
                "require_publish_gate_ready": False,
                "require_canon_longform_update": True,
                "require_review_and_revision": True,
                "rollback_required": True,
            },
            "status": "active",
            "export_package": {
                "format": "markdown",
                "path": export_ref,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size_bytes": len(payload),
                "source_draft_path": _display_path(storage.root, draft_file),
                "longform_recap_report_path": outputs["longform_recap_report_path"],
            },
            "source_isolation": {
                "raw_source_text_allowed": False,
                "source_chunk_raw_text_allowed": False,
                "runtime_assets_in_generation_rag_allowed": False,
                "export_contains_generated_draft_only": True,
            },
            "created_at": utc_now(),
        },
        metadata={"project_id": project_id, "workspace_path": workspace_path, "workflow": "v1-single-book-loop", "channel": "local_export"},
        references=filter_project_safe_references(storage, project_id, [draft.id, _display_path(storage.root, draft_file), outputs["longform_recap_report_path"], export_ref]),
    )
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("; ".join(errors))
    package_path = storage.write_asset("publishing", asset)
    package_ref = _display_path(storage.root, package_path)
    return {"export_package_path": package_ref, "export_markdown_path": export_ref, "output_paths": [package_ref, export_ref]}


def _create_next_chapter_plan(storage: LocalStorage, data: dict[str, Any]) -> dict[str, Any]:
    content = _content(data)
    outputs = _outputs(content)
    _require(outputs, "final_draft_path", "next_chapter_plan")
    _require(outputs, "export_package_path", "next_chapter_plan")
    _require(outputs, "outline_path", "next_chapter_plan")
    final = storage.read_asset(resolve_path(storage.root, outputs["final_draft_path"]))
    current_plan = storage.read_asset(resolve_path(storage.root, outputs["chapter_plan_path"]))
    project_id = str(data.get("metadata", {}).get("project_id", ""))
    workspace_path = str(data.get("metadata", {}).get("workspace_path", ""))
    next_chapter = _positive_chapter(content.get("chapter", 1)) + 1
    final_text = str(final.content.get("text", ""))
    next_path = generate_chapter_plan_service(
        storage,
        outputs["outline_path"],
        workspace_path=workspace_path,
        chapter=next_chapter,
        carry_forward={
            "previous_chapter": content.get("chapter", 1),
            "previous_plan_id": current_plan.id,
            "previous_plan_path": outputs["chapter_plan_path"],
            "previous_draft_id": final.id,
            "previous_draft_path": outputs["final_draft_path"],
            "previous_hook": _last_sentence(final_text),
            "suggested_next_hook": _next_hook(final_text),
            "previous_word_budget": current_plan.content.get("word_budget", {"target": 2500, "min": 1800, "max": 3200}),
        },
    )
    _ensure_project_metadata(storage, next_path, project_id, workspace_path)
    next_ref = _display_path(storage.root, next_path)
    version = create_chapter_plan_version(storage, next_path, change_summary="chapter production next-chapter seed", status="draft")
    return {"next_chapter_plan_path": next_ref, "next_chapter_plan_version_path": version["path"]}


V1_SEQUENCE_REQUIRED_OUTPUTS = [
    "chapter_plan_path",
    "context_bundle_path",
    "draft_v0_path",
    "review_path",
    "revision_plan_path",
    "final_draft_path",
    "chapter_state_path",
    "fact_ledger_path",
    "character_state_ledger_path",
    "foreshadowing_graph_path",
    "reward_ledger_path",
    "review_score_system_report_path",
    "canon_state_machine_ledger_path",
    "canon_state_machine_snapshot_path",
    "canon_state_machine_diff_report_path",
    "longform_recap_report_path",
    "export_package_path",
    "export_markdown_path",
    "next_chapter_plan_path",
]


def _v1_run_coverage(run: dict[str, Any]) -> dict[str, Any]:
    outputs = run.get("outputs", {}) if isinstance(run.get("outputs", {}), dict) else {}
    missing = [key for key in V1_SEQUENCE_REQUIRED_OUTPUTS if not str(outputs.get(key, "")).strip()]
    return {
        "status": "passed" if not missing else "failed",
        "observed": len(V1_SEQUENCE_REQUIRED_OUTPUTS) - len(missing),
        "expected": len(V1_SEQUENCE_REQUIRED_OUTPUTS),
        "missing_outputs": missing,
    }


def _v1_sequence_outputs(run: dict[str, Any]) -> dict[str, str]:
    outputs = run.get("outputs", {}) if isinstance(run.get("outputs", {}), dict) else {}
    return {key: str(outputs.get(key, "") or "") for key in V1_SEQUENCE_REQUIRED_OUTPUTS}


def _write_sequence_acceptance_report(
    storage: LocalStorage,
    *,
    project_id: str,
    workspace_path: str,
    outline_path: str,
    requested_chapter_count: int,
    completed_chapters: int,
    runs: list[dict[str, Any]],
    failures: list[dict[str, Any]],
    started_at: str = "",
    finished_at: str = "",
    duration_seconds: float = 0.0,
    asset_counts_before: dict[str, int] | None = None,
    asset_counts_after: dict[str, int] | None = None,
    runtime_artifact_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    checks = _v1_sequence_checks(requested_chapter_count=requested_chapter_count, completed_chapters=completed_chapters, runs=runs, failures=failures)
    recommendation = "pass" if completed_chapters == requested_chapter_count and not failures and all(item["status"] == "passed" for item in checks) else "block"
    output_counts = _v1_output_counts(runs)
    count_before = asset_counts_before or {}
    count_after = asset_counts_after or {}
    count_delta = _asset_count_delta(count_before, count_after)
    normalized_runtime_policy = _runtime_artifact_policy_from_control(runtime_artifact_policy or {})
    report_id = make_id("long_chain_acceptance", f"v1-sequence-{project_id}-{requested_chapter_count}-{utc_now()}")
    asset = LongChainAcceptanceReport(
        id=report_id,
        title=f"V1 single-book sequence acceptance {completed_chapters}/{requested_chapter_count} chapters",
        tags=["acceptance", "v1-single-book-loop", f"chapters-{requested_chapter_count}", recommendation],
        content={
            "run_id": report_id,
            "project_id": project_id,
            "chapter_count": requested_chapter_count,
            "completed_chapters": completed_chapters,
            "checks": checks,
            "quality_trends": {
                "mode": "artifact_coverage",
                "chapter_run_count": len(runs),
                "completed_chapters": completed_chapters,
                "quality_record_count": output_counts.get("review_score_system_report_path", 0),
                "trend": "sufficient_v1_coverage" if completed_chapters == requested_chapter_count else "incomplete",
            },
            "canon_conflicts": [
                {
                    "chapter": item.get("chapter", ""),
                    "severity": "high",
                    "message": item.get("error") or f"coverage failed: {item.get('coverage', {}).get('missing_outputs', [])}",
                    "run_path": item.get("run_path", ""),
                }
                for item in failures
            ],
            "publish_gate_summary": {
                "ready": 0,
                "needs_revision": 0,
                "blocked": 0 if not failures else len(failures),
                "local_export_ready": output_counts.get("export_package_path", 0),
            },
            "acceptance_mode": "v1_single_book_sequence",
            "outline_path": outline_path,
            "workspace_path": workspace_path,
            "output_counts": output_counts,
            "runtime_summary": {
                "started_at": started_at,
                "finished_at": finished_at,
                "duration_seconds": round(float(duration_seconds or 0.0), 3),
                "average_chapter_seconds": round(float(duration_seconds or 0.0) / completed_chapters, 3) if completed_chapters else 0.0,
                "asset_counts_before": count_before,
                "asset_counts_after": count_after,
                "asset_count_delta": count_delta,
                "total_asset_delta": sum(count_delta.values()),
                "runtime_artifact_policy": normalized_runtime_policy,
                "task_status_mode": normalized_runtime_policy["task_status_mode"],
            },
            "runs": runs,
            "failures": failures,
            "recommendation": recommendation,
            "created_at": utc_now(),
        },
        metadata={"project_id": project_id, "workspace_path": workspace_path, "workflow": "v1-single-book-sequence", "risk_level": "low" if recommendation == "pass" else "high"},
        references=filter_project_safe_references(
            storage,
            project_id,
            _dedupe([outline_path, workspace_path, *[str(item.get("run_path", "")) for item in runs], *[path for item in runs for path in item.get("outputs", {}).values() if str(path).strip()]]),
        ),
    )
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset("runs", asset)
    return {"path": _display_path(storage.root, path), "id": asset.id, "asset": asset.to_dict(), "validation": {"ok": True, "errors": []}}


def _emit_sequence_progress(callback: Callable[[dict[str, Any]], None] | None, event: dict[str, Any]) -> None:
    if not callback:
        return
    callback(event)


def _elapsed_seconds(started: float) -> float:
    return round(max(time.monotonic() - started, 0.0), 3)


def _asset_count_delta(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    keys = sorted({*before.keys(), *after.keys()})
    return {key: int(after.get(key, 0)) - int(before.get(key, 0)) for key in keys}


def _v1_sequence_checks(*, requested_chapter_count: int, completed_chapters: int, runs: list[dict[str, Any]], failures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    checks = [
        {
            "check": "chapter_sequence_completed",
            "status": "passed" if completed_chapters == requested_chapter_count and not failures else "failed",
            "observed": completed_chapters,
            "expected": requested_chapter_count,
        }
    ]
    output_counts = _v1_output_counts(runs)
    for key in V1_SEQUENCE_REQUIRED_OUTPUTS:
        checks.append(
            {
                "check": key,
                "status": "passed" if output_counts.get(key, 0) >= requested_chapter_count else "failed",
                "observed": output_counts.get(key, 0),
                "expected": requested_chapter_count,
            }
        )
    return checks


def _v1_output_counts(runs: list[dict[str, Any]]) -> dict[str, int]:
    counts = {key: 0 for key in V1_SEQUENCE_REQUIRED_OUTPUTS}
    for item in runs:
        outputs = item.get("outputs", {}) if isinstance(item.get("outputs", {}), dict) else {}
        for key in V1_SEQUENCE_REQUIRED_OUTPUTS:
            if str(outputs.get(key, "") or "").strip():
                counts[key] += 1
    return counts


def _bounded_chapter_count(value: Any, *, max_chapters: int) -> int:
    try:
        count = int(value)
    except Exception:
        count = 10
    count = max(count, 1)
    limit = max(int(max_chapters or 30), 1)
    if count > limit:
        raise ValueError(f"chapter_count must be <= {limit} for a single local sequence run")
    return count


def _read_run_data(storage: LocalStorage, run_file: Path) -> dict[str, Any]:
    data = storage.read_json(run_file)
    if not isinstance(data, dict) or data.get("type") != "chapter_production_run":
        raise ValueError(f"run_path must point to a chapter_production_run asset: {run_file}")
    data["_path"] = _display_path(storage.root, run_file)
    return data


def _write_run_data(storage: LocalStorage, run_file: Path, data: dict[str, Any]) -> None:
    data = {key: value for key, value in data.items() if key != "_path"}
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    storage.write_json(run_file, data)


def _mark_step(
    storage: LocalStorage,
    run_file: Path,
    data: dict[str, Any],
    step: str,
    status: str,
    *,
    input_paths: list[str | Path] | None = None,
    output_paths: list[str | Path] | None = None,
    error: str = "",
    status_paths: list[Path] | None = None,
) -> None:
    content = _content(data)
    steps = content.setdefault("steps", _initial_steps())
    state = steps.setdefault(step, _initial_step(step))
    now = utc_now()
    if status == "running":
        state["started_at"] = now
        state["attempts"] = int(state.get("attempts", 0)) + 1
    if status in {"completed", "failed"}:
        state["finished_at"] = now
    state["status"] = status
    state["input_paths"] = [_display_path(storage.root, path) for path in input_paths or []]
    state["output_paths"] = [_display_path(storage.root, path) for path in output_paths or []]
    state["error"] = error
    state["task_status_paths"] = [_display_path(storage.root, path) for path in status_paths or []]
    project_id = str(data.get("metadata", {}).get("project_id", ""))
    data["references"] = filter_project_safe_references(
        storage,
        project_id,
        _dedupe([*[str(item) for item in data.get("references", []) if str(item).strip()], *state["input_paths"], *state["output_paths"], *state["task_status_paths"]]),
    )
    content["current_step"] = step
    content["status"] = "failed" if status == "failed" else "running"
    content["updated_at"] = now
    content.setdefault("timeline", []).append(
        {
            "step": step,
            "label": STEP_LABELS.get(step, step),
            "status": status,
            "input_paths": state["input_paths"],
            "output_paths": state["output_paths"],
            "error": error,
            "task_status_paths": state["task_status_paths"],
            "recorded_at": now,
        }
    )
    _write_run_data(storage, run_file, data)


def _mark_run_status(storage: LocalStorage, run_file: Path, data: dict[str, Any], status: str, current_step: str) -> None:
    content = _content(data)
    content["status"] = status
    content["current_step"] = current_step
    content["updated_at"] = utc_now()
    _write_run_data(storage, run_file, data)


def _prepare_control_for_resume(content: dict[str, Any]) -> None:
    control = _control(content)
    if content.get("status") == "paused" or control.get("pause_requested"):
        control["pause_requested"] = False
        control["pause_reason"] = ""
        control["last_resumed_at"] = utc_now()
        content["recovery_instruction"] = ""
        _append_control_event(content, "running", "resume requested")


def _honor_control_requests(storage: LocalStorage, run_file: Path, data: dict[str, Any], step: str) -> dict[str, Any] | None:
    latest = _read_run_data(storage, run_file)
    content = _content(latest)
    control = _control(content)
    run_id = str(content.get("run_id", ""))
    if control.get("cancel_requested") or content.get("status") == "cancelled":
        now = utc_now()
        control["cancel_requested"] = True
        control["cancelled_at"] = control.get("cancelled_at") or now
        content["status"] = "cancelled"
        content["current_step"] = step
        content["updated_at"] = now
        content["recovery_instruction"] = str(control.get("cancel_reason") or "chapter production run cancelled")
        _append_control_event(content, "cancelled", content["recovery_instruction"])
        _write_run_data(storage, run_file, latest)
        _write_task_status(storage, run_id, f"chapter-production:{step}", "cancelled", error_message=content["recovery_instruction"])
        return chapter_production_run_detail(storage, run_file)
    if control.get("pause_requested") or content.get("status") == "paused":
        now = utc_now()
        control["pause_requested"] = True
        control["paused_at"] = control.get("paused_at") or now
        content["status"] = "paused"
        content["current_step"] = step
        content["updated_at"] = now
        content["recovery_instruction"] = str(control.get("pause_reason") or "chapter production run paused at step boundary")
        _append_control_event(content, "paused", content["recovery_instruction"])
        _write_run_data(storage, run_file, latest)
        _write_task_status(storage, run_id, f"chapter-production:{step}", "paused", error_message=content["recovery_instruction"])
        return chapter_production_run_detail(storage, run_file)
    return None


def _control(content: dict[str, Any]) -> dict[str, Any]:
    control = content.get("control")
    if not isinstance(control, dict):
        control = {}
        content["control"] = control
    defaults = {
        "execution_mode": "sync",
        "task_status_mode": "full",
        "runtime_artifact_policy": _runtime_artifact_policy(task_status_mode="full"),
        "celery_task_id": "",
        "pause_requested": False,
        "pause_reason": "",
        "pause_requested_at": "",
        "paused_at": "",
        "cancel_requested": False,
        "cancel_reason": "",
        "cancel_requested_at": "",
        "cancelled_at": "",
        "last_resumed_at": "",
    }
    for key, value in defaults.items():
        control.setdefault(key, value)
    control["runtime_artifact_policy"] = _runtime_artifact_policy_from_control(control)
    control["task_status_mode"] = control["runtime_artifact_policy"]["task_status_mode"]
    return control


def _append_control_event(content: dict[str, Any], status: str, message: str) -> None:
    event = {
        "step": content.get("current_step", ""),
        "label": STEP_LABELS.get(str(content.get("current_step", "")), str(content.get("current_step", ""))),
        "status": status,
        "input_paths": [],
        "output_paths": [],
        "error": message,
        "task_status_paths": [],
        "recorded_at": utc_now(),
        "control_event": True,
    }
    timeline = content.setdefault("timeline", [])
    if isinstance(timeline, list):
        if timeline and timeline[-1].get("status") == status and timeline[-1].get("control_event"):
            timeline[-1] = event
        else:
            timeline.append(event)


def _failed_step(content: dict[str, Any]) -> str:
    steps = content.get("steps", {}) if isinstance(content.get("steps", {}), dict) else {}
    for step in CHAPTER_PRODUCTION_STEPS:
        state = steps.get(step, {}) if isinstance(steps.get(step, {}), dict) else {}
        if state.get("status") == "failed":
            return step
    return ""


def _initial_steps() -> dict[str, dict[str, Any]]:
    return {step: _initial_step(step) for step in CHAPTER_PRODUCTION_STEPS}


def _initial_step(step: str) -> dict[str, Any]:
    return {"label": STEP_LABELS.get(step, step), "status": "planned", "attempts": 0, "input_paths": [], "output_paths": [], "error": "", "started_at": "", "finished_at": "", "task_status_paths": []}


def _next_step_index(content: dict[str, Any]) -> int:
    steps = content.get("steps", {}) if isinstance(content.get("steps", {}), dict) else {}
    for index, step in enumerate(CHAPTER_PRODUCTION_STEPS):
        state = steps.get(step, {}) if isinstance(steps.get(step, {}), dict) else {}
        if state.get("status") != "completed":
            return index
    return len(CHAPTER_PRODUCTION_STEPS)


def _step_index(step: str | None) -> int:
    if not step:
        return 0
    _validate_step(step)
    return CHAPTER_PRODUCTION_STEPS.index(step)


def _validate_step(step: str) -> None:
    if step not in CHAPTER_PRODUCTION_STEPS:
        raise ValueError(f"step must be one of: {', '.join(CHAPTER_PRODUCTION_STEPS)}")


def _content(data: dict[str, Any]) -> dict[str, Any]:
    content = data.get("content", {})
    if not isinstance(content, dict):
        raise ValueError("chapter_production_run content must be an object")
    return content


def _outputs(content: dict[str, Any]) -> dict[str, str]:
    outputs = content.get("outputs", {})
    if not isinstance(outputs, dict):
        outputs = {}
        content["outputs"] = outputs
    return {str(key): str(value or "") for key, value in outputs.items()}


def _step_state(content: dict[str, Any], step: str) -> dict[str, Any]:
    steps = content.get("steps", {}) if isinstance(content.get("steps", {}), dict) else {}
    state = steps.get(step, {}) if isinstance(steps.get(step, {}), dict) else {}
    return state


def _step_inputs(content: dict[str, Any], step: str) -> list[str]:
    outputs = _outputs(content)
    mapping = {
        "outline_checkpoint": ["outline_path"],
        "chapter_plan": ["outline_path", "chapter_plan_path"],
        "stability_preflight": ["chapter_plan_path"],
        "context_bundle": ["chapter_plan_path", "stability_preflight_path"],
        "draft_v0": ["chapter_plan_path", "stability_preflight_path", "context_bundle_path"],
        "review": ["draft_v0_path"],
        "revision_plan": ["review_path"],
        "final_draft": ["draft_v0_path", "review_path", "revision_plan_path"],
        "canon_longform_update": ["final_draft_path"],
        "export_package": ["final_draft_path", "longform_recap_report_path"],
        "next_chapter_plan": ["final_draft_path", "outline_path", "export_package_path"],
    }
    return [outputs[key] for key in mapping.get(step, []) if outputs.get(key)]


def _step_result(main_path: str | Path, output_paths: list[str | Path], updates: dict[str, Any]) -> dict[str, Any]:
    return {"main_path": str(main_path), "output_paths": [str(path) for path in output_paths], "updates": {key: str(value or "") for key, value in updates.items() if key != "output_paths"}}


def _run_row(storage: LocalStorage, path: Path, data: dict[str, Any]) -> dict[str, Any]:
    content = _content(data)
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    control = _control(content)
    steps = _step_rows(data)
    return {
        "path": _display_path(storage.root, path),
        "id": data.get("id", ""),
        "run_id": content.get("run_id", ""),
        "type": data.get("type", ""),
        "title": data.get("title", ""),
        "project_id": metadata.get("project_id", ""),
        "workspace_path": metadata.get("workspace_path", ""),
        "chapter": content.get("chapter", ""),
        "status": content.get("status", ""),
        "current_step": content.get("current_step", ""),
        "execution_mode": control.get("execution_mode", "sync"),
        "celery_task_id": control.get("celery_task_id", metadata.get("celery_task_id", "")),
        "pause_requested": bool(control.get("pause_requested")),
        "cancel_requested": bool(control.get("cancel_requested")),
        "completed_steps": sum(1 for step in steps if step.get("status") == "completed"),
        "total_steps": len(CHAPTER_PRODUCTION_STEPS),
        "stability_preflight_path": _outputs(content).get("stability_preflight_path", ""),
        "final_draft_path": _outputs(content).get("final_draft_path", ""),
        "final_forward_patch_path": _outputs(content).get("final_forward_patch_path", ""),
        "final_rollback_patch_path": _outputs(content).get("final_rollback_patch_path", ""),
        "longform_recap_report_path": _outputs(content).get("longform_recap_report_path", ""),
        "export_package_path": _outputs(content).get("export_package_path", ""),
        "export_markdown_path": _outputs(content).get("export_markdown_path", ""),
        "next_chapter_plan_path": _outputs(content).get("next_chapter_plan_path", ""),
        "updated_at": data.get("updated_at", ""),
        "summary": content.get("recovery_instruction") or f"{content.get('current_step', '')} / {content.get('status', '')}",
    }


def _step_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    content = _content(data)
    steps = content.get("steps", {}) if isinstance(content.get("steps", {}), dict) else {}
    rows: list[dict[str, Any]] = []
    for step in CHAPTER_PRODUCTION_STEPS:
        state = steps.get(step, {}) if isinstance(steps.get(step, {}), dict) else {}
        rows.append({"step": step, **_initial_step(step), **state})
    return rows


def _require(outputs: dict[str, str], key: str, step: str) -> None:
    if not outputs.get(key):
        raise ValueError(f"{step} requires {key}")


def _chapter_from_plan(storage: LocalStorage, plan_path: str) -> int:
    if not plan_path:
        return 0
    try:
        plan = storage.read_asset(resolve_path(storage.root, plan_path))
    except Exception:
        return 0
    return _positive_chapter(plan.content.get("chapter", 1))


def _positive_chapter(value: Any) -> int:
    try:
        number = int(value)
    except Exception:
        number = 1
    return max(number, 1)


def _context_query(storage: LocalStorage, chapter_plan_path: str) -> str:
    plan = storage.read_asset(resolve_path(storage.root, chapter_plan_path))
    return f"chapter {plan.content.get('chapter', '')} {plan.content.get('objective', '')} {plan.content.get('hook', '')} character world continuity knowledge material"


def _next_hook(text: str) -> str:
    last = _last_sentence(text)
    if not last:
        return "the previous chapter's unresolved signal returns with a higher cost"
    return f"{last[:80]} 的后果在下一章被迫兑现"


def _last_sentence(text: str) -> str:
    normalized = str(text or "").strip().replace("\n", " ")
    if not normalized:
        return ""
    for sep in ["。", "！", "？", ".", "!", "?"]:
        if sep in normalized:
            parts = [part.strip() for part in normalized.split(sep) if part.strip()]
            if parts:
                return parts[-1] + sep
    return normalized[-80:]


def _safe_filename(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip()).strip("-._")
    return normalized[:80] or "chapter"


def _ensure_project_metadata(storage: LocalStorage, path: str | Path, project_id: str, workspace_path: str) -> None:
    asset_file = resolve_path(storage.root, path)
    data = storage.read_json(asset_file)
    if not isinstance(data, dict):
        return
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    metadata["project_id"] = project_id
    metadata["workspace_path"] = workspace_path
    data["metadata"] = metadata
    refs = data.get("references", []) if isinstance(data.get("references", []), list) else []
    data["references"] = filter_project_safe_references(storage, project_id, [*refs, workspace_path])
    storage.write_json(asset_file, data)


def _update_workspace_best_effort(storage: LocalStorage, workspace_path: str, asset_path: str | Path, chapter: int, status: str) -> None:
    if not workspace_path:
        return
    try:
        update_workspace(storage, str(asset_path), workspace_path, chapter=chapter, status=status)
    except Exception:
        return


def _execute_task(
    storage: LocalStorage,
    run_id: str,
    step: str,
    input_paths: list[str | Path],
    action: Any,
    status_paths: list[Path],
    *,
    task_status_mode: str = "full",
) -> Path:
    task_status_mode = _task_status_mode(task_status_mode)
    if task_status_mode == "full":
        status_paths.append(_write_task_status(storage, run_id, step, "pending", input_paths=input_paths))
    started_at = utc_now()
    if task_status_mode == "full":
        status_paths.append(_write_task_status(storage, run_id, step, "running", input_paths=input_paths))
    try:
        result = action()
    except Exception as exc:
        error_message = f"{type(exc).__name__}: {exc}"
        status_paths.append(_write_task_status(storage, run_id, step, "failed", input_paths=input_paths, error_message=error_message))
        record_node_run(
            storage,
            run_id=run_id,
            node_id=step,
            node_type="chapter_production_step",
            operation=step,
            status="failed",
            input_assets=input_paths,
            output_assets=[],
            processor={"kind": "chapter_production_bus", "name": step},
            started_at=started_at,
            finished_at=utc_now(),
            error=error_message,
            quality_gate={"required": True, "status": "failed"},
        )
        raise
    output_paths = [result]
    record_node_run(
        storage,
        run_id=run_id,
        node_id=step,
        node_type="chapter_production_step",
        operation=step,
        status="succeeded",
        input_assets=input_paths,
        output_assets=output_paths,
        processor={"kind": "chapter_production_bus", "name": step},
        started_at=started_at,
        finished_at=utc_now(),
        quality_gate={"required": True, "status": "passed"},
    )
    status_paths.append(_write_task_status(storage, run_id, step, "completed", input_paths=input_paths, output_paths=output_paths))
    return result


def _task_status_mode(value: Any) -> str:
    normalized = str(value or "full").strip().lower()
    if normalized == "summary":
        normalized = "compact"
    return normalized if normalized in TASK_STATUS_MODES else "full"


def _runtime_artifact_policy(*, task_status_mode: Any = "full") -> dict[str, Any]:
    mode = _task_status_mode(task_status_mode)
    return {
        "policy_version": "chapter-production-runtime-artifact-policy-v1",
        "task_status_mode": mode,
        "task_status_recording": {
            "pending": mode == "full",
            "running": mode == "full",
            "completed": True,
            "failed": True,
            "paused": True,
            "cancelled": True,
        },
        "node_run_mode": "full",
        "trace_mode": "full",
        "reason": "compact mode is only for batch chapter sequence runs; it preserves terminal task evidence while avoiding repeated pending/running status assets.",
    }


def _runtime_artifact_policy_from_control(control: dict[str, Any]) -> dict[str, Any]:
    policy = control.get("runtime_artifact_policy", {}) if isinstance(control.get("runtime_artifact_policy", {}), dict) else {}
    return _runtime_artifact_policy(task_status_mode=policy.get("task_status_mode") or control.get("task_status_mode", "full"))


def _write_task_status(
    storage: LocalStorage,
    run_id: str,
    step: str,
    status: str,
    *,
    input_paths: list[str | Path] | None = None,
    output_paths: list[str | Path] | None = None,
    error_message: str = "",
) -> Path:
    input_values = [_display_path(storage.root, path) for path in input_paths or []]
    output_values = [_display_path(storage.root, path) for path in output_paths or []]
    asset = TaskStatus(
        title=f"{step} {status}",
        source=run_id,
        tags=["task-status", "chapter-production", step, status],
        content={
            "run_id": run_id,
            "step": step,
            "status": status,
            "input_paths": input_values,
            "output_paths": output_values,
            "error_message": error_message,
        },
        metadata={"recorded_at": utc_now(), "task_type": "chapter_production"},
        references=[run_id, *input_values, *output_values],
    )
    return storage.write_asset("runs", asset)


def _build_run_log(storage: LocalStorage, status_paths: list[Path]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path in status_paths:
        try:
            asset = storage.read_asset(path)
        except Exception:
            continue
        if asset.type != "task_status":
            continue
        entries.append(
            {
                "step": asset.content.get("step", ""),
                "status": asset.content.get("status", ""),
                "input_paths": asset.content.get("input_paths", []),
                "output_paths": asset.content.get("output_paths", []),
                "error_message": asset.content.get("error_message", ""),
                "recorded_at": asset.metadata.get("recorded_at", ""),
                "status_asset": _display_path(storage.root, path),
            }
        )
    return entries


def _build_recovery_instruction(run_log: list[dict[str, Any]], error_message: str) -> str:
    failed = next((entry for entry in reversed(run_log) if entry.get("status") == "failed"), {})
    step = failed.get("step") or "unknown"
    inputs = failed.get("input_paths") or []
    input_text = ", ".join(inputs) if inputs else "the failed step input"
    return (
        f"Recover by inspecting step '{step}' and input {input_text}. "
        f"Fix the input asset or provider configuration, then resume the chapter production run from this step. "
        f"Original error: {error_message}"
    )


def _display_path(root: Path, path: str | Path) -> str:
    resolved = Path(path)
    if not resolved.is_absolute():
        return str(resolved)
    try:
        return str(resolved.relative_to(root))
    except ValueError:
        return str(resolved)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result

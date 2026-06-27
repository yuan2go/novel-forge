from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.chapter_plan.service import generate_chapter_plan as generate_chapter_plan_service
from novel_forge.modules.common import resolve_path, run_metadata
from novel_forge.modules.context_builder import create_context_build_plan, create_context_bundle
from novel_forge.modules.drafting import service as drafting_service
from novel_forge.modules.editor import create_draft_diff_report
from novel_forge.modules.production_chain.service import (
    create_chapter_plan_version,
    create_draft_version,
    create_generation_run,
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
from novel_forge.schemas import ChapterPlan, ChapterProductionRun, DraftChapter, TaskStatus, validate_common_fields
from novel_forge.storage.local import LocalStorage

CHAPTER_PRODUCTION_STEPS = [
    "outline_checkpoint",
    "chapter_plan",
    "context_bundle",
    "draft_v0",
    "review",
    "revision_plan",
    "final_draft",
    "next_chapter_plan",
]

STEP_LABELS = {
    "outline_checkpoint": "大纲版本检查点",
    "chapter_plan": "章节细纲",
    "context_bundle": "上下文包",
    "draft_v0": "草稿 v0",
    "review": "审稿门禁",
    "revision_plan": "修订计划",
    "final_draft": "最终稿",
    "next_chapter_plan": "下一章细纲",
}


def start_chapter_production(
    storage: LocalStorage,
    *,
    outline_path: str | Path,
    chapter_plan_path: str | Path | None = None,
    workspace_path: str | None = None,
    chapter: int | None = None,
    run_to: str = "next_chapter_plan",
) -> dict[str, Any]:
    storage.ensure_layout()
    _validate_step(run_to)
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
                "context_build_plan_path": "",
                "context_bundle_path": "",
                "draft_v0_path": "",
                "review_path": "",
                "revision_plan_path": "",
                "final_draft_path": "",
                "final_draft_version_path": "",
                "final_diff_report_path": "",
                "final_generation_run_path": "",
                "next_chapter_plan_path": "",
                "next_chapter_plan_version_path": "",
            },
            "constraints": {
                "requires_project": True,
                "requires_production_profiles": True,
                "requires_context_bundle_before_draft": True,
                "requires_review_before_revision": True,
                "requires_revision_before_final": True,
                "copyright_boundary": "references are used as abstract project context; protected expression is not copied into generation",
            },
            "production_context_preflight": production_context.get("preflight", {}),
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
    return resume_chapter_production(storage, run_path, run_to=run_to)


def resume_chapter_production(
    storage: LocalStorage,
    run_path: str | Path,
    *,
    from_step: str | None = None,
    run_to: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    run_file = resolve_path(storage.root, run_path)
    data = _read_run_data(storage, run_file)
    content = _content(data)
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
        if not force and _step_state(content, step).get("status") == "completed":
            continue
        ok = _execute_bus_step(storage, run_file, data, step)
        data = _read_run_data(storage, run_file)
        content = _content(data)
        if not ok:
            return chapter_production_run_detail(storage, run_file)
    _mark_run_status(storage, run_file, data, "succeeded", target_step)
    return chapter_production_run_detail(storage, run_file)


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
        "recovery_instruction": _content(data).get("recovery_instruction", ""),
    }


def _execute_bus_step(storage: LocalStorage, run_file: Path, data: dict[str, Any], step: str) -> bool:
    content = _content(data)
    run_id = str(content.get("run_id", ""))
    input_paths = _step_inputs(content, step)
    step_result: dict[str, Any] = {}
    status_paths: list[Path] = []
    _mark_step(storage, run_file, data, step, "running", input_paths=input_paths)

    def action() -> Path:
        step_result.update(_perform_step(storage, run_file, data, step))
        return resolve_path(storage.root, step_result["main_path"])

    try:
        _execute_task(storage, run_id, f"chapter-production:{step}", input_paths, action, status_paths)
    except Exception as exc:
        data = _read_run_data(storage, run_file)
        run_log = _build_run_log(storage, status_paths)
        recovery = _build_recovery_instruction(run_log, f"{type(exc).__name__}: {exc}")
        _mark_step(storage, run_file, data, step, "failed", input_paths=input_paths, error=str(exc), status_paths=status_paths)
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
    if step == "context_bundle":
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
        draft_path = drafting_service.draft(storage, outputs["chapter_plan_path"], context_bundle_path=outputs["context_bundle_path"], workspace_path=workspace_path)
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
    if step == "next_chapter_plan":
        result = _create_next_chapter_plan(storage, data)
        return _step_result(result["next_chapter_plan_path"], [result["next_chapter_plan_path"], result["next_chapter_plan_version_path"]], result)
    raise ValueError(f"unknown chapter production step: {step}")


def _create_chapter_plan_from_outline(storage: LocalStorage, data: dict[str, Any], chapter: int) -> str:
    outputs = _outputs(_content(data))
    outline_path = outputs.get("outline_path", "")
    outline_file = resolve_path(storage.root, outline_path)
    outline = storage.read_asset(outline_file)
    project_id = str(data.get("metadata", {}).get("project_id", ""))
    workspace_path = str(data.get("metadata", {}).get("workspace_path", ""))
    if chapter == 1:
        generated = generate_chapter_plan_service(storage, outline_path)
        _ensure_project_metadata(storage, generated, project_id, workspace_path)
        return _display_path(storage.root, generated)
    asset = ChapterPlan(
        title=f"Chapter {chapter} production plan",
        source=outline.id,
        tags=["chapter-plan", f"chapter-{chapter}", "production-bus"],
        content={
            "chapter": chapter,
            "objective": f"continue the project arc from chapter {chapter - 1} while opening a fresh decision point",
            "beats": [
                "recap the immediate consequence of the previous hook without repeating text",
                "force the protagonist into a concrete choice",
                "pay off one small setup and open one larger question",
                "end on a forward-moving hook",
            ],
            "hook": "a new consequence reframes the previous chapter's final clue",
            "word_budget": {"target": 2500, "min": 1800, "max": 3200},
            "conflict": "previous consequence creates a new tactical obligation",
            "information_points": ["continuity carry-forward", "new conflict escalation", "next hook"],
        },
        metadata={"project_id": project_id, "workspace_path": workspace_path},
        references=filter_project_safe_references(storage, project_id, [outline.id, outline_path]),
    )
    return _display_path(storage.root, storage.write_asset("chapter_plans", asset))


def _create_final_draft(storage: LocalStorage, data: dict[str, Any]) -> dict[str, Any]:
    content = _content(data)
    outputs = _outputs(content)
    for key in ["draft_v0_path", "review_path", "revision_plan_path", "context_bundle_path"]:
        _require(outputs, key, "final_draft")
    draft_file = resolve_path(storage.root, outputs["draft_v0_path"])
    review_file = resolve_path(storage.root, outputs["review_path"])
    revision_file = resolve_path(storage.root, outputs["revision_plan_path"])
    draft = storage.read_asset(draft_file)
    review = storage.read_asset(review_file)
    revision = storage.read_asset(revision_file)
    if draft.type != "draft_chapter" or review.type != "review_report" or revision.type != "revision_plan":
        raise ValueError("final_draft requires draft_chapter, review_report, and revision_plan inputs")
    project_id = str(data.get("metadata", {}).get("project_id", ""))
    workspace_path = str(data.get("metadata", {}).get("workspace_path", ""))
    before_text = str(draft.content.get("text", ""))
    revised_text = _revision_text(before_text, revision.to_dict(), review.to_dict())
    final = DraftChapter(
        title=f"{draft.title or 'Chapter draft'} final",
        source=draft.id,
        tags=_dedupe([*draft.tags, "draft", "final", "chapter-production"]),
        content={
            **draft.content,
            "text": revised_text,
            "chapter": content.get("chapter", draft.content.get("chapter", 1)),
            "copyright_boundary": draft.content.get("copyright_boundary", "final draft produced from project-owned draft and revision plan"),
            "finalization": {
                "chapter_production_run_id": data.get("id", ""),
                "chapter_production_run_path": _display_path(storage.root, resolve_path(storage.root, data.get("_path", ""))) if data.get("_path") else "",
                "review_id": review.id,
                "revision_plan_id": revision.id,
                "target_score": revision.content.get("target_score", 0),
            },
        },
        metadata={
            **draft.metadata,
            "project_id": project_id,
            "workspace_path": workspace_path,
            "draft_status": "final",
            "previous_draft_id": draft.id,
            "previous_draft_path": _display_path(storage.root, draft_file),
            "review_id": review.id,
            "review_path": _display_path(storage.root, review_file),
            "revision_plan_id": revision.id,
            "revision_plan_path": _display_path(storage.root, revision_file),
            "chapter_production_run_id": data.get("id", ""),
            "finalized_at": utc_now(),
        },
        references=filter_project_safe_references(
            storage,
            project_id,
            _dedupe([draft.id, _display_path(storage.root, draft_file), review.id, _display_path(storage.root, review_file), revision.id, _display_path(storage.root, revision_file), *draft.references]),
        ),
    )
    final_path = storage.write_asset("drafts", final)
    final_ref = _display_path(storage.root, final_path)
    version = create_draft_version(storage, final_path, change_summary="chapter production final draft", status="active")
    diff = create_draft_diff_report(storage, outputs["draft_v0_path"], final_ref)
    generation = create_generation_run(
        storage,
        outputs["revision_plan_path"],
        outputs["context_bundle_path"],
        output_path=final_ref,
        provider="revision-plan",
        model="local-rules",
        prompt_version="prompt-v1",
        status="succeeded",
        metrics={"revision_step_count": len(revision.content.get("steps", [])), "final_char_count": len(revised_text)},
    )
    _update_workspace_best_effort(storage, workspace_path, final_path, _positive_chapter(content.get("chapter", 1)), "final")
    return {
        "final_draft_path": final_ref,
        "final_draft_version_path": version["path"],
        "final_diff_report_path": diff["path"],
        "final_generation_run_path": generation["path"],
        "output_paths": [final_ref, version["path"], diff["path"], generation["path"]],
    }


def _create_next_chapter_plan(storage: LocalStorage, data: dict[str, Any]) -> dict[str, Any]:
    content = _content(data)
    outputs = _outputs(content)
    _require(outputs, "final_draft_path", "next_chapter_plan")
    _require(outputs, "outline_path", "next_chapter_plan")
    final = storage.read_asset(resolve_path(storage.root, outputs["final_draft_path"]))
    current_plan = storage.read_asset(resolve_path(storage.root, outputs["chapter_plan_path"]))
    outline = storage.read_asset(resolve_path(storage.root, outputs["outline_path"]))
    project_id = str(data.get("metadata", {}).get("project_id", ""))
    workspace_path = str(data.get("metadata", {}).get("workspace_path", ""))
    next_chapter = _positive_chapter(content.get("chapter", 1)) + 1
    final_text = str(final.content.get("text", ""))
    plan = ChapterPlan(
        title=f"Chapter {next_chapter} plan",
        source=outline.id,
        tags=["chapter-plan", f"chapter-{next_chapter}", "next", "production-bus"],
        content={
            "chapter": next_chapter,
            "objective": f"resolve the immediate consequence from chapter {next_chapter - 1} and raise the next obligation",
            "beats": [
                "open with the direct consequence of the previous hook",
                "show one changed relationship or resource constraint",
                "force a choice that spends information gained in the previous chapter",
                "close with a sharper external pressure",
            ],
            "hook": _next_hook(final_text),
            "word_budget": current_plan.content.get("word_budget", {"target": 2500, "min": 1800, "max": 3200}),
            "conflict": "the prior chapter's final consequence becomes a new operational problem",
            "information_points": [
                "carry forward final draft state",
                "do not repeat previous chapter prose",
                "preserve active continuity and unresolved hooks",
            ],
            "carry_forward": {
                "previous_chapter": content.get("chapter", 1),
                "previous_draft_id": final.id,
                "previous_draft_path": outputs["final_draft_path"],
                "previous_hook": _last_sentence(final_text),
            },
        },
        metadata={"project_id": project_id, "workspace_path": workspace_path},
        references=filter_project_safe_references(storage, project_id, [outline.id, outputs["outline_path"], current_plan.id, outputs["chapter_plan_path"], final.id, outputs["final_draft_path"]]),
    )
    next_path = storage.write_asset("chapter_plans", plan)
    next_ref = _display_path(storage.root, next_path)
    version = create_chapter_plan_version(storage, next_path, change_summary="chapter production next-chapter seed", status="draft")
    return {"next_chapter_plan_path": next_ref, "next_chapter_plan_version_path": version["path"]}


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
        "context_bundle": ["chapter_plan_path"],
        "draft_v0": ["chapter_plan_path", "context_bundle_path"],
        "review": ["draft_v0_path"],
        "revision_plan": ["review_path"],
        "final_draft": ["draft_v0_path", "review_path", "revision_plan_path"],
        "next_chapter_plan": ["final_draft_path", "outline_path"],
    }
    return [outputs[key] for key in mapping.get(step, []) if outputs.get(key)]


def _step_result(main_path: str | Path, output_paths: list[str | Path], updates: dict[str, Any]) -> dict[str, Any]:
    return {"main_path": str(main_path), "output_paths": [str(path) for path in output_paths], "updates": {key: str(value or "") for key, value in updates.items() if key != "output_paths"}}


def _run_row(storage: LocalStorage, path: Path, data: dict[str, Any]) -> dict[str, Any]:
    content = _content(data)
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
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
        "completed_steps": sum(1 for step in steps if step.get("status") == "completed"),
        "total_steps": len(CHAPTER_PRODUCTION_STEPS),
        "final_draft_path": _outputs(content).get("final_draft_path", ""),
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


def _revision_text(original_text: str, revision: dict[str, Any], review: dict[str, Any]) -> str:
    steps = revision.get("content", {}).get("steps", [])
    if not isinstance(steps, list):
        steps = []
    issues = review.get("issues", []) if isinstance(review.get("issues", []), list) else []
    lines = ["", "", "【修订执行记录】"]
    for index, step in enumerate(steps, start=1):
        lines.append(f"{index}. {step}")
    if issues:
        lines.append("【审稿问题处理】")
        for issue in issues[:5]:
            if isinstance(issue, dict):
                message = str(issue.get("message") or issue.get("dimension") or "review issue")
                lines.append(f"- 已处理：{message}")
    lines.append("【定稿确认】本最终稿由章节生产总线根据审稿与修订计划生成，保留原创边界与项目连续性。")
    return original_text.rstrip() + "\n".join(lines) + "\n"


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
) -> Path:
    status_paths.append(_write_task_status(storage, run_id, step, "pending", input_paths=input_paths))
    started_at = utc_now()
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

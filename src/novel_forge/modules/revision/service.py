from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.model_adapters import GuardedModelAdapter, ModelAdapter, model_from_env, validate_model_output
from novel_forge.modules.agent_runs import AgentExecutionContext
from novel_forge.modules.audit import create_publish_gate_report
from novel_forge.modules.common import read_previous, resolve_path
from novel_forge.modules.editor import execute_revision_plan
from novel_forge.modules.production_context import filter_project_safe_references, project_scope_from_asset
from novel_forge.modules.review import service as review_service
from novel_forge.schemas import ContextBundle, RevisionPlan, RevisionTask, validate_common_fields
from novel_forge.storage.local import LocalStorage


def revise(storage: LocalStorage, input_path: str | None = None, model: ModelAdapter | None = None) -> Path:
    model = model or model_from_env("revise")
    review_asset = read_previous(storage, "reviews", input_path)
    review_path = input_path or str(storage.root / "data" / "reviews" / f"{review_asset.id}.json")
    project = project_scope_from_asset(storage, review_asset, input_path=review_path)
    with AgentExecutionContext(
        storage,
        agent_key="review",
        operation="revise",
        input_assets=[review_path],
        output_types=["revision_plan"],
        model_provider=getattr(model, "name", "local"),
        model_name=getattr(model, "name", "local"),
        prompt_version="prompt-v1",
        token_budget=1500,
        sla_seconds=600,
        workspace_path=str(project.get("workspace_path", "")),
    ) as agent_run:
        agent_run.guard("read_asset")
        guarded_model = GuardedModelAdapter(model, storage, agent_run.path)
        result = validate_model_output("revise", guarded_model.revise("", review_asset.to_dict()))
        target_score = result.get("target_score")
        if target_score is None:
            target_score = max(80, int(review_asset.score) + 8 if hasattr(review_asset, "score") else 80)
        agent_run.guard("write_revision_plan", "revision_plan")
        asset = RevisionPlan(
            title=f"Revision plan for {review_asset.title}",
            source=review_asset.id,
            tags=["revision", "plan"],
            content={
                "steps": result["plan"],
                "target_score": target_score,
                "must_preserve": result.get("must_preserve") or ["original premise", "copyright boundary", "chapter hook"],
                "agent_run_path": agent_run.path,
                "model_output": result,
            },
            metadata={
                "model": model.name,
                "provider": result.get("provider", model.name),
                "agent_run_path": agent_run.path,
                "project_id": project.get("project_id", ""),
                "workspace_path": project.get("workspace_path", ""),
            },
            references=filter_project_safe_references(storage, str(project.get("project_id", "")), [review_asset.id]),
        )
        path = storage.write_asset("reviews", asset)
        agent_run.succeed(output_assets=[path], token_used=len(str(result)))
        return path


def create_revision_task(
    storage: LocalStorage,
    review_path: str | Path,
    *,
    draft_path: str | Path | None = None,
    issue_indexes: list[int] | None = None,
    workspace_path: str | None = None,
) -> dict[str, Any]:
    """Promote review issues into a schema-backed revision task."""

    storage.ensure_layout()
    review_file = resolve_path(storage.root, review_path)
    review = storage.read_json(review_file)
    if not isinstance(review, dict) or review.get("type") != "review_report":
        raise ValueError(f"review_path must point to a review_report asset: {review_path}")
    draft_file = resolve_path(storage.root, draft_path) if draft_path else _draft_path_for_review(storage, review)
    draft = storage.read_asset(draft_file)
    project = project_scope_from_asset(storage, draft, input_path=draft_file, workspace_path=workspace_path)
    issues = _selected_review_issues(review, issue_indexes)
    indexes = [int(issue.get("issue_index", issue.get("_source_index", index))) for index, issue in enumerate(issues)]
    now = utc_now()
    task_id = make_id("revision_task", f"{review.get('id', '')}-{draft.id}-{','.join(str(item) for item in indexes)}-{now}")
    content = {
        "task_id": task_id,
        "review_id": review.get("id", ""),
        "review_path": _display_path(storage.root, review_file),
        "source_draft_id": draft.id,
        "source_draft_path": _display_path(storage.root, draft_file),
        "issue_indexes": indexes,
        "review_issue_ids": [str(issue.get("issue_id") or f"{review.get('id', '')}:issue:{index}") for index, issue in enumerate(issues)],
        "issues": issues,
        "status": "open",
        "stage": "revision_task_created",
        "outputs": {},
        "created_at": now,
        "updated_at": now,
    }
    asset = RevisionTask(
        title=f"Revision task for {review.get('title') or review.get('id')}",
        source=str(review.get("id", "")),
        tags=["revision", "task", "review-issue"],
        content=content,
        metadata={
            "project_id": project.get("project_id", ""),
            "workspace_path": project.get("workspace_path", ""),
            "source_review_path": _display_path(storage.root, review_file),
            "source_draft_path": _display_path(storage.root, draft_file),
        },
        references=filter_project_safe_references(
            storage,
            str(project.get("project_id", "")),
            [str(review.get("id", "")), _display_path(storage.root, review_file), draft.id, _display_path(storage.root, draft_file)],
        ),
    )
    path = storage.write_asset("reviews", asset)
    _mark_review_issues(
        storage,
        review_file,
        indexes,
        status="accepted",
        evidence={"revision_task_path": _display_path(storage.root, path), "revision_task_id": task_id},
    )
    return {"path": _display_path(storage.root, path), "id": asset.id, "asset": asset.to_dict()}


def run_review_rework_loop(
    storage: LocalStorage,
    review_path: str | Path,
    *,
    draft_path: str | Path | None = None,
    issue_indexes: list[int] | None = None,
    context_bundle_path: str | Path | None = None,
    workspace_path: str | None = None,
    revision_model: ModelAdapter | None = None,
    editor_model: ModelAdapter | None = None,
    review_model: ModelAdapter | None = None,
    human_override: bool = False,
) -> dict[str, Any]:
    """Run the production review rework loop end to end.

    review_issue -> revision_task -> revision_plan -> editor_patch ->
    draft_version -> re-review -> publish gate
    """

    storage.ensure_layout()
    review_file = resolve_path(storage.root, review_path)
    review_data = storage.read_json(review_file)
    if not isinstance(review_data, dict) or review_data.get("type") != "review_report":
        raise ValueError(f"review_path must point to a review_report asset: {review_path}")
    draft_file = resolve_path(storage.root, draft_path) if draft_path else _draft_path_for_review(storage, review_data)
    draft_asset = storage.read_asset(draft_file)
    draft_metadata = draft_asset.metadata if isinstance(draft_asset.metadata, dict) else {}
    review_metadata = review_data.get("metadata", {}) if isinstance(review_data.get("metadata", {}), dict) else {}
    project = project_scope_from_asset(storage, draft_asset, input_path=draft_file, workspace_path=workspace_path)
    project_id = str(project.get("project_id") or draft_metadata.get("project_id") or review_metadata.get("project_id") or "")
    resolved_workspace_path = str(project.get("workspace_path") or workspace_path or draft_metadata.get("workspace_path") or review_metadata.get("workspace_path") or "")
    from novel_forge.modules.loop_kernel import run_loop

    result = run_loop(
        storage,
        {
            "loop_type": "review_revision_publish",
            "target_path": _display_path(storage.root, draft_file),
            "review_path": _display_path(storage.root, review_file),
            "issue_indexes": issue_indexes or [],
            "context_bundle_path": str(context_bundle_path or ""),
            "workspace_path": resolved_workspace_path,
            "project_id": project_id,
            "revision_model": revision_model,
            "editor_model": editor_model,
            "review_model": review_model,
            "human_override": human_override,
            "bypass_reason": "review rework compatibility facade routed through Loop Kernel",
        },
    )
    outputs = result.get("outputs", {}) if isinstance(result.get("outputs", {}), dict) else {}
    revision_task_path = str(outputs.get("revision_task_path") or "")
    task_status = str(outputs.get("revision_task_status") or "")
    if revision_task_path:
        try:
            task = storage.read_json(resolve_path(storage.root, revision_task_path))
            task_status = task_status or str((task.get("content", {}) if isinstance(task.get("content", {}), dict) else {}).get("status") or "")
        except Exception:
            pass
    status = task_status or ("failed" if result.get("status") == "failed" else str(result.get("status") or "succeeded"))
    return {
        "status": status,
        "revision_task_path": revision_task_path,
        "review_path": _display_path(storage.root, review_file),
        "source_draft_path": _display_path(storage.root, draft_file),
        "revision_plan_path": str(outputs.get("revision_plan_path") or ""),
        "editor_patch_path": str(outputs.get("editor_patch_path") or ""),
        "rollback_patch_path": str(outputs.get("rollback_patch_path") or ""),
        "draft_version_path": str(outputs.get("draft_version_path") or ""),
        "draft_diff_report_path": str(outputs.get("draft_diff_report_path") or ""),
        "generation_run_path": str(outputs.get("generation_run_path") or ""),
        "final_draft_path": str(outputs.get("final_draft_path") or ""),
        "re_review_path": str(outputs.get("re_review_path") or ""),
        "publish_gate_report_path": str(outputs.get("publish_gate_report_path") or ""),
        "publish_decision": str(outputs.get("publish_decision") or ""),
        "loop_run_path": str(result.get("loop_run_path") or outputs.get("loop_run_path") or ""),
        "loop_report_path": str(result.get("loop_report_path") or outputs.get("loop_report_path") or ""),
        "outputs": outputs,
    }


def _selected_review_issues(review: dict[str, Any], issue_indexes: list[int] | None) -> list[dict[str, Any]]:
    issues = review.get("issues", [])
    if not isinstance(issues, list):
        issues = []
    selected: list[dict[str, Any]] = []
    indexes = issue_indexes if issue_indexes is not None else list(range(len(issues)))
    for index in indexes:
        if index < 0 or index >= len(issues) or not isinstance(issues[index], dict):
            raise ValueError(f"review issue index out of range: {index}")
        selected.append({**issues[index], "_source_index": index, "issue_index": int(issues[index].get("issue_index", index))})
    if selected:
        return selected
    suggestions = review.get("revision_suggestions", [])
    return [
        {
            "issue_id": f"{review.get('id', '')}:synthetic-revision-issue",
            "issue_index": 0,
            "_source_index": 0,
            "dimension": "review_rework",
            "severity": "medium",
            "message": "Review requested revision but did not provide structured issues.",
            "recommendation": "; ".join(str(item) for item in suggestions[:3]) if isinstance(suggestions, list) else "revise before publish",
            "status": "open",
        }
    ]


def _draft_path_for_review(storage: LocalStorage, review: dict[str, Any]) -> Path:
    source_id = str(review.get("source", ""))
    for path in storage.list_json("drafts"):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") not in {"draft_chapter", "draft_version"}:
            continue
        if data.get("id") == source_id:
            return path
    for ref in review.get("references", []):
        text = str(ref)
        if text.endswith(".json"):
            path = resolve_path(storage.root, text)
            if path.exists():
                data = storage.read_json(path)
                if isinstance(data, dict) and data.get("type") in {"draft_chapter", "draft_version"}:
                    return path
    raise ValueError("could not resolve source draft for review; pass draft_path explicitly")


def _create_rework_context_bundle(
    storage: LocalStorage,
    *,
    draft_file: Path,
    review_file: Path,
    revision_file: Path,
    task_path: Path,
    workspace_path: str | None,
) -> Path:
    draft = storage.read_asset(draft_file)
    review = storage.read_asset(review_file)
    revision = storage.read_asset(revision_file)
    task = storage.read_asset(task_path)
    project = project_scope_from_asset(storage, draft, input_path=draft_file, workspace_path=workspace_path)
    selected_assets = [
        {"path": _display_path(storage.root, draft_file), "type": draft.type, "role": "source_draft"},
        {"path": _display_path(storage.root, review_file), "type": review.type, "role": "source_review"},
        {"path": _display_path(storage.root, task_path), "type": task.type, "role": "revision_task"},
        {"path": _display_path(storage.root, revision_file), "type": revision.type, "role": "revision_plan"},
    ]
    actual_context = {
        "draft_title": draft.title,
        "review_score": getattr(review, "score", 0),
        "review_issues": task.content.get("issues", []),
        "revision_steps": revision.content.get("steps", []),
        "must_preserve": revision.content.get("must_preserve", []),
        "copyright_boundary": draft.content.get("copyright_boundary", ""),
    }
    asset = ContextBundle(
        title=f"Rework context bundle for {draft.title or draft.id}",
        source=draft.id,
        tags=["context", "revision", "rework-loop"],
        content={
            "build_plan_id": make_id("context_build_plan", f"rework-{task.id}"),
            "target_asset_id": draft.id,
            "selected_assets": selected_assets,
            "compressed_context": actual_context,
            "token_budget": 5000,
            "token_estimate": len(str(actual_context)),
            "actual_context": actual_context,
            "source_asset_ids": [draft.id, review.id, task.id, revision.id],
        },
        metadata={"project_id": project.get("project_id", ""), "workspace_path": project.get("workspace_path", "")},
        references=filter_project_safe_references(storage, str(project.get("project_id", "")), [draft.id, review.id, task.id, revision.id]),
    )
    return storage.write_asset("contexts", asset)


def _link_revision_plan(storage: LocalStorage, revision_path: str | Path, *, task_path: str, issue_indexes: list[int]) -> None:
    path = resolve_path(storage.root, revision_path)
    data = storage.read_json(path)
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    content["revision_task_path"] = task_path
    content["review_issue_indexes"] = issue_indexes
    data["content"] = content
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    metadata["revision_task_path"] = task_path
    metadata["review_issue_indexes"] = issue_indexes
    data["metadata"] = metadata
    data["references"] = _dedupe([*data.get("references", []), task_path])
    data["updated_at"] = utc_now()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    storage.write_json(path, data)


def _link_re_review(storage: LocalStorage, review_path: str | Path, *, task_path: str, source_review_path: str, outputs: dict[str, Any]) -> None:
    path = resolve_path(storage.root, review_path)
    data = storage.read_json(path)
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    metadata["rework_loop"] = {
        "revision_task_path": task_path,
        "source_review_path": source_review_path,
        "editor_patch_path": outputs.get("editor_patch_path", ""),
        "draft_version_path": outputs.get("draft_version_path", ""),
    }
    data["metadata"] = metadata
    data["references"] = _dedupe([*data.get("references", []), task_path, source_review_path])
    data["updated_at"] = utc_now()
    storage.write_json(path, data)


def _link_publish_gate(storage: LocalStorage, publish_gate_path: str | Path, *, task_path: str, source_review_path: str) -> None:
    path = resolve_path(storage.root, publish_gate_path)
    data = storage.read_json(path)
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    metadata["rework_loop"] = {"revision_task_path": task_path, "source_review_path": source_review_path}
    data["metadata"] = metadata
    data["references"] = _dedupe([*data.get("references", []), task_path, source_review_path])
    data["updated_at"] = utc_now()
    storage.write_json(path, data)


def _update_revision_task(
    storage: LocalStorage,
    task_path: str | Path,
    *,
    status: str,
    stage: str,
    outputs: dict[str, Any] | None = None,
    error: str = "",
) -> dict[str, Any]:
    path = resolve_path(storage.root, task_path)
    data = storage.read_json(path)
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    merged_outputs = content.get("outputs", {}) if isinstance(content.get("outputs", {}), dict) else {}
    if outputs:
        merged_outputs.update({key: value for key, value in outputs.items() if value is not None})
    timeline = content.get("timeline", []) if isinstance(content.get("timeline", []), list) else []
    timeline.append({"stage": stage, "status": status, "at": utc_now(), "outputs": outputs or {}, "error": error})
    content.update({"status": status, "stage": stage, "outputs": merged_outputs, "timeline": timeline, "updated_at": utc_now()})
    if error:
        content["error"] = error
    data["content"] = content
    data["updated_at"] = utc_now()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    storage.write_json(path, data)
    return data


def _mark_review_issues(
    storage: LocalStorage,
    review_path: str | Path,
    issue_indexes: list[int],
    *,
    status: str,
    evidence: dict[str, Any],
) -> None:
    path = resolve_path(storage.root, review_path)
    data = storage.read_json(path)
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


def _revision_task_status_from_gate(decision: str) -> str:
    if decision == "ready":
        return "publish_ready"
    if decision == "needs_revision":
        return "needs_revision"
    return "blocked"


def _display_path(root: Path, path: str | Path) -> str:
    resolved = resolve_path(root, path)
    try:
        return str(resolved.relative_to(root))
    except ValueError:
        return str(resolved)


def _dedupe(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result

from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.common import resolve_path, run_metadata
from novel_forge.modules.production_context import filter_project_safe_references, project_scope_from_asset
from novel_forge.schemas import (
    BaseAsset,
    ChapterPlanVersion,
    DraftVersion,
    GenerationRun,
    OutlineVersion,
    validate_common_fields,
)
from novel_forge.storage.local import LocalStorage

VERSION_CATEGORY_BY_TYPE = {
    "outline_version": "outlines",
    "chapter_plan_version": "chapter_plans",
    "draft_version": "drafts",
    "generation_run": "runs",
}


def create_outline_version(
    storage: LocalStorage,
    outline_path: str | Path,
    *,
    change_summary: str = "initial outline version",
    status: str = "active",
) -> dict[str, Any]:
    path = resolve_path(storage.root, outline_path)
    outline = storage.read_asset(path)
    if outline.type != "outline":
        raise ValueError("outline_path must point to an outline asset")
    project = project_scope_from_asset(storage, outline, input_path=path)
    index = _next_version_index(storage, "outline_version", outline.id)
    project_id = str(project.get("project_id", ""))
    asset = OutlineVersion(
        title=f"{outline.title or outline.id} v{index}",
        source=outline.id,
        tags=["outline", "version", f"v{index}"],
        content={
            "outline_id": outline.id,
            "outline_path": _display_path(storage.root, path),
            "version_index": index,
            "base_outline_id": outline.source or outline.id,
            "acts": outline.content.get("acts", []),
            "change_summary": change_summary,
            "status": status,
        },
        metadata=_version_metadata(storage, project, "outline_version", outline, path),
        references=filter_project_safe_references(storage, project_id, _dedupe([outline.id, _display_path(storage.root, path), *outline.references])),
    )
    return _write_version_asset(storage, asset)


def create_chapter_plan_version(
    storage: LocalStorage,
    chapter_plan_path: str | Path,
    *,
    change_summary: str = "initial chapter plan version",
    status: str = "active",
) -> dict[str, Any]:
    path = resolve_path(storage.root, chapter_plan_path)
    plan = storage.read_asset(path)
    if plan.type != "chapter_plan":
        raise ValueError("chapter_plan_path must point to a chapter_plan asset")
    project = project_scope_from_asset(storage, plan, input_path=path)
    index = _next_version_index(storage, "chapter_plan_version", plan.id)
    project_id = str(project.get("project_id", ""))
    content = plan.content
    asset = ChapterPlanVersion(
        title=f"{plan.title or plan.id} v{index}",
        source=plan.id,
        tags=["chapter-plan", "version", f"v{index}"],
        content={
            "chapter_plan_id": plan.id,
            "chapter_plan_path": _display_path(storage.root, path),
            "version_index": index,
            "base_chapter_plan_id": plan.source or plan.id,
            "chapter": content.get("chapter", 1),
            "objective": content.get("objective", ""),
            "beats": content.get("beats", []),
            "hook": content.get("hook", ""),
            "word_budget": content.get("word_budget", {"target": 2500, "min": 1800, "max": 3200}),
            "conflict": content.get("conflict", content.get("objective", "")),
            "scene_beats": content.get("scene_beats", []),
            "conflict_beats": content.get("conflict_beats", []),
            "information_points": content.get("information_points", content.get("quality_targets", [])),
            "info_release_points": content.get("info_release_points", []),
            "hook_plan": content.get("hook_plan", {}),
            "emotion_curve": content.get("emotion_curve", []),
            "payoff_target": content.get("payoff_target", {}),
            "chapter_blueprint_contract": content.get("chapter_blueprint_contract", {}),
            "blueprint_quality_gate": content.get("blueprint_quality_gate", {}),
            "change_summary": change_summary,
            "status": status,
        },
        metadata=_version_metadata(storage, project, "chapter_plan_version", plan, path),
        references=filter_project_safe_references(storage, project_id, _dedupe([plan.id, _display_path(storage.root, path), *plan.references])),
    )
    return _write_version_asset(storage, asset)


def create_draft_version(
    storage: LocalStorage,
    draft_path: str | Path,
    *,
    change_summary: str = "initial draft version",
    status: str = "active",
) -> dict[str, Any]:
    path = resolve_path(storage.root, draft_path)
    draft = storage.read_asset(path)
    if draft.type != "draft_chapter":
        raise ValueError("draft_path must point to a draft_chapter asset")
    project = project_scope_from_asset(storage, draft, input_path=path)
    index = _next_version_index(storage, "draft_version", draft.id)
    project_id = str(project.get("project_id", ""))
    content = draft.content
    asset = DraftVersion(
        title=f"{draft.title or draft.id} v{index}",
        source=draft.id,
        tags=["draft", "version", f"v{index}", str(draft.metadata.get("model", ""))],
        content={
            "draft_id": draft.id,
            "draft_path": _display_path(storage.root, path),
            "version_index": index,
            "chapter": content.get("chapter", 1),
            "text": content.get("text", ""),
            "source_draft_id": draft.source or draft.id,
            "change_summary": change_summary,
            "status": status,
            "context_bundle_id": content.get("context_bundle_id", draft.metadata.get("context_bundle_id", "")),
            "context_bundle_path": content.get("context_bundle_path", draft.metadata.get("context_bundle_path", "")),
        },
        metadata=_version_metadata(storage, project, "draft_version", draft, path),
        references=filter_project_safe_references(storage, project_id, _dedupe([draft.id, _display_path(storage.root, path), *draft.references])),
    )
    return _write_version_asset(storage, asset)


def create_generation_run(
    storage: LocalStorage,
    input_path: str | Path,
    context_bundle_path: str | Path,
    *,
    output_path: str | Path | None = None,
    provider: str = "local-rules",
    model: str = "local-rules",
    prompt_version: str = "prompt-v1",
    status: str = "succeeded",
    error: str = "",
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    input_file = resolve_path(storage.root, input_path)
    bundle_file = resolve_path(storage.root, context_bundle_path)
    input_asset = storage.read_asset(input_file)
    bundle = storage.read_asset(bundle_file)
    if bundle.type != "context_bundle":
        raise ValueError("context_bundle_path must point to a context_bundle asset")
    output_ref = ""
    output_asset_id = ""
    if output_path:
        output_file = resolve_path(storage.root, output_path)
        output_ref = _display_path(storage.root, output_file)
        if output_file.exists():
            output_asset = storage.read_asset(output_file)
            output_asset_id = output_asset.id
    project = project_scope_from_asset(storage, input_asset, input_path=input_file)
    project_id = str(project.get("project_id", ""))
    workspace_path = str(project.get("workspace_path", ""))
    now = utc_now()
    run_id = make_id("generation_run", f"{input_asset.id}-{output_asset_id or now}")
    source_asset_ids = _dedupe(
        [
            input_asset.id,
            bundle.id,
            *[str(item) for item in bundle.content.get("source_asset_ids", []) if str(item).strip()],
            output_asset_id,
        ]
    )
    asset = GenerationRun(
        title=f"Generation run for {input_asset.title or input_asset.id}",
        source=input_asset.id,
        tags=["generation-run", input_asset.type, status],
        content={
            "run_id": run_id,
            "input_asset_id": input_asset.id,
            "input_asset_path": _display_path(storage.root, input_file),
            "input_asset_type": input_asset.type,
            "context_bundle_id": bundle.id,
            "context_bundle_path": _display_path(storage.root, bundle_file),
            "output_asset_id": output_asset_id,
            "output_asset_path": output_ref,
            "provider": provider,
            "model": model,
            "prompt_version": prompt_version,
            "status": status,
            "started_at": now,
            "finished_at": now,
            "error": error,
            "source_asset_ids": source_asset_ids,
            "metrics": metrics or {},
        },
        metadata={
            "project_id": project_id,
            "workspace_path": workspace_path,
            "provider": provider,
            "model": model,
            "prompt_version": prompt_version,
            "context_bundle_id": bundle.id,
            "context_bundle_path": _display_path(storage.root, bundle_file),
            "output_asset_id": output_asset_id,
            "output_asset_path": output_ref,
            "run_metadata": run_metadata("generation_run", input_asset, provider=provider, model=model, prompt_version=prompt_version),
        },
        references=filter_project_safe_references(
            storage,
            project_id,
            _dedupe([input_asset.id, _display_path(storage.root, input_file), bundle.id, _display_path(storage.root, bundle_file), *source_asset_ids]),
        ),
    )
    return _write_version_asset(storage, asset)


def list_production_versions(storage: LocalStorage, *, project_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for asset_type, category in VERSION_CATEGORY_BY_TYPE.items():
        for path in storage.list_json(category):
            try:
                data = storage.read_json(path)
            except Exception:
                continue
            if not isinstance(data, dict) or data.get("type") != asset_type:
                continue
            metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
            if project_id and str(metadata.get("project_id", "")) != project_id:
                continue
            content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
            rows.append(
                {
                    "path": _display_path(storage.root, path),
                    "id": data.get("id", ""),
                    "type": data.get("type", ""),
                    "title": data.get("title") or data.get("name", ""),
                    "project_id": metadata.get("project_id", ""),
                    "workspace_path": metadata.get("workspace_path", ""),
                    "version_index": content.get("version_index", ""),
                    "status": content.get("status", ""),
                    "source": data.get("source", ""),
                    "source_path": content.get("outline_path") or content.get("chapter_plan_path") or content.get("draft_path") or content.get("input_asset_path", ""),
                    "context_bundle_path": content.get("context_bundle_path", ""),
                    "output_path": content.get("output_asset_path", ""),
                    "updated_at": data.get("updated_at", ""),
                    "summary": content.get("change_summary") or content.get("status") or "",
                }
            )
    return sorted(rows, key=lambda row: row.get("updated_at", ""), reverse=True)[:limit]


def _version_metadata(
    storage: LocalStorage,
    project: dict[str, Any],
    asset_type: str,
    source_asset: BaseAsset,
    source_path: Path,
) -> dict[str, Any]:
    return {
        "project_id": str(project.get("project_id", "")),
        "workspace_path": str(project.get("workspace_path", "")),
        "version_asset_type": asset_type,
        "source_asset_id": source_asset.id,
        "source_asset_type": source_asset.type,
        "source_asset_path": _display_path(storage.root, source_path),
        "run_metadata": run_metadata(asset_type, source_asset),
    }


def _write_version_asset(storage: LocalStorage, asset: BaseAsset) -> dict[str, Any]:
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset_auto(asset)
    return {"path": _display_path(storage.root, path), "asset": asset.to_dict(), "validation": {"ok": True, "errors": []}}


def _next_version_index(storage: LocalStorage, asset_type: str, source_id: str) -> int:
    category = VERSION_CATEGORY_BY_TYPE.get(asset_type)
    if not category:
        return 0
    indexes: list[int] = []
    for path in storage.list_json(category):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != asset_type or data.get("source") != source_id:
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        index = content.get("version_index")
        if isinstance(index, int):
            indexes.append(index)
    return max(indexes, default=-1) + 1


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result

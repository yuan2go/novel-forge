from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.common import resolve_path
from novel_forge.schemas import ProjectWorkspaceState
from novel_forge.storage.local import LocalStorage


def init_workspace(
    storage: LocalStorage,
    title: str = "Sample Novel Workspace",
    series_title: str | None = None,
    book_number: int | None = None,
) -> Path:
    project_key = f"{series_title or title}:book-{book_number}" if book_number is not None else title
    project_id = make_id("project", project_key)
    asset = ProjectWorkspaceState(
        title=title,
        source="local-workspace",
        tags=["workspace", "project-memory", "continuity"],
        content={
            "project_id": project_id,
            "memory": {
                "project_title": title,
                "series_title": series_title or "",
                "book_number": book_number,
                "premise": "",
                "canon_facts": [],
                "style_notes": [],
                "cross_book_threads": [],
                "last_updated_from": "",
            },
            "project_config": {
                "genre": "",
                "target_platform": "",
                "target_word_count": 0,
                "update_cadence": "",
                "quality_threshold": 80,
                "audience": "",
                "status": "active",
            },
            "chapter_states": [],
            "continuity_threads": {
                "open_hooks": [],
                "foreshadowing": [],
                "character_states": {},
                "world_state": {},
            },
            "open_issues": [],
        },
        metadata={
            "workflow": "long-project-workspace",
            "chapter_count": 0,
            "status": "initialized",
            "series_title": series_title or "",
            "book_number": book_number,
            "external_api": False,
        },
        references=[],
    )
    return storage.write_asset("workspaces", asset)


def update_workspace(
    storage: LocalStorage,
    input_path: str | None = None,
    workspace_path: str | None = None,
    chapter: int | None = None,
    status: str = "drafted",
) -> Path:
    workspace = _read_or_create_workspace(storage, workspace_path)
    source_path = resolve_path(storage.root, input_path) if input_path else storage.latest("drafts")
    source_asset = storage.read_asset(source_path)
    chapter_number = chapter or _infer_chapter_number(source_asset)
    content = dict(workspace.content)
    chapter_states = [dict(item) for item in content.get("chapter_states", []) if isinstance(item, dict)]
    chapter_state = _build_chapter_state(storage, source_path, source_asset, chapter_number, status)
    chapter_states = _upsert_chapter_state(chapter_states, chapter_state)
    content["chapter_states"] = chapter_states
    content["continuity_threads"] = _update_continuity_threads(content.get("continuity_threads", {}), chapter_state, source_asset)
    content["memory"] = _update_memory(content.get("memory", {}), chapter_state)
    content["open_issues"] = _update_open_issues(content.get("open_issues", []), source_asset, chapter_number)

    workspace.content = content
    workspace.updated_at = utc_now()
    workspace.metadata = {
        **workspace.metadata,
        "workflow": "long-project-workspace",
        "chapter_count": len(chapter_states),
        "latest_chapter": chapter_number,
        "latest_asset": source_asset.id,
        "status": "updated",
    }
    workspace.references = _dedupe([*workspace.references, source_asset.id])
    return storage.write_asset("workspaces", workspace)


def workspace_status(storage: LocalStorage, workspace_path: str | None = None) -> dict[str, Any]:
    workspace = _read_workspace(storage, workspace_path)
    chapter_states = workspace.content.get("chapter_states", [])
    threads = workspace.content.get("continuity_threads", {})
    open_issues = workspace.content.get("open_issues", [])
    return {
        "id": workspace.id,
        "title": workspace.title,
        "path": str(_workspace_path(storage, workspace).relative_to(storage.root)),
        "chapter_count": len(chapter_states) if isinstance(chapter_states, list) else 0,
        "latest_chapter": workspace.metadata.get("latest_chapter", 0),
        "series_title": workspace.metadata.get("series_title", ""),
        "book_number": workspace.metadata.get("book_number"),
        "open_hook_count": len(threads.get("open_hooks", [])) if isinstance(threads, dict) else 0,
        "open_issue_count": len(open_issues) if isinstance(open_issues, list) else 0,
        "references": workspace.references,
    }


def _read_or_create_workspace(storage: LocalStorage, workspace_path: str | None) -> ProjectWorkspaceState:
    try:
        return _read_workspace(storage, workspace_path)
    except FileNotFoundError:
        path = init_workspace(storage)
        return storage.read_asset(path)  # type: ignore[return-value]


def _read_workspace(storage: LocalStorage, workspace_path: str | None) -> ProjectWorkspaceState:
    path = resolve_path(storage.root, workspace_path) if workspace_path else storage.latest("workspaces")
    asset = storage.read_asset(path)
    if not isinstance(asset, ProjectWorkspaceState):
        raise ValueError(f"workspace asset must be project_workspace_state: {path}")
    return asset


def _workspace_path(storage: LocalStorage, workspace: ProjectWorkspaceState) -> Path:
    return storage.data_dir("workspaces") / f"{workspace.id}.json"


def _infer_chapter_number(source_asset: Any) -> int:
    chapter = source_asset.content.get("chapter") if isinstance(source_asset.content, dict) else None
    if isinstance(chapter, int):
        return chapter
    if isinstance(chapter, str) and chapter.isdigit():
        return int(chapter)
    return 1


def _build_chapter_state(
    storage: LocalStorage,
    source_path: Path,
    source_asset: Any,
    chapter_number: int,
    status: str,
) -> dict[str, Any]:
    text = _chapter_text(source_asset)
    return {
        "chapter": chapter_number,
        "status": status,
        "asset_id": source_asset.id,
        "asset_type": source_asset.type,
        "asset_path": str(source_path.relative_to(storage.root)),
        "title": source_asset.title,
        "summary": _summarize(text or source_asset.title),
        "hook": _last_sentence(text),
        "updated_at": utc_now(),
    }


def _upsert_chapter_state(chapter_states: list[dict[str, Any]], chapter_state: dict[str, Any]) -> list[dict[str, Any]]:
    updated = False
    result: list[dict[str, Any]] = []
    for existing in chapter_states:
        if existing.get("chapter") == chapter_state["chapter"]:
            merged = {**existing, **chapter_state}
            if not chapter_state.get("hook") and existing.get("hook"):
                merged["hook"] = existing["hook"]
            if chapter_state.get("asset_type") == "review_report":
                merged["review_asset_id"] = chapter_state["asset_id"]
                merged["draft_asset_id"] = existing.get("draft_asset_id") or existing.get("asset_id")
            if chapter_state.get("asset_type") == "draft_chapter":
                merged["draft_asset_id"] = chapter_state["asset_id"]
            result.append(merged)
            updated = True
        else:
            result.append(existing)
    if not updated:
        if chapter_state.get("asset_type") == "draft_chapter":
            chapter_state["draft_asset_id"] = chapter_state["asset_id"]
        if chapter_state.get("asset_type") == "review_report":
            chapter_state["review_asset_id"] = chapter_state["asset_id"]
        result.append(chapter_state)
    return sorted(result, key=lambda item: int(item.get("chapter", 0)))


def _update_continuity_threads(threads: Any, chapter_state: dict[str, Any], source_asset: Any) -> dict[str, Any]:
    current = threads if isinstance(threads, dict) else {}
    open_hooks = [dict(item) for item in current.get("open_hooks", []) if isinstance(item, dict)]
    if chapter_state.get("hook"):
        open_hooks = _upsert_thread(
            open_hooks,
            {
                "id": f"chapter-{chapter_state['chapter']}-hook",
                "chapter": chapter_state["chapter"],
                "description": chapter_state["hook"],
                "status": "open",
            },
        )
    return {
        "open_hooks": open_hooks,
        "foreshadowing": current.get("foreshadowing", []),
        "character_states": current.get("character_states", {}),
        "world_state": current.get("world_state", {}),
        "latest_asset_type": source_asset.type,
    }


def _update_memory(memory: Any, chapter_state: dict[str, Any]) -> dict[str, Any]:
    current = memory if isinstance(memory, dict) else {}
    canon_facts = [str(item) for item in current.get("canon_facts", []) if str(item).strip()]
    fact = f"Chapter {chapter_state['chapter']}: {chapter_state['summary']}"
    if fact not in canon_facts:
        canon_facts.append(fact)
    return {
        **current,
        "canon_facts": canon_facts,
        "last_updated_from": chapter_state["asset_id"],
    }


def _update_open_issues(open_issues: Any, source_asset: Any, chapter_number: int) -> list[dict[str, Any]]:
    issues = [dict(item) for item in open_issues if isinstance(item, dict)] if isinstance(open_issues, list) else []
    if source_asset.type != "review_report":
        return issues
    for issue in source_asset.issues:
        if isinstance(issue, dict):
            issues = _upsert_thread(
                issues,
                {
                    "id": f"chapter-{chapter_number}-{issue.get('dimension', 'issue')}",
                    "chapter": chapter_number,
                    "dimension": issue.get("dimension", "unknown"),
                    "severity": issue.get("severity", "medium"),
                    "message": issue.get("message", ""),
                    "status": "open",
                },
            )
    return issues


def _upsert_thread(items: list[dict[str, Any]], new_item: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    updated = False
    for item in items:
        if item.get("id") == new_item["id"]:
            result.append(new_item)
            updated = True
        else:
            result.append(item)
    if not updated:
        result.append(new_item)
    return result


def _chapter_text(source_asset: Any) -> str:
    content = source_asset.content if isinstance(source_asset.content, dict) else {}
    for key in ["text", "summary"]:
        value = content.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _summarize(text: str) -> str:
    compact = " ".join(text.split())
    return compact[:160]


def _last_sentence(text: str) -> str:
    compact = " ".join(text.split())
    if not compact:
        return ""
    for delimiter in ["。", "！", "？", ".", "!", "?"]:
        if delimiter in compact:
            parts = [part.strip() for part in compact.replace("！", "。").replace("？", "。").split("。") if part.strip()]
            if parts:
                return parts[-1][:120]
    return compact[-120:]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result

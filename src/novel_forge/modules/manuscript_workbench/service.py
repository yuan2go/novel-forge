from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.modules.common import resolve_path
from novel_forge.storage.local import LocalStorage


def build_manuscript_workbench(
    storage: LocalStorage,
    *,
    project_id: str | None = None,
    draft_path: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Return a chapter-centric reading, editing, and provenance snapshot.

    The workbench is deliberately an aggregation layer over existing assets. It
    does not introduce a parallel manuscript model; instead it makes draft,
    context, review, editor, and Agent evidence visible from one API boundary.
    """

    storage.ensure_layout()
    drafts = _asset_rows(storage, "drafts", {"draft_chapter"}, project_id=project_id, limit=limit)
    selected_path = _select_draft_path(storage, drafts, draft_path)
    selected = _draft_detail(storage, selected_path) if selected_path else None
    related = _related_references(selected)
    generation_runs = _related_assets(storage, "runs", {"generation_run"}, related, project_id=project_id, limit=limit)
    context_bundles = _context_bundles(storage, selected, generation_runs, project_id=project_id, limit=limit)
    context_sources = _context_sources(context_bundles)
    reviews = _related_assets(
        storage,
        "reviews",
        {"review_report", "chapter_audit_report", "quality_score_report", "style_review_report", "originality_report"},
        related,
        project_id=project_id,
        limit=limit,
    )
    revisions = _revision_assets(storage, reviews, related, project_id=project_id, limit=limit)
    editor_artifacts = _related_assets(storage, "drafts", {"editor_patch", "draft_diff_report"}, related, project_id=project_id, limit=limit)
    agent_runs = _agent_runs(storage, related, project_id=project_id, limit=limit)
    agent_events = _agent_events(storage, agent_runs, project_id=project_id, limit=limit)
    return {
        "project_id": project_id or _project_id_from_selected(selected),
        "selected_draft_path": selected_path,
        "selected_draft": selected,
        "chapters": _chapter_rows(drafts, reviews),
        "versions": _draft_versions(storage, selected, project_id=project_id, limit=limit),
        "generation_runs": generation_runs,
        "context_bundles": context_bundles,
        "context_sources": context_sources,
        "reviews": reviews,
        "revision_plans": revisions,
        "editor_artifacts": editor_artifacts,
        "agent_runs": agent_runs,
        "agent_events": agent_events,
        "trace_summary": _trace_summary(
            selected=selected,
            context_sources=context_sources,
            generation_runs=generation_runs,
            reviews=reviews,
            editor_artifacts=editor_artifacts,
            agent_runs=agent_runs,
        ),
    }


def _select_draft_path(storage: LocalStorage, drafts: list[dict[str, Any]], draft_path: str | None) -> str:
    if draft_path:
        path = resolve_path(storage.root, draft_path)
        path.resolve().relative_to(storage.root)
        if not path.exists():
            raise FileNotFoundError(f"draft not found: {draft_path}")
        return _display_path(storage.root, path)
    return str(drafts[0].get("path", "")) if drafts else ""


def _draft_detail(storage: LocalStorage, draft_path: str) -> dict[str, Any]:
    path = resolve_path(storage.root, draft_path)
    data = storage.read_json(path)
    if not isinstance(data, dict) or data.get("type") != "draft_chapter":
        raise ValueError(f"draft_path must point to a draft_chapter asset: {draft_path}")
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    return {
        "path": _display_path(storage.root, path),
        "id": data.get("id", ""),
        "type": data.get("type", ""),
        "title": data.get("title") or data.get("name", ""),
        "chapter": content.get("chapter", ""),
        "text": content.get("text", ""),
        "word_count": len(str(content.get("text", "")).split()),
        "status": metadata.get("draft_status", "draft"),
        "version_index": metadata.get("version_index", 0),
        "source": data.get("source", ""),
        "references": data.get("references", []) if isinstance(data.get("references", []), list) else [],
        "metadata": metadata,
        "context_bundle_path": content.get("context_bundle_path") or metadata.get("context_bundle_path", ""),
        "context_bundle_id": content.get("context_bundle_id") or metadata.get("context_bundle_id", ""),
        "generation_run_path": metadata.get("generation_run_path", ""),
        "generation_run_id": metadata.get("generation_run_id", ""),
        "agent_run_path": content.get("agent_run_path") or metadata.get("agent_run_path", ""),
        "production_context": content.get("production_context", {}) if isinstance(content.get("production_context", {}), dict) else {},
        "retrieved_context": content.get("retrieved_context", {}) if isinstance(content.get("retrieved_context", {}), dict) else {},
        "copyright_boundary": content.get("copyright_boundary", ""),
        "updated_at": data.get("updated_at", ""),
    }


def _asset_rows(
    storage: LocalStorage,
    category: str,
    asset_types: set[str],
    *,
    project_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in reversed(storage.list_json(category)):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") not in asset_types:
            continue
        if project_id and _project_id(data) != project_id:
            continue
        rows.append(_row(storage, path, data))
        if len(rows) >= limit:
            break
    return rows


def _related_assets(
    storage: LocalStorage,
    category: str,
    asset_types: set[str],
    related: set[str],
    *,
    project_id: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in reversed(storage.list_json(category)):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") not in asset_types:
            continue
        if project_id and _project_id(data) != project_id:
            continue
        if not _matches_related(storage, path, data, related):
            continue
        rows.append(_row(storage, path, data))
        if len(rows) >= limit:
            break
    return rows


def _revision_assets(
    storage: LocalStorage,
    reviews: list[dict[str, Any]],
    related: set[str],
    *,
    project_id: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    review_refs = {str(row.get("id", "")) for row in reviews} | {str(row.get("path", "")) for row in reviews}
    return _related_assets(storage, "reviews", {"revision_plan"}, related | review_refs, project_id=project_id, limit=limit)


def _context_bundles(
    storage: LocalStorage,
    selected: dict[str, Any] | None,
    generation_runs: list[dict[str, Any]],
    *,
    project_id: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    refs = set()
    if selected:
        refs.update([str(selected.get("context_bundle_path", "")), str(selected.get("context_bundle_id", ""))])
    for run in generation_runs:
        content = run.get("content", {}) if isinstance(run.get("content", {}), dict) else {}
        refs.update([str(content.get("context_bundle_path", "")), str(content.get("context_bundle_id", ""))])
    refs = {ref for ref in refs if ref}
    if not refs:
        return []
    rows: list[dict[str, Any]] = []
    for path in reversed(storage.list_json("contexts")):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "context_bundle":
            continue
        if project_id and _project_id(data) != project_id:
            continue
        display = _display_path(storage.root, path)
        if data.get("id") not in refs and display not in refs:
            continue
        rows.append(_row(storage, path, data))
        if len(rows) >= limit:
            break
    return rows


def _context_sources(context_bundles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for bundle in context_bundles:
        content = bundle.get("content", {}) if isinstance(bundle.get("content", {}), dict) else {}
        selected_assets = content.get("selected_assets", []) if isinstance(content.get("selected_assets", []), list) else []
        for item in selected_assets:
            if not isinstance(item, dict):
                continue
            key = str(item.get("path") or item.get("id") or item.get("title") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "id": item.get("id", ""),
                    "path": item.get("path", ""),
                    "type": item.get("type", ""),
                    "title": item.get("title", ""),
                    "rank": item.get("rank", ""),
                    "score": item.get("score", ""),
                    "ranker": item.get("ranker", ""),
                    "backend": item.get("backend", content.get("retrieval_backend", "")),
                    "risk_level": item.get("risk_level", ""),
                    "preview": item.get("preview", ""),
                    "source_bundle_path": bundle.get("path", ""),
                }
            )
        retrieved = content.get("retrieved_context", {}) if isinstance(content.get("retrieved_context", {}), dict) else {}
        for item in retrieved.get("items", []) if isinstance(retrieved.get("items", []), list) else []:
            if not isinstance(item, dict):
                continue
            key = str(item.get("path") or item.get("id") or item.get("title") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "id": item.get("id", ""),
                    "path": item.get("path", ""),
                    "type": item.get("type", ""),
                    "title": item.get("title", ""),
                    "rank": item.get("rank", ""),
                    "score": item.get("score", ""),
                    "ranker": item.get("ranker", ""),
                    "backend": item.get("backend", retrieved.get("retrieval_backend", "")),
                    "risk_level": item.get("risk_level", ""),
                    "preview": item.get("preview", ""),
                    "source_bundle_path": bundle.get("path", ""),
                }
            )
    return rows


def _draft_versions(
    storage: LocalStorage,
    selected: dict[str, Any] | None,
    *,
    project_id: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    if not selected:
        return []
    refs = _related_references(selected)
    source = str(selected.get("source", ""))
    if source:
        refs.add(source)
    return _related_assets(storage, "drafts", {"draft_chapter", "draft_version"}, refs, project_id=project_id, limit=limit)


def _agent_runs(storage: LocalStorage, related: set[str], *, project_id: str | None, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in reversed(storage.list_json("runs")):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "agent_run":
            continue
        if project_id and _project_id(data) != project_id:
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        input_assets = content.get("input_assets", []) if isinstance(content.get("input_assets", []), list) else []
        output_assets = content.get("output_assets", []) if isinstance(content.get("output_assets", []), list) else []
        asset_refs = _asset_refs(input_assets) | _asset_refs(output_assets)
        if not (asset_refs & related):
            continue
        rows.append(_row(storage, path, data))
        if len(rows) >= limit:
            break
    return rows


def _agent_events(storage: LocalStorage, agent_runs: list[dict[str, Any]], *, project_id: str | None, limit: int) -> list[dict[str, Any]]:
    refs = {str(row.get("id", "")) for row in agent_runs} | {str(row.get("path", "")) for row in agent_runs}
    rows: list[dict[str, Any]] = []
    for path in reversed(storage.list_json("runs")):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "agent_event":
            continue
        if project_id and _project_id(data) != project_id:
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if str(content.get("agent_run_id", "")) not in refs and str(content.get("agent_run_path", "")) not in refs:
            continue
        rows.append(_row(storage, path, data))
        if len(rows) >= limit:
            break
    return rows


def _chapter_rows(drafts: list[dict[str, Any]], reviews: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for draft in drafts:
        chapter = str(draft.get("chapter") or "unknown")
        row = grouped.setdefault(
            chapter,
            {
                "chapter": draft.get("chapter", ""),
                "latest_draft_path": draft.get("path", ""),
                "latest_title": draft.get("title", ""),
                "draft_count": 0,
                "review_count": 0,
                "latest_updated_at": draft.get("updated_at", ""),
                "status": draft.get("status", "") or "draft",
            },
        )
        row["draft_count"] += 1
        if str(draft.get("updated_at", "")) >= str(row.get("latest_updated_at", "")):
            row["latest_draft_path"] = draft.get("path", "")
            row["latest_title"] = draft.get("title", "")
            row["latest_updated_at"] = draft.get("updated_at", "")
            row["status"] = draft.get("status", "") or row.get("status", "")
    for review in reviews:
        chapter = str(review.get("chapter") or "unknown")
        if chapter in grouped:
            grouped[chapter]["review_count"] += 1
    return sorted(grouped.values(), key=lambda row: _chapter_sort_key(row.get("chapter")))


def _trace_summary(
    *,
    selected: dict[str, Any] | None,
    context_sources: list[dict[str, Any]],
    generation_runs: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
    editor_artifacts: list[dict[str, Any]],
    agent_runs: list[dict[str, Any]],
) -> dict[str, Any]:
    review_scores = [row.get("score") for row in reviews if isinstance(row.get("score"), (int, float))]
    statuses = [str(row.get("status", "")) for row in agent_runs if row.get("status")]
    return {
        "has_selected_draft": bool(selected),
        "context_source_count": len(context_sources),
        "generation_run_count": len(generation_runs),
        "review_count": len(reviews),
        "editor_artifact_count": len(editor_artifacts),
        "agent_run_count": len(agent_runs),
        "latest_review_score": review_scores[0] if review_scores else None,
        "agent_statuses": _counts(statuses),
        "ready_for_review": bool(selected) and bool(context_sources) and bool(generation_runs),
    }


def _related_references(selected: dict[str, Any] | None) -> set[str]:
    if not selected:
        return set()
    refs = {
        str(selected.get("id", "")),
        str(selected.get("path", "")),
        str(selected.get("source", "")),
        str(selected.get("context_bundle_path", "")),
        str(selected.get("context_bundle_id", "")),
        str(selected.get("generation_run_path", "")),
        str(selected.get("generation_run_id", "")),
        str(selected.get("agent_run_path", "")),
    }
    refs.update(str(item) for item in selected.get("references", []) if str(item).strip())
    return {ref for ref in refs if ref}


def _matches_related(storage: LocalStorage, path: Path, data: dict[str, Any], related: set[str]) -> bool:
    if not related:
        return False
    display = _display_path(storage.root, path)
    refs = {display, str(path), str(data.get("id", "")), str(data.get("source", ""))}
    if isinstance(data.get("references", []), list):
        refs.update(str(item) for item in data.get("references", []) if str(item).strip())
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    refs.update(_scalar_values(content))
    refs.update(_scalar_values(metadata))
    refs.update(_asset_refs(content.get("input_assets", [])) if isinstance(content.get("input_assets", []), list) else set())
    refs.update(_asset_refs(content.get("output_assets", [])) if isinstance(content.get("output_assets", []), list) else set())
    return bool(refs & related)


def _row(storage: LocalStorage, path: Path, data: dict[str, Any]) -> dict[str, Any]:
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    return {
        "path": _display_path(storage.root, path),
        "id": data.get("id", ""),
        "type": data.get("type", ""),
        "title": data.get("title") or data.get("name", ""),
        "source": data.get("source", ""),
        "chapter": content.get("chapter", ""),
        "score": data.get("score") or content.get("overall_score"),
        "status": content.get("status") or metadata.get("draft_status") or metadata.get("asset_status", ""),
        "risk_level": data.get("risk_level") or metadata.get("risk_level", ""),
        "updated_at": data.get("updated_at", ""),
        "summary": _summary(content),
        "tags": data.get("tags", []) if isinstance(data.get("tags", []), list) else [],
        "content": content,
        "metadata": metadata,
        "references": data.get("references", []) if isinstance(data.get("references", []), list) else [],
    }


def _asset_refs(rows: list[Any]) -> set[str]:
    refs: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in ["id", "path", "asset_id", "asset_path"]:
            value = row.get(key)
            if value:
                refs.add(str(value))
    return refs


def _scalar_values(payload: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    for key, value in payload.items():
        if key.endswith("_id") or key.endswith("_path") or key in {"target_asset_id", "target_draft_id", "target_draft_path", "output_asset_id", "output_asset_path", "input_asset_id", "input_asset_path"}:
            if value:
                values.add(str(value))
        if isinstance(value, dict):
            values.update(_scalar_values(value))
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    values.update(_scalar_values(item))
                elif isinstance(item, str) and ("/" in item or item.endswith(".json")):
                    values.add(item)
    return values


def _project_id(data: dict[str, Any]) -> str:
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    return str(metadata.get("project_id") or content.get("project_id") or "")


def _project_id_from_selected(selected: dict[str, Any] | None) -> str:
    if not selected:
        return ""
    metadata = selected.get("metadata", {}) if isinstance(selected.get("metadata", {}), dict) else {}
    production = selected.get("production_context", {}) if isinstance(selected.get("production_context", {}), dict) else {}
    project = production.get("project", {}) if isinstance(production.get("project", {}), dict) else {}
    return str(metadata.get("project_id") or project.get("project_id") or "")


def _counts(values: list[str]) -> dict[str, int]:
    rows: dict[str, int] = {}
    for value in values:
        rows[value] = rows.get(value, 0) + 1
    return rows


def _summary(content: dict[str, Any]) -> str:
    for key in ["summary", "text", "objective", "hook", "recommendation", "status", "change_summary"]:
        value = content.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:220]
    return str(content)[:220]


def _chapter_sort_key(value: Any) -> tuple[int, str]:
    try:
        return (0, f"{int(value):06d}")
    except Exception:
        return (1, str(value))


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)

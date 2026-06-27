from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from novel_forge.core.constants import DATA_DIRS
from novel_forge.modules.common import resolve_path, run_metadata
from novel_forge.modules.production_context import filter_project_safe_references, project_scope_from_asset
from novel_forge.schemas import BaseAsset, ContextBuildPlan, ContextBundle, validate_common_fields
from novel_forge.storage.local import LocalStorage
from novel_forge.storage.rag_context import build_rag_context, retrieval_metadata

RAW_OR_REPORT_TYPES = {
    "source_document",
    "cleaned_text",
    "decomposition_report",
    "common_novel_analysis_report",
    "web_fiction_business_analysis_report",
    "published_fiction_analysis_report",
    "classic_literary_analysis_report",
}


def create_context_build_plan(
    storage: LocalStorage,
    target_path: str | Path,
    *,
    query: str = "",
    top_k: int = 8,
    token_budget: int = 4000,
    backend: str = "auto",
    workspace_path: str | None = None,
) -> dict[str, Any]:
    target_file = resolve_path(storage.root, target_path)
    target_asset = storage.read_asset(target_file)
    project = project_scope_from_asset(storage, target_asset, input_path=target_file, workspace_path=workspace_path)
    context_query = query or _default_query(target_asset)
    retrieved_context = build_rag_context(
        storage,
        target_asset,
        input_path=target_file,
        query=context_query,
        top_k=top_k,
        backend=backend,
    )
    candidates = [_candidate_payload(item) for item in retrieved_context.get("items", []) if isinstance(item, dict)]
    exclusions = _context_exclusions(storage, project)
    project_id = str(project.get("project_id", ""))
    workspace = str(project.get("workspace_path", "") or workspace_path or "")
    asset = ContextBuildPlan(
        title=f"Context build plan for {target_asset.title or target_asset.id}",
        source=target_asset.id,
        tags=["context", "build-plan", retrieved_context.get("retrieval_backend", "unknown")],
        content={
            "target_asset_id": target_asset.id,
            "target_asset_type": target_asset.type,
            "target_path": _display_path(storage.root, target_file),
            "query": retrieved_context.get("query", context_query),
            "top_k": int(top_k),
            "ranker": retrieved_context.get("ranker", ""),
            "requested_backend": retrieved_context.get("requested_backend", backend),
            "retrieval_backend": retrieved_context.get("retrieval_backend", ""),
            "backend_attempts": retrieved_context.get("backend_attempts", []),
            "token_budget": _token_budget(token_budget),
            "selection_policy": {
                "project_scoped": bool(project_id or workspace),
                "allowed_buckets": list(retrieved_context.get("buckets", {}).keys()),
                "exclude_raw_sources": True,
                "exclude_analysis_reports_from_generation_rag": True,
                "required_asset_types": [
                    "character_card",
                    "world_bible",
                    "knowledge_card",
                    "material_card",
                    "writing_template",
                    "craft_template",
                    "draft_chapter",
                ],
                "ranker": retrieved_context.get("ranker", ""),
            },
            "candidate_assets": candidates,
            "exclusions": exclusions,
            "retrieved_context": retrieved_context,
        },
        metadata={
            "project_id": project_id,
            "workspace_path": workspace,
            "retrieval_backend": retrieved_context.get("retrieval_backend", ""),
            "retrieval_ranker": retrieved_context.get("ranker", ""),
            "retrieval_top_k": retrieved_context.get("top_k", top_k),
            "retrieval_query": retrieved_context.get("query", context_query),
            "source_asset_path": _display_path(storage.root, target_file),
            "copyright_boundary": "generation context plan uses project-scoped abstract and original assets; raw sources and analysis reports are excluded",
            "run_metadata": run_metadata("context_build_plan", target_asset),
            **retrieval_metadata(retrieved_context),
        },
        references=filter_project_safe_references(
            storage,
            project_id,
            _dedupe([target_asset.id, _display_path(storage.root, target_file), *retrieved_context.get("source_asset_ids", [])]),
        ),
    )
    _ensure_valid(asset)
    path = storage.write_asset_auto(asset)
    return {"path": _display_path(storage.root, path), "asset": asset.to_dict(), "validation": {"ok": True, "errors": []}}


def create_context_bundle(
    storage: LocalStorage,
    build_plan_path: str | Path,
    *,
    max_items: int | None = None,
) -> dict[str, Any]:
    plan_file = resolve_path(storage.root, build_plan_path)
    plan = storage.read_asset(plan_file)
    if plan.type != "context_build_plan":
        raise ValueError("build_plan_path must point to a context_build_plan asset")
    content = plan.content
    candidates = [item for item in content.get("candidate_assets", []) if isinstance(item, dict)]
    selected = _select_candidates(candidates, max_items=max_items)
    selected_ids = _dedupe([str(item.get("asset_id", "")) for item in selected if item.get("asset_id")])
    bucketed = _bucket_selected(selected)
    actual_context = _actual_context_text(bucketed, int(content.get("token_budget", {}).get("max_tokens", 4000)))
    token_estimate = _estimate_tokens(actual_context)
    project_id = str(plan.metadata.get("project_id") or "")
    workspace_path = str(plan.metadata.get("workspace_path") or "")
    asset = ContextBundle(
        title=f"Context bundle for {content.get('target_asset_type', 'asset')} {content.get('target_asset_id', '')}",
        source=plan.id,
        tags=["context", "bundle", str(content.get("retrieval_backend", ""))],
        content={
            "build_plan_id": plan.id,
            "build_plan_path": _display_path(storage.root, plan_file),
            "target_asset_id": content.get("target_asset_id", ""),
            "target_asset_type": content.get("target_asset_type", ""),
            "target_path": content.get("target_path", ""),
            "query": content.get("query", ""),
            "ranker": content.get("ranker", ""),
            "retrieval_backend": content.get("retrieval_backend", ""),
            "selected_assets": selected,
            "compressed_context": bucketed,
            "token_budget": content.get("token_budget", _token_budget(4000)),
            "token_estimate": token_estimate,
            "actual_context": actual_context,
            "source_asset_ids": selected_ids,
            "retrieved_context": content.get("retrieved_context", {}),
        },
        metadata={
            "project_id": project_id,
            "workspace_path": workspace_path,
            "context_build_plan_path": _display_path(storage.root, plan_file),
            "retrieval_backend": content.get("retrieval_backend", ""),
            "retrieval_ranker": content.get("ranker", ""),
            "retrieval_query": content.get("query", ""),
            "retrieval_top_k": content.get("top_k", 0),
            "retrieval_source_asset_ids": selected_ids,
            "token_estimate": token_estimate,
            "copyright_boundary": "context bundle includes compressed summaries and project-owned/abstract assets only; raw source text is not included",
            "run_metadata": run_metadata("context_bundle", plan),
        },
        references=filter_project_safe_references(
            storage,
            project_id,
            _dedupe([plan.id, _display_path(storage.root, plan_file), str(content.get("target_asset_id", "")), *selected_ids]),
        ),
    )
    _ensure_valid(asset)
    path = storage.write_asset_auto(asset)
    return {"path": _display_path(storage.root, path), "asset": asset.to_dict(), "validation": {"ok": True, "errors": []}}


def list_context_assets(storage: LocalStorage, *, project_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in storage.list_json("contexts"):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") not in {"context_build_plan", "context_bundle"}:
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
                "target_asset_id": content.get("target_asset_id", ""),
                "target_asset_type": content.get("target_asset_type", ""),
                "target_path": content.get("target_path", ""),
                "retrieval_backend": content.get("retrieval_backend", metadata.get("retrieval_backend", "")),
                "ranker": content.get("ranker", metadata.get("retrieval_ranker", "")),
                "token_estimate": content.get("token_estimate", metadata.get("token_estimate", 0)),
                "source_count": len(content.get("source_asset_ids", []) if isinstance(content.get("source_asset_ids", []), list) else []),
                "candidate_count": len(content.get("candidate_assets", []) if isinstance(content.get("candidate_assets", []), list) else []),
                "updated_at": data.get("updated_at", ""),
                "summary": _compact(str(content.get("actual_context") or content.get("query") or ""), 180),
            }
        )
    return sorted(rows, key=lambda row: row.get("updated_at", ""), reverse=True)[:limit]


def _default_query(asset: BaseAsset) -> str:
    return f"{asset.type} {asset.title} {json.dumps(asset.content, ensure_ascii=False, sort_keys=True)[:900]}"


def _candidate_payload(item: dict[str, Any]) -> dict[str, Any]:
    summary = str(item.get("summary", ""))
    return {
        "asset_id": str(item.get("asset_id", "")),
        "path": str(item.get("path", "")),
        "type": str(item.get("type", "")),
        "title": str(item.get("title", "")),
        "categories": item.get("categories", []) if isinstance(item.get("categories", []), list) else [],
        "score": item.get("score", 0),
        "ranker": str(item.get("ranker", "")),
        "project_id": str(item.get("project_id", "")),
        "workspace_path": str(item.get("workspace_path", "")),
        "token_estimate": _estimate_tokens(summary),
        "summary": summary,
        "selected_by_default": str(item.get("type", "")) not in RAW_OR_REPORT_TYPES,
    }


def _context_exclusions(storage: LocalStorage, project: dict[str, Any]) -> list[dict[str, str]]:
    project_id = str(project.get("project_id", ""))
    excluded: list[dict[str, str]] = []
    for category in DATA_DIRS:
        for path in storage.list_json(category):
            try:
                data = storage.read_json(path)
            except Exception:
                continue
            if not isinstance(data, dict) or data.get("type") not in RAW_OR_REPORT_TYPES:
                continue
            metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
            asset_project_id = str(metadata.get("project_id", ""))
            if project_id and asset_project_id and asset_project_id != project_id:
                continue
            excluded.append(
                {
                    "asset_id": str(data.get("id", "")),
                    "path": _display_path(storage.root, path),
                    "type": str(data.get("type", "")),
                    "reason": "raw source or analysis report must be converted before generation RAG",
                }
            )
    return excluded[:100]


def _select_candidates(candidates: list[dict[str, Any]], *, max_items: int | None) -> list[dict[str, Any]]:
    selected = [
        candidate
        for candidate in candidates
        if candidate.get("selected_by_default", True) and str(candidate.get("type", "")) not in RAW_OR_REPORT_TYPES
    ]
    if max_items is not None and max_items > 0:
        return selected[:max_items]
    return selected


def _bucket_selected(selected: list[dict[str, Any]]) -> dict[str, list[dict[str, str]]]:
    buckets: dict[str, list[dict[str, str]]] = {}
    for item in selected:
        categories = item.get("categories", []) if isinstance(item.get("categories", []), list) else []
        if not categories:
            categories = ["other"]
        for category in categories:
            buckets.setdefault(str(category), []).append(
                {
                    "asset_id": str(item.get("asset_id", "")),
                    "path": str(item.get("path", "")),
                    "type": str(item.get("type", "")),
                    "title": str(item.get("title", "")),
                    "summary": _compact(str(item.get("summary", "")), 480),
                }
            )
    return buckets


def _actual_context_text(bucketed: dict[str, list[dict[str, str]]], max_tokens: int) -> str:
    limit = max(max_tokens * 4, 1200)
    chunks: list[str] = []
    for bucket, items in bucketed.items():
        if not items:
            continue
        chunks.append(f"## {bucket}")
        for item in items:
            chunks.append(f"- [{item['type']}] {item['title']} ({item['path']}): {item['summary']}")
    text = "\n".join(chunks).strip()
    return _compact(text or "No eligible project-scoped context assets were selected.", limit)


def _token_budget(max_tokens: int) -> dict[str, int]:
    safe_max = max(int(max_tokens), 512)
    return {
        "max_tokens": safe_max,
        "reserved_for_prompt": max(128, int(safe_max * 0.15)),
        "reserved_for_response": max(512, int(safe_max * 0.35)),
    }


def _estimate_tokens(text: str) -> int:
    return max(0, int(len(str(text)) / 4))


def _ensure_valid(asset: BaseAsset) -> None:
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("; ".join(errors))


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _compact(text: str, limit: int) -> str:
    compact = " ".join(str(text).split())
    return compact if len(compact) <= limit else compact[: limit - 3] + "..."


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result

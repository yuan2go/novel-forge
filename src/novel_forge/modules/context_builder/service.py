from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from novel_forge.core.constants import DATA_DIRS
from novel_forge.core.ids import utc_now
from novel_forge.modules.common import resolve_path, run_metadata
from novel_forge.modules.novel_kg import build_novel_kg_context
from novel_forge.modules.production_context import filter_project_safe_references, project_scope_from_asset
from novel_forge.modules.runtime_ledger import record_trace_span
from novel_forge.schemas import BaseAsset, ContextBuildPlan, ContextBundle, ProjectMetricSnapshot, RagQualityReport, validate_common_fields
from novel_forge.storage.local import LocalStorage
from novel_forge.storage.rag_context import build_rag_context, generation_context_policy, retrieval_metadata

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
    context_profile: str = "chapter_generation",
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
    project_id = str(project.get("project_id", ""))
    workspace = str(project.get("workspace_path", "") or workspace_path or "")
    kg_context = _kg_context_for_plan(
        storage,
        target_path=target_file,
        query=context_query,
        project_id=project_id or None,
        workspace_path=workspace or None,
        limit=max(4, int(top_k)),
    )
    candidates = _merge_context_candidates(
        [*_candidate_payloads(retrieved_context.get("items", [])), *kg_context.get("items", [])],
    )
    exclusions = _dedupe_exclusions([*_context_exclusions(storage, project), *_rag_copyright_exclusions(retrieved_context)])
    profile_policy = _context_profile_policy(context_profile)
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
            "context_profile": context_profile,
            "context_profile_policy": profile_policy,
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
                "exclude_high_copyright_risk": True,
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
            "retrieval_quality": retrieved_context.get("quality", {}),
            "recall_explanation": retrieved_context.get("recall_explanation", {}),
            "omission_check": retrieved_context.get("omission_check", {}),
            "copyright_filter": retrieved_context.get("copyright_filter", {}),
            "retrieved_context": retrieved_context,
            "kg_context": kg_context,
        },
        metadata={
            "project_id": project_id,
            "workspace_path": workspace,
            "retrieval_backend": retrieved_context.get("retrieval_backend", ""),
            "retrieval_ranker": retrieved_context.get("ranker", ""),
            "retrieval_top_k": retrieved_context.get("top_k", top_k),
            "retrieval_query": retrieved_context.get("query", context_query),
            "context_profile": context_profile,
            "source_asset_path": _display_path(storage.root, target_file),
            "copyright_boundary": "generation context plan uses project-scoped abstract and original assets; raw sources and analysis reports are excluded",
            "run_metadata": run_metadata("context_build_plan", target_asset),
            **retrieval_metadata(retrieved_context),
        },
        references=filter_project_safe_references(
            storage,
            project_id,
            _dedupe([target_asset.id, _display_path(storage.root, target_file), *retrieved_context.get("source_asset_ids", []), *kg_context.get("source_asset_ids", [])]),
        ),
    )
    _ensure_valid(asset)
    path = storage.write_asset_auto(asset)
    _record_context_span(
        storage,
        trace_id=target_asset.id,
        span_type="context_bundle",
        name="create_context_build_plan",
        path=_display_path(storage.root, path),
        project_id=project_id,
        workspace_path=workspace,
        attributes={"target_path": _display_path(storage.root, target_file), "candidate_count": len(candidates), "kg_context_count": len(kg_context.get("items", [])) if isinstance(kg_context.get("items", []), list) else 0},
    )
    return {"path": _display_path(storage.root, path), "asset": asset.to_dict(), "validation": {"ok": True, "errors": []}}


def compare_context_bundles(
    storage: LocalStorage,
    left_path: str | Path,
    right_path: str | Path,
    *,
    persist: bool = True,
) -> dict[str, Any]:
    left_file = resolve_path(storage.root, left_path)
    right_file = resolve_path(storage.root, right_path)
    left = storage.read_asset(left_file)
    right = storage.read_asset(right_file)
    if left.type != "context_bundle" or right.type != "context_bundle":
        raise ValueError("left_path and right_path must both point to context_bundle assets")
    left_content = left.content if isinstance(left.content, dict) else {}
    right_content = right.content if isinstance(right.content, dict) else {}
    left_ids = set(str(item) for item in left_content.get("source_asset_ids", []) if str(item).strip())
    right_ids = set(str(item) for item in right_content.get("source_asset_ids", []) if str(item).strip())
    left_paths = _selected_paths(left_content)
    right_paths = _selected_paths(right_content)
    added = sorted(right_paths - left_paths)
    removed = sorted(left_paths - right_paths)
    shared = sorted(left_paths & right_paths)
    project_id = str(right.metadata.get("project_id") or left.metadata.get("project_id") or "local-system")
    diff = {
        "snapshot_kind": "context_bundle_diff",
        "left_bundle_id": left.id,
        "left_bundle_path": _display_path(storage.root, left_file),
        "right_bundle_id": right.id,
        "right_bundle_path": _display_path(storage.root, right_file),
        "added_asset_paths": added,
        "removed_asset_paths": removed,
        "shared_asset_paths": shared,
        "added_asset_ids": sorted(right_ids - left_ids),
        "removed_asset_ids": sorted(left_ids - right_ids),
        "token_delta": int(right_content.get("token_estimate", 0) or 0) - int(left_content.get("token_estimate", 0) or 0),
        "budget_status_change": {
            "from": _budget_status(left_content),
            "to": _budget_status(right_content),
        },
        "stale_warning_delta": {
            "from": len(left_content.get("stale_context_warnings", []) if isinstance(left_content.get("stale_context_warnings", []), list) else []),
            "to": len(right_content.get("stale_context_warnings", []) if isinstance(right_content.get("stale_context_warnings", []), list) else []),
        },
        "recommendation": _context_diff_recommendation(added, removed, right_content),
        "generated_at": utc_now(),
    }
    if not persist:
        return diff
    asset = ProjectMetricSnapshot(
        title=f"Context bundle diff {left.id[-8:]} -> {right.id[-8:]}",
        source=right.id,
        tags=["context-diff", diff["recommendation"]],
        content={
            "project_id": project_id,
            "snapshot_at": utc_now(),
            "throughput": {
                "snapshot_kind": "context_bundle_diff",
                "added": len(added),
                "removed": len(removed),
                "shared": len(shared),
                "token_delta": diff["token_delta"],
            },
            "quality": {
                "context_budget_from": diff["budget_status_change"]["from"],
                "context_budget_to": diff["budget_status_change"]["to"],
                "stale_warnings_to": diff["stale_warning_delta"]["to"],
            },
            "task_health": {"failed": 0, "running": 0, "waiting_handoff": 0, "dead_letters": 0},
            "agent_health": {"status": "not_applicable"},
            "storage_health": {"context_diff": diff},
            "recommendations": [diff["recommendation"]],
            "details": diff,
        },
        metadata={
            "project_id": project_id if project_id != "local-system" else "",
            "workspace_path": str(right.metadata.get("workspace_path") or left.metadata.get("workspace_path") or ""),
            "snapshot_kind": "context_bundle_diff",
            "left_bundle_path": diff["left_bundle_path"],
            "right_bundle_path": diff["right_bundle_path"],
        },
        references=filter_project_safe_references(
            storage,
            project_id,
            _dedupe([left.id, diff["left_bundle_path"], right.id, diff["right_bundle_path"], *added, *removed]),
        ),
    )
    _ensure_valid(asset)
    path = storage.write_asset_auto(asset)
    return {**diff, "path": _display_path(storage.root, path), "asset": asset.to_dict()}


def create_context_bundle(
    storage: LocalStorage,
    build_plan_path: str | Path,
    *,
    max_items: int | None = None,
    selected_asset_paths: list[str] | None = None,
    disabled_asset_paths: list[str] | None = None,
    priority_asset_paths: list[str] | None = None,
    final_confirmed: bool = False,
) -> dict[str, Any]:
    plan_file = resolve_path(storage.root, build_plan_path)
    plan = storage.read_asset(plan_file)
    if plan.type != "context_build_plan":
        raise ValueError("build_plan_path must point to a context_build_plan asset")
    content = plan.content
    candidates = [item for item in content.get("candidate_assets", []) if isinstance(item, dict)]
    manual_selection = _manual_selection(selected_asset_paths or [], disabled_asset_paths or [], priority_asset_paths or [], final_confirmed=final_confirmed)
    selected = _select_candidates(
        candidates,
        max_items=max_items,
        selected_paths=manual_selection["selected_asset_paths"],
        disabled_paths=manual_selection["disabled_asset_paths"],
        priority_paths=manual_selection["priority_asset_paths"],
    )
    policy_rejections = _selection_policy_rejections(storage, content, candidates, manual_selection)
    selected_ids = _dedupe([str(item.get("asset_id", "")) for item in selected if item.get("asset_id")])
    kg_context = content.get("kg_context", {}) if isinstance(content.get("kg_context", {}), dict) else {"items": [], "source_asset_ids": [], "recommendation": "kg_context_missing_from_plan"}
    kg_source_ids = [str(item) for item in kg_context.get("source_asset_ids", []) if str(item).strip()] if isinstance(kg_context.get("source_asset_ids", []), list) else []
    bucketed = _bucket_selected(selected)
    actual_context = _actual_context_text(bucketed, int(content.get("token_budget", {}).get("max_tokens", 4000)))
    token_estimate = _estimate_tokens(actual_context)
    budget_score = _context_budget_score(selected, content.get("candidate_assets", []), token_estimate, content.get("token_budget", _token_budget(4000)))
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
            "manual_selection": manual_selection,
            "stale_context_warnings": _stale_context_warnings(selected),
            "compressed_context": bucketed,
            "token_budget": content.get("token_budget", _token_budget(4000)),
            "token_estimate": token_estimate,
            "context_budget_score": budget_score,
            "actual_context": actual_context,
            "source_asset_ids": selected_ids,
            "retrieval_quality": content.get("retrieval_quality", {}),
            "recall_explanation": content.get("recall_explanation", {}),
            "omission_check": content.get("omission_check", {}),
            "copyright_filter": content.get("copyright_filter", {}),
            "policy_rejections": policy_rejections,
            "retrieved_context": content.get("retrieved_context", {}),
            "kg_context": kg_context,
            "kg_context_item_count": len(kg_context.get("items", []) if isinstance(kg_context.get("items", []), list) else []),
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
            "kg_context_source_asset_ids": kg_source_ids,
            "kg_context_item_count": len(kg_context.get("items", []) if isinstance(kg_context.get("items", []), list) else []),
            "token_estimate": token_estimate,
            "context_policy_rejection_count": len(policy_rejections),
            "copyright_boundary": "context bundle includes compressed summaries and project-owned/abstract assets only; raw source text is not included",
            "final_context_confirmed": bool(final_confirmed),
            "run_metadata": run_metadata("context_bundle", plan),
        },
        references=filter_project_safe_references(
            storage,
            project_id,
            _dedupe([plan.id, _display_path(storage.root, plan_file), str(content.get("target_asset_id", "")), *selected_ids, *kg_source_ids]),
        ),
    )
    _ensure_valid(asset)
    path = storage.write_asset_auto(asset)
    report = _create_rag_quality_report(storage, plan, plan_file, path, asset.to_dict(), budget_score)
    _attach_quality_report_to_bundle(storage, path, report)
    bundle_data = storage.read_json(path)
    _record_context_span(
        storage,
        trace_id=str(content.get("target_asset_id") or plan.id),
        span_type="context_bundle",
        name="create_context_bundle",
        path=_display_path(storage.root, path),
        project_id=project_id,
        workspace_path=workspace_path,
        attributes={"build_plan_path": _display_path(storage.root, plan_file), "selected_count": len(selected), "token_estimate": token_estimate, "budget_status": budget_score.get("status", "")},
    )
    return {"path": _display_path(storage.root, path), "asset": bundle_data, "rag_quality_report": report, "validation": {"ok": True, "errors": []}}


def list_context_assets(storage: LocalStorage, *, project_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in storage.list_json("contexts"):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") not in {"context_build_plan", "context_bundle", "rag_quality_report"}:
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
                "context_profile": content.get("context_profile", metadata.get("context_profile", "")),
                "token_estimate": content.get("token_estimate", metadata.get("token_estimate", 0)),
                "source_count": len(content.get("source_asset_ids", []) if isinstance(content.get("source_asset_ids", []), list) else []),
                "candidate_count": len(content.get("candidate_assets", []) if isinstance(content.get("candidate_assets", []), list) else []),
                "candidate_assets": content.get("candidate_assets", []) if isinstance(content.get("candidate_assets", []), list) else [],
                "selected_assets": content.get("selected_assets", []) if isinstance(content.get("selected_assets", []), list) else [],
                "manual_selection": content.get("manual_selection", {}) if isinstance(content.get("manual_selection", {}), dict) else {},
                "stale_context_warnings": content.get("stale_context_warnings", []) if isinstance(content.get("stale_context_warnings", []), list) else [],
                "actual_context": content.get("actual_context", ""),
                "context_budget_score": content.get("context_budget_score", {}) if isinstance(content.get("context_budget_score", {}), dict) else {},
                "quality_recommendation": content.get("recommendation", content.get("context_budget_score", {}).get("status", "")) if isinstance(content.get("context_budget_score", {}), dict) else content.get("recommendation", ""),
                "updated_at": data.get("updated_at", ""),
                "summary": _compact(str(content.get("actual_context") or content.get("query") or ""), 180),
            }
        )
    return sorted(rows, key=lambda row: row.get("updated_at", ""), reverse=True)[:limit]


def _default_query(asset: BaseAsset) -> str:
    return f"{asset.type} {asset.title} {json.dumps(asset.content, ensure_ascii=False, sort_keys=True)[:900]}"


def _context_profile_policy(profile: str) -> dict[str, Any]:
    key = (profile or "chapter_generation").strip().lower().replace("-", "_")
    policies = {
        "chapter_generation": {
            "required_buckets": ["characters", "worldbuilding", "previous_summaries", "knowledge", "foreshadowing", "materials"],
            "default_top_k": 10,
            "risk_gate": "block high copyright risk and raw analysis reports",
        },
        "review": {
            "required_buckets": ["quality", "style", "previous_summaries", "drafts"],
            "default_top_k": 8,
            "risk_gate": "include rubric assets and final draft lineage",
        },
        "revision": {
            "required_buckets": ["reviews", "style", "quality", "previous_summaries"],
            "default_top_k": 8,
            "risk_gate": "require review/revision lineage before applying edits",
        },
        "analysis_conversion": {
            "required_buckets": ["knowledge", "materials", "templates"],
            "default_top_k": 6,
            "risk_gate": "analysis reports must stay abstract-only until human approved",
        },
    }
    return {"profile": key, **policies.get(key, policies["chapter_generation"])}


def _selected_paths(content: dict[str, Any]) -> set[str]:
    rows = content.get("selected_assets", []) if isinstance(content.get("selected_assets", []), list) else []
    return {str(item.get("path", "")) for item in rows if isinstance(item, dict) and str(item.get("path", "")).strip()}


def _budget_status(content: dict[str, Any]) -> str:
    score = content.get("context_budget_score", {}) if isinstance(content.get("context_budget_score", {}), dict) else {}
    return str(score.get("status", "unknown"))


def _context_diff_recommendation(added: list[str], removed: list[str], right_content: dict[str, Any]) -> str:
    budget = _budget_status(right_content)
    warnings = right_content.get("stale_context_warnings", []) if isinstance(right_content.get("stale_context_warnings", []), list) else []
    if budget in {"over_budget", "empty"}:
        return "block_until_context_fixed"
    if removed or len(warnings) >= 3:
        return "human_confirm_before_generation"
    if added:
        return "review_added_sources"
    return "no_material_change"


def _record_context_span(
    storage: LocalStorage,
    *,
    trace_id: str,
    span_type: str,
    name: str,
    path: str,
    project_id: str,
    workspace_path: str,
    attributes: dict[str, Any],
) -> None:
    try:
        record_trace_span(
            storage,
            trace_id=trace_id or path,
            span_type=span_type,
            name=name,
            status="succeeded",
            attributes={**attributes, "path": path},
            references=[path],
            project_id=project_id,
            workspace_path=workspace_path,
        )
    except Exception:
        return


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
        "copyright": item.get("copyright", {}) if isinstance(item.get("copyright", {}), dict) else {},
        "recall_explanation": item.get("recall_explanation", {}) if isinstance(item.get("recall_explanation", {}), dict) else {},
        "selected_by_default": str(item.get("type", "")) not in RAW_OR_REPORT_TYPES,
    }


def _candidate_payloads(items: Any) -> list[dict[str, Any]]:
    return [_candidate_payload(item) for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _kg_context_for_plan(
    storage: LocalStorage,
    *,
    target_path: str | Path,
    query: str,
    project_id: str | None,
    workspace_path: str | None,
    limit: int,
) -> dict[str, Any]:
    try:
        return build_novel_kg_context(
            storage,
            target_path=target_path,
            query=query,
            project_id=project_id,
            workspace_path=workspace_path,
            limit=limit,
        )
    except Exception as exc:
        return {"items": [], "source_asset_ids": [], "recommendation": "kg_context_unavailable", "error": f"{type(exc).__name__}: {exc}"}


def _merge_context_candidates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_path: dict[str, dict[str, Any]] = {}
    for item in items:
        path = str(item.get("path", ""))
        if not path:
            continue
        existing = by_path.get(path)
        if not existing or float(item.get("score", 0) or 0) > float(existing.get("score", 0) or 0):
            if existing:
                item = {**item, "categories": _merged_candidate_categories(existing, item)}
            by_path[path] = item
        elif existing:
            existing["categories"] = _merged_candidate_categories(existing, item)
    return sorted(by_path.values(), key=lambda row: -float(row.get("score", 0) or 0))


def _merged_candidate_categories(left: dict[str, Any], right: dict[str, Any]) -> list[str]:
    categories = left.get("categories", []) if isinstance(left.get("categories", []), list) else []
    more = right.get("categories", []) if isinstance(right.get("categories", []), list) else []
    return _dedupe([*[str(value) for value in categories], *[str(value) for value in more]])


def _rag_copyright_exclusions(retrieved_context: dict[str, Any]) -> list[dict[str, str]]:
    copyright_filter = retrieved_context.get("copyright_filter", {}) if isinstance(retrieved_context.get("copyright_filter", {}), dict) else {}
    filtered = copyright_filter.get("filtered_assets", []) if isinstance(copyright_filter.get("filtered_assets", []), list) else []
    exclusions: list[dict[str, str]] = []
    for item in filtered:
        if not isinstance(item, dict):
            continue
        exclusions.append(
            {
                "asset_id": str(item.get("asset_id", "")),
                "path": str(item.get("path", "")),
                "type": str(item.get("type", "")),
                "reason": str(item.get("reason", "copyright risk filter")),
            }
        )
    return exclusions


def _dedupe_exclusions(items: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    result: list[dict[str, str]] = []
    for item in items:
        key = (str(item.get("asset_id", "")), str(item.get("path", "")))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


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


def _context_budget_score(
    selected: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    token_estimate: int,
    token_budget: dict[str, Any],
) -> dict[str, Any]:
    max_tokens = int(token_budget.get("max_tokens", 4000)) if isinstance(token_budget, dict) else 4000
    response_reserved = int(token_budget.get("reserved_for_response", max(512, int(max_tokens * 0.35)))) if isinstance(token_budget, dict) else max(512, int(max_tokens * 0.35))
    prompt_reserved = int(token_budget.get("reserved_for_prompt", max(128, int(max_tokens * 0.15)))) if isinstance(token_budget, dict) else max(128, int(max_tokens * 0.15))
    usable_tokens = max(max_tokens - response_reserved - prompt_reserved, 1)
    usage_ratio = token_estimate / usable_tokens
    selected_count = len(selected)
    candidate_count = len(candidates)
    if usage_ratio > 1.0:
        score = max(0, int(100 - ((usage_ratio - 1.0) * 120)))
        status = "over_budget"
    elif usage_ratio < 0.15 and candidate_count > selected_count:
        score = 65
        status = "underfilled"
    elif selected_count == 0:
        score = 30
        status = "empty"
    else:
        score = int(max(70, 100 - abs(usage_ratio - 0.72) * 45))
        status = "healthy"
    return {
        "score": max(0, min(100, score)),
        "status": status,
        "max_tokens": max_tokens,
        "usable_tokens": usable_tokens,
        "token_estimate": token_estimate,
        "usage_ratio": round(usage_ratio, 4),
        "selected_count": selected_count,
        "candidate_count": candidate_count,
        "recommendation": _budget_recommendation(status),
    }


def _budget_recommendation(status: str) -> str:
    if status == "over_budget":
        return "Reduce selected context or raise token budget before chapter generation."
    if status == "underfilled":
        return "More eligible context is available than selected; consider increasing max_items or budget."
    if status == "empty":
        return "No eligible context was selected; bind project assets before generation."
    return "Context budget is within the healthy operating range."


def _create_rag_quality_report(
    storage: LocalStorage,
    plan: BaseAsset,
    plan_file: Path,
    bundle_path: Path,
    bundle_data: dict[str, Any],
    budget_score: dict[str, Any],
) -> dict[str, Any]:
    content = bundle_data.get("content", {}) if isinstance(bundle_data.get("content", {}), dict) else {}
    metadata = bundle_data.get("metadata", {}) if isinstance(bundle_data.get("metadata", {}), dict) else {}
    omission = content.get("omission_check", {}) if isinstance(content.get("omission_check", {}), dict) else {}
    copyright_filter = content.get("copyright_filter", {}) if isinstance(content.get("copyright_filter", {}), dict) else {}
    policy_rejections = content.get("policy_rejections", []) if isinstance(content.get("policy_rejections", []), list) else []
    recommendation = _rag_recommendation(omission, copyright_filter, budget_score, policy_rejections)
    selected_ids = content.get("source_asset_ids", []) if isinstance(content.get("source_asset_ids", []), list) else []
    asset = RagQualityReport(
        title=f"RAG quality report for {content.get('target_asset_type', 'asset')} {content.get('target_asset_id', '')}",
        source=plan.id,
        tags=["rag", "quality", recommendation, str(content.get("retrieval_backend", ""))],
        content={
            "target_asset_id": content.get("target_asset_id", ""),
            "target_asset_type": content.get("target_asset_type", ""),
            "target_path": content.get("target_path", ""),
            "context_build_plan_id": plan.id,
            "context_build_plan_path": _display_path(storage.root, plan_file),
            "context_bundle_id": bundle_data.get("id", ""),
            "context_bundle_path": _display_path(storage.root, bundle_path),
            "retrieval_backend": content.get("retrieval_backend", ""),
            "ranker": content.get("ranker", ""),
            "query": content.get("query", ""),
            "recall_explanation": content.get("recall_explanation", {}),
            "omission_check": omission,
            "copyright_filter": copyright_filter,
            "policy_rejections": policy_rejections,
            "manual_policy_rejections": [item for item in policy_rejections if isinstance(item, dict) and item.get("requested_by")],
            "context_budget_score": budget_score,
            "selected_asset_ids": selected_ids,
            "recommendation": recommendation,
        },
        metadata={
            "project_id": metadata.get("project_id", ""),
            "workspace_path": metadata.get("workspace_path", ""),
            "context_build_plan_path": _display_path(storage.root, plan_file),
            "context_bundle_path": _display_path(storage.root, bundle_path),
            "retrieval_backend": content.get("retrieval_backend", ""),
            "quality_score": budget_score.get("score", 0),
            "recommendation": recommendation,
            "run_metadata": run_metadata("rag_quality_report", plan),
        },
        references=filter_project_safe_references(
            storage,
            str(metadata.get("project_id", "")),
            _dedupe([plan.id, _display_path(storage.root, plan_file), str(bundle_data.get("id", "")), _display_path(storage.root, bundle_path), *selected_ids]),
        ),
    )
    _ensure_valid(asset)
    path = storage.write_asset_auto(asset)
    return {"path": _display_path(storage.root, path), "asset": asset.to_dict()}


def _attach_quality_report_to_bundle(storage: LocalStorage, bundle_path: Path, report: dict[str, Any]) -> None:
    data = storage.read_json(bundle_path)
    if not isinstance(data, dict):
        return
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    report_asset = report.get("asset", {}) if isinstance(report.get("asset", {}), dict) else {}
    content["rag_quality_report_id"] = str(report_asset.get("id", ""))
    content["rag_quality_report_path"] = str(report.get("path", ""))
    metadata["rag_quality_report_id"] = str(report_asset.get("id", ""))
    metadata["rag_quality_report_path"] = str(report.get("path", ""))
    metadata["rag_quality_recommendation"] = str(report_asset.get("content", {}).get("recommendation", "")) if isinstance(report_asset.get("content", {}), dict) else ""
    data["content"] = content
    data["metadata"] = metadata
    storage.write_json(bundle_path, data)


def _rag_recommendation(
    omission: dict[str, Any],
    copyright_filter: dict[str, Any],
    budget_score: dict[str, Any],
    policy_rejections: list[dict[str, Any]] | None = None,
) -> str:
    if copyright_filter.get("status") == "blocked" or budget_score.get("status") in {"over_budget", "empty"}:
        return "block"
    if any(item.get("requested_by") for item in policy_rejections or [] if isinstance(item, dict)):
        return "revise"
    if omission.get("missing_count", 0) >= 3 or budget_score.get("status") == "underfilled":
        return "revise"
    if omission.get("missing_count", 0):
        return "pass_with_warnings"
    return "pass"


def _select_candidates(
    candidates: list[dict[str, Any]],
    *,
    max_items: int | None,
    selected_paths: list[str] | None = None,
    disabled_paths: list[str] | None = None,
    priority_paths: list[str] | None = None,
) -> list[dict[str, Any]]:
    disabled = set(disabled_paths or [])
    explicit_selected = set(selected_paths or [])
    priority = list(priority_paths or [])
    selected = [
        candidate
        for candidate in candidates
        if str(candidate.get("path", "")) not in disabled
        and (candidate.get("selected_by_default", True) or str(candidate.get("path", "")) in explicit_selected)
        and str(candidate.get("type", "")) not in RAW_OR_REPORT_TYPES
        and _candidate_allowed_by_copyright(candidate)
    ]
    if priority:
        order = {path: index for index, path in enumerate(priority)}
        selected.sort(key=lambda item: (order.get(str(item.get("path", "")), len(order) + 1000), -float(item.get("score", 0) or 0)))
    if max_items is not None and max_items > 0:
        return selected[:max_items]
    return selected


def _manual_selection(selected_paths: list[str], disabled_paths: list[str], priority_paths: list[str], *, final_confirmed: bool) -> dict[str, Any]:
    return {
        "selected_asset_paths": _dedupe(selected_paths),
        "disabled_asset_paths": _dedupe(disabled_paths),
        "priority_asset_paths": _dedupe(priority_paths),
        "final_confirmed": bool(final_confirmed),
        "policy": "manual selections override default inclusion only for eligible non-raw, non-high-risk context assets",
    }


def _stale_context_warnings(selected: list[dict[str, Any]]) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    for item in selected:
        score = float(item.get("score", 0) or 0)
        if score <= 0:
            warnings.append({"path": str(item.get("path", "")), "reason": "fallback scan item has no semantic retrieval score; verify relevance before generation"})
        if str(item.get("type", "")) in {"draft_chapter", "chapter_plan", "outline"} and "previous_summaries" in item.get("categories", []):
            warnings.append({"path": str(item.get("path", "")), "reason": "narrative context may be stale after recent edits; confirm before sending final context"})
    return warnings[:40]


def _candidate_allowed_by_copyright(candidate: dict[str, Any]) -> bool:
    copyright = candidate.get("copyright", {}) if isinstance(candidate.get("copyright", {}), dict) else {}
    if copyright.get("eligible") is False:
        return False
    return str(copyright.get("risk_level", "unknown")) != "high"


def _selection_policy_rejections(
    storage: LocalStorage,
    plan_content: dict[str, Any],
    candidates: list[dict[str, Any]],
    manual_selection: dict[str, Any],
) -> list[dict[str, Any]]:
    candidate_by_path = {str(item.get("path", "")): item for item in candidates if isinstance(item, dict) and str(item.get("path", "")).strip()}
    exclusion_by_path = _plan_exclusion_index(plan_content)
    requested_by_path: dict[str, list[str]] = {}
    for field, label in [("selected_asset_paths", "manual_selected"), ("priority_asset_paths", "manual_priority")]:
        for path in manual_selection.get(field, []) if isinstance(manual_selection.get(field, []), list) else []:
            path_text = str(path).strip()
            if not path_text:
                continue
            requested_by_path.setdefault(path_text, []).append(label)
    disabled = {str(path) for path in manual_selection.get("disabled_asset_paths", []) if str(path).strip()} if isinstance(manual_selection.get("disabled_asset_paths", []), list) else set()
    rejections: list[dict[str, Any]] = []
    seen: set[str] = set()

    for path, candidate in candidate_by_path.items():
        if path in disabled:
            continue
        if str(candidate.get("type", "")) in RAW_OR_REPORT_TYPES:
            rejections.append(_candidate_rejection(candidate, reason="raw source or analysis report cannot enter generation context", requested_by=requested_by_path.get(path, [])))
            seen.add(path)
        elif not _candidate_allowed_by_copyright(candidate):
            copyright = candidate.get("copyright", {}) if isinstance(candidate.get("copyright", {}), dict) else {}
            rejections.append(_candidate_rejection(candidate, reason=str(copyright.get("reason") or "copyright policy rejected candidate"), requested_by=requested_by_path.get(path, [])))
            seen.add(path)

    for path, requested_by in requested_by_path.items():
        if path in disabled or path in seen:
            continue
        if path in exclusion_by_path:
            item = exclusion_by_path[path]
            rejections.append(
                {
                    "path": path,
                    "asset_id": str(item.get("asset_id", "")),
                    "type": str(item.get("type", "")),
                    "title": str(item.get("title", "")),
                    "reason": str(item.get("reason") or "generation context policy excluded this asset"),
                    "signals": item.get("signals", []) if isinstance(item.get("signals", []), list) else [],
                    "requested_by": requested_by,
                }
            )
            seen.add(path)
            continue
        data = _read_asset_policy_candidate(storage, path)
        if data:
            policy = generation_context_policy(data)
            if not policy["eligible"]:
                rejections.append(
                    {
                        "path": path,
                        "asset_id": str(data.get("id", "")),
                        "type": str(data.get("type", "")),
                        "title": str(data.get("title") or data.get("name") or ""),
                        "reason": policy["reason"],
                        "signals": policy["signals"],
                        "requested_by": requested_by,
                    }
                )
                seen.add(path)
                continue
        rejections.append(
            {
                "path": path,
                "asset_id": "",
                "type": str(data.get("type", "")) if data else "",
                "title": str(data.get("title") or data.get("name") or "") if data else "",
                "reason": "manual selection was not present in the audited eligible candidate set",
                "signals": ["not_in_candidate_set"],
                "requested_by": requested_by,
            }
        )
        seen.add(path)

    return rejections[:80]


def _plan_exclusion_index(plan_content: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: list[Any] = []
    rows.extend(plan_content.get("exclusions", []) if isinstance(plan_content.get("exclusions", []), list) else [])
    copyright_filter = plan_content.get("copyright_filter", {}) if isinstance(plan_content.get("copyright_filter", {}), dict) else {}
    rows.extend(copyright_filter.get("filtered_assets", []) if isinstance(copyright_filter.get("filtered_assets", []), list) else [])
    return {str(item.get("path", "")): item for item in rows if isinstance(item, dict) and str(item.get("path", "")).strip()}


def _candidate_rejection(candidate: dict[str, Any], *, reason: str, requested_by: list[str]) -> dict[str, Any]:
    copyright = candidate.get("copyright", {}) if isinstance(candidate.get("copyright", {}), dict) else {}
    return {
        "path": str(candidate.get("path", "")),
        "asset_id": str(candidate.get("asset_id", "")),
        "type": str(candidate.get("type", "")),
        "title": str(candidate.get("title", "")),
        "reason": reason,
        "signals": copyright.get("signals", []) if isinstance(copyright.get("signals", []), list) else [],
        "requested_by": requested_by,
    }


def _read_asset_policy_candidate(storage: LocalStorage, path: str) -> dict[str, Any] | None:
    try:
        data = storage.read_json(resolve_path(storage.root, path))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


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

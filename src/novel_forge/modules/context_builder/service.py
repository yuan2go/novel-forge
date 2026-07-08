from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from novel_forge.core.constants import DATA_DIRS
from novel_forge.core.ids import utc_now
from novel_forge.modules.common import resolve_path, run_metadata
from novel_forge.modules.materials import record_material_usage_event
from novel_forge.modules.mkaos import build_knowledge_pack, load_context_governance_binding_application, record_usage_event
from novel_forge.modules.mkaos.pack_policy import (
    mkaos_pack_warning_fallback,
    resolve_mkaos_pack_policy,
    should_block_mkaos_pack_failure,
    validate_mkaos_pack_result,
)
from novel_forge.modules.novel_kg import build_novel_kg_context
from novel_forge.modules.os_envelope import is_production_environment
from novel_forge.modules.production_context import filter_project_safe_references, project_scope_from_asset
from novel_forge.modules.runtime_ledger import record_trace_span
from novel_forge.modules.source_intake import run_source_governance_runtime_gate
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

BASE_FORBIDDEN_CONTEXT_TYPES = RAW_OR_REPORT_TYPES | {
    "source_chunk",
    "parallel_pair",
    "operation_raw_output_segment",
}

FLOW_CONTEXT_PROFILES = {
    "topic": "topic",
    "topic_development": "topic",
    "world": "worldbuilding",
    "worldbuilding": "worldbuilding",
    "character": "character",
    "character_design": "character",
    "analysis": "review",
    "decompose": "review",
    "convert": "review",
    "outline": "outline",
    "chapter_plan": "chapter_outline",
    "chapter_outline": "chapter_outline",
    "draft": "prose",
    "prose": "prose",
    "review": "review",
    "revision": "revision",
    "editor_patch": "revision",
    "recap": "recap",
    "publish": "publish",
    "publish_gate": "publish",
    "feedback": "feedback",
    "feedback_backflow": "feedback",
}

KNOWLEDGE_CONTEXT_CONTRACT_VERSION = "knowledge-context-contract-v1"

CONTEXT_TYPE_BUCKETS = {
    "character_card": ["characters"],
    "character_mechanism": ["characters", "material_cards"],
    "world_bible": ["worldbuilding"],
    "continuity_bible": ["worldbuilding", "foreshadowing"],
    "foreshadowing_thread": ["foreshadowing"],
    "power_scale_rule": ["worldbuilding"],
    "platform_profile": ["material_cards"],
    "genre_market_profile": ["material_cards"],
    "genre_profile": ["material_cards"],
    "subgenre_mechanic": ["material_cards", "writing_templates"],
    "genre_strategy_pack": ["material_cards", "writing_templates", "foreshadowing"],
    "platform_genre_fit": ["material_cards"],
    "genre_template_binding": ["writing_templates", "material_cards"],
    "creative_strategy_profile": ["material_cards", "writing_templates", "foreshadowing"],
    "quality_standard_profile": ["writing_templates"],
    "quality_rubric_pack": ["writing_templates"],
    "opening_3_report": ["previous_summaries"],
    "golden_10_report": ["previous_summaries"],
    "volume_30_report": ["previous_summaries"],
    "longform_100_report": ["previous_summaries"],
    "quality_regression_report": ["previous_summaries"],
    "style_profile": ["writing_templates"],
    "style_fingerprint": ["previous_summaries"],
    "style_generation_policy": ["writing_templates"],
    "style_review_rule": ["writing_templates"],
    "style_drift_report": ["previous_summaries"],
    "style_blend_preset": ["writing_templates"],
    "fantasy_power_scale_report": ["worldbuilding", "previous_summaries"],
    "mystery_evidence_chain_report": ["foreshadowing", "previous_summaries"],
    "romance_relationship_state_report": ["characters", "previous_summaries"],
    "historical_faction_network_report": ["worldbuilding", "previous_summaries"],
    "sci_fi_rule_consistency_report": ["worldbuilding", "previous_summaries"],
    "horror_rule_contamination_report": ["foreshadowing", "previous_summaries"],
    "outline": ["previous_summaries"],
    "outline_version": ["previous_summaries"],
    "chapter_plan": ["previous_summaries"],
    "chapter_plan_version": ["previous_summaries"],
    "draft_chapter": ["previous_summaries"],
    "revision_plan": ["previous_summaries"],
    "longform_recap_report": ["previous_summaries"],
    "knowledge_card": ["knowledge_cards"],
    "material_card": ["material_cards"],
    "commercial_pattern": ["material_cards"],
    "narrative_pattern": ["material_cards"],
    "conflict_pattern": ["material_cards"],
    "emotion_curve": ["material_cards"],
    "hook_pattern": ["foreshadowing", "material_cards"],
    "writing_template": ["writing_templates", "material_cards"],
    "craft_template": ["writing_templates", "material_cards"],
}


def create_context_build_plan(
    storage: LocalStorage,
    target_path: str | Path,
    *,
    query: str = "",
    top_k: int = 8,
    token_budget: int = 4000,
    backend: str = "auto",
    retrieval_backend: str | None = None,
    memory_levels: list[str] | None = None,
    kg_context_enabled: bool = True,
    quality_memory_enabled: bool = True,
    context_profile: str = "chapter_generation",
    workspace_path: str | None = None,
    environment: str = "",
) -> dict[str, Any]:
    target_file = resolve_path(storage.root, target_path)
    target_asset = storage.read_asset(target_file)
    project = project_scope_from_asset(storage, target_asset, input_path=target_file, workspace_path=workspace_path)
    context_query = query or _default_query(target_asset)
    resolved_backend = retrieval_backend or backend
    resolved_memory_levels = _memory_levels(memory_levels)
    retrieved_context = build_rag_context(
        storage,
        target_asset,
        input_path=target_file,
        query=context_query,
        top_k=top_k,
        backend=resolved_backend,
        memory_levels=resolved_memory_levels,
        quality_memory=quality_memory_enabled,
    )
    project_id = str(project.get("project_id", ""))
    workspace = str(project.get("workspace_path", "") or workspace_path or "")
    kg_context = (
        _kg_context_for_plan(
            storage,
            target_path=target_file,
            query=context_query,
            project_id=project_id or None,
            workspace_path=workspace or None,
            limit=max(4, int(top_k)),
        )
        if kg_context_enabled
        else {"items": [], "source_asset_ids": [], "recommendation": "kg_context_disabled"}
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
            "environment": environment,
            "context_profile_policy": profile_policy,
            "ranker": retrieved_context.get("ranker", ""),
            "requested_backend": retrieved_context.get("requested_backend", resolved_backend),
            "retrieval_backend": retrieved_context.get("retrieval_backend", ""),
            "retrieval_backend_policy": {
                "supported": ["pgvector", "qdrant", "local", "hybrid"],
                "requested": resolved_backend,
                "actual": retrieved_context.get("retrieval_backend", ""),
                "auto_allowed": True,
            },
            "backend_attempts": retrieved_context.get("backend_attempts", []),
            "memory_levels": retrieved_context.get("memory_levels", resolved_memory_levels),
            "memory_policy": {
                "enabled": True,
                "levels": retrieved_context.get("memory_levels", resolved_memory_levels),
                "quality_memory": bool(quality_memory_enabled),
                "source": "long_memory+pgvector_hybrid_retrieval",
            },
            "kg_context_enabled": bool(kg_context_enabled),
            "quality_memory_enabled": bool(quality_memory_enabled),
            "token_budget": _token_budget(token_budget),
            "selection_policy": {
                "project_scoped": bool(project_id or workspace),
                "allowed_buckets": list(retrieved_context.get("buckets", {}).keys()),
                "exclude_raw_sources": True,
                "exclude_analysis_reports_from_generation_rag": True,
                "exclude_high_copyright_risk": True,
                "stage_profile_enforced": True,
                "allowed_asset_types": profile_policy.get("allowed_asset_types", []),
                "forbidden_asset_types": profile_policy.get("forbidden_asset_types", []),
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
            "environment": environment,
            "retrieval_ranker": retrieved_context.get("ranker", ""),
            "retrieval_top_k": retrieved_context.get("top_k", top_k),
            "retrieval_query": retrieved_context.get("query", context_query),
            "context_profile": context_profile,
            "memory_levels": retrieved_context.get("memory_levels", resolved_memory_levels),
            "kg_context_enabled": bool(kg_context_enabled),
            "quality_memory_enabled": bool(quality_memory_enabled),
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
    environment = str(plan.metadata.get("environment") or content.get("environment") or "")
    candidates = [
        _enrich_candidate_source_eligibility(storage, item)
        for item in content.get("candidate_assets", [])
        if isinstance(item, dict)
    ]
    manual_selection = _manual_selection(selected_asset_paths or [], disabled_asset_paths or [], priority_asset_paths or [], final_confirmed=final_confirmed)
    selected = _select_candidates(
        candidates,
        max_items=max_items,
        selected_paths=manual_selection["selected_asset_paths"],
        disabled_paths=manual_selection["disabled_asset_paths"],
        priority_paths=manual_selection["priority_asset_paths"],
        profile_policy=content.get("context_profile_policy", {}) if isinstance(content.get("context_profile_policy", {}), dict) else {},
        environment=environment,
    )
    profile_policy = content.get("context_profile_policy", {}) if isinstance(content.get("context_profile_policy", {}), dict) else {}
    policy_rejections = _selection_policy_rejections(storage, content, candidates, manual_selection, profile_policy=profile_policy, environment=environment)
    selected_ids = _dedupe([str(item.get("asset_id", "")) for item in selected if item.get("asset_id")])
    kg_context = content.get("kg_context", {}) if isinstance(content.get("kg_context", {}), dict) else {"items": [], "source_asset_ids": [], "recommendation": "kg_context_missing_from_plan"}
    kg_source_ids = [str(item) for item in kg_context.get("source_asset_ids", []) if str(item).strip()] if isinstance(kg_context.get("source_asset_ids", []), list) else []
    bucketed = _bucket_selected(selected)
    bundle_omission = _bundle_omission_check(str(content.get("target_asset_type", "")), bucketed, content.get("omission_check", {}))
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
            "retrieval_backend_policy": content.get("retrieval_backend_policy", {}),
            "memory_levels": content.get("memory_levels", []),
            "memory_policy": content.get("memory_policy", {}),
            "kg_context_enabled": bool(content.get("kg_context_enabled", True)),
            "quality_memory_enabled": bool(content.get("quality_memory_enabled", True)),
            "context_profile": content.get("context_profile", ""),
            "environment": environment,
            "context_profile_policy": profile_policy,
            "stage_context_contract": _stage_context_contract(profile_policy),
            "source_policy": _stage_source_policy(profile_policy),
            "source_isolation": _stage_source_isolation(profile_policy),
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
            "retrieval_omission_check": content.get("omission_check", {}),
            "omission_check": bundle_omission,
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
            "memory_levels": content.get("memory_levels", []),
            "kg_context_enabled": bool(content.get("kg_context_enabled", True)),
            "quality_memory_enabled": bool(content.get("quality_memory_enabled", True)),
            "context_profile": content.get("context_profile", ""),
            "stage_context_contract_version": _stage_context_contract(profile_policy)["contract_version"],
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
    usage_feedback = _record_context_usage_feedback(
        storage,
        bundle_path=_display_path(storage.root, path),
        bundle_data=bundle_data,
        plan=plan,
        selected=selected,
        plan_content=content,
        project_id=project_id,
        workspace_path=workspace_path,
    )
    if usage_feedback["event_count"]:
        bundle_content = bundle_data.get("content", {}) if isinstance(bundle_data.get("content", {}), dict) else {}
        bundle_content["usage_feedback_events"] = usage_feedback["events"]
        bundle_content["usage_feedback_event_count"] = usage_feedback["event_count"]
        bundle_data["content"] = bundle_content
        bundle_metadata = bundle_data.get("metadata", {}) if isinstance(bundle_data.get("metadata", {}), dict) else {}
        bundle_metadata["usage_feedback_event_count"] = usage_feedback["event_count"]
        bundle_data["metadata"] = bundle_metadata
        storage.write_json(path, bundle_data)
    approval_requests = _create_context_approval_requests(
        storage,
        bundle_path=_display_path(storage.root, path),
        plan_path=_display_path(storage.root, plan_file),
        project_id=project_id,
        workspace_path=workspace_path,
        policy_rejections=policy_rejections,
    )
    if approval_requests:
        content = bundle_data.get("content", {}) if isinstance(bundle_data.get("content", {}), dict) else {}
        content["approval_requests"] = approval_requests
        content["approval_request_count"] = len(approval_requests)
        content["context_policy_requires_operator_review"] = True
        bundle_data["content"] = content
        metadata = bundle_data.get("metadata", {}) if isinstance(bundle_data.get("metadata", {}), dict) else {}
        metadata["approval_request_count"] = len(approval_requests)
        bundle_data["metadata"] = metadata
        storage.write_json(path, bundle_data)
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


def build_flow_context_bundle(
    storage: LocalStorage,
    target_path: str | Path,
    *,
    flow: str,
    project_id: str = "",
    workspace_path: str = "",
    genre: str = "",
    platform: str = "",
    chapter_id: str = "",
    current_goal: str = "",
    query: str = "",
    top_k: int = 8,
    token_budget: int = 4000,
    context_profile: str | None = None,
    existing_context_bundle_path: str | Path | None = None,
    source_policy: dict[str, Any] | None = None,
    environment: str = "",
    os_envelope: dict[str, Any] | None = None,
    selector_governance_report_path: str | Path | None = None,
    selector_governance_binding_application_report_path: str | Path | None = None,
) -> dict[str, Any]:
    target_file = resolve_path(storage.root, target_path)
    target_asset = storage.read_asset(target_file)
    target_metadata = target_asset.metadata if isinstance(target_asset.metadata, dict) else {}
    profile = context_profile or FLOW_CONTEXT_PROFILES.get(flow, "chapter_generation")
    mkaos_flow = _mkaos_flow_for_context(flow)
    policy = dict(source_policy or {})
    policy.update({
        "source_chunk_raw_text_allowed": False,
        "runtime_assets_in_generation_rag_allowed": False,
        "exclude_raw_sources": True,
    })
    if is_production_environment(environment) and selector_governance_report_path and not selector_governance_binding_application_report_path:
        raise ValueError("production selector governance binding requires selector_governance_binding_application_report_path")
    if existing_context_bundle_path:
        bundle_file = resolve_path(storage.root, existing_context_bundle_path)
        bundle_asset = storage.read_asset(bundle_file)
        if bundle_asset.type != "context_bundle":
            raise ValueError("existing_context_bundle_path must point to a context_bundle asset")
        context_bundle = {"path": _display_path(storage.root, bundle_file), "asset": bundle_asset.to_dict()}
        build_plan_path = str(bundle_asset.content.get("build_plan_path", ""))
        context_plan = {"path": build_plan_path, "asset": storage.read_asset(resolve_path(storage.root, build_plan_path)).to_dict() if build_plan_path else {"id": "", "content": {}}}
    else:
        context_plan = create_context_build_plan(
            storage,
            target_file,
            query=query,
            top_k=top_k,
            token_budget=token_budget,
            backend="auto",
            context_profile=profile,
            workspace_path=workspace_path or None,
            environment=environment,
        )
        context_bundle = create_context_bundle(storage, context_plan["path"])
        bundle_file = resolve_path(storage.root, context_bundle["path"])
    plan_asset = context_plan.get("asset", {}) if isinstance(context_plan.get("asset", {}), dict) else {}
    plan_metadata = plan_asset.get("metadata", {}) if isinstance(plan_asset.get("metadata", {}), dict) else {}
    bundle_asset = context_bundle.get("asset", {}) if isinstance(context_bundle.get("asset", {}), dict) else {}
    bundle_metadata = bundle_asset.get("metadata", {}) if isinstance(bundle_asset.get("metadata", {}), dict) else {}
    resolved_project_id = str(bundle_metadata.get("project_id") or plan_metadata.get("project_id") or target_metadata.get("project_id") or "")
    if (not project_id or project_id == "local-system") and resolved_project_id:
        project_id = resolved_project_id
    else:
        project_id = str(project_id or resolved_project_id or "")
    selector_governance_binding = _resolve_context_selector_governance_binding(
        storage,
        selector_governance_binding_application_report_path,
        selector_governance_report_path=selector_governance_report_path,
        project_id=project_id,
        environment=environment,
    )
    effective_selector_governance_report_path = selector_governance_binding.get("selector_governance_report_path") or str(selector_governance_report_path or "")
    pack_policy = resolve_mkaos_pack_policy(mkaos_flow, environment=environment)
    try:
        mkaos_pack = build_knowledge_pack(
            storage,
            {
                "flow": mkaos_flow,
                "task_id": f"{flow}-{project_id or 'local'}-{chapter_id or 'project'}",
                "project_id": project_id or "local-system",
                "workspace_path": workspace_path,
                "genre": genre,
                "platform": platform,
                "chapter_id": chapter_id,
                "current_goal": current_goal,
                "knowledge_budget": {"max_core_knowledge": 3 if mkaos_flow == "prose" else 8},
                "source_policy": policy,
                "environment": environment,
                "os_envelope": os_envelope or {},
                "selector_governance_report_path": effective_selector_governance_report_path,
            },
        )
    except Exception as exc:
        if should_block_mkaos_pack_failure(pack_policy, exc):
            raise ValueError(f"MKAOS pack build failed in production for {flow}: {exc}") from exc
        mkaos_pack = mkaos_pack_warning_fallback(
            storage,
            flow=mkaos_flow,
            project_id=project_id or "local-system",
            workspace_path=workspace_path,
            target_path=target_file,
            policy=pack_policy,
            warning=f"MKAOS pack build warning fallback for {flow}: {exc}",
        )
    bundle_data = storage.read_json(bundle_file)
    if not isinstance(bundle_data, dict):
        raise ValueError("context_bundle asset JSON must be an object")
    content = bundle_data.get("content", {}) if isinstance(bundle_data.get("content", {}), dict) else {}
    metadata = bundle_data.get("metadata", {}) if isinstance(bundle_data.get("metadata", {}), dict) else {}
    mkaos_content = _mkaos_pack_content(mkaos_pack)
    _assert_flow_context_source_isolated(flow, content, mkaos_content)
    mkaos_pack = validate_mkaos_pack_result(
        storage,
        flow=mkaos_flow,
        mkaos_pack=mkaos_pack,
        project_id=project_id or "local-system",
        workspace_path=workspace_path,
        target_path=target_file,
        environment=environment,
        context_bundle_path=_display_path(storage.root, bundle_file),
    )
    mkaos_content = _mkaos_pack_content(mkaos_pack)
    context_id = str(bundle_data.get("id", ""))
    mkaos_asset = mkaos_pack.get("asset", {}) if isinstance(mkaos_pack.get("asset", {}), dict) else {}
    source_asset_ids = [str(item) for item in content.get("source_asset_ids", []) if str(item).strip()] if isinstance(content.get("source_asset_ids", []), list) else []
    evidence_refs = _dedupe([
        str(mkaos_asset.get("id", "")),
        str(mkaos_pack.get("path", "")),
        *source_asset_ids,
        *(_selector_governance_binding_evidence_refs(selector_governance_binding) if selector_governance_binding else []),
    ])
    knowledge_context_contract = build_knowledge_context_contract(
        context_bundle={"path": _display_path(storage.root, bundle_file), "asset": bundle_data},
        mkaos_pack=mkaos_pack,
        flow=mkaos_flow,
        source_policy=policy,
    )
    if selector_governance_binding:
        knowledge_context_contract["selector_governance_binding_application"] = selector_governance_binding
    content.update(
        {
            "context_bundle_id": context_id,
            "context_builder_version": "context-builder-v2-mkaos",
            "project_id": project_id or "local-system",
            "knowledge_context_contract": knowledge_context_contract,
            "selector_governance_binding_application": selector_governance_binding,
            "task_type": flow,
            "mkaos_flow": mkaos_flow,
            "target_asset_type": content.get("target_asset_type", ""),
            "target_asset_id": content.get("target_asset_id", ""),
            "mkaos_pack": mkaos_content,
            "mkaos_pack_id": str(mkaos_asset.get("id", "")),
            "mkaos_pack_path": str(mkaos_pack.get("path", "")),
            "mkaos_pack_warning": str(mkaos_pack.get("warning", "")),
            "mkaos_pack_policy": mkaos_pack.get("mkaos_pack_policy") or (mkaos_asset.get("metadata", {}) if isinstance(mkaos_asset.get("metadata", {}), dict) else {}).get("mkaos_pack_policy", {}),
            "mkaos_runtime_policy_warning_path": str(mkaos_pack.get("runtime_policy_warning_path", "")),
            "mkaos_pack_trace_span_path": str(mkaos_pack.get("trace_span_path", "")),
            "mkaos_knowledge_pack": mkaos_content,
            "mkaos_knowledge_pack_id": str(mkaos_asset.get("id", "")),
            "mkaos_knowledge_pack_path": str(mkaos_pack.get("path", "")),
            "selected_knowledge_ids": knowledge_context_contract["selected_knowledge_ids"],
            "risk_warnings": knowledge_context_contract["risk_warnings"],
            "selector_policy_version": knowledge_context_contract["selector_policy_version"],
            "review_rules": mkaos_content.get("review_rules", []) if isinstance(mkaos_content.get("review_rules", []), list) else [],
            "prior_issues": content.get("prior_issues", []) if isinstance(content.get("prior_issues", []), list) else [],
            "revision_constraints": content.get("revision_constraints", []) if isinstance(content.get("revision_constraints", []), list) else [],
            "forbidden_changes": content.get("forbidden_changes", []) if isinstance(content.get("forbidden_changes", []), list) else [],
            "source_policy": policy,
            "source_isolation": {
                "source_chunk_raw_text_allowed": False,
                "mkaos_raw_text_included": False,
                "runtime_assets_in_generation_rag_allowed": False,
            },
            "evidence_refs": evidence_refs,
            "trace_id": str(metadata.get("trace_id") or context_id),
            "envelope_id": str(metadata.get("os_envelope_id") or ""),
        }
    )
    metadata.update(
        {
            "context_builder_unified": True,
            "project_id": project_id or "local-system",
            "task_type": flow,
            "mkaos_flow": mkaos_flow,
            "source_policy": policy,
            "mkaos_pack_id": str(mkaos_asset.get("id", "")),
            "mkaos_pack_path": str(mkaos_pack.get("path", "")),
            "mkaos_warning": str(mkaos_pack.get("warning", "")),
            "knowledge_context_contract": knowledge_context_contract,
            "selector_governance_binding_application_path": selector_governance_binding.get("application_report_path", "") if selector_governance_binding else "",
            "selector_governance_report_path": effective_selector_governance_report_path,
            "knowledge_pack_id": knowledge_context_contract["knowledge_pack_id"],
            "selected_knowledge_ids": knowledge_context_contract["selected_knowledge_ids"],
            "selector_policy_version": knowledge_context_contract["selector_policy_version"],
            "mkaos_pack_policy": mkaos_pack.get("mkaos_pack_policy") or (mkaos_asset.get("metadata", {}) if isinstance(mkaos_asset.get("metadata", {}), dict) else {}).get("mkaos_pack_policy", {}),
            "mkaos_runtime_policy_warning_path": str(mkaos_pack.get("runtime_policy_warning_path", "")),
            "mkaos_pack_trace_span_path": str(mkaos_pack.get("trace_span_path", "")),
            "trace_id": str(metadata.get("trace_id") or context_id),
        }
    )
    bundle_data["content"] = content
    bundle_data["metadata"] = metadata
    bundle_data["references"] = filter_project_safe_references(
        storage,
        project_id,
        _dedupe([*[str(item) for item in bundle_data.get("references", []) if str(item).strip()], *evidence_refs]),
    )
    bundle_data["updated_at"] = utc_now()
    storage.write_json(bundle_file, bundle_data)
    from novel_forge.modules.mkaos_production_gate import run_mkaos_production_gate

    gate_report = run_mkaos_production_gate(
        storage,
        {
            "project_id": project_id or "local-system",
            "flow": mkaos_flow,
            "target_asset_path": _display_path(storage.root, target_file),
            "context_bundle": bundle_data,
            "knowledge_pack": mkaos_pack,
            "environment": environment,
            "os_envelope": os_envelope or {},
        },
    )
    bundle_data = storage.read_json(bundle_file)
    content = bundle_data.get("content", {}) if isinstance(bundle_data.get("content", {}), dict) else {}
    metadata = bundle_data.get("metadata", {}) if isinstance(bundle_data.get("metadata", {}), dict) else {}
    content["mkaos_production_gate"] = {
        "passed": bool(gate_report.get("passed")),
        "gate_report_path": gate_report.get("path", ""),
        "recommendation": gate_report.get("recommendation", ""),
        "blocking_issue_count": gate_report.get("blocking_issue_count", 0),
    }
    metadata["mkaos_production_gate_report_path"] = gate_report.get("path", "")
    metadata["mkaos_production_gate_passed"] = bool(gate_report.get("passed"))
    source_governance_gate = run_source_governance_runtime_gate(
        storage,
        project_id=project_id or "local-system",
        environment=environment,
        mode=environment,
        limit=1000,
        persist_readiness=True,
    )
    source_gate_path = str(source_governance_gate.get("gate_result", {}).get("path", ""))
    source_readiness_path = str(source_governance_gate.get("readiness_report", {}).get("path", ""))
    content["source_governance_runtime_gate"] = {
        "status": source_governance_gate["status"],
        "blocking": source_governance_gate["blocking"],
        "gate_result_path": source_gate_path,
        "readiness_report_path": source_readiness_path,
        "summary": source_governance_gate.get("summary", {}),
    }
    metadata["source_governance_runtime_gate_path"] = source_gate_path
    metadata["source_governance_runtime_gate_status"] = source_governance_gate["status"]
    bundle_data["references"] = filter_project_safe_references(
        storage,
        project_id,
        _dedupe([*[str(item) for item in bundle_data.get("references", []) if str(item).strip()], source_gate_path, source_readiness_path]),
    )
    bundle_data["content"] = content
    bundle_data["metadata"] = metadata
    storage.write_json(bundle_file, bundle_data)
    if is_production_environment(environment) and source_governance_gate["status"] == "failed":
        raise ValueError(f"context source governance runtime gate failed: {source_governance_gate.get('message', '')}")
    _record_context_span(
        storage,
        trace_id=str(metadata.get("trace_id") or context_id),
        span_type="context_bundle",
        name=f"build_flow_context_bundle.{flow}",
        path=_display_path(storage.root, bundle_file),
        project_id=project_id,
        workspace_path=workspace_path,
        attributes={"flow": flow, "mkaos_flow": mkaos_flow, "mkaos_pack_id": str(mkaos_asset.get("id", "")), "token_budget": token_budget},
    )
    updated_bundle = storage.read_json(bundle_file)
    return {
        "path": _display_path(storage.root, bundle_file),
        "asset": updated_bundle,
        "context_plan": context_plan,
        "context_bundle": {"path": _display_path(storage.root, bundle_file), "asset": updated_bundle},
        "mkaos_pack": mkaos_pack,
        "source_policy": policy,
        "source_governance_runtime_gate": source_governance_gate,
        "knowledge_context_contract": knowledge_context_contract,
        "validation": {"ok": True, "errors": []},
    }


def build_knowledge_context_contract(
    *,
    context_bundle: dict[str, Any],
    mkaos_pack: dict[str, Any],
    flow: str,
    source_policy: dict[str, Any],
) -> dict[str, Any]:
    bundle_asset = context_bundle.get("asset", {}) if isinstance(context_bundle.get("asset", {}), dict) else {}
    bundle_content = bundle_asset.get("content", {}) if isinstance(bundle_asset.get("content", {}), dict) else {}
    pack_asset = mkaos_pack.get("asset", {}) if isinstance(mkaos_pack.get("asset", {}), dict) else {}
    pack_content = pack_asset.get("content", {}) if isinstance(pack_asset.get("content", {}), dict) else {}
    pack_items = pack_content.get("pack_items", []) if isinstance(pack_content.get("pack_items", []), list) else []
    selector_policy = pack_content.get("selector_policy", {}) if isinstance(pack_content.get("selector_policy", {}), dict) else {}
    source_isolation = bundle_content.get("source_isolation", {}) if isinstance(bundle_content.get("source_isolation", {}), dict) else {}
    pack_source_isolation = pack_content.get("source_isolation", {}) if isinstance(pack_content.get("source_isolation", {}), dict) else {}
    return {
        "contract_version": KNOWLEDGE_CONTEXT_CONTRACT_VERSION,
        "context_bundle_id": str(bundle_asset.get("id") or bundle_content.get("context_bundle_id") or ""),
        "context_bundle_path": str(context_bundle.get("path") or ""),
        "knowledge_pack_id": str(pack_content.get("knowledge_pack_id") or pack_asset.get("id") or ""),
        "knowledge_pack_path": str(mkaos_pack.get("path") or ""),
        "source_policy": source_policy,
        "source_isolation": {
            "source_chunk_raw_text_allowed": False,
            "runtime_assets_in_generation_rag_allowed": False,
            "raw_source_text_allowed": False,
            **pack_source_isolation,
            **source_isolation,
        },
        "mkaos_flow": str(flow or pack_content.get("flow") or ""),
        "selected_knowledge_ids": _dedupe([str(item.get("knowledge_id", "")) for item in pack_items if isinstance(item, dict)]),
        "review_rules": pack_content.get("review_rules", []) if isinstance(pack_content.get("review_rules", []), list) else [],
        "risk_warnings": pack_content.get("risk_warnings", []) if isinstance(pack_content.get("risk_warnings", []), list) else [],
        "selector_policy_version": str(selector_policy.get("version") or "selector-v1"),
        "selector_governance": selector_policy.get("selector_governance", {}) if isinstance(selector_policy.get("selector_governance", {}), dict) else {},
    }


def knowledge_context_contract_from_result(result: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    direct = result.get("knowledge_context_contract")
    if isinstance(direct, dict) and direct:
        return direct
    asset = result.get("asset", {}) if isinstance(result.get("asset", {}), dict) else {}
    content = asset.get("content", {}) if isinstance(asset.get("content", {}), dict) else {}
    contract = content.get("knowledge_context_contract")
    if isinstance(contract, dict) and contract:
        return contract
    return build_knowledge_context_contract(
        context_bundle={"path": str(result.get("path") or ""), "asset": asset},
        mkaos_pack=result.get("mkaos_pack", {}) if isinstance(result.get("mkaos_pack", {}), dict) else {},
        flow=str(content.get("task_type") or ""),
        source_policy=result.get("source_policy", {}) if isinstance(result.get("source_policy", {}), dict) else {},
    )


def knowledge_context_contract_from_pack(pack: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(pack, dict):
        return {}
    bundle = pack.get("context_bundle", {}) if isinstance(pack.get("context_bundle", {}), dict) else {}
    bundle_asset = bundle.get("asset", {}) if isinstance(bundle.get("asset", {}), dict) else {}
    bundle_content = bundle_asset.get("content", {}) if isinstance(bundle_asset.get("content", {}), dict) else {}
    existing = bundle_content.get("knowledge_context_contract")
    if isinstance(existing, dict) and existing:
        return existing
    return build_knowledge_context_contract(
        context_bundle=bundle,
        mkaos_pack=pack,
        flow=str(bundle_content.get("task_type") or ""),
        source_policy=bundle_content.get("source_policy", {}) if isinstance(bundle_content.get("source_policy", {}), dict) else {},
    )


def knowledge_context_contract_metadata(contract: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(contract, dict) or not contract:
        return {}
    return {
        "knowledge_context_contract": contract,
        "context_bundle_id": str(contract.get("context_bundle_id", "")),
        "context_bundle_path": str(contract.get("context_bundle_path", "")),
        "knowledge_pack_id": str(contract.get("knowledge_pack_id", "")),
        "mkaos_knowledge_pack_id": str(contract.get("knowledge_pack_id", "")),
        "mkaos_flow": str(contract.get("mkaos_flow", "")),
        "selected_knowledge_ids": contract.get("selected_knowledge_ids", []) if isinstance(contract.get("selected_knowledge_ids", []), list) else [],
        "selector_policy_version": str(contract.get("selector_policy_version", "")),
    }


def _resolve_context_selector_governance_binding(
    storage: LocalStorage,
    binding_application_ref: str | Path | None,
    *,
    selector_governance_report_path: str | Path | None,
    project_id: str,
    environment: str,
) -> dict[str, Any]:
    direct_report_ref = str(selector_governance_report_path or "").strip()
    if binding_application_ref:
        binding = load_context_governance_binding_application(storage, binding_application_ref, project_id=project_id, environment=environment)
        binding_report_path = str(binding.get("selector_governance_report_path") or "")
        if direct_report_ref and direct_report_ref != binding_report_path:
            raise ValueError("selector_governance_report_path does not match approved binding application payload")
        return binding
    if is_production_environment(environment) and direct_report_ref:
        raise ValueError("production selector governance binding requires selector_governance_binding_application_report_path")
    return {}


def _selector_governance_binding_evidence_refs(binding: dict[str, Any]) -> list[str]:
    return _dedupe(
        [
            str(binding.get("application_report_path") or ""),
            str(binding.get("binding_proposal_path") or ""),
            str(binding.get("selector_governance_report_path") or ""),
            str(binding.get("approval_request_path") or ""),
            str(binding.get("rollback_plan_path") or ""),
        ]
    )


def require_knowledge_context_contract(contract: dict[str, Any], *, operation: str, environment: str = "") -> dict[str, Any]:
    if not is_production_environment(environment):
        return contract if isinstance(contract, dict) else {}
    if not isinstance(contract, dict) or not contract:
        raise ValueError(f"knowledge context contract required for production operation {operation}")
    missing = [
        field
        for field in ["context_bundle_id", "knowledge_pack_id", "source_policy", "source_isolation", "mkaos_flow"]
        if (field in {"source_policy", "source_isolation"} and not isinstance(contract.get(field), dict)) or (field not in {"source_policy", "source_isolation"} and not str(contract.get(field) or "").strip())
    ]
    if missing:
        raise ValueError(f"knowledge context contract missing required fields for production operation {operation}: {', '.join(missing)}")
    return contract


def _mkaos_flow_for_context(flow: str) -> str:
    normalized = str(flow or "").strip().lower().replace("-", "_")
    aliases = {
        "analysis": "review",
        "decompose": "review",
        "convert": "review",
        "chapter_plan": "chapter_outline",
        "draft": "prose",
        "editor_patch": "revision",
        "publish_gate": "publish",
        "feedback_backflow": "feedback",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized in {"outline", "chapter_outline", "prose", "review", "revision", "recap", "publish", "feedback"}:
        return normalized
    return "review"


def _mkaos_pack_content(pack: dict[str, Any]) -> dict[str, Any]:
    asset = pack.get("asset", {}) if isinstance(pack.get("asset", {}), dict) else {}
    return asset.get("content", {}) if isinstance(asset.get("content", {}), dict) else {}


def _assert_flow_context_source_isolated(flow: str, context_content: dict[str, Any], mkaos_content: dict[str, Any]) -> None:
    if _contains_key(mkaos_content, "raw_text"):
        raise ValueError(f"{flow} context bundle must not include MKAOS source_chunk.raw_text")
    actual_context = str(context_content.get("actual_context") or "")
    if "source_chunk.raw_text" in actual_context:
        raise ValueError(f"{flow} context bundle actual_context mentions source_chunk.raw_text")
    if _mkaos_flow_for_context(flow) in {"prose", "review", "recap", "publish"} and '"raw_text"' in json.dumps(context_content, ensure_ascii=False):
        raise ValueError(f"{flow} context bundle must not include raw_text keys")


def _contains_key(value: Any, key: str) -> bool:
    if isinstance(value, dict):
        return any(str(item_key) == key or _contains_key(item_value, key) for item_key, item_value in value.items())
    if isinstance(value, list):
        return any(_contains_key(item, key) for item in value)
    return False


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
    key = {
        "topic_development": "topic",
        "world": "worldbuilding",
        "character_design": "character",
        "chapter_plan": "chapter_outline",
        "draft": "prose",
        "editor_patch": "revision",
        "publish_gate": "publish",
        "feedback_backflow": "feedback",
    }.get(key, key)
    common_project_assets = [
        "knowledge_card",
        "material_card",
        "commercial_pattern",
        "narrative_pattern",
        "character_mechanism",
        "conflict_pattern",
        "emotion_curve",
        "hook_pattern",
        "rule_card",
        "template_card",
        "writing_template",
        "craft_template",
        "genre_profile",
        "genre_strategy_pack",
        "platform_profile",
        "platform_genre_fit",
        "quality_standard_profile",
        "quality_rubric_pack",
        "review_rule_pack",
        "style_profile",
        "feedback_insight",
    ]
    continuity_assets = [
        "world_bible",
        "continuity_bible",
        "power_scale_rule",
        "character_card",
        "foreshadowing_thread",
        "chapter_state",
        "fact_ledger",
        "character_state_ledger",
        "foreshadowing_graph",
        "reward_ledger",
        "longform_recap_report",
        "canon_graph_snapshot",
        "canon_state_machine_ledger",
    ]
    chapter_assets = [
        "outline",
        "outline_version",
        "chapter_plan",
        "chapter_plan_version",
        "draft_chapter",
        "draft_version",
        "review_report",
        "review_issue",
        "revision_plan",
        "revision_task",
    ]
    policies = {
        "topic": {
            "stage": "topic",
            "required_buckets": ["material_cards", "knowledge_cards", "writing_templates"],
            "default_top_k": 8,
            "default_token_budget": 3600,
            "allowed_asset_types": _dedupe([*common_project_assets, "creative_strategy_profile", "genre_market_profile", "subgenre_mechanic", "genre_template_binding"]),
            "forbidden_asset_types": _dedupe([*BASE_FORBIDDEN_CONTEXT_TYPES, "draft_chapter", "draft_version", "review_report", "revision_plan"]),
            "risk_gate": "topic context may use abstract market/material signals but not draft prose or raw source material",
        },
        "worldbuilding": {
            "stage": "worldbuilding",
            "required_buckets": ["worldbuilding", "material_cards", "knowledge_cards"],
            "default_top_k": 8,
            "default_token_budget": 4200,
            "allowed_asset_types": _dedupe([*common_project_assets, *continuity_assets, "subgenre_mechanic", "genre_template_binding"]),
            "forbidden_asset_types": _dedupe([*BASE_FORBIDDEN_CONTEXT_TYPES, "draft_chapter", "draft_version", "review_report", "revision_plan"]),
            "risk_gate": "worldbuilding context must be project-safe, abstract, and rule-oriented",
        },
        "character": {
            "stage": "character",
            "required_buckets": ["characters", "worldbuilding", "knowledge_cards", "material_cards"],
            "default_top_k": 8,
            "default_token_budget": 4000,
            "allowed_asset_types": _dedupe([*common_project_assets, *continuity_assets, "style_generation_policy", "style_review_rule"]),
            "forbidden_asset_types": _dedupe([*BASE_FORBIDDEN_CONTEXT_TYPES, "draft_chapter", "draft_version", "review_report"]),
            "risk_gate": "character context must preserve project continuity and avoid importing prose examples as character voice",
        },
        "chapter_generation": {
            "stage": "draft",
            "required_buckets": ["characters", "worldbuilding", "previous_summaries", "knowledge", "foreshadowing", "materials"],
            "default_top_k": 10,
            "default_token_budget": 6000,
            "allowed_asset_types": _dedupe([*common_project_assets, *continuity_assets, *chapter_assets, "style_generation_policy", "style_review_rule", "style_drift_report"]),
            "forbidden_asset_types": _dedupe(BASE_FORBIDDEN_CONTEXT_TYPES),
            "risk_gate": "block high copyright risk and raw analysis reports",
        },
        "review": {
            "stage": "review",
            "required_buckets": ["quality", "style", "previous_summaries", "drafts"],
            "default_top_k": 8,
            "default_token_budget": 4500,
            "allowed_asset_types": _dedupe([*common_project_assets, *continuity_assets, *chapter_assets, "style_review_rule", "style_drift_report", "quality_regression_report", "opening_3_report", "golden_10_report"]),
            "forbidden_asset_types": _dedupe(BASE_FORBIDDEN_CONTEXT_TYPES),
            "risk_gate": "include rubric assets and final draft lineage",
        },
        "revision": {
            "stage": "revision",
            "required_buckets": ["reviews", "style", "quality", "previous_summaries"],
            "default_top_k": 8,
            "default_token_budget": 4500,
            "allowed_asset_types": _dedupe([*common_project_assets, *continuity_assets, *chapter_assets, "style_review_rule", "style_drift_report", "quality_regression_report"]),
            "forbidden_asset_types": _dedupe(BASE_FORBIDDEN_CONTEXT_TYPES),
            "risk_gate": "require review/revision lineage before applying edits",
        },
        "analysis_conversion": {
            "stage": "analysis_conversion",
            "required_buckets": ["knowledge", "materials", "templates"],
            "default_top_k": 6,
            "default_token_budget": 3600,
            "allowed_asset_types": _dedupe([*common_project_assets, "decomposition_report", "common_novel_analysis_report", "web_fiction_business_analysis_report", "published_fiction_analysis_report", "classic_literary_analysis_report"]),
            "forbidden_asset_types": ["source_document", "cleaned_text", "source_chunk", "parallel_pair"],
            "risk_gate": "analysis reports must stay abstract-only until human approved",
        },
        "outline": {
            "stage": "outline",
            "required_buckets": ["characters", "worldbuilding", "knowledge_cards", "material_cards", "writing_templates"],
            "default_top_k": 8,
            "default_token_budget": 5000,
            "allowed_asset_types": _dedupe([*common_project_assets, *continuity_assets, "outline", "outline_version", "long_form_macro_plan", "subgenre_mechanic", "genre_template_binding"]),
            "forbidden_asset_types": _dedupe([*BASE_FORBIDDEN_CONTEXT_TYPES, "draft_chapter", "draft_version", "review_report", "revision_plan"]),
            "risk_gate": "outline context must use project canon, abstract knowledge, and original assets only",
        },
        "chapter_outline": {
            "stage": "chapter_plan",
            "required_buckets": ["characters", "worldbuilding", "previous_summaries", "knowledge_cards", "foreshadowing"],
            "default_top_k": 8,
            "default_token_budget": 5200,
            "allowed_asset_types": _dedupe([*common_project_assets, *continuity_assets, "outline", "outline_version", "long_form_macro_plan", "chapter_plan", "chapter_plan_version"]),
            "forbidden_asset_types": _dedupe([*BASE_FORBIDDEN_CONTEXT_TYPES, "draft_chapter", "draft_version", "review_report", "revision_plan"]),
            "risk_gate": "chapter outline context must preserve continuity and exclude raw sources",
        },
        "prose": {
            "stage": "draft",
            "required_buckets": ["characters", "worldbuilding", "previous_summaries", "knowledge_cards", "foreshadowing", "writing_templates"],
            "default_top_k": 8,
            "default_token_budget": 6000,
            "allowed_asset_types": _dedupe([*common_project_assets, *continuity_assets, *chapter_assets, "style_generation_policy", "style_review_rule", "style_drift_report"]),
            "forbidden_asset_types": _dedupe(BASE_FORBIDDEN_CONTEXT_TYPES),
            "risk_gate": "prose context must not include source_chunk.raw_text or runtime assets",
        },
        "recap": {
            "stage": "recap",
            "required_buckets": ["previous_summaries", "characters", "worldbuilding", "foreshadowing", "knowledge_cards", "quality"],
            "default_top_k": 10,
            "default_token_budget": 5200,
            "allowed_asset_types": _dedupe([*common_project_assets, *continuity_assets, *chapter_assets, "chapter_quality_trend", "canon_conflict_trend", "style_drift_trend"]),
            "forbidden_asset_types": _dedupe(BASE_FORBIDDEN_CONTEXT_TYPES),
            "risk_gate": "recap context must summarize project-owned state without raw sources",
        },
        "publish": {
            "stage": "publish",
            "required_buckets": ["quality", "previous_summaries", "drafts", "knowledge_cards"],
            "default_top_k": 8,
            "default_token_budget": 4500,
            "allowed_asset_types": _dedupe([*common_project_assets, *continuity_assets, *chapter_assets, "publish_gate_report", "release_package", "platform_strategy_pack", "platform_upload_package"]),
            "forbidden_asset_types": _dedupe(BASE_FORBIDDEN_CONTEXT_TYPES),
            "risk_gate": "publish context must include gate evidence and exclude raw sources",
        },
        "feedback": {
            "stage": "feedback",
            "required_buckets": ["quality", "previous_summaries", "knowledge_cards"],
            "default_top_k": 8,
            "default_token_budget": 4200,
            "allowed_asset_types": _dedupe([*common_project_assets, *continuity_assets, *chapter_assets, "feedback_insight", "comment_cluster_report", "chapter_dropoff_report", "feedback_plan_mutation_proposal"]),
            "forbidden_asset_types": _dedupe(BASE_FORBIDDEN_CONTEXT_TYPES),
            "risk_gate": "feedback context must map reader signals to assets and issues",
        },
    }
    policy = {"profile": key, **policies.get(key, policies["chapter_generation"])}
    policy.setdefault("stage", key)
    policy["source_policy"] = _stage_source_policy(policy)
    policy["source_isolation"] = _stage_source_isolation(policy)
    policy["contract_version"] = "stage-context-profile-v1"
    return policy


def _stage_source_policy(profile_policy: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract_version": "stage-source-policy-v1",
        "profile": str(profile_policy.get("profile", "")),
        "stage": str(profile_policy.get("stage", "")),
        "generation_context_allowed": True,
        "raw_source_text_allowed": False,
        "parallel_pairs_allowed": False,
        "analysis_reports_allowed": str(profile_policy.get("stage", "")) == "analysis_conversion",
        "max_source_risk": "R1",
        "required_lineage": ["asset_id", "path", "type", "title"],
        "policy": "only schema-backed, project-safe, abstract or owned assets can enter context bundles",
    }


def _stage_source_isolation(profile_policy: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract_version": "stage-source-isolation-v1",
        "profile": str(profile_policy.get("profile", "")),
        "stage": str(profile_policy.get("stage", "")),
        "raw_source_text_allowed": False,
        "source_chunk_raw_text_allowed": False,
        "parallel_pair_text_allowed": False,
        "external_reference_text_allowed": False,
        "allowed_source_forms": ["schema_asset_summary", "approved_knowledge_card", "approved_material_card", "project_canon"],
        "forbidden_asset_types": profile_policy.get("forbidden_asset_types", []) if isinstance(profile_policy.get("forbidden_asset_types", []), list) else [],
        "enforcement": "context_builder_candidate_filter",
    }


def _stage_context_contract(profile_policy: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract_version": str(profile_policy.get("contract_version") or "stage-context-profile-v1"),
        "profile": str(profile_policy.get("profile", "")),
        "stage": str(profile_policy.get("stage", "")),
        "required_buckets": profile_policy.get("required_buckets", []) if isinstance(profile_policy.get("required_buckets", []), list) else [],
        "allowed_asset_types": profile_policy.get("allowed_asset_types", []) if isinstance(profile_policy.get("allowed_asset_types", []), list) else [],
        "forbidden_asset_types": profile_policy.get("forbidden_asset_types", []) if isinstance(profile_policy.get("forbidden_asset_types", []), list) else [],
        "source_policy": _stage_source_policy(profile_policy),
        "source_isolation": _stage_source_isolation(profile_policy),
        "risk_gate": str(profile_policy.get("risk_gate", "")),
        "manual_selection_rule": "manual selection may prioritize eligible assets but cannot override source isolation, copyright, or stage profile gates",
    }


def _memory_levels(levels: list[str] | None) -> list[str]:
    values = [str(item).strip().upper() for item in levels or [] if str(item).strip()]
    if not values:
        values = ["L0", "L1", "L2", "L3", "L4", "L5"]
    allowed = {"L0", "L1", "L2", "L3", "L4", "L5"}
    return _dedupe([item for item in values if item in allowed])


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


def _record_context_usage_feedback(
    storage: LocalStorage,
    *,
    bundle_path: str,
    bundle_data: dict[str, Any],
    plan: BaseAsset,
    selected: list[dict[str, Any]],
    plan_content: dict[str, Any],
    project_id: str,
    workspace_path: str,
) -> dict[str, Any]:
    bundle_content = bundle_data.get("content", {}) if isinstance(bundle_data.get("content", {}), dict) else {}
    context_profile = str(plan_content.get("context_profile") or bundle_content.get("context_profile") or "")
    profile_policy = plan_content.get("context_profile_policy", {}) if isinstance(plan_content.get("context_profile_policy", {}), dict) else {}
    context_stage = str(profile_policy.get("stage") or context_profile or "")
    mkaos_flow = _mkaos_flow_for_context(context_stage or context_profile)
    target_artifact_id = str(bundle_content.get("target_asset_id") or plan_content.get("target_asset_id") or bundle_content.get("target_path") or "")
    chapter_id = _context_chapter_id(plan_content, bundle_content)
    events: list[dict[str, Any]] = []
    for item in selected:
        asset_type = str(item.get("type") or "")
        asset_id = str(item.get("asset_id") or "")
        if not asset_id:
            continue
        source_eligibility = item.get("source_eligibility") if isinstance(item.get("source_eligibility"), dict) else {}
        prompt_context = {
            "context_bundle_id": str(bundle_data.get("id") or ""),
            "context_bundle_path": bundle_path,
            "context_profile": context_profile,
            "context_stage": context_stage,
            "source_eligibility": source_eligibility,
        }
        if asset_type == "knowledge_card":
            result = record_usage_event(
                storage,
                {
                    "knowledge_id": asset_id,
                    "knowledge_pack_id": str(plan.id),
                    "project_id": project_id or "local-system",
                    "workspace_path": workspace_path,
                    "flow": mkaos_flow,
                    "target_artifact_id": target_artifact_id,
                    "chapter_id": chapter_id,
                    "agent_name": "context-builder",
                    "used_as": "context_bundle_selected_asset",
                    "prompt_context": prompt_context,
                    "effect_score": 0.0,
                    "references": [bundle_path, str(item.get("path") or "")],
                },
            )
            events.extend(_usage_event_refs(result, event_type="knowledge_usage_event"))
        elif asset_type == "material_card":
            result = record_material_usage_event(
                storage,
                {
                    "material_id": asset_id,
                    "project_id": project_id or "local-system",
                    "workspace_path": workspace_path,
                    "flow": mkaos_flow,
                    "target_artifact_id": target_artifact_id,
                    "context_bundle_id": str(bundle_data.get("id") or ""),
                    "context_bundle_path": bundle_path,
                    "chapter_id": chapter_id,
                    "agent_name": "context-builder",
                    "used_as": "context_bundle_selected_asset",
                    "source_eligibility": source_eligibility,
                    "effect_score": 0.0,
                    "references": [str(item.get("path") or "")],
                },
            )
            events.extend(_usage_event_refs(result, event_type="material_usage_event"))
    return {"events": events, "event_count": len(events)}


def _usage_event_refs(result: dict[str, Any], *, event_type: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    events = result.get("events", []) if isinstance(result.get("events", []), list) else []
    for event in events:
        asset = event.get("asset", {}) if isinstance(event.get("asset", {}), dict) else {}
        rows.append(
            {
                "type": event_type,
                "path": str(event.get("path") or ""),
                "asset_id": str(asset.get("id") or ""),
                "source": str(asset.get("source") or ""),
            }
        )
    return rows


def _context_chapter_id(plan_content: dict[str, Any], bundle_content: dict[str, Any]) -> str:
    for row in [plan_content, bundle_content]:
        value = row.get("chapter_id") if isinstance(row, dict) else ""
        if value:
            return str(value)
    target_id = str(bundle_content.get("target_asset_id") or plan_content.get("target_asset_id") or "")
    return target_id if target_id.startswith("chapter") else ""


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
        "source_eligibility": item.get("source_eligibility", {}) if isinstance(item.get("source_eligibility", {}), dict) else {},
        "source_chunk_ids": item.get("source_chunk_ids", []) if isinstance(item.get("source_chunk_ids", []), list) else [],
        "recall_explanation": item.get("recall_explanation", {}) if isinstance(item.get("recall_explanation", {}), dict) else {},
        "selected_by_default": str(item.get("type", "")) not in RAW_OR_REPORT_TYPES,
    }


def _candidate_payloads(items: Any) -> list[dict[str, Any]]:
    return [_candidate_payload(item) for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _enrich_candidate_source_eligibility(storage: LocalStorage, candidate: dict[str, Any]) -> dict[str, Any]:
    if not str(candidate.get("path", "")).strip():
        return candidate
    data = _read_asset_policy_candidate(storage, str(candidate.get("path", "")))
    if not data:
        return candidate
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    source_eligibility = content.get("source_eligibility") if isinstance(content.get("source_eligibility"), dict) else {}
    source_chunk_ids = content.get("source_chunk_ids") if isinstance(content.get("source_chunk_ids"), list) else []
    current_policy = generation_context_policy(data)
    existing_copyright = candidate.get("copyright", {}) if isinstance(candidate.get("copyright", {}), dict) else {}
    existing_signals = [str(item) for item in existing_copyright.get("signals", []) if str(item).strip()] if isinstance(existing_copyright.get("signals", []), list) else []
    current_signals = [str(item) for item in current_policy.get("signals", []) if str(item).strip()] if isinstance(current_policy.get("signals", []), list) else []
    merged_signals = _dedupe([*existing_signals, *current_signals])
    merged_eligible = bool(current_policy.get("eligible")) and existing_copyright.get("eligible") is not False
    merged_risk_level = _stricter_context_risk(existing_copyright.get("risk_level"), current_policy.get("risk_level"))
    merged_reason = "; ".join(_dedupe([str(existing_copyright.get("reason") or ""), str(current_policy.get("reason") or "")])) or "eligible for generation RAG"
    enriched = {
        **candidate,
        "source_eligibility": candidate.get("source_eligibility") if isinstance(candidate.get("source_eligibility"), dict) and candidate.get("source_eligibility") else source_eligibility,
        "source_chunk_ids": [str(item) for item in source_chunk_ids if str(item).strip()],
        "copyright": {
            **existing_copyright,
            "eligible": merged_eligible,
            "risk_level": merged_risk_level,
            "reason": merged_reason,
            "signals": merged_signals,
        },
    }
    if enriched.get("source_eligibility"):
        copyright = enriched.get("copyright", {}) if isinstance(enriched.get("copyright", {}), dict) else {}
        enriched["copyright"] = {
            **copyright,
            "source_eligibility_status": enriched["source_eligibility"].get("status", ""),
            "source_policy_refs": enriched["source_eligibility"].get("source_policy_refs", []),
            "source_risk_report_refs": enriched["source_eligibility"].get("source_risk_report_refs", []),
        }
    elif metadata.get("source_eligibility_status"):
        enriched["source_eligibility"] = {"status": metadata.get("source_eligibility_status")}
    return enriched


def _stricter_context_risk(left: Any, right: Any) -> str:
    order = {"unknown": 0, "low": 1, "medium": 2, "high": 3}
    normalized = []
    for value in [left, right]:
        text = str(value or "unknown").strip().lower().replace("_", "-")
        if text in {"non-commercial", "noncommercial", "restricted", "blocked"}:
            text = "high"
        if text not in order:
            text = "unknown"
        normalized.append(text)
    return max(normalized, key=lambda item: order[item])


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
        item = {**item, "categories": _normalized_candidate_categories(item)}
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


def _normalized_candidate_categories(item: dict[str, Any]) -> list[str]:
    categories = item.get("categories", []) if isinstance(item.get("categories", []), list) else []
    asset_type = str(item.get("type", ""))
    return _dedupe([*[str(value) for value in categories if str(value).strip()], *CONTEXT_TYPE_BUCKETS.get(asset_type, [])])


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
    profile_policy: dict[str, Any] | None = None,
    environment: str = "",
) -> list[dict[str, Any]]:
    disabled = set(disabled_paths or [])
    explicit_selected = set(selected_paths or [])
    priority = list(priority_paths or [])
    profile = profile_policy if isinstance(profile_policy, dict) else {}
    selected = [
        candidate
        for candidate in candidates
        if str(candidate.get("path", "")) not in disabled
        and (candidate.get("selected_by_default", True) or str(candidate.get("path", "")) in explicit_selected)
        and str(candidate.get("type", "")) not in RAW_OR_REPORT_TYPES
        and _candidate_allowed_by_profile(candidate, profile)
        and _candidate_allowed_by_copyright(candidate)
        and _candidate_allowed_by_source_eligibility(candidate, environment=environment)
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


def _candidate_allowed_by_source_eligibility(candidate: dict[str, Any], *, environment: str) -> bool:
    if not is_production_environment(environment):
        return True
    source_eligibility = candidate.get("source_eligibility") if isinstance(candidate.get("source_eligibility"), dict) else {}
    source_chunk_ids = [str(item) for item in candidate.get("source_chunk_ids", []) if str(item).strip()] if isinstance(candidate.get("source_chunk_ids", []), list) else []
    if source_chunk_ids and not source_eligibility:
        return False
    if not source_eligibility:
        return True
    if source_eligibility.get("status") != "passed":
        return False
    if not bool(source_eligibility.get("generation_context_allowed")):
        return False
    if bool(source_eligibility.get("evidence_only") or source_eligibility.get("quarantine")):
        return False
    return True


def _candidate_allowed_by_profile(candidate: dict[str, Any], profile_policy: dict[str, Any]) -> bool:
    return _profile_rejection_reason(candidate, profile_policy) == ""


def _profile_rejection_reason(candidate: dict[str, Any], profile_policy: dict[str, Any]) -> str:
    asset_type = str(candidate.get("type", ""))
    if not asset_type:
        return "asset type missing from context candidate"
    forbidden = {
        str(item)
        for item in profile_policy.get("forbidden_asset_types", [])
        if str(item).strip()
    } if isinstance(profile_policy.get("forbidden_asset_types", []), list) else set()
    if asset_type in forbidden:
        return f"asset type {asset_type} is forbidden for {profile_policy.get('profile', 'unknown')} context profile"
    allowed = {
        str(item)
        for item in profile_policy.get("allowed_asset_types", [])
        if str(item).strip()
    } if isinstance(profile_policy.get("allowed_asset_types", []), list) else set()
    if allowed and asset_type not in allowed:
        return f"asset type {asset_type} is not allowed for {profile_policy.get('profile', 'unknown')} context profile"
    return ""


def _selection_policy_rejections(
    storage: LocalStorage,
    plan_content: dict[str, Any],
    candidates: list[dict[str, Any]],
    manual_selection: dict[str, Any],
    *,
    profile_policy: dict[str, Any] | None = None,
    environment: str = "",
) -> list[dict[str, Any]]:
    profile = profile_policy if isinstance(profile_policy, dict) else {}
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
            rejections.append(
                _candidate_rejection(
                    candidate,
                    reason="raw source or analysis report cannot enter generation context",
                    requested_by=requested_by_path.get(path, []),
                    signals=["blocked_asset_type"],
                )
            )
            seen.add(path)
        elif not _candidate_allowed_by_profile(candidate, profile):
            rejections.append(
                _candidate_rejection(
                    candidate,
                    reason=_profile_rejection_reason(candidate, profile),
                    requested_by=requested_by_path.get(path, []),
                    signals=["stage_profile_rejected", "blocked_asset_type"],
                )
            )
            seen.add(path)
        elif not _candidate_allowed_by_copyright(candidate):
            copyright = candidate.get("copyright", {}) if isinstance(candidate.get("copyright", {}), dict) else {}
            rejections.append(_candidate_rejection(candidate, reason=str(copyright.get("reason") or "copyright policy rejected candidate"), requested_by=requested_by_path.get(path, [])))
            seen.add(path)
        elif not _candidate_allowed_by_source_eligibility(candidate, environment=environment):
            source_eligibility = candidate.get("source_eligibility") if isinstance(candidate.get("source_eligibility"), dict) else {}
            rejections.append(
                _candidate_rejection(
                    candidate,
                    reason=f"source eligibility rejected candidate for production context: {source_eligibility.get('status') or 'missing'}",
                    requested_by=requested_by_path.get(path, []),
                    signals=["source_eligibility_rejected"],
                )
            )
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
            candidate = {
                "path": path,
                "asset_id": str(data.get("id", "")),
                "type": str(data.get("type", "")),
                "title": str(data.get("title") or data.get("name") or ""),
                "copyright": {"signals": policy.get("signals", []) if isinstance(policy.get("signals", []), list) else []},
            }
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
            candidate = _enrich_candidate_source_eligibility(storage, candidate)
            if not _candidate_allowed_by_source_eligibility(candidate, environment=environment):
                source_eligibility = candidate.get("source_eligibility") if isinstance(candidate.get("source_eligibility"), dict) else {}
                rejections.append(
                    {
                        "path": path,
                        "asset_id": str(data.get("id", "")),
                        "type": str(data.get("type", "")),
                        "title": str(data.get("title") or data.get("name") or ""),
                        "reason": f"source eligibility rejected candidate for production context: {source_eligibility.get('status') or 'missing'}",
                        "signals": ["source_eligibility_rejected"],
                        "requested_by": requested_by,
                        "source_eligibility": source_eligibility,
                    }
                )
                seen.add(path)
                continue
            profile_reason = _profile_rejection_reason(candidate, profile)
            if profile_reason:
                rejections.append(
                    {
                        "path": path,
                        "asset_id": str(data.get("id", "")),
                        "type": str(data.get("type", "")),
                        "title": str(data.get("title") or data.get("name") or ""),
                        "reason": profile_reason,
                        "signals": ["stage_profile_rejected", "blocked_asset_type"],
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


def _create_context_approval_requests(
    storage: LocalStorage,
    *,
    bundle_path: str,
    plan_path: str,
    project_id: str,
    workspace_path: str,
    policy_rejections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    requested_rejections = [
        item
        for item in policy_rejections
        if isinstance(item, dict) and item.get("requested_by")
    ]
    if not requested_rejections:
        return []
    from novel_forge.modules.permission_center import create_approval_request

    evidence_refs = _dedupe([bundle_path, plan_path, *[str(item.get("path", "")) for item in requested_rejections]])
    approval = create_approval_request(
        storage,
        {
            "project_id": project_id or "context-builder",
            "workspace_path": workspace_path,
            "scope": "context",
            "action": "approve_rejected_context_selection",
            "risk_level": "high",
            "environment": "production",
            "blocking": True,
            "target_type": "context_bundle",
            "target_id": bundle_path,
            "target_refs": [bundle_path],
            "evidence_refs": evidence_refs,
            "requested_by": "context-builder",
            "subject_type": "agent",
            "subject_id": "context-agent",
            "reason": "manual context selection attempted to include source/profile/copyright-rejected assets",
            "required_before": ["context_bundle_use_in_generation", "agent_model_call"],
            "rollback_plan": {
                "automatic_context_override_allowed": False,
                "rollback_action": "use generated bundle without rejected assets unless approval is resolved",
                "bundle_path": bundle_path,
            },
        },
    )
    return [
        {
            "scope": "context",
            "action": "approve_rejected_context_selection",
            "approval_request_path": approval["path"],
            "approval_request_id": approval["asset"]["content"]["request_id"],
            "blocking": bool(approval.get("blocking")),
            "rejected_path_count": len(requested_rejections),
            "rejected_paths": [str(item.get("path", "")) for item in requested_rejections],
            "signals": _dedupe([str(signal) for item in requested_rejections for signal in (item.get("signals", []) if isinstance(item.get("signals", []), list) else [])]),
        }
    ]


def _plan_exclusion_index(plan_content: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: list[Any] = []
    rows.extend(plan_content.get("exclusions", []) if isinstance(plan_content.get("exclusions", []), list) else [])
    copyright_filter = plan_content.get("copyright_filter", {}) if isinstance(plan_content.get("copyright_filter", {}), dict) else {}
    rows.extend(copyright_filter.get("filtered_assets", []) if isinstance(copyright_filter.get("filtered_assets", []), list) else [])
    return {str(item.get("path", "")): item for item in rows if isinstance(item, dict) and str(item.get("path", "")).strip()}


def _candidate_rejection(candidate: dict[str, Any], *, reason: str, requested_by: list[str], signals: list[str] | None = None) -> dict[str, Any]:
    copyright = candidate.get("copyright", {}) if isinstance(candidate.get("copyright", {}), dict) else {}
    base_signals = copyright.get("signals", []) if isinstance(copyright.get("signals", []), list) else []
    source_eligibility = candidate.get("source_eligibility") if isinstance(candidate.get("source_eligibility"), dict) else {}
    return {
        "path": str(candidate.get("path", "")),
        "asset_id": str(candidate.get("asset_id", "")),
        "type": str(candidate.get("type", "")),
        "title": str(candidate.get("title", "")),
        "reason": reason,
        "signals": _dedupe([*[str(item) for item in base_signals], *[str(item) for item in signals or []]]),
        "requested_by": requested_by,
        "source_eligibility": source_eligibility,
    }


def _read_asset_policy_candidate(storage: LocalStorage, path: str) -> dict[str, Any] | None:
    try:
        data = storage.read_json(resolve_path(storage.root, path))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _bucket_selected(selected: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
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
                    "source_eligibility": item.get("source_eligibility", {}) if isinstance(item.get("source_eligibility", {}), dict) else {},
                }
            )
    return buckets


def _bundle_omission_check(target_asset_type: str, bucketed: dict[str, list[dict[str, str]]], retrieval_omission: Any) -> dict[str, Any]:
    retrieval = retrieval_omission if isinstance(retrieval_omission, dict) else {}
    expected = retrieval.get("expected_buckets") if isinstance(retrieval.get("expected_buckets"), list) else []
    if not expected:
        if target_asset_type in {"chapter_plan", "draft_chapter", "draft_version", "review_report", "revision_plan"}:
            expected = ["characters", "worldbuilding", "previous_summaries", "knowledge_cards", "foreshadowing", "material_cards", "writing_templates"]
        elif target_asset_type in {"outline", "outline_version"}:
            expected = ["characters", "worldbuilding", "knowledge_cards", "material_cards", "writing_templates"]
        else:
            expected = ["knowledge_cards", "material_cards"]
    expected_buckets = [str(bucket) for bucket in expected if str(bucket).strip()]
    present = [bucket for bucket in expected_buckets if bucketed.get(bucket)]
    missing = [bucket for bucket in expected_buckets if bucket not in present]
    return {
        "expected_buckets": expected_buckets,
        "present_buckets": present,
        "missing_buckets": missing,
        "missing_count": len(missing),
        "retrieval_missing_buckets": retrieval.get("missing_buckets", []) if isinstance(retrieval.get("missing_buckets", []), list) else [],
        "status": "passed" if not missing else "warning",
        "recommendations": retrieval.get("recommendations", []) if isinstance(retrieval.get("recommendations", []), list) else [],
    }


def _actual_context_text(bucketed: dict[str, list[dict[str, str]]], max_tokens: int) -> str:
    limit = max(max_tokens * 4, 1200)
    chunks: list[str] = []
    emitted_paths: set[str] = set()
    emitted_bucket_by_path: dict[str, list[str]] = {}
    for bucket, items in bucketed.items():
        if not items:
            continue
        bucket_chunks: list[str] = []
        for item in items:
            path = str(item.get("path", ""))
            if path in emitted_paths:
                emitted_bucket_by_path.setdefault(path, []).append(str(bucket))
                continue
            emitted_paths.add(path)
            emitted_bucket_by_path[path] = [str(bucket)]
            bucket_chunks.append(f"- [{item['type']}] {item['title']} ({path}): {item['summary']}")
        if bucket_chunks:
            chunks.append(f"## {bucket}")
            chunks.extend(bucket_chunks)
    if emitted_bucket_by_path:
        multi_bucket = [f"{path}: {', '.join(buckets)}" for path, buckets in emitted_bucket_by_path.items() if len(buckets) > 1]
        if multi_bucket:
            chunks.append("## bucket_crosswalk")
            chunks.extend(f"- {item}" for item in multi_bucket[:40])
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

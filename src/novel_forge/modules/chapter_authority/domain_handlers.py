"""Storage-free domain transformations for the authoritative chapter chain."""
from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.context_builder.domain import (
    ContextCandidate,
    build_authority_context_bundle,
)
from novel_forge.modules.review.domain import evaluate_rereview_result, evaluate_review_result
from novel_forge.modules.revision.domain import apply_revision_result
from novel_forge.modules.canon_graph.domain import build_canon_update, extract_canon_candidates
from novel_forge.modules.content_quality_loop.domain import evaluate_quality_evidence
from novel_forge.modules.chapter_quality_authority import build_chapter_quality_evidence
from novel_forge.modules.publishing.domain import (
    build_export_blob_manifest,
    finalize_blob_verified_release,
    prepare_internal_release,
)


def build_chapter_plan(
    *,
    chapter: int,
    title: str,
    premise: str,
    trace_id: str,
) -> dict[str, Any]:
    if chapter <= 0 or not premise.strip():
        raise KernelError("CHAPTER_PLAN_INPUT_INVALID", "chapter and premise are required")
    return {
        "chapter": chapter,
        "title": title.strip() or f"Chapter {chapter}",
        "premise": premise.strip(),
        "objective": "force a consequential choice and preserve continuity",
        "beats": ["promise tested", "public choice", "visible cost"],
        "closing_hook": "the cost creates a new obligation",
        "trace_id": trace_id,
        "blueprint_version": "chapter-blueprint-v1",
    }


def build_context_bundle(
    *,
    plan: dict[str, Any],
    plan_asset_version_id: str,
    plan_content_hash: str,
    project_id: str = "local-system",
    created_by_operation_id: str = "legacy-direct-call",
    governed_candidates: list[dict[str, Any]] | None = None,
    version_refs: dict[str, Any] | None = None,
    token_budget: int = 6000,
    required_asset_types: tuple[str, ...] = (),
) -> dict[str, Any]:
    _require_keys(plan, "chapter", "premise")
    objective = str(plan.get("chapter_objective") or plan.get("objective") or "").strip()
    scene_sequence = list(plan.get("scene_sequence") or plan.get("beats") or [])
    if not objective or not scene_sequence:
        raise KernelError(
            "CHAPTER_HANDLER_INPUT_INVALID",
            "authoritative ChapterPlan objective and scene sequence are required",
        )
    candidates = [
        ContextCandidate(
            asset_version_id=str(item["asset_version_id"]),
            asset_type=str(item["asset_type"]),
            project_id=str(item["project_id"]),
            estimated_tokens=int(item.get("estimated_tokens", 0)),
            relevance_score=float(item.get("relevance_score", item.get("score", 0))),
            qualification=str(item.get("qualification", "ELIGIBLE")),
            governance_status=str(item.get("governance_status", "CLEAR")),
            source_use_mode=str(item.get("source_use_mode", item.get("allowed_use", "generation"))),
            source_risk=int(item.get("source_risk", 0)),
            raw_source=bool(item.get("raw_source", False)),
            content_digest=str(item.get("content_digest", "")),
            policy_version=str(item.get("policy_version", item.get("source_policy_version", ""))),
            invalidation_keys=tuple(item.get("invalidation_keys", [])),
            narrative_function=str(item.get("narrative_function", "")),
            safe_summary=str(item.get("safe_summary", "")),
            structured_facts=tuple(item.get("structured_facts", [])),
            allowed_use=str(item.get("allowed_use", "generation")),
            compression_method=str(item.get("compression_method", "safe_summary")),
            physical_asset_type=str(
                item.get("physical_asset_type") or item.get("asset_type") or ""
            ),
        )
        for item in (governed_candidates or [])
    ]
    candidates.insert(
        0,
        ContextCandidate(
            asset_version_id=plan_asset_version_id,
            asset_type="chapter_plan",
            project_id=project_id,
            estimated_tokens=max(1, len(str(plan)) // 4),
            relevance_score=1.0,
            content_digest=plan_content_hash,
            invalidation_keys=(f"chapter-plan:{plan_asset_version_id}",),
            narrative_function="current_chapter_plan",
            safe_summary=(
                f"Chapter {plan['chapter']} objective: {objective}. "
                f"Premise: {plan['premise']}. Scene sequence: {scene_sequence}."
            ),
            structured_facts=(
                {"kind": "chapter", "value": plan["chapter"]},
                {"kind": "objective", "value": objective},
            ),
        ),
    )
    refs = {**(version_refs or {}), "chapter_plan_version": plan_asset_version_id}
    governed = build_authority_context_bundle(
        project_id=project_id,
        stage="draft",
        created_by_operation_id=created_by_operation_id,
        context_profile_version="draft-context-profile-v2",
        candidates=candidates,
        token_budget=token_budget,
        version_refs=refs,
        required_asset_types=required_asset_types,
    )
    return {
        **governed,
        "chapter": plan["chapter"],
        "goal": objective,
        "actual_context": {
            "premise": plan["premise"],
            "scene_sequence": scene_sequence,
            "beats": scene_sequence,
            "stage_context_view": governed["stage_context_view"],
            "copyright_boundary": "project-owned and abstract eligible context only",
        },
        "forbidden_source_count": 0,
    }


def normalize_draft_result(
    *,
    plan: dict[str, Any],
    context_asset_version_id: str,
    result: dict[str, Any],
    provider_evidence: dict[str, Any],
) -> dict[str, Any]:
    text = str(result.get("text") or "").strip()
    if not text:
        raise KernelError("CHAPTER_MODEL_OUTPUT_INVALID", "draft result has no text")
    return {
        "chapter": plan["chapter"],
        "title": plan["title"],
        "text": text,
        "context_bundle_id": context_asset_version_id,
        "provider_evidence": dict(provider_evidence),
    }


def normalize_review_result(
    *,
    draft: dict[str, Any],
    draft_asset_version_id: str,
    result: dict[str, Any],
    provider_evidence: dict[str, Any],
    project_id: str = "local-system",
    context_bundle_version_id: str = "legacy-context-bundle",
) -> dict[str, Any]:
    return evaluate_review_result(
        project_id=project_id,
        target_asset_version_id=draft_asset_version_id,
        context_bundle_version_id=context_bundle_version_id,
        chapter=int(draft["chapter"]),
        result=result,
        provider_evidence=provider_evidence,
    )


def normalize_revision_result(
    *,
    draft: dict[str, Any],
    review: dict[str, Any],
    draft_asset_version_id: str,
    review_asset_version_id: str,
    result: dict[str, Any],
    provider_evidence: dict[str, Any],
    project_id: str = "local-system",
    context_bundle_version_id: str = "legacy-context-bundle",
) -> dict[str, Any]:
    return apply_revision_result(
        project_id=project_id,
        draft=draft,
        review=review,
        draft_asset_version_id=draft_asset_version_id,
        review_asset_version_id=review_asset_version_id,
        context_bundle_version_id=context_bundle_version_id,
        result=result,
        provider_evidence=provider_evidence,
    )


def normalize_rereview_result(
    *,
    draft_asset_version_id: str,
    review: dict[str, Any],
    review_asset_version_id: str,
    revision: dict[str, Any],
    revision_asset_version_id: str,
    context_bundle_version_id: str,
    result: dict[str, Any],
    provider_evidence: dict[str, Any],
    project_id: str,
) -> dict[str, Any]:
    return evaluate_rereview_result(
        project_id=project_id,
        original_draft_version_id=draft_asset_version_id,
        initial_review_version_id=review_asset_version_id,
        revision_version_id=revision_asset_version_id,
        context_bundle_version_id=context_bundle_version_id,
        initial_review=review,
        revision=revision,
        result=result,
        provider_evidence=provider_evidence,
    )


def build_canon_patch(
    *,
    revision: dict[str, Any],
    revision_asset_version_id: str,
    project_id: str = "local-system",
    context_bundle_version_id: str = "legacy-context-bundle",
    extraction: dict[str, Any] | None = None,
    context_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    historical_state: dict[str, list[dict[str, Any]]] = {}
    state_aliases = {
        "canon_snapshot": "canon_snapshot",
        "character_state": "character_state",
        "character_state_snapshot": "character_state",
        "relationship_state": "relationship_state",
        "relationship_state_snapshot": "relationship_state",
        "timeline_snapshot": "timeline_snapshot",
        "foreshadow_state": "foreshadow_state",
        "foreshadow_snapshot": "foreshadow_state",
        "reader_promise": "reader_promise",
        "promise_ledger_snapshot": "reader_promise",
        "reward_ledger": "reward_ledger",
        "reward_ledger_snapshot": "reward_ledger",
        "world_rule": "world_rule",
        "world_rule_snapshot": "world_rule",
        "power_state": "power_state",
        "power_state_snapshot": "power_state",
        "plot_thread": "plot_thread",
        "plot_thread_snapshot": "plot_thread",
        "resource_state": "resource_state",
        "resource_state_snapshot": "resource_state",
    }
    for segment in (context_bundle or {}).get("context_segments", []):
        asset_type = str(segment.get("asset_type") or "")
        state_kind = state_aliases.get(asset_type)
        if state_kind is None:
            continue
        facts = list(segment.get("structured_facts", []))
        historical_state.setdefault(state_kind, []).append(
            {
                "asset_version_id": segment.get("asset_version_id", ""),
                "facts": facts,
                **(facts[0] if len(facts) == 1 and isinstance(facts[0], dict) else {}),
            }
        )
    if int(revision.get("chapter", 0)) > 1 and not historical_state.get("canon_snapshot"):
        raise KernelError(
            "CANON_HISTORY_BASELINE_REQUIRED",
            "chapters after the first require an explicit CanonSnapshot baseline",
        )
    return build_canon_update(
        project_id=project_id,
        revision=revision,
        revision_asset_version_id=revision_asset_version_id,
        context_bundle_version_id=context_bundle_version_id,
        extraction=extraction,
        historical_state=historical_state,
    )


def build_canon_extraction(
    *,
    revision: dict[str, Any],
    revision_asset_version_id: str,
    project_id: str,
    context_bundle_version_id: str,
    provider_extraction: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return extract_canon_candidates(
        project_id=project_id,
        revision=revision,
        revision_asset_version_id=revision_asset_version_id,
        context_bundle_version_id=context_bundle_version_id,
        provider_extraction=provider_extraction,
    )


def build_quality_report(
    *,
    revision: dict[str, Any],
    revision_asset_version_id: str,
    canon: dict[str, Any],
    canon_asset_version_id: str,
    review: dict[str, Any] | None = None,
    review_asset_version_id: str = "legacy-review-version",
    project_id: str = "local-system",
    context_bundle_version_id: str = "legacy-context-bundle",
    context_bundle: dict[str, Any] | None = None,
    evidence_reports: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    effective_review = review or {
        "issues": [
            {"code": code, "severity": "blocking", "status": "OPEN", "qualification": "ELIGIBLE"}
            for code in revision.get("resolved_issue_codes", [])
        ]
    }
    fixture = not bool(
        effective_review.get("provider_evidence", {}).get("real_model_call")
    )
    authority_reports = (
        build_chapter_quality_evidence(
            project_id=project_id,
            revision=revision,
            revision_asset_version_id=revision_asset_version_id,
            context_bundle=context_bundle or {},
            canon=canon,
            fixture=fixture,
        )
        if evidence_reports is None
        else list(evidence_reports)
    )
    aggregate = evaluate_quality_evidence(
        project_id=project_id,
        revision=revision,
        revision_asset_version_id=revision_asset_version_id,
        review=effective_review,
        review_asset_version_id=review_asset_version_id,
        canon=canon,
        canon_asset_version_id=canon_asset_version_id,
        context_bundle_version_id=context_bundle_version_id,
        evidence_reports=authority_reports,
    )
    return {**aggregate, "evidence_reports": authority_reports}


def build_publish_gate(
    *,
    revision: dict[str, Any],
    revision_asset_version_id: str,
    quality: dict[str, Any],
    quality_asset_version_id: str,
    review: dict[str, Any],
    review_asset_version_id: str,
    canon: dict[str, Any],
    canon_asset_version_id: str,
    context_bundle: dict[str, Any],
    context_bundle_version_id: str,
    project_id: str,
) -> dict[str, Any]:
    return prepare_internal_release(
        project_id=project_id,
        revision=revision,
        revision_asset_version_id=revision_asset_version_id,
        quality=quality,
        quality_asset_version_id=quality_asset_version_id,
        review=review,
        review_asset_version_id=review_asset_version_id,
        canon=canon,
        canon_asset_version_id=canon_asset_version_id,
        context_bundle=context_bundle,
        context_bundle_version_id=context_bundle_version_id,
    )


def build_export_package(
    *,
    revision: dict[str, Any],
    revision_asset_version_id: str,
    quality: dict[str, Any],
    quality_asset_version_id: str,
) -> dict[str, Any]:
    return build_export_blob_manifest(
        revision=revision,
        revision_asset_version_id=revision_asset_version_id,
        publish_gate=quality,
        publish_gate_asset_version_id=quality_asset_version_id,
    )


def build_final_release_gate(
    *,
    project_id: str,
    export_package: dict[str, Any],
    export_asset_version_id: str,
    export_blobs: tuple[dict[str, Any], ...],
    publish_gate: dict[str, Any],
    publish_gate_asset_version_id: str,
    quality: dict[str, Any],
    quality_asset_version_id: str,
    review: dict[str, Any],
    review_asset_version_id: str,
    canon: dict[str, Any],
    canon_asset_version_id: str,
    context_bundle_version_id: str,
) -> dict[str, Any]:
    return finalize_blob_verified_release(
        project_id=project_id,
        export_package=export_package,
        export_asset_version_id=export_asset_version_id,
        export_blobs=export_blobs,
        publish_gate=publish_gate,
        publish_gate_asset_version_id=publish_gate_asset_version_id,
        quality=quality,
        quality_asset_version_id=quality_asset_version_id,
        review=review,
        review_asset_version_id=review_asset_version_id,
        canon=canon,
        canon_asset_version_id=canon_asset_version_id,
        context_bundle_version_id=context_bundle_version_id,
    )


def _require_keys(payload: dict[str, Any], *keys: str) -> None:
    missing = [key for key in keys if key not in payload]
    if missing:
        raise KernelError("CHAPTER_HANDLER_INPUT_INVALID", f"missing chapter fields: {', '.join(missing)}")


__all__ = [
    "build_canon_patch",
    "build_canon_extraction",
    "build_chapter_plan",
    "build_context_bundle",
    "build_export_package",
    "build_final_release_gate",
    "build_publish_gate",
    "build_quality_report",
    "normalize_draft_result",
    "normalize_review_result",
    "normalize_rereview_result",
    "normalize_revision_result",
]

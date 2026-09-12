from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.chapter_authority.realization_composition import reconcile_revision_composition


def apply_revision_result(
    *,
    project_id: str,
    draft: dict[str, Any],
    review: dict[str, Any],
    draft_asset_version_id: str,
    review_asset_version_id: str,
    context_bundle_version_id: str,
    result: dict[str, Any],
    provider_evidence: dict[str, Any],
) -> dict[str, Any]:
    if not all((project_id, draft_asset_version_id, review_asset_version_id, context_bundle_version_id)):
        raise KernelError("REVISION_INPUT_INVALID", "versioned revision lineage is required")
    from novel_forge.modules.review.diagnostics import open_diagnoses
    diagnoses = open_diagnoses(review)
    if review.get("diagnostic_contract_version") == "actionable-diagnostics.v1":
        from novel_forge.modules.review.diagnostics import prose_hash
        if (review.get("target_asset_version_id") != draft_asset_version_id
            or review.get("context_bundle_version_id") != context_bundle_version_id
            or review.get("target_text_hash") != prose_hash(str(draft.get("text") or ""))):
            raise KernelError("REVISION_DIAGNOSIS_STALE", "revision must consume diagnostics for its exact source candidate and Context")
    text = str(result.get("text") or "").strip()
    resolved = sorted({str(item) for item in result.get("resolved_issue_codes", []) if str(item).strip()})
    open_blocking = {
        str(item.get("code") or "")
        for item in diagnoses
        if item.get("severity") == "blocking"
        and item.get("status", "OPEN") == "OPEN"
        and item.get("qualification", "ELIGIBLE") == "ELIGIBLE"
    }
    if not text or not open_blocking.issubset(set(resolved)):
        raise KernelError(
            "CHAPTER_REVISION_INCOMPLETE",
            "revision must provide text and resolve every eligible blocking issue",
        )
    resolutions = [
        {
            "code": str(item.get("code") or ""),
            "review_issue_id": str(item.get("review_issue_id") or ""),
            "from_status": item.get("status", "OPEN"),
            "to_status": (
                "RESOLUTION_CLAIMED"
                if item.get("code") in resolved
                else item.get("status", "OPEN")
            ),
        }
        for item in diagnoses
    ]
    assertions = result.get("canon_assertions", [])
    if not isinstance(assertions, list) or any(not isinstance(item, dict) for item in assertions):
        raise KernelError("CHAPTER_MODEL_OUTPUT_INVALID", "canon_assertions must be objects")
    return {
        **reconcile_revision_composition(draft, result),
        "project_id": project_id,
        "chapter": draft["chapter"],
        "title": draft["title"],
        "text": text,
        "source_draft_version_id": draft_asset_version_id,
        "creative_execution": dict(draft.get("creative_execution") or {}),
        **({"author_design_guidance": dict(draft["author_design_guidance"])} if draft.get("author_design_guidance") else {}),
        "review_version_id": review_asset_version_id,
        "context_bundle_version_id": context_bundle_version_id,
        "resolved_issue_codes": resolved,
        "resolution_claimed_issue_codes": resolved,
        "issue_resolutions": resolutions,
        "canon_assertions": assertions,
        "provider_evidence": dict(provider_evidence),
        "revision_contract_version": "revision-domain-v3",
    }


def apply_quality_revision_result(
    *,
    project_id: str,
    revision: dict[str, Any],
    revision_asset_version_id: str,
    quality: dict[str, Any],
    quality_asset_version_id: str,
    revision_tasks: tuple[dict[str, Any], ...],
    revision_task_asset_version_ids: tuple[str, ...],
    context_bundle_version_id: str,
    result: dict[str, Any],
    provider_evidence: dict[str, Any],
) -> dict[str, Any]:
    if not all(
        (
            project_id,
            revision_asset_version_id,
            quality_asset_version_id,
            context_bundle_version_id,
        )
    ) or not revision_tasks or len(revision_tasks) != len(
        revision_task_asset_version_ids
    ):
        raise KernelError(
            "QUALITY_REVISION_INPUT_INVALID",
            "Quality correction requires versioned target, decision, task, and context lineage",
        )
    text = str(result.get("text") or "").strip()
    if not text:
        raise KernelError(
            "QUALITY_REVISION_INCOMPLETE", "Quality correction produced no revised text"
        )
    required_actions = list(quality.get("required_actions") or [])
    expected = {
        str(item.get("observation") or item.get("issue", {}).get("code") or "")
        for item in required_actions
    }
    frozen = {
        str(item.get("observation") or item.get("issue", {}).get("code") or "")
        for item in revision_tasks
    }
    expected.discard("")
    frozen.discard("")
    if not expected or not frozen or not frozen.issubset(expected) or any(
        str(item.get("status") or "OPEN") != "OPEN" for item in revision_tasks
    ):
        raise KernelError(
            "QUALITY_REVISION_TASK_CONFLICT",
            "frozen RevisionTasks are not active aggregate Quality required actions",
        )
    if str(quality.get("project_id") or "") != project_id or any(
        str(item.get("project_id") or "") != project_id
        or str(item.get("target_revision_asset_version_id") or "")
        != revision_asset_version_id
        for item in revision_tasks
    ):
        raise KernelError(
            "QUALITY_REVISION_LINEAGE_CONFLICT",
            "Quality correction task scope does not match its frozen target revision",
        )
    source_text = str(revision.get("text") or "").strip()
    minimum_preserved_ratio = 0.6
    if (
        len(source_text) >= 500
        and "chapter_length" not in frozen
        and len(text) < len(source_text) * minimum_preserved_ratio
    ):
        raise KernelError(
            "QUALITY_REVISION_SCOPE_INVALID",
            "bounded Quality correction cannot replace a complete chapter with a "
            "truncated summary or excerpt",
        )
    return {
        **revision,
        **reconcile_revision_composition(revision, result),
        "text": text,
        "source_revision_asset_version_id": revision_asset_version_id,
        "source_quality_asset_version_id": quality_asset_version_id,
        "quality_revision_task_asset_version_ids": list(
            revision_task_asset_version_ids
        ),
        "quality_action_observations": sorted(frozen),
        "context_bundle_version_id": context_bundle_version_id,
        "provider_evidence": dict(provider_evidence),
        "revision_contract_version": "quality-corrective-revision-v2",
    }


__all__ = ["apply_quality_revision_result", "apply_revision_result"]

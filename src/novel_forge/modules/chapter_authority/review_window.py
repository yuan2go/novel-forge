from __future__ import annotations

from typing import Any

from novel_forge.modules.book_authority.prose_sources import (
    require_frozen_prose_frontier,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.review.prose_window import (
    PRESERVATION_DIMENSIONS,
    freeze_review_window,
    validate_window,
)
from .contracts import (
    ChapterHandlerRequest,
    ChapterInputAsset,
    resolve_stage_context_token_budget,
)
from .provider_views import build_provider_context_view


def prepare_native_review(request: ChapterHandlerRequest, *, stage: str) -> tuple[Any, ...]:
    from dataclasses import replace
    from novel_forge.modules.review.knowledge import knowledge_review_targets

    target_type = {"review": "draft_chapter", "rereview": "draft_version"}[stage]
    binding = (request.command.get("chapter_sampling") or {}).get("generation_sample")
    if binding is None:
        target = request.require_input(target_type)
    else:
        target = request.require_input("chapter_provider_sample")
        if (binding != {"asset_version_id": target.asset_version_id, "content_hash": target.content_hash}
            or target.content.get("sampled_asset_type") != target_type
            or target.content.get("production_eligible") is not False):
            raise KernelError("QUALITY_REFERENCE_TARGET_INVALID", "reference review must retain its exact native generator sample")
        target = replace(target, content=target.content["sampled_output"])
    context = request.require_input("context_bundle")
    draft = target if stage == "review" else request.require_input("draft_chapter")
    review = request.require_input("review_report") if stage == "rereview" else None
    targets = knowledge_review_targets(context.content)
    window = prepare_review_window(request, target, context, review.content if review else None)
    payload = {**({"cross_chapter_window": window, "target_candidate_asset_version_id": target.asset_version_id} if window is not None else {}),
        "draft": target.content, "knowledge_review_targets": targets,
        "author_design_review_targets": draft.content.get("author_design_guidance") or {}}
    if review is not None:
        payload.update(original_draft=draft.content, review=review.content, revision=target.content)
    return target, context, targets, window, payload


def require_review_frontier(request: ChapterHandlerRequest) -> None:
    snapshot = (request.command.get("preparation_report") or {}).get(
        "accepted_prose_snapshot"
    )
    if snapshot is not None:
        if request.command.get("book_id") != snapshot.get("book_id"):
            raise KernelError(
                "CROSS_CHAPTER_REVIEW_SOURCE_INVALID", "Chapter and source Book differ"
            )
        require_frozen_prose_frontier(
            request.database_url,
            snapshot=snapshot,
            project_id=request.project_id,
            workspace_id=request.workspace_id,
            chapter=int(request.command["chapter"]),
        )


def prepare_review_window(
    request: ChapterHandlerRequest,
    draft: ChapterInputAsset,
    context: ChapterInputAsset,
    prior: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    snapshot = (request.command.get("preparation_report") or {}).get(
        "accepted_prose_snapshot"
    )
    if snapshot is None:
        if prior and prior.get("cross_chapter_window"):
            raise KernelError(
                "CROSS_CHAPTER_REVIEW_WINDOW_INVALID",
                "rereview lost its frozen source admission",
            )
        return None
    require_review_frontier(request)
    if prior is not None:
        window = prior.get("cross_chapter_window")
        if (
            not isinstance(window, dict)
            or window.get("snapshot_hash") != snapshot["snapshot_hash"]
        ):
            raise KernelError(
                "CROSS_CHAPTER_REVIEW_WINDOW_INVALID",
                "rereview must retain the original source coverage",
            )
        validate_window(window)
        return window
    protected = {
        "dimensions": list(PRESERVATION_DIMENSIONS),
        "context_bundle_asset_version_id": context.asset_version_id,
        "context_bundle_content_hash": context.content_hash,
        "memo_asset_version_id": (draft.content.get("creative_execution") or {}).get(
            "memo_asset_version_id", ""
        ),
        "approved_hard_constraints": [],
    }
    return freeze_review_window(
        snapshot,
        candidate_id=draft.asset_version_id,
        text=str(draft.content.get("text") or ""),
        context_token_budget=resolve_stage_context_token_budget(
            request.command, "review"
        ),
        protected_context=protected,
        required_context=build_provider_context_view("review", context.content, {}),
    )

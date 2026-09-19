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

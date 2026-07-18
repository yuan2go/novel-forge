from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError

from .contracts import ResolvedProductionAsset
from .policies import CONTINUING_CHAPTER_REQUIRED_ASSET_TYPES


TYPED_EMPTY_STATE_ASSET_TYPE = "typed_empty_state_snapshot"


@dataclass(frozen=True, slots=True)
class TypedEmptyStateSnapshot:
    project_id: str
    chapter: int
    state_kind: str
    logical_asset_type: str
    declared_empty: bool
    reason: str
    previous_chapter: int
    evidence: tuple[dict[str, Any], ...]
    contract_version: str = "typed-empty-state-snapshot-v1"


def validate_typed_empty_state(
    asset: ResolvedProductionAsset,
    *,
    project_id: str,
    requested_chapter: int,
    logical_asset_type: str,
) -> TypedEmptyStateSnapshot:
    if asset.asset_type != TYPED_EMPTY_STATE_ASSET_TYPE:
        raise KernelError(
            "TYPED_EMPTY_STATE_ASSET_TYPE_INVALID",
            "an explicit empty baseline must be a typed_empty_state_snapshot AssetVersion",
        )
    if asset.project_id != project_id:
        raise KernelError(
            "TYPED_EMPTY_STATE_CROSS_PROJECT",
            "typed empty state belongs to another project",
        )
    content = asset.content
    state_kind = str(content.get("state_kind") or content.get("logical_asset_type") or "")
    if state_kind not in CONTINUING_CHAPTER_REQUIRED_ASSET_TYPES:
        raise KernelError(
            "TYPED_EMPTY_STATE_KIND_INVALID",
            "typed empty state has an unsupported state_kind",
        )
    if state_kind != logical_asset_type:
        raise KernelError(
            "TYPED_EMPTY_STATE_KIND_MISMATCH",
            "typed empty state does not satisfy the requested logical state kind",
        )
    if content.get("declared_empty") is not True:
        raise KernelError(
            "TYPED_EMPTY_STATE_NOT_EMPTY",
            "typed empty state must explicitly declare declared_empty=true",
        )
    try:
        chapter = int(content.get("chapter"))
        previous_chapter = int(content.get("previous_chapter", chapter))
    except (TypeError, ValueError) as error:
        raise KernelError(
            "TYPED_EMPTY_STATE_CHAPTER_INVALID",
            "typed empty state must identify its previous chapter",
        ) from error
    if chapter != requested_chapter - 1 or previous_chapter != requested_chapter - 1:
        raise KernelError(
            "TYPED_EMPTY_STATE_CHAPTER_MISMATCH",
            "typed empty state may only declare the immediately preceding chapter empty",
        )
    if content.get("entries") not in (None, []):
        raise KernelError(
            "TYPED_EMPTY_STATE_HAS_ENTRIES",
            "typed empty state cannot contain non-empty state entries",
        )
    return TypedEmptyStateSnapshot(
        project_id=project_id,
        chapter=chapter,
        state_kind=state_kind,
        logical_asset_type=logical_asset_type,
        declared_empty=True,
        reason=str(content.get("reason") or "explicit first-baseline declaration"),
        previous_chapter=previous_chapter,
        evidence=tuple(dict(item) for item in content.get("evidence", [])),
        contract_version=str(
            content.get("contract_version") or "typed-empty-state-snapshot-v1"
        ),
    )


def project_typed_empty_state(
    asset: ResolvedProductionAsset,
    *,
    snapshot: TypedEmptyStateSnapshot,
) -> ResolvedProductionAsset:
    """Expose a persisted typed-empty AssetVersion through its logical state role."""
    structured_facts = [
        {
            "declared_empty": True,
            "state_kind": snapshot.state_kind,
            "chapter": snapshot.chapter,
            "reason": snapshot.reason,
            "source_typed_empty_state_asset_version_id": asset.asset_version_id,
        }
    ]
    return ResolvedProductionAsset(
        project_id=asset.project_id,
        asset_id=asset.asset_id,
        asset_version_id=asset.asset_version_id,
        asset_type=snapshot.logical_asset_type,
        content_hash=asset.content_hash,
        content={
            **asset.content,
            "type": "TypedEmptyStateSnapshot",
            "physical_asset_type": TYPED_EMPTY_STATE_ASSET_TYPE,
            "logical_asset_type": snapshot.logical_asset_type,
            "declared_empty": True,
            "entries": [],
            "safe_summary": (
                f"Explicitly empty {snapshot.logical_asset_type} baseline for "
                f"chapter {snapshot.chapter}."
            ),
            "structured_facts": structured_facts,
        },
        qualification=asset.qualification,
        selected_reason=(
            f"typed empty baseline for {snapshot.logical_asset_type}; "
            f"source AssetVersion {asset.asset_version_id}"
        ),
    )


__all__ = [
    "TYPED_EMPTY_STATE_ASSET_TYPE",
    "TypedEmptyStateSnapshot",
    "project_typed_empty_state",
    "validate_typed_empty_state",
]

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError

from .contracts import ResolvedProductionAsset

# Historical compatibility only. Production Preparation no longer selects or
# projects these records; Narrative State v2 starts from accepted ChapterOutcome
# and Book acceptance evidence instead of an operator-declared empty surrogate.
TYPED_EMPTY_STATE_ASSET_TYPE = "typed_empty_state_snapshot"
LEGACY_INITIALIZABLE_STATE_KINDS = frozenset(
    {
        "canon_snapshot",
        "character_state_snapshot",
        "relationship_state_snapshot",
        "timeline_snapshot",
        "foreshadow_snapshot",
        "promise_ledger_snapshot",
        "reward_ledger_snapshot",
        "world_rule_snapshot",
        "power_state_snapshot",
        "plot_thread_snapshot",
        "resource_state_snapshot",
    }
)


def initialize_typed_empty_state(
    *,
    project_id: str,
    operation_id: str,
    state_kind: str,
    previous_chapter: int,
    reason: str,
    absence_evidence_asset_version_id: str,
    absence_evidence: dict[str, object],
) -> dict[str, object]:
    if state_kind not in LEGACY_INITIALIZABLE_STATE_KINDS:
        raise ValueError("typed empty initializer state kind is unsupported")
    if absence_evidence.get("state_kind") != state_kind:
        raise ValueError("state absence evidence targets another state kind")
    if int(absence_evidence.get("previous_chapter", -1)) != previous_chapter:
        raise ValueError("state absence evidence targets another chapter")
    if absence_evidence.get("state_exists") is not False:
        raise ValueError("state absence evidence does not prove absence")
    reduction_status = str(absence_evidence.get("canon_reduction_status") or "")
    if reduction_status not in {"SUCCEEDED", "NOT_REQUIRED_PROJECT_INITIALIZATION"}:
        raise KernelError(
            "STATE_REDUCTION_INCOMPLETE",
            "failed or incomplete Canon Reduction cannot be replaced by an empty snapshot",
        )
    gate_id = str(absence_evidence.get("previous_final_release_gate_id") or "")
    if previous_chapter > 0 and not gate_id:
        raise ValueError("previous chapter final release gate evidence is required")
    return {
        "type": "TypedEmptyStateSnapshot",
        "project_id": project_id,
        "chapter": previous_chapter,
        "previous_chapter": previous_chapter,
        "state_kind": state_kind,
        "logical_asset_type": state_kind,
        "declared_empty": True,
        "entries": [],
        "reason": reason,
        "producer_operation_id": operation_id,
        "producer_definition": "chapter.state.initialize_empty",
        "previous_final_release_gate_id": gate_id,
        "initialization_reason": reason,
        "absence_evidence_asset_version_id": absence_evidence_asset_version_id,
        "absence_evidence": [dict(absence_evidence)],
        "contract_version": "typed-empty-state-snapshot-v2",
    }


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
    if (
        content.get("_authority_producer_verified") is not True
        or content.get("producer_definition") != "chapter.state.initialize_empty"
        or not str(content.get("producer_operation_id") or "")
    ):
        raise KernelError(
            "TYPED_EMPTY_STATE_PRODUCER_UNTRUSTED",
            "typed empty state was not materialized by the trusted initializer Operation",
        )
    state_kind = str(content.get("state_kind") or content.get("logical_asset_type") or "")
    if state_kind not in LEGACY_INITIALIZABLE_STATE_KINDS:
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
    "initialize_typed_empty_state",
    "project_typed_empty_state",
    "validate_typed_empty_state",
]

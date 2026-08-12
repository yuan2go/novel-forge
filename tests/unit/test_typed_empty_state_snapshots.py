from __future__ import annotations

from dataclasses import replace
import unittest

from novel_forge.modules.production_preparation.contracts import (
    ProductionPreparationRequest,
    ResolvedProductionAsset,
)
from novel_forge.modules.production_preparation.empty_state import (
    TYPED_EMPTY_STATE_ASSET_TYPE,
)
from novel_forge.modules.production_preparation.policies import (
    CONTINUING_CHAPTER_REQUIRED_ASSET_TYPES,
)
from novel_forge.modules.production_preparation.service import (
    ProductionPreparationService,
)


def _asset(asset_type: str) -> ResolvedProductionAsset:
    content: dict = {
        "type": asset_type,
        "chapter": 1,
        "safe_summary": f"Safe {asset_type} summary.",
        "structured_facts": [],
    }
    if asset_type == "chapter_plan":
        content.update(
            {
                "chapter": 2,
                "title": "Chapter Two",
                "premise": "The accepted state creates a new obligation.",
                "chapter_objective": "advance the obligation",
                "scene_sequence": [{"scene_id": "scene-1", "goal": "choose"}],
                "chapter_hook": "the cost becomes visible",
                "conflict_chain": ["promise collides with safety"],
                "emotional_curve": ["resolve", "fear", "choice"],
                "suspense_curve": ["question", "pressure", "new question"],
                "reader_promise_actions": ["progress"],
                "antagonist_pressure": "the safe path closes",
                "next_chapter_bridge": "a witness must answer",
            }
        )
    if asset_type == "story_state_snapshot":
        content.update(
            {
                "contract_version": "story-state-snapshot-v2",
                "book_id": "book-1",
                "accepted_through_chapter": 1,
                "_authority_acceptance_bound": True,
                "current_state": {},
            }
        )
    if asset_type == "canon_snapshot":
        content.update(
            {
                "contract_version": "canon-snapshot-v2",
                "book_id": "book-1",
                "accepted_through_chapter": 1,
                "_authority_acceptance_bound": True,
                "current_facts": [],
            }
        )
    return ResolvedProductionAsset(
        project_id="project-1",
        asset_id=f"asset:{asset_type}",
        asset_version_id=f"version:{asset_type}",
        asset_type=asset_type,
        content_hash=f"sha256:{asset_type}",
        content=content,
        qualification="ELIGIBLE",
        selected_reason="latest eligible authority version",
    )


def _typed_empty(state_kind: str) -> ResolvedProductionAsset:
    base = _asset(TYPED_EMPTY_STATE_ASSET_TYPE)
    return replace(
        base,
        asset_id=f"asset:empty:{state_kind}",
        asset_version_id=f"version:empty:{state_kind}",
        content={
            **base.content,
            "type": "TypedEmptyStateSnapshot",
            "state_kind": state_kind,
            "logical_asset_type": state_kind,
            "declared_empty": True,
            "previous_chapter": 1,
            "entries": [],
            "producer_definition": "chapter.state.initialize_empty",
            "_authority_producer_verified": True,
            "contract_version": "typed-empty-state-snapshot-v2",
        },
    )


class _Resolver:
    def __init__(self, rows: dict[str, list[ResolvedProductionAsset]]) -> None:
        self.rows = rows

    def resolve_all(self, *, project_id: str, asset_type: str, limit: int = 200):
        return tuple(
            item
            for item in self.rows.get(asset_type, ())[:limit]
            if item.project_id == project_id
        )

    def resolve_latest(self, *, project_id: str, asset_type: str):
        rows = self.resolve_all(project_id=project_id, asset_type=asset_type)
        return rows[0] if rows else None

    def resolve_override(self, *, project_id: str, asset_version_id: str):
        return next(
            item
            for rows in self.rows.values()
            for item in rows
            if item.project_id == project_id and item.asset_version_id == asset_version_id
        )


def _base_rows() -> dict[str, list[ResolvedProductionAsset]]:
    return {
        kind: [_asset(kind)]
        for kind in (
            "chapter_plan",
            "style_policy",
            "quality_rubric",
            "platform_profile",
        )
    }


def _request() -> ProductionPreparationRequest:
    return ProductionPreparationRequest(
        project_id="project-1",
        workspace_id="workspace-1",
        book_id="book-1",
        chapter=2,
        idempotency_key="chapter-2-state",
    )


class TypedEmptyStateSnapshotTests(unittest.TestCase):
    def test_continuing_contract_has_only_story_state_and_canon(self) -> None:
        self.assertEqual(
            CONTINUING_CHAPTER_REQUIRED_ASSET_TYPES,
            ("story_state_snapshot", "canon_snapshot"),
        )

    def test_typed_empty_cannot_impersonate_accepted_narrative_state(self) -> None:
        rows = _base_rows()
        rows[TYPED_EMPTY_STATE_ASSET_TYPE] = [
            _typed_empty(kind) for kind in CONTINUING_CHAPTER_REQUIRED_ASSET_TYPES
        ]

        result = ProductionPreparationService(_Resolver(rows)).prepare(_request())

        self.assertEqual(result.report.decision, "BLOCKED")
        self.assertEqual(
            set(result.report.missing_required_asset_types),
            set(CONTINUING_CHAPTER_REQUIRED_ASSET_TYPES),
        )

    def test_committed_v2_snapshots_are_selected_instead_of_empty_declarations(self) -> None:
        rows = _base_rows()
        rows.update(
            {kind: [_asset(kind)] for kind in CONTINUING_CHAPTER_REQUIRED_ASSET_TYPES}
        )
        rows[TYPED_EMPTY_STATE_ASSET_TYPE] = [
            _typed_empty(kind) for kind in CONTINUING_CHAPTER_REQUIRED_ASSET_TYPES
        ]

        result = ProductionPreparationService(_Resolver(rows)).prepare(_request())

        self.assertEqual(result.report.decision, "READY")
        assert result.command is not None
        self.assertNotIn(
            TYPED_EMPTY_STATE_ASSET_TYPE,
            {item.get("physical_asset_type") for item in result.command.context_candidates},
        )


if __name__ == "__main__":
    unittest.main()

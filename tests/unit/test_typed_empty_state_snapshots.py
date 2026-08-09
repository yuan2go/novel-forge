from __future__ import annotations

import unittest
from dataclasses import replace

from novel_forge.modules.command_kernel.errors import KernelError
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


def _asset(asset_type: str, *, chapter: int = 1, suffix: str = "") -> ResolvedProductionAsset:
    return ResolvedProductionAsset(
        project_id="project-1",
        asset_id=f"asset:{asset_type}:{suffix}",
        asset_version_id=f"version:{asset_type}:{suffix}",
        asset_type=asset_type,
        content_hash=f"sha256:{asset_type}:{chapter}:{suffix}",
        content={
            "type": asset_type,
            "chapter": chapter,
            "title": "Chapter Two" if asset_type == "chapter_plan" else "",
            "premise": "The first stateful continuation." if asset_type == "chapter_plan" else "",
            "chapter_objective": "advance the first stateful continuation" if asset_type == "chapter_plan" else "",
            "scene_sequence": [{"scene_id": "scene-1", "goal": "make a costly choice"}] if asset_type == "chapter_plan" else [],
            "chapter_hook": "the choice creates a new obligation" if asset_type == "chapter_plan" else "",
            "conflict_chain": ["promise collides with safety"] if asset_type == "chapter_plan" else [],
            "emotional_curve": ["resolve", "fear", "costly resolve"] if asset_type == "chapter_plan" else [],
            "suspense_curve": ["question", "pressure", "new obligation"] if asset_type == "chapter_plan" else [],
            "reader_promise_actions": ["test the opening promise"] if asset_type == "chapter_plan" else [],
            "antagonist_pressure": "the institution closes the safe path" if asset_type == "chapter_plan" else "",
            "next_chapter_bridge": "the obligation requires a new witness" if asset_type == "chapter_plan" else "",
            "safe_summary": f"Safe {asset_type} summary.",
            "structured_facts": [],
        },
        qualification="ELIGIBLE",
        selected_reason="latest eligible authority version",
    )


def _empty(state_kind: str, *, chapter: int = 1) -> ResolvedProductionAsset:
    base = _asset(TYPED_EMPTY_STATE_ASSET_TYPE, chapter=chapter, suffix=state_kind)
    return replace(
        base,
        content={
            **base.content,
            "type": "TypedEmptyStateSnapshot",
            "state_kind": state_kind,
            "logical_asset_type": state_kind,
            "declared_empty": True,
            "previous_chapter": chapter,
            "entries": [],
            "reason": "project explicitly starts this ledger empty",
            "producer_operation_id": f"operation:{state_kind}",
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
            item for item in self.rows.get(asset_type, ())[:limit]
            if item.project_id == project_id
        )

    def resolve_latest(self, *, project_id: str, asset_type: str):
        rows = self.resolve_all(project_id=project_id, asset_type=asset_type)
        return rows[0] if rows else None

    def resolve_override(self, *, project_id: str, asset_version_id: str):
        for rows in self.rows.values():
            for item in rows:
                if item.asset_version_id == asset_version_id and item.project_id == project_id:
                    return item
        raise ValueError("missing override")


def _base_rows() -> dict[str, list[ResolvedProductionAsset]]:
    return {
        "chapter_plan": [_asset("chapter_plan", chapter=2)],
        "style_policy": [_asset("style_policy")],
        "quality_rubric": [_asset("quality_rubric")],
        "platform_profile": [_asset("platform_profile")],
    }


class TypedEmptyStateSnapshotTests(unittest.TestCase):
    def test_all_ten_typed_empty_states_are_logical_manifest_inputs(self) -> None:
        rows = _base_rows()
        rows[TYPED_EMPTY_STATE_ASSET_TYPE] = [
            _empty(kind) for kind in CONTINUING_CHAPTER_REQUIRED_ASSET_TYPES
        ]
        result = ProductionPreparationService(_Resolver(rows)).prepare(
            ProductionPreparationRequest(
                project_id="project-1",
                workspace_id="workspace-1",
                chapter=2,
                idempotency_key="typed-empty-nine",
            )
        )

        self.assertEqual(result.report.decision, "READY")
        assert result.command is not None
        candidates = {
            item["asset_type"]: item for item in result.command.context_candidates
            if item.get("physical_asset_type") == TYPED_EMPTY_STATE_ASSET_TYPE
        }
        self.assertEqual(set(candidates), set(CONTINUING_CHAPTER_REQUIRED_ASSET_TYPES))
        self.assertTrue(
            all(item["structured_facts"][0]["declared_empty"] for item in candidates.values())
        )
        manifest_rows = result.report.production_input_manifest["selected_asset_versions"]
        typed_rows = [
            item for item in manifest_rows
            if item["physical_asset_type"] == TYPED_EMPTY_STATE_ASSET_TYPE
        ]
        self.assertEqual(len(typed_rows), 10)
        self.assertNotIn(
            TYPED_EMPTY_STATE_ASSET_TYPE,
            {item["asset_type"] for item in typed_rows},
        )

    def test_missing_state_is_not_equivalent_to_explicit_empty(self) -> None:
        rows = _base_rows()
        rows[TYPED_EMPTY_STATE_ASSET_TYPE] = [
            _empty(kind)
            for kind in CONTINUING_CHAPTER_REQUIRED_ASSET_TYPES
            if kind != "relationship_state_snapshot"
        ]
        result = ProductionPreparationService(_Resolver(rows)).prepare(
            ProductionPreparationRequest(
                project_id="project-1",
                workspace_id="workspace-1",
                chapter=2,
                idempotency_key="missing-relationship-empty",
            )
        )
        self.assertEqual(result.report.decision, "BLOCKED")
        self.assertIn(
            "relationship_state_snapshot", result.report.missing_required_asset_types
        )

    def test_wrong_chapter_typed_empty_is_rejected(self) -> None:
        rows = _base_rows()
        rows[TYPED_EMPTY_STATE_ASSET_TYPE] = [
            _empty(kind, chapter=0) for kind in CONTINUING_CHAPTER_REQUIRED_ASSET_TYPES
        ]
        with self.assertRaisesRegex(KernelError, "immediately preceding chapter"):
            ProductionPreparationService(_Resolver(rows)).prepare(
                ProductionPreparationRequest(
                    project_id="project-1",
                    workspace_id="workspace-1",
                    chapter=2,
                    idempotency_key="wrong-empty-chapter",
                )
            )

    def test_untrusted_asset_cannot_claim_an_empty_state(self) -> None:
        rows = _base_rows()
        forged = _empty("relationship_state_snapshot")
        rows[TYPED_EMPTY_STATE_ASSET_TYPE] = [
            replace(
                forged,
                content={**forged.content, "_authority_producer_verified": False},
            )
        ]
        with self.assertRaisesRegex(KernelError, "trusted initializer"):
            ProductionPreparationService(_Resolver(rows)).prepare(
                ProductionPreparationRequest(
                    project_id="project-1",
                    workspace_id="workspace-1",
                    chapter=2,
                    idempotency_key="forged-empty-state",
                )
            )

    def test_non_empty_snapshot_wins_over_typed_empty(self) -> None:
        rows = _base_rows()
        rows.update(
            {
                kind: [_asset(kind)]
                for kind in CONTINUING_CHAPTER_REQUIRED_ASSET_TYPES
            }
        )
        rows[TYPED_EMPTY_STATE_ASSET_TYPE] = [
            _empty(kind) for kind in CONTINUING_CHAPTER_REQUIRED_ASSET_TYPES
        ]
        result = ProductionPreparationService(_Resolver(rows)).prepare(
            ProductionPreparationRequest(
                project_id="project-1",
                workspace_id="workspace-1",
                chapter=2,
                idempotency_key="non-empty-wins",
            )
        )
        self.assertEqual(result.report.decision, "READY")
        assert result.command is not None
        self.assertNotIn(
            TYPED_EMPTY_STATE_ASSET_TYPE,
            {item.get("physical_asset_type") for item in result.command.context_candidates},
        )


if __name__ == "__main__":
    unittest.main()

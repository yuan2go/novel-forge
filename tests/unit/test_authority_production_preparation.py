from __future__ import annotations

import unittest
from dataclasses import replace

from novel_forge.modules.authority_security import (
    PrincipalType,
    TrustedPrincipalResolver,
)
from novel_forge.modules.production_preparation.contracts import (
    ProductionPreparationRequest,
    ResolvedProductionAsset,
)
from novel_forge.modules.production_preparation.service import ProductionPreparationService
from novel_forge.modules.production_preparation.policies import STAGE_PROFILES


class _Resolver:
    def __init__(self, assets: dict[str, ResolvedProductionAsset]) -> None:
        self.assets = assets

    def resolve_latest(self, *, project_id: str, asset_type: str):
        asset = self.assets.get(asset_type)
        if asset is not None and asset.project_id != project_id:
            return None
        return asset

    def resolve_all(self, *, project_id: str, asset_type: str, limit: int = 200):
        del limit
        asset = self.resolve_latest(project_id=project_id, asset_type=asset_type)
        return () if asset is None else (asset,)

    def resolve_override(self, *, project_id: str, asset_version_id: str):
        for asset in self.assets.values():
            if asset.asset_version_id == asset_version_id:
                if asset.project_id != project_id:
                    raise ValueError("cross-project override")
                return asset
        raise ValueError("missing override")


class _MultiResolver(_Resolver):
    def __init__(self, assets: dict[str, list[ResolvedProductionAsset]]) -> None:
        self.collections = assets
        super().__init__({key: values[0] for key, values in assets.items() if values})

    def resolve_all(self, *, project_id: str, asset_type: str, limit: int = 200):
        return tuple(
            item for item in self.collections.get(asset_type, [])[:limit]
            if item.project_id == project_id
        )

    def resolve_override(self, *, project_id: str, asset_version_id: str):
        for values in self.collections.values():
            for asset in values:
                if asset.asset_version_id == asset_version_id:
                    if asset.project_id != project_id:
                        raise ValueError("cross-project override")
                    return asset
        raise ValueError("missing override")


def _asset(asset_type: str, *, project_id: str = "project-1") -> ResolvedProductionAsset:
    content = {
        "type": asset_type,
        "chapter": 1,
        "safe_summary": f"Safe {asset_type} summary.",
        "structured_facts": [],
    }
    if asset_type == "operator_checklist":
        content["structured_facts"] = [{"key": "completed", "value": True}]
    if asset_type == "operator_approval":
        content["structured_facts"] = [{"key": "approved", "value": True}]
    if asset_type == "chapter_plan":
        content.update(
            {
                "title": "Qualified plan",
                "premise": "A costly choice advances the promise.",
                "chapter_objective": "Force a consequential choice.",
                "scene_sequence": [{"scene_id": "scene-1", "goal": "choose"}],
                "chapter_hook": "The cost creates a new obligation.",
                "conflict_chain": [{"pressure": "public consequence"}],
                "reader_promise_actions": [{"promise_id": "promise-1", "action": "progress"}],
                "protagonist_charm_mechanism": "accepts a cost for another person",
                "information_reveals": [{"fact": "the promise has a hidden price"}],
                "next_chapter_bridge": "The obligation becomes the next conflict.",
                "emotional_curve": ["resolve", "doubt", "cost"],
                "suspense_curve": ["question", "pressure", "new question"],
                "antagonist_pressure": {"mechanism": "tightens the deadline"},
            }
        )
    return ResolvedProductionAsset(
        project_id=project_id,
        asset_id=f"asset:{asset_type}",
        asset_version_id=f"version:{asset_type}",
        asset_type=asset_type,
        content_hash=f"sha256:{asset_type}",
        content=content,
        qualification="ELIGIBLE",
        selected_reason="latest eligible authority version",
    )


class ProductionPreparationTests(unittest.TestCase):
    def test_project_knowledge_pack_is_optional_unless_capability_requires_it(self) -> None:
        assets = {
            kind: _asset(kind)
            for kind in (
                "chapter_plan",
                "style_policy",
                "quality_rubric",
                "platform_profile",
            )
        }
        service = ProductionPreparationService(_Resolver(assets))
        optional = service.prepare(
            ProductionPreparationRequest(
                project_id="project-1",
                workspace_id="workspace-1",
                chapter=1,
                idempotency_key="knowledge-optional",
            )
        )
        required = service.prepare(
            ProductionPreparationRequest(
                project_id="project-1",
                workspace_id="workspace-1",
                chapter=1,
                idempotency_key="knowledge-required",
                capability_required_asset_types=("knowledge_pack",),
            )
        )

        self.assertEqual(optional.report.decision, "READY")
        self.assertEqual(required.report.decision, "BLOCKED")
        self.assertIn(
            "knowledge_pack", required.report.missing_required_asset_types
        )

    def test_previous_production_manifest_is_not_recursive_chapter_context(self) -> None:
        assets = {
            kind: _asset(kind)
            for kind in (
                "chapter_plan",
                "style_policy",
                "quality_rubric",
                "platform_profile",
                "production_input_manifest",
            )
        }
        result = ProductionPreparationService(_Resolver(assets)).prepare(
            ProductionPreparationRequest(
                project_id="project-1",
                workspace_id="workspace-1",
                chapter=1,
                idempotency_key="non-recursive-manifest",
            )
        )

        self.assertEqual(result.report.decision, "READY")
        self.assertNotIn(
            "production_input_manifest",
            {item["asset_type"] for item in result.command.context_candidates},
        )

    def test_ready_report_freezes_context_and_versions(self) -> None:
        assets = {
            kind: _asset(kind)
            for kind in (
                "chapter_plan", "style_policy", "quality_rubric",
                "platform_profile", "world_bible",
            )
        }
        result = ProductionPreparationService(_Resolver(assets)).prepare(
            ProductionPreparationRequest(
                project_id="project-1",
                workspace_id="workspace-1",
                chapter=1,
                title_override="Chapter One",
                premise_override="A costly promise.",
                idempotency_key="chapter-1",
            )
        )

        self.assertEqual(result.report.decision, "READY")
        self.assertIn("version:chapter_plan", result.report.selected_asset_version_ids)
        self.assertEqual(
            result.command.context_version_refs["chapter_plan_version"],
            "version:chapter_plan",
        )
        self.assertTrue(result.command.context_candidates)
        style_candidate = next(
            item for item in result.command.context_candidates
            if item["asset_type"] == "style_policy"
        )
        self.assertEqual(style_candidate["project_id"], "project-1")
        self.assertTrue(style_candidate["safe_summary"])
        self.assertIn(
            "chapter_plan",
            {item["asset_type"] for item in result.command.context_candidates},
        )
        self.assertEqual(
            result.report.production_input_manifest["platform_profile_version_id"],
            "version:platform_profile",
        )

    def test_wrong_chapter_plan_is_blocked(self) -> None:
        assets = {
            kind: _asset(kind)
            for kind in (
                "chapter_plan", "style_policy", "quality_rubric",
                "platform_profile",
            )
        }
        assets["chapter_plan"] = replace(
            assets["chapter_plan"],
            content={**assets["chapter_plan"].content, "chapter": 2},
        )
        result = ProductionPreparationService(_Resolver(assets)).prepare(
            ProductionPreparationRequest(
                project_id="project-1", workspace_id="workspace-1", chapter=1,
                idempotency_key="wrong-plan",
            )
        )
        self.assertEqual(result.report.decision, "BLOCKED")
        self.assertIn(
            {"asset_type": "chapter_plan", "code": "CHAPTER_PLAN_TARGET_MISMATCH"},
            result.report.blocked_assets,
        )

    def test_second_chapter_without_canon_baseline_is_blocked_with_repair(self) -> None:
        assets = {
            kind: _asset(kind)
            for kind in (
                "chapter_plan", "style_policy", "quality_rubric",
                "platform_profile",
            )
        }
        result = ProductionPreparationService(_Resolver(assets)).prepare(
            ProductionPreparationRequest(
                project_id="project-1",
                workspace_id="workspace-1",
                chapter=2,
                idempotency_key="chapter-2",
            )
        )

        self.assertEqual(result.report.decision, "BLOCKED")
        self.assertIn("canon_snapshot", result.report.missing_required_asset_types)
        self.assertTrue(any("Canon" in action for action in result.report.repair_actions))
        self.assertIsNone(result.command)

    def test_story_state_snapshot_is_required_for_continuing_chapter(self) -> None:
        assets = {
            kind: _asset(kind)
            for kind in (
                "chapter_plan",
                "style_policy",
                "quality_rubric",
                "platform_profile",
                "canon_snapshot",
                "character_state_snapshot",
                "relationship_state_snapshot",
                "timeline_snapshot",
                "foreshadow_snapshot",
                "promise_ledger_snapshot",
                "reward_ledger_snapshot",
                "world_rule_snapshot",
                "power_state_snapshot",
            )
        }
        assets["chapter_plan"] = replace(
            assets["chapter_plan"],
            content={**assets["chapter_plan"].content, "chapter": 2},
        )

        result = ProductionPreparationService(_Resolver(assets)).prepare(
            ProductionPreparationRequest(
                project_id="project-1",
                workspace_id="workspace-1",
                chapter=2,
                idempotency_key="missing-story-state",
            )
        )

        self.assertIn(
            "story_state_snapshot", result.report.missing_required_asset_types
        )

    def test_cross_project_override_fails_closed(self) -> None:
        assets = {"chapter_plan": _asset("chapter_plan", project_id="project-2")}
        with self.assertRaisesRegex(ValueError, "cross-project"):
            ProductionPreparationService(_Resolver(assets)).prepare(
                ProductionPreparationRequest(
                    project_id="project-1",
                    workspace_id="workspace-1",
                    chapter=1,
                    explicit_asset_version_overrides={
                        "chapter_plan": "version:chapter_plan"
                    },
                    idempotency_key="chapter-1",
                )
            )

    def test_api_actor_is_not_a_trusted_principal_source(self) -> None:
        principal = TrustedPrincipalResolver(
            environment="test",
            configured_local_operator_id="trusted-local",
        ).resolve_api_principal(claimed_actor_id="attacker-supplied")

        self.assertEqual(principal.principal_id, "trusted-local")
        self.assertEqual(principal.principal_type, PrincipalType.LOCAL_OPERATOR)
        self.assertNotEqual(principal.principal_id, "attacker-supplied")
        self.assertTrue(principal.allows("chapter.authority.execute", "project-1"))
        self.assertTrue(
            principal.allows("content.operation:theme.question.create", "project-1")
        )
        self.assertTrue(
            principal.allows("story_planning.authority.execute", "project-1")
        )
        worker = TrustedPrincipalResolver(environment="test").resolve_worker_principal(
            "book-worker"
        )
        self.assertTrue(
            worker.allows("story_planning.authority.execute", "project-1")
        )

    def test_production_requires_configured_trusted_principal(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "trusted local operator"):
            TrustedPrincipalResolver(environment="production").resolve_api_principal()

    def test_v2_selects_multiple_character_and_relationship_states(self) -> None:
        required = (
            "chapter_plan", "style_policy", "quality_rubric", "platform_profile",
            "story_state_snapshot", "canon_snapshot", "timeline_snapshot",
            "foreshadow_snapshot",
            "promise_ledger_snapshot", "reward_ledger_snapshot", "world_rule_snapshot",
            "power_state_snapshot",
        )
        collections = {kind: [_asset(kind)] for kind in required}
        collections["chapter_plan"][0] = replace(
            collections["chapter_plan"][0],
            content={**collections["chapter_plan"][0].content, "chapter": 2},
        )
        collections["character_state_snapshot"] = [
            replace(
                _asset("character_state_snapshot"),
                asset_id=f"asset:character:{index}",
                asset_version_id=f"version:character:{index}",
                content={**_asset("character_state_snapshot").content, "entity_id": f"character-{index}"},
            )
            for index in (1, 2)
        ]
        collections["relationship_state_snapshot"] = [
            replace(
                _asset("relationship_state_snapshot"),
                asset_id=f"asset:relationship:{index}",
                asset_version_id=f"version:relationship:{index}",
                content={**_asset("relationship_state_snapshot").content, "entity_id": f"pair-{index}"},
            )
            for index in (1, 2)
        ]
        result = ProductionPreparationService(_MultiResolver(collections)).prepare(
            ProductionPreparationRequest(
                project_id="project-1", workspace_id="workspace-1", chapter=2,
                title_override="Chapter Two", premise_override="State carries forward.",
                idempotency_key="chapter-2-multi",
            )
        )
        self.assertEqual(result.report.decision, "READY")
        manifest = result.report.production_input_manifest
        self.assertEqual(
            sorted(manifest["entity_scopes"]["character_state_snapshot"]),
            ["character-1", "character-2"],
        )
        self.assertEqual(
            sorted(manifest["entity_scopes"]["relationship_state_snapshot"]),
            ["pair-1", "pair-2"],
        )

    def test_current_collection_snapshot_is_not_blocked_by_historical_versions(self) -> None:
        state_types = (
            "story_state_snapshot",
            "canon_snapshot",
            "character_state_snapshot",
            "relationship_state_snapshot",
            "timeline_snapshot",
            "foreshadow_snapshot",
            "promise_ledger_snapshot",
            "reward_ledger_snapshot",
            "world_rule_snapshot",
            "power_state_snapshot",
        )
        collections = {
            kind: [_asset(kind)]
            for kind in (
                "chapter_plan",
                "style_policy",
                "quality_rubric",
                "platform_profile",
                *state_types,
            )
        }
        collections["chapter_plan"][0] = replace(
            collections["chapter_plan"][0],
            content={**collections["chapter_plan"][0].content, "chapter": 3},
        )
        for state_type in state_types:
            current = collections[state_type][0]
            collections[state_type][0] = replace(
                current,
                asset_id=f"asset:{state_type}:chapter-2",
                asset_version_id=f"version:{state_type}:chapter-2",
                content={**current.content, "chapter": 2},
            )
        for state_type in (
            "character_state_snapshot",
            "relationship_state_snapshot",
            "foreshadow_snapshot",
        ):
            historical = _asset(state_type)
            collections[state_type].append(
                replace(
                    historical,
                    asset_id=f"asset:{state_type}:chapter-1",
                    asset_version_id=f"version:{state_type}:chapter-1",
                    content={**historical.content, "chapter": 1},
                )
            )

        result = ProductionPreparationService(_MultiResolver(collections)).prepare(
            ProductionPreparationRequest(
                project_id="project-1",
                workspace_id="workspace-1",
                chapter=3,
                title_override="Chapter Three",
                premise_override="Current state carries forward after replan.",
                idempotency_key="chapter-3-current-state",
            )
        )

        self.assertEqual(result.report.decision, "READY")
        self.assertEqual(result.report.blocked_assets, ())
        for state_type in (
            "character_state_snapshot",
            "relationship_state_snapshot",
            "foreshadow_snapshot",
        ):
            self.assertIn(
                f"version:{state_type}:chapter-2",
                result.report.selected_asset_version_ids,
            )
            self.assertEqual(
                result.report.production_input_manifest["rejection_reasons"][
                    f"version:{state_type}:chapter-1"
                ],
                "HISTORICAL_SNAPSHOT_CHAPTER_MISMATCH",
            )

    def test_relationship_snapshot_is_required_for_continuing_chapter(self) -> None:
        assets = {
            kind: _asset(kind)
            for kind in (
                "chapter_plan", "style_policy", "quality_rubric", "platform_profile",
                "canon_snapshot", "character_state_snapshot", "timeline_snapshot",
                "foreshadow_snapshot", "promise_ledger_snapshot", "reward_ledger_snapshot",
                "world_rule_snapshot", "power_state_snapshot",
            )
        }
        assets["chapter_plan"] = replace(
            assets["chapter_plan"], content={**assets["chapter_plan"].content, "chapter": 2}
        )
        result = ProductionPreparationService(_Resolver(assets)).prepare(
            ProductionPreparationRequest(
                project_id="project-1", workspace_id="workspace-1", chapter=2,
                idempotency_key="missing-relationship",
            )
        )
        self.assertIn("relationship_state_snapshot", result.report.missing_required_asset_types)

    def test_stage_profiles_have_distinct_allowed_and_required_contracts(self) -> None:
        draft = STAGE_PROFILES["draft"]
        review = STAGE_PROFILES["review"]
        quality = STAGE_PROFILES["quality"]

        self.assertNotIn("review_rule", draft.allowed_asset_types)
        self.assertIn("review_rule", review.allowed_asset_types)
        self.assertIn("structural_quality_report", draft.allowed_asset_types)
        self.assertIn("structural_quality_report", draft.evidence_only_types)
        self.assertIn("structural_quality_report", quality.allowed_asset_types)
        self.assertIn("draft_version", review.required_asset_types)
        self.assertIn("re_review_report", quality.required_asset_types)


if __name__ == "__main__":
    unittest.main()

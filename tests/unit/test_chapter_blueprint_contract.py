from pathlib import Path
import json
import os
import sys
import tempfile
import unittest
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.model_adapters.mock import MockModelAdapter
from novel_forge.modules.chapter_plan import service as chapter_plan_service
from novel_forge.modules.context_builder import create_context_build_plan, create_context_bundle
from novel_forge.modules.drafting import service as drafting_service
from novel_forge.schemas import CharacterCard, KnowledgeCard, MaterialCard, Outline, WorldBible, WritingTemplate
from novel_forge.storage.local import LocalStorage


class ChapterBlueprintContractTests(unittest.TestCase):
    def setUp(self):
        self._previous_model_provider = os.environ.get("NOVEL_FORGE_MODEL_PROVIDER")
        os.environ["NOVEL_FORGE_MODEL_PROVIDER"] = "mock"

    def tearDown(self):
        if self._previous_model_provider is None:
            os.environ.pop("NOVEL_FORGE_MODEL_PROVIDER", None)
        else:
            os.environ["NOVEL_FORGE_MODEL_PROVIDER"] = self._previous_model_provider

    def test_mock_fallback_chapter_plan_gets_blueprint_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            outline_path = _outline(storage)

            plan_path = chapter_plan_service.generate_chapter_plan(storage, str(outline_path), model=MockModelAdapter(), chapter=1)
            plan = storage.read_asset(plan_path)
            content = plan.content

            self.assertEqual(content["chapter_blueprint_contract"]["contract_version"], "chapter-blueprint-contract-v1")
            self.assertEqual(content["blueprint_quality_gate"]["status"], "passed")
            self.assertGreaterEqual(len(content["scene_beats"]), 3)
            self.assertTrue(all(item["scene_goal"] for item in content["scene_beats"]))
            self.assertTrue(content["conflict_beats"])
            self.assertTrue(content["info_release_points"])
            self.assertTrue(content["hook_plan"]["opening_hook"])
            self.assertTrue(content["hook_plan"]["closing_hook"])
            self.assertTrue(content["emotion_curve"])
            self.assertTrue(content["payoff_target"]["local_payoff"])
            self.assertEqual(plan.metadata["chapter_blueprint_contract_version"], "chapter-blueprint-contract-v1")
            self.assertEqual(plan.metadata["chapter_blueprint_gate_status"], "passed")
            versions = [storage.read_asset(path) for path in storage.list_json("chapter_plans") if storage.read_json(path).get("type") == "chapter_plan_version"]
            self.assertTrue(versions)
            self.assertEqual(versions[-1].content["chapter_blueprint_contract"]["contract_version"], "chapter-blueprint-contract-v1")
            self.assertTrue(versions[-1].content["scene_beats"])

    def test_structured_model_blueprint_fields_are_normalized_and_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            outline_path = _outline(storage)

            plan_path = chapter_plan_service.generate_chapter_plan(storage, str(outline_path), model=StructuredChapterPlanModel(), chapter=1)
            content = storage.read_asset(plan_path).content

            self.assertEqual(content["scene_beats"][0]["scene_goal"], "open with the missing ledger seal")
            self.assertEqual(content["scene_beats"][0]["conflict_pressure"], "archive guards close the room")
            self.assertEqual(content["conflict_beats"][0]["choice"], "take public blame or lose the witness")
            self.assertEqual(content["info_release_points"][0]["timing"], "opening")
            self.assertEqual(content["hook_plan"]["closing_hook"], "the seal matches the protagonist family mark")
            self.assertEqual(content["emotion_curve"][-1]["pressure_level"], 5)
            self.assertEqual(content["payoff_target"]["withheld_question"], "who forged the family mark")
            self.assertEqual(content["blueprint_quality_gate"]["status"], "passed")

    def test_drafting_receives_and_persists_chapter_blueprint_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            outline_path = _outline(storage)
            plan_path = chapter_plan_service.generate_chapter_plan(storage, str(outline_path), model=StructuredChapterPlanModel(), chapter=1)
            bundle = _context_bundle(storage, plan_path)
            draft_model = SpyDraftModel()

            draft_path = drafting_service.draft(storage, str(plan_path), model=draft_model, context_bundle_path=bundle["path"], post_quality_loop=False)
            draft = storage.read_asset(draft_path)

            self.assertTrue(draft_model.context)
            self.assertEqual(draft_model.context["plan"]["chapter_blueprint_contract"]["contract_version"], "chapter-blueprint-contract-v1")
            self.assertEqual(draft_model.context["plan"]["scene_beats"][0]["scene_goal"], "open with the missing ledger seal")
            self.assertEqual(draft.content["chapter_plan_blueprint"]["contract"]["contract_version"], "chapter-blueprint-contract-v1")
            self.assertEqual(draft.content["chapter_blueprint_gate"]["status"], "passed")
            self.assertEqual(draft.metadata["chapter_blueprint_gate_status"], "passed")


class StructuredChapterPlanModel:
    name = "structured-chapter-plan-test-model"

    def generate(self, prompt: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        packet = {
            "title": "Chapter 2 plan",
            "objective": "force the protagonist to act before the public hearing",
            "beats": ["open with the missing ledger seal", "pressure the witness", "trade safety for proof", "close on family mark"],
            "hook": "the seal matches the protagonist family mark",
            "word_budget": {"target": 2600, "min": 1900, "max": 3300},
            "conflict": "archive guards close the room",
            "scene_beats": [
                {
                    "scene_goal": "open with the missing ledger seal",
                    "protagonist_action": "breaks procedure to inspect the seal",
                    "conflict_pressure": "archive guards close the room",
                    "turn": "the witness denies seeing the seal",
                    "payoff": "ledger proof becomes physical",
                    "exit_hook": "seal wax carries a forbidden mark",
                },
                {
                    "scene_goal": "pressure the witness",
                    "protagonist_action": "offers a public confession bargain",
                    "conflict_pressure": "the witness risks exile",
                    "turn": "the witness names a dead clerk",
                    "payoff": "the dead clerk becomes the next lead",
                    "exit_hook": "guard captain recognizes the name",
                },
                {
                    "scene_goal": "trade safety for proof",
                    "protagonist_action": "takes public blame to keep the proof",
                    "conflict_pressure": "family reputation is exposed",
                    "turn": "the seal matches the family mark",
                    "payoff": "protagonist owns the cost",
                    "exit_hook": "the family mark points home",
                },
            ],
            "conflict_beats": [
                {
                    "pressure": "archive guards close the room",
                    "choice": "take public blame or lose the witness",
                    "cost": "family reputation becomes suspect",
                    "reversal": "proof implicates home",
                }
            ],
            "information_points": ["the seal is fresh", "the dead clerk had access"],
            "info_release_points": [{"point": "the seal is fresh", "timing": "opening", "purpose": "force inspection", "withheld": "who stamped it"}],
            "hook_plan": {
                "opening_hook": "a fresh seal appears on an old ledger",
                "midpoint_turn": "the witness names a dead clerk",
                "closing_hook": "the seal matches the protagonist family mark",
                "long_hook_link": "family involvement mystery",
                "next_chapter_question": "who forged the family mark",
            },
            "emotion_curve": [
                {"position": "opening", "target_emotion": "alarm", "pressure_level": 2},
                {"position": "build", "target_emotion": "dread", "pressure_level": 3},
                {"position": "turn", "target_emotion": "shock", "pressure_level": 4},
                {"position": "ending", "target_emotion": "urgent dread", "pressure_level": 5},
            ],
            "payoff_target": {
                "local_payoff": "ledger proof becomes physical",
                "promise_payoff": "bureaucratic pressure changes action",
                "withheld_question": "who forged the family mark",
            },
            "quality_targets": ["causal_chain", "chapter_hook"],
            "reader_promise": "a public institution hides a family cost",
            "volume_goal": "prove the archive conspiracy has personal stakes",
            "pleasure_beats": ["pressure", "choice", "cost", "reveal"],
            "long_hook_progress": ["family involvement mystery"],
            "platform_pacing": ["clear opening pressure", "chapter-end hook"],
            "creative_strategy_constraints": ["show through action"],
            "continuity_checks": ["do not contradict family status"],
            "feedback_constraints": [],
            "risk_controls": ["no copied source prose"],
        }
        return {"model": self.name, "text": json.dumps(packet, ensure_ascii=False)}


class SpyDraftModel:
    name = "spy-draft-test-model"

    def __init__(self) -> None:
        self.context: dict[str, Any] = {}

    def generate(self, prompt: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        self.context = context or {}
        return {
            "model": self.name,
            "text": "林乔按下新鲜封蜡，先承认越权，再逼证人说出死去书吏的名字。守卫封门时，她看见封蜡纹路正是家族暗记，下一步只能回家查问。",
        }


def _outline(storage: LocalStorage) -> Path:
    return storage.write_asset_auto(
        Outline(
            title="Blueprint outline",
            content={
                "acts": [
                    {
                        "act": 1,
                        "goal": "prove the archive conspiracy through public cost",
                        "turn": "a family mark appears on the forged ledger",
                        "chapters": [
                            {"chapter": 1, "promise": "archive pressure", "hook": "ledger seal appears"},
                            {"chapter": 2, "promise": "family cost", "hook": "family mark appears"},
                        ],
                    }
                ]
            },
            metadata={"project_id": "chapter-blueprint-test"},
        )
    )


def _context_bundle(storage: LocalStorage, plan_path: Path) -> dict[str, Any]:
    plan = create_context_build_plan(storage, plan_path, query="archive family seal pressure blueprint", context_profile="prose")
    assets = [
        storage.write_asset_auto(
            CharacterCard(
                title="林乔",
                content={"role": "protagonist", "goal": "prove archive conspiracy through public cost"},
                metadata={"project_id": "chapter-blueprint-test"},
            )
        ),
        storage.write_asset_auto(
            WorldBible(
                title="Archive city",
                content={"rules": ["public records create legal pressure"], "institutions": ["archive hall"]},
                metadata={"project_id": "chapter-blueprint-test"},
            )
        ),
        storage.write_asset_auto(
            KnowledgeCard(
                title="Institutional pressure mechanism",
                content={"principle": "turn rules into visible costs and choices"},
                metadata={"project_id": "chapter-blueprint-test"},
            )
        ),
        storage.write_asset_auto(
            MaterialCard(
                title="Ledger seal material",
                content={"pattern": "physical proof forces a public decision"},
                metadata={"project_id": "chapter-blueprint-test"},
            )
        ),
        storage.write_asset_auto(
            WritingTemplate(
                title="Chapter hook template",
                content={"structure": ["pressure", "choice", "cost", "closing hook"]},
                metadata={"project_id": "chapter-blueprint-test"},
            )
        ),
    ]
    data = storage.read_json(storage.root / plan["path"])
    data["content"]["candidate_assets"] = [_candidate(storage, path) for path in assets]
    storage.write_json(storage.root / plan["path"], data)
    return create_context_bundle(storage, plan["path"])


def _candidate(storage: LocalStorage, path: Path) -> dict[str, Any]:
    asset = storage.read_asset(path)
    categories_by_type = {
        "character_card": ["characters"],
        "world_bible": ["worldbuilding"],
        "knowledge_card": ["knowledge_cards"],
        "material_card": ["material_cards"],
        "writing_template": ["writing_templates"],
    }
    return {
        "asset_id": asset.id,
        "path": str(path.relative_to(storage.root)),
        "type": asset.type,
        "title": asset.title,
        "categories": categories_by_type.get(asset.type, ["material_cards"]),
        "score": 0.99,
        "ranker": "unit-test",
        "project_id": str(asset.metadata.get("project_id", "")),
        "workspace_path": str(asset.metadata.get("workspace_path", "")),
        "token_estimate": 24,
        "summary": f"{asset.title}: {asset.content}",
        "copyright": {"eligible": True, "risk_level": "low", "signals": []},
        "selected_by_default": True,
    }


if __name__ == "__main__":
    unittest.main()

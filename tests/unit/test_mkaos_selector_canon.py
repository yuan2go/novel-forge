from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.mkaos import (
    build_knowledge_pack,
    canon_conflict_to_issue_candidate,
    check_canon_conflict,
    create_knowledge_card,
    create_usage_binding,
    record_review_feedback,
    apply_weight_update,
)
from novel_forge.schemas import CharacterCard
from novel_forge.storage.local import LocalStorage


class MkaosSelectorCanonTests(unittest.TestCase):
    def test_selector_respects_feedback_quality_and_weight(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            weaker = _knowledge(storage, "selector-p", "制度解释卡", quality=0.75, weight=1.0)
            stronger = _knowledge(storage, "selector-p", "行动成本卡", quality=0.75, weight=1.0)
            for card in [weaker, stronger]:
                create_usage_binding(
                    storage,
                    card["asset"]["id"],
                    {"flow": "prose", "usage_type": "optional", "input_role": "optional", "priority": 30},
                )

            record_review_feedback(storage, {"project_id": "selector-p", "knowledge_id": stronger["asset"]["id"], "flow": "prose", "delta": 0.2, "reason": "human_effective"})
            apply_weight_update(storage, {"project_id": "selector-p", "knowledge_id": stronger["asset"]["id"], "flow": "prose", "delta": 0.3, "reason": "weight_proof"})
            pack = build_knowledge_pack(storage, {"flow": "prose", "project_id": "selector-p", "knowledge_budget": {"max_core_knowledge": 2}})
            concepts = [item["concept_name"] for item in pack["asset"]["content"]["pack_items"]]

            self.assertEqual(concepts[0], "行动成本卡")
            first = pack["asset"]["content"]["pack_items"][0]
            self.assertGreater(first["selector_decision"]["feedback_delta"], 0)
            self.assertGreater(first["selector_decision"]["weight"], 1.0)
            self.assertIn("quality_score", pack["asset"]["content"]["selector_policy"]["scoring"])

    def test_selector_respects_risk_exclusion_and_project_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            low = _knowledge(storage, "selector-risk", "低风险卡", risk_level="low", quality=0.7, weight=1.0)
            high = _knowledge(storage, "selector-risk", "高风险卡", risk_level="high", quality=1.0, weight=3.0)
            other = _knowledge(storage, "selector-other", "其他项目卡", quality=1.0, weight=5.0)
            for card in [low, high, other]:
                create_usage_binding(
                    storage,
                    card["asset"]["id"],
                    {"flow": "outline", "usage_type": "required", "input_role": "required", "priority": 10},
                )

            pack = build_knowledge_pack(
                storage,
                {
                    "flow": "outline",
                    "project_id": "selector-risk",
                    "source_policy": {"exclude_risk_levels": ["high", "critical"]},
                },
            )
            ids = {item["knowledge_id"] for item in pack["asset"]["content"]["pack_items"]}

            self.assertIn(low["asset"]["id"], ids)
            self.assertNotIn(high["asset"]["id"], ids)
            self.assertNotIn(other["asset"]["id"], ids)
            self.assertEqual(pack["asset"]["content"]["selector_rejections"][0]["reason"], "risk_excluded_by_source_policy")

    def test_canon_conflict_returns_structured_result_and_issue_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            character = CharacterCard(
                title="阿照",
                content={
                    "role": "主角盟友",
                    "external_goal": "守住账册",
                    "internal_need": "确认自己能承担代价",
                    "motivation_chain": ["保护证据", "阻止豪强灭证"],
                    "canonical_name": "阿照",
                    "status": "alive",
                },
                metadata={"project_id": "canon-p"},
            )
            storage.write_asset("characters", character)

            result = check_canon_conflict(
                storage,
                {
                    "project_id": "canon-p",
                    "target_asset_id": "draft-1",
                    "target_asset_type": "draft_chapter",
                    "artifact_text": "阿照死了，飞天税票再次出现。",
                    "canon": {
                        "source": "payload",
                        "arcs": [{"arc_id": "tax-arc", "status": "active"}],
                        "foreshadowing": [{"thread_id": "seal-clue", "status": "paid_off"}],
                        "rules": [{"name": "低魔写实规则", "forbidden_terms": ["飞天税票"], "source_asset_id": "world-rule-1"}],
                    },
                    "claims": [
                        {"arc_id": "tax-arc", "key": "status", "value": "closed"},
                        {"thread_id": "seal-clue", "key": "status", "value": "developing"},
                    ],
                },
            )

            self.assertFalse(result["passed"])
            self.assertGreaterEqual(len(result["issues"]), 3)
            self.assertTrue(all(item["blocking"] for item in result["issue_candidates"]))
            self.assertEqual(result["issue_candidates"][0]["issue_type"], "canon_conflict")
            self.assertEqual(result["issue_candidates"][0]["target_asset_id"], "draft-1")

            candidate = canon_conflict_to_issue_candidate(result["issues"][0], result["input"])
            self.assertEqual(candidate["source_system"], "mkaos.canon_conflict")
            self.assertEqual(candidate["project_id"], "canon-p")


def _knowledge(storage: LocalStorage, project_id: str, concept: str, *, risk_level: str = "low", quality: float = 0.8, weight: float = 1.0) -> dict:
    return create_knowledge_card(
        storage,
        {
            "project_id": project_id,
            "concept_name": concept,
            "discipline": "制度",
            "knowledge_type": "conflict_mechanism",
            "core_explanation": f"{concept} 必须转化为行动成本。",
            "quality_score": quality,
            "weight": weight,
            "risk_level": risk_level,
        },
    )


if __name__ == "__main__":
    unittest.main()

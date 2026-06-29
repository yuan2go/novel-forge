from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.semantic_enhancement import analyze_story_semantics, create_semantic_extraction_report
from novel_forge.schemas import CharacterCard, DraftChapter, ForeshadowingThread, PowerScaleRule, WorldBible, validate_common_fields
from novel_forge.storage.local import LocalStorage


class SemanticEnhancementTests(unittest.TestCase):
    def test_semantic_story_review_detects_entities_threads_motivation_power_and_chapter_signals(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            metadata = {"project_id": "semantic-project", "workspace_path": "data/workspaces/semantic-project.json"}
            storage.write_asset(
                "worlds",
                WorldBible(
                    title="Clock World",
                    content={
                        "factions": [{"name": "Archive Guild"}],
                        "locations": [{"name": "North Tower"}],
                        "props": [{"name": "Memory Key"}],
                        "rules": ["epoch toll always consumes memory sacrifice"],
                    },
                    metadata=metadata,
                ),
            )
            storage.write_asset(
                "characters",
                CharacterCard(
                    title="Lin Qiao",
                    content={
                        "name": "林乔",
                        "aliases": ["钟城行者"],
                        "external_goal": "recover the Memory Key",
                        "internal_need": "pay the memory cost",
                        "motivation_chain": ["choice", "cost"],
                    },
                    metadata=metadata,
                ),
            )
            storage.write_asset(
                "continuity",
                ForeshadowingThread(
                    title="Silent bell",
                    content={"thread_id": "silent_bell", "setup": "silent bell", "payoff_plan": "founder reveal", "status": "planned"},
                    metadata=metadata,
                ),
            )
            storage.write_asset(
                "continuity",
                PowerScaleRule(
                    title="Bell power",
                    content={"scale_id": "bell_power", "constraints": ["epoch toll requires sacrifice"], "violation_checks": ["restore memory for free"]},
                    metadata=metadata,
                ),
            )
            draft = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Semantic draft",
                    content={
                        "chapter": 1,
                        "text": (
                            "为了 recover the Memory Key，林乔选择推开 North Tower 的门。"
                            "Archive Guild 逼她交出代价，但 Memory Key suddenly lets her restore memory for free without sacrifice。"
                            "silent bell 在墙后响起，秘密 founder reveal 还没有完全揭开。"
                        ),
                    },
                    metadata=metadata,
                ),
            )

            result = analyze_story_semantics(storage, target_path=draft, project_id="semantic-project", workspace_path="data/workspaces/semantic-project.json")

            self.assertEqual(result["version"], "semantic-enhancement-0.1.0")
            self.assertTrue(any(item["name"] == "Memory Key" for item in result["semantic_entities"]))
            self.assertTrue(result["foreshadowing_tracking"]["threads"])
            self.assertNotEqual(result["character_motivation_drift"]["status"], "blocked")
            self.assertEqual(result["power_scale_conflicts"]["status"], "blocked")
            self.assertGreater(result["chapter_pleasure_toxicity"]["pleasure_score"], 50)
            self.assertTrue(any(item.get("dimension") == "power_scale_conflict" for item in result["issues"]))
            self.assertIn(result["recommendation"], {"block", "revise"})

            report = create_semantic_extraction_report(
                storage,
                target_path=draft,
                project_id="semantic-project",
                workspace_path="data/workspaces/semantic-project.json",
                extractor_model={
                    "provider": "mock",
                    "model": "semantic-fixture",
                    "entities": [{"name": "Clock Founder", "entity_type": "character", "confidence": 0.82}],
                    "relations": [{"source": "Clock Founder", "target": "Archive Guild", "relation_type": "founded", "confidence": 0.86}],
                    "events": [{"source": "silent bell", "target": "founder reveal", "type": "foreshadowing_payoff", "confidence": 0.9}],
                },
            )
            asset = report["asset"]
            self.assertEqual(asset["type"], "semantic_extraction_report")
            self.assertEqual(validate_common_fields(asset), [])
            self.assertIn("model_assisted", asset["content"]["semantic_model"]["mode"])
            self.assertEqual(asset["content"]["model_assisted_extraction"]["status"], "validated")
            self.assertEqual(asset["content"]["summary"]["model_assisted_entity_count"], 1)
            self.assertEqual(asset["content"]["summary"]["model_assisted_relation_count"], 1)
            self.assertTrue(asset["content"]["semantic_entities"][0]["evidence_spans"])


if __name__ == "__main__":
    unittest.main()

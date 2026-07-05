from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.mkaos_lineage import apply_lineage_weight_governance, attribute_feedback_to_knowledge, build_lineage_index
from novel_forge.schemas import BaseAsset
from novel_forge.storage.local import LocalStorage


class MkaosFeedbackAttributionTests(unittest.TestCase):
    def test_feedback_attribution_maps_draft_back_to_knowledge(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            _seed_feedback_assets(storage)
            build_lineage_index(storage, project_id="feedback-p")

            result = attribute_feedback_to_knowledge(storage, {"project_id": "feedback-p", "feedback_id": "feedback-1", "generated_asset_id": "draft-1", "feedback_text": "节奏慢，设定太多"})

            self.assertEqual(result["feedback_id"], "feedback-1")
            self.assertIn("knowledge-1", result["knowledge_ids_used"])
            self.assertLess(result["weight_delta"], 0)
            self.assertFalse(result["source_isolation"]["raw_text_included"])

    def test_weight_governance_produces_dry_run_recommendation(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            _seed_feedback_assets(storage)
            build_lineage_index(storage, project_id="feedback-p")
            attribute_feedback_to_knowledge(storage, {"project_id": "feedback-p", "feedback_id": "feedback-1", "generated_asset_id": "draft-1", "feedback_text": "很好看，想追"})

            report = apply_lineage_weight_governance(storage, {"project_id": "feedback-p", "knowledge_id": "knowledge-1", "dry_run": True})

            self.assertTrue(report["dry_run"])
            self.assertEqual(report["recommendations"][0]["asset_id"], "knowledge-1")
            self.assertIn(report["recommendations"][0]["recommended_action"], {"keep", "increase_weight", "review"})


def _seed_feedback_assets(storage: LocalStorage) -> None:
    knowledge = BaseAsset(id="knowledge-1", type="knowledge_card", title="Knowledge", content={"concept_name": "机制"}, metadata={"project_id": "feedback-p"})
    context = BaseAsset(id="context-1", type="context_bundle", title="Context", content={"selected_knowledge_ids": ["knowledge-1"], "knowledge_pack_id": "pack-1"}, metadata={"project_id": "feedback-p"}, references=["knowledge-1"])
    draft = BaseAsset(id="draft-1", type="draft_chapter", title="Draft", source="context-1", content={"context_bundle_id": "context-1", "text": "safe"}, metadata={"project_id": "feedback-p"}, references=["context-1"])
    feedback = BaseAsset(id="feedback-1", type="reader_feedback", title="Feedback", source="draft-1", content={"artifact_id": "draft-1", "sentiment": "negative"}, metadata={"project_id": "feedback-p"}, references=["draft-1"])
    for category, asset in [("knowledge", knowledge), ("contexts", context), ("drafts", draft), ("feedback", feedback)]:
        storage.write_asset(category, asset)


if __name__ == "__main__":
    unittest.main()

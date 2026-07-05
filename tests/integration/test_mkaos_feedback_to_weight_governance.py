from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.mkaos_lineage import apply_lineage_weight_governance, attribute_feedback_to_knowledge, build_lineage_index
from novel_forge.schemas import BaseAsset
from novel_forge.storage.local import LocalStorage


class MkaosFeedbackToWeightGovernanceTests(unittest.TestCase):
    def test_feedback_attribution_flows_into_weight_governance_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            metadata = {"project_id": "fb-weight"}
            storage.write_asset("knowledge", BaseAsset(id="knowledge-1", type="knowledge_card", title="Knowledge", content={"concept_name": "节奏钩子"}, metadata=metadata))
            storage.write_asset("contexts", BaseAsset(id="context-1", type="context_bundle", title="Context", content={"selected_knowledge_ids": ["knowledge-1"]}, metadata=metadata, references=["knowledge-1"]))
            storage.write_asset("drafts", BaseAsset(id="draft-1", type="draft_chapter", title="Draft", source="context-1", content={"context_bundle_id": "context-1", "text": "safe"}, metadata=metadata, references=["context-1"]))
            build_lineage_index(storage, project_id="fb-weight")

            attribution = attribute_feedback_to_knowledge(storage, {"project_id": "fb-weight", "feedback_id": "feedback-1", "generated_asset_id": "draft-1", "feedback_text": "很好看，想追"})
            report = apply_lineage_weight_governance(storage, {"project_id": "fb-weight", "knowledge_id": "knowledge-1", "dry_run": True})

            self.assertIn("knowledge-1", attribution["knowledge_ids_used"])
            self.assertGreater(report["recommendations"][0]["weight_delta"], -0.01)
            self.assertTrue(report["dry_run"])


if __name__ == "__main__":
    unittest.main()

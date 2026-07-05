from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.mkaos_lineage import apply_lineage_weight_governance, attribute_feedback_to_knowledge, build_lineage_index
from novel_forge.storage.local import LocalStorage
from novel_forge.schemas import BaseAsset


class MkaosWeightGovernanceApplyPolicyTests(unittest.TestCase):
    def test_apply_updates_requires_explicit_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            _seed_feedback_assets(storage)
            build_lineage_index(storage, project_id="apply-p")

            with self.assertRaisesRegex(ValueError, "apply_policy=explicit"):
                apply_lineage_weight_governance(storage, {"project_id": "apply-p", "knowledge_id": "knowledge-1", "apply_updates": True})

    def test_explicit_apply_updates_weight_and_records_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            _seed_feedback_assets(storage)
            build_lineage_index(storage, project_id="apply-p")
            attribute_feedback_to_knowledge(storage, {"project_id": "apply-p", "feedback_id": "feedback-1", "generated_asset_id": "draft-1", "feedback_text": "很好看，想追"})
            build_lineage_index(storage, project_id="apply-p")

            report = apply_lineage_weight_governance(
                storage,
                {
                    "project_id": "apply-p",
                    "knowledge_id": "knowledge-1",
                    "apply_updates": True,
                    "apply_policy": "explicit",
                    "environment": "compat",
                    "bypass_reason": "unit-test-explicit-weight-governance",
                },
            )

            self.assertFalse(report["dry_run"])
            self.assertTrue(report["apply_updates"])
            self.assertGreaterEqual(report["applied_count"], 1)
            knowledge = storage.read_json(storage.data_dir("knowledge") / "knowledge-1.json")
            self.assertGreater(float(knowledge["content"]["weight"]), 1.0)
            mutations = [storage.read_json(path) for path in storage.list_json("runs") if storage.read_json(path).get("type") == "knowledge_mutation_audit"]
            self.assertTrue(mutations)


def _seed_feedback_assets(storage: LocalStorage) -> None:
    knowledge = BaseAsset(id="knowledge-1", type="knowledge_card", title="Knowledge", content={"concept_name": "机制", "weight": 1.0}, metadata={"project_id": "apply-p", "weight": 1.0})
    context = BaseAsset(id="context-1", type="context_bundle", title="Context", content={"selected_knowledge_ids": ["knowledge-1"], "knowledge_pack_id": "pack-1"}, metadata={"project_id": "apply-p"}, references=["knowledge-1"])
    draft = BaseAsset(id="draft-1", type="draft_chapter", title="Draft", source="context-1", content={"context_bundle_id": "context-1", "text": "safe"}, metadata={"project_id": "apply-p"}, references=["context-1"])
    feedback = BaseAsset(id="feedback-1", type="reader_feedback", title="Feedback", source="draft-1", content={"artifact_id": "draft-1", "sentiment": "positive"}, metadata={"project_id": "apply-p"}, references=["draft-1"])
    for category, asset in [("knowledge", knowledge), ("contexts", context), ("drafts", draft), ("feedback", feedback)]:
        storage.write_asset(category, asset)


if __name__ == "__main__":
    unittest.main()

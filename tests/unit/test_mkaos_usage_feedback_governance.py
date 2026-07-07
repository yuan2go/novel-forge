from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.materials import record_material_usage_event
from novel_forge.modules.mkaos import record_usage_event
from novel_forge.modules.mkaos_lineage import apply_lineage_weight_governance, build_lineage_index
from novel_forge.modules.source_intake import create_source_policy, create_source_refresh_report, create_source_risk_report, create_source_snapshot
from novel_forge.schemas import BaseAsset
from novel_forge.storage.local import LocalStorage


class MkaosUsageFeedbackGovernanceTests(unittest.TestCase):
    def test_usage_feedback_and_source_refresh_drive_reviewable_weight_governance(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            project_id = "usage-governance-p"
            source_ref = "operator-source"
            policy = create_source_policy(storage, {"source_ref": source_ref, "risk_tier": "R1", "project_id": project_id})
            risk = create_source_risk_report(storage, {"source_ref": source_ref, "source_policy_path": policy["path"], "project_id": project_id})
            snapshot = create_source_snapshot(
                storage,
                {
                    "source_ref": source_ref,
                    "source_type": "manual_note",
                    "content": "approved abstract source note",
                    "source_policy_path": policy["path"],
                    "risk_report_path": risk["path"],
                    "project_id": project_id,
                },
            )
            refresh = create_source_refresh_report(
                storage,
                {
                    "source_ref": source_ref,
                    "risk_report_path": risk["path"],
                    "snapshot_path": snapshot["path"],
                    "expected_content_hash": "changed-hash",
                    "project_id": project_id,
                },
            )
            source_eligibility = {
                "status": "passed",
                "generation_context_allowed": True,
                "evidence_only": False,
                "source_policy_refs": [policy["asset"]["id"]],
                "source_risk_report_refs": [risk["asset"]["id"]],
            }
            knowledge = BaseAsset(
                id="knowledge-usage-1",
                type="knowledge_card",
                title="Governed knowledge",
                content={"principles": ["use pressure as a choice cost"], "source_eligibility": source_eligibility},
                metadata={"project_id": project_id, "use_in_generation_rag": True},
            )
            material = BaseAsset(
                id="material-usage-1",
                type="material_card",
                title="Governed material",
                content={"usable_patterns": ["public pressure with visible cost"], "do_not_copy": ["source wording"], "source_eligibility": source_eligibility},
                metadata={"project_id": project_id, "use_in_generation_rag": True},
                references=["knowledge-usage-1"],
            )
            context = BaseAsset(
                id="context-usage-1",
                type="context_bundle",
                title="Context",
                content={"target_asset_id": "draft-usage-1", "selected_knowledge_ids": ["knowledge-usage-1"], "selected_assets": [{"asset_id": "material-usage-1"}]},
                metadata={"project_id": project_id},
                references=["knowledge-usage-1", "material-usage-1"],
            )
            for category, asset in [("knowledge", knowledge), ("materials", material), ("contexts", context)]:
                storage.write_asset(category, asset)
            record_usage_event(
                storage,
                {
                    "knowledge_id": "knowledge-usage-1",
                    "knowledge_pack_id": "context-usage-1",
                    "project_id": project_id,
                    "flow": "outline",
                    "target_artifact_id": "draft-usage-1",
                    "used_as": "context_bundle_selected_asset",
                },
            )
            record_material_usage_event(
                storage,
                {
                    "material_id": "material-usage-1",
                    "project_id": project_id,
                    "flow": "outline",
                    "target_artifact_id": "draft-usage-1",
                    "context_bundle_id": "context-usage-1",
                    "source_eligibility": source_eligibility,
                },
            )
            build_lineage_index(storage, project_id=project_id)

            report = apply_lineage_weight_governance(storage, {"project_id": project_id, "knowledge_id": "knowledge-usage-1", "dry_run": True})
            recommendation = report["recommendations"][0]

            self.assertEqual(refresh["asset"]["content"]["decision"], "needs_snapshot_refresh")
            self.assertTrue(report["dry_run"])
            self.assertFalse(report["governance_contract"]["usage_feedback_auto_applied"])
            self.assertFalse(report["governance_contract"]["source_refresh_auto_invalidated"])
            self.assertEqual(recommendation["asset_id"], "knowledge-usage-1")
            self.assertGreaterEqual(recommendation["usage_feedback_count"], 2)
            self.assertEqual(recommendation["source_refresh_signal_count"], 1)
            self.assertEqual(recommendation["recommended_action"], "review")
            self.assertTrue(recommendation["review_required_before_apply"])
            self.assertEqual(recommendation["invalidation_recommendations"][0]["downstream_action"], "invalidate_context_and_regenerate_after_review")


if __name__ == "__main__":
    unittest.main()

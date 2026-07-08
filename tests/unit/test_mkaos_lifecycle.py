from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.mkaos import apply_mkaos_asset_lifecycle, plan_mkaos_asset_lifecycle, rollback_mkaos_asset_lifecycle
from novel_forge.modules.permission_center import resolve_approval_request
from novel_forge.schemas import BaseAsset, KnowledgeCard, TemplateCard
from novel_forge.storage.local import LocalStorage


class MkaosLifecycleTests(unittest.TestCase):
    def test_candidate_approval_requires_approval_creates_card_and_rolls_back_without_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            candidate_path = storage.write_asset(
                "knowledge",
                BaseAsset(
                    id="candidate-life-1",
                    type="knowledge_card_candidate",
                    title="Candidate lifecycle",
                    source="source-chunk-1",
                    tags=["mkaos", "knowledge-candidate", "needs-review"],
                    content={
                        "concept_name": "代价选择机制",
                        "core_explanation": "角色在礼法压力下通过选择付出代价。",
                        "target_disciplines": ["historical_governance"],
                        "source_chunk_ids": [],
                        "evidence_refs": [],
                        "status": "needs_review",
                    },
                    metadata={"project_id": "mkaos-life-p", "asset_status": "needs_review", "use_in_generation_rag": False},
                    references=[],
                )
            )
            plan = plan_mkaos_asset_lifecycle(
                storage,
                {
                    "target_ref": str(candidate_path.relative_to(storage.root)),
                    "requested_state": "approved",
                    "project_id": "mkaos-life-p",
                    "reason": "approve safe abstraction",
                },
            )
            self.assertEqual(plan["status"], "planned")
            self.assertTrue(plan["valid_transition"])

            blocked = apply_mkaos_asset_lifecycle(storage, {"lifecycle_plan_path": plan["path"], "project_id": "mkaos-life-p"})
            self.assertEqual(blocked["status"], "approval_required")
            self.assertEqual(storage.read_json(candidate_path)["content"]["status"], "needs_review")

            approval_path = blocked["approval_request"]["path"]
            resolve_approval_request(storage, approval_path, {"decision": "approved", "actor": "unit-test", "reason": "approve lifecycle"})
            ready = apply_mkaos_asset_lifecycle(storage, {"lifecycle_plan_path": plan["path"], "approval_request_path": approval_path, "project_id": "mkaos-life-p"})
            self.assertEqual(ready["status"], "ready_for_confirm")
            self.assertEqual(storage.read_json(candidate_path)["content"]["status"], "needs_review")

            applied = apply_mkaos_asset_lifecycle(
                storage,
                {
                    "lifecycle_plan_path": plan["path"],
                    "approval_request_path": approval_path,
                    "confirm_apply": True,
                    "actor": "unit-test",
                    "project_id": "mkaos-life-p",
                },
            )
            candidate = storage.read_json(candidate_path)
            self.assertEqual(applied["status"], "applied")
            self.assertEqual(candidate["content"]["status"], "approved")
            self.assertFalse(candidate["metadata"]["use_in_generation_rag"])
            self.assertEqual(len(applied["created_assets"]), 1)
            created_path = applied["created_assets"][0]["path"]
            created = storage.read_json(storage.root / created_path)
            self.assertEqual(created["type"], "knowledge_card")
            self.assertTrue(created["metadata"]["mkaos_lifecycle_created_by_transition"])

            rollback_blocked = rollback_mkaos_asset_lifecycle(storage, {"rollback_plan_path": applied["rollback_plan"]["path"], "project_id": "mkaos-life-p"})
            self.assertEqual(rollback_blocked["status"], "approval_required")
            rollback_approval_path = rollback_blocked["approval_request"]["path"]
            resolve_approval_request(storage, rollback_approval_path, {"decision": "approved", "actor": "unit-test", "reason": "approve rollback"})
            rolled_back = rollback_mkaos_asset_lifecycle(
                storage,
                {
                    "rollback_plan_path": applied["rollback_plan"]["path"],
                    "approval_request_path": rollback_approval_path,
                    "confirm_rollback": True,
                    "actor": "unit-test",
                    "project_id": "mkaos-life-p",
                },
            )
            restored_candidate = storage.read_json(candidate_path)
            superseded_card = storage.read_json(storage.root / created_path)
            self.assertEqual(rolled_back["status"], "applied")
            self.assertTrue(rolled_back["rollback_applied"])
            self.assertEqual(restored_candidate["content"]["status"], "needs_review")
            self.assertEqual(superseded_card["metadata"]["asset_status"], "superseded_by_lifecycle_rollback")
            self.assertFalse(superseded_card["metadata"]["use_in_generation_rag"])

    def test_knowledge_card_quarantine_is_approval_gated_and_reversible(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            knowledge_path = storage.write_asset_auto(
                KnowledgeCard(
                    id="knowledge-life-1",
                    title="Knowledge lifecycle",
                    source="manual",
                    tags=["mkaos"],
                    content={"concept_name": "冲突机制", "principles": ["用资源不足制造行动代价。"], "principle": "用资源不足制造行动代价。", "status": "active"},
                    metadata={
                        "project_id": "mkaos-life-p2",
                        "asset_status": "active",
                        "use_in_generation_rag": True,
                        "copyright_boundary": "abstract structure only; no raw source expression",
                    },
                    references=[],
                )
            )
            plan = plan_mkaos_asset_lifecycle(storage, {"target_ref": str(knowledge_path.relative_to(storage.root)), "requested_state": "quarantined", "project_id": "mkaos-life-p2"})
            blocked = apply_mkaos_asset_lifecycle(storage, {"lifecycle_plan_path": plan["path"], "project_id": "mkaos-life-p2"})
            approval_path = blocked["approval_request"]["path"]
            resolve_approval_request(storage, approval_path, {"decision": "approved", "actor": "unit-test", "reason": "approve quarantine"})
            applied = apply_mkaos_asset_lifecycle(
                storage,
                {"lifecycle_plan_path": plan["path"], "approval_request_path": approval_path, "confirm_apply": True, "actor": "unit-test", "project_id": "mkaos-life-p2"},
            )
            quarantined = storage.read_json(knowledge_path)
            self.assertEqual(applied["status"], "applied")
            self.assertEqual(quarantined["content"]["status"], "quarantined")
            self.assertEqual(quarantined["metadata"]["asset_status"], "quarantined")
            self.assertFalse(quarantined["metadata"]["use_in_generation_rag"])

            rollback_blocked = rollback_mkaos_asset_lifecycle(storage, {"rollback_plan_path": applied["rollback_plan"]["path"], "project_id": "mkaos-life-p2"})
            rollback_approval_path = rollback_blocked["approval_request"]["path"]
            resolve_approval_request(storage, rollback_approval_path, {"decision": "approved", "actor": "unit-test", "reason": "approve rollback"})
            rolled_back = rollback_mkaos_asset_lifecycle(
                storage,
                {"rollback_plan_path": applied["rollback_plan"]["path"], "approval_request_path": rollback_approval_path, "confirm_rollback": True, "actor": "unit-test", "project_id": "mkaos-life-p2"},
            )
            restored = storage.read_json(knowledge_path)
            self.assertEqual(rolled_back["status"], "applied")
            self.assertEqual(restored["content"]["status"], "active")
            self.assertEqual(restored["metadata"]["asset_status"], "active")
            self.assertTrue(restored["metadata"]["use_in_generation_rag"])

    def test_template_lifecycle_quarantine_disables_template_and_rolls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            template_path = storage.write_asset_auto(
                TemplateCard(
                    id="template-life-1",
                    title="Template lifecycle",
                    source="mkaos",
                    tags=["mkaos", "template"],
                    content={
                        "template_name": "Choice cost template",
                        "template_type": "outline_template",
                        "structure": ["pressure", "choice", "cost"],
                        "usage_constraints": ["structure only"],
                        "enabled": True,
                    },
                    metadata={"project_id": "mkaos-life-p3", "asset_status": "active", "use_in_generation_rag": True},
                    references=[],
                )
            )
            plan = plan_mkaos_asset_lifecycle(storage, {"target_ref": str(template_path.relative_to(storage.root)), "requested_state": "quarantined", "project_id": "mkaos-life-p3"})
            blocked = apply_mkaos_asset_lifecycle(storage, {"lifecycle_plan_path": plan["path"], "project_id": "mkaos-life-p3"})
            approval_path = blocked["approval_request"]["path"]
            resolve_approval_request(storage, approval_path, {"decision": "approved", "actor": "unit-test", "reason": "approve template quarantine"})
            applied = apply_mkaos_asset_lifecycle(
                storage,
                {"lifecycle_plan_path": plan["path"], "approval_request_path": approval_path, "confirm_apply": True, "actor": "unit-test", "project_id": "mkaos-life-p3"},
            )
            quarantined = storage.read_json(template_path)
            self.assertEqual(applied["status"], "applied")
            self.assertEqual(quarantined["metadata"]["asset_status"], "quarantined")
            self.assertFalse(quarantined["metadata"]["use_in_generation_rag"])
            self.assertFalse(quarantined["content"]["enabled"])

            rollback_blocked = rollback_mkaos_asset_lifecycle(storage, {"rollback_plan_path": applied["rollback_plan"]["path"], "project_id": "mkaos-life-p3"})
            rollback_approval_path = rollback_blocked["approval_request"]["path"]
            resolve_approval_request(storage, rollback_approval_path, {"decision": "approved", "actor": "unit-test", "reason": "approve template rollback"})
            rollback_mkaos_asset_lifecycle(
                storage,
                {"rollback_plan_path": applied["rollback_plan"]["path"], "approval_request_path": rollback_approval_path, "confirm_rollback": True, "actor": "unit-test", "project_id": "mkaos-life-p3"},
            )
            restored = storage.read_json(template_path)
            self.assertEqual(restored["metadata"]["asset_status"], "active")
            self.assertTrue(restored["metadata"]["use_in_generation_rag"])
            self.assertTrue(restored["content"]["enabled"])


if __name__ == "__main__":
    unittest.main()

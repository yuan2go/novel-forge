from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.context_builder import build_flow_context_bundle
from novel_forge.modules.mkaos import (
    apply_context_governance_binding,
    build_knowledge_pack,
    create_knowledge_card,
    create_usage_binding,
    diff_mkaos_selector_governance,
    propose_context_governance_binding,
    refresh_mkaos_selector_governance,
    rollback_context_governance_binding,
)
from novel_forge.modules.permission_center import resolve_approval_request
from novel_forge.schemas import ChapterPlan
from novel_forge.storage.local import LocalStorage


class MkaosSelectorGovernanceTests(unittest.TestCase):
    def test_selector_refresh_applies_report_backed_weight_and_exclusion_without_mutating_card_weight(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            boosted = create_knowledge_card(
                storage,
                {
                    "concept_name": "Boosted pressure mechanism",
                    "core_explanation": "A concrete cost makes the protagonist choice sharper.",
                    "project_id": "selector-p",
                    "weight": 1.0,
                    "quality_score": 0.7,
                },
            )
            excluded = create_knowledge_card(
                storage,
                {
                    "concept_name": "Excluded stale mechanism",
                    "core_explanation": "This source-derived mechanism is stale and should not enter context.",
                    "project_id": "selector-p",
                    "weight": 1.0,
                    "quality_score": 0.9,
                },
            )
            create_usage_binding(storage, boosted["asset"]["id"], {"project_id": "selector-p", "flow": "prose", "usage_type": "optional", "input_role": "optional", "priority": 20})
            create_usage_binding(storage, excluded["asset"]["id"], {"project_id": "selector-p", "flow": "prose", "usage_type": "optional", "input_role": "optional", "priority": 1})

            boosted_path = storage.root / boosted["path"]
            boosted_data = storage.read_json(boosted_path)
            boosted_data["metadata"].update(
                {
                    "mkaos_governance_application_status": "applied_metadata_only",
                    "mkaos_governance_weight_delta": 2.5,
                    "mkaos_governance_action": "boost",
                    "mkaos_governance_report_path": "data/runs/weight-governance.json",
                    "mkaos_governance_approval_request_path": "data/runs/approval.json",
                }
            )
            storage.write_json(boosted_path, boosted_data)

            excluded_path = storage.root / excluded["path"]
            excluded_data = storage.read_json(excluded_path)
            excluded_data["metadata"].update(
                {
                    "mkaos_governance_application_status": "applied_metadata_only",
                    "mkaos_governance_action": "quarantine",
                    "use_in_generation_rag": False,
                    "mkaos_governance_report_path": "data/runs/stale-governance.json",
                    "mkaos_governance_approval_request_path": "data/runs/stale-approval.json",
                }
            )
            storage.write_json(excluded_path, excluded_data)

            report = refresh_mkaos_selector_governance(storage, {"project_id": "selector-p"})
            self.assertEqual(report["status"], "refreshed")
            self.assertEqual(report["adjustment_count"], 2)
            self.assertEqual(report["exclusion_count"], 1)
            report_content = report["asset"]["content"]
            self.assertEqual(report_content["adjustments"][boosted["asset"]["id"]]["effective_weight"], 3.5)
            self.assertIn(excluded["asset"]["id"], report_content["exclusions"])

            pack = build_knowledge_pack(
                storage,
                {
                    "project_id": "selector-p",
                    "flow": "prose",
                    "task_id": "selector-governance-test",
                    "task_goal": "protagonist pressure cost choice",
                    "selector_governance_report_path": report["path"],
                },
            )
            pack_content = pack["asset"]["content"]
            selected_by_id = {item["knowledge_id"]: item for item in pack_content["pack_items"]}
            rejected_by_id = {item["knowledge_id"]: item for item in pack_content["selector_rejections"]}

            self.assertIn(boosted["asset"]["id"], selected_by_id)
            boosted_decision = selected_by_id[boosted["asset"]["id"]]["selector_decision"]
            self.assertEqual(boosted_decision["weight"], 3.5)
            self.assertTrue(boosted_decision["weight_source"].startswith("selector_governance:"))
            self.assertEqual(boosted_decision["selector_governance_report_path"], report["path"])
            self.assertIn(excluded["asset"]["id"], rejected_by_id)
            self.assertEqual(rejected_by_id[excluded["asset"]["id"]]["reason"], "selector_governance_excluded")

            boosted_after = storage.read_json(boosted_path)
            self.assertEqual(boosted_after["content"]["weight"], 1.0)

    def test_context_builder_passes_selector_governance_report_to_mkaos_pack_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            plan_path = storage.write_asset(
                "chapter_plans",
                ChapterPlan(
                    title="Selector governed plan",
                    content={"chapter": 1, "objective": "show pressure", "beats": ["pressure", "choice"], "hook": "cost appears"},
                    metadata={"project_id": "selector-context-p"},
                ),
            )
            card = create_knowledge_card(
                storage,
                {
                    "concept_name": "Context selector boosted mechanism",
                    "core_explanation": "Governed knowledge should carry selector evidence into context.",
                    "project_id": "selector-context-p",
                    "weight": 1.0,
                },
            )
            create_usage_binding(storage, card["asset"]["id"], {"project_id": "selector-context-p", "flow": "prose", "usage_type": "optional", "input_role": "optional", "priority": 10})
            card_path = storage.root / card["path"]
            card_data = storage.read_json(card_path)
            card_data["metadata"].update(
                {
                    "mkaos_governance_application_status": "applied_metadata_only",
                    "mkaos_governance_weight_delta": 1.0,
                    "mkaos_governance_action": "boost",
                    "mkaos_governance_report_path": "data/runs/context-weight-governance.json",
                    "mkaos_governance_approval_request_path": "data/runs/context-approval.json",
                }
            )
            storage.write_json(card_path, card_data)
            report = refresh_mkaos_selector_governance(storage, {"project_id": "selector-context-p"})

            result = build_flow_context_bundle(
                storage,
                plan_path,
                flow="prose",
                project_id="selector-context-p",
                chapter_id="1",
                current_goal="show governed pressure",
                selector_governance_report_path=report["path"],
            )
            contract = result["knowledge_context_contract"]
            self.assertEqual(contract["selector_governance"]["report_path"], report["path"])
            self.assertIn(card["asset"]["id"], contract["selector_governance"]["weight_overrides"])

    def test_selector_governance_diff_compares_reports_and_existing_pack_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            card = create_knowledge_card(
                storage,
                {
                    "concept_name": "Diff governed mechanism",
                    "core_explanation": "Governance diff should show changed selector impact.",
                    "project_id": "selector-diff-p",
                    "weight": 1.0,
                },
            )
            create_usage_binding(storage, card["asset"]["id"], {"project_id": "selector-diff-p", "flow": "prose", "usage_type": "optional", "input_role": "optional", "priority": 10})
            card_path = storage.root / card["path"]
            card_data = storage.read_json(card_path)
            card_data["metadata"].update(
                {
                    "mkaos_governance_application_status": "applied_metadata_only",
                    "mkaos_governance_weight_delta": 1.0,
                    "mkaos_governance_action": "boost",
                }
            )
            storage.write_json(card_path, card_data)
            report_a = refresh_mkaos_selector_governance(storage, {"project_id": "selector-diff-p"})
            pack = build_knowledge_pack(
                storage,
                {
                    "project_id": "selector-diff-p",
                    "flow": "prose",
                    "task_id": "selector-diff-pack",
                    "task_goal": "diff governed selector",
                    "selector_governance_report_path": report_a["path"],
                },
            )

            card_data = storage.read_json(card_path)
            card_data["metadata"].update(
                {
                    "mkaos_governance_weight_delta": 3.0,
                    "mkaos_governance_action": "quarantine",
                    "use_in_generation_rag": False,
                }
            )
            storage.write_json(card_path, card_data)
            report_b = refresh_mkaos_selector_governance(storage, {"project_id": "selector-diff-p"})
            diff = diff_mkaos_selector_governance(
                storage,
                {
                    "project_id": "selector-diff-p",
                    "base_report_path": report_a["path"],
                    "compare_report_path": report_b["path"],
                    "knowledge_pack_path": pack["path"],
                },
            )
            content = diff["asset"]["content"]
            self.assertEqual(diff["status"], "diffed")
            self.assertEqual(diff["weight_changed_count"], 1)
            self.assertEqual(diff["exclusion_added_count"], 1)
            self.assertEqual(diff["selected_now_excluded_count"], 1)
            self.assertFalse(content["diff_contract"]["mutation_applied"])
            self.assertEqual(storage.read_json(card_path)["content"]["weight"], 1.0)

    def test_context_governance_binding_proposal_creates_diff_approval_and_agent_task_without_adoption(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            card = create_knowledge_card(
                storage,
                {
                    "concept_name": "Binding governed mechanism",
                    "core_explanation": "A selector governance binding proposal should be reviewable before context adoption.",
                    "project_id": "selector-binding-p",
                    "weight": 1.0,
                },
            )
            create_usage_binding(storage, card["asset"]["id"], {"project_id": "selector-binding-p", "flow": "prose", "usage_type": "optional", "input_role": "optional", "priority": 10})
            card_path = storage.root / card["path"]
            card_data = storage.read_json(card_path)
            card_data["metadata"].update(
                {
                    "mkaos_governance_application_status": "applied_metadata_only",
                    "mkaos_governance_weight_delta": 1.0,
                    "mkaos_governance_action": "boost",
                }
            )
            storage.write_json(card_path, card_data)
            report_a = refresh_mkaos_selector_governance(storage, {"project_id": "selector-binding-p"})
            pack = build_knowledge_pack(
                storage,
                {
                    "project_id": "selector-binding-p",
                    "flow": "prose",
                    "task_id": "selector-binding-pack",
                    "task_goal": "governance binding baseline",
                    "selector_governance_report_path": report_a["path"],
                },
            )

            card_data = storage.read_json(card_path)
            card_data["metadata"].update(
                {
                    "mkaos_governance_weight_delta": 2.0,
                    "mkaos_governance_action": "quarantine",
                    "use_in_generation_rag": False,
                }
            )
            storage.write_json(card_path, card_data)
            report_b = refresh_mkaos_selector_governance(storage, {"project_id": "selector-binding-p"})

            proposal = propose_context_governance_binding(
                storage,
                {
                    "project_id": "selector-binding-p",
                    "knowledge_pack_path": pack["path"],
                    "base_report_path": report_a["path"],
                    "environment": "production",
                    "reason": "review latest selector governance before context binding",
                },
            )
            content = proposal["asset"]["content"]
            self.assertEqual(proposal["status"], "proposed")
            self.assertEqual(proposal["asset"]["type"], "mkaos_selector_governance_binding_proposal")
            self.assertEqual(content["selector_governance_report_path"], report_b["path"])
            self.assertEqual(content["recommended_context_builder_payload_patch"]["selector_governance_report_path"], report_b["path"])
            self.assertTrue(content["diff_report_path"])
            self.assertTrue(content["approval_request_path"])
            self.assertTrue(content["agent_task_path"])
            self.assertFalse(content["binding_contract"]["adoption_applied"])
            self.assertFalse(content["binding_contract"]["context_build_executed"])

            approval_content = proposal["approval_request"]["asset"]["content"]
            self.assertEqual(approval_content["scope"], "context")
            self.assertEqual(approval_content["action"], "approve_selector_governance_binding")
            self.assertEqual(approval_content["status"], "pending")
            self.assertEqual(approval_content["target"]["target_path"], proposal["path"])
            self.assertTrue(approval_content["blocking"])

            task_content = proposal["agent_task"]["asset"]["content"]
            self.assertEqual(task_content["agent_type"], "Context Agent")
            self.assertEqual(task_content["operation"], "review-context-governance-binding")
            self.assertEqual(task_content["status"], "needs_review")
            self.assertFalse(task_content["evidence"]["dispatch_allowed"])
            self.assertFalse(task_content["evidence"]["adoption_applied"])
            self.assertEqual(task_content["evidence"]["recommended_context_builder_payload_patch"]["selector_governance_report_path"], report_b["path"])

            self.assertEqual(proposal["diff_report"]["asset"]["type"], "mkaos_selector_governance_diff_report")
            self.assertEqual(proposal["diff_report"]["selected_now_excluded_count"], 1)
            self.assertEqual(storage.read_json(card_path)["content"]["weight"], 1.0)

    def test_context_governance_binding_apply_and_rollback_are_approval_bound_and_payload_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            card = create_knowledge_card(
                storage,
                {
                    "concept_name": "Apply governed mechanism",
                    "core_explanation": "Approved selector governance binding should produce a payload patch, not a context bundle.",
                    "project_id": "selector-apply-p",
                    "weight": 1.0,
                },
            )
            create_usage_binding(storage, card["asset"]["id"], {"project_id": "selector-apply-p", "flow": "prose", "usage_type": "optional", "input_role": "optional", "priority": 10})
            card_path = storage.root / card["path"]
            card_data = storage.read_json(card_path)
            card_data["metadata"].update({"mkaos_governance_application_status": "applied_metadata_only", "mkaos_governance_weight_delta": 1.0, "mkaos_governance_action": "boost"})
            storage.write_json(card_path, card_data)
            report = refresh_mkaos_selector_governance(storage, {"project_id": "selector-apply-p"})
            proposal = propose_context_governance_binding(storage, {"project_id": "selector-apply-p", "selector_governance_report_path": report["path"], "environment": "production"})

            blocked = apply_context_governance_binding(storage, {"binding_proposal_path": proposal["path"], "project_id": "selector-apply-p"})
            self.assertEqual(blocked["status"], "approval_required")
            approval_path = proposal["asset"]["content"]["approval_request_path"]
            resolve_approval_request(storage, approval_path, {"decision": "approved", "actor": "unit-test", "reason": "approve binding"})

            ready = apply_context_governance_binding(storage, {"binding_proposal_path": proposal["path"], "approval_request_path": approval_path, "project_id": "selector-apply-p"})
            self.assertEqual(ready["status"], "ready_for_confirm")

            applied = apply_context_governance_binding(
                storage,
                {
                    "binding_proposal_path": proposal["path"],
                    "approval_request_path": approval_path,
                    "project_id": "selector-apply-p",
                    "confirm_apply": True,
                },
            )
            self.assertEqual(applied["status"], "applied")
            application_content = applied["application_report"]["asset"]["content"]
            self.assertEqual(applied["application_report"]["asset"]["type"], "mkaos_selector_governance_binding_application_report")
            self.assertEqual(application_content["context_builder_payload_patch"]["selector_governance_report_path"], report["path"])
            self.assertFalse(application_content["application_contract"]["context_build_executed"])
            self.assertFalse(application_content["application_contract"]["context_bundle_mutated"])
            self.assertEqual(applied["rollback_plan"]["asset"]["type"], "rollback_plan")
            self.assertEqual(applied["rollback_plan"]["asset"]["content"]["strategy"], "rollback_context_governance_binding_application")

            repeated = apply_context_governance_binding(storage, {"binding_proposal_path": proposal["path"], "approval_request_path": approval_path, "project_id": "selector-apply-p", "confirm_apply": True})
            self.assertEqual(repeated["status"], "already_applied")
            self.assertEqual(repeated["application_report"]["path"], applied["application_report"]["path"])

            task_path = proposal["asset"]["content"]["agent_task_path"]
            task_after_apply = storage.read_json(storage.root / task_path)
            self.assertEqual(task_after_apply["content"]["status"], "approved_pending_dispatch")
            self.assertFalse(task_after_apply["content"]["evidence"]["dispatch_allowed"])

            rollback_blocked = rollback_context_governance_binding(storage, {"rollback_plan_path": applied["rollback_plan"]["path"], "project_id": "selector-apply-p"})
            self.assertEqual(rollback_blocked["status"], "approval_required")
            rollback_approval_path = rollback_blocked["approval_request"]["path"]
            resolve_approval_request(storage, rollback_approval_path, {"decision": "approved", "actor": "unit-test", "reason": "approve binding rollback"})
            rollback_ready = rollback_context_governance_binding(
                storage,
                {"rollback_plan_path": applied["rollback_plan"]["path"], "approval_request_path": rollback_approval_path, "project_id": "selector-apply-p"},
            )
            self.assertEqual(rollback_ready["status"], "ready_for_confirm")
            rolled_back = rollback_context_governance_binding(
                storage,
                {
                    "rollback_plan_path": applied["rollback_plan"]["path"],
                    "approval_request_path": rollback_approval_path,
                    "project_id": "selector-apply-p",
                    "confirm_rollback": True,
                    "actor": "unit-test",
                },
            )
            self.assertEqual(rolled_back["status"], "applied")
            task_after_rollback = storage.read_json(storage.root / task_path)
            self.assertEqual(task_after_rollback["content"]["status"], "needs_review")
            application_after_rollback = storage.read_json(storage.root / applied["application_report"]["path"])
            self.assertEqual(application_after_rollback["content"]["status"], "rolled_back")
            proposal_after_rollback = storage.read_json(storage.root / proposal["path"])
            self.assertEqual(proposal_after_rollback["content"]["status"], "needs_approval")
            self.assertNotIn("binding_apply_result", proposal_after_rollback["content"])
            self.assertEqual(storage.read_json(card_path)["content"]["weight"], 1.0)


if __name__ == "__main__":
    unittest.main()

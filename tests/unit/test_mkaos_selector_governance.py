from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.context_builder import build_flow_context_bundle
from novel_forge.modules.mkaos import build_knowledge_pack, create_knowledge_card, create_usage_binding, diff_mkaos_selector_governance, refresh_mkaos_selector_governance
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


if __name__ == "__main__":
    unittest.main()

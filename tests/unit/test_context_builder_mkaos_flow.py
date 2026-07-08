from pathlib import Path
import os
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.model_adapters.mock import MockModelAdapter
from novel_forge.modules.chapter_plan import service as chapter_plan_service
from novel_forge.modules.context_builder import build_flow_context_bundle
from novel_forge.modules.drafting import service as drafting_service
from novel_forge.modules.outline import service as outline_service
from novel_forge.modules.review import service as review_service
from novel_forge.modules.mkaos import (
    apply_context_governance_binding,
    create_knowledge_card,
    create_usage_binding,
    propose_context_governance_binding,
    refresh_mkaos_selector_governance,
    rollback_context_governance_binding,
)
from novel_forge.modules.permission_center import resolve_approval_request
from novel_forge.schemas import CharacterCard, ChapterPlan
from novel_forge.storage.local import LocalStorage


class ContextBuilderMkaosFlowTests(unittest.TestCase):
    def setUp(self):
        self._previous_model_provider = os.environ.get("NOVEL_FORGE_MODEL_PROVIDER")
        os.environ["NOVEL_FORGE_MODEL_PROVIDER"] = "mock"

    def tearDown(self):
        if self._previous_model_provider is None:
            os.environ.pop("NOVEL_FORGE_MODEL_PROVIDER", None)
        else:
            os.environ["NOVEL_FORGE_MODEL_PROVIDER"] = self._previous_model_provider

    def test_build_flow_context_bundle_injects_mkaos_pack_without_raw_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            plan_path = storage.write_asset(
                "chapter_plans",
                ChapterPlan(
                    title="Chapter 1 plan",
                    content={
                        "chapter": 1,
                        "objective": "turn abstract land pressure into action",
                        "beats": ["find deed", "choose cost", "leave hook"],
                        "hook": "the deed is stamped twice",
                    },
                    metadata={"project_id": "ctx-mkaos"},
                ),
            )
            card = create_knowledge_card(
                storage,
                {
                    "project_id": "ctx-mkaos",
                    "concept_name": "制度压力",
                    "discipline": "制度",
                    "knowledge_type": "conflict_mechanism",
                    "core_explanation": "制度压力必须转成行动成本和可见物件。",
                },
            )
            create_usage_binding(storage, card["asset"]["id"], {"flow": "prose", "usage_type": "optional", "input_role": "optional", "priority": 10})

            result = build_flow_context_bundle(
                storage,
                plan_path,
                flow="prose",
                project_id="ctx-mkaos",
                chapter_id="1",
                current_goal="draft chapter 1",
                token_budget=3000,
            )
            content = result["asset"]["content"]

            self.assertEqual(content["context_builder_version"], "context-builder-v2-mkaos")
            self.assertEqual(content["task_type"], "prose")
            self.assertTrue(content["mkaos_pack"]["pack_items"])
            self.assertFalse(content["source_isolation"]["source_chunk_raw_text_allowed"])
            self.assertNotIn('"raw_text"', str(content["mkaos_pack"]))

    def test_build_flow_context_bundle_consumes_approved_selector_governance_binding_application(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            plan_path = storage.write_asset(
                "chapter_plans",
                ChapterPlan(
                    title="Governed Chapter plan",
                    content={"chapter": 1, "objective": "use governed knowledge", "beats": ["pressure"], "hook": "cost appears"},
                    metadata={"project_id": "ctx-binding"},
                ),
            )
            card = create_knowledge_card(
                storage,
                {
                    "project_id": "ctx-binding",
                    "concept_name": "governed pressure mechanism",
                    "core_explanation": "Governance-approved selector evidence should influence context only through an application report.",
                    "weight": 1.0,
                },
            )
            create_usage_binding(storage, card["asset"]["id"], {"project_id": "ctx-binding", "flow": "prose", "usage_type": "optional", "input_role": "optional", "priority": 10})
            card_path = storage.root / card["path"]
            card_data = storage.read_json(card_path)
            card_data["metadata"].update({"mkaos_governance_application_status": "applied_metadata_only", "mkaos_governance_weight_delta": 2.0, "mkaos_governance_action": "boost"})
            storage.write_json(card_path, card_data)
            report = refresh_mkaos_selector_governance(storage, {"project_id": "ctx-binding"})
            proposal = propose_context_governance_binding(storage, {"project_id": "ctx-binding", "selector_governance_report_path": report["path"]})
            approval_path = proposal["asset"]["content"]["approval_request_path"]
            resolve_approval_request(storage, approval_path, {"decision": "approved", "actor": "unit-test", "reason": "approve binding"})
            applied = apply_context_governance_binding(storage, {"binding_proposal_path": proposal["path"], "approval_request_path": approval_path, "confirm_apply": True, "project_id": "ctx-binding"})

            result = build_flow_context_bundle(
                storage,
                plan_path,
                flow="prose",
                project_id="ctx-binding",
                chapter_id="1",
                current_goal="draft governed chapter",
                selector_governance_binding_application_report_path=applied["application_report"]["path"],
            )
            content = result["asset"]["content"]
            binding = content["selector_governance_binding_application"]
            self.assertEqual(binding["application_report_path"], applied["application_report"]["path"])
            self.assertEqual(binding["selector_governance_report_path"], report["path"])
            self.assertEqual(content["knowledge_context_contract"]["selector_governance_binding_application"]["application_report_path"], applied["application_report"]["path"])
            self.assertEqual(content["knowledge_context_contract"]["selector_governance"]["report_path"], report["path"])
            selected_by_id = {item["knowledge_id"]: item for item in content["mkaos_pack"]["pack_items"]}
            self.assertEqual(selected_by_id[card["asset"]["id"]]["selector_decision"]["weight"], 3.0)
            self.assertIn(applied["application_report"]["path"], content["evidence_refs"])

    def test_production_context_builder_rejects_direct_selector_governance_report_without_binding_application(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            plan_path = storage.write_asset(
                "chapter_plans",
                ChapterPlan(
                    title="Direct report production plan",
                    content={"chapter": 1, "objective": "reject direct report", "beats": ["gate"], "hook": "gate holds"},
                    metadata={"project_id": "ctx-direct-block"},
                ),
            )
            card = create_knowledge_card(storage, {"project_id": "ctx-direct-block", "concept_name": "direct report", "core_explanation": "direct production report should be blocked"})
            create_usage_binding(storage, card["asset"]["id"], {"project_id": "ctx-direct-block", "flow": "prose", "usage_type": "optional", "input_role": "optional", "priority": 10})
            report = refresh_mkaos_selector_governance(storage, {"project_id": "ctx-direct-block"})

            with self.assertRaisesRegex(ValueError, "production selector governance binding requires"):
                build_flow_context_bundle(
                    storage,
                    plan_path,
                    flow="prose",
                    project_id="ctx-direct-block",
                    chapter_id="1",
                    current_goal="draft direct block",
                    environment="production",
                    os_envelope=_os_envelope("ctx-direct-block", "prose", "knowledge_pack", trace_id="trace-direct-block"),
                    selector_governance_report_path=report["path"],
                )

    def test_context_builder_rejects_rolled_back_selector_governance_binding_application(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            plan_path = storage.write_asset(
                "chapter_plans",
                ChapterPlan(
                    title="Rolled back binding plan",
                    content={"chapter": 1, "objective": "reject rolled back binding", "beats": ["gate"], "hook": "gate holds"},
                    metadata={"project_id": "ctx-rolled-back"},
                ),
            )
            card = create_knowledge_card(storage, {"project_id": "ctx-rolled-back", "concept_name": "rolled back", "core_explanation": "rolled back binding should not be consumed"})
            create_usage_binding(storage, card["asset"]["id"], {"project_id": "ctx-rolled-back", "flow": "prose", "usage_type": "optional", "input_role": "optional", "priority": 10})
            report = refresh_mkaos_selector_governance(storage, {"project_id": "ctx-rolled-back"})
            proposal = propose_context_governance_binding(storage, {"project_id": "ctx-rolled-back", "selector_governance_report_path": report["path"]})
            approval_path = proposal["asset"]["content"]["approval_request_path"]
            resolve_approval_request(storage, approval_path, {"decision": "approved", "actor": "unit-test", "reason": "approve binding"})
            applied = apply_context_governance_binding(storage, {"binding_proposal_path": proposal["path"], "approval_request_path": approval_path, "confirm_apply": True, "project_id": "ctx-rolled-back"})
            rollback_blocked = rollback_context_governance_binding(storage, {"rollback_plan_path": applied["rollback_plan"]["path"], "project_id": "ctx-rolled-back"})
            rollback_approval_path = rollback_blocked["approval_request"]["path"]
            resolve_approval_request(storage, rollback_approval_path, {"decision": "approved", "actor": "unit-test", "reason": "approve rollback"})
            rollback_context_governance_binding(
                storage,
                {
                    "rollback_plan_path": applied["rollback_plan"]["path"],
                    "approval_request_path": rollback_approval_path,
                    "confirm_rollback": True,
                    "project_id": "ctx-rolled-back",
                },
            )

            with self.assertRaisesRegex(ValueError, "binding application must be applied"):
                build_flow_context_bundle(
                    storage,
                    plan_path,
                    flow="prose",
                    project_id="ctx-rolled-back",
                    chapter_id="1",
                    current_goal="draft rolled back block",
                    selector_governance_binding_application_report_path=applied["application_report"]["path"],
                )

    def test_production_context_builder_requires_os_envelope_and_can_use_enforced_envelope(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            plan_path = storage.write_asset(
                "chapter_plans",
                ChapterPlan(
                    title="Production chapter plan",
                    content={"chapter": 1, "objective": "prove fail closed", "beats": ["gate"], "hook": "gate holds"},
                    metadata={"project_id": "ctx-prod"},
                ),
            )

            with self.assertRaisesRegex(ValueError, "OS envelope required"):
                build_flow_context_bundle(
                    storage,
                    plan_path,
                    flow="prose",
                    project_id="ctx-prod",
                    chapter_id="1",
                    current_goal="draft production chapter",
                    environment="production",
                )
            card = create_knowledge_card(
                storage,
                {
                    "project_id": "ctx-prod",
                    "concept_name": "生产门禁",
                    "core_explanation": "生产模式必须带可追溯知识包。",
                },
            )
            create_usage_binding(storage, card["asset"]["id"], {"flow": "prose", "usage_type": "optional", "input_role": "optional", "priority": 10})

            result = build_flow_context_bundle(
                storage,
                plan_path,
                flow="prose",
                project_id="ctx-prod",
                chapter_id="1",
                current_goal="draft production chapter",
                environment="production",
                os_envelope=_os_envelope("ctx-prod", "prose", "knowledge_pack", trace_id="trace-context-prod"),
            )
            pack_metadata = result["mkaos_pack"]["asset"]["metadata"]

            self.assertEqual(pack_metadata["os_envelope"]["status"], "enforced")
            self.assertEqual(pack_metadata["os_envelope"]["trace_id"], "trace-context-prod")

    def test_production_outline_fails_closed_on_mkaos_pack_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            character_path = storage.write_asset(
                "characters",
                CharacterCard(
                    title="Production protagonist",
                    content={"role": "主角", "external_goal": "prove production fail closed"},
                    metadata={"project_id": "outline-prod"},
                ),
            )

            with self.assertRaisesRegex(ValueError, "MKAOS pack build failed in production"):
                outline_service.generate_outline(
                    storage,
                    str(character_path),
                    model=MockModelAdapter(),
                    environment="production",
                )

            self.assertFalse([path for path in storage.list_json("outlines") if storage.read_json(path).get("type") == "outline"])

    def test_outline_chapter_prose_review_outputs_reference_context_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            character_path = storage.write_asset(
                "characters",
                CharacterCard(
                    title="林乔",
                    content={
                        "role": "主角",
                        "external_goal": "查清钟楼异常",
                        "internal_need": "承担公开真相的代价",
                        "motivation_chain": ["看到异常", "追踪证据", "保护证人"],
                    },
                    metadata={"project_id": "ctx-service"},
                ),
            )

            outline_path = outline_service.generate_outline(storage, str(character_path), model=MockModelAdapter())
            chapter_path = chapter_plan_service.generate_chapter_plan(storage, str(outline_path), model=MockModelAdapter(), chapter=1)
            draft_path = drafting_service.draft(storage, str(chapter_path), model=MockModelAdapter())
            review_path = review_service.review(storage, str(draft_path), model=MockModelAdapter())

            for path in [outline_path, chapter_path, draft_path, review_path]:
                asset = storage.read_asset(path)
                self.assertTrue(asset.metadata.get("context_builder_unified"), asset.type)
                bundle_path = asset.metadata.get("context_bundle_path")
                self.assertTrue(bundle_path, asset.type)
                bundle = storage.read_json(storage.root / bundle_path)
                self.assertEqual(bundle["type"], "context_bundle")
                self.assertIn("mkaos_pack", bundle["content"])
                self.assertFalse(bundle["content"]["source_isolation"]["source_chunk_raw_text_allowed"])


def _os_envelope(project_id: str, task_type: str, asset_type: str, *, trace_id: str) -> dict[str, object]:
    return {
        "envelope_id": f"env-{trace_id}",
        "project_id": project_id,
        "task_type": task_type,
        "asset_type": asset_type,
        "actor_type": "unit_test",
        "actor_id": "test",
        "source": "unit-test",
        "trace_id": trace_id,
        "source_policy": {
            "raw_source_text_allowed": False,
            "generation_rag_allowed": False,
            "source_chunk_raw_text_allowed": False,
        },
        "environment": "production",
    }


if __name__ == "__main__":
    unittest.main()

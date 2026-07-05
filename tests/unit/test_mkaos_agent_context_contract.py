from pathlib import Path
import os
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.model_adapters.mock import MockModelAdapter
from novel_forge.modules.publishing import create_publish_gate_report
from novel_forge.modules.chapter_plan import service as chapter_plan_service
from novel_forge.modules.context_builder import build_flow_context_bundle
from novel_forge.modules.drafting import service as drafting_service
from novel_forge.modules.longform_recap import run_longform_recap
from novel_forge.modules.longform_stability import create_longform_artifacts_for_draft
from novel_forge.modules.mkaos import create_knowledge_card, create_usage_binding
from novel_forge.modules.outline import service as outline_service
from novel_forge.modules.review import service as review_service
from novel_forge.schemas import CharacterCard, DraftChapter
from novel_forge.storage.local import LocalStorage


class MkaosAgentContextContractTests(unittest.TestCase):
    def setUp(self):
        self._previous_model_provider = os.environ.get("NOVEL_FORGE_MODEL_PROVIDER")
        os.environ["NOVEL_FORGE_MODEL_PROVIDER"] = "mock"

    def tearDown(self):
        if self._previous_model_provider is None:
            os.environ.pop("NOVEL_FORGE_MODEL_PROVIDER", None)
        else:
            os.environ["NOVEL_FORGE_MODEL_PROVIDER"] = self._previous_model_provider

    def test_draft_review_publish_and_recap_carry_knowledge_context_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            project_id = "local-system"
            _knowledge(storage, project_id)
            character_path = storage.write_asset(
                "characters",
                CharacterCard(
                    title="林乔",
                    content={"role": "主角", "external_goal": "证明知识上下文入口"},
                    metadata={"project_id": project_id},
                ),
            )

            outline_path = outline_service.generate_outline(storage, str(character_path), model=MockModelAdapter())
            chapter_path = chapter_plan_service.generate_chapter_plan(storage, str(outline_path), model=MockModelAdapter(), chapter=1)
            draft_path = drafting_service.draft(storage, str(chapter_path), model=MockModelAdapter())
            review_path = review_service.review(storage, str(draft_path), model=MockModelAdapter())
            publish_gate_path = create_publish_gate_report(storage, draft_path, human_override=True)

            draft = storage.read_asset(draft_path)
            review = storage.read_asset(review_path)
            gate = storage.read_asset(publish_gate_path)

            for asset in [draft, review, gate]:
                contract = asset.metadata.get("knowledge_context_contract")
                self.assert_contract(contract)
                self.assertEqual(asset.metadata.get("context_bundle_id"), contract["context_bundle_id"])
                self.assertEqual(asset.metadata.get("knowledge_pack_id"), contract["knowledge_pack_id"])

            for asset in [draft, review]:
                run = storage.read_json(storage.root / asset.metadata["agent_run_path"])
                self.assert_contract(run["metadata"].get("knowledge_context_contract"))
                self.assertEqual(run["metadata"]["context_bundle_id"], asset.metadata["context_bundle_id"])
                self.assertEqual(run["metadata"]["knowledge_pack_id"], asset.metadata["knowledge_pack_id"])

            publish_runs = [
                storage.read_json(path)
                for path in storage.list_json("runs")
                if storage.read_json(path).get("type") == "agent_run"
                and storage.read_json(path).get("content", {}).get("operation") == "create-publish-gate-report"
            ]
            self.assertTrue(publish_runs)
            self.assert_contract(publish_runs[0]["metadata"].get("knowledge_context_contract"))

            latest_path = _longform_fixture(storage, project_id=project_id)
            recap = run_longform_recap(storage, {"project_id": project_id, "chapter_count": 12})
            report = recap["asset"]
            self.assertTrue(latest_path)
            self.assert_contract(report["content"].get("knowledge_context_contract"))
            self.assert_contract(report["metadata"].get("knowledge_context_contract"))

    def test_operation_aliases_resolve_to_standard_mkaos_flows(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            project_id = "local-system"
            _knowledge(storage, project_id)
            character_path = storage.write_asset(
                "characters",
                CharacterCard(
                    title="许澜",
                    content={"role": "主角", "external_goal": "验证主链 operation flow"},
                    metadata={"project_id": project_id},
                ),
            )

            cases = {
                "draft": "prose",
                "chapter_plan": "chapter_outline",
                "publish_gate": "publish",
                "feedback_backflow": "feedback",
                "editor_patch": "revision",
            }
            for operation_flow, expected_mkaos_flow in cases.items():
                with self.subTest(operation_flow=operation_flow):
                    result = build_flow_context_bundle(
                        storage,
                        character_path,
                        flow=operation_flow,
                        project_id=project_id,
                        current_goal=f"validate {operation_flow}",
                        environment="compat",
                    )
                    contract = result["knowledge_context_contract"]
                    self.assert_contract(contract)
                    self.assertEqual(contract["mkaos_flow"], expected_mkaos_flow)
                    self.assertTrue(contract["selected_knowledge_ids"])
                    bundle = result["asset"]
                    self.assertEqual(bundle["content"]["task_type"], operation_flow)
                    self.assertEqual(bundle["content"]["mkaos_flow"], expected_mkaos_flow)

    def assert_contract(self, contract):
        self.assertIsInstance(contract, dict)
        for field in [
            "context_bundle_id",
            "knowledge_pack_id",
            "source_policy",
            "source_isolation",
            "mkaos_flow",
            "selected_knowledge_ids",
            "review_rules",
            "risk_warnings",
            "selector_policy_version",
        ]:
            self.assertIn(field, contract)
        self.assertTrue(contract["context_bundle_id"])
        self.assertTrue(contract["knowledge_pack_id"])
        self.assertFalse(contract["source_isolation"]["source_chunk_raw_text_allowed"])


def _knowledge(storage: LocalStorage, project_id: str) -> None:
    card = create_knowledge_card(
        storage,
        {
            "project_id": project_id,
            "concept_name": "知识上下文入口",
            "discipline": "叙事工程",
            "knowledge_type": "governance_rule",
            "core_explanation": "核心 Agent 必须通过 Context Builder 和 MKAOS pack 获取治理上下文。",
        },
    )
    for flow in ["prose", "review", "outline", "chapter_outline", "revision", "recap", "publish", "feedback"]:
        create_usage_binding(storage, card["asset"]["id"], {"flow": flow, "usage_type": "optional", "input_role": "governance_context", "priority": 10})


def _longform_fixture(storage: LocalStorage, *, project_id: str) -> Path:
    latest = None
    for chapter in range(1, 13):
        latest = storage.write_asset(
            "drafts",
            DraftChapter(
                title=f"Chapter {chapter}",
                content={
                    "chapter": chapter,
                    "text": f"第{chapter}章。林乔围绕知识上下文入口继续推进主线。",
                    "copyright_boundary": "project-owned contract fixture",
                },
                metadata={"project_id": project_id},
            ),
        )
        create_longform_artifacts_for_draft(storage, latest)
    assert latest is not None
    return latest


if __name__ == "__main__":
    unittest.main()

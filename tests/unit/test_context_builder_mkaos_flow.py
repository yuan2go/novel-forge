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
from novel_forge.modules.mkaos import create_knowledge_card, create_usage_binding
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


if __name__ == "__main__":
    unittest.main()

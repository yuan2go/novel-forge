from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.context_builder import build_flow_context_bundle
from novel_forge.modules.mkaos import create_usage_binding
from novel_forge.modules.mkaos_ingestion import create_creative_knowledge_card
from novel_forge.schemas import ChapterPlan
from novel_forge.storage.local import LocalStorage


class MkaosCreativeExtractionToContextBuilderTests(unittest.TestCase):
    def test_creative_card_enters_context_bundle_without_source_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            plan_path = storage.write_asset(
                "chapter_plans",
                ChapterPlan(
                    title="Chapter plan",
                    content={"chapter": 1, "objective": "use abstract knowledge", "beats": ["choice"], "hook": "cost"},
                    metadata={"project_id": "ctx-ciep"},
                ),
            )
            card = create_creative_knowledge_card(storage, {"project_id": "ctx-ciep", "concept_name": "礼法压力", "creative_principle": "礼法压力转成选择代价", "applicable_flows": ["prose"], "originality_boundary": "abstract only"})["asset"]
            create_usage_binding(storage, card["id"], {"flow": "prose", "usage_type": "optional", "input_role": "constraint", "priority": 5})

            bundle = build_flow_context_bundle(storage, plan_path, flow="prose", project_id="ctx-ciep", chapter_id="1", current_goal="draft chapter")
            text = str(bundle["asset"]["content"])

            self.assertIn(card["id"], text)
            self.assertNotIn("子曰", text)
            self.assertNotIn("译文原文", text)
            self.assertFalse(bundle["asset"]["content"]["source_isolation"]["source_chunk_raw_text_allowed"])


if __name__ == "__main__":
    unittest.main()

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.context_builder import build_flow_context_bundle
from novel_forge.modules.mkaos import create_usage_binding
from novel_forge.modules.mkaos_ingestion import create_creative_knowledge_card
from novel_forge.modules.mkaos_production_gate import list_gate_reports
from novel_forge.schemas import ChapterPlan
from novel_forge.storage.local import LocalStorage


class MkaosGateContextBuilderAutoTests(unittest.TestCase):
    def test_context_builder_automatically_writes_mkaos_gate_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            plan_path = storage.write_asset(
                "chapter_plans",
                ChapterPlan(
                    title="Plan",
                    content={"chapter": 1, "objective": "prove gate", "beats": ["choice"], "hook": "cost"},
                    metadata={"project_id": "gate-context"},
                ),
            )
            card = create_creative_knowledge_card(storage, {"project_id": "gate-context", "concept_name": "选择压力", "creative_principle": "转成行动代价", "applicable_flows": ["prose"], "originality_boundary": "abstract only"})["asset"]
            create_usage_binding(storage, card["id"], {"flow": "prose", "usage_type": "optional", "input_role": "constraint", "priority": 10})

            result = build_flow_context_bundle(storage, plan_path, flow="prose", project_id="gate-context", chapter_id="1", current_goal="draft")

            self.assertIn("mkaos_production_gate", result["asset"]["content"])
            self.assertTrue(result["asset"]["content"]["mkaos_production_gate"]["gate_report_path"])
            self.assertTrue(list_gate_reports(storage, project_id="gate-context"))


if __name__ == "__main__":
    unittest.main()

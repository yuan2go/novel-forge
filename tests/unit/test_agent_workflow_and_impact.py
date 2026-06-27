from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.agent_runs import (
    ensure_agent_contract,
    list_agent_events,
    list_agent_runs,
    start_agent_run,
    update_agent_run_status,
)
from novel_forge.modules.change_impact import create_change_impact_report
from novel_forge.modules.workflow_nodes import list_node_runs, record_node_run
from novel_forge.schemas import ChapterPlan, DecompositionReport, DraftChapter, Outline, SourceDocument
from novel_forge.storage.local import LocalStorage


class AgentWorkflowImpactTests(unittest.TestCase):
    def test_node_run_agent_run_and_change_impact_are_persisted_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            source_path = storage.write_asset(
                "raw",
                SourceDocument(
                    title="Source",
                    source="fixture.txt",
                    content={"text": "fixture"},
                    metadata={
                        "rights": {
                            "authorization": "test_fixture",
                            "copyright_boundary": "test fixture",
                            "allow_downstream_generation": True,
                        }
                    },
                ),
            )
            output_path = storage.write_asset(
                "decompositions",
                DecompositionReport(
                    title="Decomposition",
                    source=storage.read_asset(source_path).id,
                    content={
                        "summary": "abstract fixture",
                        "commercial_patterns": [],
                        "narrative_patterns": [],
                        "character_mechanisms": [],
                        "conflict_patterns": [],
                        "emotion_curve": [],
                        "hook_patterns": [],
                    },
                    metadata={"copyright_boundary": "abstract structure only"},
                    references=[storage.read_asset(source_path).id],
                ),
            )

            node = record_node_run(
                storage,
                run_id="run-1",
                node_id="decompose",
                node_type="analysis",
                operation="decompose",
                status="succeeded",
                input_assets=[source_path],
                output_assets=[output_path],
            )
            self.assertEqual(storage.read_asset(node["path"]).type, "node_run")
            self.assertEqual(list_node_runs(storage, run_id="run-1")[0]["operation"], "decompose")

            contract = ensure_agent_contract(
                storage,
                skill="hot-novel-deconstruction",
                operation="hot_novel_deconstruction",
                input_types=["source_document"],
                output_types=["decomposition_report"],
            )
            run = start_agent_run(
                storage,
                skill="hot-novel-deconstruction",
                operation="hot_novel_deconstruction",
                input_assets=[source_path],
                status="waiting_human",
                contract_path=contract["path"],
            )
            self.assertEqual(storage.read_asset(run["path"]).type, "agent_run")
            self.assertEqual(list_agent_runs(storage)[0]["status"], "waiting_human")
            updated = update_agent_run_status(storage, run["path"], status="succeeded", output_assets=[output_path])
            self.assertEqual(updated["asset"]["content"]["status"], "succeeded")
            self.assertTrue(list_agent_events(storage, agent_run_path=run["path"]))

            outline_path = storage.write_asset(
                "outlines",
                Outline(title="Outline", content={"acts": [{"act": 1, "goal": "open"}]}),
            )
            outline = storage.read_asset(outline_path)
            plan_path = storage.write_asset(
                "chapter_plans",
                ChapterPlan(
                    title="Plan",
                    source=outline.id,
                    content={"chapter": 1, "objective": "open", "beats": ["beat"], "hook": "hook"},
                    references=[outline.id, str(outline_path.relative_to(storage.root))],
                ),
            )
            plan = storage.read_asset(plan_path)
            draft_path = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Draft",
                    source=plan.id,
                    content={"chapter": 1, "text": "原创测试章节。", "copyright_boundary": "test fixture"},
                    references=[plan.id, str(plan_path.relative_to(storage.root))],
                ),
            )
            self.assertTrue(draft_path.exists())

            impact = create_change_impact_report(storage, outline_path)
            impacted_types = {item["type"] for item in impact["asset"]["content"]["impacted_assets"]}
            self.assertIn("chapter_plan", impacted_types)
            self.assertIn("draft_chapter", impacted_types)
            self.assertEqual(storage.read_asset(impact["path"]).type, "change_impact_report")


if __name__ == "__main__":
    unittest.main()
